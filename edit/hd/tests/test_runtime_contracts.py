import importlib
import copy
import json
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest


class RuntimeTreeTests(unittest.TestCase):
    def test_declared_library_bytes_are_verified(self):
        import hashlib
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            contracts = self.contracts()
            for name in ("node", "ffmpeg", "ffprobe"):
                path = root / name
                path.write_bytes(b"tool")
                path.chmod(0o700)
                contracts[name].update(path=str(path), sha256=hashlib.sha256(b"tool").hexdigest())
            for name in ("playwright", "browser"):
                folder = root / name
                folder.mkdir()
                entry = folder / "entry"
                entry.write_bytes(b"entry")
                entry.chmod(0o700)
                contracts[name].update(path=str(entry), roots=[{"path": str(folder), "sha256": module.tree_identity(folder)["sha256"]}])
            library = root / "libcodec.dylib"
            library.write_bytes(b"library")
            library.chmod(0o600)
            contracts["ffmpeg"]["libraries"] = [{"path": str(library), "sha256": hashlib.sha256(b"library").hexdigest()}]
            self.assertEqual(module.verify_contracts(contracts), contracts)
            alias = root / "codec-current"
            alias.symlink_to(library)
            contracts["ffmpeg"]["libraries"][0]["load_paths"] = [str(alias)]
            self.assertEqual(module.verify_contracts(contracts), contracts)
            contracts["ffmpeg"]["library_discovery"] = "mach_o_static_v1"
            declared = copy.deepcopy(contracts["ffmpeg"]["libraries"])
            with patch.object(module, "discover_macho_libraries", return_value=declared) as discover:
                self.assertEqual(module.verify_contracts(contracts), contracts)
                discover.assert_called_once_with(root / "ffmpeg")
            with patch.object(module, "discover_macho_libraries", return_value=[]):
                with self.assertRaisesRegex(ValueError, "identity"):
                    module.verify_contracts(contracts)
            def replace_entry_during_discovery(path):
                path.write_bytes(b"replacement")
                return declared
            with patch.object(module, "discover_macho_libraries", side_effect=replace_entry_during_discovery):
                with self.assertRaisesRegex(ValueError, "identity"):
                    module.verify_contracts(contracts)
            (root / "ffmpeg").write_bytes(b"tool")
            del contracts["ffmpeg"]["library_discovery"]
            replacement = root / "codec-other"
            replacement.write_bytes(b"library")
            alias.unlink()
            alias.symlink_to(replacement)
            with self.assertRaisesRegex(ValueError, "identity"):
                module.verify_contracts(contracts)
            alias.unlink()
            alias.symlink_to(library)
            library.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "identity"):
                module.verify_contracts(contracts)
            library.unlink()
            with self.assertRaisesRegex(ValueError, "identity"):
                module.verify_contracts(contracts)
            library.symlink_to(root / "node")
            with self.assertRaisesRegex(ValueError, "identity"):
                module.verify_contracts(contracts)

    def test_library_declarations_reject_ambiguous_paths_and_hashes(self):
        module = self.module()
        record = {"path": "/libs/lib.dylib", "sha256": "a" * 64}
        value = self.contracts()
        value["ffmpeg"]["libraries"] = [record]
        self.assertEqual(module.normalize_contracts(value), value)
        for libraries in ([record, record], [{"path": "relative", "sha256": "a" * 64}],
                          [{"path": "/libs/lib.dylib", "sha256": "bad"}],
                          [{**record, "extra": True}], "invalid"):
            invalid = copy.deepcopy(value)
            invalid["ffmpeg"]["libraries"] = libraries
            with self.assertRaises(ValueError):
                module.normalize_contracts(invalid)
        for paths in ([], ["relative"], ["/alias", "/alias"], "invalid"):
            invalid = copy.deepcopy(value)
            invalid["ffmpeg"]["libraries"][0]["load_paths"] = paths
            with self.assertRaises(ValueError):
                module.normalize_contracts(invalid)

    def test_total_load_paths_are_bounded_per_tool(self):
        module = self.module()
        value = self.contracts()
        value["ffmpeg"]["libraries"] = [
            {"path": "/libs/one", "sha256": "a" * 64, "load_paths": ["/alias/a" + str(i) for i in range(256)]},
            {"path": "/libs/two", "sha256": "b" * 64, "load_paths": ["/alias/b" + str(i) for i in range(256)]}]
        self.assertEqual(module.normalize_contracts(value), value)
        value["ffmpeg"]["libraries"][1]["load_paths"].append("/alias/extra")
        with self.assertRaises(ValueError):
            module.normalize_contracts(value)

    def test_static_discovery_requires_explicit_complete_shape(self):
        module = self.module()
        value = self.contracts()
        value["node"].update(library_discovery="mach_o_static_v1", libraries=[])
        self.assertEqual(module.normalize_contracts(value), value)
        for change in ({"library_discovery": "unknown"}, {"libraries": [{"path": "/lib/a", "sha256": "a" * 64}]}):
            invalid = copy.deepcopy(value)
            invalid["node"].update(change)
            with self.assertRaises(ValueError):
                module.normalize_contracts(invalid)
        del value["node"]["libraries"]
        with self.assertRaises(ValueError):
            module.normalize_contracts(value)

    def test_verify_reads_actual_dependencies(self):
        import hashlib
        module = self.module()
        self.assertTrue(callable(getattr(module, "verify_contracts", None)), "runtime verification missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            contracts = self.contracts()
            for name in ("node", "ffmpeg", "ffprobe"):
                path = root / name
                path.write_bytes(b"tool")
                path.chmod(0o700)
                contracts[name].update(path=str(path), sha256=hashlib.sha256(b"tool").hexdigest())
            for name in ("playwright", "browser"):
                folder = root / name
                folder.mkdir()
                (folder / "entry").write_bytes(b"entry")
                (folder / "entry").chmod(0o700)
                (folder / "resource").write_bytes(b"original")
                contracts[name].update(path=str(folder / "entry"), roots=[{"path":str(folder),"sha256":module.tree_identity(folder)["sha256"]}])
            self.assertEqual(module.verify_contracts(contracts), contracts)
            original_access = module.os.access
            def change_mode_after_access(path, mode):
                allowed = original_access(path, mode)
                if Path(path) == root / "node":
                    Path(path).chmod(0o600)
                return allowed
            with patch.object(module.os, "access", side_effect=change_mode_after_access):
                with self.assertRaisesRegex(ValueError, "identity"):
                    module.verify_contracts(contracts)
            (root / "node").chmod(0o700)
            (root / "browser" / "resource").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "identity"):
                module.verify_contracts(contracts)

    def test_executor_records_contracts_without_changing_legacy_evidence(self):
        from edit.hd.tools import broll_component_executor as executor
        self.assertIn("runtime_contracts", executor.ReferenceProcessAdapter.__dataclass_fields__)
        adapter = executor.ReferenceProcessAdapter(adapter_id="test", dependency_id="test",
            approved_executor="reference_adapter", dependency_root=Path("/runtime"), entrypoint="entry.py",
            entrypoint_sha256="a"*64, producer_version="1", primary_renderer="SemanticState",
            renderer_version="1", artifact_media_type="video", launcher=Path("/python"),
            launcher_sha256="b"*64, argv_template=("{launcher}","{entrypoint}","--brief","{brief_path}","--output","{output_path}"),
            brief_loader=lambda *_: b"{}", self_contained_wrapper=True)
        self.assertNotIn("runtime_contracts", executor._base_process_evidence(adapter))
        native = replace(adapter, dependency_id="hd-talking-head-semantic-state")
        with patch.object(executor, "_common_code_binding_valid", return_value=False) as common:
            with self.assertRaises(executor.BrollComponentExecutionError):
                executor._validate_code_adapter(native, {"dependency_id": native.dependency_id})
            common.assert_not_called()
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor._base_process_evidence(replace(adapter, runtime_contracts={}))
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
        contracts = self.contracts()
        adapter = replace(adapter, runtime_contracts=contracts)
        probe = executor.ArtifactProbe(probe_id="test", probe_version="1", probe=lambda *_: {})
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor._adapter_binding_record(adapter, probe)
        argv = list(adapter.argv_template)
        for key, contract in contracts.items():
            argv.extend(["--" + key, contract["path"]])
        argv.extend(["--runtime-contracts", json.dumps(contracts)])
        adapter = replace(adapter, argv_template=tuple(argv))
        binding = executor._adapter_binding_record(adapter, probe)
        self.assertEqual(binding["runtime_contracts"], contracts)
        evidence = executor._base_process_evidence(adapter)
        self.assertEqual(evidence["runtime_contracts"], contracts)
        wrong_path = list(adapter.argv_template)
        wrong_path[wrong_path.index("--node") + 1] = "/wrong-node"
        duplicate_json = list(adapter.argv_template)
        duplicate_json[-1] = '{"node":{},"node":{}}'
        for arguments in (tuple(wrong_path), tuple(duplicate_json), adapter.argv_template + ("--runtime-contracts", "{}")):
            with self.assertRaises(executor.BrollComponentExecutionError):
                executor._base_process_evidence(replace(adapter, argv_template=arguments))
        evidence["runtime_contracts"]["node"]["path"] = "/changed"
        self.assertEqual(contracts["node"]["path"], "/tools/node")
        contracts["node"]["version"] = "changed"
        for check in (lambda: executor._adapter_binding_record(adapter, probe), lambda: executor._base_process_evidence(adapter)):
            with self.assertRaises(executor.BrollComponentExecutionError):
                check()

    def contracts(self):
        value = {name: {"kind":"file_snapshot","path":"/tools/"+name,"sha256":"a"*64,"version":"1"}
                 for name in ("node","ffmpeg","ffprobe")}
        for name in ("playwright","browser"):
            value[name] = {"kind":"directory_tree","path":"/runtime/"+name+"/entry","version":"1",
                           "roots":[{"path":"/runtime/"+name,"sha256":"b"*64}]}
        return value

    def module(self):
        name = "edit.hd.tools.runtime_contracts"
        self.assertIsNotNone(importlib.util.find_spec(name), "runtime contracts missing")
        return importlib.import_module(name)

    def test_internal_file_change_is_detected_without_entry_change(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "index.js").write_text("entry")
            (root / "lib").mkdir()
            internal = root / "lib" / "engine.js"
            internal.write_text("version one")
            before = module.tree_identity(root)
            self.assertEqual(before, module.tree_identity(root))
            internal.write_text("version two")
            self.assertNotEqual(before["sha256"], module.tree_identity(root)["sha256"])
            self.assertEqual((root / "index.js").read_text(), "entry")

    def test_internal_symlink_allowed_but_escape_rejected(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / "runtime"
            root.mkdir()
            (root / "real").write_text("source")
            link = root / "current"
            link.symlink_to("real")
            self.assertEqual(module.tree_identity(root)["file_count"], 1)
            link.unlink()
            (parent / "outside").write_text("outside")
            link.symlink_to("../outside")
            with self.assertRaisesRegex(ValueError, "escape"):
                module.tree_identity(root)

    def test_empty_directory_and_executable_permission_affect_identity(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            program = root / "program"
            program.write_text("code")
            before = module.tree_identity(root)
            program.chmod(0o700)
            after = module.tree_identity(root)
            self.assertNotEqual(before["sha256"], after["sha256"])
            (root / "resources").mkdir()
            self.assertNotEqual(after["sha256"], module.tree_identity(root)["sha256"])

    def test_contract_schema_is_complete_and_returns_detached_values(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, "normalize_contracts", None)), "runtime schema missing")
        contracts = {name: {"kind": "file_snapshot", "path": "/tools/" + name,
                           "sha256": "a" * 64, "version": "1"}
                     for name in ("node", "ffmpeg", "ffprobe")}
        for name in ("playwright", "browser"):
            contracts[name] = {"kind": "directory_tree", "path": "/runtime/" + name + "/entry",
                "version": "1", "roots": [{"path": "/runtime/" + name, "sha256": "b" * 64}]}
        normalized = module.normalize_contracts(contracts)
        self.assertEqual(normalized, contracts)
        normalized["node"]["path"] = "/changed"
        self.assertEqual(contracts["node"]["path"], "/tools/node")
        invalid = []
        missing = copy.deepcopy(contracts)
        del missing["browser"]
        invalid.append(missing)
        for field, value in (("path", "relative"), ("sha256", "x" * 64), ("extra", True)):
            changed = copy.deepcopy(contracts)
            changed["node"][field] = value
            invalid.append(changed)
        outside = copy.deepcopy(contracts)
        outside["browser"]["path"] = "/outside/entry"
        invalid.append(outside)
        for value in invalid:
            with self.assertRaises(ValueError):
                module.normalize_contracts(value)

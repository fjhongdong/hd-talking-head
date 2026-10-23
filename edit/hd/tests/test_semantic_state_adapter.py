import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from edit.hd.tests.test_semantic_state_renderer import brief


class SemanticAdapterTests(unittest.TestCase):
    def test_loader_rechecks_dependencies_plan_and_request(self):
        name = "edit.hd.tools.semantic_state_adapter"
        self.assertIsNotNone(importlib.util.find_spec(name), "semantic adapter missing")
        module = importlib.import_module(name)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths, hashes = {}, {}
            for key in ("python", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
                path = root / key
                path.write_text(key)
                path.chmod(0o700)
                paths[key] = path
                hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            entry = root / "bundle.py"
            entry.write_text("frozen")
            value = brief()
            payload = json.dumps(value).encode()
            report = {"plan": value["motion"], "execution_status": "planning_only"}
            request = {"semantic_family": "replacement", "information_units": 2,
                       "numeric_values": [], "numeric_scale": "not_applicable"}
            component = {"template_id": "hd-talking-head/semantic-state-replacement",
                "invocation_record": {"semantic_motion": report, "template_request": request},
                "render_window": {"start_frame": 12, "end_frame": 132},
                "artifact_contract": {"width":1080,"height":1920,"fps":24,"alpha":False}}
            recipe = {"canvas": {"width":1080,"height":1920,"fps":24}}
            contracts = {key: {"kind": "file_snapshot", "path": str(paths[key]), "sha256": hashes[key],
                "version": "test", "library_discovery": "mach_o_static_v1", "libraries": []}
                for key in ("node", "ffmpeg", "ffprobe")}
            for key in ("playwright", "browser"):
                contracts[key] = {"kind": "directory_tree", "path": str(paths[key]), "version": "test",
                    "roots": [{"path": str(root), "sha256": "a" * 64}]}
            self.assertTrue(callable(getattr(module, "verify_contracts", None)), "adapter runtime verification missing")
            verification = patch.object(module, "verify_contracts", side_effect=lambda value: value)
            verification.start()
            self.addCleanup(verification.stop)
            adapter = module.create_adapter(dependency_root=root, entrypoint="bundle.py",
                entrypoint_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),
                tools=paths, tool_hashes=hashes, brief_loader=lambda *_: payload, runtime_contracts=contracts)
            self.assertEqual(adapter.runtime_contracts, contracts)
            encoded = adapter.argv_template[adapter.argv_template.index("--runtime-contracts") + 1]
            self.assertEqual(json.loads(encoded), contracts)
            with patch.object(module, "bind_brief", return_value={"semantic_motion": report, "template_request": request}):
                self.assertEqual(adapter.brief_loader("job", recipe, component), payload)
                adapter.runtime_contracts["node"]["version"] = "changed"
                with self.assertRaisesRegex(ValueError, "contract"):
                    adapter.brief_loader("job", recipe, component)
                adapter.runtime_contracts["node"]["version"] = "test"
                for key in ("semantic_motion", "template_request"):
                    invalid = copy.deepcopy(component)
                    invalid["invocation_record"][key] = {}
                    with self.assertRaises(ValueError):
                        adapter.brief_loader("job", recipe, invalid)
                paths["node"].write_text("changed")
                with self.assertRaisesRegex(ValueError, "dependency"):
                    adapter.brief_loader("job", recipe, component)
            self.assertEqual(adapter.primary_renderer, "SemanticState")

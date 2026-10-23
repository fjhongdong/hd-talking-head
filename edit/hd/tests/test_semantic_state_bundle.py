import base64
import hashlib
import importlib
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SemanticBundleTests(unittest.TestCase):
    def test_builder_cli_publishes_exact_bundle_without_overwrite(self):
        builder = Path(__file__).resolve().parents[1] / 'tools/semantic_state_bundle.py'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / 'bundle.py'
            command = [sys.executable, str(builder), '--output', str(output)]
            first = subprocess.run(command, cwd='/', capture_output=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            from edit.hd.tools.semantic_state_bundle import build_bundle
            self.assertEqual(output.read_bytes(), build_bundle())
            output.write_bytes(b'preserve')
            second = subprocess.run(command, cwd='/', capture_output=True, timeout=10)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), b'preserve')

    def test_contract_json_rejects_duplicate_keys_and_oversize(self):
        from edit.hd.tools.semantic_state_bundle import build_bundle
        namespace = {"__name__": "bundle_test"}
        exec(compile(build_bundle(), "frozen-semantic.py", "exec"), namespace)
        parse = namespace["parse_runtime_contracts"]
        self.assertEqual(parse('{"node":{}}'), {"node": {}})
        for payload in ('{"node":{},"node":{}}', '{"node":{"path":"a","path":"b"}}', '"' + '字' * 22000 + '"'):
            with self.assertRaises(ValueError):
                parse(payload)

    def test_bundle_freezes_complete_semantic_sources(self):
        name = "edit.hd.tools.semantic_state_bundle"
        self.assertIsNotNone(importlib.util.find_spec(name), "semantic bundle missing")
        module = importlib.import_module(name)
        payload = module.build_bundle()
        namespace = {"__name__": "bundle_test"}
        exec(compile(payload, "frozen-semantic.py", "exec"), namespace)
        root = Path(module.__file__).parent
        expected = {"semantic_state_cli.py", "semantic_state_pipeline.py",
            "semantic_state_renderer.cjs", "semantic_state_capture.cjs",
            "relation_motion_maintenance_render.py", "relation_browser_watchdog.py", "relation_browser_shim.py",
            "runtime_contracts.py", "semantic_validator.py"}
        self.assertEqual(set(namespace["FROZEN_SOURCES"]), expected)
        for source in expected:
            self.assertEqual(base64.b64decode(namespace["FROZEN_SOURCES"][source]), (root / source).read_bytes())
        self.assertEqual(payload, module.build_bundle())
        self.assertNotIn("relation_motion_cli.py", namespace["SEMANTIC_ENTRY"])
        self.assertIn("semantic_state_cli.py", namespace["SEMANTIC_ENTRY"])


@unittest.skipUnless(all(os.environ.get(key) for key in
    ("HD_PLAYWRIGHT", "HD_CHROMIUM", "HD_FFMPEG", "HD_FFPROBE")), "explicit media tools required")
class SemanticBundleMediaTests(unittest.TestCase):
    def test_frozen_package_runs_outside_project_with_descriptors(self):
        from edit.hd.tools.semantic_state_bundle import build_bundle
        from edit.hd.tests.test_semantic_state_renderer import brief
        from edit.hd.tools.relation_motion_maintenance_render import validate_relation_media_probe
        from edit.hd.tools.runtime_contracts import discover_macho_libraries, tree_identity
        tool_paths = {"node": Path("/usr/local/bin/node").resolve()}
        for key, env in (("playwright", "HD_PLAYWRIGHT"), ("browser", "HD_CHROMIUM"),
                         ("ffmpeg", "HD_FFMPEG"), ("ffprobe", "HD_FFPROBE")):
            tool_paths[key] = Path(os.environ[env]).resolve()
        contracts = {}
        for key in ("node", "ffmpeg", "ffprobe"):
            digest = hashlib.sha256()
            with tool_paths[key].open("rb") as file:
                for block in iter(lambda: file.read(65536), b""):
                    digest.update(block)
            contracts[key] = {"kind": "file_snapshot", "path": str(tool_paths[key]), "sha256": digest.hexdigest(),
                "version": "test-not-approved", "library_discovery": "mach_o_static_v1",
                "libraries": discover_macho_libraries(tool_paths[key])}
        for key, roots in (("playwright", [tool_paths["playwright"].parent, tool_paths["playwright"].parent.parent / "playwright-core"]),
                           ("browser", [tool_paths["browser"].parents[2]])):
            contracts[key] = {"kind": "directory_tree", "path": str(tool_paths[key]), "version": "test-not-approved",
                "roots": [{"path": str(path), "sha256": tree_identity(path)["sha256"]} for path in roots]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "entry.py"
            entry.write_bytes(build_bundle())
            source = root / "brief.json"
            source.write_text(json.dumps(brief("hierarchy")))
            output = root / "output.mp4"
            shadow = root / "shadow"
            package = shadow / "edit" / "hd" / "tools"
            package.mkdir(parents=True)
            for folder in (shadow / "edit", shadow / "edit" / "hd", package):
                (folder / "__init__.py").write_text("")
            (package / "semantic_state_pipeline.py").write_text("raise RuntimeError('external shadow loaded')")
            with source.open("rb") as incoming, output.open("w+b") as outgoing:
                args = [sys.executable, str(entry), "--brief", f"/dev/fd/{incoming.fileno()}",
                        "--output", f"/dev/fd/{outgoing.fileno()}", "--node", str(tool_paths["node"]),
                        "--runtime-contracts", json.dumps(contracts)]
                for key, env in (("playwright", "HD_PLAYWRIGHT"), ("browser", "HD_CHROMIUM"),
                                 ("ffmpeg", "HD_FFMPEG"), ("ffprobe", "HD_FFPROBE")):
                    args.extend(["--" + key, str(tool_paths[key])])
                process = subprocess.Popen(args, cwd=root, pass_fds=(incoming.fileno(), outgoing.fileno()),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                    env=dict(os.environ, PYTHONPATH=str(shadow)))
                try:
                    stdout, stderr = process.communicate(timeout=120)
                    self.assertEqual(process.returncode, 0, stderr)
                    self.assertEqual(stdout, "")
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate(timeout=5)
            probe = subprocess.run([os.environ["HD_FFPROBE"], "-v", "error", "-count_frames",
                "-show_streams", "-show_format", "-of", "json", str(output)],
                check=True, capture_output=True, text=True, timeout=30)
            validate_relation_media_probe(json.loads(probe.stdout), 120)

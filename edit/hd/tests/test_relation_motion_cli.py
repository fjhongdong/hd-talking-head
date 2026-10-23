import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


CLI = Path(__file__).parents[1] / "tools/relation_motion_cli.py"


class RelationCliTests(unittest.TestCase):
    def load_cli(self):
        self.assertTrue(CLI.exists(), "shared renderer CLI must exist")
        spec = importlib.util.spec_from_file_location("relation_cli_test", CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def invoke(self, module, root, output):
        source = root / "brief.json"
        source.write_text('{}')
        return module.main([
            "--brief", str(source), "--output", str(output), "--node", "/node",
            "--playwright", "/playwright", "--browser", "/browser",
            "--ffmpeg", "/ffmpeg", "--ffprobe", "/ffprobe",
        ])

    def test_cli_publishes_shared_renderer_bytes_without_approval(self):
        module = self.load_cli()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "sample.mp4"

            def render(**kwargs):
                self.assertNotIn("job_dir", kwargs)
                stage = kwargs["output_dir"]
                stage.mkdir()
                candidate = stage / "candidate.mp4"
                candidate.write_bytes(b"rendered")
                return {"candidate_path": str(candidate), "mp4_sha256": hashlib.sha256(b"rendered").hexdigest()}

            with mock.patch.object(module, "render_relation_brief_artifact", side_effect=render) as renderer:
                result = self.invoke(module, root, output)
            self.assertEqual(result, 0)
            self.assertEqual(output.read_bytes(), b"rendered")
            self.assertEqual(renderer.call_count, 1)
            self.assertFalse(list(root.rglob("maintenance-receipt.json")))
            self.assertFalse(list(root.glob("relation-render-*")))

    def test_existing_output_rejected_before_render(self):
        module = self.load_cli()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "sample.mp4"
            output.write_bytes(b"keep")
            with mock.patch.object(module, "render_relation_brief_artifact") as renderer:
                self.assertEqual(self.invoke(module, root, output), 1)
                renderer.assert_not_called()
            self.assertEqual(output.read_bytes(), b"keep")

    def test_render_failure_never_publishes_output(self):
        module = self.load_cli()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "sample.mp4"
            with mock.patch.object(module, "render_relation_brief_artifact", side_effect=ValueError("failed")):
                self.assertEqual(self.invoke(module, root, output), 1)
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob("relation-render-*")))

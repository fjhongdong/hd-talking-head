"""Shared semantic media pipeline contracts, independent of Job approval."""
import importlib
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from edit.hd.tests.test_semantic_state_renderer import brief
from edit.hd.tests.test_semantic_state_browser import run_browser_check


class SemanticPipelineTests(unittest.TestCase):
    def module(self):
        name = "edit.hd.tools.semantic_state_pipeline"
        self.assertIsNotNone(importlib.util.find_spec(name), "shared semantic pipeline missing")
        return importlib.import_module(name)

    def test_invalid_brief_leaves_no_output(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "render"
            with self.assertRaises(ValueError):
                module.render_semantic_artifact(brief={}, output_dir=output,
                    node_executable="/usr/local/bin/node", playwright_module="/missing",
                    browser_executable="/missing", ffmpeg_executable="/missing", ffprobe_executable="/missing")
            self.assertFalse(output.exists())

    def test_capture_failure_never_returns_success(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "render"
            with self.assertRaisesRegex(ValueError, "supervisor"):
                with patch.dict("os.environ", {}, clear=True):
                    module.render_semantic_artifact(brief=brief(), output_dir=output,
                        node_executable="/usr/local/bin/node", playwright_module="/missing",
                        browser_executable="/missing", ffmpeg_executable="/missing", ffprobe_executable="/missing")
            self.assertFalse((output / "candidate.mp4").exists())

    def test_existing_output_is_preserved(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve()
            marker = output / "keep"
            marker.write_text("unchanged")
            with self.assertRaisesRegex(ValueError, "new"):
                module.render_semantic_artifact(brief=brief(), output_dir=output,
                    node_executable="/usr/local/bin/node", playwright_module="/missing",
                    browser_executable="/missing", ffmpeg_executable="/missing", ffprobe_executable="/missing")
            self.assertEqual(marker.read_text(), "unchanged")


@unittest.skipUnless(all(os.environ.get(key) for key in
    ("HD_PLAYWRIGHT", "HD_CHROMIUM", "HD_FFMPEG", "HD_FFPROBE")), "explicit media tools required")
class SemanticPipelineMediaTests(unittest.TestCase):
    def test_five_families_use_shared_pipeline(self):
        script = """
const r=require('node:child_process').spawnSync(process.argv[1],['-c',process.argv[2]],
 {input:require('node:fs').readFileSync(0),timeout:120000});
if(r.stdout)process.stdout.write(r.stdout);
if(r.stderr)process.stderr.write(r.stderr);
process.exitCode=Number.isInteger(r.status)?r.status:1;
"""
        python = """
import json,sys,os
from edit.hd.tools.semantic_state_pipeline import render_semantic_artifact
request=json.load(sys.stdin)
print(json.dumps(render_semantic_artifact(**request,
 node_executable='/usr/local/bin/node',playwright_module=os.environ['HD_PLAYWRIGHT'],
 browser_executable=os.environ['HD_CHROMIUM'],ffmpeg_executable=os.environ['HD_FFMPEG'],
 ffprobe_executable=os.environ['HD_FFPROBE'])))
"""
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                output = Path(directory).resolve() / "render"
                result = run_browser_check(script, [sys.executable, python],
                    json.dumps({"brief": brief(family), "output_dir": str(output)}), timeout=150)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertTrue(Path(report["candidate_path"]).is_file())
                self.assertEqual(report["media_probe"]["streams"][0]["nb_read_frames"], "120")
                self.assertEqual(len(report["mp4_sha256"]), 64)
                self.assertNotIn("approved", report)


if __name__ == "__main__":
    unittest.main()

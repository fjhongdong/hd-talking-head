"""CLI publication boundaries; actual encoding is tested in pipeline tests."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from edit.hd.tests.test_semantic_state_browser import run_browser_check
from edit.hd.tests.test_semantic_state_renderer import brief


class SemanticCliTests(unittest.TestCase):
    def test_publication_and_failure_cleanup(self):
        name = "edit.hd.tools.semantic_state_cli"
        self.assertIsNotNone(importlib.util.find_spec(name), "semantic CLI missing")
        module = importlib.import_module(name)
        for scenario in ("success", "failure", "drift", "existing", "duplicate", "race"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                source, output = root / "brief.json", root / "result.mp4"
                source.write_text('{"x":1,"x":2}' if scenario == "duplicate" else '{}')
                if scenario == "existing":
                    output.write_bytes(b"keep")
                def render(**kwargs):
                    stage = kwargs["output_dir"]
                    stage.mkdir()
                    candidate = stage / "candidate.mp4"
                    candidate.write_bytes(b"video")
                    if scenario == "failure":
                        raise ValueError("render failed")
                    return {"candidate_path": str(candidate), "mp4_sha256":
                        hashlib.sha256(b"wrong" if scenario == "drift" else b"video").hexdigest()}
                args = ["--brief", str(source), "--output", str(output)]
                for flag in ("node", "playwright", "browser", "ffmpeg", "ffprobe"):
                    args.extend(["--" + flag, "/" + flag])
                link = os.link
                def replace_before_link(candidate, destination):
                    if scenario == "race":
                        candidate.unlink()
                        candidate.write_bytes(b"replacement")
                    link(candidate, destination)
                with patch.object(module, "render_semantic_artifact", side_effect=render) as mocked:
                    with patch.object(module.os, "link", side_effect=replace_before_link):
                        result = module.main(args)
                self.assertEqual(result, 0 if scenario == "success" else 1)
                if scenario in ("existing", "duplicate"):
                    mocked.assert_not_called()
                if scenario in ("success", "existing"):
                    self.assertEqual(output.read_bytes(), b"video" if scenario == "success" else b"keep")
                else:
                    self.assertFalse(output.exists())
                self.assertEqual(sorted(p.name for p in root.iterdir()),
                    ["brief.json", "result.mp4"] if output.exists() else ["brief.json"])


@unittest.skipUnless(all(os.environ.get(key) for key in
    ("HD_PLAYWRIGHT", "HD_CHROMIUM", "HD_FFMPEG", "HD_FFPROBE")), "explicit media tools required")
class SemanticCliMediaTests(unittest.TestCase):
    def test_actual_script_publishes_video_and_cleans_staging(self):
        script = """
const r=require('node:child_process').spawnSync(process.argv[1],
 [process.argv[2],'--brief',process.argv[3],'--output',process.argv[4],
 '--node',process.execPath,'--playwright',process.env.HD_PLAYWRIGHT,
 '--browser',process.env.HD_CHROMIUM,'--ffmpeg',process.env.HD_FFMPEG,
 '--ffprobe',process.env.HD_FFPROBE],{timeout:120000});
if(r.stdout)process.stdout.write(r.stdout);
if(r.stderr)process.stderr.write(r.stderr);
process.exitCode=Number.isInteger(r.status)?r.status:1;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, output = root / "brief.json", root / "result.mp4"
            source.write_text(json.dumps(brief("feedback")))
            cli = Path(__file__).parents[1] / "tools/semantic_state_cli.py"
            result = run_browser_check(script, [sys.executable, str(cli), str(source), str(output)], "", timeout=150)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["brief.json", "result.mp4"])
            result = subprocess.run([os.environ["HD_FFPROBE"], "-v", "error", "-count_frames",
                "-show_streams", "-show_format", "-of", "json", str(output)],
                check=True, capture_output=True, text=True, timeout=30)
            from edit.hd.tools.relation_motion_maintenance_render import validate_relation_media_probe
            validate_relation_media_probe(json.loads(result.stdout), 120)

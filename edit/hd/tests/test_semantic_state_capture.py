"""Maintenance capture tests; no production template registration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from edit.hd.tests.test_semantic_state_renderer import brief, RENDERER
from edit.hd.tests.test_semantic_state_browser import run_browser_check

CAPTURE = RENDERER.with_name("semantic_state_capture.cjs")
SCRIPT = """
const fs=require('node:fs');
require(process.argv[1]).capture({brief:JSON.parse(fs.readFileSync(0,'utf8')),
 output:process.argv[2],playwright:process.env.HD_PLAYWRIGHT,browser:process.env.HD_CHROMIUM})
 .then(r=>process.stdout.write(JSON.stringify(r))).catch(e=>{console.error(e.message);process.exitCode=1});
"""
CLI_SCRIPT = """
const fs=require('node:fs');
const result=require('node:child_process').spawnSync(process.execPath,
 [process.argv[1],'--output',process.argv[2],
  '--playwright',process.env.HD_PLAYWRIGHT,'--browser',process.env.HD_CHROMIUM],
 {input:fs.readFileSync(0),timeout:75000});
if(result.stdout)process.stdout.write(result.stdout);
if(result.stderr)process.stderr.write(result.stderr);
if(result.error)console.error(result.error.message);
process.exitCode=Number.isInteger(result.status)?result.status:1;
"""


class CaptureValidationTests(unittest.TestCase):
    def test_cli_rejects_bad_arguments_and_bounded_input_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "frames"
            arguments = ["--output", str(output), "--playwright", "/missing/module", "--browser", "/missing/browser"]
            cases = [
                (arguments, b"x" * (4 * 1024 * 1024 + 1), "4 MiB"),
                (arguments, b"\xff", "encoded data"),
                (arguments, b"{", "JSON"),
                (arguments[:4] + ["--output", str(output)], b"{}", "duplicate"),
                (arguments + ["--extra", "value"], b"{}", "arguments required"),
            ]
            for args, payload, message in cases:
                with self.subTest(message=message):
                    result = subprocess.run(["node", str(CAPTURE), *args], input=payload,
                                            capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr.decode())
                    self.assertEqual(result.stdout, b"")
                    self.assertFalse(output.exists())

    def test_cli_rejects_unsupervised_capture_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "frames"
            environment = {k: v for k, v in os.environ.items() if not k.startswith("HD_BROWSER_")}
            result = subprocess.run(
                ["node", str(CAPTURE), "--output", str(output),
                 "--playwright", "/missing/playwright.cjs", "--browser", "/missing/browser"],
                input=json.dumps(brief()), env=environment, text=True,
                capture_output=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supervisor", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(output.exists())

    def test_launch_failure_preserves_error_and_never_deletes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fake = root / "playwright.cjs"
            fake.write_text("exports.chromium={launch:async()=>{throw 'launch fixture failure'}};")
            output = root / "frames"
            environment = dict(os.environ, HD_BROWSER_SOCKET="unused", HD_BROWSER_TOKEN="unused",
                               HD_PLAYWRIGHT=str(fake), HD_CHROMIUM=str(RENDERER.with_name("relation_browser_shim.py")))
            def run():
                return subprocess.run(["node", str(CAPTURE), "--output", str(output),
                                       "--playwright", str(fake), "--browser", environment["HD_CHROMIUM"]],
                                      input=json.dumps(brief()), env=environment,
                                      text=True, capture_output=True, timeout=10)
            result = run()
            self.assertIn("semantic capture failed: launch fixture failure", result.stderr)
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])
            marker = output / "keep.txt"
            marker.write_text("keep")
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual(marker.read_text(), "keep")

    def test_unsupervised_capture_refuses_before_output(self):
        self.assertTrue(CAPTURE.exists(), "semantic capture is missing")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "frames"
            environment = {k: v for k, v in os.environ.items() if not k.startswith("HD_BROWSER_")}
            result = subprocess.run(["node", "-e", SCRIPT, str(CAPTURE), str(output)],
                                    input=json.dumps(brief()), env=environment,
                                    text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supervisor", result.stderr)
            self.assertFalse(output.exists())


@unittest.skipUnless(os.environ.get("HD_PLAYWRIGHT") and os.environ.get("HD_CHROMIUM")
                     and os.environ.get("HD_FFMPEG") and os.environ.get("HD_FFPROBE"),
                     "explicit local browser and media tools required")
class CaptureMediaTests(unittest.TestCase):
    def test_real_frames_encode_to_exact_native_silent_video(self):
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            with self.subTest(family=family):
                self.check_family_media(family)

    def check_family_media(self, family):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "frames"
            result = run_browser_check(CLI_SCRIPT, [str(CAPTURE), str(output)], json.dumps(brief(family)), timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["frame_count"], 120)
            self.assertEqual(len(list(output.glob("frame-*.png"))), 120)
            self.assertEqual((output / "frame-000072.png").read_bytes(), (output / "frame-000119.png").read_bytes())
            self.assertNotEqual((output / "frame-000030.png").read_bytes(), (output / "frame-000050.png").read_bytes())
            video = Path(directory) / "candidate.mp4"
            subprocess.run([os.environ["HD_FFMPEG"], "-v", "error", "-n", "-framerate", "24",
                            "-i", str(output / "frame-%06d.png"), "-frames:v", "120", "-vf", "setsar=1",
                            "-threads", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                           check=True, capture_output=True, timeout=60)
            probe = subprocess.run([os.environ["HD_FFPROBE"], "-v", "error", "-count_frames",
                                    "-show_streams", "-show_format", "-of", "json", str(video)],
                                   check=True, capture_output=True, text=True, timeout=15)
            from edit.hd.tools.relation_motion_maintenance_render import validate_relation_media_probe
            validate_relation_media_probe(json.loads(probe.stdout), 120)
            subprocess.run([os.environ["HD_FFMPEG"], "-v", "error", "-nostdin", "-xerror",
                            "-threads", "1", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"],
                           check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    unittest.main()

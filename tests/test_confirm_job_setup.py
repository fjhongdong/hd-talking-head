"""Setup-confirmation gate: context binding rejects stale or wrong files."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401


SCRIPT = _env.SKILL / "scripts/confirm_job_setup.py"


def tiny_video(directory: Path) -> Path:
    video = directory / "tiny.mp4"
    video.write_bytes(b"tiny-video-fixture")
    return video


def tiny_script(directory: Path) -> Path:
    script = directory / "script.md"
    script.write_text("一句口播文案", encoding="utf-8")
    return script


@unittest.skipUnless(_env.EDIT_HD_AVAILABLE, "edit.hd runtime is unavailable")
class ConfirmJobSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sys.path.insert(0, str(_env.SKILL / "scripts"))
        import initialize_video_job as initializer
        job, context = initializer.initialize_video_job(
            self.root / "jobs", "confirm-gate", tiny_video(self.root),
            script=None, script_text="一句口播文案", project_root=_env.PROJECT)
        self.context = context
        self.job = job

    def run_cli(self, context_path, confirmation="同意本次配置"):
        return subprocess.run([sys.executable, str(SCRIPT),
                               "--job-context", str(context_path),
                               "--user-confirmation", confirmation],
                              capture_output=True, text=True, check=False)

    def test_context_copy_outside_the_job_is_rejected(self):
        copied = self.root / "copied-context.json"
        copied.write_text(json.dumps(self.context, ensure_ascii=False), encoding="utf-8")
        result = self.run_cli(copied)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("not the current Job context", result.stderr)

    def test_invalid_context_file_stops_before_runtime(self):
        broken = self.root / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        result = self.run_cli(broken)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid context", result.stderr)

    def test_context_missing_project_root_stops(self):
        partial = self.root / "partial.json"
        partial.write_text(json.dumps({"job_dir": str(self.job.root)}), encoding="utf-8")
        result = self.run_cli(partial)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid context", result.stderr)


if __name__ == "__main__":
    unittest.main()

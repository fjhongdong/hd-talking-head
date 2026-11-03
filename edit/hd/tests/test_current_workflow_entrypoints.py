"""Keep human and CLI entrypoints on the current, single Skill contract."""

import contextlib
import importlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from edit.hd.tools import cli, state


PROJECT = Path(__file__).resolve().parents[3]
SKILL = PROJECT / "."


class CurrentWorkflowEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.txt"
        self.video.write_bytes(b"fixture-video")
        self.script.write_text("fixture-script", encoding="utf-8")

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def run_job(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SKILL / "run.py"), "job", *arguments],
            cwd=self.root, capture_output=True, text=True, check=False,
        )

    def test_canonical_job_status_is_read_only_from_another_directory(self):
        job = state.create_job(self.root, self.video, self.script)
        workflow = job.job_dir / "workflow.json"
        before = workflow.read_bytes()
        manifests = job.job_dir / "manifests"
        previous_records = sorted(path.name for path in manifests.iterdir())
        result = self.run_job("status", "--job", str(job.job_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["current_stage"], "inspect")
        self.assertEqual(summary["delivery_status"], "pending")
        self.assertEqual(tuple(summary["stages"]), tuple(sorted(state.STAGE_IDS)))
        self.assertEqual(workflow.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in manifests.iterdir()), previous_records)

    def test_job_cli_does_not_expose_machine_completion_or_old_initialization(self):
        for command in ("init", "approve", "ready", "complete"):
            with self.subTest(command=command):
                result, stdout, _ = self.invoke(command)
                self.assertEqual(result, 2)
                self.assertEqual(stdout, "")
        self.assertFalse((self.root / "edit").exists())

    def test_python_creation_never_defaults_to_retired_profile(self):
        job = state.create_job(self.root, self.video, self.script)
        self.assertEqual(job.version, 2)

    def test_retired_profile_is_not_created(self):
        with self.assertRaises(state.WorkflowError):
            state.create_job(self.root, self.video, self.script, profile="legacy-v1")

    def test_canonical_job_revision_preserves_requested_artifact_scope(self):
        job = state.create_job(self.root, self.video, self.script)
        for stage in state.STAGE_IDS:
            state.mark_ready(job, stage, [])
            state.complete(job, stage)
            if stage == "visual_assets":
                break
        result = self.run_job(
            "revise", "--job", str(job.job_dir), "--stage", "visual_assets",
            "--reason", "调整第1、3处动效", "--artifact-scope", "seg-001",
            "--artifact-scope", "seg-003",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        current = state.load_job(job.job_dir)
        self.assertEqual(current.stages["visual_assets"]["status"], "needs_revision")
        self.assertEqual(current.stages["visual_assets"]["artifact_scope"], ["seg-001", "seg-003"])
        self.assertEqual(current.stages["visual_direction"]["status"], "completed")
        self.assertEqual(current.stages["subtitles"]["status"], "pending")
        self.assertEqual(json.loads(result.stdout)["delivery_status"], "pending")

    def test_documented_composition_symbols_exist(self):
        source = (SKILL / "references/production-bindings.md").read_text(encoding="utf-8")
        for symbol in re.findall(r"`broll_systems\.([a-z_]+)`", source):
            with self.subTest(symbol=symbol):
                self.assertTrue(callable(getattr(
                    importlib.import_module("edit.hd.tools.broll_systems"), symbol, None
                )))

    def test_generic_production_contract_does_not_bind_a_historical_topic(self):
        source = (SKILL / "references/production-bindings.md").read_text(encoding="utf-8")
        self.assertNotIn("edit/hd/canary/shot-spec.json", source)
        self.assertNotIn("/Users/Abner/Downloads/broll-canary-5shot.mp4", source)


if __name__ == "__main__":
    unittest.main()

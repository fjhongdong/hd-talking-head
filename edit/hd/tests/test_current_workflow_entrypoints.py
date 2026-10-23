"""Keep human and CLI entrypoints on the current, single Skill contract."""

import contextlib
import importlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from edit.hd.tools import cli, state


PROJECT = Path(__file__).resolve().parents[3]
SKILL = PROJECT / "skill-development/hd-talking-head"


class CurrentWorkflowEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.txt"
        self.video.write_bytes(b"fixture-video")
        self.script.write_text("fixture-script", encoding="utf-8")

    def invoke(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main([
                "init", "--root", str(self.root), "--video", str(self.video),
                "--script", str(self.script), *extra,
            ])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_default_cli_creation_uses_twelve_stages(self):
        result, stdout, stderr = self.invoke()
        self.assertEqual(result, 0, stderr)
        job = state.load_job(self.root / json.loads(stdout)["job"])
        self.assertEqual(job.version, 2)
        self.assertEqual(state.stage_ids_for(job), state.FULL_V2_STAGE_IDS)

    def test_cli_cannot_create_retired_profile(self):
        result, stdout, _ = self.invoke("--profile", "legacy-v1")
        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertFalse((self.root / "edit").exists())

    def test_python_creation_never_defaults_to_retired_profile(self):
        job = state.create_job(self.root, self.video, self.script)
        self.assertEqual(job.version, 2)

    def test_old_job_remains_readable_without_migration(self):
        job = state.create_job(self.root, self.video, self.script, profile="legacy-v1")
        workflow = job.job_dir / "workflow.json"
        before = workflow.read_bytes()
        loaded = state.load_job(job.job_dir)
        self.assertEqual(loaded.version, 1)
        self.assertEqual(workflow.read_bytes(), before)

    def test_project_guide_only_points_to_the_single_skill(self):
        guide = (PROJECT / "docs/workflows/hd-talking-head.md").read_text(encoding="utf-8")
        targets = re.findall(r"\]\(([^)]+)\)", guide)
        self.assertIn(str(SKILL / "SKILL.md"), targets)
        self.assertLessEqual(len(guide.splitlines()), 12)

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

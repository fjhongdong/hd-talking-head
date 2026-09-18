"""Release tests run from a copied Skill, without relying on the caller's cwd."""

from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


class ReleaseIntegrityTests(unittest.TestCase):
    def run_check(self, root: Path, *arguments: str) -> subprocess.CompletedProcess:
        script = root / "scripts/verify_skill_release.py"
        self.assertTrue(script.is_file(), "published Skill is missing its release verifier")
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=root.parent, capture_output=True, text=True, check=False,
        )

    def copy_skill(self, parent: Path) -> Path:
        return Path(shutil.copytree(SKILL, parent / "copied skill", ignore=shutil.ignore_patterns("__pycache__")))

    def test_shipped_package_verifies_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_skill(Path(directory))
            result = self.run_check(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "pass")

    def test_missing_template_verifier_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_skill(Path(directory))
            path = root / "scripts/verify_broll_template.py"
            if path.exists():
                path.unlink()
            result = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("scripts/verify_broll_template.py", result.stdout)

    def test_edited_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_skill(Path(directory))
            with (root / "references/cover-opening-bgm.md").open("a") as handle:
                handle.write("\nUnreleased change\n")
            result = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cover-opening-bgm.md", result.stdout)

    def test_different_peer_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_skill(Path(directory))
            (root / "SKILL.md").write_text("old skill", encoding="utf-8")
            result = self.run_check(SKILL, "--peer", str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SKILL.md", result.stdout)

    def test_initializer_rejects_modified_release_before_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self.copy_skill(parent)
            (root / "references/cover-opening-bgm.md").write_text("old rules", encoding="utf-8")
            jobs = parent / "jobs"
            result = subprocess.run(
                [sys.executable, str(root / "scripts/initialize_video_job.py"),
                 "--jobs-root", str(jobs), "--title", "release check",
                 "--video", str(parent / "absent.mp4"), "--script", str(parent / "absent.md")],
                cwd=parent, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Skill release integrity check failed", result.stderr)
            self.assertFalse(jobs.exists())

    def test_semantic_motion_docs_match_registered_boundaries(self) -> None:
        semantic = (SKILL / "references/semantic-motion.md").read_text(encoding="utf-8")
        entrypoint = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        registry = json.loads(
            (SKILL / "references/verified-template-registry.json").read_text(encoding="utf-8")
        )
        template_ids = {record["template_id"] for record in registry["templates"]}

        semantic_ids = {
            f"hd-talking-head/semantic-state-{family}"
            for family in ("replacement", "threshold", "delay", "hierarchy", "feedback")
        }
        self.assertEqual(len(template_ids), 14)
        self.assertIn("hd-talking-head/relation-motion", template_ids)
        self.assertTrue(semantic_ids.issubset(template_ids))
        self.assertIn("relation_motion: registered", semantic)
        self.assertIn("semantic_state: registered", semantic)
        self.assertIn("production_policy: registered_templates_only", semantic)
        self.assertIn("[语义动效规划接口与执行边界]", entrypoint)

        for record in registry["templates"]:
            if record["template_id"] not in semantic_ids:
                continue
            self.assertEqual(record["semantic_families"], [record["template_id"].rsplit("-", 1)[-1]])
            self.assertEqual(record["execution_qa"]["status"], "reviewed")
            self.assertEqual(len(record["execution_qa"]["cases"]), 2)
            self.assertIn(
                "semantic-state-qualification-20260918-restore",
                record["execution_qa"]["source_registry"]["path"],
            )

        canary_script = SKILL / "tests/render_semantic_state_avatar_canary.py"
        spec = importlib.util.spec_from_file_location("release_avatar_canary", canary_script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        approval = module.validate_human_approval(
            SKILL,
            SKILL / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored/review.json",
        )
        self.assertEqual(set(approval["template_ids"]), semantic_ids)


if __name__ == "__main__":
    unittest.main()

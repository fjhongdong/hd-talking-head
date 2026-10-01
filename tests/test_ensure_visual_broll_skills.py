"""Check project-only visual Skill acquisition without network or provider calls."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ensure_visual_broll_skills as deps


class VisualBrollDependenciesTests(unittest.TestCase):
    def test_missing_upstream_is_cloned_inside_project_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "edit/hd/tools").mkdir(parents=True)
            (root / "edit/hd/tools/state.py").write_text("# fixture\n")
            vendor = root / "skill-development/vendor"
            vendor.mkdir(parents=True)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("# fixture\n")
            for command in (
                ["git", "init", "-q", str(source)],
                ["git", "-C", str(source), "add", "SKILL.md"],
                ["git", "-C", str(source), "-c", "user.name=Fixture", "-c",
                 "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
            ):
                subprocess.run(command, check=True, capture_output=True)
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    check=True, capture_output=True, text=True).stdout.strip()
            fixture = {"url": str(source), "commit": commit, "files": ("SKILL.md",)}
            with patch.dict(deps.SOURCES, {"gbro-collage-broll": fixture}):
                first = deps.ensure(root, "gbro-collage-broll")
                second = deps.ensure(root, "gbro-collage-broll")
            self.assertEqual(first["status"], "installed")
            self.assertEqual(second["status"], "already_available")
            self.assertTrue((vendor / "gbro-collage-broll/SKILL.md").is_file())
            self.assertFalse((root / "gbro-collage-broll").exists())


if __name__ == "__main__":
    unittest.main()

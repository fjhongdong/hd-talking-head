"""Project-local Punk cover dependency bootstrap behavior."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ensure_punk_cover.py"
SPEC = importlib.util.spec_from_file_location("ensure_punk_cover", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class EnsurePunkCoverTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "project"
        state = project / "edit/hd/tools/state.py"
        state.parent.mkdir(parents=True)
        state.write_text("# fixture\n", encoding="utf-8")
        return project

    def _source(self, root: Path, *, complete: bool = True) -> tuple[Path, str]:
        source = root / "source"
        source.mkdir()
        files = module.REQUIRED_FILES if complete else module.REQUIRED_FILES[:-1]
        for relative in files:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        _git("init", "-q", str(source))
        _git("-C", str(source), "add", ".")
        _git("-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        return source, _git("-C", str(source), "rev-parse", "HEAD")

    def test_missing_dependency_installs_once_in_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            source, commit = self._source(root)
            with patch.object(module, "REPO_URL", str(source)), patch.object(module, "PINNED_COMMIT", commit):
                first = module.ensure_punk_cover(project)
                second = module.ensure_punk_cover(project)
            self.assertEqual(first["status"], "installed")
            self.assertEqual(second["status"], "already_available")
            self.assertEqual(Path(first["path"]), (project / "skill-development/vendor/Punk-Skill").resolve())

    def test_existing_invalid_directory_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            destination = project / "skill-development/vendor/Punk-Skill"
            destination.mkdir(parents=True)
            marker = destination / "user-file.txt"
            marker.write_text("keep me\n", encoding="utf-8")
            with self.assertRaises(module.PunkCoverInstallError):
                module.ensure_punk_cover(project)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")

    def test_incomplete_clone_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            source, commit = self._source(root, complete=False)
            with patch.object(module, "REPO_URL", str(source)), patch.object(module, "PINNED_COMMIT", commit):
                with self.assertRaises(module.PunkCoverInstallError):
                    module.ensure_punk_cover(project)
            self.assertFalse((project / "skill-development/vendor/Punk-Skill").exists())

    def test_symlinked_development_directory_does_not_write_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            outside = root / "outside"
            outside.mkdir()
            (project / "skill-development").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(module.PunkCoverInstallError):
                module.ensure_punk_cover(project)
            self.assertEqual(list(outside.iterdir()), [])

    def test_concurrent_startup_installs_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            source, commit = self._source(root)
            with patch.object(module, "REPO_URL", str(source)), patch.object(module, "PINNED_COMMIT", commit):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(module.ensure_punk_cover, (project, project)))
            self.assertEqual({item["status"] for item in results}, {"installed", "already_available"})


if __name__ == "__main__":
    unittest.main()

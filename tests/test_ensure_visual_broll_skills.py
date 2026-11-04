"""Check project-only visual Skill acquisition without network or provider calls."""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ensure_visual_broll_skills as deps


class VisualBrollDependenciesTests(unittest.TestCase):
    def test_lemo_complete_archive_prepares_without_git_identity(self) -> None:
        from prepare_sources import prepare_sources
        package = Path(__file__).resolve().parents[1]
        entry = next(row for row in json.loads((package / "archives/sources/index.json").read_text())["repositories"]
                     if row["path"] == "vendor/lemo-opuscar")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "archives/sources").mkdir(parents=True)
            (root / "archives/sources/index.json").write_text(json.dumps({"repositories": [entry]}))
            for archive in entry["archives"]:
                shutil.copyfile(package / archive, root / archive)
            self.assertEqual(prepare_sources(root), [{"path": entry["path"], "commit": entry["commit"], "status": "ready"}])
            source = root / entry["path"]
            self.assertFalse((source / ".git").exists())
            (root / 'edit/hd/tools').mkdir(parents=True)
            (root / 'edit/hd/tools/state.py').write_text('# isolated source-preparation fixture\n')
            # Reuse the installed ordinary runtime; never download for a check.
            (source / 'node_modules').symlink_to(package / 'vendor/lemo-opuscar/node_modules', target_is_directory=True)
            from upstream_scene_adapter import verify_lemo_source
            with patch.object(deps, "_git", side_effect=AssertionError("Snapshot preparation must not borrow any Git identity")):
                # Isolate the machine/executor probe; the actual restored source
                # is checked again at the runtime-preparation boundary.
                with patch('upstream_scene_adapter.check_runtime', side_effect=lambda project, _dep: verify_lemo_source(project)) as probe, \
                     patch.object(sys, 'argv', ['ensure_visual_broll_skills.py', '--project-root', str(root),
                                               '--skill', 'lemo-opuscar']):
                    self.assertEqual(deps.main(), 0)
                    probe.assert_called_once_with(root, 'lemo-opuscar')

    def test_missing_upstream_is_cloned_inside_project_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "edit/hd/tools").mkdir(parents=True)
            (root / "edit/hd/tools/state.py").write_text("# fixture\n")
            vendor = root / "vendor"
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

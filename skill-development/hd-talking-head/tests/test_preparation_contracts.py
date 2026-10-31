"""Guard: manifest preparation arguments must stay CLI-compatible.

project_python.py prepends ``--project-root <project>`` itself before the
manifest arguments, so a script gaining a required argument would break the
real preparation flow with no test failing. This guard runs every manifest
preparation entry with the runner-shaped argv against a nonexistent project
root and requires the failure to be environmental, never an argparse error.
"""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401


SKILL = Path(__file__).resolve().parents[1]
MANIFEST = SKILL / "references/dependency-manifest.json"


class PreparationContractTests(unittest.TestCase):
    def test_bundled_source_subset_checks_actual_files_without_git_history(self):
        from prepare_sources import bundled_source_revision
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            source = package / "source"
            source.mkdir()
            path = source / "template.html"
            path.write_text("original native template")
            index = package / "source-repositories/index.json"
            index.parent.mkdir()
            index.write_text(json.dumps({"schema_version": 1, "repositories": [{
                "path": "source", "commit": "a" * 40,
                "files": {"template.html": hashlib.sha256(path.read_bytes()).hexdigest()},
            }]}))
            self.assertEqual(bundled_source_revision(package, source), "a" * 40)
            self.assertFalse((source / ".git").exists())
            path.write_text("changed native template")
            with self.assertRaisesRegex(ValueError, "source file changed"):
                bundled_source_revision(package, source)

    def test_complete_source_archive_is_verified_before_cold_restore(self):
        import tarfile
        from prepare_sources import prepare_sources
        from verify_skill_release import package_files
        with tempfile.TemporaryDirectory() as name:
            package=Path(name).resolve();skill=package/'skill-development/hd-talking-head';skill.mkdir(parents=True)
            seed=package/'seed';seed.mkdir();original=seed/'README.md';original.write_text('complete original source')
            (seed/'workbench').mkdir();(seed/'workbench/source').symlink_to('../README.md')
            archives=package/'source-repositories';archives.mkdir();archive=archives/'native.source.part-000'
            with tarfile.open(archive,'w:gz',dereference=False) as bundle:
                bundle.add(original,arcname='README.md');bundle.add(seed/'workbench/source',arcname='workbench/source')
            entry={'path':'skill-development/vendor/video-shotcraft','commit':'a'*40,
                'archives':['source-repositories/native.source.part-000'],
                'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                'files':{'README.md':hashlib.sha256(original.read_bytes()).hexdigest()},
                'symlinks':{'workbench/source':'../README.md'}}
            (archives/'index.json').write_text(json.dumps({'schema_version':1,'repositories':[entry]}))
            before=set(package_files(skill));source=package/entry['path'];self.assertFalse(source.exists())
            self.assertEqual(prepare_sources(package),[{'path':entry['path'],'commit':'a'*40,'status':'ready'}])
            self.assertEqual((source/'README.md').read_bytes(),original.read_bytes())
            self.assertEqual(str((source/'workbench/source').readlink()),'../README.md')
            self.assertEqual(before,set(package_files(skill)))
            self.assertIn('source-repositories/native.source.part-000',before)
            (source/'README.md').write_text('unrelated local edit')
            with self.assertRaisesRegex(ValueError,'source file changed'):
                prepare_sources(package)
            self.assertEqual((source/'README.md').read_text(),'unrelated local edit')

    def test_runner_shaped_argv_is_accepted_by_every_preparation_script(self):
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["preparation"]
        checked = 0
        for entry in entries:
            if not isinstance(entry.get("script"), str):
                continue
            checked += 1
            with self.subTest(id=entry.get("id")):
                argv = [sys.executable, str(SKILL / entry["script"]),
                        "--project-root", "/nonexistent-hd-guard-root",
                        *entry["arguments"]]
                result = subprocess.run(argv, capture_output=True, text=True,
                                         timeout=60, check=False)
                combined = result.stderr + result.stdout
                # 脚本自身用退出码 2 报环境错误;判据是 argparse 签名而非退出码。
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("unrecognized arguments", combined)
                self.assertNotIn("the following arguments are required", combined)
        self.assertGreaterEqual(checked, 3)


if __name__ == "__main__":
    unittest.main()

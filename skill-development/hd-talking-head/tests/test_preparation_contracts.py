"""Guard: manifest preparation arguments must stay CLI-compatible.

project_python.py prepends ``--project-root <project>`` itself before the
manifest arguments, so a script gaining a required argument would break the
real preparation flow with no test failing. This guard runs every manifest
preparation entry with the runner-shaped argv against a nonexistent project
root and requires the failure to be environmental, never an argparse error.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import _env  # noqa: F401


SKILL = Path(__file__).resolve().parents[1]
MANIFEST = SKILL / "references/dependency-manifest.json"


class PreparationContractTests(unittest.TestCase):
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

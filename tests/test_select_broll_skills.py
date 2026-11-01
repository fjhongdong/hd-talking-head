"""Selection-entry CLI contracts: offline actions only, no rendering."""
import json
import os
import subprocess
import sys
import unittest

import _env  # noqa: F401


SCRIPT = _env.SKILL / "scripts/select_broll_skills.py"


@unittest.skipUnless(_env.EDIT_HD_AVAILABLE, "edit.hd runtime is unavailable")
class SelectBrollSkillsCliTests(unittest.TestCase):
    def run_cli(self, *args):
        environment = {**os.environ, "PYTHONPATH": str(_env.PROJECT)}
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, check=False,
                              timeout=180, env=environment)

    def test_assign_requires_treatment(self):
        assign = self.run_cli("assign", "--project-root", str(_env.PROJECT))
        self.assertEqual(assign.returncode, 2)

    def test_missing_treatment_file_stops_with_report(self):
        result = self.run_cli("assign", "--project-root", str(_env.PROJECT),
                              "--treatment", "does-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("B-roll selection stopped", result.stderr)

    def test_discover_reports_offline_candidates(self):
        result = self.run_cli("discover", "--project-root", str(_env.PROJECT))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)


if __name__ == "__main__":
    unittest.main()

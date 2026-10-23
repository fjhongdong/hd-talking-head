"""Exercise the Python entry exactly as the frozen executor starts it."""
from pathlib import Path
import subprocess
import sys
import unittest


SKILL = Path(__file__).resolve().parents[1]


class NativeHyperFramesStartupTests(unittest.TestCase):
    def test_stdin_entry_imports_its_helper_outside_the_project(self):
        result = subprocess.run(
            [sys.executable, "-", "--skill-root", str(SKILL), "--help"],
            input=(SKILL / "scripts/hyperframes_native_adapter.py").read_bytes(),
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        self.assertIn(b"--media-manifest", result.stdout)
        self.assertIn(b"--skill-root", result.stdout)


if __name__ == "__main__":
    unittest.main()

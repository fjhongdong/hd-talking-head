"""Renderer CLI surface: no-arg runs must fail with their frozen usage."""
import shutil
import subprocess
import unittest
from pathlib import Path

import _env  # noqa: F401


RENDERERS = {
    "render_adu_native.mjs": ("Missing --", ()),
    "render_hypit_native.mjs": ("Missing --", ()),
    "render_talkcraft_native.mjs": ("Usage:", ("--project-root", "--entry", "--composition", "--output")),
    "render_doudou.mjs": ("Usage:", ("--project-root", "--entry", "--composition", "--output")),
    "render_motion_graphics.cjs": ("Missing --", ()),
}


@unittest.skipUnless(shutil.which("node"), "node is unavailable")
class RendererCliContractTests(unittest.TestCase):
    def test_missing_arguments_fail_with_frozen_surface(self):
        for name, (marker, flags) in RENDERERS.items():
            with self.subTest(renderer=name):
                result = subprocess.run(
                    ["node", str(_env.SKILL / "scripts" / name)],
                    capture_output=True, text=True, timeout=30, check=False)
                combined = result.stderr + result.stdout
                self.assertNotEqual(result.returncode, 0, combined)
                self.assertIn(marker, combined)
                for flag in flags:
                    self.assertIn(flag, combined)
                if name in ("render_talkcraft_native.mjs", "render_doudou.mjs"):
                    frozen = subprocess.run(
                        ["node", str(_env.SKILL / "scripts" / name), "--brief"],
                        capture_output=True, text=True, timeout=30, check=False)
                    self.assertNotEqual(frozen.returncode, 0, frozen.stderr + frozen.stdout)
                    self.assertIn("Usage:", frozen.stderr + frozen.stdout)


if __name__ == "__main__":
    unittest.main()

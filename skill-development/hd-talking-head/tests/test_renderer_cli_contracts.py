"""Renderer CLI surface: no-arg runs must fail with their frozen usage."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
from PIL import Image


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

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg is unavailable")
    def test_paper_wrapper_normalizes_transparent_palette_png_to_rgba(self):
        from render_paper_collage import _normalize_png

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cutout-pal8.png"
            image = Image.new("P", (8, 6), 0)
            image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
            image.info["transparency"] = 0
            image.putpixel((3, 2), 1)
            image.save(source, format="PNG", optimize=False)
            target = root / "normalized.png"
            _normalize_png(shutil.which("ffmpeg"), source, target,
                           full_canvas=False, width=8, height=6)
            probe = subprocess.run(
                [shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=pix_fmt", "-of", "default=nw=1", str(target)],
                capture_output=True, text=True, check=True)
            self.assertIn("pix_fmt=rgba", probe.stdout)
            alpha = subprocess.run(
                [shutil.which("ffmpeg"), "-v", "error", "-i", str(target), "-vf",
                 "alphaextract", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
                capture_output=True, check=True)
            self.assertEqual(len(alpha.stdout), 8 * 6)
            self.assertEqual(min(alpha.stdout), 0)
            self.assertGreater(max(alpha.stdout), 0)


if __name__ == "__main__":
    unittest.main()

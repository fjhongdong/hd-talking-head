import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "relation_motion_capture.cjs"


class RelationMotionCaptureCliTests(unittest.TestCase):
    def run_cli(self, args):
        return subprocess.run(
            ["node", str(SCRIPT), *map(str, args)],
            cwd=ROOT.parents[1],
            text=True,
            capture_output=True,
        )

    def test_invalid_arguments_do_not_start_browser_or_write_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html = root / "scene.html"
            html.write_text("<html></html>")
            output = root / "frames"
            result = self.run_cli(
                [
                    "--html", html,
                    "--output", output,
                    "--duration", 48,
                    "--playwright", root / "missing-playwright.cjs",
                    "--browser", "/bin/false",
                    "--unknown", "x",
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertIn("unknown", (result.stderr + result.stdout).lower())

    def test_missing_html_is_rejected_without_writing_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "frames"
            result = self.run_cli(
                [
                    "--html", root / "missing.html",
                    "--output", output,
                    "--duration", 48,
                    "--playwright", root / "missing-playwright.cjs",
                    "--browser", "/bin/false",
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_existing_output_is_rejected_without_starting_browser_or_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html = root / "scene.html"
            html.write_text("<html></html>")
            output = root / "frames"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep")
            result = self.run_cli(
                [
                    "--html", html,
                    "--output", output,
                    "--duration", 48,
                    "--playwright", root / "missing-playwright.cjs",
                    "--browser", "/bin/false",
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), "keep")

    def test_boundary_holds_artifact_and_reports_completed_external_exit(self):
        state = "{frame:48,artifact_alpha:1,compositor_alpha:0,source_progress:1,connector_progress:1,hub_progress:1}"
        result = subprocess.run(
            ["node", "-e", f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({state},48,true) ? 0 : 1)"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_boundary_state_requires_exact_zero_compositor_alpha(self):
        result = subprocess.run(
            [
                "node", "-e",
                f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({{frame:48,artifact_alpha:1,compositor_alpha:0.01,source_progress:1,connector_progress:1,hub_progress:1}},48,true) ? 0 : 1)",
            ], text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_boundary_state_requires_exact_duration_frame(self):
        result = subprocess.run(
            [
                "node", "-e",
                f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({{frame:47,artifact_alpha:1,compositor_alpha:0,source_progress:1,connector_progress:1,hub_progress:1}},48,true) ? 0 : 1)",
            ], text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_regular_state_accepts_matching_finite_alpha(self):
        result = subprocess.run(
            [
                "node", "-e",
                f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({{frame:3,source_progress:0.5,connector_progress:0.25,hub_progress:0,artifact_alpha:1,compositor_alpha:1}},3,false) ? 0 : 1)",
            ], text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_regular_state_requires_all_finite_progress_values_in_range(self):
        for state in (
            "{frame:3,artifact_alpha:1,compositor_alpha:1,source_progress:0.5,connector_progress:0.5}",
            "{frame:3,artifact_alpha:1,compositor_alpha:1,source_progress:Number.NaN,connector_progress:0.5,hub_progress:0.5}",
            "{frame:3,artifact_alpha:1,compositor_alpha:1,source_progress:1.1,connector_progress:0.5,hub_progress:0.5}",
            "{frame:3,artifact_alpha:0.5,compositor_alpha:1,source_progress:1,connector_progress:1,hub_progress:1}",
            "{frame:3,artifact_alpha:1,compositor_alpha:1.01,source_progress:1,connector_progress:1,hub_progress:1}",
        ):
            result = subprocess.run(
                ["node", "-e", f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({state},3,false) ? 0 : 1)"],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_boundary_state_requires_all_progress_values_equal_one(self):
        state = "{frame:48,source_progress:1,connector_progress:1,hub_progress:0.99,artifact_alpha:1,compositor_alpha:0}"
        result = subprocess.run(
            ["node", "-e", f"const m=require({str(SCRIPT)!r}); process.exit(m.validateFrameState({state},48,true) ? 0 : 1)"],
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

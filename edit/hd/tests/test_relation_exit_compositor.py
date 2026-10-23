"""RelationMotion exits through the segment compositor to the same A-roll clock."""
from __future__ import annotations

import copy
from dataclasses import replace
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from PIL import Image

from edit.hd.tests import test_segment_render_components as fixtures
from edit.hd.tests.test_relation_motion_schema import component as relation_component
from edit.hd.tests.test_avatar_contract import avatar_fixture
from edit.hd.tests import test_semantic_state_identity as semantic_fixture
from edit.hd.tools import segment_render, visual_strategy


class RelationExitCompositorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "source").mkdir()
        self.job = SimpleNamespace(job_id="relation-exit", job_dir=self.root)
        self.component = relation_component()
        self.component["render_window"] = {
            "start_frame": 0,
            "end_frame": 120,
            "z_index": 0,
            "layout_slot": "main",
            "opacity": 1.0,
            "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
        }
        self.component["layer_role"] = "base"
        self.source = self.root / "source/relation.png"
        Image.new("RGB", (1080, 1920), (0, 0, 255)).save(self.source)
        source_sha = fixtures._sha256_file(self.source)
        self.recipe = fixtures._recipe([self.component], source_sha256=source_sha)
        self.recipe["composition"]["avatar"] = avatar_fixture(
            frames=120, source_sha256=source_sha
        )
        self.artifact = fixtures._artifact(
            self.job, self.recipe, self.component, self.source, alpha=False
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_native_full_window_relation_adds_frame_exact_aroll_exit(self) -> None:
        graph = segment_render.build_filter_graph(
            self.recipe, (self.artifact,), frames=120
        )
        self.assertIn("[0:v]fps=24,scale=1080:1920", graph)
        self.assertIn("[relation_aroll]", graph)
        self.assertIn("[relation_composite][relation_aroll]blend=", graph)
        self.assertIn("gte(N-1\\,119)", graph)
        self.assertNotIn("fade=t=out", graph)

    def test_five_semantic_families_share_single_composite_exit(self) -> None:
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            recipe = copy.deepcopy(self.recipe)
            native = semantic_fixture.SemanticStateIdentityTests().component(family)
            native.pop("render_window")
            recipe["components"][0].update(native)
            with self.subTest(family=family):
                graph = segment_render.build_filter_graph(recipe, (self.artifact,), frames=120)
                self.assertEqual(graph.count("blend=all_expr="), 1)
                self.assertIn("gte(N-1\\,119)", graph)
                self.assertNotIn("fade=t=out", graph)
                for mode in ("hidden", "full_frame"):
                    invalid = copy.deepcopy(recipe)
                    invalid["composition"]["presenter_mode"] = mode
                    with self.assertRaises(segment_render.SegmentRenderError):
                        segment_render.build_filter_graph(invalid, (self.artifact,), frames=120)

    def test_full_canvas_base_preserves_native_geometry(self) -> None:
        for slot in ("full_frame", "background_blur"):
            with self.subTest(slot=slot):
                artifact = replace(
                    self.artifact, layout_slot=slot,
                    safe_zone={"top": 0, "bottom": 0, "left": 0, "right": 0},
                )
                self.assertEqual(
                    segment_render._layout(artifact, "base"),
                    (0, 0, 1080, 1920, False),
                )

    def test_content_safe_slot_still_keeps_approved_margins(self) -> None:
        self.assertEqual(
            segment_render._layout(self.artifact, "base"),
            (40, 120, 1000, 1480, False),
        )

    def test_relation_exit_rejects_ambiguous_or_non_native_composition(self) -> None:
        cases = []
        partial = copy.deepcopy(self.recipe)
        partial["components"][0]["render_window"]["start_frame"] = 1
        partial_artifact = copy.deepcopy(self.artifact)
        partial_artifact.render_window["start_frame"] = 1
        cases.append((partial, (partial_artifact,)))

        hidden = copy.deepcopy(self.recipe)
        hidden["composition"]["presenter_mode"] = "hidden"
        hidden["composition"].pop("avatar")
        cases.append((hidden, (self.artifact,)))

        drifted = copy.deepcopy(self.recipe)
        drifted["components"][0]["renderer_version"] = "0.9.0"
        cases.append((drifted, (self.artifact,)))

        duplicate = copy.deepcopy(self.recipe)
        second = copy.deepcopy(duplicate["components"][0])
        second["component_id"] = "relation-second"
        duplicate["components"].append(second)
        second_artifact = replace(self.artifact, component_id="relation-second")
        cases.append((duplicate, (self.artifact, second_artifact)))

        for recipe, artifacts in cases:
            with self.subTest(recipe=recipe), self.assertRaises(
                segment_render.SegmentRenderError
            ):
                segment_render.build_filter_graph(recipe, artifacts, frames=120)

    def test_non_native_compositor_keeps_fade_and_limited_range_output(self) -> None:
        legacy = fixtures._component(
            "legacy",
            "local_material",
            fixtures._sha256_file(self.source),
            window=fixtures._window(start=0, end=120, z_index=0, slot="main"),
            alpha=False,
        )
        source_sha = fixtures._sha256_file(self.source)
        recipe = fixtures._recipe([legacy], source_sha256=source_sha)
        recipe["composition"]["avatar"] = avatar_fixture(
            frames=120, source_sha256=source_sha
        )
        artifact = fixtures._artifact(self.job, recipe, legacy, self.source, alpha=False)
        graph = segment_render.build_filter_graph(recipe, (artifact,), frames=120)
        self.assertNotIn("relation_aroll", graph)
        self.assertIn("fade=t=out:st=4.500000000:d=0.5:alpha=1", graph)
        self.assertTrue(
            graph.endswith(
                "scale=in_range=auto:out_range=tv,"
                "format=yuv420p,setparams=range=limited[out]"
            )
        )

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for pixel regression")
    def test_moving_aroll_exit_preserves_nonzero_source_seek(self) -> None:
        arroll = self.root / "moving-aroll.mp4"
        output = self.root / "seek-output.mp4"
        ffmpeg = shutil.which("ffmpeg")
        # Coprime step/modulus produce 223 distinct phases, beyond all 144 frames.
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
                "-f", "lavfi", "-i", "nullsrc=s=320x568:r=24:d=6",
                "-vf", "geq=lum='16+mod(X+N*11,223)':cb=128:cr=128,scale=1080:1920",
                "-frames:v", "144", "-c:v", "libx264", "-preset", "ultrafast",
                "-threads", "1", "-pix_fmt", "yuv420p", "-y", str(arroll),
            ],
            check=True, capture_output=True, timeout=60,
        )
        graph = segment_render.build_filter_graph(self.recipe, (self.artifact,), frames=120)
        command = segment_render._ffmpeg_command(
            arroll, (self.source,), (self.artifact,), graph, output, 1.0, 120
        )
        segment_render._default_ffmpeg_runner(command, 90)

        def frame_bytes(path: Path, frame: int) -> bytes:
            result = subprocess.run(
                [
                    ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
                    "-i", str(path), "-vf",
                    f"select='eq(n,{frame})',scale=160:284",
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ],
                check=True, capture_output=True, timeout=30,
            )
            self.assertEqual(len(result.stdout), 160 * 284 * 3)
            return result.stdout

        def difference(left: bytes, right: bytes) -> float:
            return sum(abs(a - b) for a, b in zip(left, right)) / len(left)

        final = frame_bytes(output, 119)
        expected = frame_bytes(arroll, 143)  # source offset 24 + local frame 119
        wrong_clock = frame_bytes(arroll, 119)
        previous = frame_bytes(arroll, 142)
        self.assertLess(difference(final, expected), 5.0)
        self.assertGreater(difference(final, wrong_clock), 15.0)
        self.assertGreater(difference(final, previous), 8.0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for pixel regression")
    def test_real_exit_blends_component_and_avatar_to_same_time_aroll(self) -> None:
        arroll = self.root / "arroll.mp4"
        output = self.root / "output.mp4"
        subprocess.run(
            [
                shutil.which("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error",
                "-f", "lavfi", "-i", "color=red:s=1080x1920:r=24:d=2.5",
                "-f", "lavfi", "-i", "color=green:s=1080x1920:r=24:d=2.5",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                "-frames:v", "120", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-y", str(arroll),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        graph = segment_render.build_filter_graph(self.recipe, (self.artifact,), frames=120)
        command = segment_render._ffmpeg_command(
            arroll, (self.source,), (self.artifact,), graph, output, 0.0, 120
        )
        segment_render._default_ffmpeg_runner(command, 90)

        def pixel(path: Path, frame: int, x: int, y: int) -> tuple[int, int, int]:
            result = subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error",
                    "-i", str(path), "-vf",
                    f"select='eq(n,{frame})',crop=2:2:{x}:{y},scale=1:1:flags=neighbor",
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return tuple(result.stdout[:3])

        blue_before = pixel(output, 107, 100, 100)
        exit_start = pixel(output, 108, 100, 100)
        middle = pixel(output, 114, 100, 100)
        last = pixel(output, 119, 100, 100)
        arroll_last = pixel(arroll, 119, 100, 100)
        self.assertGreater(blue_before[2], blue_before[1] + 100)
        self.assertLess(
            sum(abs(a - b) for a, b in zip(blue_before, exit_start)), 8,
            "exit start must still be fully composed; blend N is one-based",
        )
        self.assertGreater(middle[1], 20)
        self.assertGreater(middle[2], 20)
        self.assertLess(sum(abs(a - b) for a, b in zip(last, arroll_last)), 20)

        border = pixel(output, 107, 772, 1536)
        border_last = pixel(output, 119, 772, 1536)
        arroll_border_last = pixel(arroll, 119, 772, 1536)
        self.assertGreater(min(border), 180)
        self.assertLess(
            sum(abs(a - b) for a, b in zip(border_last, arroll_border_last)), 20
        )


if __name__ == "__main__":
    unittest.main()

"""Contract tests for the native 9:16 B-roll canary reel."""

from __future__ import annotations

import unittest
import tempfile
import os
import json
import hashlib
from pathlib import Path

from PIL import Image

from edit.hd.tools import render_broll_canary as canary


ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "edit/hd/canary/shot-spec.json"


class BrollCanaryTests(unittest.TestCase):
    def test_spec_is_native_vertical_and_has_five_distinct_grammars(self) -> None:
        spec = canary.load_spec(SPEC)

        self.assertEqual(
            (1080, 1920, 24),
            (spec["width"], spec["height"], spec["fps"]),
        )
        self.assertEqual(30, spec["duration"])
        self.assertEqual(5, len(spec["shots"]))
        self.assertEqual(5, len({shot["grammar"] for shot in spec["shots"]}))

    def test_canary_build_html_matches_the_approved_visual_source(self) -> None:
        source = canary.build_html(canary.load_spec(SPEC))

        self.assertEqual(
            "0425fe61a6353f49300fa6542b739d1a9657c3eeb4f9a65de83e02a9314c51b0",
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )
        self.assertIn('id="canary-root"', source)
        self.assertEqual(5, source.count('class="avatar-media-direct '))
        self.assertEqual(5, source.count('<span class="avatar-pin"></span>'))
        self.assertIn('object-position:50% 50%', source)

    def test_canary_uses_the_approved_template_and_five_grammars(self) -> None:
        source = canary.build_html(canary.load_spec(SPEC))

        self.assertEqual(
            ROOT / "edit/hd/canary/index.template.html",
            canary.CANARY_TEMPLATE,
        )
        self.assertIn('id="canary-root" data-composition-id="main"', source)
        self.assertNotIn('id="hd-visual-root"', source)
        self.assertNotIn("subtitle", source.lower())
        for grammar in {
            "text-column-converge",
            "timeline-travel",
            "bezier-source-converge-merge",
            "scanline-annotate-focus",
            "odometer-digit-roll",
        }:
            self.assertIn(f'data-grammar="{grammar}"', source)
        self.assertIn('<div class="survey-big" data-source>≈ 0</div>', source)
        self.assertIn('<div class="survey-big" data-source>多数</div>', source)
        self.assertIn('data-source>经验 × AI，才是不可复制的壁垒</div>', source)
        self.assertIn('data-source>7个项目</div>', source)
        self.assertIn('data-source>真正拉开差距的是工作方式</div>', source)
        self.assertIn('data-width="1080"', source)
        self.assertIn('data-height="1920"', source)
        self.assertIn('data-fps="24"', source)

    def test_production_canary_declares_a_dedicated_global_avatar_track(self) -> None:
        nodes = "\n".join(canary._production_media_nodes())

        self.assertIn('id="media-global-arroll-10"', nodes)
        self.assertIn('id="media-global-avatar-11"', nodes)
        self.assertIn('data-media-clock="global"', nodes)
        self.assertIn('data-track-index="11"', nodes)

    def test_timed_avatar_media_preserve_the_global_aroll_clock_and_crop(self) -> None:
        source = canary.build_html(canary.load_spec(SPEC))

        self.assertIn(
            'id="canary-root" data-composition-id="main" data-start="0" data-no-timeline',
            source,
        )
        self.assertEqual(5, source.count('id="media-avatar-'))
        self.assertEqual(5, source.count('data-media-clock="global"'))
        self.assertIn('data-media-start="24" data-media-clock="global"', source)
        self.assertEqual(1, source.count('id="media-official-shot-04"'))
        self.assertEqual(1, source.count('id="media-ai-shot-05"'))
        self.assertIn('width:214px;height:214px', source)
        self.assertIn('width:200px;height:200px', source)
        self.assertIn('object-position:50% 50%', source)
        self.assertIn('.avatar-pin{', source)

    def test_every_shot_is_an_independent_six_second_production_sequence(self) -> None:
        source = canary.build_html(canary.load_spec(SPEC))
        shots = canary.load_spec(SPEC)["shots"]

        for index, shot in enumerate(shots):
            self.assertEqual(index * 6, shot["start"])
            self.assertEqual(6, shot["duration"])
            self.assertIn(
                f'id="shot-{index + 1:02d}" data-grammar="{shot["grammar"]}" '
                f'data-system="{shot["system"]}" data-start="{index * 6}" '
                'data-duration="6"',
                source,
            )

    def test_official_shot_binds_evidence_to_lecturer_insight(self) -> None:
        source = canary.build_html(canary.load_spec(SPEC))

        self.assertIn('data-system="official-dossier"', source)
        self.assertIn('id="media-official-shot-04"', source)
        self.assertIn('class="avatar-shell avatar-bottom-left avatar-shot-04"', source)
        self.assertIn('official-chip official-chip-source', source)
        self.assertIn('official-chip official-chip-finding', source)
        self.assertIn('<div class="official-insight-label">讲师判断</div>', source)
        self.assertIn('<div class="official-insight-copy">先看真实资料，再给出判断</div>', source)

    def test_render_command_is_strict_portrait_and_single_worker(self) -> None:
        command = canary.build_render_command(
            Path("/runtime/hyperframes"),
            Path("/stage"),
            Path("/output.mp4"),
        )

        self.assertIn("--resolution=portrait", command)
        self.assertIn("--workers=1", command)
        self.assertIn("--low-memory-mode", command)
        self.assertIn("--strict", command)
        self.assertIn("--experimental-fast-capture", command)

    def test_media_commands_create_silent_native_assets_serially(self) -> None:
        commands = canary.build_media_commands(
            Path("avatar.mp4"),
            Path("official.mp4"),
            Path("ai.mp4"),
            Path("stage/media"),
        )

        self.assertEqual(["avatar", "official", "ai"], list(commands))
        self.assertTrue(all("-an" in command for command in commands.values()))
        self.assertTrue(all("-g" in command for command in commands.values()))
        self.assertTrue(all("24" == command[command.index("-g") + 1] for command in commands.values()))
        self.assertTrue(all("-sc_threshold" in command for command in commands.values()))
        avatar_filter = " ".join(commands["avatar"])
        self.assertIn("split=2[avatar_bg][avatar_fg]", avatar_filter)
        self.assertIn("gblur=sigma=12", avatar_filter)
        self.assertIn("scale=187:-2", avatar_filter)
        self.assertIn("overlay=(W-w)/2:(H-h)*0.40", avatar_filter)
        self.assertIn("pad=936:526", " ".join(commands["official"]))
        self.assertIn("-stream_loop", commands["official"])
        self.assertNotIn("-ss", commands["official"])
        self.assertIn("crop=1080:1920", " ".join(commands["ai"]))

    def test_probe_rejects_non_vertical_render(self) -> None:
        probe = {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "r_frame_rate": "24/1",
            "nb_read_frames": "720",
            "audio_streams": 0,
        }

        with self.assertRaisesRegex(canary.CanaryError, "1080x1920"):
            canary.validate_probe(probe)

    def test_probe_accepts_exact_silent_canary_contract(self) -> None:
        probe = {
            "codec_name": "h264",
            "width": 1080,
            "height": 1920,
            "pix_fmt": "yuv420p",
            "r_frame_rate": "24/1",
            "nb_read_frames": "720",
            "audio_streams": 0,
        }

        self.assertEqual(probe, canary.validate_probe(probe))

    def test_review_commands_sample_each_shot_after_motion_settles(self) -> None:
        commands = canary.build_keyframe_commands(
            Path("canary.mp4"), Path("keyframes")
        )

        self.assertEqual(5, len(commands))
        self.assertEqual(
            ["4.6", "10.6", "16.6", "22.6", "28.6"],
            [command[command.index("-ss") + 1] for command in commands],
        )
        self.assertEqual(
            [f"shot-{index:02d}.png" for index in range(1, 6)],
            [Path(command[-1]).name for command in commands],
        )

    def test_probe_and_decode_commands_are_complete(self) -> None:
        probe = canary.build_probe_command(Path("canary.mp4"))
        decode = canary.build_decode_command(Path("canary.mp4"))

        self.assertIn("-count_frames", probe)
        self.assertIn("stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames", probe)
        self.assertIn("-xerror", decode)
        self.assertEqual(["-f", "null", "-"], decode[-3:])

    def test_contact_sheet_uses_large_vertical_review_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = []
            for index in range(5):
                frame = root / f"shot-{index + 1:02d}.png"
                Image.new("RGB", (108, 192), (index * 40, 60, 90)).save(frame)
                frames.append(frame)
            output = root / "contact-sheet.png"

            canary.make_contact_sheet(frames, output)

            with Image.open(output) as sheet:
                self.assertEqual((864, 2304), sheet.size)

    def test_runtime_symlink_resolves_to_regular_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "hyperframes.mjs"
            target.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            target.chmod(0o755)
            link = root / "hyperframes"
            link.symlink_to(target)

            self.assertEqual(target.resolve(), canary.resolve_runtime(link))
            self.assertTrue(os.access(canary.resolve_runtime(link), os.X_OK))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class PreviewPublicContractTests(unittest.TestCase):
    def test_module_exposes_the_approved_preview_api(self) -> None:
        preview = importlib.import_module("edit.hd.tools.preview")

        self.assertEqual(
            preview.__all__,
            [
                "PreviewError",
                "PreviewResult",
                "build_preview_command",
                "validate_preview_command",
                "build_evidence_schedule",
                "validate_preview_media",
                "prepare_preview",
            ],
        )

    def test_command_maps_edited_aroll_audio_by_stream_copy_and_subtitles_last(self) -> None:
        preview = importlib.import_module("edit.hd.tools.preview")

        command = preview.build_preview_command(
            visual_track=Path("visual-track.mp4"),
            subtitle_track=Path("subtitles.webm"),
            edited_aroll=Path("edited-aroll.mp4"),
            cover_raster=Path("cover-delivery-raster.png"),
            output=Path("review.mp4"),
            width=1080,
            height=1920,
            fps=24,
            frames=48,
        )
        preview.validate_preview_command(command)

        graph = command[command.index("-filter_complex") + 1]
        self.assertLess(graph.index("[visual][cover]overlay"), graph.index("[covered][subtitles]overlay"))
        self.assertTrue(graph.rstrip().endswith("[outv]"))
        self.assertEqual(command[command.index("-map", command.index("-map") + 1) + 1], "2:a:0")
        audio_codec = command.index("-c:a")
        self.assertEqual(command[audio_codec + 1], "copy")
        forbidden = ("loudnorm", "volume", "aresample", "-af", "-filter:a")
        self.assertFalse(any(token in " ".join(command) for token in forbidden))

    def test_real_preview_replaces_only_frame_zero_and_copies_audio_packets(self) -> None:
        preview = importlib.import_module("edit.hd.tools.preview")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            visual = root / "visual.mp4"
            subtitles = root / "subtitles.webm"
            dialogue = root / "edited-aroll.mp4"
            cover = root / "cover.png"
            output = root / "review.mp4"
            commands = [
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=96x160:r=4:d=1.5", "-an", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "4", str(visual),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=black@0.0:s=96x160:r=4:d=1.5,format=yuva420p", "-an",
                    "-c:v", "libvpx-vp9", "-auto-alt-ref", "0", "-pix_fmt", "yuva420p",
                    str(subtitles),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=96x160:r=4:d=1.5", "-f", "lavfi", "-i",
                    "sine=frequency=733:sample_rate=48000:duration=1.5", "-map", "0:v:0",
                    "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-r", "4", "-c:a", "aac", "-ar", "48000",
                    "-ac", "2", "-shortest", str(dialogue),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=lime:s=96x160", "-frames:v", "1", str(cover),
                ],
            ]
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)

            command = preview.build_preview_command(
                visual_track=visual,
                subtitle_track=subtitles,
                edited_aroll=dialogue,
                cover_raster=cover,
                output=output,
                width=96,
                height=160,
                fps=4,
                frames=6,
            )
            subprocess.run(command, check=True, capture_output=True)

            summary = preview.validate_preview_media(
                output,
                edited_aroll=dialogue,
                cover_raster=cover,
                canvas={"width": 96, "height": 160, "fps": 4, "frames": 6, "duration": 1.5},
            )

            self.assertEqual((1, 1, 6), (summary["video_streams"], summary["audio_streams"], summary["frames"]))
            self.assertEqual(summary["source_audio_packet_hash"], summary["preview_audio_packet_hash"])
            self.assertEqual("cover", summary["frame_zero"])
            self.assertEqual("content", summary["frame_one"])
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-xerror", "-i", str(output),
                    "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
                ],
                check=True,
                capture_output=True,
            )
            invalid_commands = {
                "no-audio": [
                    "ffmpeg", "-v", "error", "-y", "-i", str(output),
                    "-map", "0:v:0", "-c:v", "copy", "-an",
                ],
                "two-audio": [
                    "ffmpeg", "-v", "error", "-y", "-i", str(output),
                    "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:0", "-c", "copy",
                ],
                "wrong-pixfmt": [
                    "ffmpeg", "-v", "error", "-y", "-i", str(output),
                    "-c:v", "libx264", "-pix_fmt", "yuv444p", "-c:a", "copy",
                ],
                "wrong-fps": [
                    "ffmpeg", "-v", "error", "-y", "-i", str(output),
                    "-vf", "fps=5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "copy",
                ],
                "audio-reencoded": [
                    "ffmpeg", "-v", "error", "-y", "-i", str(output),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
                ],
            }
            for label, invalid_command in invalid_commands.items():
                invalid = root / f"{label}.mp4"
                subprocess.run(
                    [*invalid_command, str(invalid)], check=True, capture_output=True,
                )
                with self.subTest(label=label):
                    with self.assertRaises(preview.PreviewError):
                        preview.validate_preview_media(
                            invalid,
                            edited_aroll=dialogue,
                            cover_raster=cover,
                            canvas={
                                "width": 96, "height": 160, "fps": 4,
                                "frames": 6, "duration": 1.5,
                            },
                        )
            held_cover = root / "held-cover.mp4"
            held_command = list(command)
            graph_index = held_command.index("-filter_complex") + 1
            held_command[graph_index] = held_command[graph_index].replace(
                "eq(n,0)", "lte(n,1)",
            ).replace("trim=end_frame=1", "trim=end_frame=2")
            held_command[-1] = str(held_cover)
            subprocess.run(held_command, check=True, capture_output=True)
            with self.assertRaises(preview.PreviewError):
                preview.validate_preview_media(
                    held_cover,
                    edited_aroll=dialogue,
                    cover_raster=cover,
                    canvas={"width": 96, "height": 160, "fps": 4, "frames": 6, "duration": 1.5},
                )
            truncated = root / "truncated.mp4"
            truncated.write_bytes(output.read_bytes()[: len(output.read_bytes()) // 2])
            with self.assertRaises(preview.PreviewError):
                preview.validate_preview_media(
                    truncated,
                    edited_aroll=dialogue,
                    cover_raster=cover,
                    canvas={"width": 96, "height": 160, "fps": 4, "frames": 6, "duration": 1.5},
                )

    def test_real_preview_preserves_copied_audio_longer_than_video_canvas(self) -> None:
        preview = importlib.import_module("edit.hd.tools.preview")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            visual = root / "visual.mp4"
            subtitles = root / "subtitles.webm"
            dialogue = root / "edited-aroll.mp4"
            cover = root / "cover.png"
            output = root / "review.mp4"
            commands = [
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=96x160:r=4:d=1.5", "-an", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "4", str(visual),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=black@0.0:s=96x160:r=4:d=1.5,format=yuva420p", "-an",
                    "-c:v", "libvpx-vp9", "-auto-alt-ref", "0", "-pix_fmt", "yuva420p",
                    str(subtitles),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=96x160:r=4:d=1.75", "-f", "lavfi", "-i",
                    "sine=frequency=733:sample_rate=48000:duration=1.75", "-map", "0:v:0",
                    "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-r", "4", "-c:a", "aac", "-ar", "48000",
                    "-ac", "2", "-shortest", str(dialogue),
                ],
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
                    "color=c=lime:s=96x160", "-frames:v", "1", str(cover),
                ],
            ]
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)

            command = preview.build_preview_command(
                visual_track=visual,
                subtitle_track=subtitles,
                edited_aroll=dialogue,
                cover_raster=cover,
                output=output,
                width=96,
                height=160,
                fps=4,
                frames=6,
            )
            subprocess.run(command, check=True, capture_output=True)

            summary = preview.validate_preview_media(
                output,
                edited_aroll=dialogue,
                cover_raster=cover,
                canvas={"width": 96, "height": 160, "fps": 4, "frames": 6, "duration": 1.5},
            )

            self.assertEqual(
                summary["source_audio_packet_hash"],
                summary["preview_audio_packet_hash"],
            )
            self.assertEqual(summary["frames"], 6)
            self.assertGreater(summary["duration"], 1.5)

    def test_full_v2_public_entry_uses_the_current_preview_builder(self) -> None:
        from edit.hd.tools import preview, preview_v2

        job = mock.Mock(version=2)
        expected = mock.Mock()
        with mock.patch.object(
            preview_v2,
            "prepare_preview_v2",
            return_value=expected,
        ) as builder:
            result = preview.prepare_preview(job)

        self.assertIs(result, expected)
        builder.assert_called_once_with(job)

if __name__ == "__main__":
    unittest.main()

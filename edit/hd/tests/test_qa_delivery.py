from __future__ import annotations

import copy
import importlib
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


def _write_pixel_frames(path: Path, values: list[int], *, fps: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-xerror", "-y",
            "-f", "rawvideo", "-pixel_format", "gray",
            "-video_size", "64x96", "-framerate", str(fps), "-i", "-",
            "-frames:v", str(len(values)), "-c:v", "ffv1", str(path),
        ],
        input=b"".join(bytes([value]) * (64 * 96) for value in values),
        check=True,
        capture_output=True,
    )


def _write_delivery_inventory_fixture(root: Path, qa_delivery) -> dict[str, object]:
    artifact_names = (
        "final.mp4", "cover-3x4.png", "cover-9x16.png", "cover-canvas.png",
        "subtitles.srt", "subtitles.webm", "edit-plan.json", "visual-plan.json",
        "asset-manifest.json", "qa-report.json", "inspection.json", "contact-sheet.png",
    )
    artifacts: dict[str, object] = {}
    for index, relative in enumerate(artifact_names, 1):
        content = b"" if relative == "subtitles.srt" else f"{relative}\n".encode()
        (root / relative).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        artifacts[relative] = {
            "source": {
                "path": (
                    "06-subtitles/subtitles.srt"
                    if relative == "subtitles.srt"
                    else f"source/{relative}"
                ),
                "sha256": digest,
                "bytes": len(content),
                "device": 1,
                "inode": index,
                "parent_device": 1,
                "parent_inode": 1,
            },
            "output": {"path": relative, "sha256": digest, "bytes": len(content)},
        }
    manifest = {
        "version": 1,
        "workflow": {"revision": 1, "sha256": "a" * 64, "bytes": 1},
        "retired_lineage": [],
        "artifacts": artifacts,
    }
    (root / "delivery-manifest.json").write_bytes(
        qa_delivery._canonical_json(manifest)
    )
    return manifest


def _write_cover_contract(
    job_dir: Path,
    aspect: str,
) -> tuple[tuple[Path, ...], Path, Path]:
    from edit.hd.tools import contract_artifacts

    specs = {
        "3:4": ("cover-3x4.png", {"width": 1080, "height": 1440}),
        "9:16": ("cover-9x16.png", {"width": 1080, "height": 1920}),
    }
    selected_name, canvas = specs[aspect]
    directory = Path(job_dir) / "04-cover"
    directory.mkdir(parents=True, exist_ok=True)
    for existing in directory.iterdir():
        if existing.is_file():
            existing.unlink()
    preliminary = (
        directory / "cover-base.png",
        directory / "cover-brief.json",
        directory / selected_name,
        directory / "cover-delivery-raster.png",
    )
    payloads = (
        b"cover-base",
        b"{}\n",
        f"cover-{aspect}".encode(),
        f"delivery-{aspect}".encode(),
    )
    for path, payload in zip(preliminary, payloads):
        path.write_bytes(payload)
    artifact_records = [
        {
            "path": f"04-cover/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in preliminary
    ]
    report = {
        "version": 1,
        "generator": "gbro-cover-design",
        "generation_id": "1" * 64,
        "mode": "openlux",
        "base_reused": False,
        "base_generation": "scene_only_no_people_no_text",
        "output_aspect_ratio": aspect,
        "direction_sha256": "2" * 64,
        "reference_sha256": "3" * 64,
        "model": "openlux-images",
        "prompt": "approved cover prompt",
        "workflow": {},
        "source_bindings": {},
        "face_frame": {},
        "person_composite": {},
        "alternative_evidence": None,
        "canvas": canvas,
        "artifacts": artifact_records,
        "output_sha256": {
            Path(record["path"]).name: record["sha256"]
            for record in artifact_records
        },
    }
    report_path = directory / "cover-report.json"
    report_path.write_bytes(contract_artifacts.canonical_json_bytes(report))
    return preliminary, report_path, directory / selected_name


def _run_strict_qa_for_subtitle_evidence(
    cues: list[dict[str, object]],
    *,
    omitted_kinds: set[str] | None = None,
) -> dict[str, object]:
    from edit.hd.tools import preview, qa_delivery, subtitles, visual_plan

    canvas = {"width": 1080, "height": 1920, "fps": 24, "frames": 48, "duration": 2.0}
    checked_subtitles = {"version": 1, "canvas": canvas, "cues": cues}
    checked_visual = {
        "version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24.0},
        "duration": 2.0,
        "segments": [{
            "segment_id": "seg-001", "start": 0.0, "end": 2.0,
            "implementation": "code", "visual_type": "chart",
        }],
    }
    timeline_map = {
        "version": 1,
        "output_duration": 2.0,
        "segments": [{
            "source_start": 0.0, "source_end": 2.0,
            "timeline_start": 0.0, "timeline_end": 2.0,
        }],
    }
    schedule = preview.build_evidence_schedule(
        {"version": 1}, timeline_map, checked_visual, checked_subtitles,
    )
    omitted = omitted_kinds or set()
    evidence = [
        {
            **item,
            "sha256": f"{index:x}" * 64,
            "bytes": 1,
            "device": 1,
            "inode": index,
            "parent_device": 1,
            "parent_inode": 1,
        }
        for index, item in enumerate(schedule, 1)
        if item["kind"] not in omitted
    ]
    identity = {
        "path": "08-preview/review.mp4", "sha256": "f" * 64, "bytes": 1,
        "device": 1, "inode": 99, "parent_device": 1, "parent_inode": 1,
    }
    with (
        mock.patch.object(visual_plan, "validate_visual_plan", return_value=checked_visual),
        mock.patch.object(subtitles, "validate_subtitle_plan", return_value=checked_subtitles),
        mock.patch.object(
            preview, "validate_preview_media",
            return_value={"video_streams": 1, "audio_streams": 1, "frames": 48},
        ),
        mock.patch.object(
            qa_delivery, "_pixel_checks", return_value={"sample_paths": []},
        ),
        mock.patch.object(qa_delivery, "_verify_qa_evidence", return_value=evidence),
    ):
        report, _ = qa_delivery.run_strict_qa(
            preview=Path("08-preview/review.mp4"),
            edited_aroll=Path("edited-aroll.mp4"),
            cover_raster=Path("cover.png"),
            edit_plan={"version": 1},
            timeline_map=timeline_map,
            visual_plan=checked_visual,
            subtitle_plan=checked_subtitles,
            asset_manifest={"version": 1},
            evidence=evidence,
            workflow_binding={
                "workflow": {"revision": 1, "sha256": "a" * 64, "bytes": 1},
                "plan_hashes": {
                    "edit_plan": "b" * 64,
                    "visual_plan": "c" * 64,
                    "subtitle_plan": "d" * 64,
                },
                "inputs": {"preview": identity},
            },
        )
    return report


class QaDeliveryPublicContractTests(unittest.TestCase):
    def test_module_exposes_the_approved_qa_delivery_api(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")

        self.assertEqual(
            qa_delivery.__all__,
            [
                "QaDeliveryError",
                "DeliveryResult",
                "StableGenerationPublisher",
                "run_strict_qa",
                "validate_qa_report",
                "validate_delivery_inventory",
                "prepare_delivery",
            ],
        )

    def test_stable_publisher_lock_resists_job_path_replacement(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            job_dir = parent / "job-001"
            job_dir.mkdir()
            publisher = qa_delivery.StableGenerationPublisher(job_dir, "09-delivery")
            publisher.acquire()
            moved = parent / "held-original"
            os.rename(job_dir, moved)
            job_dir.mkdir()
            sentinel = job_dir / "unknown-owner.bin"
            sentinel.write_bytes(b"do-not-touch")
            script = (
                "from pathlib import Path; import sys; "
                "from edit.hd.tools.qa_delivery import ("
                "QaDeliveryError, StableGenerationPublisher); "
                f"p=StableGenerationPublisher(Path({str(job_dir)!r}), '09-delivery'); "
                "\ntry: p.acquire(blocking=False)\n"
                "except QaDeliveryError: sys.exit(23)\n"
                "else: p.release(); sys.exit(0)"
            )
            contender = subprocess.run(
                ["python3", "-c", script], cwd=Path(__file__).resolve().parents[3],
                capture_output=True, text=True,
            )
            publisher.release()
            self.assertEqual(23, contender.returncode, contender.stderr)
            self.assertEqual(b"do-not-touch", sentinel.read_bytes())

    def test_stable_publisher_closes_every_fd_and_preserves_keyboard_interrupt(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            job_dir = Path(directory) / "job-001"
            job_dir.mkdir()
            publisher = qa_delivery.StableGenerationPublisher(job_dir, "09-delivery")
            publisher.acquire()
            descriptors = {publisher._parent_descriptor, publisher._lock_descriptor}
            closed: list[int] = []
            real_close = os.close

            def close_then_fail(descriptor: int) -> None:
                closed.append(descriptor)
                real_close(descriptor)
                raise OSError("injected close failure")

            with mock.patch.object(qa_delivery.os, "close", side_effect=close_then_fail):
                with self.assertRaises(qa_delivery.QaDeliveryError):
                    publisher.release()
            self.assertEqual(descriptors, set(closed))
            self.assertEqual(-1, publisher._parent_descriptor)
            self.assertEqual(-1, publisher._lock_descriptor)

            interrupted = qa_delivery.StableGenerationPublisher(job_dir, "08-preview")
            with mock.patch.object(
                qa_delivery.fcntl, "flock", side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    interrupted.acquire()
            self.assertEqual(-1, interrupted._parent_descriptor)
            self.assertEqual(-1, interrupted._lock_descriptor)

            combined = qa_delivery.StableGenerationPublisher(job_dir, "08-preview")
            combined_closed: list[int] = []

            def combined_close(descriptor: int) -> None:
                combined_closed.append(descriptor)
                real_close(descriptor)
                raise OSError("secondary close failure")

            with (
                mock.patch.object(qa_delivery.fcntl, "flock", side_effect=KeyboardInterrupt),
                mock.patch.object(qa_delivery.os, "close", side_effect=combined_close),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    combined.acquire()
            self.assertTrue(combined_closed)
            self.assertEqual(-1, combined._parent_descriptor)
            self.assertEqual(-1, combined._lock_descriptor)

    def test_retirement_lineage_cannot_escape_generation_directory(self) -> None:
        from edit.hd.tools import preview, qa_delivery

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "victim.bin"
            victim.write_bytes(b"MUST-SURVIVE")
            preview_backup = root / "preview-backup"
            delivery_backup = root / "delivery-backup"
            preview_backup.mkdir()
            delivery_backup.mkdir()
            malicious = {
                "sha256": "a" * 64, "bytes": len(b"MUST-SURVIVE"),
                "device": 1, "inode": 1, "parent_device": 1, "parent_inode": 1,
            }
            with self.assertRaises(preview.PreviewError):
                preview._zero_preview_generation(
                    preview_backup,
                    [{**malicious, "path": "08-preview/../../victim.bin"}],
                )
            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._zero_delivery_generation(
                    delivery_backup,
                    [{**malicious, "path": "09-delivery/../../victim.bin"}],
                )
            self.assertEqual(b"MUST-SURVIVE", victim.read_bytes())

    def test_evidence_schedule_is_dynamic_and_includes_cover_cut_cue_and_visual_samples(self) -> None:
        preview = importlib.import_module("edit.hd.tools.preview")
        edit_plan = {
            "version": 1,
            "cleanup_proposal": {
                "version": 1,
                "segments": [
                    {"action": "keep", "source_start": 0.0, "source_end": 1.0},
                    {"action": "keep", "source_start": 1.0, "source_end": 2.0},
                    {"action": "keep", "source_start": 2.0, "source_end": 3.0},
                ],
            },
        }
        timeline_map = {
            "version": 1,
            "output_duration": 3.0,
            "segments": [
                {
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "timeline_start": 0.0,
                    "timeline_end": 1.0,
                },
                {
                    "source_start": 1.0,
                    "source_end": 2.0,
                    "timeline_start": 1.0,
                    "timeline_end": 2.0,
                },
                {
                    "source_start": 2.0,
                    "source_end": 3.0,
                    "timeline_start": 2.0,
                    "timeline_end": 3.0,
                },
            ],
        }
        visual_plan = {
            "version": 1,
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "duration": 3.0,
            "segments": [
                {"segment_id": "seg-person", "start": 0.0, "end": 1.0, "implementation": "arroll", "visual_type": "teacher"},
                {"segment_id": "seg-source", "start": 1.0, "end": 2.0, "implementation": "official", "visual_type": "report"},
                {"segment_id": "seg-chart", "start": 2.0, "end": 3.0, "implementation": "code", "visual_type": "chart"},
            ],
        }
        subtitle_plan = {
            "version": 1,
            "canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 72, "duration": 3.0},
            "cues": [
                {"id": "cue-a", "start": 0.25, "end": 0.75},
                {"id": "cue-b", "start": 2.25, "end": 2.75},
            ],
        }

        schedule = preview.build_evidence_schedule(
            edit_plan, timeline_map, visual_plan, subtitle_plan
        )

        kinds = [record["kind"] for record in schedule]
        self.assertEqual(2, kinds.count("subtitle_midpoint"))
        self.assertEqual(6, kinds.count("cut_boundary"))
        self.assertEqual(2, kinds.count("cover_frame"))
        self.assertEqual(3, kinds.count("visual_keyframe"))
        self.assertEqual(len(schedule), len({record["path"] for record in schedule}))

    def test_strict_qa_accepts_empty_cues_without_subtitle_evidence(self) -> None:
        report = _run_strict_qa_for_subtitle_evidence([])

        self.assertNotIn("subtitle_midpoint", {item["kind"] for item in report["evidence"]})
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual([], checks["duplicate_subtitles"]["evidence"])
        self.assertEqual([], checks["subtitle_safe_zones"]["evidence"])

    def test_strict_qa_rejects_nonempty_cues_without_subtitle_evidence(self) -> None:
        from edit.hd.tools import qa_delivery

        cues = [{"id": "cue-001", "start": 0.25, "end": 0.75, "text": "保留字幕"}]
        with self.assertRaises(qa_delivery.QaDeliveryError):
            _run_strict_qa_for_subtitle_evidence(cues, omitted_kinds={"subtitle_midpoint"})

    def test_strict_qa_rejects_empty_cues_without_cover_or_visual_evidence(self) -> None:
        from edit.hd.tools import qa_delivery

        for kind in ("cover_frame", "visual_keyframe"):
            with self.subTest(kind=kind):
                with self.assertRaises(qa_delivery.QaDeliveryError):
                    _run_strict_qa_for_subtitle_evidence([], omitted_kinds={kind})

    def test_pixel_qa_rejects_black_white_flash_and_freeze_real_media(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = {
                "black": "color=c=black:s=64x96:r=24:d=2",
                "white-flash": (
                    "color=c=0x202020:s=64x96:r=24:d=2,"
                    "drawbox=color=white:t=fill:enable='eq(n,12)'"
                ),
                "freeze": "color=c=gray:s=64x96:r=24:d=2",
            }
            for label, source in media.items():
                path = root / f"{label}.mp4"
                subprocess.run(
                    [
                        "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi",
                        "-i", source, "-frames:v", "48", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-r", "24", str(path),
                    ],
                    check=True, capture_output=True,
                )
                with self.subTest(label=label):
                    with self.assertRaises(qa_delivery.QaDeliveryError):
                        qa_delivery._pixel_checks(
                            path, width=64, height=96, fps=24, frames=48,
                        )

    def test_pixel_qa_accepts_slowly_changing_real_media(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slow-motion.mkv"
            frames = []
            for frame_index in range(48):
                pixels = bytearray([64] * (64 * 96))
                x = frame_index % 62
                for y in (47, 48):
                    for offset in (0, 1):
                        pixels[y * 64 + x + offset] = 192
                frames.append(bytes(pixels))
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y",
                    "-f", "rawvideo", "-pixel_format", "gray",
                    "-video_size", "64x96", "-framerate", "24", "-i", "-",
                    "-frames:v", "48", "-c:v", "ffv1", str(path),
                ],
                input=b"".join(frames), check=True, capture_output=True,
            )

            result = qa_delivery._pixel_checks(
                path, width=64, height=96, fps=24, frames=48,
            )

            self.assertEqual(0, result["freeze_run"])

    def test_pixel_qa_counts_a_freeze_interval_starting_at_frame_zero(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        values = [64] * 25 + [72 + index * 3 for index in range(23)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "leading-one-second-freeze.mkv"
            _write_pixel_frames(path, values, fps=24)

            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    path, width=64, height=96, fps=24, frames=48,
                )

    def test_pixel_qa_rejects_an_entirely_static_code_segment(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        changing_prefix = [48 + index * 3 for index in range(24)]
        values = changing_prefix + [176] * 25
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entire-code-segment-static.mkv"
            _write_pixel_frames(path, values, fps=24)

            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    path, width=64, height=96, fps=24, frames=49,
                    checked_visual={
                        "segments": [
                            {"start": 0.0, "end": 1.0, "implementation": "arroll"},
                            {
                                "start": 1.0,
                                "end": 49 / 24,
                                "implementation": "code",
                            },
                        ],
                    },
                )

    def test_pixel_qa_allows_only_one_second_tail_hold_in_a_code_segment(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")

        animation = [48 + (index * 7 % 144) for index in range(48)]
        code_tail_hold = animation + [animation[-1]] * 24
        code_plan = {
            "segments": [
                {"start": 0.0, "end": 1.0, "implementation": "arroll"},
                {"start": 1.0, "end": 3.0, "implementation": "code"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "code-tail-one-second.mkv"
            _write_pixel_frames(allowed, code_tail_hold, fps=24)

            result = qa_delivery._pixel_checks(
                allowed, width=64, height=96, fps=24, frames=72,
                checked_visual=code_plan,
            )

            self.assertEqual(24, result["freeze_run"])

            too_long = root / "code-tail-too-long.mkv"
            longer_animation = animation[:-1]
            _write_pixel_frames(
                too_long, longer_animation + [longer_animation[-1]] * 25, fps=24,
            )
            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    too_long, width=64, height=96, fps=24, frames=72,
                    checked_visual=code_plan,
                )

            for route in ("arroll", "official", "ai"):
                with self.subTest(route=route):
                    with self.assertRaises(qa_delivery.QaDeliveryError):
                        qa_delivery._pixel_checks(
                            allowed, width=64, height=96, fps=24, frames=72,
                            checked_visual={
                                "segments": [{
                                    "start": 0.0, "end": 3.0, "implementation": route,
                                }],
                            },
                        )

            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    allowed, width=64, height=96, fps=24, frames=72,
                    checked_visual={
                        "segments": [
                            {"start": 0.0, "end": 2.0, "implementation": "arroll"},
                            {"start": 2.0, "end": 3.0, "implementation": "code"},
                        ],
                    },
                )

    def test_pixel_qa_does_not_round_fractional_fps_above_one_second(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fps, frozen_intervals, frames in (
                (23.976, 24, 72),
                (29.97, 30, 90),
            ):
                with self.subTest(fps=fps):
                    animation = [
                        48 + (index * 7 % 144)
                        for index in range(frames - frozen_intervals)
                    ]
                    path = root / f"fractional-{fps}.mkv"
                    _write_pixel_frames(
                        path, animation + [animation[-1]] * frozen_intervals, fps=fps,
                    )
                    with self.assertRaises(qa_delivery.QaDeliveryError):
                        qa_delivery._pixel_checks(
                            path, width=64, height=96, fps=fps, frames=frames,
                            checked_visual={
                                "segments": [{
                                    "start": 1.0,
                                    "end": frames / fps,
                                    "implementation": "code",
                                }],
                            },
                        )

    def test_pixel_qa_allows_fractional_fps_tail_hold_below_one_second(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fps, frozen_intervals, frames in (
                (23.976, 23, 72),
                (29.97, 29, 90),
            ):
                with self.subTest(fps=fps):
                    animation = [
                        48 + (index * 7 % 144)
                        for index in range(frames - frozen_intervals)
                    ]
                    path = root / f"fractional-below-one-second-{fps}.mkv"
                    _write_pixel_frames(
                        path, animation + [animation[-1]] * frozen_intervals, fps=fps,
                    )

                    result = qa_delivery._pixel_checks(
                        path, width=64, height=96, fps=fps, frames=frames,
                        checked_visual={
                            "segments": [{
                                "start": 1.0,
                                "end": frames / fps,
                                "implementation": "code",
                            }],
                        },
                    )

                    self.assertEqual(frozen_intervals, result["freeze_run"])

    def test_pixel_qa_uses_half_open_unaligned_code_segment_times(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        animation = [48 + (index * 7 % 144) for index in range(25)]
        tail_through_frame_48 = animation + [animation[-1]] * 24
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "unaligned-tail.mkv"
            _write_pixel_frames(path, tail_through_frame_48, fps=24)

            result = qa_delivery._pixel_checks(
                path, width=64, height=96, fps=24, frames=49,
                checked_visual={
                    "segments": [{
                        "start": 0.5, "end": 2.01, "implementation": "code",
                    }],
                },
            )
            self.assertEqual(24, result["freeze_run"])

            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    path, width=64, height=96, fps=24, frames=49,
                    checked_visual={
                        "segments": [{
                            "start": 1.02, "end": 2.03, "implementation": "code",
                        }],
                    },
                )

            early_tail = root / "unaligned-early-tail.mkv"
            before = [48 + (index * 7 % 144) for index in range(24)]
            values = before + [before[-1]] * 24 + [before[-1] + 7]
            _write_pixel_frames(early_tail, values, fps=24)
            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    early_tail, width=64, height=96, fps=24, frames=49,
                    checked_visual={
                        "segments": [{
                            "start": 0.5, "end": 2.01, "implementation": "code",
                        }],
                    },
                )

    def test_pixel_qa_rejects_a_freeze_crossing_adjacent_code_segments(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        before = [48 + (index * 7 % 144) for index in range(37)]
        after = [56 + (index * 7 % 136) for index in range(11)]
        values = before + [before[-1]] * 24 + after
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cross-code-boundary.mkv"
            _write_pixel_frames(path, values, fps=24)

            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery._pixel_checks(
                    path, width=64, height=96, fps=24, frames=72,
                    checked_visual={
                        "segments": [
                            {"start": 0.0, "end": 1.52, "implementation": "code"},
                            {"start": 1.52, "end": 2.5, "implementation": "code"},
                            {"start": 2.5, "end": 3.0, "implementation": "ai"},
                        ],
                    },
                )

    def test_pixel_qa_allows_independent_tail_holds_in_multiple_code_segments(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        first_animation = [40 + index * 3 for index in range(24)]
        bridge = [120 + index * 3 for index in range(24)]
        second_animation = [50 + index * 4 for index in range(24)]
        values = (
            first_animation + [first_animation[-1]] * 24
            + bridge
            + second_animation + [second_animation[-1]] * 24
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "independent-code-tails.mkv"
            _write_pixel_frames(path, values, fps=24)

            result = qa_delivery._pixel_checks(
                path, width=64, height=96, fps=24, frames=120,
                checked_visual={
                    "segments": [
                        {"start": 0.0, "end": 2.0, "implementation": "code"},
                        {"start": 2.0, "end": 3.0, "implementation": "arroll"},
                        {"start": 3.0, "end": 5.0, "implementation": "code"},
                    ],
                },
            )

            self.assertEqual(24, result["freeze_run"])

    def test_pixel_qa_accepts_a_persistent_high_contrast_scene_cut(self) -> None:
        qa_delivery = importlib.import_module("edit.hd.tools.qa_delivery")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene-cut.mkv"
            bright = bytes([230] * (64 * 96))
            dark = bytes([37] * (64 * 96))
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-xerror", "-y",
                    "-f", "rawvideo", "-pixel_format", "gray",
                    "-video_size", "64x96", "-framerate", "24", "-i", "-",
                    "-frames:v", "48", "-c:v", "ffv1", str(path),
                ],
                input=bright * 24 + dark * 24,
                check=True,
                capture_output=True,
            )

            result = qa_delivery._pixel_checks(
                path, width=64, height=96, fps=24, frames=48,
            )

            self.assertLess(result["black_min"], 40)
            self.assertGreater(result["white_max"], 220)

    def test_delivery_inventory_accepts_only_the_exact_empty_subtitle_artifact(self) -> None:
        from edit.hd.tools import qa_delivery

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _write_delivery_inventory_fixture(root, qa_delivery)

            self.assertIs(
                manifest,
                qa_delivery.validate_delivery_inventory(root, manifest),
            )
            subtitle = manifest["artifacts"]["subtitles.srt"]
            empty_sha256 = hashlib.sha256(b"").hexdigest()
            self.assertEqual(0, subtitle["source"]["bytes"])
            self.assertEqual(empty_sha256, subtitle["source"]["sha256"])
            self.assertEqual(0, subtitle["output"]["bytes"])
            self.assertEqual(empty_sha256, subtitle["output"]["sha256"])

    def test_delivery_inventory_rejects_every_other_empty_or_mismatched_binding(self) -> None:
        from edit.hd.tools import qa_delivery

        cases = (
            "other-empty-artifact",
            "wrong-subtitle-source-path",
            "wrong-subtitle-output-path",
            "wrong-empty-size",
            "wrong-empty-hash",
            "nonempty-subtitle-output",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = _write_delivery_inventory_fixture(root, qa_delivery)
                subtitle = manifest["artifacts"]["subtitles.srt"]
                if case == "other-empty-artifact":
                    path = root / "inspection.json"
                    path.write_bytes(b"")
                    binding = manifest["artifacts"]["inspection.json"]
                    for record in (binding["source"], binding["output"]):
                        record["bytes"] = 0
                        record["sha256"] = hashlib.sha256(b"").hexdigest()
                elif case == "wrong-subtitle-source-path":
                    subtitle["source"]["path"] = "06-subtitles/other.srt"
                elif case == "wrong-subtitle-output-path":
                    subtitle["output"]["path"] = "06-subtitles/subtitles.srt"
                elif case == "wrong-empty-size":
                    subtitle["source"]["bytes"] = 1
                    subtitle["output"]["bytes"] = 1
                elif case == "wrong-empty-hash":
                    subtitle["source"]["sha256"] = "f" * 64
                    subtitle["output"]["sha256"] = "f" * 64
                elif case == "nonempty-subtitle-output":
                    content = b"unexpected subtitle"
                    (root / "subtitles.srt").write_bytes(content)
                    subtitle["output"]["bytes"] = len(content)
                    subtitle["output"]["sha256"] = hashlib.sha256(content).hexdigest()
                (root / "delivery-manifest.json").write_bytes(
                    qa_delivery._canonical_json(manifest)
                )

                with self.assertRaises(qa_delivery.QaDeliveryError):
                    qa_delivery.validate_delivery_inventory(root, manifest)

    def test_delivery_copies_only_approved_inventory_and_inspection_is_task_one_bytes(self) -> None:
        from edit.hd.tools import qa_delivery, state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video = root / "source.mp4"
            script = root / "script.txt"
            video.write_bytes(b"source-video")
            script.write_text("严格交付", encoding="utf-8")
            job = state.create_job(root, video, script, profile="legacy-v1")
            initial_fd_count = len(os.listdir("/dev/fd"))
            identity = {
                "path": "08-preview/review.mp4", "sha256": "a" * 64, "bytes": 1,
                "device": 1, "inode": 1, "parent_device": 1, "parent_inode": 1,
            }
            qa_report = {
                "version": 1, "status": "pass",
                "workflow": {"revision": 1, "sha256": "b" * 64, "bytes": 1},
                "plan_hashes": {
                    "edit_plan": "c" * 64, "visual_plan": "d" * 64,
                    "subtitle_plan": "e" * 64,
                },
                "inputs": {"preview": identity},
                "retired_lineage": [],
                "media": {"video_streams": 1, "audio_streams": 1, "frames": 48},
                "evidence": [{
                    "id": "cover-000", "kind": "cover_frame", "timestamp": 0.0,
                    **{**identity, "path": "keyframes/cover/frame-000.png"},
                }],
                "checks": [
                    {"id": check_id, "status": "pass", "evidence": ["08-preview/review.mp4"]}
                    for check_id in (
                        "one_video_one_audio", "complete_decode", "audio_packet_copy",
                        "black_frames", "white_flashes", "freeze_runs",
                        "duplicate_subtitles", "subtitle_safe_zones", "cover_frame_zero",
                        "content_frame_one",
                    )
                ],
            }

            stage_files = {
                "inspect": ("01-inspect", {"report.json": b"task-one-inspection\n"}),
                "speech_cleanup": ("02-speech-cleanup", {"report.json": b"speech\n"}),
                "edit_structure": (
                    "03-edit-structure",
                    {"edit-plan.json": b'{"version":1}\n'},
                ),
                "visual_direction": (
                    "04-visual-direction",
                    {"visual-plan.json": b'{"version":1}\n'},
                ),
                "visual_assets": (
                    "05-visual-assets",
                    {"asset-manifest.json": b'{"version":1}\n'},
                ),
                "subtitles": (
                    "06-subtitles",
                    {"subtitles.srt": b"strict srt\n", "subtitles.webm": b"alpha-track"},
                ),
                "cover": (
                    "07-cover",
                    {
                        "cover-3x4.png": b"cover-3x4",
                        "cover-9x16.png": b"cover-9x16",
                        "cover-delivery-raster.png": b"cover-canvas",
                    },
                ),
                "preview": (
                    "08-preview",
                    {
                        "review.mp4": b"approved-review",
                        "qa-report.json": (
                            json.dumps(qa_report, sort_keys=True, separators=(",", ":")) + "\n"
                        ).encode(),
                        "contact-sheet.png": b"contact",
                        "keyframes/cover/frame-000.png": b"frame-zero",
                        "keyframes/cover/frame-001.png": b"frame-one",
                    },
                ),
            }
            for stage_id in state.STAGE_IDS[:-1]:
                directory_name, contents = stage_files[stage_id]
                base = job.job_dir / directory_name
                artifacts = []
                for relative, source in contents.items():
                    path = base / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source)
                    artifacts.append(path)
                state.mark_ready(job, stage_id, artifacts)
                state.approve(job, stage_id)

            inspection = job.job_dir / "01-inspect/report.json"
            inspection_status = inspection.stat()
            environment = os.environ.copy()
            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "prepared"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            prepared = [
                path for path in job.job_dir.iterdir()
                if path.name.startswith(".09-delivery.stage-")
            ]
            self.assertEqual(1, len(prepared))
            prepared_inode = (prepared[0] / "final.mp4").stat().st_ino
            result = qa_delivery.prepare_delivery(job)

            self.assertEqual("ready_for_review", job.stages["delivery"]["status"])
            self.assertEqual(prepared_inode, (result.directory / "final.mp4").stat().st_ino)
            self.assertEqual(b"task-one-inspection\n", (result.directory / "inspection.json").read_bytes())
            self.assertEqual(b"approved-review", (result.directory / "final.mp4").read_bytes())
            expected = {
                "final.mp4", "cover-3x4.png", "cover-9x16.png", "cover-canvas.png",
                "subtitles.srt", "subtitles.webm", "edit-plan.json", "visual-plan.json",
                "asset-manifest.json", "qa-report.json", "inspection.json",
                "contact-sheet.png", "keyframes/cover/frame-000.png",
                "keyframes/cover/frame-001.png", "delivery-manifest.json",
            }
            actual = {
                path.relative_to(result.directory).as_posix()
                for path in result.directory.rglob("*") if path.is_file()
            }
            self.assertEqual(expected, actual)
            manifest = json.loads((result.directory / "delivery-manifest.json").read_text())
            source = manifest["artifacts"]["inspection.json"]["source"]
            self.assertEqual("01-inspect/report.json", source["path"])
            self.assertEqual(inspection_status.st_dev, source["device"])
            self.assertEqual(inspection_status.st_ino, source["inode"])
            self.assertEqual(len(b"task-one-inspection\n"), source["bytes"])
            first_inode = (result.directory / "final.mp4").stat().st_ino
            state.approve(job, "delivery")
            state.revise(job, "delivery", "更新交付代")

            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "old-moved"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            self.assertFalse((job.job_dir / "09-delivery").exists())

            revised = qa_delivery.prepare_delivery(job)

            self.assertEqual("ready_for_review", job.stages["delivery"]["status"])
            self.assertNotEqual(first_inode, (revised.directory / "final.mp4").stat().st_ino)
            self.assertEqual(b"task-one-inspection\n", (revised.directory / "inspection.json").read_bytes())
            state.approve(job, "delivery")
            state.revise(job, "delivery", "new-installed crash")
            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "new-installed"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3], env=environment,
                capture_output=True, text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            installed_inode = (job.job_dir / "09-delivery/final.mp4").stat().st_ino
            revised = qa_delivery.prepare_delivery(job)
            self.assertEqual(installed_inode, (revised.directory / "final.mp4").stat().st_ino)
            state.approve(job, "delivery")
            state.revise(job, "delivery", "workflow-ready crash")
            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "workflow-ready"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3], env=environment,
                capture_output=True, text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            ready_inode = (job.job_dir / "09-delivery/final.mp4").stat().st_ino
            revised = qa_delivery.prepare_delivery(job)
            self.assertEqual("ready_for_review", job.stages["delivery"]["status"])
            self.assertEqual(ready_inode, (revised.directory / "final.mp4").stat().st_ino)
            state.approve(job, "delivery")
            state.revise(job, "delivery", "metadata-retired crash")
            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "metadata-retired"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3], env=environment,
                capture_output=True, text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            retired_inode = (job.job_dir / "09-delivery/final.mp4").stat().st_ino
            revised = qa_delivery.prepare_delivery(job)
            self.assertEqual(retired_inode, (revised.directory / "final.mp4").stat().st_ino)
            state.approve(job, "delivery")
            state.revise(job, "delivery", "marker-moved crash")
            environment["HD_DELIVERY_CRASH_CHECKPOINT"] = "marker-moved"
            crashed = subprocess.run(
                [
                    "python3", "-c",
                    (
                        "from pathlib import Path; "
                        "from edit.hd.tools.state import load_job; "
                        "from edit.hd.tools.qa_delivery import prepare_delivery; "
                        f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[3], env=environment,
                capture_output=True, text=True,
            )
            self.assertEqual(91, crashed.returncode, crashed.stderr)
            marker_inode = (job.job_dir / "09-delivery/final.mp4").stat().st_ino
            revised = qa_delivery.prepare_delivery(job)
            self.assertEqual(marker_inode, (revised.directory / "final.mp4").stat().st_ino)
            self.assertFalse(any(
                path.stat().st_size
                for path in job.job_dir.iterdir()
                if path.name.startswith(".09-delivery.marker-retired-")
            ))
            state.approve(job, "delivery")
            state.revise(job, "delivery", "concurrent publishers")
            environment.pop("HD_DELIVERY_CRASH_CHECKPOINT", None)
            command = [
                "python3", "-c",
                (
                    "from pathlib import Path; "
                    "from edit.hd.tools.state import load_job; "
                    "from edit.hd.tools.qa_delivery import prepare_delivery; "
                    f"prepare_delivery(load_job(Path({str(job.job_dir)!r})))"
                ),
            ]
            publishers = [
                subprocess.Popen(
                    command, cwd=Path(__file__).resolve().parents[3], env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for _ in range(2)
            ]
            outcomes = [process.communicate(timeout=60) for process in publishers]
            self.assertEqual([0, 1], sorted(process.returncode for process in publishers), outcomes)
            concurrent = state.load_job(job.job_dir)
            self.assertEqual("ready_for_review", concurrent.stages["delivery"]["status"])
            self.assertFalse((job.job_dir / ".09-delivery.transaction.json").exists())
            concurrent_manifest = json.loads(
                (job.job_dir / "09-delivery/delivery-manifest.json").read_text(encoding="utf-8")
            )
            self.assertIs(
                concurrent_manifest,
                qa_delivery.validate_delivery_inventory(
                    job.job_dir / "09-delivery", concurrent_manifest,
                ),
            )
            unknown_directory = job.job_dir / "09-delivery/late-race-directory"
            unknown_directory.mkdir()
            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery.validate_delivery_inventory(
                    job.job_dir / "09-delivery", concurrent_manifest,
                )
            self.assertTrue(unknown_directory.is_dir())
            self.assertEqual(initial_fd_count, len(os.listdir("/dev/fd")))
            self.assertTrue(all(
                path.stat().st_size == 0
                for retired in job.job_dir.iterdir()
                if retired.name.startswith(".09-delivery.retired-")
                for path in retired.rglob("*")
                if path.is_file()
            ))
            unknown = job.job_dir / "09-delivery/late-race.bin"
            unknown.write_bytes(b"unknown-owner")
            with self.assertRaises(qa_delivery.QaDeliveryError):
                qa_delivery.validate_delivery_inventory(
                    job.job_dir / "09-delivery",
                    json.loads(
                        (job.job_dir / "09-delivery/delivery-manifest.json").read_text(
                            encoding="utf-8"
                        )
                    ),
                )

    def test_qa_report_schema_is_closed_and_binds_workflow_plans_evidence_and_checks(self) -> None:
        from edit.hd.tools import qa_delivery

        report = {
            "version": 1,
            "status": "pass",
            "workflow": {"revision": 8, "sha256": "a" * 64, "bytes": 321},
            "plan_hashes": {
                "edit_plan": "b" * 64,
                "visual_plan": "c" * 64,
                "subtitle_plan": "d" * 64,
            },
            "inputs": {
                "preview": {
                    "path": "08-preview/review.mp4", "sha256": "e" * 64,
                    "bytes": 99, "device": 1, "inode": 2,
                    "parent_device": 3, "parent_inode": 4,
                }
            },
            "retired_lineage": [],
            "media": {"video_streams": 1, "audio_streams": 1, "frames": 48},
            "evidence": [
                {
                    "id": "cover-000", "kind": "cover_frame", "timestamp": 0.0,
                    "path": "keyframes/cover/frame-000.png", "sha256": "f" * 64,
                    "bytes": 77, "device": 5, "inode": 6,
                    "parent_device": 7, "parent_inode": 8,
                }
            ],
            "checks": [
                {"id": identifier, "status": "pass", "evidence": ["08-preview/review.mp4"]}
                for identifier in (
                    "one_video_one_audio", "complete_decode", "audio_packet_copy",
                    "black_frames", "white_flashes", "freeze_runs",
                    "duplicate_subtitles", "subtitle_safe_zones", "cover_frame_zero",
                    "content_frame_one",
                )
            ],
        }

        self.assertIs(report, qa_delivery.validate_qa_report(report))
        for mutation in (
            lambda value: value.update(extra=True),
            lambda value: value.update(status="pending"),
            lambda value: value["workflow"].update(revision=True),
            lambda value: value["evidence"][0].update(sha256="bad"),
            lambda value: value["checks"][0].update(status="skip"),
        ):
            changed = json.loads(json.dumps(report))
            mutation(changed)
            with self.subTest(changed=changed):
                with self.assertRaises(qa_delivery.QaDeliveryError):
                    qa_delivery.validate_qa_report(changed)


class SemanticSourceDeliveryTests(unittest.TestCase):
    def test_legacy_cover_review_does_not_request_missing_thumbnail(self):
        from edit.hd.tools import cover
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, _ = self._job(root, attribution_required=False)
            before = {path.name: path.read_bytes() for path in (root / "04-cover").iterdir()}
            for status in ("approved", "ready_for_review"):
                job.stages["cover"]["status"] = status
                with self.subTest(status=status), mock.patch.object(cover.state, "load_job", return_value=job):
                    result = cover.review_cover(job)
                    self.assertNotIn("thumbnail_status", result)
                    self.assertNotIn("thumbnail", result)
                    self.assertEqual(set(result["images"]), {"final"})
                    self.assertIn("仅展示", result["review_instruction"])
            self.assertEqual(before, {
                path.name: path.read_bytes() for path in (root / "04-cover").iterdir()
            })

    def test_cover_v2_thumbnail_report_is_rejected(self):
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import qa_delivery_v2
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, _ = self._job(root, attribution_required=False, cover_aspect="9:16")
            folder = root / "04-cover"
            report_path = folder / "cover-report.json"
            report = json.loads(report_path.read_text())
            report["version"] = 2
            report_path.write_text(json.dumps(report))
            job.stages["cover"]["artifacts"][-1] = _artifact_record(report_path, root)
            with self.assertRaisesRegex(qa_delivery_v2.DeliveryV2Error, "incomplete"):
                qa_delivery_v2._cover_sources(job)

    def setUp(self) -> None:
        from edit.hd.tests.test_preview_v2 import _output_probe
        from edit.hd.tools import material_usage, state

        patcher = mock.patch(
            "edit.hd.tools.segment_render._default_probe",
            return_value=_output_probe(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        dependencies_for = material_usage.state.dependencies_for

        def compatible_dependencies(job, stage_id: str):
            if not isinstance(job, state.JobState) and stage_id == "delivery":
                return ("preview",)
            return dependencies_for(job, stage_id)

        dependency_patcher = mock.patch.object(
            material_usage.state,
            "dependencies_for",
            side_effect=compatible_dependencies,
        )
        dependency_patcher.start()
        self.addCleanup(dependency_patcher.stop)

    def _job(
        self,
        root: Path,
        *,
        attribution_required: bool,
        cover_aspect: str = "3:4",
    ):
        from edit.hd.tests.test_preview_v2 import (
            _artifact_record,
            _publish_rendered_manifest,
            _source_fixture,
            _write,
        )
        from edit.hd.tools import contract_artifacts, preview_v2

        source_job, plan, asset_manifest = _source_fixture(
            root, attribution_required=attribution_required
        )
        _publish_rendered_manifest(
            Path(source_job.job_dir), source_job, plan, asset_manifest
        )
        source_manifest = preview_v2.build_source_manifest(
            source_job, plan, asset_manifest
        )
        cover_preliminary, cover_report, _selected_cover = _write_cover_contract(
            root, cover_aspect
        )
        paths = {
            "preview_video": _write(root / "11-preview/review.mp4", b"preview"),
            "qa_report": _write(root / "11-preview/qa-report.json", b"{}\n"),
            "source_manifest": _write(
                root / "11-preview/source-manifest.json",
                contract_artifacts.canonical_json_bytes(source_manifest) + b"\n",
            ),
            "content_analysis": _write(
                root / "02-content-analysis/content-analysis.json", b"{}\n"
            ),
            "visual_plan": _write(
                root / "07-visual-direction/visual-plan.json",
                contract_artifacts.canonical_json_bytes(plan) + b"\n",
            ),
            "asset_manifest": _write(
                root / "09-visual-assets/asset-manifest.json",
                contract_artifacts.canonical_json_bytes(asset_manifest) + b"\n",
            ),
            "subtitle_plan": _write(
                root / "10-subtitles/subtitle-plan.json", b"{}\n"
            ),
            "subtitles_srt": _write(
                root / "10-subtitles/subtitles.srt", b"subtitle\n"
            ),
            "subtitles_webm": _write(
                root / "10-subtitles/subtitles.webm", b"subtitle-track"
            ),
            "arroll": Path(source_job.job_dir)
            / "06-edit-structure/edited-aroll.mp4",
        }
        stages = {
            "delivery": {"status": "pending", "artifacts": []},
            "preview": {
                "status": "approved",
                "artifacts": [
                    _artifact_record(paths["preview_video"], root),
                    _artifact_record(paths["qa_report"], root),
                    _artifact_record(paths["source_manifest"], root),
                ],
            },
            "cover": {
                "status": "approved",
                "artifacts": [
                    *(
                        _artifact_record(path, root)
                        for path in cover_preliminary
                    ),
                    _artifact_record(cover_report, root),
                ],
            },
            "content_analysis": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["content_analysis"], root)],
            },
            "visual_direction": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["visual_plan"], root)],
            },
            "visual_assets": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["asset_manifest"], root)],
            },
            "subtitles": {
                "status": "approved",
                "artifacts": [
                    _artifact_record(paths["subtitle_plan"], root),
                    _artifact_record(paths["subtitles_srt"], root),
                    _artifact_record(paths["subtitles_webm"], root),
                ],
            },
            "edit_structure": {
                "status": "approved",
                "artifacts": [
                    _artifact_record(paths["arroll"], Path(source_job.job_dir))
                ],
            },
        }
        return (
            type(
                "DeliveryJob",
                (),
                {
                    "job_dir": source_job.job_dir,
                    "root": source_job.job_dir,
                    "job_id": source_job.job_id,
                    "version": 2,
                    "revision": 11,
                    "expected_sha256": "f" * 64,
                    "stages": stages,
                },
            )(),
            source_manifest,
        )

    def _persisted_job(
        self,
        root: Path,
        *,
        attribution_required: bool,
        cover_aspect: str = "3:4",
        preview_pending: bool = False,
        preview_content: bytes = b"preview",
    ):
        from edit.hd.tests.test_preview_v2 import (
            _publish_rendered_manifest,
            _source_fixture,
            _write,
        )
        from edit.hd.tools import (
            contract_artifacts, material_usage, preview_v2, state,
            talkcraft_subtitles,
        )

        root = root.resolve()
        video = _write(root / "source.mp4", b"source-video")
        script = _write(root / "script.md", "口播文案".encode("utf-8"))
        job = state.create_job(root, video, script, profile="full-v2")
        source_job, plan, asset_manifest = _source_fixture(
            Path(job.job_dir),
            attribution_required=attribution_required,
            job_id=job.job_id,
        )
        _publish_rendered_manifest(
            Path(job.job_dir), source_job, plan, asset_manifest
        )
        source_manifest = preview_v2.build_source_manifest(
            source_job, plan, asset_manifest
        )
        job_dir = Path(job.job_dir)
        cover_preliminary, cover_report, _selected_cover = _write_cover_contract(
            job_dir, cover_aspect
        )
        visual_track = _write(
            job_dir / "09-visual-assets/visual-track.mp4", b"visual"
        )
        subtitle_plan = {
            "visual_plan_sha256": plan["visual_plan_sha256"],
            "render_plan": {
                "canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 72},
                "cues": [],
            },
        }
        subtitle_plan["schema_version"] = 4
        subtitle_plan["renderer_input"] = talkcraft_subtitles.renderer_input(
            subtitle_plan["render_plan"], []
        )
        subtitle_plan["renderer"] = talkcraft_subtitles.identity(
            subtitle_plan["renderer_input"], subtitle_plan["render_plan"]
        )
        subtitle_plan["subtitle_plan_sha256"] = contract_artifacts.sha256_json(
            {key: value for key, value in subtitle_plan.items() if key != "subtitle_plan_sha256"}
        )
        paths = {
            "inspect": (_write(job_dir / "01-inspect/report.json", b"{}\n"),),
            "content_analysis": (
                _write(
                    job_dir / "02-content-analysis/content-analysis.json", b"{}\n"
                ),
            ),
            "cover_direction": (
                _write(
                    job_dir / "03-cover-direction/cover-direction.json", b"{}\n"
                ),
            ),
            "cover": (
                *cover_preliminary,
                cover_report,
            ),
            "speech_cleanup": (
                _write(
                    job_dir / "05-speech-cleanup/word-transcript.json", b"{}\n"
                ),
            ),
            "edit_structure": (
                job_dir / "06-edit-structure/edited-aroll.mp4",
            ),
            "visual_direction": (
                _write(
                    job_dir / "07-visual-direction/visual-plan.json",
                    contract_artifacts.canonical_json_bytes(plan) + b"\n",
                ),
            ),
            "visual_canary": (
                _write(
                    job_dir / "08-visual-canary/canary-manifest.json", b"{}\n"
                ),
            ),
            "visual_assets": (
                visual_track,
                _write(
                    job_dir / "09-visual-assets/asset-manifest.json",
                    contract_artifacts.canonical_json_bytes(asset_manifest) + b"\n",
                ),
            ),
            "subtitles": (
                _write(
                    job_dir / "10-subtitles/subtitle-plan.json",
                    contract_artifacts.canonical_json_bytes(subtitle_plan) + b"\n",
                ),
                _write(job_dir / "10-subtitles/subtitles.srt", b"subtitle\n"),
                _write(job_dir / "10-subtitles/subtitles.webm", b"subtitle-track"),
            ),
            "preview": () if preview_pending else (
                _write(job_dir / "11-preview/review.mp4", preview_content),
                _write(job_dir / "11-preview/qa-report.json", b"{}\n"),
                _write(
                    job_dir / "11-preview/source-manifest.json",
                    contract_artifacts.canonical_json_bytes(source_manifest) + b"\n",
                ),
            ),
        }
        for stage_id in state.stage_ids_for(job):
            if stage_id == "delivery" or (
                preview_pending and stage_id == "preview"
            ):
                break
            if stage_id == "cover":
                material_usage.publish_and_mark_ready(
                    job, stage_id, paths[stage_id],
                    producer="edit.hd.tools.cover", producer_version="test-v1",
                    stage_input_records=material_usage.current_stage_input_records(job, stage_id),
                    references=[],
                )
            else:
                state.mark_ready(job, stage_id, paths[stage_id])
            state.approve(job, stage_id)
        return state.load_job(job.job_dir)

    def test_delivery_copies_source_manifest_and_writes_required_credits(self) -> None:
        from edit.hd.tools import qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, source_manifest = self._job(
                root, attribution_required=True
            )
            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2.state, "mark_ready"):
                result = qa_delivery_v2.prepare_delivery_v2(job)

            delivered = json.loads(
                (result.directory / "source-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_manifest, delivered)
            credits = (result.directory / "credits.md").read_text(encoding="utf-8")
            for value in (
                "Example Stock",
                "Example Author",
                "https://stock.example/assets/asset-1",
                "Example Stock License",
            ):
                self.assertIn(value, credits)
            self.assertIn("credits.md", result.manifest["artifacts"])

    def test_full_v2_delivery_publishes_material_usage_receipt(self) -> None:
        from edit.hd.tools import material_usage, qa_delivery_v2, state

        with tempfile.TemporaryDirectory() as directory:
            job = self._persisted_job(
                Path(directory), attribution_required=False
            )
            result = qa_delivery_v2.prepare_delivery_v2(job)
            current = state.load_job(job.job_dir)

            self.assertTrue((result.directory / "material-usage.json").is_file())
            receipt = material_usage.load_current_receipt(current, "delivery")
            self.assertEqual([], receipt["references"])

    def test_delivery_rejects_changed_or_invalid_approved_cover_receipt(self) -> None:
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import qa_delivery_v2

        for mutation in ("bytes", "declaration", "stage", "extra_artifact"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                job = self._persisted_job(Path(directory), attribution_required=False)
                receipt_path = job.job_dir / "04-cover/material-usage.json"
                artifacts = job.stages["cover"]["artifacts"]
                if mutation == "bytes":
                    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
                elif mutation == "extra_artifact":
                    extra = job.job_dir / "04-cover/unexpected.json"
                    extra.write_text("{}", encoding="utf-8")
                    artifacts.append(_artifact_record(extra, job.job_dir))
                else:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if mutation == "declaration":
                        receipt["complete_reference_declaration"] = False
                    else:
                        receipt["stage_id"] = "preview"
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                    artifacts[:] = [
                        _artifact_record(receipt_path, job.job_dir)
                        if item["path"] == "04-cover/material-usage.json" else item
                        for item in artifacts
                    ]

                with self.assertRaises(qa_delivery_v2.DeliveryV2Error):
                    qa_delivery_v2._cover_sources(job)

    def test_delivery_wraps_cover_receipt_read_failure(self) -> None:
        from edit.hd.tools import qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            job = self._persisted_job(Path(directory), attribution_required=False)
            receipt_path = job.job_dir / "04-cover/material-usage.json"
            read_bytes = Path.read_bytes

            def fail_receipt_read(path: Path) -> bytes:
                if path == receipt_path:
                    raise PermissionError("receipt became unreadable")
                return read_bytes(path)

            with mock.patch.object(Path, "read_bytes", new=fail_receipt_read):
                with self.assertRaisesRegex(
                    qa_delivery_v2.DeliveryV2Error, "cover material usage receipt"
                ):
                    qa_delivery_v2._cover_sources(job)

    def test_delivery_copies_only_the_approved_cover_aspect_and_delivery_raster(self) -> None:
        from edit.hd.tools import qa_delivery_v2

        cases = {
            "3:4": "cover-3x4.png",
            "9:16": "cover-9x16.png",
        }
        for aspect, selected_name in cases.items():
            with self.subTest(aspect=aspect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                job, _source_manifest = self._job(
                    root,
                    attribution_required=False,
                    cover_aspect=aspect,
                )
                with mock.patch.object(
                    qa_delivery_v2.state, "require_runnable"
                ), mock.patch.object(qa_delivery_v2.state, "mark_ready"):
                    result = qa_delivery_v2.prepare_delivery_v2(job)

                delivered = {
                    path.relative_to(result.directory / "cover").as_posix()
                    for path in (result.directory / "cover").iterdir()
                }
                self.assertEqual(
                    {selected_name, "cover-delivery-raster.png", "cover-report.json"},
                    delivered,
                )
                self.assertIn(f"cover/{selected_name}", result.manifest["artifacts"])
                self.assertIn(
                    "cover/cover-delivery-raster.png",
                    result.manifest["artifacts"],
                )
                other_name = (
                    "cover-9x16.png"
                    if selected_name == "cover-3x4.png"
                    else "cover-3x4.png"
                )
                self.assertNotIn(f"cover/{other_name}", result.manifest["artifacts"])

    def test_delivery_rejects_cover_report_aspect_and_artifact_mismatches(self) -> None:
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        def remove_aspect(report: dict[str, object]) -> None:
            report.pop("output_aspect_ratio")

        def unknown_aspect(report: dict[str, object]) -> None:
            report["output_aspect_ratio"] = "2:3"

        def another_aspect(report: dict[str, object]) -> None:
            report["output_aspect_ratio"] = "9:16"

        def changed_artifact(report: dict[str, object]) -> None:
            selected = next(
                record
                for record in report["artifacts"]
                if record["path"].endswith("cover-3x4.png")
            )
            selected["sha256"] = "f" * 64
            report["output_sha256"]["cover-3x4.png"] = "f" * 64

        for mutate in (
            remove_aspect,
            unknown_aspect,
            another_aspect,
            changed_artifact,
        ):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                job, _source_manifest = self._job(
                    root,
                    attribution_required=False,
                    cover_aspect="3:4",
                )
                report_path = root / "04-cover/cover-report.json"
                report = contract_artifacts.read_json_artifact(report_path)
                mutate(report)
                report_path.write_bytes(
                    contract_artifacts.canonical_json_bytes(report)
                )
                report_record = next(
                    record
                    for record in job.stages["cover"]["artifacts"]
                    if record["path"] == "04-cover/cover-report.json"
                )
                report_record.update(
                    _artifact_record(report_path, root)
                )

                with self.assertRaises(qa_delivery_v2.DeliveryV2Error):
                    qa_delivery_v2.prepare_delivery_v2(job)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, _source_manifest = self._job(
                root,
                attribution_required=False,
                cover_aspect="9:16",
            )
            (root / "04-cover/cover-9x16.png").unlink()
            with self.assertRaises(qa_delivery_v2.DeliveryV2Error):
                qa_delivery_v2.prepare_delivery_v2(job)

    def test_delivery_mark_ready_failure_restores_previous_generation_and_job(self) -> None:
        from edit.hd.tools import qa_delivery_v2, state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = self._persisted_job(
                root, attribution_required=True
            )
            target = Path(job.job_dir) / "12-delivery"
            target.mkdir()
            previous = target / "previous.txt"
            previous.write_bytes(b"previous-delivery")
            previous_stage = copy.deepcopy(job.stages["delivery"])

            with mock.patch.object(
                qa_delivery_v2.state,
                "save_job",
                side_effect=RuntimeError("workflow update rejected"),
            ), self.assertRaisesRegex(RuntimeError, "workflow update rejected"):
                qa_delivery_v2.prepare_delivery_v2(job)

            self.assertEqual(b"previous-delivery", previous.read_bytes())
            self.assertEqual(previous_stage, job.stages["delivery"])
            self.assertEqual(
                "pending",
                state.load_job(job.job_dir).stages["delivery"]["status"],
            )
            self.assertFalse(any(Path(job.job_dir).glob(".12-delivery.stage-*")))
            self.assertFalse(any(Path(job.job_dir).glob(".12-delivery.backup-*")))
            self.assertFalse(
                (Path(job.job_dir) / ".12-delivery.publication.json").exists()
            )

    def test_delivery_install_interruption_recovers_then_publishes_on_retry(self) -> None:
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, _source_manifest = self._job(
                root, attribution_required=True
            )
            target = root / "12-delivery"
            target.mkdir()
            (target / "previous.txt").write_bytes(b"previous-delivery")
            replace = os.replace

            def interrupt_install(source, destination) -> None:
                if (
                    Path(source).name.startswith(".12-delivery.stage-")
                    and Path(destination) == target
                ):
                    raise OSError("delivery install interrupted")
                replace(source, destination)

            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(
                qa_delivery_v2.os, "replace", side_effect=interrupt_install
            ), self.assertRaisesRegex(OSError, "delivery install interrupted"):
                qa_delivery_v2.prepare_delivery_v2(job)

            self.assertFalse(target.exists())
            self.assertTrue(any(root.glob(".12-delivery.backup-*")))
            self.assertTrue((root / ".12-delivery.publication.json").exists())

            def mark_ready(_job, _stage_id: str, artifacts) -> None:
                _job.stages["delivery"].update(
                    status="ready_for_review",
                    artifacts=[
                        _artifact_record(path, Path(_job.job_dir))
                        for path in artifacts
                    ],
                )

            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(
                qa_delivery_v2.state, "mark_ready", side_effect=mark_ready
            ):
                result = qa_delivery_v2.prepare_delivery_v2(job)

            self.assertTrue((result.directory / "final.mp4").is_file())
            self.assertFalse((target / "previous.txt").exists())
            self.assertFalse(any(root.glob(".12-delivery.backup-*")))
            self.assertFalse((root / ".12-delivery.publication.json").exists())

    def test_delivery_restore_interruption_is_retried_before_build(self) -> None:
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, _source_manifest = self._job(
                root, attribution_required=True
            )
            target = root / "12-delivery"
            target.mkdir()
            (target / "previous.txt").write_bytes(b"previous-delivery")
            old_digest = qa_delivery_v2._delivery_tree_digest(target)
            stage = root / ".12-delivery.stage-recovery"
            stage.mkdir()
            (stage / "final.mp4").write_bytes(b"new-delivery")
            new_digest = qa_delivery_v2._delivery_tree_digest(stage)
            backup = root / ".12-delivery.backup-recovery"
            os.replace(target, backup)
            os.replace(stage, target)
            contract_artifacts.write_json_artifact(
                root / ".12-delivery.publication.json",
                {
                    "schema_version": 1,
                    "state": "installed",
                    "stage_name": stage.name,
                    "backup_name": backup.name,
                    "had_target": True,
                    "old_tree_sha256": old_digest,
                    "new_tree_sha256": new_digest,
                },
            )
            replace = os.replace

            def interrupt_restore(source, destination) -> None:
                if Path(source) == backup and Path(destination) == target:
                    raise OSError("delivery recovery interrupted")
                replace(source, destination)

            with mock.patch.object(
                qa_delivery_v2.os, "replace", side_effect=interrupt_restore
            ), self.assertRaisesRegex(OSError, "delivery recovery interrupted"):
                qa_delivery_v2.prepare_delivery_v2(job)

            self.assertFalse(target.exists())
            self.assertTrue(backup.exists())
            self.assertTrue((root / ".12-delivery.publication.json").exists())

            with mock.patch.object(
                qa_delivery_v2.state,
                "require_runnable",
                side_effect=RuntimeError("stop after recovery"),
            ), self.assertRaisesRegex(RuntimeError, "stop after recovery"):
                qa_delivery_v2.prepare_delivery_v2(job)

            self.assertEqual(
                b"previous-delivery", (target / "previous.txt").read_bytes()
            )
            self.assertFalse(backup.exists())
            self.assertFalse((root / ".12-delivery.publication.json").exists())

    def test_delivery_journal_accepts_only_direct_job_child_names(self) -> None:
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        cases = (
            ("stage_name", ".12-delivery.stage-x/../../other-tree"),
            ("stage_name", ".12-delivery.stage-x\\other-tree"),
            ("backup_name", ".12-delivery.backup-x/../../other-tree"),
        )
        for field, value in cases:
            with self.subTest(
                field=field, value=value
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                job_dir = root / "job"
                job_dir.mkdir()
                job, _source_manifest = self._job(
                    job_dir, attribution_required=False
                )
                other = root / "other-tree"
                other.mkdir()
                sentinel = other / "sentinel.bin"
                sentinel.write_bytes(b"other-tree")
                digest = qa_delivery_v2._delivery_tree_digest(other)
                had_target = field == "backup_name"
                contract_artifacts.write_json_artifact(
                    job_dir / ".12-delivery.publication.json",
                    {
                        "schema_version": 1,
                        "state": "installed",
                        "stage_name": (
                            value
                            if field == "stage_name"
                            else ".12-delivery.stage-valid"
                        ),
                        "backup_name": value if had_target else None,
                        "had_target": had_target,
                        "old_tree_sha256": digest if had_target else None,
                        "new_tree_sha256": digest,
                    },
                )
                error = None
                try:
                    with mock.patch.object(
                        qa_delivery_v2.state,
                        "require_runnable",
                        side_effect=RuntimeError("stop after recovery"),
                    ):
                        qa_delivery_v2.prepare_delivery_v2(job)
                except BaseException as exc:
                    error = exc

                self.assertIsInstance(error, qa_delivery_v2.DeliveryV2Error)
                self.assertTrue(sentinel.is_file())
                self.assertEqual(b"other-tree", sentinel.read_bytes())

    def test_two_preview_job_snapshots_build_once_then_strictly_reuse(self) -> None:
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import preview_v2, state

        with tempfile.TemporaryDirectory() as directory:
            current = self._persisted_job(
                Path(directory),
                attribution_required=False,
                preview_pending=True,
            )
            first_job = state.load_job(current.job_dir)
            second_job = state.load_job(current.job_dir)
            compose_count = 0
            count_lock = threading.Lock()
            barrier = threading.Barrier(3)
            results = []
            errors: list[BaseException] = []

            def compose(command, **_kwargs) -> mock.Mock:
                nonlocal compose_count
                with count_lock:
                    compose_count += 1
                Path(command[-1]).write_bytes(b"review-video")
                return mock.Mock(returncode=0, stdout="")

            def extract(
                _video: Path, output: Path, _duration: float
            ) -> list[Path]:
                output.mkdir()
                frames = []
                for index in range(1, 6):
                    path = output / f"frame-{index:02d}.png"
                    path.write_bytes(f"frame-{index}".encode())
                    frames.append(path)
                return frames

            def invoke(job) -> None:
                try:
                    barrier.wait(3)
                    results.append(preview_v2.prepare_preview_v2(job))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                preview_v2.subprocess, "run", side_effect=compose
            ), mock.patch.object(
                preview_v2,
                "_validate_media",
                return_value={
                    "width": 1080,
                    "height": 1920,
                    "fps": 24,
                    "frames": 72,
                    "duration": 3.0,
                    "video_streams": 1,
                    "audio_streams": 1,
                },
            ), mock.patch.object(
                preview_v2, "_extract_frames", side_effect=extract
            ):
                first = threading.Thread(target=invoke, args=(first_job,))
                second = threading.Thread(target=invoke, args=(second_job,))
                first.start()
                second.start()
                barrier.wait(3)
                first.join(10)
                second.join(10)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(2, len(results))
            self.assertEqual(1, compose_count)
            persisted = state.load_job(current.job_dir)
            self.assertEqual(
                "ready_for_review", persisted.stages["preview"]["status"]
            )
            for snapshot in (first_job, second_job):
                self.assertEqual(
                    "ready_for_review", snapshot.stages["preview"]["status"]
                )
                self.assertEqual(
                    persisted.expected_sha256, snapshot.expected_sha256
                )
                self.assertEqual(
                    persisted.expected_bytes, snapshot.expected_bytes
                )
            self.assertEqual(
                results[0].qa_report["qa_report_sha256"],
                results[1].qa_report["qa_report_sha256"],
            )
            self.assertEqual(
                {
                    _artifact_record(path, Path(current.job_dir))["sha256"]
                    for path in results[0].artifacts
                },
                {
                    _artifact_record(path, Path(current.job_dir))["sha256"]
                    for path in results[1].artifacts
                },
            )

    def test_two_job_snapshots_publish_once_then_reuse(self) -> None:
        from edit.hd.tools import qa_delivery_v2, state

        with tempfile.TemporaryDirectory() as directory:
            current = self._persisted_job(
                Path(directory), attribution_required=True
            )
            first_job = state.load_job(current.job_dir)
            second_job = state.load_job(current.job_dir)
            expected_copies = len(qa_delivery_v2._sources(first_job))
            copy_count = 0
            count_lock = threading.Lock()
            original_copy = qa_delivery_v2._copy
            barrier = threading.Barrier(3)
            results = []
            errors: list[BaseException] = []

            def counted_copy(source: Path, destination: Path) -> None:
                nonlocal copy_count
                with count_lock:
                    copy_count += 1
                original_copy(source, destination)

            def invoke(job) -> None:
                try:
                    barrier.wait(3)
                    results.append(qa_delivery_v2.prepare_delivery_v2(job))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                qa_delivery_v2, "_copy", side_effect=counted_copy
            ):
                first = threading.Thread(target=invoke, args=(first_job,))
                second = threading.Thread(target=invoke, args=(second_job,))
                first.start()
                second.start()
                barrier.wait(3)
                first.join(10)
                second.join(10)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(2, len(results))
            self.assertEqual(expected_copies, copy_count)
            self.assertEqual(
                results[0].manifest["delivery_manifest_sha256"],
                results[1].manifest["delivery_manifest_sha256"],
            )
            self.assertEqual(
                "ready_for_review", first_job.stages["delivery"]["status"]
            )
            self.assertEqual(
                "ready_for_review", second_job.stages["delivery"]["status"]
            )
            self.assertEqual(
                "ready_for_review",
                state.load_job(current.job_dir).stages["delivery"]["status"],
            )

    def test_ready_and_approved_delivery_reuse_exact_inventory_without_copying(self) -> None:
        from edit.hd.tools import qa_delivery_v2, state

        with tempfile.TemporaryDirectory() as directory:
            job = self._persisted_job(
                Path(directory), attribution_required=True
            )
            first = qa_delivery_v2.prepare_delivery_v2(job)

            with mock.patch.object(
                qa_delivery_v2,
                "_copy",
                side_effect=AssertionError("reuse must not copy"),
            ) as copier:
                ready = qa_delivery_v2.prepare_delivery_v2(job)
            copier.assert_not_called()
            self.assertEqual(
                first.manifest["delivery_manifest_sha256"],
                ready.manifest["delivery_manifest_sha256"],
            )

            state.approve(job, "delivery")
            with mock.patch.object(
                qa_delivery_v2,
                "_copy",
                side_effect=AssertionError("reuse must not copy"),
            ) as copier:
                approved = qa_delivery_v2.prepare_delivery_v2(job)
            copier.assert_not_called()
            self.assertEqual(
                first.manifest["delivery_manifest_sha256"],
                approved.manifest["delivery_manifest_sha256"],
            )

            (approved.directory / "unrecorded.json").write_bytes(b"{}\n")
            with mock.patch.object(
                qa_delivery_v2,
                "_copy",
                side_effect=AssertionError("reuse must not copy"),
            ) as copier, self.assertRaises(qa_delivery_v2.DeliveryV2Error):
                qa_delivery_v2.prepare_delivery_v2(job)
            copier.assert_not_called()

    def test_delivery_does_not_create_an_empty_credits_file(self) -> None:
        from edit.hd.tools import qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, _ = self._job(root, attribution_required=False)
            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2.state, "mark_ready"):
                result = qa_delivery_v2.prepare_delivery_v2(job)

            self.assertFalse((result.directory / "credits.md").exists())
            self.assertNotIn("credits.md", result.manifest["artifacts"])

    def test_reusable_delivery_rechecks_the_copied_source_manifest(self) -> None:
        from edit.hd.tests.test_preview_v2 import _artifact_record
        from edit.hd.tools import qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, _source_manifest = self._job(
                root, attribution_required=True
            )
            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2.state, "mark_ready"):
                result = qa_delivery_v2.prepare_delivery_v2(job)

            job.stages["delivery"] = {
                "status": "ready_for_review",
                "artifacts": [
                    _artifact_record(path, Path(job.job_dir))
                    for path in result.artifacts
                ],
            }
            job.revision += 1
            (result.directory / "source-manifest.json").write_bytes(b"{}\n")

            with self.assertRaises(qa_delivery_v2.DeliveryV2Error):
                qa_delivery_v2.prepare_delivery_v2(job)

    def test_delivery_blocks_an_incomplete_source_record_before_copying(self) -> None:
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, source_manifest = self._job(root, attribution_required=True)
            source_manifest["components"][0]["artifact"]["sha256"] = ""
            unsigned = {
                key: value
                for key, value in source_manifest.items()
                if key != "source_manifest_sha256"
            }
            source_manifest["source_manifest_sha256"] = (
                contract_artifacts.sha256_json(unsigned)
            )
            source_path = root / "11-preview/source-manifest.json"
            source_path.write_bytes(
                contract_artifacts.canonical_json_bytes(source_manifest) + b"\n"
            )
            record = next(
                item
                for item in job.stages["preview"]["artifacts"]
                if item["path"] == "11-preview/source-manifest.json"
            )
            record.update(
                sha256=contract_artifacts.sha256_file(source_path),
                bytes=source_path.stat().st_size,
            )

            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2, "_copy") as copier, self.assertRaisesRegex(
                qa_delivery_v2.DeliveryV2Error,
                "^BROLL_SOURCE_MANIFEST_BLOCKED$",
            ):
                qa_delivery_v2.prepare_delivery_v2(job)

            copier.assert_not_called()
            self.assertFalse((root / "12-delivery").exists())
            self.assertFalse(any(root.glob(".12-delivery.stage-*")))

    def test_delivery_binds_source_manifest_to_the_approved_plan_and_assets(self) -> None:
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, source_manifest = self._job(root, attribution_required=False)
            source_manifest["asset_manifest_sha256"] = "e" * 64
            unsigned = {
                key: value
                for key, value in source_manifest.items()
                if key != "source_manifest_sha256"
            }
            source_manifest["source_manifest_sha256"] = (
                contract_artifacts.sha256_json(unsigned)
            )
            source_path = root / "11-preview/source-manifest.json"
            source_path.write_bytes(
                contract_artifacts.canonical_json_bytes(source_manifest) + b"\n"
            )
            record = next(
                item
                for item in job.stages["preview"]["artifacts"]
                if item["path"] == "11-preview/source-manifest.json"
            )
            record.update(
                sha256=contract_artifacts.sha256_file(source_path),
                bytes=source_path.stat().st_size,
            )

            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2, "_copy") as copier, self.assertRaisesRegex(
                qa_delivery_v2.DeliveryV2Error,
                "^BROLL_SOURCE_MANIFEST_BLOCKED$",
            ):
                qa_delivery_v2.prepare_delivery_v2(job)

            copier.assert_not_called()

    def test_delivery_binds_every_approved_component_before_copying(self) -> None:
        from edit.hd.tools import contract_artifacts, qa_delivery_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, source_manifest = self._job(root, attribution_required=False)
            source_manifest["components"] = []
            unsigned = {
                key: value
                for key, value in source_manifest.items()
                if key != "source_manifest_sha256"
            }
            source_manifest["source_manifest_sha256"] = (
                contract_artifacts.sha256_json(unsigned)
            )
            source_path = root / "11-preview/source-manifest.json"
            source_path.write_bytes(
                contract_artifacts.canonical_json_bytes(source_manifest) + b"\n"
            )
            record = next(
                item
                for item in job.stages["preview"]["artifacts"]
                if item["path"] == "11-preview/source-manifest.json"
            )
            record.update(
                sha256=contract_artifacts.sha256_file(source_path),
                bytes=source_path.stat().st_size,
            )

            with mock.patch.object(
                qa_delivery_v2.state, "require_runnable"
            ), mock.patch.object(qa_delivery_v2, "_copy") as copier, self.assertRaisesRegex(
                qa_delivery_v2.DeliveryV2Error,
                "^BROLL_SOURCE_MANIFEST_BLOCKED$",
            ):
                qa_delivery_v2.prepare_delivery_v2(job)

            copier.assert_not_called()


if __name__ == "__main__":
    unittest.main()

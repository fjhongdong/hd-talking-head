"""Strict QA and immutable HD delivery publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import state


__all__ = [
    "QaDeliveryError",
    "DeliveryResult",
    "StableGenerationPublisher",
    "run_strict_qa",
    "validate_qa_report",
    "validate_delivery_inventory",
    "prepare_delivery",
]

_QA_CHECK_IDS = {
    "one_video_one_audio", "complete_decode", "audio_packet_copy", "black_frames",
    "white_flashes", "freeze_runs", "duplicate_subtitles", "subtitle_safe_zones",
    "cover_frame_zero", "content_frame_one",
}
_DELIVERY_REQUIRED = {
    "final.mp4", "cover-3x4.png", "cover-9x16.png", "cover-canvas.png",
    "subtitles.srt", "subtitles.webm", "edit-plan.json", "visual-plan.json",
    "asset-manifest.json", "qa-report.json", "inspection.json", "contact-sheet.png",
}


class QaDeliveryError(RuntimeError):
    """A sanitized QA or delivery-stage failure."""


@dataclass(frozen=True)
class DeliveryResult:
    directory: Path
    artifacts: tuple[Path, ...]
    manifest: dict[str, object]
    media_summary: dict[str, object]


class StableGenerationPublisher:
    """A parent-anchored lock shared by both Task 9 publication stages."""

    def __init__(self, job_dir: Path, target_name: str):
        self.job_dir = Path(os.path.abspath(job_dir))
        self.target_name = target_name
        self._parent_descriptor = -1
        self._lock_descriptor = -1
        self._parent_locked = False
        self._file_locked = False

    def acquire(self, *, blocking: bool = True) -> "StableGenerationPublisher":
        if self._parent_descriptor >= 0:
            raise QaDeliveryError("publication lock is already held")
        parent = self.job_dir.parent
        lock_name = f".hd-task9-{hashlib.sha256(self.job_dir.name.encode()).hexdigest()[:24]}.lock"
        guard_name = f"{lock_name}.guard"
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            parent_named = os.lstat(parent)
            descriptor = os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            self._parent_descriptor = descriptor
            if not os.path.samestat(parent_named, os.fstat(descriptor)):
                raise QaDeliveryError("publication lock changed identity")
            fcntl.flock(descriptor, operation)
            self._parent_locked = True
            try:
                named = os.stat(lock_name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                named = None
            try:
                guarded = os.stat(guard_name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                guarded = None
            if named is None and guarded is None:
                lock_descriptor = os.open(
                    lock_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=descriptor,
                )
                os.link(
                    lock_name, guard_name, src_dir_fd=descriptor, dst_dir_fd=descriptor,
                    follow_symlinks=False,
                )
                os.fsync(descriptor)
            elif named is None or guarded is None:
                raise QaDeliveryError("publication lock changed identity")
            else:
                lock_descriptor = os.open(
                    lock_name, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor,
                )
            self._lock_descriptor = lock_descriptor
            opened = os.fstat(lock_descriptor)
            named = os.stat(lock_name, dir_fd=descriptor, follow_symlinks=False)
            guarded = os.stat(guard_name, dir_fd=descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 2
                or not os.path.samestat(opened, named)
                or not os.path.samestat(opened, guarded)
            ):
                raise QaDeliveryError("publication lock changed identity")
            fcntl.flock(lock_descriptor, operation)
            self._file_locked = True
            return self
        except (KeyboardInterrupt, SystemExit):
            try:
                self.release()
            except BaseException:
                pass
            raise
        except QaDeliveryError:
            try:
                self.release()
            except BaseException:
                pass
            raise
        except BaseException:
            try:
                self.release()
            except BaseException:
                pass
            raise QaDeliveryError("cannot acquire publication lock") from None

    def release(self) -> None:
        failure = False
        if self._lock_descriptor >= 0:
            descriptor, self._lock_descriptor = self._lock_descriptor, -1
            try:
                if self._file_locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                failure = True
            self._file_locked = False
            try:
                os.close(descriptor)
            except OSError:
                failure = True
        if self._parent_descriptor >= 0:
            descriptor, self._parent_descriptor = self._parent_descriptor, -1
            try:
                if self._parent_locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                failure = True
            self._parent_locked = False
            try:
                os.close(descriptor)
            except OSError:
                failure = True
        if failure:
            raise QaDeliveryError("cannot release publication lock") from None


def run_strict_qa(
    *,
    preview: Path,
    edited_aroll: Path,
    cover_raster: Path,
    edit_plan: object,
    timeline_map: object,
    visual_plan: object,
    subtitle_plan: object,
    asset_manifest: object,
    evidence: Sequence[Mapping[str, object]],
    workflow_binding: Mapping[str, object],
    semantic_event_plan: Mapping[str, object] | None = None,
    audio_event_cues: Mapping[str, object] | None = None,
    region_timeline: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run strict structural, plan, pixel and evidence QA over a real preview."""
    try:
        from . import preview as preview_module
        from . import subtitles as subtitle_module
        from . import visual_plan as visual_plan_module

        if type(workflow_binding) is not dict or set(workflow_binding) not in (
            {"workflow", "plan_hashes", "inputs"},
            {"workflow", "plan_hashes", "inputs", "retired_lineage"},
        ):
            raise QaDeliveryError("strict QA failed")
        workflow = _exact(workflow_binding["workflow"], {"revision", "sha256", "bytes"})
        plan_hashes = _exact(
            workflow_binding["plan_hashes"], {"edit_plan", "visual_plan", "subtitle_plan"},
        )
        inputs = workflow_binding["inputs"]
        retired_lineage = workflow_binding.get("retired_lineage", [])
        if type(inputs) is not dict or not inputs or type(retired_lineage) is not list:
            raise QaDeliveryError("strict QA failed")
        checked_visual = visual_plan_module.validate_visual_plan(visual_plan)
        checked_subtitles = subtitle_module.validate_subtitle_plan(subtitle_plan)
        if semantic_event_plan is not None:
            from . import semantic_events

            semantic_events.validate_semantic_event_plan(
                semantic_event_plan,
                expected_visual_plan_sha256=checked_visual["visual_plan_sha256"],
            )
            if region_timeline is not None:
                from . import region_timeline as region_timeline_module

                checked_regions = region_timeline_module.validate_region_timeline(
                    region_timeline,
                    expected_plan_sha256=checked_visual["visual_plan_sha256"],
                )
                for event in semantic_event_plan["events"]:
                    spatial = event["channels"].get("spatial")
                    if type(spatial) is dict and "requested_box" in spatial:
                        try:
                            result = region_timeline_module.resolve_event_box(
                                checked_regions,
                                event_id=event["event_id"],
                                start_frame=event["start_frame"],
                                end_frame=event["end_frame"],
                                requested=spatial["requested_box"],
                                avoid_roles=spatial.get("avoid_roles", ("presenter", "forbidden")),
                            )
                        except region_timeline_module.RegionTimelineError:
                            raise QaDeliveryError("strict QA failed") from None
                        if result["status"] != "resolved":
                            raise QaDeliveryError("strict QA failed")
            semantic_events.validate_subtitle_event_alignment(
                checked_subtitles, semantic_event_plan
            )
            if audio_event_cues is not None:
                semantic_events.validate_audio_event_alignment(
                    audio_event_cues, semantic_event_plan
                )
        elif audio_event_cues is not None:
            raise QaDeliveryError("audio event cues require a semantic event plan")
        if type(edit_plan) is not dict or type(timeline_map) is not dict or type(asset_manifest) is not dict:
            raise QaDeliveryError("strict QA failed")
        canvas = checked_subtitles["canvas"]
        media = preview_module.validate_preview_media(
            preview,
            edited_aroll=edited_aroll,
            cover_raster=cover_raster,
            canvas=canvas,
        )
        if (
            checked_visual.get("canvas")
            != {"width": canvas["width"], "height": canvas["height"], "fps": float(canvas["fps"])}
            and checked_visual.get("canvas")
            != {"width": canvas["width"], "height": canvas["height"], "fps": canvas["fps"]}
        ):
            raise QaDeliveryError("strict QA failed")
        pixel_checks = _pixel_checks(
            preview,
            width=int(canvas["width"]),
            height=int(canvas["height"]),
            fps=float(canvas["fps"]),
            frames=int(canvas["frames"]),
            checked_visual=checked_visual,
        )
        cue_texts = [str(cue["text"]).strip() for cue in checked_subtitles["cues"]]
        if any(left == right for left, right in zip(cue_texts, cue_texts[1:])):
            raise QaDeliveryError("strict QA failed")
        checked_evidence = _verify_qa_evidence(preview.parent, evidence)
        expected_schedule = preview_module.build_evidence_schedule(
            edit_plan, timeline_map, checked_visual, checked_subtitles,
        )
        actual_schedule = [
            {key: item[key] for key in ("id", "kind", "timestamp", "path")}
            for item in checked_evidence
        ]
        if actual_schedule != expected_schedule:
            raise QaDeliveryError("strict QA failed")
        kinds = {str(item["kind"]) for item in checked_evidence}
        required_kinds = {"cover_frame", "visual_keyframe"}
        if checked_subtitles["cues"]:
            required_kinds.add("subtitle_midpoint")
        if not required_kinds.issubset(kinds):
            raise QaDeliveryError("strict QA failed")
        checks = [
            {"id": "one_video_one_audio", "status": "pass", "evidence": ["08-preview/review.mp4"]},
            {"id": "complete_decode", "status": "pass", "evidence": ["08-preview/review.mp4"]},
            {"id": "audio_packet_copy", "status": "pass", "evidence": ["08-preview/review.mp4"]},
            {"id": "black_frames", "status": "pass", "evidence": pixel_checks["sample_paths"]},
            {"id": "white_flashes", "status": "pass", "evidence": pixel_checks["sample_paths"]},
            {"id": "freeze_runs", "status": "pass", "evidence": pixel_checks["sample_paths"]},
            {"id": "duplicate_subtitles", "status": "pass", "evidence": [str(item["path"]) for item in checked_evidence if item["kind"] == "subtitle_midpoint"]},
            {"id": "subtitle_safe_zones", "status": "pass", "evidence": [str(item["path"]) for item in checked_evidence if item["kind"] == "subtitle_midpoint"]},
            {"id": "cover_frame_zero", "status": "pass", "evidence": ["keyframes/cover/frame-000.png"]},
            {"id": "content_frame_one", "status": "pass", "evidence": ["keyframes/cover/frame-001.png"]},
        ]
        report = {
            "version": 1,
            "status": "pass",
            "workflow": workflow,
            "plan_hashes": plan_hashes,
            "inputs": inputs,
            "retired_lineage": retired_lineage,
            "media": {
                "video_streams": media["video_streams"],
                "audio_streams": media["audio_streams"],
                "frames": media["frames"],
            },
            "evidence": checked_evidence,
            "checks": checks,
        }
        validate_qa_report(report)
        return report, media
    except (KeyboardInterrupt, SystemExit):
        raise
    except QaDeliveryError:
        raise
    except BaseException:
        raise QaDeliveryError("strict QA failed") from None


def _verify_qa_evidence(
    root: Path, evidence: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if type(evidence) not in (list, tuple) or not evidence:
        raise QaDeliveryError("strict QA failed")
    checked: list[dict[str, object]] = []
    for value in evidence:
        if type(value) is not dict:
            raise QaDeliveryError("strict QA failed")
        item = dict(value)
        _validate_identity_record({
            key: item.get(key)
            for key in (
                "path", "sha256", "bytes", "device", "inode", "parent_device", "parent_inode",
            )
        })
        relative = Path(str(item["path"]))
        path = root / relative
        status = os.lstat(path)
        parent = os.lstat(path.parent)
        source = path.read_bytes()
        if (
            status.st_dev != item["device"] or status.st_ino != item["inode"]
            or parent.st_dev != item["parent_device"] or parent.st_ino != item["parent_inode"]
            or len(source) != item["bytes"]
            or hashlib.sha256(source).hexdigest() != item["sha256"]
            or set(item) != {
                "id", "kind", "timestamp", "path", "sha256", "bytes",
                "device", "inode", "parent_device", "parent_inode",
            }
        ):
            raise QaDeliveryError("strict QA failed")
        checked.append(item)
    return checked


def _pixel_checks(
    path: Path,
    *,
    width: int,
    height: int,
    fps: float,
    frames: int,
    checked_visual: Mapping[str, object] | None = None,
) -> dict[str, object]:
    sample_width = min(width, 64)
    sample_height = min(height, 96)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-i", str(path), "-vf", f"scale={sample_width}:{sample_height},format=gray",
                "-frames:v", str(frames), "-f", "rawvideo", "-",
            ],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=180,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise QaDeliveryError("strict QA failed") from None
    frame_bytes = sample_width * sample_height
    if len(result.stdout) != frame_bytes * frames:
        raise QaDeliveryError("strict QA failed")
    decoded = [
        result.stdout[index * frame_bytes:(index + 1) * frame_bytes]
        for index in range(frames)
    ]
    means = [sum(frame) / frame_bytes for frame in decoded]
    if any(value <= 2.0 for value in means) or any(value >= 253.0 for value in means):
        raise QaDeliveryError("strict QA failed")
    if any(
        abs(middle - left) >= 180.0 and abs(middle - right) >= 180.0
        for left, middle, right in zip(means, means[1:], means[2:])
    ):
        raise QaDeliveryError("strict QA failed")
    frozen = 0
    maximum = 0
    run_start: int | None = None
    freeze_runs: list[tuple[int, int, int]] = []
    for left_index, (left, right) in enumerate(zip(decoded, decoded[1:])):
        difference = sum(abs(first - second) for first, second in zip(left, right)) / frame_bytes
        if difference == 0.0:
            if run_start is None:
                run_start = left_index
            frozen += 1
        else:
            if run_start is not None:
                freeze_runs.append((run_start, left_index, frozen))
                run_start = None
            frozen = 0
        maximum = max(maximum, frozen)
    if run_start is not None:
        freeze_runs.append((run_start, frames - 1, frozen))
    segments = checked_visual.get("segments") if checked_visual is not None else None
    for start_frame, end_frame, length in freeze_runs:
        if length < fps:
            continue
        allowed_code_tail = False
        if length <= fps and type(segments) is list:
            for segment in segments:
                if type(segment) is not dict or segment.get("implementation") != "code":
                    continue
                segment_start_time = float(segment["start"])
                segment_end_time = float(segment["end"])
                segment_start = math.ceil(segment_start_time * fps)
                segment_end = min(frames, math.ceil(segment_end_time * fps)) - 1
                if (
                    start_frame > segment_start
                    and end_frame == segment_end
                    and start_frame / fps >= segment_start_time
                    and end_frame / fps < segment_end_time
                    and (end_frame + 1) / fps >= segment_end_time
                ):
                    allowed_code_tail = True
                    break
        if not allowed_code_tail:
            raise QaDeliveryError("strict QA failed")
    return {
        "black_min": min(means),
        "white_max": max(means),
        "freeze_run": maximum,
        "sample_paths": ["08-preview/review.mp4"],
    }


def validate_qa_report(report: object) -> dict[str, object]:
    """Validate the canonical closed Task 9 machine-QA report contract."""
    try:
        top = _exact(
            report,
            {"version", "status", "workflow", "plan_hashes", "inputs", "retired_lineage", "media", "evidence", "checks"},
        )
        if type(top["version"]) is not int or top["version"] != 1 or top["status"] != "pass":
            raise QaDeliveryError("strict QA report is invalid")
        workflow = _exact(top["workflow"], {"revision", "sha256", "bytes"})
        if (
            type(workflow["revision"]) is not int or workflow["revision"] < 0
            or type(workflow["bytes"]) is not int or workflow["bytes"] <= 0
            or not _sha(workflow["sha256"])
        ):
            raise QaDeliveryError("strict QA report is invalid")
        hashes = _exact(top["plan_hashes"], {"edit_plan", "visual_plan", "subtitle_plan"})
        if not all(_sha(value) for value in hashes.values()):
            raise QaDeliveryError("strict QA report is invalid")
        inputs = top["inputs"]
        if type(inputs) is not dict or not inputs:
            raise QaDeliveryError("strict QA report is invalid")
        for name, record in inputs.items():
            if type(name) is not str or not name:
                raise QaDeliveryError("strict QA report is invalid")
            _validate_identity_record(record)
        if type(top["retired_lineage"]) is not list:
            raise QaDeliveryError("strict QA report is invalid")
        media = _exact(top["media"], {"video_streams", "audio_streams", "frames"})
        if (
            media["video_streams"] != 1 or type(media["video_streams"]) is not int
            or media["audio_streams"] != 1 or type(media["audio_streams"]) is not int
            or type(media["frames"]) is not int or media["frames"] <= 1
        ):
            raise QaDeliveryError("strict QA report is invalid")
        evidence = top["evidence"]
        if type(evidence) is not list or not evidence:
            raise QaDeliveryError("strict QA report is invalid")
        evidence_paths: set[str] = set()
        for item in evidence:
            checked = _exact(
                item,
                {
                    "id", "kind", "timestamp", "path", "sha256", "bytes",
                    "device", "inode", "parent_device", "parent_inode",
                },
            )
            if (
                type(checked["id"]) is not str or not checked["id"]
                or type(checked["kind"]) is not str or not checked["kind"]
                or type(checked["timestamp"]) not in (int, float)
                or not math.isfinite(float(checked["timestamp"])) or checked["timestamp"] < 0
            ):
                raise QaDeliveryError("strict QA report is invalid")
            _validate_identity_record({
                key: checked[key]
                for key in (
                    "path", "sha256", "bytes", "device", "inode",
                    "parent_device", "parent_inode",
                )
            })
            if checked["path"] in evidence_paths:
                raise QaDeliveryError("strict QA report is invalid")
            evidence_paths.add(str(checked["path"]))
        checks = top["checks"]
        if type(checks) is not list or not checks:
            raise QaDeliveryError("strict QA report is invalid")
        check_ids: set[str] = set()
        for item in checks:
            checked = _exact(item, {"id", "status", "evidence"})
            if (
                type(checked["id"]) is not str or not checked["id"]
                or checked["id"] in check_ids or checked["status"] != "pass"
                or type(checked["evidence"]) is not list
                or not all(type(value) is str and value for value in checked["evidence"])
            ):
                raise QaDeliveryError("strict QA report is invalid")
            if not set(checked["evidence"]).issubset(evidence_paths | {"08-preview/review.mp4"}):
                raise QaDeliveryError("strict QA report is invalid")
            check_ids.add(checked["id"])
        if check_ids != _QA_CHECK_IDS:
            raise QaDeliveryError("strict QA report is invalid")
        return top
    except (KeyboardInterrupt, SystemExit):
        raise
    except QaDeliveryError:
        raise
    except BaseException:
        raise QaDeliveryError("strict QA report is invalid") from None


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise QaDeliveryError("strict QA report is invalid")
    return value


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_identity_record(value: object) -> None:
    record = _exact(
        value,
        {"path", "sha256", "bytes", "device", "inode", "parent_device", "parent_inode"},
    )
    path = record["path"]
    if (
        type(path) is not str or not path or Path(path).is_absolute() or ".." in Path(path).parts
        or not _sha(record["sha256"])
        or any(type(record[key]) is not int or record[key] <= 0 for key in (
            "bytes", "device", "inode", "parent_device", "parent_inode",
        ))
    ):
        raise QaDeliveryError("strict QA report is invalid")


def validate_delivery_inventory(
    directory: Path, manifest: object,
) -> dict[str, object]:
    """Require the published tree to equal the manifest inventory exactly."""
    try:
        checked = _exact(manifest, {"version", "workflow", "retired_lineage", "artifacts"})
        if type(checked["version"]) is not int or checked["version"] != 1:
            raise QaDeliveryError("delivery inventory is invalid")
        workflow = _exact(checked["workflow"], {"revision", "sha256", "bytes"})
        if (
            type(workflow["revision"]) is not int or workflow["revision"] < 0
            or type(workflow["bytes"]) is not int or workflow["bytes"] <= 0
            or not _sha(workflow["sha256"])
        ):
            raise QaDeliveryError("delivery inventory is invalid")
        if type(checked["retired_lineage"]) is not list:
            raise QaDeliveryError("delivery inventory is invalid")
        artifacts = checked["artifacts"]
        if type(artifacts) is not dict or not artifacts:
            raise QaDeliveryError("delivery inventory is invalid")
        artifact_names = set(artifacts)
        if not _DELIVERY_REQUIRED.issubset(artifact_names) or any(
            name not in _DELIVERY_REQUIRED and not name.startswith("keyframes/")
            for name in artifact_names
        ):
            raise QaDeliveryError("delivery inventory is invalid")
        expected = set(artifacts) | {"delivery-manifest.json"}
        actual: set[str] = set()
        expected_directories = {
            parent.as_posix()
            for relative in expected
            for parent in Path(relative).parents
            if parent != Path(".")
        }
        actual_directories: set[str] = set()
        for parent, subdirectories, files in os.walk(directory, topdown=True, followlinks=False):
            base = Path(parent)
            if any((base / name).is_symlink() for name in subdirectories):
                raise QaDeliveryError("delivery inventory is invalid")
            actual_directories.update(
                (base / name).relative_to(directory).as_posix()
                for name in subdirectories
            )
            for name in files:
                path = base / name
                if path.is_symlink():
                    raise QaDeliveryError("delivery inventory is invalid")
                actual.add(path.relative_to(directory).as_posix())
        if actual != expected or actual_directories != expected_directories:
            raise QaDeliveryError("delivery inventory is invalid")
        for relative, binding in artifacts.items():
            if (
                type(relative) is not str or not relative or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                raise QaDeliveryError("delivery inventory is invalid")
            pair = _exact(binding, {"source", "output"})
            source_record = _exact(
                pair["source"],
                {
                    "path", "sha256", "bytes", "device", "inode",
                    "parent_device", "parent_inode",
                },
            )
            empty_subtitles = (
                relative == "subtitles.srt"
                and source_record["path"] == "06-subtitles/subtitles.srt"
                and type(source_record["bytes"]) is int
                and source_record["bytes"] == 0
            )
            _validate_identity_record(
                {**source_record, "bytes": 1} if empty_subtitles else source_record
            )
            output = _exact(pair["output"], {"path", "sha256", "bytes"})
            path = directory / relative
            source = path.read_bytes()
            if (
                output["path"] != relative or not _sha(output["sha256"])
                or type(output["bytes"]) is not int or output["bytes"] < 0
                or (output["bytes"] == 0 and not empty_subtitles)
                or output["sha256"] != pair["source"]["sha256"]
                or output["bytes"] != pair["source"]["bytes"]
                or len(source) != output["bytes"]
                or hashlib.sha256(source).hexdigest() != output["sha256"]
            ):
                raise QaDeliveryError("delivery inventory is invalid")
        manifest_source = (directory / "delivery-manifest.json").read_bytes()
        if manifest_source != _canonical_json(checked):
            raise QaDeliveryError("delivery inventory is invalid")
        return checked
    except (KeyboardInterrupt, SystemExit):
        raise
    except QaDeliveryError:
        raise
    except BaseException:
        raise QaDeliveryError("delivery inventory is invalid") from None


def prepare_delivery(job: state.JobState) -> DeliveryResult:
    """Copy the approved review generation into an immutable delivery generation."""
    if job.version == 2:
        from . import qa_delivery_v2

        return qa_delivery_v2.prepare_delivery_v2(job)
    publisher = StableGenerationPublisher(job.job_dir, "09-delivery")
    directory_descriptor: int | None = None
    pins: list[dict[str, object]] = []
    stage: Path | None = None
    transaction: Path | None = None
    target: Path | None = None
    backup: Path | None = None
    backup_records: list[dict[str, object]] = []
    try:
        publisher.acquire()
        directory_descriptor = os.open(
            job.job_dir,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        fcntl.flock(directory_descriptor, fcntl.LOCK_EX)
        fresh = state.load_job(job.job_dir)
        recovered = _recover_prepared_delivery(fresh)
        if recovered is not None:
            _sync_job(job, fresh)
            return recovered
        state.require_runnable(fresh, "delivery")
        sources = _delivery_sources(fresh)
        for destination, record in sources.items():
            pins.append(_pin_artifact(fresh, destination, record))
        stage = fresh.job_dir / f".09-delivery.stage-{secrets.token_hex(16)}"
        stage.mkdir(mode=0o700)
        manifest_artifacts: dict[str, object] = {}
        published: list[Path] = []
        for pin in pins:
            destination = stage / str(pin["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_descriptor(int(pin["descriptor"]), destination)
            source = {
                key: pin[key]
                for key in (
                    "path", "sha256", "bytes", "device", "inode",
                    "parent_device", "parent_inode",
                )
            }
            output_source = destination.read_bytes()
            manifest_artifacts[str(pin["destination"])] = {
                "source": source,
                "output": {
                    "path": str(pin["destination"]),
                    "sha256": hashlib.sha256(output_source).hexdigest(),
                    "bytes": len(output_source),
                },
            }
            published.append(destination)
        manifest = {
            "version": 1,
            "workflow": {
                "revision": fresh.revision,
                "sha256": fresh.expected_sha256,
                "bytes": fresh.expected_bytes,
            },
            "retired_lineage": fresh.stages["delivery"].get("lineage", []),
            "artifacts": manifest_artifacts,
        }
        manifest_path = stage / "delivery-manifest.json"
        _write_new(manifest_path, _canonical_json(manifest))
        published.append(manifest_path)
        _fsync_tree(stage)
        for pin in pins:
            _verify_pin(pin)
        transaction = fresh.job_dir / ".09-delivery.transaction.json"
        stage_status = os.lstat(stage)
        marker = {
            "version": 1,
            "stage": stage.name,
            "stage_device": stage_status.st_dev,
            "stage_inode": stage_status.st_ino,
            "workflow_revision": fresh.revision,
            "workflow_sha256": fresh.expected_sha256,
            "old_lineage": fresh.stages["delivery"].get("lineage", []),
            "manifest_sha256": hashlib.sha256(_canonical_json(manifest)).hexdigest(),
        }
        _write_new(transaction, _canonical_json(marker))
        _fsync_directory(fresh.job_dir)
        _delivery_checkpoint("prepared")
        target = fresh.job_dir / "09-delivery"
        if target.exists():
            _verify_old_delivery(fresh, target)
            backup_records = list(fresh.stages["delivery"].get("lineage", []))
            backup = fresh.job_dir / f".09-delivery.backup-{secrets.token_hex(16)}"
            os.rename(target, backup)
            _fsync_directory(fresh.job_dir)
            _delivery_checkpoint("old-moved")
        try:
            os.rename(stage, target)
        except BaseException:
            if backup is not None and not target.exists():
                os.rename(backup, target)
                backup = None
                _fsync_directory(fresh.job_dir)
            raise
        stage = None
        _fsync_directory(fresh.job_dir)
        _delivery_checkpoint("new-installed")
        target_paths = [target / item for item in manifest_artifacts]
        target_paths.append(target / "delivery-manifest.json")
        try:
            validate_delivery_inventory(target, manifest)
            state.mark_ready(fresh, "delivery", target_paths)
            _delivery_checkpoint("workflow-ready")
        except BaseException:
            committed = state.load_job(fresh.job_dir)
            if (
                committed.stages["delivery"]["status"] == "ready_for_review"
                and committed.revision == fresh.revision
            ):
                fresh = committed
            else:
                if target.exists():
                    rollback = fresh.job_dir / f".09-delivery.retained-{secrets.token_hex(16)}"
                    os.rename(target, rollback)
                    if backup is not None:
                        os.rename(backup, target)
                        backup = None
                    _fsync_directory(fresh.job_dir)
                raise
        if backup is not None:
            _zero_delivery_generation(backup, backup_records)
            os.rename(
                backup,
                fresh.job_dir / f".09-delivery.retired-{secrets.token_hex(16)}",
            )
            backup = None
            _fsync_directory(fresh.job_dir)
        _delivery_checkpoint("metadata-retired")
        _retire_transaction_marker(transaction, marker)
        _sync_job(job, fresh)
        final_source = (target / "final.mp4").read_bytes()
        return DeliveryResult(
            directory=target,
            artifacts=tuple(target_paths),
            manifest=manifest,
            media_summary={
                "sha256": hashlib.sha256(final_source).hexdigest(),
                "bytes": len(final_source),
            },
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except QaDeliveryError:
        raise
    except BaseException:
        raise QaDeliveryError("delivery preparation failed") from None
    finally:
        primary = __import__("sys").exc_info()[0] is not None
        close_failure = False
        for pin in pins:
            try:
                os.close(int(pin["descriptor"]))
            except OSError:
                close_failure = True
        if directory_descriptor is not None:
            try:
                fcntl.flock(directory_descriptor, fcntl.LOCK_UN)
            except OSError:
                close_failure = True
            try:
                os.close(directory_descriptor)
            except OSError:
                close_failure = True
        try:
            publisher.release()
        except BaseException:
            close_failure = True
        if stage is not None and stage.exists() and (
            transaction is None or not transaction.exists()
        ):
            try:
                os.rename(stage, stage.with_name(f".09-delivery.retained-{secrets.token_hex(16)}"))
            except OSError:
                pass
        if backup is not None and backup.exists():
            try:
                live = job.job_dir / "09-delivery"
                if not live.exists():
                    os.rename(backup, live)
                    _fsync_directory(job.job_dir)
            except OSError:
                pass
        if close_failure and not primary:
            raise QaDeliveryError("delivery preparation failed") from None


def _delivery_sources(job: state.JobState) -> dict[str, dict[str, object]]:
    required = {
        "inspection.json": ("inspect", "01-inspect/report.json"),
        "edit-plan.json": ("edit_structure", "03-edit-structure/edit-plan.json"),
        "visual-plan.json": ("visual_direction", "04-visual-direction/visual-plan.json"),
        "asset-manifest.json": ("visual_assets", "05-visual-assets/asset-manifest.json"),
        "subtitles.srt": ("subtitles", "06-subtitles/subtitles.srt"),
        "subtitles.webm": ("subtitles", "06-subtitles/subtitles.webm"),
        "cover-3x4.png": ("cover", "07-cover/cover-3x4.png"),
        "cover-9x16.png": ("cover", "07-cover/cover-9x16.png"),
        "cover-canvas.png": ("cover", "07-cover/cover-delivery-raster.png"),
        "final.mp4": ("preview", "08-preview/review.mp4"),
        "qa-report.json": ("preview", "08-preview/qa-report.json"),
        "contact-sheet.png": ("preview", "08-preview/contact-sheet.png"),
    }
    result: dict[str, dict[str, object]] = {}
    for destination, (stage_id, source_path) in required.items():
        result[destination] = _approved_record(job, stage_id, source_path)
    preview_records = job.stages["preview"]["artifacts"]
    for record in preview_records:
        path = record.get("path") if type(record) is dict else None
        prefix = "08-preview/keyframes/"
        if type(path) is str and path.startswith(prefix):
            relative = path[len("08-preview/"):]
            if relative in result:
                raise QaDeliveryError("delivery artifact binding is invalid")
            result[relative] = record
    qa_source = job.job_dir / result["qa-report.json"]["path"]
    try:
        qa_payload = json.loads(qa_source.read_text(encoding="utf-8"))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise QaDeliveryError("delivery artifact binding is invalid") from None
    try:
        validate_qa_report(qa_payload)
    except QaDeliveryError:
        raise QaDeliveryError("delivery artifact binding is invalid")
    return result


def _delivery_checkpoint(name: str) -> None:
    if os.environ.get("HD_DELIVERY_CRASH_CHECKPOINT") == name:
        os._exit(91)


def _recover_prepared_delivery(job: state.JobState) -> DeliveryResult | None:
    marker_path = job.job_dir / ".09-delivery.transaction.json"
    if not marker_path.exists():
        unfinished = [
            path for path in job.job_dir.iterdir()
            if path.name.startswith(".09-delivery.marker-retired-")
            and path.is_file() and not path.is_symlink() and path.stat().st_size > 0
        ]
        if not unfinished:
            return None
        if len(unfinished) != 1:
            raise QaDeliveryError("delivery recovery failed")
        marker_path = unfinished[0]
    try:
        marker_source = marker_path.read_bytes()
        marker = json.loads(marker_source.decode("utf-8"))
        if type(marker) is not dict or set(marker) != {
            "version", "stage", "stage_device", "stage_inode", "workflow_revision",
            "workflow_sha256", "old_lineage", "manifest_sha256",
        }:
            raise QaDeliveryError("delivery recovery failed")
        before_matches = (
            marker["workflow_revision"] == job.revision
            and marker["workflow_sha256"] == job.expected_sha256
        )
        ready_matches = (
            job.stages["delivery"]["status"] == "ready_for_review"
            and type(marker["workflow_revision"]) is int
            and job.revision == marker["workflow_revision"] + 1
        )
        if (
            marker["version"] != 1 or type(marker["stage"]) is not str
            or re.fullmatch(r"\.09-delivery\.stage-[0-9a-f]{32}", marker["stage"]) is None
            or type(marker["old_lineage"]) is not list
            or not (before_matches or ready_matches)
        ):
            raise QaDeliveryError("delivery recovery failed")
        stage = job.job_dir / marker["stage"]
        target = job.job_dir / "09-delivery"
        stage_exists = stage.exists()
        target_exists = target.exists()
        if stage_exists:
            status = os.lstat(stage)
            if (
                not stat.S_ISDIR(status.st_mode) or status.st_dev != marker["stage_device"]
                or status.st_ino != marker["stage_inode"]
            ):
                raise QaDeliveryError("delivery recovery failed")
        elif not target_exists:
            raise QaDeliveryError("delivery recovery failed")
        generation = stage if stage_exists else target
        manifest_source = (generation / "delivery-manifest.json").read_bytes()
        if hashlib.sha256(manifest_source).hexdigest() != marker["manifest_sha256"]:
            raise QaDeliveryError("delivery recovery failed")
        manifest = json.loads(manifest_source.decode("utf-8"))
        validate_delivery_inventory(generation, manifest)
        if marker["old_lineage"] != manifest["retired_lineage"]:
            raise QaDeliveryError("delivery recovery failed")
        current_sources = _delivery_sources(job)
        if set(current_sources) != set(manifest["artifacts"]):
            raise QaDeliveryError("delivery recovery failed")
        source_keys = (
            "path", "sha256", "bytes", "device", "inode", "parent_device", "parent_inode",
        )
        for destination, record in current_sources.items():
            pin = _pin_artifact(job, destination, record)
            try:
                if manifest["artifacts"][destination]["source"] != {
                    key: pin[key] for key in source_keys
                }:
                    raise QaDeliveryError("delivery recovery failed")
            finally:
                os.close(int(pin["descriptor"]))
        backups = sorted(
            path for path in job.job_dir.iterdir()
            if path.name.startswith(".09-delivery.backup-")
        )
        stage_status = job.stages["delivery"]["status"]
        installed_now = False
        created_backup: Path | None = None
        backup_records = list(marker["old_lineage"])
        if stage_status in {"pending", "needs_revision"}:
            if stage_exists:
                if target_exists:
                    if backups:
                        raise QaDeliveryError("delivery recovery failed")
                    _verify_old_delivery(job, target)
                    created_backup = job.job_dir / f".09-delivery.backup-{secrets.token_hex(16)}"
                    os.rename(target, created_backup)
                    backups.append(created_backup)
                    _fsync_directory(job.job_dir)
                os.rename(stage, target)
                installed_now = True
                _fsync_directory(job.job_dir)
            elif not target_exists:
                raise QaDeliveryError("delivery recovery failed")
        elif stage_status != "ready_for_review" or not target_exists:
            raise QaDeliveryError("delivery recovery failed")
        target_paths = [target / item for item in manifest["artifacts"]]
        target_paths.append(target / "delivery-manifest.json")
        if stage_status != "ready_for_review":
            try:
                state.mark_ready(job, "delivery", target_paths)
            except BaseException:
                committed = state.load_job(job.job_dir)
                if (
                    committed.stages["delivery"]["status"] == "ready_for_review"
                    and committed.revision == job.revision
                ):
                    _sync_job(job, committed)
                else:
                    if installed_now and target.exists():
                        os.rename(target, stage)
                    if backups and not target.exists():
                        os.rename(backups[0], target)
                        backups = backups[1:]
                    _fsync_directory(job.job_dir)
                    raise
        for backup in backups:
            if backup.exists():
                _zero_delivery_generation(backup, backup_records)
                os.rename(
                    backup,
                    job.job_dir / f".09-delivery.retired-{secrets.token_hex(16)}",
                )
        _fsync_directory(job.job_dir)
        _retire_transaction_marker(marker_path, marker)
        final_source = (target / "final.mp4").read_bytes()
        return DeliveryResult(
            directory=target,
            artifacts=tuple(target_paths),
            manifest=manifest,
            media_summary={
                "sha256": hashlib.sha256(final_source).hexdigest(),
                "bytes": len(final_source),
            },
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except QaDeliveryError:
        raise
    except BaseException:
        raise QaDeliveryError("delivery recovery failed") from None


def _retire_transaction_marker(path: Path, marker: dict[str, object]) -> None:
    source = _canonical_json(marker)
    if path.read_bytes() != source:
        raise QaDeliveryError("delivery recovery failed")
    retained = path
    if not path.name.startswith(".09-delivery.marker-retired-"):
        retained = path.with_name(f".09-delivery.marker-retired-{secrets.token_hex(16)}")
        os.rename(path, retained)
        _fsync_directory(path.parent)
        _delivery_checkpoint("marker-moved")
    descriptor = os.open(retained, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _verify_old_delivery(job: state.JobState, target: Path) -> None:
    lineage = job.stages["delivery"].get("lineage")
    if type(lineage) is not list or not lineage:
        raise QaDeliveryError("delivery artifact binding is invalid")
    expected = {str(record.get("path")) for record in lineage}
    actual: set[str] = set()
    expected_directories = {
        parent.relative_to("09-delivery").as_posix()
        for relative in expected
        for parent in Path(relative).parents
        if parent != Path("09-delivery") and Path("09-delivery") in parent.parents
    }
    actual_directories: set[str] = set()
    for directory, subdirectories, files in os.walk(target, topdown=True, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in subdirectories):
            raise QaDeliveryError("delivery artifact binding is invalid")
        actual_directories.update(
            (base / name).relative_to(target).as_posix() for name in subdirectories
        )
        for name in files:
            path = base / name
            if path.is_symlink():
                raise QaDeliveryError("delivery artifact binding is invalid")
            actual.add(path.relative_to(job.job_dir).as_posix())
    if actual != expected or actual_directories != expected_directories:
        raise QaDeliveryError("delivery artifact binding is invalid")
    for record in lineage:
        path = job.job_dir / str(record["path"])
        status = os.lstat(path)
        parent = os.lstat(path.parent)
        source = path.read_bytes()
        if (
            status.st_dev != record.get("device") or status.st_ino != record.get("inode")
            or parent.st_dev != record.get("parent_device")
            or parent.st_ino != record.get("parent_inode")
            or len(source) != record.get("bytes")
            or hashlib.sha256(source).hexdigest() != record.get("sha256")
        ):
            raise QaDeliveryError("delivery artifact binding is invalid")


def _zero_delivery_generation(
    directory: Path, records: list[dict[str, object]],
) -> None:
    normalized: list[tuple[dict[str, object], tuple[str, ...]]] = []
    for record in records:
        raw = record.get("path") if type(record) is dict else None
        candidate = Path(raw) if type(raw) is str else Path()
        if (
            type(raw) is not str or candidate.is_absolute() or len(candidate.parts) < 2
            or candidate.parts[0] != "09-delivery"
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise QaDeliveryError("delivery artifact binding is invalid")
        normalized.append((record, candidate.parts[1:]))
    actual = {
        path.relative_to(directory).parts
        for path in directory.rglob("*") if path.is_file() and not path.is_symlink()
    }
    if actual != {parts for _record, parts in normalized}:
        raise QaDeliveryError("delivery artifact binding is invalid")
    root_descriptor = os.open(
        directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        for record, parts in normalized:
            parent_descriptor = os.dup(root_descriptor)
            try:
                for component in parts[:-1]:
                    child = os.open(
                        component,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_descriptor,
                    )
                    os.close(parent_descriptor)
                    parent_descriptor = child
                descriptor = os.open(
                    parts[-1], os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_descriptor,
                )
            finally:
                os.close(parent_descriptor)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or opened.st_dev != record.get("device") or opened.st_ino != record.get("inode")
                    or _digest_descriptor(descriptor)
                    != (record.get("sha256"), record.get("bytes"))
                ):
                    raise QaDeliveryError("delivery artifact binding is invalid")
                os.ftruncate(descriptor, 0)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        os.close(root_descriptor)
    _fsync_tree(directory)


def _approved_record(job: state.JobState, stage_id: str, path: str) -> dict[str, object]:
    stage_value = job.stages.get(stage_id)
    if type(stage_value) is not dict or stage_value.get("status") != "approved":
        raise QaDeliveryError("delivery artifact binding is invalid")
    matches = [record for record in stage_value.get("artifacts", []) if record.get("path") == path]
    if len(matches) != 1:
        raise QaDeliveryError("delivery artifact binding is invalid")
    return matches[0]


def _pin_artifact(
    job: state.JobState, destination: str, record: dict[str, object],
) -> dict[str, object]:
    path_value = record.get("path")
    if type(path_value) is not str or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
        raise QaDeliveryError("delivery artifact binding is invalid")
    path = job.job_dir / path_value
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        parent = os.lstat(path.parent)
        if (
            not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or not os.path.samestat(opened, named) or not stat.S_ISDIR(parent.st_mode)
        ):
            raise QaDeliveryError("delivery artifact binding is invalid")
        sha256, size = _digest_descriptor(descriptor)
        if sha256 != record.get("sha256") or size != record.get("bytes"):
            raise QaDeliveryError("delivery artifact binding is invalid")
        return {
            "destination": destination,
            "descriptor": descriptor,
            "absolute": path,
            "path": path_value,
            "sha256": sha256,
            "bytes": size,
            "device": opened.st_dev,
            "inode": opened.st_ino,
            "parent_device": parent.st_dev,
            "parent_inode": parent.st_ino,
        }
    except BaseException:
        os.close(descriptor)
        raise


def _digest_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        digest.update(block)
        size += len(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), size


def _verify_pin(pin: dict[str, object]) -> None:
    descriptor = int(pin["descriptor"])
    status = os.fstat(descriptor)
    try:
        named = os.lstat(Path(str(pin["absolute"])))
        parent = os.lstat(Path(str(pin["absolute"])).parent)
    except OSError:
        raise QaDeliveryError("delivery artifact binding is invalid") from None
    if (
        status.st_dev != pin["device"] or status.st_ino != pin["inode"]
        or not os.path.samestat(status, named)
        or parent.st_dev != pin["parent_device"] or parent.st_ino != pin["parent_inode"]
    ):
        raise QaDeliveryError("delivery artifact binding is invalid")
    if _digest_descriptor(descriptor) != (pin["sha256"], pin["bytes"]):
        raise QaDeliveryError("delivery artifact binding is invalid")


def _copy_descriptor(source: int, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.lseek(source, 0, os.SEEK_SET)
        while True:
            block = os.read(source, 1024 * 1024)
            if not block:
                break
            view = memoryview(block)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
        os.fsync(descriptor)
        os.lseek(source, 0, os.SEEK_SET)
    finally:
        os.close(descriptor)


def _canonical_json(payload: object) -> bytes:
    try:
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise QaDeliveryError("delivery artifact binding is invalid") from None


def _write_new(path: Path, source: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600,
    )
    try:
        view = memoryview(source)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(path: Path) -> None:
    for directory, _subdirs, _files in os.walk(path, topdown=False):
        _fsync_directory(Path(directory))


def _sync_job(target: state.JobState, source: state.JobState) -> None:
    target.revision = source.revision
    target.expected_revision = source.expected_revision
    target.expected_sha256 = source.expected_sha256
    target.expected_bytes = source.expected_bytes
    target.stages.clear()
    target.stages.update(source.stages)

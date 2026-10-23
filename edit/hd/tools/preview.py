"""Prepare the HD review render and its dynamically derived QA evidence."""

from __future__ import annotations

import math
import hashlib
import json
import subprocess
import fcntl
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageOps

from . import state


__all__ = [
    "PreviewError",
    "PreviewResult",
    "build_preview_command",
    "validate_preview_command",
    "build_evidence_schedule",
    "validate_preview_media",
    "prepare_preview",
]


class PreviewError(RuntimeError):
    """A sanitized preview-stage failure."""


@dataclass(frozen=True)
class PreviewResult:
    directory: Path
    review: Path
    artifacts: tuple[Path, ...]
    qa_report: dict[str, object]
    media_summary: dict[str, object]


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise PreviewError("preview contract is invalid")
    return value


def _positive_number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
        raise PreviewError("preview contract is invalid")
    return float(value)


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def build_preview_command(
    *,
    visual_track: Path,
    subtitle_track: Path,
    edited_aroll: Path,
    cover_raster: Path,
    output: Path,
    width: int,
    height: int,
    fps: int | float,
    frames: int,
) -> list[str]:
    """Build the one-video/one-audio preview command without touching audio."""
    checked_width = _positive_int(width)
    checked_height = _positive_int(height)
    checked_frames = _positive_int(frames)
    checked_fps = _positive_number(fps)
    fps_text = _number_text(checked_fps)
    graph = (
        f"[0:v:0]scale={checked_width}:{checked_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={checked_width}:{checked_height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps_text},format=yuv420p,setpts=PTS-STARTPTS[visual];"
        f"[3:v:0]scale={checked_width}:{checked_height},fps={fps_text},"
        "trim=end_frame=1,setpts=PTS-STARTPTS[cover];"
        "[visual][cover]overlay=0:0:enable='eq(n,0)':eof_action=pass[covered];"
        f"[1:v:0]scale={checked_width}:{checked_height},fps={fps_text},"
        "format=rgba,setpts=PTS-STARTPTS[subtitles];"
        "[covered][subtitles]overlay=0:0:eof_action=pass[composed];"
        f"[composed]trim=end_frame={checked_frames}[outv]"
    )
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
        "-i", str(visual_track),
        "-c:v", "libvpx-vp9", "-i", str(subtitle_track),
        "-i", str(edited_aroll),
        "-loop", "1", "-framerate", fps_text, "-i", str(cover_raster),
        "-filter_complex", graph,
        "-map", "[outv]", "-map", "2:a:0",
        "-r", fps_text,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        str(output),
    ]
    validate_preview_command(command)
    return command


def validate_preview_command(command: Sequence[str]) -> None:
    """Reject command shapes that can filter/re-encode audio or cover subtitles."""
    if type(command) not in (list, tuple) or not all(type(item) is str for item in command):
        raise PreviewError("preview command is invalid")
    joined = " ".join(command)
    if any(token in joined for token in ("loudnorm", "volume", "aresample")):
        raise PreviewError("preview command is invalid")
    if any(token in command for token in ("-af", "-filter:a")):
        raise PreviewError("preview command is invalid")
    try:
        graph = command[command.index("-filter_complex") + 1]
        if command[command.index("-c:a") + 1] != "copy":
            raise ValueError
        maps = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "-map"]
    except (ValueError, IndexError):
        raise PreviewError("preview command is invalid") from None
    if maps != ["[outv]", "2:a:0"]:
        raise PreviewError("preview command is invalid")
    cover = graph.find("[visual][cover]overlay")
    subtitles = graph.find("[covered][subtitles]overlay")
    if (
        cover < 0 or subtitles <= cover or not graph.endswith("[outv]")
        or "trim=end_frame=" not in graph or "-frames:v" in command
    ):
        raise PreviewError("preview command is invalid")


def _records(value: object, key: str) -> list[dict[str, object]]:
    if type(value) is not dict or type(value.get(key)) is not list:
        raise PreviewError("preview evidence plan is invalid")
    records = value[key]
    if not all(type(record) is dict for record in records):
        raise PreviewError("preview evidence plan is invalid")
    return records


def build_evidence_schedule(
    edit_plan: object,
    timeline_map: object,
    visual_plan: object,
    subtitle_plan: object,
) -> list[dict[str, object]]:
    """Derive evidence solely from the current job's plans."""
    del edit_plan  # The timeline map is the authoritative output-time projection.
    timeline_segments = _records(timeline_map, "segments")
    visual_segments = _records(visual_plan, "segments")
    cues = _records(subtitle_plan, "cues")
    canvas = subtitle_plan.get("canvas") if type(subtitle_plan) is dict else None
    if type(canvas) is not dict:
        raise PreviewError("preview evidence plan is invalid")
    fps = _positive_number(canvas.get("fps"))
    frames = _positive_int(canvas.get("frames"))
    duration = frames / fps
    schedule: list[dict[str, object]] = []
    paths: set[str] = set()

    def add(identifier: str, kind: str, timestamp: float, path: str) -> None:
        if (
            type(identifier) is not str or not identifier
            or type(timestamp) not in (int, float) or not math.isfinite(float(timestamp))
            or not 0 <= float(timestamp) < duration or path in paths
        ):
            raise PreviewError("preview evidence plan is invalid")
        paths.add(path)
        schedule.append({
            "id": identifier, "kind": kind, "timestamp": float(timestamp), "path": path,
        })

    add("cover-000", "cover_frame", 0.0, "keyframes/cover/frame-000.png")
    add("cover-001", "cover_frame", 1 / fps, "keyframes/cover/frame-001.png")
    for index, segment in enumerate(timeline_segments[:-1]):
        cut = float(segment.get("timeline_end"))
        for label, timestamp in (
            ("before", cut - 1 / fps), ("at", cut), ("after", cut + 1 / fps),
        ):
            add(
                f"cut-{index + 1:03d}-{label}", "cut_boundary", timestamp,
                f"keyframes/cuts/cut-{index + 1:03d}-{label}.png",
            )
    for cue in cues:
        cue_id = cue.get("id")
        start, end = float(cue.get("start")), float(cue.get("end"))
        add(
            str(cue_id), "subtitle_midpoint", (start + end) / 2,
            f"keyframes/subtitles/{cue_id}-midpoint.png",
        )
    for segment in visual_segments:
        segment_id = segment.get("segment_id")
        start, end = float(segment.get("start")), float(segment.get("end"))
        implementation = str(segment.get("implementation"))
        visual_type = str(segment.get("visual_type"))
        add(
            str(segment_id), "visual_keyframe", (start + end) / 2,
            f"keyframes/visuals/{segment_id}-{implementation}-{visual_type}.png",
        )
    return schedule


def validate_preview_media(
    preview: Path,
    *,
    edited_aroll: Path,
    cover_raster: Path,
    canvas: Mapping[str, object],
) -> dict[str, object]:
    """Validate complete decode, media shape, cover frames and audio packets."""
    try:
        width = _positive_int(canvas.get("width"))
        height = _positive_int(canvas.get("height"))
        fps = _positive_number(canvas.get("fps"))
        frames = _positive_int(canvas.get("frames"))
        duration = _positive_number(canvas.get("duration"))
        if frames != round(duration * fps):
            raise PreviewError("preview media validation failed")
        probe = _run_media([
            "ffprobe", "-v", "error", "-count_frames", "-show_entries",
            "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,duration,"
            "nb_read_frames,sample_rate,channels:format=duration",
            "-of", "json", str(preview),
        ])
        payload = _strict_json(probe.stdout)
        if type(payload) is not dict or type(payload.get("streams")) is not list:
            raise PreviewError("preview media validation failed")
        streams = payload["streams"]
        videos = [item for item in streams if type(item) is dict and item.get("codec_type") == "video"]
        audios = [item for item in streams if type(item) is dict and item.get("codec_type") == "audio"]
        if len(streams) != 2 or len(videos) != 1 or len(audios) != 1:
            raise PreviewError("preview media validation failed")
        video = videos[0]
        expected_rate = f"{_number_text(fps)}/1"
        if (
            video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p"
            or video.get("width") != width or video.get("height") != height
            or video.get("r_frame_rate") != expected_rate
            or video.get("avg_frame_rate") != expected_rate
            or video.get("nb_read_frames") != str(frames)
        ):
            raise PreviewError("preview media validation failed")
        actual_duration = float(payload.get("format", {}).get("duration"))
        video_duration = float(video.get("duration"))
        if (
            not math.isfinite(actual_duration)
            or not math.isfinite(video_duration)
            or abs(video_duration - duration) > 1 / fps
            or actual_duration < duration - 1 / fps
            or actual_duration - duration > 1.0
        ):
            raise PreviewError("preview media validation failed")
        _run_media([
            "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
            "-i", str(preview), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ])
        source_audio = _audio_packet_hash(edited_aroll)
        preview_audio = _audio_packet_hash(preview)
        if source_audio != preview_audio:
            raise PreviewError("preview media validation failed")
        frame_zero = _raw_frame(preview, 0, width, height)
        frame_one = _raw_frame(preview, 1, width, height)
        cover = _raw_frame(cover_raster, 0, width, height)
        if _mean_difference(frame_zero, cover) > 12.0:
            raise PreviewError("preview media validation failed")
        if _mean_difference(frame_one, cover) < 24.0:
            raise PreviewError("preview media validation failed")
        return {
            "duration": actual_duration,
            "frames": frames,
            "video_streams": len(videos),
            "audio_streams": len(audios),
            "video": video,
            "audio": audios[0],
            "source_audio_packet_hash": source_audio,
            "preview_audio_packet_hash": preview_audio,
            "frame_zero": "cover",
            "frame_one": "content",
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except PreviewError:
        raise
    except BaseException:
        raise PreviewError("preview media validation failed") from None


def _strict_json(source: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    return json.loads(
        source,
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


def _run_media(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise PreviewError("preview media validation failed") from None


def _audio_packet_hash(path: Path) -> str:
    probe = _run_media([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets",
        "-show_entries", "packet=size,data_hash", "-show_data_hash", "sha256",
        "-of", "json", str(path),
    ])
    payload = _strict_json(probe.stdout)
    packets = payload.get("packets") if type(payload) is dict else None
    if type(packets) is not list or not packets:
        raise PreviewError("preview media validation failed")
    digest = hashlib.sha256()
    for packet in packets:
        if type(packet) is not dict or type(packet.get("size")) is not str:
            raise PreviewError("preview media validation failed")
        data_hash = packet.get("data_hash")
        if type(data_hash) is not str or not data_hash.startswith("SHA256:"):
            raise PreviewError("preview media validation failed")
        digest.update(packet["size"].encode("ascii"))
        digest.update(b"\0")
        digest.update(data_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _raw_frame(path: Path, index: int, width: int, height: int) -> bytes:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        "-i", str(path), "-vf", f"select=eq(n\\,{index}),scale={width}:{height}",
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise PreviewError("preview media validation failed") from None
    expected = width * height * 3
    if len(result.stdout) != expected:
        raise PreviewError("preview media validation failed")
    return result.stdout


def _mean_difference(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        raise PreviewError("preview media validation failed")
    return sum(abs(first - second) for first, second in zip(left, right)) / len(left)


def prepare_preview(job: state.JobState) -> PreviewResult:
    """Build one exact preview generation and stop at ready-for-review."""
    if job.version == 2:
        from . import preview_v2

        return preview_v2.prepare_preview_v2(job)
    publisher = None
    lock: int | None = None
    pins: dict[str, dict[str, object]] = {}
    stage: Path | None = None
    transaction: Path | None = None
    backup: Path | None = None
    backup_records: list[dict[str, object]] = []
    try:
        from . import qa_delivery

        publisher = qa_delivery.StableGenerationPublisher(job.job_dir, "08-preview")
        publisher.acquire()
        lock = os.open(
            job.job_dir,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        fcntl.flock(lock, fcntl.LOCK_EX)
        fresh = state.load_job(job.job_dir)
        wanted = {
            "inspection": ("inspect", "01-inspect/report.json"),
            "edit_plan": ("edit_structure", "03-edit-structure/edit-plan.json"),
            "timeline_map": ("edit_structure", "03-edit-structure/timeline-map.json"),
            "edited_aroll": ("edit_structure", "03-edit-structure/edited-aroll.mp4"),
            "visual_plan": ("visual_direction", "04-visual-direction/visual-plan.json"),
            "asset_manifest": ("visual_assets", "05-visual-assets/asset-manifest.json"),
            "visual_track": ("visual_assets", "05-visual-assets/visual-track.mp4"),
            "subtitle_plan": ("subtitles", "06-subtitles/subtitle-plan.json"),
            "subtitle_track": ("subtitles", "06-subtitles/subtitles.webm"),
            "cover_raster": ("cover", "07-cover/cover-delivery-raster.png"),
        }
        for label, (stage_id, relative) in wanted.items():
            pins[label] = _pin_approved_artifact(fresh, stage_id, relative)
        edit_plan = _pin_json(pins["edit_plan"])
        timeline_map = _pin_json(pins["timeline_map"])
        visual_plan = _pin_json(pins["visual_plan"])
        subtitle_plan = _pin_json(pins["subtitle_plan"])
        asset_manifest = _pin_json(pins["asset_manifest"])
        canvas = subtitle_plan.get("canvas") if type(subtitle_plan) is dict else None
        if type(canvas) is not dict:
            raise PreviewError("preview preparation failed")
        width = _positive_int(canvas.get("width"))
        height = _positive_int(canvas.get("height"))
        fps = _positive_number(canvas.get("fps"))
        frames = _positive_int(canvas.get("frames"))
        duration = _positive_number(canvas.get("duration"))
        if frames != round(duration * fps):
            raise PreviewError("preview preparation failed")
        recovered = _recover_prepared_preview(fresh, pins, canvas)
        if recovered is not None:
            _sync_preview_job(job, fresh)
            return recovered
        state.require_runnable(fresh, "preview")
        schedule = build_evidence_schedule(edit_plan, timeline_map, visual_plan, subtitle_plan)
        stage = fresh.job_dir / f".08-preview.stage-{secrets.token_hex(16)}"
        stage.mkdir(mode=0o700)
        review = stage / "review.mp4"
        command = build_preview_command(
            visual_track=_fd_path(pins["visual_track"]),
            subtitle_track=_fd_path(pins["subtitle_track"]),
            edited_aroll=_fd_path(pins["edited_aroll"]),
            cover_raster=_fd_path(pins["cover_raster"]),
            output=review,
            width=width,
            height=height,
            fps=fps,
            frames=frames,
        )
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=300,
            pass_fds=tuple(int(pin["descriptor"]) for pin in pins.values()),
        )
        media = validate_preview_media(
            review,
            edited_aroll=Path(str(pins["edited_aroll"]["absolute"])),
            cover_raster=Path(str(pins["cover_raster"]["absolute"])),
            canvas=canvas,
        )
        evidence = _extract_evidence(review, stage, schedule)
        contact = stage / "contact-sheet.png"
        _contact_sheet(stage, evidence, contact)
        preview_identity = _identity_record(review, "08-preview/review.mp4")
        workflow_binding = {
            "workflow": {
                "revision": fresh.revision,
                "sha256": fresh.expected_sha256,
                "bytes": fresh.expected_bytes,
            },
            "plan_hashes": {
                "edit_plan": pins["edit_plan"]["sha256"],
                "visual_plan": pins["visual_plan"]["sha256"],
                "subtitle_plan": pins["subtitle_plan"]["sha256"],
            },
            "inputs": {
                "preview": preview_identity,
                **{
                    label: _pin_identity(pin)
                    for label, pin in pins.items()
                },
            },
            "retired_lineage": fresh.stages["preview"].get("lineage", []),
        }
        report, media = qa_delivery.run_strict_qa(
            preview=review,
            edited_aroll=Path(str(pins["edited_aroll"]["absolute"])),
            cover_raster=Path(str(pins["cover_raster"]["absolute"])),
            edit_plan=edit_plan,
            timeline_map=timeline_map,
            visual_plan=visual_plan,
            subtitle_plan=subtitle_plan,
            asset_manifest=asset_manifest,
            evidence=evidence,
            workflow_binding=workflow_binding,
        )
        report_path = stage / "qa-report.json"
        _write_bytes(report_path, _canonical(report))
        artifacts = [review, report_path, contact]
        artifacts.extend(stage / str(item["path"]) for item in evidence)
        for pin in pins.values():
            _verify_artifact_pin(pin)
        _fsync_preview_tree(stage)
        transaction = fresh.job_dir / ".08-preview.transaction.json"
        stage_status = os.lstat(stage)
        marker = {
            "version": 1,
            "stage": stage.name,
            "stage_device": stage_status.st_dev,
            "stage_inode": stage_status.st_ino,
            "workflow_revision": fresh.revision,
            "workflow_sha256": fresh.expected_sha256,
            "workflow_bytes": fresh.expected_bytes,
            "old_lineage": fresh.stages["preview"].get("lineage", []),
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        }
        _write_bytes(transaction, _canonical(marker))
        _fsync_path(fresh.job_dir)
        _preview_checkpoint("prepared")
        target = fresh.job_dir / "08-preview"
        if target.exists():
            _verify_old_preview(fresh, target)
            backup_records = list(fresh.stages["preview"].get("lineage", []))
            backup = fresh.job_dir / f".08-preview.backup-{secrets.token_hex(16)}"
            os.rename(target, backup)
            _fsync_path(fresh.job_dir)
            _preview_checkpoint("old-moved")
        try:
            os.rename(stage, target)
        except BaseException:
            if backup is not None and not target.exists():
                os.rename(backup, target)
                backup = None
                _fsync_path(fresh.job_dir)
            raise
        stage = None
        _fsync_path(fresh.job_dir)
        _preview_checkpoint("new-installed")
        target_artifacts = [target / "review.mp4", target / "qa-report.json", target / "contact-sheet.png"]
        target_artifacts.extend(target / str(item["path"]) for item in evidence)
        try:
            state.mark_ready(fresh, "preview", target_artifacts)
            _preview_checkpoint("workflow-ready")
        except BaseException:
            committed = state.load_job(fresh.job_dir)
            if (
                committed.stages["preview"]["status"] == "ready_for_review"
                and committed.revision == fresh.revision
            ):
                fresh = committed
            else:
                retained = fresh.job_dir / f".08-preview.retained-{secrets.token_hex(16)}"
                os.rename(target, retained)
                if backup is not None:
                    os.rename(backup, target)
                    backup = None
                _fsync_path(fresh.job_dir)
                raise
        if backup is not None:
            _zero_preview_generation(backup, backup_records)
            os.rename(
                backup,
                fresh.job_dir / f".08-preview.retired-{secrets.token_hex(16)}",
            )
            backup = None
            _fsync_path(fresh.job_dir)
        _preview_checkpoint("metadata-retired")
        _retire_preview_marker(transaction, marker)
        _sync_preview_job(job, fresh)
        return PreviewResult(
            directory=target,
            review=target / "review.mp4",
            artifacts=tuple(target_artifacts),
            qa_report=report,
            media_summary=media,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except PreviewError:
        raise
    except BaseException:
        raise PreviewError("preview preparation failed") from None
    finally:
        active = __import__("sys").exc_info()[0] is not None
        close_error = False
        for pin in pins.values():
            try:
                os.close(int(pin["descriptor"]))
            except OSError:
                close_error = True
        if lock is not None:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError:
                close_error = True
            try:
                os.close(lock)
            except OSError:
                close_error = True
        if publisher is not None:
            try:
                publisher.release()
            except BaseException:
                close_error = True
        if stage is not None and stage.exists() and (
            transaction is None or not transaction.exists()
        ):
            try:
                os.rename(stage, stage.with_name(f".08-preview.retained-{secrets.token_hex(16)}"))
            except OSError:
                pass
        if backup is not None and backup.exists():
            try:
                target = job.job_dir / "08-preview"
                if not target.exists():
                    os.rename(backup, target)
                    _fsync_path(job.job_dir)
            except OSError:
                pass
        if close_error and not active:
            raise PreviewError("preview preparation failed") from None


def _approved_record(job: state.JobState, stage_id: str, relative: str) -> dict[str, object]:
    stage_value = job.stages.get(stage_id)
    if type(stage_value) is not dict or stage_value.get("status") != "approved":
        raise PreviewError("preview preparation failed")
    matches = [item for item in stage_value.get("artifacts", []) if item.get("path") == relative]
    if len(matches) != 1:
        raise PreviewError("preview preparation failed")
    return matches[0]


def _preview_checkpoint(name: str) -> None:
    if os.environ.get("HD_PREVIEW_CRASH_CHECKPOINT") == name:
        os._exit(91)


def _recover_prepared_preview(
    job: state.JobState,
    pins: dict[str, dict[str, object]],
    canvas: Mapping[str, object],
) -> PreviewResult | None:
    marker_path = job.job_dir / ".08-preview.transaction.json"
    if not marker_path.exists():
        unfinished = [
            path for path in job.job_dir.iterdir()
            if path.name.startswith(".08-preview.marker-retired-")
            and path.is_file() and not path.is_symlink() and path.stat().st_size > 0
        ]
        if not unfinished:
            return None
        if len(unfinished) != 1:
            raise PreviewError("preview recovery failed")
        marker_path = unfinished[0]
    try:
        marker = _strict_json(marker_path.read_text(encoding="utf-8"))
        if type(marker) is not dict or set(marker) != {
            "version", "stage", "stage_device", "stage_inode", "workflow_revision",
            "workflow_sha256", "workflow_bytes", "old_lineage", "report_sha256",
        }:
            raise PreviewError("preview recovery failed")
        before_matches = (
            marker["workflow_revision"] == job.revision
            and marker["workflow_sha256"] == job.expected_sha256
        )
        ready_matches = (
            job.stages["preview"]["status"] == "ready_for_review"
            and type(marker["workflow_revision"]) is int
            and job.revision == marker["workflow_revision"] + 1
        )
        if (
            marker["version"] != 1 or type(marker["stage"]) is not str
            or re.fullmatch(r"\.08-preview\.stage-[0-9a-f]{32}", marker["stage"]) is None
            or type(marker["old_lineage"]) is not list
            or not (before_matches or ready_matches)
        ):
            raise PreviewError("preview recovery failed")
        stage = job.job_dir / str(marker["stage"])
        target = job.job_dir / "08-preview"
        stage_exists = stage.exists()
        target_exists = target.exists()
        if stage_exists:
            status = os.lstat(stage)
            if (
                not stat.S_ISDIR(status.st_mode) or status.st_dev != marker["stage_device"]
                or status.st_ino != marker["stage_inode"]
            ):
                raise PreviewError("preview recovery failed")
        elif not target_exists:
            raise PreviewError("preview recovery failed")
        generation = stage if stage_exists else target
        report_source = (generation / "qa-report.json").read_bytes()
        if hashlib.sha256(report_source).hexdigest() != marker["report_sha256"]:
            raise PreviewError("preview recovery failed")
        report = _strict_json(report_source.decode("utf-8"))
        from . import qa_delivery

        qa_delivery.validate_qa_report(report)
        expected_inputs = {
            "preview": _identity_record(generation / "review.mp4", "08-preview/review.mp4"),
            **{label: _pin_identity(pin) for label, pin in pins.items()},
        }
        expected_binding = {
            "workflow": {
                "revision": marker["workflow_revision"],
                "sha256": marker["workflow_sha256"],
                "bytes": marker["workflow_bytes"],
            },
            "plan_hashes": {
                "edit_plan": pins["edit_plan"]["sha256"],
                "visual_plan": pins["visual_plan"]["sha256"],
                "subtitle_plan": pins["subtitle_plan"]["sha256"],
            },
            "inputs": expected_inputs,
            "retired_lineage": marker["old_lineage"],
        }
        if any(report[key] != expected_binding[key] for key in expected_binding):
            raise PreviewError("preview recovery failed")
        checked_report, _checked_media = qa_delivery.run_strict_qa(
            preview=generation / "review.mp4",
            edited_aroll=Path(str(pins["edited_aroll"]["absolute"])),
            cover_raster=Path(str(pins["cover_raster"]["absolute"])),
            edit_plan=_pin_json(pins["edit_plan"]),
            timeline_map=_pin_json(pins["timeline_map"]),
            visual_plan=_pin_json(pins["visual_plan"]),
            subtitle_plan=_pin_json(pins["subtitle_plan"]),
            asset_manifest=_pin_json(pins["asset_manifest"]),
            evidence=report["evidence"],
            workflow_binding=expected_binding,
        )
        if checked_report != report:
            raise PreviewError("preview recovery failed")
        target_artifacts = [generation / "review.mp4", generation / "qa-report.json", generation / "contact-sheet.png"]
        target_artifacts.extend(generation / str(item["path"]) for item in report["evidence"])
        if not all(path.is_file() and not path.is_symlink() for path in target_artifacts):
            raise PreviewError("preview recovery failed")
        backups = sorted(
            path for path in job.job_dir.iterdir()
            if path.name.startswith(".08-preview.backup-")
        )
        installed_now = False
        backup_records = list(marker["old_lineage"])
        stage_status = job.stages["preview"]["status"]
        if stage_status in {"pending", "needs_revision"}:
            if stage_exists:
                if target_exists:
                    if backups:
                        raise PreviewError("preview recovery failed")
                    _verify_old_preview(job, target)
                    backup = job.job_dir / f".08-preview.backup-{secrets.token_hex(16)}"
                    os.rename(target, backup)
                    backups.append(backup)
                    _fsync_path(job.job_dir)
                os.rename(stage, target)
                installed_now = True
                _fsync_path(job.job_dir)
            elif not target_exists:
                raise PreviewError("preview recovery failed")
        elif stage_status != "ready_for_review" or not target_exists:
            raise PreviewError("preview recovery failed")
        published = [target / path.relative_to(generation) for path in target_artifacts]
        if stage_status != "ready_for_review":
            try:
                state.mark_ready(job, "preview", published)
            except BaseException:
                committed = state.load_job(job.job_dir)
                if (
                    committed.stages["preview"]["status"] == "ready_for_review"
                    and committed.revision == job.revision
                ):
                    _sync_preview_job(job, committed)
                else:
                    if installed_now and target.exists():
                        os.rename(target, stage)
                    if backups and not target.exists():
                        os.rename(backups[0], target)
                        backups = backups[1:]
                    _fsync_path(job.job_dir)
                    raise
        for backup in backups:
            if backup.exists():
                _zero_preview_generation(backup, backup_records)
                os.rename(
                    backup,
                    job.job_dir / f".08-preview.retired-{secrets.token_hex(16)}",
                )
        _fsync_path(job.job_dir)
        _retire_preview_marker(marker_path, marker)
        media = validate_preview_media(
            target / "review.mp4",
            edited_aroll=Path(str(pins["edited_aroll"]["absolute"])),
            cover_raster=Path(str(pins["cover_raster"]["absolute"])),
            canvas=canvas,
        )
        return PreviewResult(
            directory=target,
            review=target / "review.mp4",
            artifacts=tuple(published),
            qa_report=report,
            media_summary=media,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except PreviewError:
        raise
    except BaseException:
        raise PreviewError("preview recovery failed") from None


def _retire_preview_marker(path: Path, marker: dict[str, object]) -> None:
    if path.read_bytes() != _canonical(marker):
        raise PreviewError("preview recovery failed")
    retained = path
    if not path.name.startswith(".08-preview.marker-retired-"):
        retained = path.with_name(f".08-preview.marker-retired-{secrets.token_hex(16)}")
        os.rename(path, retained)
        _fsync_path(path.parent)
        _preview_checkpoint("marker-moved")
    descriptor = os.open(retained, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_path(path.parent)


def _fsync_preview_tree(path: Path) -> None:
    for directory, _subdirectories, _files in os.walk(path, topdown=False):
        _fsync_path(Path(directory))


def _verify_old_preview(job: state.JobState, target: Path) -> None:
    lineage = job.stages["preview"].get("lineage")
    if type(lineage) is not list or not lineage:
        raise PreviewError("preview preparation failed")
    expected_paths = {str(record.get("path")) for record in lineage}
    actual_paths: set[str] = set()
    expected_directories = {
        parent.relative_to("08-preview").as_posix()
        for relative in expected_paths
        for parent in Path(relative).parents
        if parent != Path("08-preview") and Path("08-preview") in parent.parents
    }
    actual_directories: set[str] = set()
    for directory, subdirectories, files in os.walk(target, topdown=True, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in subdirectories):
            raise PreviewError("preview preparation failed")
        actual_directories.update(
            (base / name).relative_to(target).as_posix() for name in subdirectories
        )
        for name in files:
            path = base / name
            if path.is_symlink():
                raise PreviewError("preview preparation failed")
            actual_paths.add(path.relative_to(job.job_dir).as_posix())
    if actual_paths != expected_paths or actual_directories != expected_directories:
        raise PreviewError("preview preparation failed")
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
            raise PreviewError("preview preparation failed")


def _zero_preview_generation(
    directory: Path, records: list[dict[str, object]],
) -> None:
    normalized: list[tuple[dict[str, object], tuple[str, ...]]] = []
    for record in records:
        raw = record.get("path") if type(record) is dict else None
        candidate = Path(raw) if type(raw) is str else Path()
        if (
            type(raw) is not str or candidate.is_absolute() or len(candidate.parts) < 2
            or candidate.parts[0] != "08-preview"
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise PreviewError("preview preparation failed")
        normalized.append((record, candidate.parts[1:]))
    actual = {
        path.relative_to(directory).parts
        for path in directory.rglob("*") if path.is_file() and not path.is_symlink()
    }
    if actual != {parts for _record, parts in normalized}:
        raise PreviewError("preview preparation failed")
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
                    or _descriptor_digest(descriptor)
                    != (record.get("sha256"), record.get("bytes"))
                ):
                    raise PreviewError("preview preparation failed")
                os.ftruncate(descriptor, 0)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        os.close(root_descriptor)
    _fsync_preview_tree(directory)


def _pin_approved_artifact(
    job: state.JobState, stage_id: str, relative: str,
) -> dict[str, object]:
    record = _approved_record(job, stage_id, relative)
    absolute = job.job_dir / relative
    descriptor = os.open(absolute, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(absolute)
        parent = os.lstat(absolute.parent)
        if (
            not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or not os.path.samestat(opened, named) or not stat.S_ISDIR(parent.st_mode)
        ):
            raise PreviewError("preview preparation failed")
        sha256, size = _descriptor_digest(descriptor)
        if sha256 != record.get("sha256") or size != record.get("bytes"):
            raise PreviewError("preview preparation failed")
        return {
            "descriptor": descriptor,
            "absolute": absolute,
            "path": relative,
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


def _descriptor_digest(descriptor: int) -> tuple[str, int]:
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


def _pin_json(pin: dict[str, object]) -> object:
    descriptor = int(pin["descriptor"])
    os.lseek(descriptor, 0, os.SEEK_SET)
    source = bytearray()
    while len(source) <= 32 * 1024 * 1024:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        source.extend(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if len(source) > 32 * 1024 * 1024:
        raise PreviewError("preview preparation failed")
    try:
        return _strict_json(source.decode("utf-8", errors="strict"))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise PreviewError("preview preparation failed") from None


def _fd_path(pin: dict[str, object]) -> Path:
    return Path(f"/dev/fd/{pin['descriptor']}")


def _verify_artifact_pin(pin: dict[str, object]) -> None:
    status = os.fstat(int(pin["descriptor"]))
    try:
        named = os.lstat(Path(str(pin["absolute"])))
        parent = os.lstat(Path(str(pin["absolute"])).parent)
    except OSError:
        raise PreviewError("preview preparation failed") from None
    if (
        status.st_dev != pin["device"] or status.st_ino != pin["inode"]
        or not os.path.samestat(status, named)
        or parent.st_dev != pin["parent_device"] or parent.st_ino != pin["parent_inode"]
    ):
        raise PreviewError("preview preparation failed")
    if _descriptor_digest(int(pin["descriptor"])) != (pin["sha256"], pin["bytes"]):
        raise PreviewError("preview preparation failed")


def _pin_identity(pin: dict[str, object]) -> dict[str, object]:
    return {
        key: pin[key]
        for key in (
            "path", "sha256", "bytes", "device", "inode", "parent_device", "parent_inode",
        )
    }


def _identity_record(path: Path, logical_path: str) -> dict[str, object]:
    status = os.lstat(path)
    parent = os.lstat(path.parent)
    source = path.read_bytes()
    return {
        "path": logical_path,
        "sha256": hashlib.sha256(source).hexdigest(),
        "bytes": len(source),
        "device": status.st_dev,
        "inode": status.st_ino,
        "parent_device": parent.st_dev,
        "parent_inode": parent.st_ino,
    }


def _extract_evidence(
    review: Path, stage: Path, schedule: list[dict[str, object]],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in schedule:
        relative = str(item["path"])
        output = stage / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
                "-ss", format(float(item["timestamp"]), ".9f"), "-i", str(review),
                "-frames:v", "1", str(output),
            ],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
        records.append({
            "id": item["id"], "kind": item["kind"], "timestamp": item["timestamp"],
            **_identity_record(output, relative),
        })
    return records


def _contact_sheet(stage: Path, evidence: list[dict[str, object]], output: Path) -> None:
    images = []
    for item in evidence:
        with Image.open(stage / str(item["path"])) as image:
            images.append(ImageOps.fit(image.convert("RGB"), (240, 426)))
    columns = min(4, len(images))
    rows = math.ceil(len(images) / columns)
    sheet = Image.new("RGB", (columns * 240, rows * 426), (18, 18, 18))
    for index, image in enumerate(images):
        sheet.paste(image, ((index % columns) * 240, (index // columns) * 426))
    sheet.save(output, format="PNG")
    _fsync_file(output)


def _canonical(payload: object) -> bytes:
    try:
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise PreviewError("preview preparation failed") from None


def _write_bytes(path: Path, source: bytes) -> None:
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


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_preview_job(target: state.JobState, source: state.JobState) -> None:
    target.revision = source.revision
    target.expected_revision = source.expected_revision
    target.expected_sha256 = source.expected_sha256
    target.expected_bytes = source.expected_bytes
    target.stages.clear()
    target.stages.update(source.stages)

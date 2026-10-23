"""Event-bound TalkCraft SFX planning and clock-preserving audio mixing."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Mapping

from . import contract_artifacts, semantic_events


class EventAudioError(ValueError):
    """Raised when event-bound audio cannot be verified."""


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DEFAULT_ASSETS = {
    "impact-card-in": "talkcraft-impact-deep-whoosh.mp3",
    "impact-card-out": "talkcraft-impact-hit-fast-exciting.mp3",
}


def _fail(message: str) -> None:
    raise EventAudioError(message)


def _regular_file(path: Path) -> Path:
    path = path.absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        _fail("event audio source must be a regular local file")
    return path


def build_default_plan(
    event_plan: Mapping[str, object],
    *,
    runtime_root: Path,
    job_id: str,
    total_frames: int,
) -> dict[str, object]:
    """Build explicit audio cues from the audio channel of a semantic plan."""
    checked = semantic_events.validate_semantic_event_plan(event_plan)
    if type(job_id) is not str or not _ID.fullmatch(job_id):
        _fail("job_id is invalid")
    if type(total_frames) is not int or total_frames <= 0:
        _fail("total_frames is invalid")
    cues: list[dict[str, object]] = []
    root = _regular_file(runtime_root / "qualification-fixtures" / "talkcraft-impact-deep-whoosh.mp3").parent
    for event in checked["events"]:
        for cue_id in event["channels"]["audio"]:
            filename = _DEFAULT_ASSETS.get(cue_id)
            if filename is None:
                _fail(f"no registered audio asset for cue {cue_id}")
            source = _regular_file(root / filename)
            start = int(event["start_frame"])
            end = min(int(event["end_frame"]), start + 72)
            if end <= start or end > total_frames:
                _fail(f"audio cue {cue_id} has an invalid clock")
            cues.append({
                "cue_id": cue_id,
                "event_id": event["event_id"],
                "start_frame": start,
                "end_frame": end,
                "asset_key": filename.removesuffix(".mp3"),
                "path": str(source),
                "sha256": contract_artifacts.sha256_file(source),
                "volume": 0.28,
            })
    base = {
        "schema_version": "event-audio-plan/v1",
        "job_id": job_id,
        "fps": 24,
        "total_frames": total_frames,
        "semantic_event_plan_sha256": checked["plan_sha256"],
        "cues": cues,
    }
    return {**base, "plan_sha256": contract_artifacts.sha256_json(base)}


def validate_plan(
    plan: object,
    event_plan: Mapping[str, object],
    *,
    job_id: str | None = None,
    total_frames: int | None = None,
    allowed_roots: tuple[Path, ...] | None = None,
) -> dict[str, object]:
    if type(plan) is not dict or set(plan) != {
        "schema_version", "job_id", "fps", "total_frames",
        "semantic_event_plan_sha256", "cues", "plan_sha256",
    }:
        _fail("event audio plan fields are invalid")
    checked_events = semantic_events.validate_semantic_event_plan(event_plan)
    if plan["schema_version"] != "event-audio-plan/v1" or plan["fps"] != 24:
        _fail("event audio plan schema is invalid")
    if job_id is not None and plan["job_id"] != job_id:
        _fail("event audio plan job identity is invalid")
    if total_frames is not None and plan["total_frames"] != total_frames:
        _fail("event audio plan clock is invalid")
    if plan["semantic_event_plan_sha256"] != checked_events["plan_sha256"]:
        _fail("event audio plan is bound to a different semantic plan")
    if not allowed_roots:
        _fail("event audio plan requires trusted asset roots")
    trusted_roots = tuple(Path(root).absolute().resolve() for root in allowed_roots)
    if type(plan["cues"]) is not list:
        _fail("event audio cues must be a list")
    stripped = []
    seen = set()
    for cue in plan["cues"]:
        if type(cue) is not dict or set(cue) != {
            "cue_id", "event_id", "start_frame", "end_frame",
            "asset_key", "path", "sha256", "volume",
        }:
            _fail("event audio cue fields are invalid")
        if cue["cue_id"] in seen or not _ID.fullmatch(str(cue["cue_id"])):
            _fail("event audio cue ids are invalid")
        seen.add(cue["cue_id"])
        if not _HASH.fullmatch(str(cue["sha256"])) or not isinstance(cue["path"], str):
            _fail("event audio source identity is invalid")
        if type(cue["volume"]) not in {int, float} or not 0 < cue["volume"] <= 1:
            _fail("event audio volume is invalid")
        source = _regular_file(Path(cue["path"]))
        resolved_source = source.resolve()
        if not any(
            resolved_source == root or root in resolved_source.parents
            for root in trusted_roots
        ):
            _fail("event audio source is outside trusted asset roots")
        if contract_artifacts.sha256_file(source) != cue["sha256"]:
            _fail("event audio source changed")
        stripped.append({key: cue[key] for key in ("cue_id", "event_id", "start_frame", "end_frame")})
    semantic_events.validate_audio_event_alignment({"cues": stripped}, checked_events)
    base = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if plan["plan_sha256"] != contract_artifacts.sha256_json(base):
        _fail("event audio plan hash is invalid")
    return plan


def prepare_stage_audio(
    plan: Mapping[str, object],
    voice: Path,
    output: Path,
) -> Path:
    """Mix voice and event cues without changing the approved frame clock."""
    checked_voice = _regular_file(voice)
    cues = plan["cues"]
    frames = int(plan["total_frames"])
    duration = frames / 24
    inputs = [str(checked_voice)] + [str(cue["path"]) for cue in cues]
    filters = [
        f"[0:a]aresample=48000,apad,atrim=duration={duration:.9f}[voice]"
    ]
    mix_labels = ["[voice]"]
    for index, cue in enumerate(cues, start=1):
        delay = int(cue["start_frame"] * 1000 / 24)
        label = f"[sfx{index}]"
        filters.append(
            f"[{index}:a]aresample=48000,volume={float(cue['volume']):.6f},"
            f"adelay={delay}:all=1,atrim=duration={duration:.9f}{label}"
        )
        mix_labels.append(label)
    filters.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0,"
        "aresample=48000,asetpts=PTS-STARTPTS[out]"
    )
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
    ]
    for source in inputs:
        command += ["-i", source]
    command += [
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.9f}", str(output),
    ]
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True, capture_output=True, timeout=max(300, int(duration * 2)))
    except (OSError, subprocess.SubprocessError) as exc:
        raise EventAudioError("event audio mix failed") from exc
    if not output.is_file() or output.stat().st_size <= 0:
        _fail("event audio mix was not created")
    return output

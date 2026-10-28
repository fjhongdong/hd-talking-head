"""Deterministic subtitles bound to the approved full-v2 content map."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import (
    content_analysis,
    contract_artifacts,
    edit_timeline,
    material_usage,
    semantic_events,
    state,
    subtitles,
    talkcraft_subtitles,
    terminology_review,
    visual_canary,
)


class SubtitlesV2Error(RuntimeError):
    """Raised when subtitle copy drifts from approved content semantics."""


_CORE_OUTPUT_NAMES = (
    "subtitle-plan.json",
    "subtitles.webm",
    "subtitles.srt",
)
_OUTPUT_NAMES = (*_CORE_OUTPUT_NAMES, "material-usage.json")
_TRANSACTION_NAME = ".10-subtitles.transaction.json"
_LOCK_NAME = ".10-subtitles.lock"
_EMPHASIS_GAP_SECONDS = 2.0
_SAME_KEYWORD_COOLDOWN_SECONDS = 15.0


def _chinese_word_phrases(text: str) -> list[str]:
    """Keep ICU-identified Chinese words intact when balancing cue lengths."""
    script = (
        "const fs=require('fs');"
        "const text=fs.readFileSync(0,'utf8');"
        "const words=[...new Intl.Segmenter('zh',{granularity:'word'}).segment(text)]"
        ".filter(part=>part.isWordLike && [...part.segment].length>1)"
        ".map(part=>part.segment);"
        "process.stdout.write(JSON.stringify(words));"
    )
    try:
        result = subprocess.run(
            ["node", "-e", script], input=text, text=True,
            capture_output=True, check=True,
        )
        phrases = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SubtitlesV2Error("Chinese subtitle word segmentation failed") from exc
    if not isinstance(phrases, list) or not all(isinstance(item, str) for item in phrases):
        raise SubtitlesV2Error("Chinese subtitle word segmentation is invalid")
    return phrases


def _shot_mode(segment: Mapping[str, Any]) -> str:
    recipe = segment.get("shot_recipe")
    mode = recipe.get("mode") if isinstance(recipe, Mapping) else None
    if mode not in {"none", "single", "hybrid"}:
        raise SubtitlesV2Error("subtitle segment ShotRecipe is invalid")
    return str(mode)


def approved_keyword_index(job: state.JobState) -> dict[str, tuple[str, ...]]:
    record = content_analysis.load_approved_content_analysis(job)
    return {
        str(item["id"]): tuple(str(value) for value in item["keywords"])
        for item in record["analysis"]["items"]
        if item["evidence_status"] != "unsupported"
    }


def validate_emphasis(
    render_plan: Mapping[str, Any],
    keyword_index: Mapping[str, tuple[str, ...]],
    segments: list[Mapping[str, Any]],
    *,
    emphasis_times: Mapping[str, float],
) -> None:
    by_id = {str(segment["segment_id"]): segment for segment in segments}
    last_keyword_time: dict[str, float] = {}
    last_emphasis_time = float("-inf")
    for cue in render_plan["cues"]:
        segment = by_id.get(str(cue["segment_id"]))
        if segment is None:
            raise SubtitlesV2Error("subtitle cue has no approved visual segment")
        allowed = {
            keyword
            for item_id in segment["content_item_ids"]
            for keyword in keyword_index.get(str(item_id), ())
        }
        emphasis = cue["emphasis_words"]
        if len(emphasis) > 1 or any(
            word not in allowed or word not in cue["text"] for word in emphasis
        ):
            raise SubtitlesV2Error(
                "subtitle emphasis is not an approved exact keyword"
            )
        if emphasis:
            try:
                word_start = float(emphasis_times[cue["id"]])
            except (KeyError, TypeError, ValueError) as exc:
                raise SubtitlesV2Error("subtitle emphasis has no real word time") from exc
            if not math.isfinite(word_start) or not float(cue["start"]) <= word_start < float(cue["end"]):
                raise SubtitlesV2Error("subtitle emphasis word is outside its cue")
            if (word_start - last_keyword_time.get(emphasis[0], float("-inf"))
                    < _SAME_KEYWORD_COOLDOWN_SECONDS
                    or word_start - last_emphasis_time < _EMPHASIS_GAP_SECONDS):
                raise SubtitlesV2Error("subtitle emphasis repeats or is too closely spaced")
            last_keyword_time[emphasis[0]] = word_start
            last_emphasis_time = word_start
    if set(emphasis_times) != {cue["id"] for cue in render_plan["cues"] if cue["emphasis_words"]}:
        raise SubtitlesV2Error("subtitle emphasis word times differ from selected keywords")


def _record(path: Path, job_dir: Path) -> dict[str, object]:
    try:
        relative = path.relative_to(job_dir).as_posix()
    except ValueError as exc:
        raise SubtitlesV2Error("subtitle source is outside the job") from exc
    return {
        "path": relative,
        "sha256": contract_artifacts.sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _approved_artifact(
    job: state.JobState, stage_id: str, relative: str
) -> tuple[Path, dict[str, object]]:
    stage = job.stages[stage_id]
    if stage["status"] != "approved":
        raise SubtitlesV2Error(f"{stage_id} must be approved")
    matches = [record for record in stage["artifacts"] if record.get("path") == relative]
    if len(matches) != 1:
        raise SubtitlesV2Error(f"approved {relative} is unavailable")
    path = job.job_dir / relative
    record = _record(path, job.job_dir)
    if record != matches[0]:
        raise SubtitlesV2Error(f"approved {relative} changed")
    return path, record


def review_subtitles(job):
    """Read the existing review artifact, without rendering or approving it."""
    job = state.load_job(job.job_dir)
    stage_identity = contract_artifacts.sha256_json(job.stages)
    if job.version != 2 or job.stages["subtitles"]["status"] not in {"ready_for_review", "approved"}:
        raise SubtitlesV2Error("subtitles are not ready for review")
    relative = "10-subtitles/subtitle-plan.json"
    path = job.job_dir / relative
    binding = _record(path, job.job_dir)
    if job.stages["subtitles"]["artifacts"].count(binding) != 1:
        raise SubtitlesV2Error("subtitle review artifact changed")
    payload = contract_artifacts.read_json_artifact(path)
    if not isinstance(payload, Mapping):
        raise SubtitlesV2Error("subtitle review must be an object")
    base = {key: value for key, value in payload.items() if key != "subtitle_plan_sha256"}
    if payload.get("job_id") != job.job_id or payload.get("subtitle_plan_sha256") != contract_artifacts.sha256_json(base):
        raise SubtitlesV2Error("subtitle review identity changed")
    _validate_terminology_binding(job, payload)
    if _record(path, job.job_dir) != binding:
        raise SubtitlesV2Error("subtitle review artifact changed during read")
    report = payload.get("terminology_review")
    current = state.load_job(job.job_dir)
    if current.revision != job.revision or contract_artifacts.sha256_json(current.stages) != stage_identity:
        raise SubtitlesV2Error("subtitle review workflow changed during read")
    return {"stage": "subtitles", "job_id": job.job_id, "revision": job.revision,
            "artifact": binding, "terminology_status": "available" if report is not None else "legacy_report_unavailable",
            "terminology_review": report,
            "review_instruction": "结合原声核听疑点；需要修改源转写时沿用 speech_cleanup 修订链，不自动替换。"}


def _build_terminology_review(job, words, keyword_index):
    path, binding = _approved_artifact(job, "speech_cleanup", "05-speech-cleanup/diff-summary.json")
    summary = contract_artifacts.read_json_artifact(path)
    if _record(path, job.job_dir) != binding:
        raise SubtitlesV2Error("terminology history changed during read")
    history_summary = {
        key: value for key, value in summary.items() if key != "terminology_review"
    }
    report = terminology_review.build_report_with_history(
        words,
        approved_terms=[term for values in keyword_index.values() for term in values],
        summary=history_summary,
    )
    return {**report, "history_binding": binding}


def _validate_terminology_binding(job, payload):
    report = payload.get("terminology_review")
    if report is None and payload.get("schema_version", 2) == 2:
        return
    if not isinstance(report, Mapping) or "history_binding" not in report:
        raise SubtitlesV2Error("terminology history binding missing")
    _, binding = _approved_artifact(job, "speech_cleanup", "05-speech-cleanup/diff-summary.json")
    if report["history_binding"] != binding:
        raise SubtitlesV2Error("terminology history binding changed")


def _corrected_phrases(job) -> tuple[str, ...]:
    path, binding = _approved_artifact(job, "speech_cleanup", "05-speech-cleanup/diff-summary.json")
    summary = contract_artifacts.read_json_artifact(path)
    if _record(path, job.job_dir) != binding:
        raise SubtitlesV2Error("correction history changed during read")
    phrases = ("".join(change["after"])
               for run in edit_timeline._correction_audit_runs(
                   {key: value for key, value in summary.items() if key != "terminology_review"})
               for change in run["changes"])
    return tuple(dict.fromkeys(phrase for phrase in phrases
                 if 1 < subtitles._visible_glyph_count([{"text": phrase}]) <= subtitles._CUE_TARGET_MAX))


def subtitle_layout(shot_mode: str, composition: Mapping[str, Any]) -> tuple[dict, str]:
    """Return the same parent subtitle reservation for planning and rendering."""
    if shot_mode == "none" or composition.get("presenter_mode") == "hidden":
        zones = {
            "face": None,
            "subtitle": {"x": 80, "y": 1430, "width": 920, "height": 230},
            "source": None,
            "chart": None,
        }
        placement = "standard"
    else:
        avatar = composition["avatar"]
        position = avatar["position"]
        diameter = avatar["profile"]["diameter"]
        outer = diameter + 2 * avatar["profile"]["border_width"]
        face = {"x": position["x"], "y": position["y"],
                "width": outer, "height": outer}
        legacy = {"x": 80, "y": 1462, "width": 640, "height": 230}
        overlaps = not (legacy["x"] + legacy["width"] <= face["x"]
                        or face["x"] + face["width"] <= legacy["x"]
                        or legacy["y"] + legacy["height"] <= face["y"]
                        or face["y"] + face["height"] <= legacy["y"])
        # A 14-glyph cue needs two seven-glyph lines at 48px plus 2px
        # tracking and the actual card's 84px padding / 2px border.
        left_width = min(640, face["x"] - 80 - 8)
        left_fits = left_width >= 7 * (48 + 2) + 84 + 2
        zones = {
            "face": face,
            "subtitle": ({"x": 80, "y": 1430, "width": left_width, "height": 270}
                         if overlaps and left_fits else
                         {"x": 80, "y": face["y"] + face["height"] + 8 - 32,
                           "width": 640,
                           "height": 1784 - (face["y"] + face["height"] + 8) + 40}
                         if overlaps else {"x": 80, "y": 1430, "width": 640, "height": 270}),
            "source": None,
            "chart": None,
        }
        placement = "above_avatar"
    return zones, placement


def build_render_plan(
    *,
    records: dict[str, dict[str, object]],
    words: list[dict[str, object]],
    timeline: dict[str, object],
    visual_plan: Mapping[str, Any],
    keyword_index: Mapping[str, tuple[str, ...]],
    event_ids_by_segment: Mapping[str, str] | None = None,
    renderer_cues: list[dict[str, Any]] | None = None,
    protected_phrases: tuple[str, ...] = (),
) -> dict[str, object]:
    mapped = subtitles._map_words(words, timeline)
    duration = float(visual_plan["duration"])
    cues: list[dict[str, object]] = []
    used_words: set[int] = set()
    last_keyword_time: dict[str, float] = {}
    last_emphasis_time = float("-inf")
    font_path = subtitles.bold_subtitles.find_cjk_font(
        "".join(str(word["text"]) for word in mapped)
    )
    emphasis_times: dict[str, float] = {}
    for segment in visual_plan["segments"]:
        zones, placement = subtitle_layout(_shot_mode(segment), segment["shot_recipe"].get("composition", {}))
        segment_start = float(segment["start"])
        segment_end = float(segment["end"])
        indices = [
            index
            for index, word in enumerate(mapped)
            if index not in used_words
            and segment_start
            <= (float(word["start"]) + float(word["end"])) / 2
            < segment_end
        ]
        if not indices:
            continue
        used_words.update(indices)
        selected = [mapped[index] for index in indices]
        keywords = [
            keyword
            for item_id in segment["content_item_ids"]
            for keyword in keyword_index.get(str(item_id), ())
        ]
        keywords = list(dict.fromkeys(keywords))
        cue_type = "emphasis"
        box = subtitles._layout_box({"safe_zones": zones}, cue_type)
        if placement == "above_avatar":
            # Match the TalkCraft card's 32px footer-clearance shift without
            # widening its bounds or changing the reserved subtitle safe zone.
            box = {**box, "y": int(box["y"]) + 32}
        bottom = 350 if placement == "standard" else 1920 - (box["y"] + box["height"])
        if placement == "above_avatar" and box["height"] < 168:
            raise SubtitlesV2Error("subtitle safe area cannot fit two lines below avatar")
        layout_cache: dict[tuple[object, ...], bool] = {}
        chunks = subtitles._split_words_for_box(
            selected, box, font_path, cue_type, layout_cache
        )
        selected_text = "".join(str(word["text"]) for word in selected)
        if any(
            keyword
            and keyword in selected_text
            and subtitles._visible_glyph_count([{"text": keyword}])
            > subtitles._CUE_TARGET_MAX
            for keyword in keywords
        ):
            raise SubtitlesV2Error("approved subtitle keyword is too long")
        chunks = subtitles._partition_subtitle_words(
            selected,
            chunks,
            box=box,
            font_path=font_path,
            cue_type=cue_type,
            segment_start=segment_start,
            segment_end=segment_end,
            duration=duration,
            protected_boundaries=subtitles._protected_word_boundaries(
                selected, [*keywords, *protected_phrases, *_chinese_word_phrases(selected_text)]
            ),
            layout_cache=layout_cache,
        )
        for chunk in chunks:
            text = "".join(str(word["text"]) for word in chunk).lstrip(
                "，,、。；;：:！？!?"
            )
            if not text:
                continue
            cue_start, cue_end = subtitles._chunk_times(
                chunk,
                segment_start=segment_start,
                segment_end=segment_end,
                duration=duration,
            )
            cue = {
                "id": f"cue-{len(cues) + 1:03d}",
                "type": cue_type,
                "segment_id": segment["segment_id"],
                "start": cue_start,
                "end": cue_end,
                "text": text,
                "emphasis_words": [],
                "safe_zones": zones,
                "box": box,
            }
            render_cue = {**cue, "bottom": bottom}
            candidates = []
            for keyword in keywords:
                if keyword not in text:
                    continue
                rendered = talkcraft_subtitles.cue_input(
                    {**render_cue, "emphasis_words": [keyword]}, chunk, placement=placement)
                word_start = float(rendered["emphasis"]["start"])
                if (word_start - last_keyword_time.get(keyword, float("-inf"))
                        >= _SAME_KEYWORD_COOLDOWN_SECONDS
                        and word_start - last_emphasis_time >= _EMPHASIS_GAP_SECONDS):
                    candidates.append((keyword, rendered))
            if candidates:
                keyword, rendered = max(candidates, key=lambda candidate: len(candidate[0]))
                cue["emphasis_words"] = [keyword]
                word_start = float(rendered["emphasis"]["start"])
                emphasis_times[cue["id"]] = word_start
                last_keyword_time[keyword] = word_start
                last_emphasis_time = word_start
            else:
                rendered = talkcraft_subtitles.cue_input(render_cue, chunk, placement=placement)
            rendered["bottom"] = bottom
            if event_ids_by_segment is not None:
                event_id = event_ids_by_segment.get(str(segment["segment_id"]))
                if event_id is not None:
                    cue["event_id"] = event_id
            cues.append(cue)
            if renderer_cues is not None:
                renderer_cues.append(rendered)
    if used_words != set(range(len(mapped))):
        raise SubtitlesV2Error("subtitle timeline does not cover every word")
    plan = {
        "version": 1,
        "canvas": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "frames": round(duration * 24),
            "duration": duration,
        },
        "source_bindings": records,
        "layout_counts": {
            "emphasis": len(cues),
            "statement": 0,
            "source": 0,
            "action": 0,
        },
        "cues": cues,
    }
    plan = subtitles.validate_subtitle_plan(plan)
    validate_emphasis(plan, keyword_index, list(visual_plan["segments"]), emphasis_times=emphasis_times)
    return plan


def _load_inputs(job: state.JobState) -> tuple[
    dict[str, object], dict[str, object], dict[str, Any], dict[str, dict[str, object]]
]:
    plan = visual_canary.load_approved_visual_plan(job)
    transcript_path, transcript_record = _approved_artifact(
        job, "speech_cleanup", "05-speech-cleanup/word-transcript.json"
    )
    timeline_path, timeline_record = _approved_artifact(
        job, "edit_structure", "06-edit-structure/timeline-map.json"
    )
    edited_path, edited_record = _approved_artifact(
        job, "edit_structure", "06-edit-structure/edited-aroll.mp4"
    )
    visual_path, visual_record = _approved_artifact(
        job, "visual_direction", "07-visual-direction/visual-plan.json"
    )
    manifest_path, manifest_record = _approved_artifact(
        job, "visual_assets", "09-visual-assets/asset-manifest.json"
    )
    track_path, track_record = _approved_artifact(
        job, "visual_assets", "09-visual-assets/visual-track.mp4"
    )
    transcript = subtitles._strict_json(transcript_path.read_bytes())
    timeline = subtitles._strict_json(timeline_path.read_bytes())
    manifest = contract_artifacts.read_json_artifact(manifest_path)
    if (
        manifest.get("visual_plan_sha256") != plan["visual_plan_sha256"]
        or manifest.get("visual_track", {}).get("sha256") != track_record["sha256"]
    ):
        raise SubtitlesV2Error("visual-assets binding changed")
    return transcript, timeline, plan, {
        "word_transcript": transcript_record,
        "timeline_map": timeline_record,
        "edited_aroll": edited_record,
        "visual_plan": visual_record,
        "asset_manifest": manifest_record,
        "visual_track": track_record,
    }


def _load_event_ids(job: state.JobState) -> dict[str, str] | None:
    stage = job.stages.get("visual_direction")
    artifacts = stage.get("artifacts", []) if isinstance(stage, Mapping) else []
    declared = any(
        isinstance(record, Mapping)
        and record.get("path") == "07-visual-direction/semantic-events.json"
        for record in artifacts
    )
    if not declared:
        # Legacy/unit fixtures without a published event plan remain supported.
        return None
    path, _record = _approved_artifact(
        job, "visual_direction", "07-visual-direction/semantic-events.json"
    )
    payload = contract_artifacts.read_json_artifact(path)
    checked = semantic_events.validate_semantic_event_plan(payload)
    event_ids: dict[str, str] = {}
    for event in checked["events"]:
        segment_id = str(event["segment_id"])
        event_id = str(event["event_id"])
        previous = event_ids.get(segment_id)
        if previous is not None and previous != event_id:
            raise SubtitlesV2Error(
                "semantic event plan has multiple event ids for a segment"
            )
        event_ids[segment_id] = event_id
    return event_ids


def _wrapper(
    job: state.JobState,
    analysis_sha256: str,
    visual_plan_sha256: str,
    render_plan: Mapping[str, Any],
    *,
    terminology_report: Mapping[str, Any] | None = None,
    renderer_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": 3 if terminology_report is not None else 2,
        "job_id": job.job_id,
        "content_analysis_sha256": analysis_sha256,
        "visual_plan_sha256": visual_plan_sha256,
        "render_plan": dict(render_plan),
    }
    if terminology_report is not None:
        base["terminology_review"] = dict(terminology_report)
    if renderer_input is not None:
        base["schema_version"] = 4
        base["renderer_input"] = dict(renderer_input)
        base["renderer"] = talkcraft_subtitles.identity(renderer_input, render_plan)
    return {**base, "subtitle_plan_sha256": contract_artifacts.sha256_json(base)}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _acquire_job_lock(job_dir: Path) -> int:
    descriptor = os.open(
        job_dir / _LOCK_NAME,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SubtitlesV2Error("subtitle lock file is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _fsync_directory(job_dir)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_job_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("subtitle file write stopped")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _snapshot(directory: Path, *, identity: bool = False) -> list[dict[str, object]]:
    if not directory.is_dir():
        raise SubtitlesV2Error("subtitle generation is incomplete")
    actual_names = {path.name for path in directory.iterdir()}
    if actual_names == set(_OUTPUT_NAMES):
        output_names = _OUTPUT_NAMES
    elif actual_names == set(_CORE_OUTPUT_NAMES):
        output_names = _CORE_OUTPUT_NAMES
    else:
        raise SubtitlesV2Error("subtitle generation is incomplete")
    parent = os.lstat(directory)
    records: list[dict[str, object]] = []
    for name in output_names:
        path = directory / name
        status = os.lstat(path)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SubtitlesV2Error("subtitle generation contains an invalid file")
        record = {
            "path": f"10-subtitles/{name}",
            "sha256": contract_artifacts.sha256_file(path),
            "bytes": status.st_size,
        }
        if identity:
            record.update(
                device=status.st_dev,
                inode=status.st_ino,
                parent_device=parent.st_dev,
                parent_inode=parent.st_ino,
            )
        records.append(record)
    return records


def _records_match(
    directory: Path,
    records: object,
    *,
    identity: bool = False,
) -> bool:
    try:
        if type(records) is not list or len(records) != len(_OUTPUT_NAMES):
            return False
        actual = _snapshot(directory, identity=identity)
        return actual == records
    except (OSError, SubtitlesV2Error, KeyError, TypeError):
        return False


def _content_records(records: object) -> list[dict[str, object]] | None:
    if type(records) is not list:
        return None
    try:
        return [{key: record[key] for key in ("path", "sha256", "bytes")} for record in records]
    except (KeyError, TypeError):
        return None


def _artifact_records_match(
    job: state.JobState, records: list[dict[str, object]]
) -> bool:
    return job.stages["subtitles"].get("artifacts") == records


def _remove_known(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    _fsync_directory(path.parent)


def _checkpoint(_name: str) -> None:
    """Test hook for publication interruption and re-entry."""


def _write_transaction(job: state.JobState, payload: Mapping[str, Any]) -> None:
    marker = job.job_dir / _TRANSACTION_NAME
    if os.path.lexists(marker):
        raise SubtitlesV2Error("subtitle publication is already in progress")
    try:
        _write_new(marker, contract_artifacts.canonical_json_bytes(dict(payload)))
        _fsync_directory(job.job_dir)
    except FileExistsError as exc:
        raise SubtitlesV2Error(
            "subtitle publication is already in progress"
        ) from exc


def _load_transaction(job: state.JobState) -> dict[str, Any] | None:
    marker = job.job_dir / _TRANSACTION_NAME
    if not os.path.lexists(marker):
        return None
    try:
        payload = contract_artifacts.read_json_artifact(marker)
    except BaseException as exc:
        raise SubtitlesV2Error("subtitle publication journal is invalid") from exc
    keys = {
        "schema_version",
        "job_id",
        "base_revision",
        "workflow_sha256",
        "workflow_bytes",
        "had_target",
        "stage",
        "backup",
        "target",
        "new_records",
        "old_records",
    }
    if (
        type(payload) is not dict
        or set(payload) != keys
        or payload["schema_version"] != 1
        or payload["job_id"] != job.job_id
        or type(payload["base_revision"]) is not int
        or type(payload["workflow_sha256"]) is not str
        or type(payload["workflow_bytes"]) is not int
        or type(payload["had_target"]) is not bool
        or payload["target"] != "10-subtitles"
        or type(payload["stage"]) is not str
        or not payload["stage"].startswith(".10-subtitles.stage-")
        or type(payload["backup"]) is not str
        or not payload["backup"].startswith(".10-subtitles.backup-")
        or any(
            "/" in str(payload[key]) or "\\" in str(payload[key])
            for key in ("stage", "backup")
        )
        or type(payload["new_records"]) is not list
        or type(payload["old_records"]) is not list
        or bool(payload["old_records"]) != payload["had_target"]
    ):
        raise SubtitlesV2Error("subtitle publication journal is invalid")
    return payload


def _journal_stage(job_dir: Path) -> str | None:
    marker = job_dir / _TRANSACTION_NAME
    if not os.path.lexists(marker):
        return None
    try:
        payload = contract_artifacts.read_json_artifact(marker)
    except BaseException:
        return None
    if isinstance(payload, Mapping) and type(payload.get("stage")) is str:
        return str(payload["stage"])
    return None


def _srt_clock(cues: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    return [
        (round(float(cue["start"]) * 1000) / 1000,
         round(float(cue["end"]) * 1000) / 1000, str(cue["text"]))
        for cue in cues
    ]


def _validate_generation(
    directory: Path,
    expected_records: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    records = _snapshot(directory)
    if expected_records is not None and records != expected_records:
        raise SubtitlesV2Error("published subtitle files changed")
    try:
        payload = contract_artifacts.read_json_artifact(
            directory / "subtitle-plan.json"
        )
        base = {
            key: value for key, value in payload.items() if key != "subtitle_plan_sha256"
        }
        if payload.get("subtitle_plan_sha256") != contract_artifacts.sha256_json(base):
            raise SubtitlesV2Error("subtitle plan identity changed")
        render_plan = subtitles.validate_subtitle_plan(payload["render_plan"])
        talkcraft_subtitles.validate_binding(payload)
        descriptor = os.open(directory / "subtitles.webm", os.O_RDONLY)
        try:
            frames = int(render_plan["canvas"]["frames"])
            if render_plan["cues"]:
                subtitles.bold_subtitles.validate_webm_fd(descriptor, frames)
            else:
                subtitles._validate_transparent_webm_fd(descriptor, frames)
            talkcraft_subtitles.verify_geometry(descriptor, render_plan, payload["renderer_input"])
        finally:
            os.close(descriptor)
        parsed_srt = subtitles.parse_srt(
            (directory / "subtitles.srt").read_text(encoding="utf-8")
        )
        if parsed_srt != _srt_clock(render_plan["cues"]):
            raise SubtitlesV2Error("subtitle sidecar does not match the plan")
        return payload
    except SubtitlesV2Error:
        raise
    except BaseException as exc:
        raise SubtitlesV2Error("published subtitles could not be validated") from exc


def _validate_published(job: state.JobState) -> Path:
    target = job.job_dir / "10-subtitles"
    records = _snapshot(target)
    if not _artifact_records_match(job, records):
        raise SubtitlesV2Error("subtitle workflow records changed")
    analysis = content_analysis.load_approved_content_analysis(job)
    transcript, timeline, visual_plan, upstream_records = _load_inputs(job)
    payload = _validate_generation(target, records)
    _validate_terminology_binding(job, payload)
    render_plan = payload.get("render_plan")
    if (
        payload.get("job_id") != job.job_id
        or payload.get("content_analysis_sha256") != analysis["analysis_sha256"]
        or payload.get("visual_plan_sha256") != visual_plan["visual_plan_sha256"]
        or not isinstance(render_plan, Mapping)
        or render_plan.get("source_bindings") != upstream_records
    ):
        raise SubtitlesV2Error("published subtitle bindings changed")
    renderer_cues: list[dict[str, Any]] = []
    rebuilt = build_render_plan(
        records=upstream_records,
        words=subtitles._validate_words(transcript),
        timeline=subtitles._validate_timeline(timeline),
        visual_plan=visual_plan,
        keyword_index=approved_keyword_index(job),
        protected_phrases=_corrected_phrases(job),
        event_ids_by_segment=_load_event_ids(job),
        renderer_cues=renderer_cues,
    )
    if (rebuilt != render_plan or payload["renderer_input"] !=
            talkcraft_subtitles.renderer_input(rebuilt, renderer_cues)):
        raise SubtitlesV2Error("published subtitle word timing changed")
    return target / "subtitles.webm"


def _synchronize_job(target: state.JobState, source: state.JobState) -> None:
    subtitles._synchronize_job(target, source)


def _cleanup_transaction(job: state.JobState, payload: Mapping[str, Any]) -> None:
    stage = job.job_dir / str(payload["stage"])
    backup = job.job_dir / str(payload["backup"])
    if os.path.lexists(stage):
        if not _records_match(stage, payload["new_records"]):
            raise SubtitlesV2Error("subtitle staging files changed")
        _remove_known(stage)
    if os.path.lexists(backup):
        if not _records_match(backup, payload["old_records"], identity=True):
            raise SubtitlesV2Error("previous subtitle generation changed")
        _remove_known(backup)
    _remove_known(job.job_dir / _TRANSACTION_NAME)


def _restore_transaction(job: state.JobState, payload: Mapping[str, Any]) -> None:
    target = job.job_dir / "10-subtitles"
    stage = job.job_dir / str(payload["stage"])
    backup = job.job_dir / str(payload["backup"])
    target_is_old = bool(payload["had_target"]) and _records_match(
        target, payload["old_records"], identity=True
    )
    target_is_new = (
        _records_match(target, payload["new_records"]) and not target_is_old
    )
    backup_is_old = bool(payload["had_target"]) and _records_match(
        backup, payload["old_records"], identity=True
    )
    if payload["had_target"]:
        if target_is_new:
            _remove_known(target)
        elif not target_is_old and os.path.lexists(target):
            raise SubtitlesV2Error("subtitle target changed during restoration")
        if not target_is_old:
            if not backup_is_old or os.path.lexists(target):
                raise SubtitlesV2Error("previous subtitle generation is unavailable")
            os.replace(backup, target)
            _fsync_directory(job.job_dir)
    else:
        if target_is_new:
            _remove_known(target)
        elif os.path.lexists(target):
            raise SubtitlesV2Error("subtitle target changed during restoration")
    if os.path.lexists(stage):
        if not _records_match(stage, payload["new_records"]):
            raise SubtitlesV2Error("subtitle staging files changed")
        _remove_known(stage)
    if os.path.lexists(backup):
        raise SubtitlesV2Error("subtitle backup was not restored")
    _remove_known(job.job_dir / _TRANSACTION_NAME)


def _finish_transaction(
    job: state.JobState, payload: dict[str, Any]
) -> Path | None:
    current = state.load_job(job.job_dir)
    _synchronize_job(job, current)
    target = job.job_dir / "10-subtitles"
    stage = job.job_dir / str(payload["stage"])
    backup = job.job_dir / str(payload["backup"])
    status = job.stages["subtitles"]["status"]
    if status in {"ready_for_review", "approved"}:
        output = _validate_published(job)
        _cleanup_transaction(job, payload)
        return output
    if status not in {"pending", "needs_revision"}:
        raise SubtitlesV2Error("subtitle stage is not runnable")
    base_matches = (
        job.revision == payload["base_revision"]
        and job.expected_sha256 == payload["workflow_sha256"]
        and job.expected_bytes == payload["workflow_bytes"]
    )
    if not base_matches:
        _restore_transaction(job, payload)
        return None
    try:
        target_is_old = bool(payload["had_target"]) and _records_match(
            target, payload["old_records"], identity=True
        )
        target_is_new = (
            _records_match(target, payload["new_records"]) and not target_is_old
        )
        stage_is_new = _records_match(stage, payload["new_records"])
        backup_is_old = bool(payload["had_target"]) and _records_match(
            backup, payload["old_records"], identity=True
        )
        _checkpoint("before-install")
        if payload["had_target"] and target_is_old:
            if os.path.lexists(backup):
                raise SubtitlesV2Error("subtitle backup path is occupied")
            os.replace(target, backup)
            _fsync_directory(job.job_dir)
            target_is_old = False
            backup_is_old = True
            _checkpoint("after-backup")
        if not target_is_new:
            if os.path.lexists(target) or not stage_is_new:
                raise SubtitlesV2Error("subtitle generation cannot be installed")
            if payload["had_target"] and not backup_is_old:
                raise SubtitlesV2Error("previous subtitle generation is unavailable")
            os.replace(stage, target)
            _fsync_directory(job.job_dir)
        if not _records_match(target, payload["new_records"]):
            raise SubtitlesV2Error("installed subtitle generation changed")
        _validate_generation(target, payload["new_records"])
        _checkpoint("after-install")
        analysis = content_analysis.load_approved_content_analysis(job)
        _transcript, _timeline, visual_plan, upstream_records = _load_inputs(job)
        wrapper = contract_artifacts.read_json_artifact(
            target / "subtitle-plan.json"
        )
        _validate_terminology_binding(job, wrapper)
        if (
            wrapper.get("content_analysis_sha256") != analysis["analysis_sha256"]
            or wrapper.get("visual_plan_sha256")
            != visual_plan["visual_plan_sha256"]
            or wrapper.get("render_plan", {}).get("source_bindings")
            != upstream_records
        ):
            raise SubtitlesV2Error("subtitle inputs changed before publication")
        state.mark_ready(
            job,
            "subtitles",
            tuple(job.job_dir / str(record["path"]) for record in payload["new_records"]),
        )
        if not _artifact_records_match(job, payload["new_records"]):
            raise SubtitlesV2Error("subtitle workflow records did not update")
        _checkpoint("after-workflow")
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        try:
            persisted = state.load_job(job.job_dir)
            if persisted.stages["subtitles"]["status"] in {
                "ready_for_review",
                "approved",
            }:
                _synchronize_job(job, persisted)
                _validate_published(job)
                _cleanup_transaction(job, payload)
                return target / "subtitles.webm"
        except BaseException:
            pass
        _restore_transaction(job, payload)
        raise
    _cleanup_transaction(job, payload)
    return target / "subtitles.webm"


def _prepare_subtitles_v2_locked(job: state.JobState) -> Path:
    if job.version != 2:
        raise SubtitlesV2Error("formal subtitle builder requires full-v2")
    target = job.job_dir / "10-subtitles"
    pending = _load_transaction(job)
    if pending is not None:
        recovered = _finish_transaction(job, pending)
        if recovered is not None:
            return recovered
    if job.stages["subtitles"]["status"] in {"ready_for_review", "approved"}:
        try:
            return _validate_published(job)
        except SubtitlesV2Error:
            raise
        except BaseException as exc:
            raise SubtitlesV2Error(
                "published subtitles could not be validated"
            ) from exc
    state.require_runnable(job, "subtitles")
    analysis = content_analysis.load_approved_content_analysis(job)
    keyword_index = approved_keyword_index(job)
    transcript, timeline, visual_plan, records = _load_inputs(job)
    event_ids_by_segment = _load_event_ids(job)
    segments = visual_plan.get("segments") if isinstance(visual_plan, Mapping) else None
    segment_ids = {
        str(segment["segment_id"])
        for segment in segments
        if isinstance(segment, Mapping) and "segment_id" in segment
    } if isinstance(segments, list) else set()
    if event_ids_by_segment is not None:
        if not segment_ids or not segment_ids.issubset(event_ids_by_segment):
            raise SubtitlesV2Error(
                "formal semantic event plan does not cover every subtitle segment"
            )
    words = subtitles._validate_words(transcript)
    mapped_timeline = subtitles._validate_timeline(timeline)
    renderer_cues: list[dict[str, Any]] = []
    render_plan = build_render_plan(
        records=records,
        words=words,
        timeline=mapped_timeline,
        visual_plan=visual_plan,
        keyword_index=keyword_index,
        protected_phrases=_corrected_phrases(job),
        event_ids_by_segment=event_ids_by_segment,
        renderer_cues=renderer_cues,
    )
    try:
        terminology_report = _build_terminology_review(job, words, keyword_index)
    except ValueError as exc:
        raise SubtitlesV2Error(f"terminology review failed: {exc}") from exc
    payload = _wrapper(
        job,
        str(analysis["analysis_sha256"]),
        str(visual_plan["visual_plan_sha256"]),
        render_plan,
        terminology_report=terminology_report,
        renderer_input=talkcraft_subtitles.renderer_input(render_plan, renderer_cues),
    )
    reuse_source: Path | None = None
    baseline_records: list[dict[str, object]] | None = None
    # A non-empty existing generation is only a candidate when its persisted
    # lineage is still intact.  This check deliberately happens before stage
    # creation so damaged history cannot be silently treated as a cache miss.
    if target.is_dir() and any(target.iterdir()):
        baseline_records = _snapshot(target, identity=True)
        lineage = job.stages["subtitles"].get("lineage")
        if (_content_records(lineage) is None
                or _content_records(baseline_records) != _content_records(lineage)):
            raise SubtitlesV2Error("previous subtitle generation changed")
        old_payload = contract_artifacts.read_json_artifact(target / "subtitle-plan.json")
        plan_record = next((record for record in lineage
                            if record.get("path") == "10-subtitles/subtitle-plan.json"), None)
        webm_record = next((record for record in lineage
                            if record.get("path") == "10-subtitles/subtitles.webm"), None)
        if not isinstance(plan_record, Mapping) or not isinstance(webm_record, Mapping):
            raise SubtitlesV2Error("previous subtitle lineage is incomplete")
        plan_path = target / "subtitle-plan.json"
        if (contract_artifacts.sha256_file(plan_path) != plan_record.get("sha256")
                or plan_path.stat().st_size != plan_record.get("bytes")):
            raise SubtitlesV2Error("previous subtitle plan changed")
        old_base = {key: value for key, value in old_payload.items()
                    if key != "subtitle_plan_sha256"}
        if (old_payload.get("job_id") != job.job_id
                or old_payload.get("subtitle_plan_sha256") != contract_artifacts.sha256_json(old_base)):
            raise SubtitlesV2Error("previous subtitle plan identity changed")
        old_renderer = old_payload.get("renderer")
        new_renderer = payload.get("renderer")
        if (old_payload.get("renderer_input") == payload.get("renderer_input")
                and isinstance(old_renderer, Mapping)
                and isinstance(new_renderer, Mapping)
                and {k: v for k, v in old_renderer.items() if k != "render_plan_sha256"}
                == {k: v for k, v in new_renderer.items() if k != "render_plan_sha256"}):
            media_records = _content_records(lineage)
            validated_old_payload = _validate_generation(target, media_records)
            if (validated_old_payload != old_payload
                    or not _records_match(target, baseline_records, identity=True)):
                raise SubtitlesV2Error("previous subtitle generation changed")
            reuse_source = target / "subtitles.webm"
    stage = job.job_dir / f".10-subtitles.stage-{secrets.token_hex(8)}"
    stage.mkdir(mode=0o700)
    journal_owns_stage = False
    try:
        contract_artifacts.write_json_artifact(stage / "subtitle-plan.json", payload)
        if baseline_records is not None and not _records_match(
            target, baseline_records, identity=True
        ):
            raise SubtitlesV2Error("previous subtitle generation changed")
        webm = stage / "subtitles.webm"
        descriptor = os.open(
            webm,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if reuse_source is None:
                talkcraft_subtitles.render(payload["renderer_input"], descriptor)
            else:
                source_fd = os.open(
                    reuse_source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    source_stat = os.fstat(source_fd)
                    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                        raise SubtitlesV2Error("previous subtitle media is invalid")
                    copied = 0
                    digest = hashlib.sha256()
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(descriptor, view)
                            if written <= 0:
                                raise OSError("subtitle media copy stopped")
                            copied += written
                            view = view[written:]
                    if (copied != source_stat.st_size
                            or copied != webm_record.get("bytes")
                            or digest.hexdigest() != webm_record.get("sha256")):
                        raise SubtitlesV2Error("previous subtitle media changed")
                finally:
                    os.close(source_fd)
            if render_plan["cues"]:
                subtitles.bold_subtitles.validate_webm_fd(
                    descriptor, int(render_plan["canvas"]["frames"])
                )
            else:
                subtitles._validate_transparent_webm_fd(
                    descriptor, int(render_plan["canvas"]["frames"])
                )
            talkcraft_subtitles.verify_geometry(descriptor, render_plan, payload["renderer_input"])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        srt = subtitles._srt_bytes(render_plan["cues"])
        if subtitles.parse_srt(srt.decode("utf-8")) != _srt_clock(render_plan["cues"]):
            raise SubtitlesV2Error("subtitle sidecar does not match the plan")
        _write_new(stage / "subtitles.srt", srt)
        material_usage.write_staged_receipt(
            job,
            "subtitles",
            stage,
            target,
            _CORE_OUTPUT_NAMES,
            producer="edit.hd.tools.subtitles_v2",
            producer_version="3-talkcraft",
            stage_input_records=material_usage.current_stage_input_records(
                job, "subtitles"
            ),
            references=[],
        )
        _fsync_directory(stage)
        new_records = _snapshot(stage)
        validated_payload = _validate_generation(stage, new_records)
        _validate_terminology_binding(job, validated_payload)
        current_analysis = content_analysis.load_approved_content_analysis(job)
        _current_transcript, _current_timeline, current_plan, current_records = (
            _load_inputs(job)
        )
        if (
            current_analysis["analysis_sha256"] != analysis["analysis_sha256"]
            or current_plan["visual_plan_sha256"]
            != visual_plan["visual_plan_sha256"]
            or current_records != records
        ):
            raise SubtitlesV2Error("subtitle inputs changed during rendering")
        backup = job.job_dir / f".10-subtitles.backup-{secrets.token_hex(8)}"
        # Job initialization creates the stage directories up front.  An empty
        # 10-subtitles directory is only a publication placeholder, not a
        # previous generation; remove it before the atomic stage install.
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
            _fsync_directory(job.job_dir)
        had_target = os.path.lexists(target)
        if had_target != (baseline_records is not None):
            raise SubtitlesV2Error("previous subtitle generation changed")
        old_records: list[dict[str, object]] = []
        if had_target:
            if baseline_records is None or not _records_match(target, baseline_records, identity=True):
                raise SubtitlesV2Error("previous subtitle generation changed")
            old_records = baseline_records
        transaction = {
            "schema_version": 1,
            "job_id": job.job_id,
            "base_revision": job.revision,
            "workflow_sha256": job.expected_sha256,
            "workflow_bytes": job.expected_bytes,
            "had_target": had_target,
            "stage": stage.name,
            "backup": backup.name,
            "target": target.name,
            "new_records": new_records,
            "old_records": old_records,
        }
        if not isinstance(job.expected_sha256, str) or not isinstance(
            job.expected_bytes, int
        ):
            raise SubtitlesV2Error("workflow identity is unavailable")
        try:
            _write_transaction(job, transaction)
            journal_owns_stage = True
        except BaseException:
            journal_owns_stage = _journal_stage(job.job_dir) == stage.name
            raise
        published = _finish_transaction(job, transaction)
        if published is None:
            raise SubtitlesV2Error("subtitle workflow changed during publication")
        return published
    finally:
        if os.path.lexists(stage) and not journal_owns_stage:
            _remove_known(stage)


def prepare_subtitles_v2(job: state.JobState) -> Path:
    if job.version != 2:
        raise SubtitlesV2Error("formal subtitle builder requires full-v2")
    lock_descriptor = _acquire_job_lock(job.job_dir)
    try:
        try:
            current = state.load_job(job.job_dir)
        except state.WorkflowError as exc:
            if job.stages["subtitles"]["status"] in {
                "ready_for_review",
                "approved",
            }:
                raise SubtitlesV2Error(
                    "subtitle workflow could not be reloaded"
                ) from exc
            raise
        _synchronize_job(job, current)
        if job.version != 2:
            raise SubtitlesV2Error("formal subtitle builder requires full-v2")
        return _prepare_subtitles_v2_locked(job)
    finally:
        _release_job_lock(lock_descriptor)

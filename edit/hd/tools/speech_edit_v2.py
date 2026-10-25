"""Speech cleanup and A-roll edit runners for the full-v2 directory layout."""

from __future__ import annotations

from array import array
import copy
import fcntl
import json
import math
import os
import secrets
import shutil
import stat
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

from . import (
    content_analysis,
    contract_artifacts,
    edit_timeline,
    material_usage,
    state,
    terminology_review,
    transcribe,
)


class SpeechEditV2Error(RuntimeError):
    """Raised when v2 transcription or edit generation is invalid."""


VIDEO_USE_RENDERER = "helpers/render.py"
VIDEO_USE_TRANSCRIBER = "helpers/transcribe.py"
VIDEO_USE_EDL_NAME = "video-use-edl.json"
VIDEO_USE_PACING_PROFILE = {
    "silence_threshold_seconds": 0.40,
    "edge_padding_seconds": 0.08,
}
PORTRAIT_NORMALIZE_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=decrease:"
    "force_divisible_by=2:reset_sar=1:flags=lanczos,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
    "setsar=1,fps=24,format=yuv420p"
)
_TRANSCRIPTION_NAMES = {"speech-16k.wav", "scribe.json", "report.json"}
_PROPOSAL_NAMES = {
    *_TRANSCRIPTION_NAMES,
    "word-transcript.json",
    "diff-summary.json",
    "cleanup-proposal.json",
    "estimated-duration.json",
}
_EDIT_NAMES = {"edit-plan.json", "edited-aroll.mp4", "timeline-map.json"}


def _input(job: state.JobState, name: str) -> Path:
    path = job.root / job.inputs[name]["path"]
    if (
        not path.is_file()
        or contract_artifacts.sha256_file(path) != job.inputs[name]["sha256"]
        or path.stat().st_size != job.inputs[name]["bytes"]
    ):
        raise SpeechEditV2Error(f"bound {name} changed")
    return path


def _inspect(job: state.JobState) -> dict[str, Any]:
    if job.stages["inspect"]["status"] != "approved":
        raise SpeechEditV2Error("inspect must be approved")
    path = job.job_dir / "01-inspect" / "report.json"
    payload = contract_artifacts.read_json_artifact(path)
    if payload.get("version") != 1:
        raise SpeechEditV2Error("inspection report is invalid")
    return payload


def _validate_reviewed_cut_activity(wav_path: Path, plan: dict[str, Any]) -> None:
    cuts = plan.get("reviewed_cut_ranges", [])
    if not cuts:
        return
    try:
        with wave.open(str(wav_path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise SpeechEditV2Error("reviewed cut audio is invalid")
            rate = audio.getframerate()
            frame_count = audio.getnframes()
            samples = array("h", audio.readframes(frame_count))
    except (EOFError, OSError, wave.Error) as exc:
        raise SpeechEditV2Error("reviewed cut audio is invalid") from exc
    if rate <= 0 or frame_count != len(samples):
        raise SpeechEditV2Error("reviewed cut audio is invalid")

    context_padding = int(round(rate * 0.75))
    minimum_relative_peak = 10 ** (-18 / 20)
    for cut in cuts:
        start = max(0, int(math.floor(float(cut["source_start"]) * rate)))
        end = min(frame_count, int(math.ceil(float(cut["source_end"]) * rate)))
        context_start = max(0, start - context_padding)
        context_end = min(frame_count, end + context_padding)
        cut_peak = max((abs(value) for value in samples[start:end]), default=0)
        context_peak = max(
            (abs(value) for value in samples[context_start:context_end]), default=0
        )
        if (
            cut_peak == 0
            or context_peak == 0
            or cut_peak / context_peak < minimum_relative_peak
        ):
            raise SpeechEditV2Error(
                "reviewed cut does not overlap audible speech"
            )


def _acquire_publication_lock(job_dir: Path) -> int:
    descriptor = os.open(
        job_dir / ".speech-edit-v2.publish.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SpeechEditV2Error("speech publication lock is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        edit_timeline._fsync_directory(job_dir)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_publication_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _synchronize_job(target: state.JobState, current: state.JobState) -> None:
    edit_timeline._sync_job(target, current)
    target.version = current.version


def _workflow_identity(job: state.JobState) -> tuple[object, ...]:
    return (
        job.revision,
        job.expected_revision,
        job.expected_sha256,
        job.expected_bytes,
    )


def _same_generation(left: Path, right: Path, names: set[str]) -> bool:
    try:
        left_tree = edit_timeline._snapshot_tree(left, names)
        right_tree = edit_timeline._snapshot_tree(right, names)
    except edit_timeline.EditTimelineError:
        return False
    return {
        name: record[2:] for name, record in left_tree.records.items()
    } == {
        name: record[2:] for name, record in right_tree.records.items()
    }


def _publication_owns_stage(
    job: state.JobState,
    target: Path,
    stage: Path,
) -> bool:
    marker = edit_timeline._marker_path(job.job_dir, target.name)
    if not os.path.lexists(marker):
        return False
    try:
        payload = contract_artifacts.read_json_artifact(marker)
    except BaseException:
        return True
    return type(payload) is dict and payload.get("stage") == stage.name


def _discard_unowned_stage(
    job: state.JobState,
    target: Path,
    stage: Path,
) -> None:
    if not _publication_owns_stage(job, target, stage):
        shutil.rmtree(stage, ignore_errors=True)


def _allowed_old_generations(target: Path) -> tuple[set[str], ...]:
    if target.name == "05-speech-cleanup":
        return (_TRANSCRIPTION_NAMES, _PROPOSAL_NAMES)
    if target.name == "06-edit-structure":
        return (_EDIT_NAMES,)
    raise SpeechEditV2Error("speech publication target is invalid")


def _fsync_stage_generation(stage: Path, names: set[str]) -> None:
    try:
        snapshot = edit_timeline._snapshot_tree(stage, names)
        for name in sorted(names):
            path = stage / name
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened = os.fstat(descriptor)
                named = os.lstat(path)
                device, inode, _digest, size = snapshot.records[name]
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino, opened.st_size)
                    != (device, inode, size)
                    or not os.path.samestat(opened, named)
                ):
                    raise SpeechEditV2Error(
                        "speech staging generation changed before publication"
                    )
                os.fsync(descriptor)
                after = os.fstat(descriptor)
                named_after = os.lstat(path)
                if (
                    not os.path.samestat(opened, after)
                    or not os.path.samestat(opened, named_after)
                    or after.st_size != size
                ):
                    raise SpeechEditV2Error(
                        "speech staging generation changed during synchronization"
                    )
            finally:
                os.close(descriptor)
        directory_descriptor = os.open(
            stage,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            directory_before = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(directory_before.st_mode)
                or (directory_before.st_dev, directory_before.st_ino)
                != (snapshot.device, snapshot.inode)
            ):
                raise SpeechEditV2Error(
                    "speech staging directory changed before synchronization"
                )
            os.fsync(directory_descriptor)
            directory_after = os.fstat(directory_descriptor)
            if not os.path.samestat(directory_before, directory_after):
                raise SpeechEditV2Error(
                    "speech staging directory changed during synchronization"
                )
        finally:
            os.close(directory_descriptor)
        if not edit_timeline._tree_matches(stage, snapshot):
            raise SpeechEditV2Error(
                "speech staging generation changed during synchronization"
            )
    except (KeyboardInterrupt, SystemExit, SpeechEditV2Error):
        raise
    except BaseException as exc:
        raise SpeechEditV2Error(
            "speech staging generation could not be synchronized"
        ) from exc


def _publish(
    job: state.JobState,
    stage: Path,
    target: Path,
    names: tuple[str, ...],
    *,
    stage_id: str,
) -> Path:
    artifact_names = set(names)
    allowed_without_receipt = _allowed_old_generations(target)
    if artifact_names not in allowed_without_receipt:
        raise SpeechEditV2Error("speech publication inventory is invalid")
    try:
        material_usage.write_staged_receipt(
            job,
            stage_id,
            stage,
            target,
            sorted(artifact_names),
            producer="edit.hd.tools.speech_edit_v2",
            producer_version="1",
            stage_input_records=material_usage.current_stage_input_records(
                job, stage_id
            ),
            references=[],
        )
    except material_usage.MaterialUsageError as exc:
        raise SpeechEditV2Error("speech material receipt is invalid") from exc
    expected_names = {*artifact_names, "material-usage.json"}
    allowed_old = tuple(
        generation
        for names_without_receipt in allowed_without_receipt
        for generation in (
            names_without_receipt,
            {*names_without_receipt, "material-usage.json"},
        )
    )
    base_identity = _workflow_identity(job)
    lock = _acquire_publication_lock(job.job_dir)
    try:
        current = state.load_job(job.job_dir)
        _synchronize_job(job, current)
        try:
            recovered = edit_timeline._recover_generation(
                job,
                target.name,
                stage_id,
                expected_names,
                restore_ready=False,
                allowed_old_names=allowed_old,
            )
        except edit_timeline.EditTimelineError as exc:
            raise SpeechEditV2Error("speech publication recovery failed") from exc
        if recovered:
            if not _same_generation(stage, target, expected_names):
                raise SpeechEditV2Error("speech publication changed")
            edit_timeline._discard_directory(stage, expected_names)
            return target

        if _workflow_identity(job) != base_identity:
            status = job.stages[stage_id]["status"]
            if (
                status in {"ready_for_review", "approved"}
                and _same_generation(stage, target, expected_names)
            ):
                target_tree = edit_timeline._snapshot_tree(target, expected_names)
                if not edit_timeline._artifacts_bind_tree(
                    job.stages[stage_id]["artifacts"], target.name, target_tree
                ):
                    raise SpeechEditV2Error("speech publication state changed")
                edit_timeline._discard_directory(stage, expected_names)
                return target
            raise SpeechEditV2Error("speech workflow changed before publication")

        state.require_runnable(job, stage_id)
        old_tree = None
        old_names = expected_names
        if os.path.lexists(target):
            try:
                actual_names = set(os.listdir(target))
            except OSError as exc:
                raise SpeechEditV2Error("speech publication target is invalid") from exc
            if not actual_names:
                try:
                    target.rmdir()
                    edit_timeline._fsync_directory(target.parent)
                except OSError as exc:
                    raise SpeechEditV2Error("speech publication target is invalid") from exc
                old_names = expected_names
                actual_names = set()
            elif not any(actual_names == allowed for allowed in allowed_old):
                raise SpeechEditV2Error("speech publication target is invalid")
            if actual_names:
                old_names = actual_names
                try:
                    old_tree = edit_timeline._snapshot_tree(target, old_names)
                except edit_timeline.EditTimelineError as exc:
                    raise SpeechEditV2Error("speech publication target is invalid") from exc
        _fsync_stage_generation(stage, expected_names)
        try:
            edit_timeline._swap_generation(
                job,
                target,
                stage,
                expected_names,
                lambda artifacts: state.mark_ready(job, stage_id, artifacts),
                old_expected_names=old_names,
                expected_old_tree=old_tree,
                stage_id=stage_id,
                restore_ready=False,
                is_committed=lambda: (
                    job.stages[stage_id]["status"]
                    in {"ready_for_review", "approved"}
                ),
            )
        except edit_timeline.EditTimelineError as exc:
            raise SpeechEditV2Error("speech publication failed") from exc
        return target
    finally:
        _release_publication_lock(lock)


def _normalize_video_use_words(payload: Any, duration: float) -> tuple[list[transcribe.Word], int]:
    events = payload.get("words") if type(payload) is dict else None
    if type(events) is not list or not events:
        raise SpeechEditV2Error("video-use did not return word-level transcription")
    normalized: list[dict[str, Any]] = []
    prefix = ""
    merged = 0

    sentence_punctuation = frozenset(
        ",.!?;:'\"，。！？；：、‘’“”「」『』（）()［］[]《》〈〉【】"
    )

    def is_punctuation_or_space(text: str) -> bool:
        return all(char.isspace() or char in sentence_punctuation for char in text)

    for event in events:
        if type(event) is not dict:
            raise SpeechEditV2Error("video-use transcription event is invalid")
        kind = event.get("type")
        if kind == "audio_event":
            continue
        if kind == "spacing":
            if type(event.get("text")) is not str:
                raise SpeechEditV2Error("video-use spacing is invalid")
            if normalized:
                normalized[-1]["text"] += event["text"]
            else:
                prefix += event["text"]
            continue
        if kind != "word" or type(event.get("text")) is not str or not event["text"].strip():
            raise SpeechEditV2Error("video-use word is invalid")
        start, end = event.get("start"), event.get("end")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or end < start or end > duration + 0.2
        ):
            raise SpeechEditV2Error("video-use word timestamp is invalid")
        punctuation_only = is_punctuation_or_space(event["text"])
        if punctuation_only and start != end:
            if normalized:
                if start < normalized[-1]["end"]:
                    raise SpeechEditV2Error("video-use words overlap")
                normalized[-1]["text"] += event["text"]
            else:
                prefix += event["text"]
            continue
        if start == end:
            merged += 1
            if normalized:
                previous = normalized[-1]
                if start < previous["end"]:
                    raise SpeechEditV2Error("video-use words overlap")
                if not punctuation_only and start > previous["end"]:
                    raise SpeechEditV2Error("video-use zero-duration word is separated")
                previous["text"] += event["text"]
            else:
                if not punctuation_only:
                    raise SpeechEditV2Error("video-use zero-duration word is separated")
                prefix += event["text"]
            continue
        if normalized and start < normalized[-1]["end"]:
            raise SpeechEditV2Error("video-use words overlap")
        normalized.append({"text": prefix + event["text"], "start": start, "end": end})
        prefix = ""
    if prefix or not normalized:
        raise SpeechEditV2Error("video-use transcription has no timed words")
    try:
        edit_timeline._validate_words(normalized)
    except edit_timeline.EditTimelineError as exc:
        raise SpeechEditV2Error("video-use word timestamps are invalid") from exc
    words = [transcribe.Word(**word) for word in normalized]
    return words, merged


def _transcribe_with_video_use(
    job: state.JobState,
    result_path: Path,
    invocation: dict[str, Any],
    duration: float,
) -> tuple[list[transcribe.Word], dict[str, Any]]:
    transcriber = _video_use_entrypoint(job, VIDEO_USE_TRANSCRIBER)
    if not isinstance(result_path, Path):
        raise SpeechEditV2Error("video-use result path is invalid")
    if type(invocation) is not dict or set(invocation) != {
        "entrypoint", "exit_code", "source_sha256", "result_sha256"
    }:
        raise SpeechEditV2Error("video-use invocation evidence is missing")
    if (
        invocation["entrypoint"] != str(transcriber)
        or invocation["exit_code"] != 0
        or invocation["source_sha256"] != job.inputs["video"]["sha256"]
        or not result_path.is_file() or result_path.is_symlink()
        or invocation["result_sha256"] != contract_artifacts.sha256_file(result_path)
    ):
        raise SpeechEditV2Error("video-use invocation does not match this source")
    payload = contract_artifacts.read_json_artifact(result_path)
    words, merged = _normalize_video_use_words(payload, duration)
    return words, {"engine": "video-use/elevenlabs-scribe", "invocation": invocation,
                   "merged_zero_duration_events": merged}


def prepare_transcription(
    job: state.JobState,
    *,
    video_use_result: Path,
    invocation: dict[str, Any],
) -> Path:
    state.require_runnable(job, "speech_cleanup")
    video = _input(job, "video")
    script = _input(job, "script").read_text(encoding="utf-8")
    inspection = _inspect(job)
    duration = float(inspection["audio"]["duration"])
    words, runtime = _transcribe_with_video_use(job, video_use_result, invocation, duration)
    target = job.job_dir / "05-speech-cleanup"
    stage = job.job_dir / f".05-speech-cleanup.stage-{secrets.token_hex(16)}"
    stage.mkdir()
    try:
        wav = stage / "speech-16k.wav"
        raw = stage / "scribe.json"
        transcribe.extract_pcm16k(video, wav)
        shutil.copy2(video_use_result, raw)
        if contract_artifacts.sha256_file(raw) != invocation["result_sha256"]:
            raise SpeechEditV2Error("video-use result changed during staging")
        report = {
            "version": 1,
            "runtime": runtime,
            "script": {
                "sha256": job.inputs["script"]["sha256"],
                "bytes": job.inputs["script"]["bytes"],
                "coverage": transcribe.script_coverage(script, words),
            },
            "transcript": {
                "word_count": len(words),
                "first": words[0].start,
                "last": words[-1].end,
                "words": [
                    {"text": word.text, "start": word.start, "end": word.end}
                    for word in words
                ],
            },
        }
        contract_artifacts.write_json_artifact(stage / "report.json", report)
        _publish(
            job,
            stage,
            target,
            ("speech-16k.wav", "scribe.json", "report.json"),
            stage_id="speech_cleanup",
        )
        return target / "report.json"
    except BaseException:
        _discard_unowned_stage(job, target, stage)
        raise


def prepare_cleanup_proposal(job: state.JobState, plan: Any) -> Path:
    current = job.stages["speech_cleanup"]
    if current["status"] not in {"ready_for_review", "needs_revision"}:
        raise SpeechEditV2Error("transcription must be ready before cleanup proposal")
    target = job.job_dir / "05-speech-cleanup"
    required = ("speech-16k.wav", "scribe.json", "report.json")
    if any(not (target / name).is_file() for name in required):
        raise SpeechEditV2Error("transcription generation is incomplete")
    report = contract_artifacts.read_json_artifact(target / "report.json")
    words = report.get("transcript", {}).get("words")
    prior_summary: dict[str, Any] | None = None
    lineage_pins: dict[str, Any] = {}
    if current["status"] == "needs_revision":
        # A revision must consume the lineage-bound reviewed transcript.  The
        # original report remains the immutable transcription source.
        try:
            lineage_pins = edit_timeline._cleanup_lineage_pins(
                job, generation_name="05-speech-cleanup",
            )
            if not {"word-transcript.json", "diff-summary.json"}.issubset(
                lineage_pins
            ):
                raise SpeechEditV2Error("reviewed transcript is incomplete")
            words = edit_timeline._word_transcript(
                lineage_pins["word-transcript.json"]
            )
            prior_summary = edit_timeline._strict_json_bytes(
                edit_timeline._descriptor_bytes(
                    lineage_pins["diff-summary.json"].descriptor,
                    16 * 1024 * 1024,
                )
            )
        except SpeechEditV2Error:
            raise
        except BaseException as exc:
            raise SpeechEditV2Error("reviewed transcript lineage is invalid") from exc
        finally:
            for pin in lineage_pins.values():
                try:
                    os.close(pin.descriptor)
                except OSError:
                    pass
            lineage_pins = {}
    script = _input(job, "script").read_text(encoding="utf-8")
    inspection = _inspect(job)
    paced_plan = _apply_video_use_pacing(
        plan, words, target / "speech-16k.wav"
    )
    _validate_reviewed_cut_activity(target / "speech-16k.wav", paced_plan)
    proposal = edit_timeline.build_cleanup_proposal(
        script,
        words,
        paced_plan,
        media_duration=float(inspection["audio"]["duration"]),
    )
    approved_content = content_analysis.load_approved_content_analysis(job)
    if prior_summary is not None and "transcript_corrections" in prior_summary:
        proposal["diff_summary"]["transcript_corrections"] = copy.deepcopy(
            prior_summary["transcript_corrections"]
        )
    proposal["diff_summary"]["terminology_review"] = (
        terminology_review.build_bound_report(
            words,
            content_record=approved_content,
            summary=proposal["diff_summary"],
        )
    )
    intervals = _video_use_intervals(
        paced_plan, float(inspection["audio"]["duration"])
    )
    proposal["estimated_duration"]["seconds"] = sum(
        end - start for start, end in intervals
    )
    stage = job.job_dir / f".05-speech-cleanup.stage-{secrets.token_hex(16)}"
    stage.mkdir()
    try:
        for name in required:
            shutil.copy2(target / name, stage / name)
        outputs = {
            "word-transcript.json": proposal["word_transcript"],
            "diff-summary.json": proposal["diff_summary"],
            "cleanup-proposal.json": proposal["cleanup_proposal"],
            "estimated-duration.json": proposal["estimated_duration"],
        }
        for name, payload in outputs.items():
            contract_artifacts.write_json_artifact(stage / name, payload)
        if current["status"] == "ready_for_review":
            state.revise(job, "speech_cleanup", "生成完整口播整理提案")
        _publish(
            job,
            stage,
            target,
            (*required, *outputs),
            stage_id="speech_cleanup",
        )
        return target / "cleanup-proposal.json"
    except BaseException:
        _discard_unowned_stage(job, target, stage)
        raise


def _video_use_entrypoint(job: state.JobState, relative_path: str) -> Path:
    report_path = job.job_dir / "manifests" / "dependency-preflight.json"
    if not report_path.is_file():
        raise SpeechEditV2Error("bound video-use dependency preflight is missing")
    report = contract_artifacts.read_json_artifact(report_path)
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise SpeechEditV2Error("bound video-use dependency preflight is invalid")
    matches = [
        item for item in dependencies
        if isinstance(item, dict) and item.get("id") == "video-use-runtime"
    ]
    if len(matches) != 1:
        raise SpeechEditV2Error("bound video-use dependency is missing")
    dependency = matches[0]
    if (
        dependency.get("status") != "bound"
        or dependency.get("availability_level") != "bound"
        or not isinstance(dependency.get("resolved_path"), str)
    ):
        raise SpeechEditV2Error("video-use is installed but not callable and bound")
    root = Path(dependency["resolved_path"]).expanduser().resolve()
    entrypoint = (root / relative_path).resolve()
    try:
        entrypoint.relative_to(root)
    except ValueError as exc:
        raise SpeechEditV2Error("video-use entrypoint escapes dependency root") from exc
    if not entrypoint.is_file():
        raise SpeechEditV2Error("video-use entrypoint changed after preflight")
    return entrypoint


def _video_use_renderer(job: state.JobState) -> Path:
    return _video_use_entrypoint(job, VIDEO_USE_RENDERER)


def _pacing_audio(wav_path: Path) -> tuple[int, array]:
    try:
        with wave.open(str(wav_path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise SpeechEditV2Error("pacing audio is invalid")
            rate = audio.getframerate()
            samples = array("h", audio.readframes(audio.getnframes()))
    except (EOFError, OSError, wave.Error) as exc:
        raise SpeechEditV2Error("pacing audio is invalid") from exc
    if rate <= 0 or not samples:
        raise SpeechEditV2Error("pacing audio is invalid")
    return rate, samples


def _quiet_ranges(rate: int, samples: array, start: float, end: float) -> list[tuple[float, float]]:
    """Contiguous quiet runs, retaining the existing RMS thresholds."""
    first, last = max(0, math.ceil(start * rate)), min(len(samples), math.floor(end * rate))
    window = max(1, round(rate * 0.04))
    window_limit = (32768 * 10 ** (-40 / 20)) ** 2
    average_limit = (32768 * 10 ** (-48 / 20)) ** 2
    runs = []
    run_start, total, count = first, 0, 0
    for offset in range(first, last, window):
        block = samples[offset:min(offset + window, last)]
        energy = sum(value * value for value in block)
        if energy / len(block) <= window_limit:
            if not count:
                run_start = offset
            total += energy
            count += len(block)
        else:
            if count and total / count <= average_limit:
                runs.append((run_start / rate, offset / rate))
            total, count = 0, 0
    if count and total / count <= average_limit:
        runs.append((run_start / rate, last / rate))
    return runs


def _output_word_gaps(plan: dict[str, Any], words: list[dict[str, Any]], duration: float):
    intervals = _video_use_intervals(plan, duration)
    def position(value):
        cursor = 0.0
        for start, end in intervals:
            if start - 1e-8 <= value <= end + 1e-8:
                return cursor + min(end, max(start, value)) - start
            cursor += end - start
        return None
    kept = [i for segment in plan["segments"] if segment["action"] == "keep"
            for i in range(segment["word_start"], segment["word_end"])
            if position(float(words[i]["start"])) is not None
            and position(float(words[i]["end"])) is not None]
    for left, right in zip(kept, kept[1:]):
        gap = position(float(words[right]["start"])) - position(float(words[left]["end"]))
        yield left, right, max(0.0, gap)


def _apply_video_use_pacing(plan: Any, words: Any, wav_path: Path) -> dict[str, Any]:
    checked_words = edit_timeline._validate_words(words)
    checked_plan = edit_timeline.validate_edit_plan(plan, checked_words)
    threshold = VIDEO_USE_PACING_PROFILE["silence_threshold_seconds"]
    padding = VIDEO_USE_PACING_PROFILE["edge_padding_seconds"]
    rate, samples = _pacing_audio(wav_path)
    cuts = {}
    for segment in checked_plan["segments"]:
        if segment["action"] != "keep":
            continue
        for index in range(segment["word_start"] + 1, segment["word_end"]):
            left, right = float(checked_words[index - 1]["end"]), float(checked_words[index]["start"])
            # Existing reviewed cuts remain authoritative, including partial words.
            if any(c["source_start"] < right and c["source_end"] > left
                   for c in checked_plan.get("reviewed_cut_ranges", [])):
                continue
            quiet = _quiet_ranges(rate, samples, left + padding, right - padding)
            eligible = [(a, b) for a, b in quiet if b - a >= threshold]
            if eligible:
                a, b = max(eligible, key=lambda r: r[1] - r[0])
                cuts[index] = (a + padding, b - padding)
    segments = []
    for segment in checked_plan["segments"]:
        if segment["action"] != "keep":
            segments.append(copy.deepcopy(segment)); continue
        boundaries = [segment["word_start"], *[i for i in cuts
                      if segment["word_start"] < i < segment["word_end"]], segment["word_end"]]
        for first, last in zip(boundaries, boundaries[1:]):
            split = copy.deepcopy(segment)
            text = "".join(w["text"] for w in checked_words[first:last])
            split.update(word_start=first, word_end=last,
                         source_start=float(checked_words[first]["start"]),
                         source_end=float(checked_words[last - 1]["end"]),
                         original_sentence=text, cleaned_sentence=text)
            if first in cuts:
                split["breathing_padding"]["before"] = float(checked_words[first]["start"]) - cuts[first][1]
            if last in cuts:
                split["breathing_padding"]["after"] = cuts[last][0] - float(checked_words[last - 1]["end"])
            if len(boundaries) > 2:
                split["reason"] += "；按 video-use 节奏切分已确认安静中段"
            segments.append(split)
    paced = {**copy.deepcopy(checked_plan), "segments": segments}
    # Across keep boundaries, shorten only already-retained quiet tails/heads.
    # Never count the source gap that the current EDL has already removed.
    keep_segments = [s for s in segments if s["action"] == "keep"]
    gaps = {(a, b): gap for a, b, gap in _output_word_gaps(paced, checked_words, len(samples) / rate)}
    for left, right in zip(keep_segments, keep_segments[1:]):
        a, b = left["word_end"] - 1, right["word_start"]
        if gaps.get((a, b), 0.0) < 0.8:
            continue
        lo, hi = float(checked_words[a]["end"]), float(checked_words[b]["start"])
        if any(c["source_start"] < hi and c["source_end"] > lo
               for c in paced.get("reviewed_cut_ranges", [])):
            continue
        tail = min(lo + float(left["breathing_padding"]["after"]), hi)
        head = max(hi - float(right["breathing_padding"]["before"]), lo)
        runs = _quiet_ranges(rate, samples, lo + padding, tail)
        if runs and abs(runs[-1][1] - tail) < 1 / rate and runs[-1][1] - runs[-1][0] > padding * 2:
            left["breathing_padding"]["after"] = min(left["breathing_padding"]["after"], runs[-1][0] + padding - lo)
        runs = _quiet_ranges(rate, samples, head, hi - padding)
        if runs and abs(runs[0][0] - head) < 1 / rate and runs[0][1] - runs[0][0] > padding * 2:
            right["breathing_padding"]["before"] = min(right["breathing_padding"]["before"], hi - (runs[0][1] - padding))
    return edit_timeline.validate_edit_plan(paced, checked_words)


def cleanup_check_candidates(job: state.JobState) -> list[dict[str, Any]]:
    """Recheck the current retained output, including pauses across keep cuts."""
    from .cleanup_risk import retained_repetitions
    speech = job.job_dir / "05-speech-cleanup"
    words = edit_timeline._validate_words(contract_artifacts.read_json_artifact(
        speech / "word-transcript.json")["words"])
    plan = edit_timeline.validate_edit_plan(contract_artifacts.read_json_artifact(
        speech / "cleanup-proposal.json"), words)
    rate, samples = _pacing_audio(speech / "speech-16k.wav")
    duration = len(samples) / rate
    candidates = retained_repetitions(words, plan, media_duration=duration)
    for left, right, gap in _output_word_gaps(plan, words, duration):
        if gap < 0.8:
            continue
        start, end = float(words[left]["end"]), float(words[right]["start"])
        identity = contract_artifacts.sha256_json({"kind": "retained_pause", "start": start, "end": end})[:16]
        candidates.append({
            "candidate_id": "retained-pause-" + identity,
            "kind": "retained_pause", "word_start": left, "word_end": right + 1,
            "source_start": start, "source_end": end, "output_gap_seconds": round(gap, 6),
            "context": "".join(w["text"] for w in words[max(0, left - 2):right + 3]),
            "evidence": "retained_output_gap_requires_audio_review",
            "audition_range": {"source_start": max(0.0, float(words[left]["start"]) - 0.35),
                               "source_end": min(duration, float(words[right]["end"]) + 0.35)},
        })
    return sorted(candidates, key=lambda c: (c["source_start"], c["candidate_id"]))


def _validate_cleanup_resolutions(candidates: list[dict[str, Any]], resolutions: Any) -> None:
    if type(resolutions) is not list:
        raise SpeechEditV2Error("cleanup candidates require per-candidate audio review")
    identifiers = []
    for item in resolutions:
        if (type(item) is not dict or set(item) != {"candidate_id", "decision", "reason"}
                or item["decision"] != "keep" or type(item["candidate_id"]) is not str
                or type(item["reason"]) is not str or len(item["reason"].strip()) < 6
                or item["reason"].strip() in {"已处理完成", "已经剪掉了", "已处理并通过"}):
            raise SpeechEditV2Error("retained cleanup candidate needs a specific keep reason after listening")
        identifiers.append(item["candidate_id"])
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != {c["candidate_id"] for c in candidates}:
        raise SpeechEditV2Error("unresolved retained pauses or repetitions; revise the plan or review each candidate")


def validate_cleanup_review(job: state.JobState, review: dict[str, Any]) -> None:
    _validate_cleanup_resolutions(cleanup_check_candidates(job), review.get("speech_cleanup_resolutions", []))


def _require_cleanup_review(job: state.JobState) -> None:
    candidates = cleanup_check_candidates(job)
    if not candidates:
        return
    for path in (job.job_dir / "manifests").glob("local-qa-speech_cleanup-r*.json"):
        receipt = contract_artifacts.read_json_artifact(path)
        if (receipt.get("job_id") != job.job_id or receipt.get("job_dir") != str(job.job_dir)
                or receipt.get("stage") != "speech_cleanup" or receipt.get("passed") is not True
                or receipt.get("reviewed_by") != "host"
                or receipt.get("artifacts") != job.stages["speech_cleanup"]["artifacts"]):
            continue
        try:
            _validate_cleanup_resolutions(candidates, receipt.get("speech_cleanup_resolutions", []))
            return
        except SpeechEditV2Error:
            continue
    raise SpeechEditV2Error("retained pauses or repetitions have no bound host audio review")


def _video_use_intervals(
    plan: dict[str, Any], media_duration: float,
) -> list[tuple[float, float]]:
    duration = float(media_duration)
    if duration <= 0:
        raise SpeechEditV2Error("invalid cleanup source duration")
    intervals: list[tuple[float, float]] = []
    segments = plan["segments"]
    for index, segment in enumerate(segments):
        if segment["action"] != "keep":
            continue
        breathing = segment["breathing_padding"]
        start = max(0.0, float(segment["source_start"]) - float(breathing["before"]))
        end = min(duration, float(segment["source_end"]) + float(breathing["after"]))
        if (
            index == 0
            and float(segment["source_start"])
            < VIDEO_USE_PACING_PROFILE["silence_threshold_seconds"]
        ):
            start = 0.0
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    cuts = [
        (float(segment["source_start"]), float(segment["source_end"]))
        for segment in segments
        if segment["action"] == "delete"
    ] + [
        (float(cut["source_start"]), float(cut["source_end"]))
        for cut in plan.get("reviewed_cut_ranges", [])
    ]
    for delete_start, delete_end in cuts:
        if delete_start < 0 or delete_end > duration:
            raise SpeechEditV2Error("invalid reviewed cut range")
        remaining: list[tuple[float, float]] = []
        for start, end in intervals:
            if delete_end <= start or delete_start >= end:
                remaining.append((start, end))
            else:
                if start < delete_start:
                    remaining.append((start, delete_start))
                if delete_end < end:
                    remaining.append((delete_end, end))
        intervals = remaining
    spoken_keeps = [
        (float(segment["source_start"]), float(segment["source_end"]))
        for segment in segments
        if segment["action"] == "keep"
        and any(character.isalnum() for character in segment["original_sentence"])
    ]
    intervals = [
        (start, end) for start, end in intervals
        if end - start >= 0.25 or any(
            start < spoken_end and end > spoken_start
            for spoken_start, spoken_end in spoken_keeps
        )
    ]
    if not intervals or any(end <= start for start, end in intervals):
        raise SpeechEditV2Error("video-use pacing removed the complete source")
    return intervals


def _frame_aligned_timeline(
    intervals: list[tuple[float, float]], *, fps: int,
) -> tuple[list[dict[str, float]], float]:
    if type(fps) is not int or fps <= 0:
        raise SpeechEditV2Error("invalid edit timeline frame rate")
    segments: list[dict[str, float]] = []
    cursor = 0.0
    for start, end in intervals:
        length = end - start
        frames = math.ceil(length * fps - 1e-9)
        rendered_length = frames / fps
        segments.append({
            "source_start": start,
            "source_end": end,
            "timeline_start": cursor,
            "timeline_end": cursor + rendered_length,
        })
        cursor += rendered_length
    return segments, cursor


def _render_with_video_use(
    renderer: Path,
    source: Path,
    intervals: list[tuple[float, float]],
    output: Path,
    stage: Path,
    *,
    timeout: int,
) -> None:
    edl_path = stage / VIDEO_USE_EDL_NAME
    rendered = stage / "video-use-render.mp4"
    edl = {
        "version": 1,
        "sources": {"aroll": str(source)},
        "ranges": [
            {
                "source": "aroll",
                "start": float(start),
                "end": float(end),
                "note": "approved speech cleanup kept range",
            }
            for start, end in intervals
        ],
        "overlays": [],
    }
    contract_artifacts.write_json_artifact(edl_path, edl)
    try:
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                str(edl_path),
                "-o",
                str(rendered),
                "--no-subtitles",
                "--no-loudnorm",
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        if not rendered.is_file() or rendered.stat().st_size <= 0:
            raise SpeechEditV2Error("video-use renderer produced no A-roll")
        # The upstream AAC-copy concat can accumulate encoder padding. Keep its
        # actual graded video clips, but normalize each cut to the same frame
        # clock used by the timeline and assemble source audio only once.
        command = [
            "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
            "-y", "-threads", "1", "-i", str(source),
        ]
        filters = ["[0:a]aresample=48000,asplit=" + str(len(intervals)) + "".join(
            f"[sourcea{index}]" for index in range(len(intervals))
        )]
        for index, (start, end) in enumerate(intervals):
            clip = stage / "clips_graded" / f"seg_{index:02d}_aroll.mp4"
            if not clip.is_file() or clip.stat().st_size <= 0:
                raise SpeechEditV2Error("video-use graded clip is missing")
            command.extend(["-threads", "1", "-i", str(clip)])
            length = end - start
            frames = math.ceil(length * 24 - 1e-9)
            filters.append(
                f"[{index + 1}:v]{PORTRAIT_NORMALIZE_FILTER},"
                "tpad=stop_mode=clone:stop_duration=0.041666667,"
                f"trim=end_frame={frames},setpts=PTS-STARTPTS[v{index}]"
            )
            filters.append(
                f"[sourcea{index}]atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS,"
                "afade=t=in:st=0:d=0.03,"
                f"afade=t=out:st={max(0.0, length - 0.03):.9f}:d=0.03,"
                f"apad=whole_len={frames * 2000},atrim=end_sample={frames * 2000},"
                f"asetpts=N/SR/TB[a{index}]"
            )
        filters.extend([
            "".join(f"[v{i}]" for i in range(len(intervals)))
            + f"concat=n={len(intervals)}:v=1:a=0[outv]",
            "".join(f"[a{i}]" for i in range(len(intervals)))
            + f"concat=n={len(intervals)}:v=0:a=1[outa]",
        ])
        command.extend([
            "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "24", "-threads", "4",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(output),
        ])
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        if not output.is_file() or output.stat().st_size <= 0:
            raise SpeechEditV2Error("portrait normalization produced no A-roll")
    finally:
        edl_path.unlink(missing_ok=True)
        rendered.unlink(missing_ok=True)
        (stage / "base.mp4").unlink(missing_ok=True)
        (stage / "_concat.txt").unlink(missing_ok=True)
        shutil.rmtree(stage / "clips_graded", ignore_errors=True)


def render_edit(job: state.JobState) -> Path:
    state.require_runnable(job, "edit_structure")
    if job.stages["speech_cleanup"]["status"] != "approved":
        raise SpeechEditV2Error("speech_cleanup must be approved")
    _require_cleanup_review(job)
    source = _input(job, "video")
    inspection = _inspect(job)
    speech = job.job_dir / "05-speech-cleanup"
    words_payload = contract_artifacts.read_json_artifact(speech / "word-transcript.json")
    words = edit_timeline._validate_words(words_payload["words"])
    plan = edit_timeline.validate_edit_plan(
        contract_artifacts.read_json_artifact(speech / "cleanup-proposal.json"),
        words,
    )
    source_duration = float(inspection["video"]["duration"])
    intervals = _video_use_intervals(plan, source_duration)
    deleted = not (
        len(intervals) == 1
        and abs(intervals[0][0]) <= 1e-9
        and abs(intervals[0][1] - source_duration) <= 1e-6
    )
    target = job.job_dir / "06-edit-structure"
    stage = job.job_dir / f".06-edit-structure.stage-{secrets.token_hex(16)}"
    stage.mkdir()
    output = stage / "edited-aroll.mp4"
    try:
        command: list[str] | None = [
            "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
            "-y", "-i", str(source),
        ]
        if not deleted:
            command.extend([
                "-map", "0:v:0", "-map", "0:a:0",
                "-vf", PORTRAIT_NORMALIZE_FILTER,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", "24", "-c:a", "copy",
                "-movflags", "+faststart", str(output),
            ])
            audio_policy = "copy-original-elementary"
            render_adapter = "native-ffmpeg-no-cut"
        else:
            command = None
            renderer = _video_use_renderer(job)
            _render_with_video_use(
                renderer,
                source,
                intervals,
                output,
                stage,
                timeout=max(600, int(source_duration * 20)),
            )
            audio_policy = "video-use-audio-clock-30ms-edge-fades"
            render_adapter = "video-use/helpers/render.py"
        if command is not None:
            subprocess.run(
                command, check=True, capture_output=True,
                timeout=max(600, int(source_duration * 20)),
            )
        timeline_segments, output_duration = _frame_aligned_timeline(
            intervals, fps=24,
        )
        edit_plan = {
            "version": 2,
            "cleanup_proposal": plan,
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "audio_policy": audio_policy,
            "render_adapter": render_adapter,
            "downstream_audio_policy": "edited-aroll-master-clock",
        }
        timeline = {
            "version": 1,
            "source_duration": source_duration,
            "output_duration": output_duration,
            "has_deletion": deleted,
            "audio_policy": audio_policy,
            "render_adapter": render_adapter,
            "segments": timeline_segments,
        }
        contract_artifacts.write_json_artifact(stage / "edit-plan.json", edit_plan)
        contract_artifacts.write_json_artifact(stage / "timeline-map.json", timeline)
        _publish(
            job,
            stage,
            target,
            ("edit-plan.json", "edited-aroll.mp4", "timeline-map.json"),
            stage_id="edit_structure",
        )
        return target / "edited-aroll.mp4"
    except BaseException:
        _discard_unowned_stage(job, target, stage)
        raise

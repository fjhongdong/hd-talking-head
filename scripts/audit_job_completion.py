#!/usr/bin/env python3
"""Report whether a video Job is actually complete without changing any file."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


FULL_V2_STAGES = (
    "inspect", "content_analysis", "cover_direction", "cover",
    "speech_cleanup", "edit_structure", "visual_direction", "visual_canary",
    "visual_assets", "subtitles", "preview", "delivery",
)
_SHA256 = frozenset("0123456789abcdef")


class JobCompletionAuditError(RuntimeError):
    """Raised when the audit target cannot be read safely."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise JobCompletionAuditError(f"required record is missing or unsafe: {path.name}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise JobCompletionAuditError(f"invalid JSON record: {path.name}") from exc
    if not isinstance(value, dict):
        raise JobCompletionAuditError(f"record must be a JSON object: {path.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _SHA256 for character in value)
    )


def _safe_job_dir(workspace: Path, context: dict[str, Any]) -> Path:
    if context.get("workspace") != str(workspace):
        raise JobCompletionAuditError("job context belongs to another workspace")
    raw = context.get("job_dir")
    if not isinstance(raw, str):
        raise JobCompletionAuditError("job context has no job directory")
    job_dir = Path(raw)
    if (
        not job_dir.is_absolute()
        or job_dir.resolve() != job_dir
        or not job_dir.is_relative_to(workspace)
        or job_dir.is_symlink()
        or not job_dir.is_dir()
    ):
        raise JobCompletionAuditError("job directory is outside the canonical workspace")
    return job_dir


def _parse_rate(value: object) -> float:
    if not isinstance(value, str) or not value:
        raise ValueError("missing rate")
    numerator, separator, denominator = value.partition("/")
    if separator:
        divisor = float(denominator)
        if divisor == 0:
            raise ValueError("zero rate denominator")
        return float(numerator) / divisor
    return float(value)


def _probe_media(path: Path) -> dict[str, object]:
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30,
        )
        payload = json.loads(completed.stdout, object_pairs_hook=_unique_object,
                             parse_constant=_reject_nonfinite)
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        rotations = [
            item.get("rotation")
            for item in video.get("side_data_list", [])
            if isinstance(item, dict) and "rotation" in item
        ]
        if not rotations:
            rotations = [video.get("tags", {}).get("rotate", 0)]
        duration = video.get("duration", payload.get("format", {}).get("duration"))
        audio = [item for item in streams if item.get("codec_type") == "audio"]
        audio_duration = audio[0].get("duration") if len(audio) == 1 else None
        return {
            "width": int(video["width"]),
            "height": int(video["height"]),
            "fps": _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "rotation": int(float(rotations[0] or 0)),
            "duration_seconds": float(duration),
            "audio_streams": sum(1 for item in streams if item.get("codec_type") == "audio"),
            "audio_duration_seconds": float(audio_duration) if audio_duration is not None else None,
        }
    except (OSError, subprocess.SubprocessError, KeyError, StopIteration, TypeError,
            ValueError, AttributeError, OverflowError) as exc:
        raise JobCompletionAuditError("delivery media probe failed") from exc


def _artifact_matches(record: object, job_dir: Path, relative: str) -> bool:
    if not isinstance(record, dict) or record.get("path") != relative:
        return False
    path = job_dir / relative
    return (
        not path.is_symlink()
        and path.resolve() == path
        and path.is_file()
        and path.stat().st_nlink == 1
        and type(record.get("bytes")) is int
        and record["bytes"] == path.stat().st_size
        and _valid_sha256(record.get("sha256"))
        and record["sha256"] == _sha256_file(path)
    )


def _opening_timeline(job_dir: Path, manifest: dict, stages: dict,
                      probe: dict | None) -> bool:
    """Validate the optional final clock without importing or mutating a runtime."""
    entries = manifest.get("artifacts", {})
    preview_records = stages.get("preview", {}).get("artifacts", [])
    relative = "11-preview/opening-manifest.json"
    registered = [r for r in preview_records if isinstance(r, dict) and r.get("path") == relative]
    path = job_dir / "12-delivery/opening-manifest.json"
    if not (registered or "opening-manifest.json" in entries or path.exists() or path.is_symlink()):
        return False
    opening = _read_json(path)
    options = opening.get("options")
    if not isinstance(options, dict):
        raise JobCompletionAuditError("opening options are invalid")
    body, hold, transition = (opening.get("body_frames"), options.get("hold_frames"),
                              options.get("transition_frames"))
    if (opening.get("schema_version") != 1 or opening.get("job_id") != manifest.get("job_id")
            or opening.get("fps") != 24 or type(body) is not int or body <= 0
            or type(hold) is not int or hold <= 0 or type(transition) is not int
            or not 0 <= transition < body or opening.get("body_offset_frames") != hold
            or opening.get("total_frames") != body + hold
            or not isinstance(options.get("user_confirmation"), str)
            or not options["user_confirmation"].strip()):
        raise JobCompletionAuditError("opening timeline is invalid")
    base = {key: value for key, value in opening.items() if key != "opening_manifest_sha256"}
    digest = hashlib.sha256((json.dumps(base, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n").encode()).hexdigest()
    if (opening.get("opening_manifest_sha256") != digest
            or len(registered) != 1 or not _artifact_matches(registered[0], job_dir, relative)
            or _sha256_file(path) != registered[0]["sha256"]
            or opening.get("preview_sha256") != manifest.get("final_sha256")):
        raise JobCompletionAuditError("opening evidence identity changed")
    srt_entry = entries.get("subtitles/subtitles.srt", {})
    output = srt_entry.get("output", {})
    srt = opening.get("output_srt")
    if (srt != {"path": "subtitles.srt", "sha256": output.get("sha256"), "bytes": output.get("bytes")}
            or srt_entry.get("source", {}).get("path") != "11-preview/subtitles.srt"
            or "plans/body-subtitles.webm" not in entries
            or "subtitles/subtitles.webm" in entries):
        raise JobCompletionAuditError("opening subtitle clock evidence changed")
    if probe is not None and (probe.get("audio_streams") != 1
            or not _positive_number(probe.get("duration_seconds"))
            or abs(float(probe["duration_seconds"]) - (body + hold) / 24) > 1 / 24 + .01):
        raise JobCompletionAuditError("opening final media timeline mismatch")
    return True


def _music_evidence(workspace: Path, job_dir: Path, delivery: dict, stages: dict,
                    probe: dict | None) -> bool:
    """Audit frozen music evidence only; this is not a listening assessment."""
    names = {'music-manifest.json', 'music-audit.m4a', 'music-license-source', 'music-credits.txt'}
    entries = delivery.get('artifacts', {})
    records = stages.get('preview', {}).get('artifacts', [])
    qa_path = job_dir / '12-delivery/qa/qa-report.json'
    qa = _read_json(qa_path) if qa_path.exists() or qa_path.is_symlink() else {}
    preview_qa_path = job_dir / '11-preview/qa-report.json'
    preview_qa = (_read_json(preview_qa_path)
                  if preview_qa_path.exists() or preview_qa_path.is_symlink() else {})
    indicated = (('background_music' in delivery and delivery['background_music'] is not False)
                 or ('background_music' in qa and qa['background_music'] is not False)
                 or ('background_music' in preview_qa and preview_qa['background_music'] is not False)
                 or 'music_manifest_sha256' in preview_qa or preview_qa.get('audio_mix_layers', 1) != 1
                 or 'music_manifest_sha256' in qa or qa.get('audio_mix_layers', 1) != 1
                 or bool(names.intersection(entries))
                 or any(isinstance(r, dict) and r.get('path') in
                        {'11-preview/' + n for n in names} for r in records)
                 or any((job_dir / folder / n).exists() or (job_dir / folder / n).is_symlink()
                        for folder in ('11-preview', '12-delivery') for n in names))
    if not indicated:
        return False
    try:
        def require(condition, message):
            if not condition:
                raise JobCompletionAuditError(message)

        def signed(value, field):
            require(type(value) is dict, 'music signed record must be an object')
            base = {k: v for k, v in value.items() if k != field}
            actual = hashlib.sha256((json.dumps(base, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False) + '\n').encode()).hexdigest()
            require(value.get(field) == actual, 'music self hash changed')

        for name in names | {'qa/qa-report.json'}:
            preview_name = 'qa-report.json' if name == 'qa/qa-report.json' else name
            relative = '11-preview/' + preview_name
            matches = [r for r in records if isinstance(r, dict) and r.get('path') == relative]
            output = entries[name]['output']
            require(len(matches) == 1 and _artifact_matches(matches[0], job_dir, relative),
                    'music preview registration changed')
            require(entries[name]['source'] == matches[0]
                    and _artifact_matches({**output, 'path': '12-delivery/' + name},
                                          job_dir, '12-delivery/' + name)
                    and output.get('path') == name
                    and output.get('sha256') == matches[0]['sha256'],
                    'music delivery attachment changed')
        music = _read_json(job_dir / '12-delivery/music-manifest.json')
        signed(music, 'music_manifest_sha256')
        plan = music['plan']
        signed(plan, 'music_plan_sha256')
        frames, offset = plan['total_frames'], plan['body_offset_frames']
        require(set(music) == {'schema_version', 'plan', 'voice_sha256', 'preview_sha256',
                'metrics', 'listening_approval', 'attachments', 'music_manifest_sha256'}
                and set(plan) == {'schema_version', 'job_id', 'fps', 'total_frames',
                'body_offset_frames', 'options', 'music', 'license', 'music_plan_sha256'},
                'music record schema changed')
        require(type(music['schema_version']) is int and music['schema_version'] == 1
                and type(plan['schema_version']) is int and plan['schema_version'] == 1
                and plan['job_id'] == delivery['job_id'] and type(plan['fps']) is int and plan['fps'] == 24
                and type(frames) is int and frames > 0 and type(offset) is int and 0 <= offset < frames
                and isinstance(plan['options']['user_confirmation'], str)
                and bool(plan['options']['user_confirmation'].strip())
                and music['listening_approval'] == 'required_at_preview'
                and _valid_sha256(music['voice_sha256'])
                and music['preview_sha256'] == delivery['final_sha256'], 'music identity or clock invalid')
        options = plan['options']
        fields = {'material_id', 'material_sha256', 'license_material_id', 'license_sha256',
                  'title', 'author', 'source', 'user_confirmation', 'selection', 'mix'}
        require(type(options) is dict and set(options) == fields
                and all(type(options[k]) is str and options[k].strip()
                        for k in fields - {'selection', 'mix'}), 'music options incomplete')
        selection = options['selection']
        require(type(selection) is dict and set(selection) == {'start_frame', 'end_frame', 'crossfade_frames'}
                and all(type(v) is int for v in selection.values())
                and selection['start_frame'] >= 0
                and 0 < 2 * selection['crossfade_frames'] < selection['end_frame'] - selection['start_frame'],
                'music selection invalid')
        ranges = {'voice_gain_db': (-30, 12), 'music_gain_db': (-60, 0),
                  'duck_threshold': (.00097563, 1), 'duck_ratio': (1, 20),
                  'duck_attack_ms': (.01, 2000), 'duck_release_ms': (.01, 9000)}
        mix = options['mix']
        require(type(mix) is dict and set(mix) == set(ranges) | {'fade_in_frames', 'fade_out_frames'},
                'music mix incomplete')
        require(all(type(mix[k]) in (int, float) and math.isfinite(mix[k]) and lo <= mix[k] <= hi
                    for k, (lo, hi) in ranges.items())
                and all(type(mix[k]) is int and 0 < mix[k] <= frames
                        for k in ('fade_in_frames', 'fade_out_frames'))
                and mix['fade_in_frames'] + mix['fade_out_frames'] <= frames, 'music mix invalid')
        voice_relative = '06-edit-structure/edited-aroll.mp4'
        edit = stages.get('edit_structure', {})
        voices = [r for r in edit.get('artifacts', []) if isinstance(r, dict) and r.get('path') == voice_relative]
        require(edit.get('status') == 'approved' and len(voices) == 1
                and _artifact_matches(voices[0], job_dir, voice_relative)
                and music['voice_sha256'] == voices[0]['sha256']
                and qa.get('audio_source_sha256') == voices[0]['sha256'], 'music voice source changed')
        for name, option in (('music', 'material_sha256'), ('license', 'license_sha256')):
            record = plan[name]
            relative = record['path']
            id_option = 'material_id' if name == 'music' else 'license_material_id'
            require(type(record) is dict and set(record) == {'material_id', 'path', 'sha256', 'bytes'}
                    and record['material_id'] == options[id_option]
                    and isinstance(relative, str) and not Path(relative).is_absolute()
                    and '..' not in Path(relative).parts and Path(relative).as_posix() == relative
                    and _artifact_matches(record, workspace, relative)
                    and record['sha256'] == plan['options'][option], 'music source changed')
        require(set(music['attachments']) == names - {'music-manifest.json'}, 'music attachments missing')
        for name, digest in music['attachments'].items():
            require(digest == entries[name]['output']['sha256'], 'music attachment identity changed')
        require(music['attachments']['music-license-source'] == plan['license']['sha256'],
                'music license identity changed')
        require(delivery.get('background_music') is True and qa.get('background_music') is True
                and type(qa.get('audio_mix_layers')) is int and qa['audio_mix_layers'] == 2
                and qa.get('music_manifest_sha256') == music['music_manifest_sha256']
                and qa.get('preview_sha256') == delivery['final_sha256']
                and type(qa['media']['frames']) is int and qa['media']['frames'] == frames,
                'music QA binding changed')
        opening_path = job_dir / '12-delivery/opening-manifest.json'
        opening = _read_json(opening_path) if opening_path.exists() else None
        require(offset == (opening['body_offset_frames'] if opening else 0)
                and (opening is None or frames == opening['total_frames']), 'music opening clock changed')
        metrics = music['metrics']
        require(set(metrics) == {'final', 'music'}, 'music measurements missing')
        for item in metrics.values():
            require(set(item) == {'integrated_lufs', 'true_peak_dbtp'}
                    and all(type(v) in (int, float) and math.isfinite(v) for v in item.values()),
                    'music measurements invalid')
        require(metrics['final']['true_peak_dbtp'] <= 0
                and metrics['music']['integrated_lufs'] >= -60, 'music measurements failed')
        require(probe is not None and type(probe.get('audio_streams')) is int
                and probe['audio_streams'] == 1 and _positive_number(probe.get('duration_seconds'))
                and _positive_number(probe.get('audio_duration_seconds'))
                and abs(probe['duration_seconds'] - frames / 24) <= 1 / 24 + .01
                and abs(probe['audio_duration_seconds'] - frames / 24) <= 1 / 24 + .01,
                'music final media clock unverified or changed')
        return True
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, OSError) as exc:
        raise JobCompletionAuditError('music evidence incomplete or invalid') from exc


def _delivery_inventory(job_dir: Path, records: list, manifest: dict, *, sidecar: bool) -> None:
    """Check every active deliverable, not just the final video and its receipt."""
    registered = {}
    for record in records:
        relative = record.get("path") if isinstance(record, dict) else None
        if (
            not isinstance(relative, str) or not relative.startswith("12-delivery/")
            or Path(relative).as_posix() != relative or ".." in Path(relative).parts
            or relative in registered or not _artifact_matches(record, job_dir, relative)
        ):
            raise JobCompletionAuditError("delivery inventory record is missing, unsafe or changed")
        registered[relative] = record
    inventory = manifest.get("artifacts")
    if not isinstance(inventory, dict):
        raise JobCompletionAuditError("delivery manifest inventory must be an object")
    business = set(registered) - {
        "12-delivery/delivery-manifest.json", "12-delivery/approval-receipt.json",
        "12-delivery/material-usage.json",
    }
    if business != {f"12-delivery/{name}" for name in inventory}:
        raise JobCompletionAuditError("delivery manifest inventory does not match registration")
    for name, entry in inventory.items():
        record = registered[f"12-delivery/{name}"]
        if not isinstance(entry, dict) or entry.get("output") != {
            "path": name, "sha256": record["sha256"], "bytes": record["bytes"],
        }:
            raise JobCompletionAuditError("delivery manifest output identity changed")
    actual = set()
    for path in (job_dir / "12-delivery").rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise JobCompletionAuditError("delivery contains an unsafe entry")
        if path.is_file():
            actual.add(path.relative_to(job_dir).as_posix())
    expected = set(registered)
    if sidecar:
        expected.add("12-delivery/approval-receipt.json")  # Semantics validated below.
    if actual != expected:
        raise JobCompletionAuditError("delivery directory does not match registration")


def _positive_number(value: object) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _receipt_state(
    receipt: dict[str, Any], *, job_id: str, revision: int,
    final_identity: dict[str, object] | None,
) -> tuple[str | None, list[str]]:
    failures: list[str] = []
    kind = receipt.get("approval_kind")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("decision") != "approved"
        or not isinstance(kind, str)
        or kind not in {"formal_final", "legacy_external"}
        or receipt.get("job_id") != job_id
        or receipt.get("approved_by") != "human"
        or not isinstance(receipt.get("approved_at"), str)
        or not receipt["approved_at"].strip()
        or not isinstance(receipt.get("delivery"), dict)
    ):
        return None, ["approval_receipt_invalid"]
    delivery = receipt["delivery"]
    if delivery.get("path") != "12-delivery/final.mp4":
        failures.append("approval_delivery_path_mismatch")
    if final_identity is None:
        failures.append("approved_delivery_missing")
    else:
        if delivery.get("sha256") != final_identity["sha256"]:
            failures.append("approval_delivery_sha256_mismatch")
        if delivery.get("bytes") != final_identity["bytes"]:
            failures.append("approval_delivery_bytes_mismatch")
    if kind == "formal_final":
        if receipt.get("workflow_revision") != revision:
            failures.append("approval_workflow_revision_mismatch")
        if (
            type(receipt.get("reviewed_revision")) is not int
            or receipt["reviewed_revision"] != revision - 1
            or not _valid_sha256(receipt.get("reviewed_workflow_sha256"))
            or not isinstance(receipt.get("user_confirmation"), str)
            or not receipt["user_confirmation"].strip()
        ):
            failures.append("approval_confirmation_evidence_invalid")
    if kind == "legacy_external" and receipt.get("workflow_revision") is not None:
        failures.append("legacy_approval_must_not_claim_workflow_revision")
    return kind, failures


def audit_job_completion(workspace: Path) -> dict[str, object]:
    """Read and classify a Job without invoking any workflow mutation API."""
    workspace = Path(workspace).expanduser().absolute()
    verified: list[str] = []
    unproven: list[str] = []
    failures: list[str] = []
    revision: int | None = None
    delivery_identity: dict[str, object] | None = None
    probe = None
    try:
        if workspace.resolve() != workspace or workspace.is_symlink() or not workspace.is_dir():
            raise JobCompletionAuditError("workspace must be an existing canonical directory")
        context = _read_json(workspace / "job-context.json")
        job_dir = _safe_job_dir(workspace, context)
        workflow = _read_json(job_dir / "workflow.json")
        job_id = workflow.get("job_id")
        revision = workflow.get("revision")
        stages = workflow.get("stages")
        if (
            not isinstance(job_id, str)
            or context.get("job_id") != job_id
            or type(revision) is not int or revision < 0
            or not isinstance(stages, dict)
        ):
            raise JobCompletionAuditError("workflow identity is invalid")
        if any(not isinstance(record, dict) or not isinstance(record.get("status"), str)
               for record in stages.values()):
            raise JobCompletionAuditError("workflow stage or status is invalid")

        missing_stage_records = [stage for stage in FULL_V2_STAGES if stage not in stages]
        if workflow.get("version") != 2 or missing_stage_records:
            all_approved = False
            unproven.append("formal_workflow_not_complete")
        else:
            not_approved = [
                stage for stage in FULL_V2_STAGES
                if not isinstance(stages.get(stage), dict)
                or stages[stage].get("status") != "approved"
            ]
            all_approved = not not_approved
            if all_approved:
                verified.append("all_full_v2_stages_approved")
            else:
                unproven.append("stages_not_approved:" + ",".join(not_approved))

        final = job_dir / "12-delivery/final.mp4"
        receipt_path = job_dir / "12-delivery/approval-receipt.json"
        receipt_present = receipt_path.exists() or receipt_path.is_symlink()
        delivery_status = (
            stages.get("delivery", {}).get("status")
            if isinstance(stages.get("delivery"), dict) else None
        )
        if final.is_symlink():
            failures.append("approved_delivery_unsafe")
        elif final.is_file():
            delivery_identity = {
                "path": "12-delivery/final.mp4",
                "sha256": _sha256_file(final),
                "bytes": final.stat().st_size,
            }
        elif receipt_present or delivery_status in {"ready_for_review", "approved"}:
            failures.append("approved_delivery_missing")
        else:
            unproven.append("delivery_missing")

        delivery_artifacts = (
            stages.get("delivery", {}).get("artifacts", [])
            if isinstance(stages.get("delivery"), dict) else []
        )
        if not isinstance(delivery_artifacts, list):
            raise JobCompletionAuditError("delivery artifacts must be a list")
        final_records = [
            record for record in delivery_artifacts
            if isinstance(record, dict) and record.get("path") == "12-delivery/final.mp4"
        ]
        if delivery_status in {"ready_for_review", "approved"}:
            if len(final_records) != 1 or not _artifact_matches(
                final_records[0], job_dir, "12-delivery/final.mp4",
            ):
                failures.append("workflow_delivery_artifact_mismatch")
            else:
                verified.append("workflow_delivery_artifact_exact")

        manifest_path = job_dir / "12-delivery/delivery-manifest.json"
        manifest: dict[str, Any] | None = None
        if manifest_path.exists() or manifest_path.is_symlink():
            try:
                manifest = _read_json(manifest_path)
            except JobCompletionAuditError:
                failures.append("delivery_manifest_invalid")
        elif delivery_status in {"ready_for_review", "approved"}:
            failures.append("delivery_manifest_missing")
        if manifest is not None and delivery_identity is not None:
            inventory = manifest.get("artifacts")
            entry = inventory.get("final.mp4") if isinstance(inventory, dict) else None
            output = entry.get("output") if isinstance(entry, dict) else None
            canvas = manifest.get("canvas")
            if not isinstance(output, dict) or not isinstance(canvas, dict) or not all(
                _positive_number(canvas.get(key)) for key in ("width", "height", "fps")
            ):
                raise JobCompletionAuditError("delivery manifest shape or canvas is invalid")
            if (
                manifest.get("job_id") != job_id
                or manifest.get("final_sha256") != delivery_identity["sha256"]
                or output.get("sha256") != delivery_identity["sha256"]
                or output.get("bytes") != delivery_identity["bytes"]
            ):
                failures.append("delivery_manifest_identity_mismatch")
            else:
                verified.append("delivery_manifest_exact")
            try:
                probe = _probe_media(final)
            except JobCompletionAuditError:
                unproven.append("delivery_media_probe_unavailable")
            else:
                if (
                    not all(_positive_number(probe.get(key))
                            for key in ("width", "height", "fps", "duration_seconds"))
                    or probe.get("width") != canvas.get("width")
                    or probe.get("height") != canvas.get("height")
                    or abs(float(probe.get("fps", 0)) - float(canvas.get("fps", 0))) > 0.01
                    or probe.get("rotation") != 0
                ):
                    failures.append("delivery_media_probe_mismatch")
                else:
                    delivery_identity["media"] = probe
                    verified.append("delivery_media_probe_consistent")

        if delivery_status in {"ready_for_review", "approved"} and manifest is not None:
            try:
                _delivery_inventory(job_dir, delivery_artifacts, manifest, sidecar=receipt_present)
            except JobCompletionAuditError as exc:
                failures.append(str(exc))
            else:
                verified.append("delivery_inventory_exact")
            try:
                if _opening_timeline(job_dir, manifest, stages, probe):
                    verified.append("opening_final_timeline_bound")
            except (JobCompletionAuditError, TypeError, AttributeError, ValueError) as exc:
                failures.append("opening_contract_invalid:" + str(exc))
            try:
                if _music_evidence(workspace, job_dir, manifest, stages, probe):
                    verified.append("music_final_evidence_bound")
                    unproven.append("music_listening_quality_not_machine_verified")
            except (JobCompletionAuditError, TypeError, AttributeError, ValueError) as exc:
                failures.append("music_contract_invalid:" + str(exc))

        receipt_kind: str | None = None
        if receipt_present:
            try:
                receipt = _read_json(receipt_path)
            except JobCompletionAuditError:
                failures.append("approval_receipt_invalid")
            else:
                retired_receipt = False
                pending_receipt = False
                formal = receipt.get("approval_kind") == "formal_final"
                if formal:
                    relative = "12-delivery/approval-receipt.json"
                    registered = [r for r in delivery_artifacts
                                  if isinstance(r, dict) and r.get("path") == relative]
                    lineage = stages.get("delivery", {}).get("lineage", [])
                    if not isinstance(lineage, list):
                        raise JobCompletionAuditError("delivery lineage must be a list")
                    retired_receipt = (
                        not registered
                        and delivery_status in {"pending", "needs_revision", "blocked"}
                        and any(_artifact_matches(r, job_dir, relative) for r in lineage)
                    )
                    pending_receipt = (
                        not registered and delivery_status == "ready_for_review"
                        and receipt.get("reviewed_revision") == revision
                        and receipt.get("workflow_revision") == revision + 1
                        and receipt.get("reviewed_workflow_sha256")
                        == _sha256_file(job_dir / "workflow.json")
                    )
                    if not retired_receipt and not pending_receipt and (
                        len(registered) != 1
                        or not _artifact_matches(registered[0], job_dir, relative)
                    ):
                        failures.append("workflow_approval_receipt_mismatch")
                    if not retired_receipt:
                        relative_manifest = "12-delivery/delivery-manifest.json"
                        manifests = [r for r in delivery_artifacts if isinstance(r, dict)
                                     and r.get("path") == relative_manifest]
                        if (len(manifests) != 1
                                or not _artifact_matches(manifests[0], job_dir, relative_manifest)
                                or receipt.get("delivery_manifest") != manifests[0]):
                            failures.append("approval_manifest_identity_mismatch")
                receipt_kind, receipt_failures = _receipt_state(
                    receipt, job_id=job_id, revision=revision + int(pending_receipt),
                    final_identity=delivery_identity,
                )
                if retired_receipt:
                    receipt_kind = None
                    unproven.append("final_approval_retired_by_revision")
                elif pending_receipt:
                    failures.extend(receipt_failures)
                    receipt_kind = None
                    unproven.append("final_approval_pending_commit")
                else:
                    failures.extend(receipt_failures)
                if receipt_kind and not receipt_failures and not failures:
                    verified.append("final_approval_exact_delivery_hash")
                    if receipt_kind == "legacy_external":
                        verified.append("external_approval_exact_delivery_hash")
        else:
            if any(isinstance(r, dict) and r.get("path") == "12-delivery/approval-receipt.json"
                   for r in delivery_artifacts):
                failures.append("registered_approval_receipt_missing")
            else:
                unproven.append("final_approval_missing")

        if receipt_kind == "formal_final" and not all_approved:
            failures.append("formal_approval_without_complete_workflow")
        if receipt_kind == "legacy_external" and all_approved:
            failures.append("legacy_approval_conflicts_with_complete_workflow")

        failures = list(dict.fromkeys(failures))
        verified = list(dict.fromkeys(verified))
        unproven = list(dict.fromkeys(unproven))
        formal_evidence = {
            "all_full_v2_stages_approved",
            "workflow_delivery_artifact_exact",
            "delivery_manifest_exact",
            "delivery_inventory_exact",
            "delivery_media_probe_consistent",
            "final_approval_exact_delivery_hash",
        }
        if failures:
            status = "inconsistent"
        elif receipt_kind == "formal_final" and formal_evidence.issubset(verified):
            status = "formal_complete"
        elif receipt_kind == "legacy_external":
            status = "legacy_external_approval"
            if "formal_workflow_not_complete" not in unproven and not all_approved:
                unproven.append("formal_workflow_not_complete")
        else:
            status = "incomplete"
    except (JobCompletionAuditError, OSError) as exc:
        status = "inconsistent"
        failures.append(str(exc))

    return {
        "status": status,
        "verified_claims": verified,
        "unproven_claims": unproven,
        "failures": failures,
        "workflow_revision": revision,
        "delivery_identity": delivery_identity,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = audit_job_completion(args.workspace)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result["status"])
    return 0 if result["status"] != "inconsistent" else 1


if __name__ == "__main__":
    raise SystemExit(main())

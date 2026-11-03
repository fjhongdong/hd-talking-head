#!/usr/bin/env python3
"""Report whether a video Job is actually complete without changing any file."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


FULL_V2_STAGES = (
    "inspect", "content_analysis", "cover_direction", "cover",
    "speech_cleanup", "edit_structure", "visual_direction",
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
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return False
    path = job_dir / relative
    return (
        path.is_relative_to(job_dir)
        and not path.is_symlink()
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
):
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


def _delivery_inventory(job_dir: Path, records: list, manifest: dict) -> None:
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
        "12-delivery/delivery-manifest.json",
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
    if actual != expected:
        raise JobCompletionAuditError("delivery directory does not match registration")


def _positive_number(value: object) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _delivery_sources(workspace: Path, job_dir: Path, stages: dict, manifest: dict) -> None:
    for name, entry in manifest["artifacts"].items():
        if name == "credits.md" and "generated_from" in entry:
            relative = "11-preview/source-manifest.json"
            origins = [r for r in stages["preview"]["artifacts"] if r.get("path") == relative]
            if (set(entry) != {"generated_from", "output"} or len(origins) != 1
                    or not _artifact_matches(origins[0], job_dir, relative)
                    or manifest["artifacts"].get("source-manifest.json", {}).get("source") != origins[0]):
                raise JobCompletionAuditError("delivery credits origin changed")
            source = _read_json(job_dir / relative)
            digest = source.get("source_manifest_sha256")
            if (not _valid_sha256(digest)
                    or entry["generated_from"] != {"path": relative, "sha256": digest}):
                raise JobCompletionAuditError("delivery credits origin changed")
            continue
        source = entry.get("source")
        if not isinstance(source, dict) or set(entry) != {"source", "output"}:
            raise JobCompletionAuditError("delivery source changed")
        relative = source.get("path", "")
        if (name == "sources/user-material-index.json"
                and relative == str(workspace / "00-user-provided/material-index.json")):
            relative = "00-user-provided/material-index.json"
            matches = _artifact_matches({**source, "path": relative}, workspace, relative)
        else:
            matches = _artifact_matches(source, job_dir, relative)
        if not matches:
            raise JobCompletionAuditError("delivery source changed")


def audit_job_completion(workspace: Path) -> dict[str, object]:
    """Check input/output identity and report delivered or actual user acceptance."""
    workspace = Path(workspace).expanduser().absolute()
    verified, unproven, failures = [], [], []
    revision, delivery_identity, delivery_file = None, None, None
    try:
        if workspace.resolve() != workspace or workspace.is_symlink() or not workspace.is_dir():
            raise JobCompletionAuditError("workspace must be an existing canonical directory")
        context = _read_json(workspace / "job-context.json")
        job_dir = _safe_job_dir(workspace, context)
        workflow = _read_json(job_dir / "workflow.json")
        job_id, revision, stages = workflow.get("job_id"), workflow.get("revision"), workflow.get("stages")
        if (workflow.get("version") != 2 or not isinstance(job_id, str)
                or context.get("job_id") != job_id or type(revision) is not int or revision < 0
                or not isinstance(stages, dict) or set(stages) != set(FULL_V2_STAGES)):
            raise JobCompletionAuditError("workflow identity or stage set is invalid")
        if not isinstance(workflow.get("inputs"), dict) or set(workflow["inputs"]) != {"video", "script"}:
            raise JobCompletionAuditError("workflow inputs are incomplete")
        for record in workflow["inputs"].values():
            if not isinstance(record, dict) or not _artifact_matches(record, workspace, record.get("path", "")):
                raise JobCompletionAuditError("workflow input changed")
        unfinished = []
        for stage, value in stages.items():
            if not isinstance(value, dict) or value.get("status") not in {"pending", "ready", "completed", "needs_revision", "blocked"}:
                raise JobCompletionAuditError("workflow stage status is invalid")
            if value["status"] != "completed":
                unfinished.append(stage)
            records = value.get("artifacts")
            if not isinstance(records, list):
                raise JobCompletionAuditError("workflow artifacts must be a list")
            for record in records:
                if not isinstance(record, dict) or not _artifact_matches(record, job_dir, record.get("path", "")):
                    raise JobCompletionAuditError("workflow artifact changed: " + stage)
        if unfinished:
            unproven.append("stages_not_completed:" + ",".join(unfinished))
        else:
            verified.append("all_stages_completed")
        final = job_dir / "12-delivery/final.mp4"
        records = stages["delivery"]["artifacts"]
        final_records = [r for r in records if r.get("path") == "12-delivery/final.mp4"]
        if not final_records:
            if stages["delivery"]["status"] in {"ready", "completed"}:
                raise JobCompletionAuditError("delivery output is not registered")
            unproven.append("delivery_missing")
        else:
            if len(final_records) != 1 or not _artifact_matches(final_records[0], job_dir, "12-delivery/final.mp4"):
                raise JobCompletionAuditError("delivery output changed")
            delivery_identity = final_records[0]
            verified.append("workflow_delivery_artifact_exact")
            manifest = _read_json(job_dir / "12-delivery/delivery-manifest.json")
            entry = manifest.get("artifacts", {}).get("final.mp4", {})
            output, canvas = entry.get("output", {}), manifest.get("canvas", {})
            if (manifest.get("job_id") != job_id or manifest.get("final_sha256") != delivery_identity["sha256"]
                    or output.get("sha256") != delivery_identity["sha256"] or output.get("bytes") != delivery_identity["bytes"]):
                raise JobCompletionAuditError("delivery manifest identity changed")
            _delivery_inventory(job_dir, records, manifest)
            _delivery_sources(workspace, job_dir, stages, manifest)
            verified += ["delivery_manifest_exact", "delivery_inventory_exact"]
            probe = _probe_media(final)
            if (not all(_positive_number(probe.get(k)) for k in ("width", "height", "fps", "duration_seconds"))
                    or probe["width"] != canvas.get("width") or probe["height"] != canvas.get("height")
                    or not _positive_number(canvas.get("fps"))
                    or abs(probe["fps"] - canvas["fps"]) > .01 or probe["rotation"] != 0):
                raise JobCompletionAuditError("delivery media probe differs from output canvas")
            verified.append("delivery_media_probe_consistent")
            if _opening_timeline(job_dir, manifest, stages, probe):
                verified.append("opening_final_timeline_bound")
        status = "incomplete"
        manifests = [r for r in records if r.get("path") == "12-delivery/delivery-manifest.json"]
        receipt_root = (job_dir / "manifests/delivery" / manifests[0]["sha256"]
                        if not unfinished and len(manifests) == 1 else None)
        receipt_path = receipt_root / "delivered.json" if receipt_root is not None else None
        if receipt_path is not None and (receipt_path.exists() or receipt_path.is_symlink()):
            receipt = _read_json(receipt_path)
            if (unfinished or len(manifests) != 1 or receipt.get("schema_version") != 1
                    or receipt.get("decision") != "delivered" or receipt.get("job_id") != job_id
                    or receipt.get("delivery") != delivery_identity
                    or receipt.get("delivery_manifest") != manifests[0]
                    or not isinstance(receipt.get("delivered_at"), str) or not receipt["delivered_at"].strip()):
                raise JobCompletionAuditError("delivery receipt differs from the completed output")
            stable_root = "delivered/" + manifests[0]["sha256"]
            for record, name in ((delivery_identity, "final.mp4"), (manifests[0], "delivery-manifest.json")):
                relative = stable_root + "/" + name
                if not _artifact_matches({**record, "path": relative}, job_dir, relative):
                    raise JobCompletionAuditError("stable delivered file is missing or changed")
            delivery_file = str(job_dir / stable_root / "final.mp4")
            authorization = receipt.get("visual_authorization")
            if not isinstance(authorization, dict) or not _artifact_matches(authorization, job_dir, authorization.get("path", "")):
                raise JobCompletionAuditError("delivery authorization changed")
            authorized = _read_json(job_dir / authorization["path"])
            if (authorized.get("job_id") != job_id or authorized.get("authorized_by") != "user"
                    or authorized.get("authorization_scope") != "visual_plan_and_generation"
                    or not isinstance(authorized.get("user_confirmation"), str) or not authorized["user_confirmation"].strip()):
                raise JobCompletionAuditError("delivery has no actual user authorization")
            status = "delivered"
            verified += ["delivery_receipt_exact", "visual_authorization_exact"]
            acceptance_path = receipt_root / "accepted.json"
            if acceptance_path.exists() or acceptance_path.is_symlink():
                accepted = _read_json(acceptance_path)
                if (accepted.get("schema_version") != 1 or accepted.get("decision") != "accepted"
                        or accepted.get("accepted_by") != "user" or accepted.get("job_id") != job_id
                        or accepted.get("delivery") != receipt["delivery"]
                        or accepted.get("delivery_manifest") != receipt["delivery_manifest"]
                        or not isinstance(accepted.get("user_confirmation"), str) or not accepted["user_confirmation"].strip()
                        or not isinstance(accepted.get("accepted_at"), str) or not accepted["accepted_at"].strip()):
                    raise JobCompletionAuditError("user acceptance differs from delivered output")
                status = "accepted"
                verified.append("actual_user_acceptance_recorded")
            else:
                unproven.append("user_final_acceptance_pending")
        elif not unfinished:
            unproven.append("delivery_receipt_missing")
    except (JobCompletionAuditError, OSError, KeyError, TypeError, ValueError) as exc:
        status = "inconsistent"
        failures.append(str(exc))
    return {"status": status, "verified_claims": verified, "unproven_claims": unproven,
            "failures": failures, "workflow_revision": revision, "delivery_identity": delivery_identity,
            "delivery_file": delivery_file}


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

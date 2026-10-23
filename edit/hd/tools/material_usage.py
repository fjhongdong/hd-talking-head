"""Authoritative user-material usage receipts for full-v2 stage artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import state


class MaterialUsageError(RuntimeError):
    """Raised when a material-usage declaration cannot be trusted."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_FIELDS = {
    "schema_version",
    "job_id",
    "stage_id",
    "stage_revision",
    "producer",
    "producer_version",
    "stage_input_sha256",
    "complete_reference_declaration",
    "references",
}
_REFERENCE_FIELDS = {
    "material_id",
    "material_sha256",
    "consumer_kind",
    "consumer_id",
    "binding_path",
    "artifact_paths",
}
_RECORD_FIELDS = {"path", "sha256", "bytes"}
_PRODUCERS = {
    "inspect": {"edit.hd.tools.inspect_inputs"},
    "content_analysis": {"edit.hd.tools.content_analysis"},
    "cover_direction": {"edit.hd.tools.cover_direction"},
    "cover": {"edit.hd.tools.cover"},
    "speech_cleanup": {"edit.hd.tools.speech_cleanup", "edit.hd.tools.speech_edit_v2"},
    "edit_structure": {
        "edit.hd.tools.edit_structure",
        "edit.hd.tools.edit_timeline",
        "edit.hd.tools.speech_edit_v2",
    },
    "visual_direction": {"edit.hd.tools.visual_plan"},
    "visual_canary": {"edit.hd.tools.visual_canary"},
    "visual_assets": {"edit.hd.tools.visual_assets_v2"},
    "subtitles": {
        "edit.hd.tools.subtitles",
        "edit.hd.tools.subtitles_v2",
        "edit.hd.tools.subtitle_render",
    },
    "preview": {
        "edit.hd.tools.preview",
        "edit.hd.tools.preview_v2",
        "edit.hd.tools.preview_render",
    },
    "delivery": {
        "edit.hd.tools.delivery",
        "edit.hd.tools.qa_delivery_v2",
        "edit.hd.tools.delivery_render",
    },
}
_CONSUMER_KINDS = {
    "background_music",
    "input_inspection",
    "cover_reference",
    "cover_render",
    "visual_segment",
    "visual_canary_segment",
    "visual_asset_segment",
}


def _fail(message: str) -> MaterialUsageError:
    return MaterialUsageError(message)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{field} must be a non-empty string")
    return value


def _hash(value: object, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise _fail(f"{field} must be a lowercase SHA-256")
    return text


def _canonical_sha256(value: object) -> str:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _fail("material usage contains invalid JSON") from exc
    return hashlib.sha256(data).hexdigest()


def _strict_record(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise _fail(f"{field} is not an artifact identity")
    path = _job_path_text(value["path"], f"{field}.path")
    digest = _hash(value["sha256"], f"{field}.sha256")
    size = value["bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise _fail(f"{field}.bytes must be a non-negative integer")
    return {"path": path, "sha256": digest, "bytes": size}


def _normalized_records(values: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    records = [_strict_record(dict(value), "stage_input_records") for value in values]
    records.sort(key=lambda item: str(item["path"]))
    if len({str(item["path"]) for item in records}) != len(records):
        raise _fail("stage input paths must be unique")
    return records


def current_stage_input_records(
    job: state.JobState, stage_id: str
) -> list[dict[str, object]]:
    """Return the complete direct-input artifact identity set for a stage."""
    dependencies = state.dependencies_for(job, stage_id)
    if not dependencies:
        source = job.inputs.values()
    else:
        source = (
            artifact
            for dependency in dependencies
            for artifact in job.stages[dependency]["artifacts"]
        )
    return _normalized_records(source)


def _job_path_text(value: object, field: str) -> str:
    text = _text(value, field)
    path = Path(text)
    if path.is_absolute() or path.as_posix() != text or ".." in path.parts:
        raise _fail(f"{field} must be a Job-relative POSIX path")
    return text


def _absolute_job_path(job: state.JobState, value: Path) -> tuple[Path, str]:
    path = Path(value)
    if not path.is_absolute():
        path = job.job_dir / path
    try:
        relative = path.relative_to(job.job_dir)
    except ValueError as exc:
        raise _fail("artifact path escapes the Job") from exc
    cursor = job.job_dir
    try:
        for part in relative.parts:
            cursor /= part
            if stat.S_ISLNK(os.lstat(cursor).st_mode):
                raise _fail("artifact path uses a symbolic link")
        named = os.lstat(path)
        if not stat.S_ISREG(named.st_mode) or named.st_nlink != 1:
            raise _fail("artifact path is not a regular file")
    except OSError as exc:
        raise _fail("artifact path does not exist") from exc
    return path, relative.as_posix()


def _material_identities(job: state.JobState) -> dict[str, str]:
    path = job.root / "00-user-provided" / "material-index.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        materials = payload["materials"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise _fail("material index is unavailable") from exc
    if not isinstance(materials, list):
        raise _fail("material index is invalid")
    result: dict[str, str] = {}
    for item in materials:
        if not isinstance(item, dict):
            raise _fail("material index is invalid")
        identifier = _text(item.get("material_id"), "material_id")
        digest = _hash(item.get("sha256"), "material.sha256")
        if identifier in result:
            raise _fail("material IDs must be unique")
        status = item.get("status", "active" if payload.get("schema_version") == 1 else None)
        if status == "active":
            result[identifier] = digest
    return result


def _references(
    job: state.JobState,
    values: object,
    published_paths: set[str],
) -> list[dict[str, object]]:
    if not isinstance(values, list):
        raise _fail("references must be an array")
    materials = _material_identities(job) if values else {}
    result: list[dict[str, object]] = []
    identities: set[tuple[str, str, str, str]] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict) or set(value) != _REFERENCE_FIELDS:
            raise _fail(f"references[{index}] fields do not match the contract")
        material_id = _text(value["material_id"], "material_id")
        material_sha256 = _hash(value["material_sha256"], "material_sha256")
        if materials.get(material_id) != material_sha256:
            raise _fail("material reference does not bind an active material identity")
        consumer_kind = _text(value["consumer_kind"], "consumer_kind")
        if consumer_kind not in _CONSUMER_KINDS:
            raise _fail("consumer_kind is unsupported")
        consumer_id = _text(value["consumer_id"], "consumer_id")
        binding_path = _text(value["binding_path"], "binding_path")
        if not binding_path.startswith("/") or ".." in binding_path.split("/"):
            raise _fail("binding_path must be an absolute JSON pointer")
        paths = value["artifact_paths"]
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(item, str) for item in paths)
        ):
            raise _fail("artifact_paths must be a non-empty string array")
        normalized_paths = [_job_path_text(item, "artifact_paths") for item in paths]
        if len(set(normalized_paths)) != len(normalized_paths):
            raise _fail("artifact_paths must be unique")
        if not set(normalized_paths) <= published_paths:
            raise _fail("material reference names an unpublished artifact")
        identity = (material_id, consumer_kind, consumer_id, binding_path)
        if identity in identities:
            raise _fail("material references must be unique")
        identities.add(identity)
        result.append(
            {
                "material_id": material_id,
                "material_sha256": material_sha256,
                "consumer_kind": consumer_kind,
                "consumer_id": consumer_id,
                "binding_path": binding_path,
                "artifact_paths": normalized_paths,
            }
        )
    return result


def _published_paths(
    job: state.JobState,
    artifact_paths: Sequence[Path],
    path_overrides: Sequence[str] | None = None,
) -> set[str]:
    checked_artifacts = [_absolute_job_path(job, Path(path)) for path in artifact_paths]
    if path_overrides is None:
        values = [relative for _, relative in checked_artifacts]
    else:
        if len(path_overrides) != len(checked_artifacts):
            raise _fail("published path overrides do not match the artifact list")
        values = [_job_path_text(value, "published_path_overrides") for value in path_overrides]
    result = set(values)
    if len(result) != len(checked_artifacts):
        raise _fail("published artifact paths must be unique")
    return result


def _build_receipt_from_paths(
    job: state.JobState,
    stage_id: str,
    *,
    producer: str,
    producer_version: str,
    stage_input_records: Iterable[Mapping[str, object]],
    references: object,
    published_paths: set[str],
) -> dict[str, object]:
    state.dependencies_for(job, stage_id)
    producer = _text(producer, "producer")
    if producer not in _PRODUCERS.get(stage_id, set()):
        raise _fail("producer is not authorized for this stage")
    producer_version = _text(producer_version, "producer_version")
    supplied_inputs = _normalized_records(stage_input_records)
    expected_inputs = current_stage_input_records(job, stage_id)
    if supplied_inputs != expected_inputs:
        raise _fail("stage input declaration is incomplete")
    if not published_paths:
        raise _fail("a stage must publish at least one artifact")
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "stage_id": stage_id,
        "stage_revision": job.revision + 1,
        "producer": producer,
        "producer_version": producer_version,
        "stage_input_sha256": _canonical_sha256(supplied_inputs),
        "complete_reference_declaration": True,
        "references": _references(job, references, published_paths),
    }


def build_receipt(
    job: state.JobState,
    stage_id: str,
    *,
    producer: str,
    producer_version: str,
    stage_input_records: Iterable[Mapping[str, object]],
    references: object,
    artifact_paths: Sequence[Path],
) -> dict[str, object]:
    """Build a complete declaration from explicit, verified consumer bindings."""
    return _build_receipt_from_paths(
        job,
        stage_id,
        producer=producer,
        producer_version=producer_version,
        stage_input_records=stage_input_records,
        references=references,
        published_paths=_published_paths(job, artifact_paths),
    )


def build_receipt_for_publication(
    job: state.JobState,
    stage_id: str,
    *,
    producer: str,
    producer_version: str,
    stage_input_records: Iterable[Mapping[str, object]],
    references: object,
    artifact_paths: Sequence[str],
) -> dict[str, object]:
    """Build a receipt for paths owned by the caller's atomic publication."""
    normalized = {_job_path_text(path, "artifact_paths") for path in artifact_paths}
    if len(normalized) != len(artifact_paths):
        raise _fail("published artifact paths must be unique")
    return _build_receipt_from_paths(
        job,
        stage_id,
        producer=producer,
        producer_version=producer_version,
        stage_input_records=stage_input_records,
        references=references,
        published_paths=normalized,
    )


def visual_segment_references(
    segments: Sequence[Mapping[str, object]],
    *,
    consumer_kind: str,
    artifact_paths_by_segment: Mapping[str, Sequence[str]],
) -> list[dict[str, object]]:
    """Extract exact local-material bindings from validated visual segments."""
    result: list[dict[str, object]] = []
    for segment_index, segment in enumerate(segments):
        segment_id = _text(segment.get("segment_id"), "segment_id")
        strategy = segment.get("visual_strategy")
        bindings = segment.get("bindings")
        if not isinstance(strategy, dict) or not isinstance(bindings, dict):
            raise _fail("visual segment bindings are invalid")
        components = strategy.get("components")
        if not isinstance(components, list):
            raise _fail("visual segment components are invalid")
        artifact_paths = list(artifact_paths_by_segment.get(segment_id, ()))
        for component in components:
            if not isinstance(component, dict) or component.get("kind") != "local_material":
                continue
            component_id = _text(component.get("component_id"), "component_id")
            binding = bindings.get(component_id)
            if not isinstance(binding, dict):
                raise _fail("local material binding is missing")
            escaped_component_id = component_id.replace("~", "~0").replace("/", "~1")
            result.append(
                {
                    "material_id": _text(binding.get("material_id"), "material_id"),
                    "material_sha256": _hash(
                        binding.get("sha256"), "material_sha256"
                    ),
                    "consumer_kind": consumer_kind,
                    "consumer_id": segment_id,
                    "binding_path": (
                        f"/segments/{segment_index}/bindings/"
                        f"{escaped_component_id}/material_id"
                    ),
                    "artifact_paths": artifact_paths,
                }
            )
    return result


def validate_receipt(
    job: state.JobState,
    stage_id: str,
    receipt: object,
    *,
    published_artifacts: Sequence[Path],
    published_path_overrides: Sequence[str] | None = None,
    expected_stage_revision: int | None = None,
) -> dict[str, object]:
    """Validate a receipt against current Job inputs and published artifacts."""
    state.dependencies_for(job, stage_id)
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise _fail("material usage receipt fields do not match the contract")
    if receipt["schema_version"] != 1 or receipt["job_id"] != job.job_id:
        raise _fail("material usage receipt identity does not match the Job")
    if receipt["stage_id"] != stage_id:
        raise _fail("material usage receipt stage does not match")
    revision = receipt["stage_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise _fail("stage_revision must be a positive integer")
    if expected_stage_revision is not None and revision != expected_stage_revision:
        raise _fail("material usage receipt revision does not match")
    if revision > job.revision + (1 if expected_stage_revision is not None else 0):
        raise _fail("material usage receipt revision is in the future")
    producer = _text(receipt["producer"], "producer")
    if producer not in _PRODUCERS.get(stage_id, set()):
        raise _fail("producer is not authorized for this stage")
    _text(receipt["producer_version"], "producer_version")
    expected_inputs = current_stage_input_records(job, stage_id)
    if _hash(receipt["stage_input_sha256"], "stage_input_sha256") != _canonical_sha256(
        expected_inputs
    ):
        raise _fail("stage inputs no longer match the receipt")
    if receipt["complete_reference_declaration"] is not True:
        raise _fail("material usage declaration is incomplete")
    published_paths = _published_paths(
        job, published_artifacts, published_path_overrides
    )
    checked = dict(receipt)
    checked["references"] = _references(job, receipt["references"], published_paths)
    return checked


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".material-usage.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    data = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _write_bytes_atomic(path, data)


def write_staged_receipt(
    job: state.JobState,
    stage_id: str,
    staging_root: Path,
    published_root: Path,
    artifact_names: Sequence[str],
    *,
    producer: str,
    producer_version: str,
    stage_input_records: Iterable[Mapping[str, object]],
    references: object,
) -> Path:
    """Write a receipt into a staged generation using its final Job paths."""
    if not artifact_names:
        raise _fail("a staged generation must contain artifacts")
    staged_paths: list[Path] = []
    published_paths: list[str] = []
    try:
        published_root_relative = published_root.relative_to(job.job_dir)
    except ValueError as exc:
        raise _fail("published root escapes the Job") from exc
    for name in artifact_names:
        relative = Path(_job_path_text(name, "artifact_names"))
        staged_paths.append(staging_root / relative)
        published_paths.append((published_root_relative / relative).as_posix())
    logical_paths = _published_paths(job, staged_paths, published_paths)
    receipt = _build_receipt_from_paths(
        job,
        stage_id,
        producer=producer,
        producer_version=producer_version,
        stage_input_records=stage_input_records,
        references=references,
        published_paths=logical_paths,
    )
    receipt_path = staging_root / "material-usage.json"
    if receipt_path.exists():
        try:
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _fail("staged material usage receipt is invalid") from exc
        if existing != receipt:
            raise _fail("staged material usage receipt changed")
        return receipt_path
    _write_json_atomic(receipt_path, receipt)
    return receipt_path


def _receipt_is_bound(job: state.JobState, receipt_path: Path) -> bool:
    try:
        persisted = state.load_job(job.job_dir)
        relative = receipt_path.relative_to(job.job_dir).as_posix()
        data = receipt_path.read_bytes()
    except (state.WorkflowError, OSError, ValueError):
        return False
    digest = hashlib.sha256(data).hexdigest()
    return any(
        item.get("path") == relative
        and item.get("sha256") == digest
        and item.get("bytes") == len(data)
        for stage_record in persisted.stages.values()
        for item in stage_record["artifacts"]
    )


def publish_and_mark_ready(
    job: state.JobState,
    stage_id: str,
    artifacts: Sequence[Path],
    *,
    producer: str,
    producer_version: str,
    stage_input_records: Iterable[Mapping[str, object]],
    references: object,
) -> Path:
    """Publish a receipt and bind it into the same formal artifact transition."""
    receipt = build_receipt(
        job,
        stage_id,
        producer=producer,
        producer_version=producer_version,
        stage_input_records=stage_input_records,
        references=references,
        artifact_paths=artifacts,
    )
    parents = [Path(path).parent for path in artifacts]
    common_parent = Path(os.path.commonpath([str(path) for path in parents]))
    try:
        common_parent.relative_to(job.job_dir)
    except ValueError as exc:
        raise _fail("stage artifacts do not share a Job directory") from exc
    receipt_path = common_parent / "material-usage.json"
    previous: bytes | None = None
    if receipt_path.exists():
        _absolute_job_path(job, receipt_path)
        previous = receipt_path.read_bytes()
    _write_json_atomic(receipt_path, receipt)
    try:
        state.mark_ready(job, stage_id, [*artifacts, receipt_path])
    except BaseException:
        if not _receipt_is_bound(job, receipt_path):
            if previous is None:
                try:
                    receipt_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                _write_bytes_atomic(receipt_path, previous)
        raise
    return receipt_path


def load_current_receipt(
    job: state.JobState, stage_id: str
) -> dict[str, object]:
    """Load the receipt bound to the stage's current formal artifact set."""
    state.dependencies_for(job, stage_id)
    stage = job.stages[stage_id]
    if stage["status"] not in {"ready_for_review", "approved"}:
        raise _fail("stage has no current published material usage receipt")
    matches = [
        record
        for record in stage["artifacts"]
        if Path(str(record.get("path", ""))).name == "material-usage.json"
    ]
    if len(matches) != 1:
        raise _fail("stage material usage receipt is missing or ambiguous")
    record = _strict_record(matches[0], "material_usage_artifact")
    path, _ = _absolute_job_path(job, job.job_dir / str(record["path"]))
    data = path.read_bytes()
    if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise _fail("material usage receipt bytes changed")
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _fail("material usage receipt is not valid JSON") from exc
    published = [
        job.job_dir / str(item["path"])
        for item in stage["artifacts"]
        if item is not matches[0]
    ]
    revision = payload.get("stage_revision") if isinstance(payload, dict) else None
    if isinstance(revision, bool) or not isinstance(revision, int) or revision > job.revision:
        raise _fail("material usage receipt revision is invalid")
    return validate_receipt(
        job,
        stage_id,
        payload,
        published_artifacts=published,
        expected_stage_revision=revision,
    )

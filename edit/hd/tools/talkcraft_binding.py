"""Bind a TalkCraft span bundle to the current approved visual direction."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import state, visual_plan
from .event_binding import build_event_binding_manifest, validate_event_binding_manifest
from .render_span import SpanExecutionRequest, select_span_chunk
from .talkcraft_contract import (
    DEFAULT_CARD_REGISTRY,
    validate_production_brief_bundle,
)


class TalkCraftBindingError(ValueError):
    pass


_BINDING_KEYS = {
    "schema_version", "job_id", "workflow_revision", "workflow_sha256",
    "visual_plan_sha256", "visual_plan_artifact_sha256", "span_id",
    "chunk_id", "spec_sha256", "scene_brief_sha256",
    "production_brief_bundle_sha256", "registry_version",
    "registry_sha256", "production_brief_bundle_artifact_sha256",
    "execution_targets",
}
_BINDING_KEYS_V2 = _BINDING_KEYS | {"event_binding_manifest"}


def _fail(message: str) -> None:
    raise TalkCraftBindingError(message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("approved TalkCraft brief bundle contains duplicate fields")
        result[key] = value
    return result


def _target_key(target: Mapping[str, Any]) -> tuple[str, ...]:
    if target["kind"] == "component":
        return ("component", target["segment_id"], target["component_id"])
    return ("boundary", target["boundary_id"], target["card_slot_id"])


def _approved_json_artifact(
    job: state.JobState,
    *,
    relative: str,
    label: str,
) -> tuple[dict[str, Any], str]:
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        _fail(f"{label} path is invalid")
    records = [
        record
        for record in job.stages["visual_direction"].get("artifacts", [])
        if type(record) is dict and record.get("path") == relative
    ]
    if len(records) != 1:
        _fail(f"{label} is not a current approved artifact")
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(
            job.job_dir.resolve(strict=True),
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        for part in parsed.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parsed.parts[-1],
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(file_fd)
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
        payload = b"".join(chunks)
        visible = os.stat(
            parsed.parts[-1], dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISREG(visible.st_mode)
            or (visible.st_dev, visible.st_ino, visible.st_size, visible.st_mtime_ns)
            != (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
            or digest.hexdigest() != records[0].get("sha256")
            or metadata.st_size != records[0].get("bytes")
        ):
            _fail(f"{label} identity changed")
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: _fail(
                f"{label} is not finite JSON"
            ),
        )
    except TalkCraftBindingError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail(f"{label} is unreadable")
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    return value, records[0]["sha256"]


def bind_approved_brief_bundle(
    job: state.JobState,
    request: SpanExecutionRequest,
    production_brief_bundle: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    semantic_event_plan: object | None = None,
) -> dict[str, Any]:
    """Return a frozen binding only for the current approved v4 plan and bundle."""

    if not isinstance(job, state.JobState) or job.version != 2:
        _fail("TalkCraft execution requires a full-v2 Job")
    try:
        current = state.load_job(job.job_dir)
    except (OSError, state.WorkflowError):
        _fail("current Job state is unavailable")
    if (
        current.job_id != job.job_id
        or current.revision != job.expected_revision
        or current.expected_sha256 != job.expected_sha256
        or current.expected_bytes != job.expected_bytes
    ):
        _fail("Job revision changed before TalkCraft binding")
    if current.stages["visual_direction"].get("status") != "approved":
        _fail("visual_direction must be currently approved")
    try:
        approved_plan_value, plan_artifact_sha256 = _approved_json_artifact(
            current,
            relative="07-visual-direction/visual-plan.json",
            label="approved visual plan",
        )
        approved_plan = visual_plan.validate_visual_plan(approved_plan_value)
        span, chunk = select_span_chunk(request)
        supplied_bundle = validate_production_brief_bundle(
            production_brief_bundle, registry_path=registry_path
        )
        approved_payload, bundle_artifact_sha256 = _approved_json_artifact(
            current,
            relative=(
                "07-visual-direction/talkcraft-briefs/"
                f"{span['span_id']}/{chunk['chunk_id']}.json"
            ),
            label="approved TalkCraft brief bundle",
        )
        approved_bundle = validate_production_brief_bundle(
            approved_payload, registry_path=registry_path
        )
    except TalkCraftBindingError:
        raise
    except Exception as error:
        _fail(str(error))
    if approved_plan != request.visual_plan or approved_plan.get("schema_version") != 4:
        _fail("SpanExecutionRequest is not the current approved v4 plan")
    if approved_bundle != supplied_bundle:
        _fail("supplied TalkCraft brief bundle is not the approved artifact")
    owner = approved_bundle["owner"]
    expected_owner = {
        "type": "span",
        "id": span["span_id"],
        "chunk_id": chunk["chunk_id"],
        "visual_plan_sha256": approved_plan["visual_plan_sha256"],
        "spec_sha256": chunk["spec_sha256"],
        "scene_brief_sha256": span["scene_brief_sha256"],
    }
    entries = approved_bundle["briefs"]
    if owner != expected_owner or len(entries) != len(chunk["execution_targets"]):
        _fail("approved TalkCraft brief bundle does not own the requested chunk")
    for entry, target in zip(entries, chunk["execution_targets"]):
        brief = entry["brief"]
        if (
            _target_key(brief["execution_target"]) != _target_key(target)
            or brief["card_id"] != target["card_id"]
        ):
            _fail("approved TalkCraft brief order differs from the requested chunk")
    registry = approved_bundle["briefs"][0]["brief"]["registry"]
    event_binding_manifest = None
    if semantic_event_plan is not None:
        event_binding_manifest = build_event_binding_manifest(
            semantic_event_plan,
            approved_bundle,
            span_id=span["span_id"],
            span_start_frame=span["start_frame"],
            span_end_frame=span["end_frame"],
            span_segment_ids=set(span["segment_ids"]),
            visual_plan=approved_plan,
        )
    binding = {
        "schema_version": (
            "talkcraft-approved-binding/v2"
            if event_binding_manifest is not None
            else "talkcraft-approved-binding/v1"
        ),
        "job_id": current.job_id,
        "workflow_revision": current.revision,
        "workflow_sha256": current.expected_sha256,
        "visual_plan_sha256": approved_plan["visual_plan_sha256"],
        "visual_plan_artifact_sha256": plan_artifact_sha256,
        "span_id": span["span_id"],
        "chunk_id": chunk["chunk_id"],
        "spec_sha256": chunk["spec_sha256"],
        "scene_brief_sha256": span["scene_brief_sha256"],
        "production_brief_bundle_sha256": approved_bundle["bundle_sha256"],
        "production_brief_bundle_artifact_sha256": bundle_artifact_sha256,
        "registry_version": registry["version"],
        "registry_sha256": registry["sha256"],
        "execution_targets": copy.deepcopy(chunk["execution_targets"]),
    }
    if event_binding_manifest is not None:
        binding["event_binding_manifest"] = event_binding_manifest
    return binding


def revalidate_approved_binding(
    job_dir: Path,
    request: SpanExecutionRequest,
    production_brief_bundle: object,
    binding: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    semantic_event_plan: object | None = None,
) -> dict[str, Any]:
    """Reject adoption when the Job approval changed while rendering."""

    if type(binding) is not dict or set(binding) not in (_BINDING_KEYS, _BINDING_KEYS_V2):
        _fail("TalkCraft approved binding is invalid")
    if binding.get("schema_version") == "talkcraft-approved-binding/v2":
        if semantic_event_plan is None:
            _fail("semantic event plan is required to revalidate a v2 binding")
        try:
            validate_event_binding_manifest(binding["event_binding_manifest"])
        except ValueError as error:
            _fail(str(error))
    try:
        current = state.load_job(Path(job_dir))
    except (OSError, state.WorkflowError):
        _fail("current Job state is unavailable")
    refreshed = bind_approved_brief_bundle(
        current,
        request,
        production_brief_bundle,
        registry_path=registry_path,
        semantic_event_plan=semantic_event_plan,
    )
    if refreshed != binding:
        _fail("TalkCraft approval changed while rendering")
    return copy.deepcopy(binding)


__all__ = [
    "TalkCraftBindingError",
    "bind_approved_brief_bundle",
    "revalidate_approved_binding",
]

"""Cross-segment RenderSpan and immutable chunk contracts for VisualPlan v4."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .broll_component_executor import ComponentArtifact
from .contract_artifacts import sha256_json
from .talkcraft_contract import (
    DEFAULT_CARD_REGISTRY,
    DEPENDENCY_ID,
    MAX_CHUNK_FRAMES,
    PRIMARY_RENDERER,
    load_card_registry,
    validate_production_brief_bundle,
)


class RenderSpanError(ValueError):
    pass


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SPAN_KEYS = {"span_id", "mode", "segment_ids", "start_frame", "end_frame", "scene_brief_sha256", "boundaries", "chunks"}
_BOUNDARY_KEYS = {"boundary_id", "card_slot_id", "from_segment_id", "to_segment_id", "card_id", "start_frame", "end_frame"}
_CHUNK_KEYS = {"chunk_id", "start_frame", "end_frame", "execution_targets", "spec_sha256"}
_COMPONENT_TARGET_KEYS = {"kind", "segment_id", "component_id", "card_id", "start_frame", "end_frame"}
_BOUNDARY_TARGET_KEYS = {"kind", "boundary_id", "card_slot_id", "card_id", "start_frame", "end_frame"}
_RENDERED_KEYS = {
    "schema_version", "visual_plan_sha256", "span_id", "chunk_id",
    "spec_sha256", "scene_brief_sha256", "production_brief_bundle_sha256",
    "video", "frames", "component_artifacts", "output_probe", "keyframes",
    "renderer", "render_identity",
}
_FILE_KEYS = {"job_path", "sha256", "bytes"}
_KEYFRAME_KEYS = _FILE_KEYS | {"frame"}
_COMPONENT_WRAPPER_KEYS = {"component_id", "execution_target", "artifact"}
_COMPONENT_ARTIFACT_KEYS = set(ComponentArtifact.__dataclass_fields__)
_PROBE_KEYS = {
    "container", "codec", "pixel_format", "width", "height", "fps",
    "frame_count", "duration", "audio_streams",
}
_RENDERER_KEYS = {
    "dependency_id", "primary_renderer", "adapter_id", "adapter_version",
    "entrypoint", "implementation_sha256",
}


@dataclass(frozen=True)
class SpanExecutionRequest:
    visual_plan: Mapping[str, Any]
    span_id: str
    chunk_id: str


def _fail(message: str) -> None:
    raise RenderSpanError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} fields are invalid")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(f"{label} must be a safe identifier")
    return value


def _frame(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label} must be a non-negative integer frame")
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase sha256")
    return value


def chunk_spec_sha256(span_id: str, chunk: Mapping[str, Any]) -> str:
    return sha256_json({
        "span_id": span_id,
        "chunk_id": chunk["chunk_id"],
        "start_frame": chunk["start_frame"],
        "end_frame": chunk["end_frame"],
        "execution_targets": chunk["execution_targets"],
    })


def _target_key(target: Mapping[str, Any]) -> tuple[str, ...]:
    if target["kind"] == "component":
        return ("component", target["segment_id"], target["component_id"])
    return ("boundary", target["boundary_id"], target["card_slot_id"])


def _expected_execution_targets(
    *,
    span: Mapping[str, Any],
    chunk_start: int,
    chunk_end: int,
    segments_by_id: Mapping[str, Mapping[str, Any]],
    card_ids: set[str],
) -> dict[tuple[str, ...], dict[str, Any]]:
    expected: dict[tuple[str, ...], dict[str, Any]] = {}
    prefix = "hd-talking-head/talkcraft/"
    for segment_id in span["segment_ids"]:
        segment = segments_by_id[segment_id]
        segment_start = round(segment["start"] * 24)
        recipe = segment.get("shot_recipe")
        components = recipe.get("components", []) if type(recipe) is dict else []
        for component in components:
            if component.get("dependency_id") != DEPENDENCY_ID:
                continue
            template_id = component.get("template_id")
            if type(template_id) is not str or not template_id.startswith(prefix):
                _fail("TalkCraft component template_id is invalid")
            card_id = _identifier(template_id[len(prefix):], "TalkCraft component card_id")
            if card_id not in card_ids:
                _fail("TalkCraft component card_id is not registered")
            start = segment_start + component["render_window"]["start_frame"]
            end = segment_start + component["render_window"]["end_frame"]
            if max(start, chunk_start) >= min(end, chunk_end):
                continue
            target = {
                "kind": "component",
                "segment_id": segment_id,
                "component_id": component["component_id"],
                "card_id": card_id,
                "start_frame": start,
                "end_frame": end,
            }
            expected[_target_key(target)] = target
    for boundary in span["boundaries"]:
        if max(boundary["start_frame"], chunk_start) >= min(boundary["end_frame"], chunk_end):
            continue
        target = {
            "kind": "boundary",
            "boundary_id": boundary["boundary_id"],
            "card_slot_id": boundary["card_slot_id"],
            "card_id": boundary["card_id"],
            "start_frame": boundary["start_frame"],
            "end_frame": boundary["end_frame"],
        }
        expected[_target_key(target)] = target
    return expected


def validate_render_spans(
    value: object,
    *,
    segments: list[dict[str, Any]],
    duration_frames: int,
) -> list[dict[str, Any]]:
    """Validate complete, non-overlapping ownership of a v4 timeline."""

    if type(value) is not list or not value:
        _fail("render_spans must be a non-empty list")
    segment_ids = [segment["segment_id"] for segment in segments]
    segment_ranges = {
        segment["segment_id"]: (round(segment["start"] * 24), round(segment["end"] * 24))
        for segment in segments
    }
    segments_by_id = {segment["segment_id"]: segment for segment in segments}
    registry_cards = load_card_registry()["cards"]
    card_ids = {card["card_id"] for card in registry_cards}
    transition_cards = {
        card["card_id"]
        for card in registry_cards
        if card["production"]["production_role"] == "transition"
    }
    consumed: list[str] = []
    span_ids: set[str] = set()
    chunk_ids: set[str] = set()
    boundary_ids: set[str] = set()
    previous_span_end = 0
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        span = _exact(raw, _SPAN_KEYS, f"render_spans[{index}]")
        span_id = _identifier(span["span_id"], f"render_spans[{index}].span_id")
        if span_id in span_ids:
            _fail("span_id must be unique")
        span_ids.add(span_id)
        if span["mode"] not in {"isolated", "transition_chain", "world"}:
            _fail(f"render_spans[{index}].mode is invalid")
        members = span["segment_ids"]
        if type(members) is not list or not members:
            _fail("span segment_ids must be non-empty")
        for member in members:
            _identifier(member, "span segment_id")
        if len(members) != len(set(members)) or any(member not in segment_ranges for member in members):
            _fail("span segment_ids are invalid")
        positions = [segment_ids.index(member) for member in members]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            _fail("span members must be contiguous and ordered")
        start = _frame(span["start_frame"], f"render_spans[{index}].start_frame")
        end = _frame(span["end_frame"], f"render_spans[{index}].end_frame")
        if end <= start or start != previous_span_end:
            _fail("render spans must form one contiguous timeline")
        if (start, end) != (segment_ranges[members[0]][0], segment_ranges[members[-1]][1]):
            _fail("span frame range must equal its member segments")
        previous_span_end = end
        _sha(span["scene_brief_sha256"], f"render_spans[{index}].scene_brief_sha256")
        boundaries = span["boundaries"]
        expected_boundaries = max(0, len(members) - 1)
        if type(boundaries) is not list or len(boundaries) != (expected_boundaries if span["mode"] == "transition_chain" else 0):
            _fail("span boundaries do not match its mode and members")
        if span["mode"] == "isolated" and len(members) != 1:
            _fail("isolated span must own exactly one segment")
        if span["mode"] == "transition_chain" and len(members) < 2:
            _fail("transition_chain span must own at least two segments")
        for boundary_index, raw_boundary in enumerate(boundaries):
            boundary = _exact(raw_boundary, _BOUNDARY_KEYS, f"boundaries[{boundary_index}]")
            boundary_id = _identifier(boundary["boundary_id"], "boundary_id")
            if boundary_id in boundary_ids:
                _fail("boundary_id must be globally unique")
            boundary_ids.add(boundary_id)
            _identifier(boundary["card_slot_id"], "boundary.card_slot_id")
            if boundary["from_segment_id"] != members[boundary_index] or boundary["to_segment_id"] != members[boundary_index + 1]:
                _fail("boundary adjacency differs from span members")
            card_id = _identifier(boundary["card_id"], "boundary.card_id")
            if card_id not in transition_cards:
                _fail("boundary card_id must name a TalkCraft transition card")
            boundary_start = _frame(boundary["start_frame"], "boundary.start_frame")
            boundary_end = _frame(boundary["end_frame"], "boundary.end_frame")
            shared = segment_ranges[members[boundary_index]][1]
            crossed_edges = [
                segment_ranges[member][1]
                for member in members[:-1]
                if boundary_start < segment_ranges[member][1] < boundary_end
            ]
            if not (
                start <= boundary_start < shared < boundary_end <= end
                and crossed_edges == [shared]
            ):
                _fail("boundary window must straddle exactly one member edge")
        chunks = span["chunks"]
        if type(chunks) is not list or not chunks:
            _fail("span chunks must be non-empty")
        previous_chunk_end = start
        normalized_chunks: list[dict[str, Any]] = []
        for chunk_index, raw_chunk in enumerate(chunks):
            chunk = _exact(raw_chunk, _CHUNK_KEYS, f"chunks[{chunk_index}]")
            chunk_id = _identifier(chunk["chunk_id"], "chunk_id")
            if chunk_id in chunk_ids:
                _fail("chunk_id must be globally unique")
            chunk_ids.add(chunk_id)
            chunk_start = _frame(chunk["start_frame"], "chunk.start_frame")
            chunk_end = _frame(chunk["end_frame"], "chunk.end_frame")
            if chunk_start != previous_chunk_end or chunk_end <= chunk_start or chunk_end - chunk_start > MAX_CHUNK_FRAMES:
                _fail("chunks must cover the span contiguously in blocks of at most 720 frames")
            targets = chunk["execution_targets"]
            if type(targets) is not list:
                _fail("chunk.execution_targets must be a list")
            expected_targets = _expected_execution_targets(
                span=span,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                segments_by_id=segments_by_id,
                card_ids=card_ids,
            )
            seen_targets: set[tuple[str, ...]] = set()
            normalized_targets: list[dict[str, Any]] = []
            for target_index, raw_target in enumerate(targets):
                if type(raw_target) is not dict or raw_target.get("kind") not in {"component", "boundary"}:
                    _fail("chunk execution_target is invalid")
                target = _exact(
                    raw_target,
                    _COMPONENT_TARGET_KEYS if raw_target["kind"] == "component" else _BOUNDARY_TARGET_KEYS,
                    f"execution_targets[{target_index}]",
                )
                key = _target_key(target)
                if key in seen_targets:
                    _fail("chunk execution_target must be unique")
                seen_targets.add(key)
                if expected_targets.get(key) != target:
                    _fail("chunk execution_target differs from the approved span")
                normalized_targets.append(copy.deepcopy(target))
            if seen_targets != set(expected_targets):
                _fail("chunk execution_targets must cover every TalkCraft use")
            normalized_chunk = {**copy.deepcopy(chunk), "execution_targets": normalized_targets}
            if _sha(chunk["spec_sha256"], "chunk.spec_sha256") != chunk_spec_sha256(span_id, normalized_chunk):
                _fail("chunk spec_sha256 does not match its immutable range")
            previous_chunk_end = chunk_end
            normalized_chunks.append(normalized_chunk)
        if previous_chunk_end != end:
            _fail("chunks must cover the complete span")
        consumed.extend(members)
        normalized.append({**copy.deepcopy(span), "chunks": normalized_chunks})
    if previous_span_end != duration_frames or consumed != segment_ids:
        _fail("render spans must own every segment exactly once")
    return normalized


def select_span_chunk(request: SpanExecutionRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind an execution request to the approved plan/span/chunk identity."""

    if type(request) is not SpanExecutionRequest:
        _fail("SpanExecutionRequest is required")
    if type(request.visual_plan) is not dict or request.visual_plan.get("schema_version") != 4:
        _fail("span execution requires a VisualPlan v4")
    from .visual_plan import VisualPlanError, validate_visual_plan

    try:
        plan = validate_visual_plan(request.visual_plan)
    except VisualPlanError as error:
        raise RenderSpanError(str(error)) from None
    span = next((item for item in plan["render_spans"] if item.get("span_id") == request.span_id), None)
    if span is None:
        _fail("requested span is not in the approved plan")
    chunk = next((item for item in span.get("chunks", []) if item.get("chunk_id") == request.chunk_id), None)
    if chunk is None or chunk.get("spec_sha256") != chunk_spec_sha256(request.span_id, chunk):
        _fail("requested chunk identity is stale")
    return copy.deepcopy(span), copy.deepcopy(chunk)


def _job_file(job_dir: Path, record: object, label: str) -> Path:
    item = _exact(record, _FILE_KEYS, label)
    relative_text = item["job_path"]
    if type(relative_text) is not str or not relative_text:
        _fail(f"{label}.job_path must be a Job-relative path")
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or ".." in relative.parts or "://" in relative_text or "\\" in relative_text:
        _fail(f"{label}.job_path must be a Job-relative path")
    if not relative.parts or any(part in {"", "."} for part in relative.parts):
        _fail(f"{label}.job_path must be a Job-relative path")
    digest = _sha(item["sha256"], f"{label}.sha256")
    size = item["bytes"]
    if type(size) is not int or size < 1:
        _fail(f"{label}.bytes must be a positive integer")
    try:
        root = Path(job_dir).resolve(strict=True)
        directory_fd = os.open(
            root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        _fail(f"{label} is unavailable")
    file_fd: int | None = None
    try:
        for part in relative.parts[:-1]:
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
            relative.parts[-1],
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"{label} must be a regular file inside the Job")
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        visible = os.stat(
            relative.parts[-1], dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(visible.st_mode)
            or (visible.st_dev, visible.st_ino, visible.st_size, visible.st_mtime_ns)
            != (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
            or hasher.hexdigest() != digest
            or metadata.st_size != size
        ):
            _fail(f"{label} bytes changed")
    except RenderSpanError:
        raise
    except OSError:
        _fail(f"{label} is unavailable")
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    return root.joinpath(*relative.parts)


def validate_job_file(
    job_dir: Path, record: object, label: str = "artifact"
) -> Path:
    """Validate one Job-relative file with the same atomic replay boundary."""

    return _job_file(job_dir, record, label)


def _validate_component_artifacts(
    value: object,
    *,
    plan: Mapping[str, Any],
    span: Mapping[str, Any],
    chunk: Mapping[str, Any],
    job_dir: Path,
    brief_bundle: Mapping[str, Any],
) -> None:
    if type(value) is not list or not value:
        _fail("component_artifacts must be a non-empty list")
    seen: set[str] = set()
    seen_targets: set[tuple[str, ...]] = set()
    briefs_by_target = {
        _target_key(entry["brief"]["execution_target"]): entry
        for entry in brief_bundle["briefs"]
    }
    for index, raw in enumerate(value):
        wrapper = _exact(
            raw, _COMPONENT_WRAPPER_KEYS, f"component_artifacts[{index}]"
        )
        component_id = _identifier(
            wrapper["component_id"], f"component_artifacts[{index}].component_id"
        )
        if component_id in seen:
            _fail("component_artifact component_id must be unique")
        seen.add(component_id)
        target = wrapper["execution_target"]
        if type(target) is not dict or target.get("kind") not in {"component", "boundary"}:
            _fail("component_artifact execution_target is invalid")
        target = _exact(
            target,
            {"kind", "segment_id", "component_id"}
            if target["kind"] == "component"
            else {"kind", "boundary_id", "card_slot_id"},
            f"component_artifacts[{index}].execution_target",
        )
        target_key = _target_key(target)
        brief_entry = briefs_by_target.get(target_key)
        if target_key in seen_targets or brief_entry is None:
            _fail("component_artifact execution_target coverage is invalid")
        seen_targets.add(target_key)
        artifact = _exact(
            wrapper["artifact"],
            _COMPONENT_ARTIFACT_KEYS,
            f"component_artifacts[{index}].artifact",
        )
        window = artifact["render_window"]
        segment = next(
            (
                item
                for item in plan["segments"]
                if item["segment_id"] == artifact["segment_id"]
            ),
            None,
        )
        evidence = artifact["invocation_evidence"]
        chunk_frames = chunk["end_frame"] - chunk["start_frame"]
        if (
            type(artifact["schema_version"]) is not int
            or artifact["schema_version"] != 1
            or artifact["status"] != "success"
            or artifact["error_code"] is not None
            or artifact["component_id"] != component_id
            or artifact["segment_id"] not in span["segment_ids"]
            or target["kind"] == "component"
            and (
                target["segment_id"] != artifact["segment_id"]
                or target["component_id"] != component_id
            )
            or segment is None
            or round(segment["end"] * 24) <= chunk["start_frame"]
            or round(segment["start"] * 24) >= chunk["end_frame"]
            or type(artifact["job_id"]) is not str
            or not artifact["job_id"]
            or type(artifact["strategy_revision"]) is not int
            or type(window) is not dict
            or type(window.get("start_frame")) is not int
            or type(window.get("end_frame")) is not int
            or not 0 <= window["start_frame"] < window["end_frame"] <= chunk_frames
            or type(artifact["safe_zone"]) is not dict
            or type(artifact["artifact_contract"]) is not dict
            or type(artifact["media_probe"]) is not dict
            or type(evidence) is not dict
            or evidence.get("span_id") != span["span_id"]
            or evidence.get("chunk_id") != chunk["chunk_id"]
            or evidence.get("spec_sha256") != chunk["spec_sha256"]
            or evidence.get("production_brief_sha256") != brief_entry["brief_sha256"]
            or evidence.get("production_brief_bundle_sha256") != brief_bundle["bundle_sha256"]
            or evidence.get("output_job_path") != artifact["job_path"]
            or evidence.get("output_sha256") != artifact["output_sha256"]
            or type(artifact["qa"]) is not dict
            or set(artifact["qa"]) != {"passed", "checks"}
            or artifact["qa"].get("passed") is not True
            or type(artifact["qa"].get("checks")) is not list
            or not artifact["qa"]["checks"]
            or any(type(check) is not str or not check for check in artifact["qa"]["checks"])
        ):
            _fail("component_artifact does not satisfy ComponentArtifact")
        _sha(artifact["input_sha256"], "component_artifact.input_sha256")
        _job_file(
            job_dir,
            {
                "job_path": artifact["job_path"],
                "sha256": artifact["output_sha256"],
                "bytes": artifact["byte_count"],
            },
            f"component_artifacts[{index}].artifact",
        )
    if seen_targets != set(briefs_by_target):
        _fail("component_artifacts must cover every TalkCraft execution_target")


def validate_rendered_span_chunk(
    value: object,
    request: SpanExecutionRequest,
    production_brief_bundle: object,
    *,
    job_dir: Path,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    """Replay one final, silent span chunk only when every frozen identity matches."""

    rendered = _exact(value, _RENDERED_KEYS, "RenderedSpanChunk")
    if rendered["schema_version"] != "rendered-span-chunk/v1":
        _fail("unsupported RenderedSpanChunk schema")
    span, chunk = select_span_chunk(request)
    plan = request.visual_plan
    brief_bundle = validate_production_brief_bundle(
        production_brief_bundle,
        registry_path=registry_path,
    )
    bundle_sha = brief_bundle["bundle_sha256"]
    expected = {
        "visual_plan_sha256": plan["visual_plan_sha256"],
        "span_id": span["span_id"],
        "chunk_id": chunk["chunk_id"],
        "spec_sha256": chunk["spec_sha256"],
        "scene_brief_sha256": span["scene_brief_sha256"],
        "production_brief_bundle_sha256": bundle_sha,
        "frames": chunk["end_frame"] - chunk["start_frame"],
    }
    if any(rendered[field] != expected[field] for field in expected):
        _fail("RenderedSpanChunk differs from the approved plan or brief")
    owner = brief_bundle["owner"]
    if (
        owner != {
            "type": "span",
            "id": span["span_id"],
            "chunk_id": chunk["chunk_id"],
            "visual_plan_sha256": plan["visual_plan_sha256"],
            "spec_sha256": chunk["spec_sha256"],
            "scene_brief_sha256": span["scene_brief_sha256"],
        }
    ):
        _fail("production brief bundle does not own the requested span chunk")
    expected_targets = chunk["execution_targets"]
    actual_entries = brief_bundle["briefs"]
    if len(actual_entries) != len(expected_targets):
        _fail("production brief bundle does not cover the approved execution order")
    for entry, target in zip(actual_entries, expected_targets):
        brief = entry["brief"]
        scope = brief["frame_scope"]
        if (
            _target_key(brief["execution_target"]) != _target_key(target)
            or brief["card_id"] != target["card_id"]
            or (scope["global_start_frame"], scope["global_end_frame"])
            != (chunk["start_frame"], chunk["end_frame"])
            or (scope["span_start_frame"], scope["span_end_frame"])
            != (
                chunk["start_frame"] - span["start_frame"],
                chunk["end_frame"] - span["start_frame"],
            )
            or scope["scene_duration_frames"] != span["end_frame"] - span["start_frame"]
        ):
            _fail("production brief bundle differs from the approved execution order")
    _job_file(job_dir, rendered["video"], "video")
    probe = _exact(rendered["output_probe"], _PROBE_KEYS, "output_probe")
    frames = expected["frames"]
    if (
        type(probe["width"]) is not int
        or type(probe["height"]) is not int
        or type(probe["fps"]) is not int
        or type(probe["frame_count"]) is not int
        or type(probe["audio_streams"]) is not int
        or probe["container"] != "mp4"
        or probe["codec"] != "h264"
        or probe["pixel_format"] != "yuv420p"
        or probe["width"] != 1080
        or probe["height"] != 1920
        or probe["fps"] != 24
        or probe["frame_count"] != frames
        or type(probe["duration"]) not in {int, float}
        or abs(float(probe["duration"]) - frames / 24) > 1e-6
        or probe["audio_streams"] != 0
    ):
        _fail("RenderedSpanChunk output probe is invalid")
    keyframes = rendered["keyframes"]
    if type(keyframes) is not dict or set(keyframes) != {"entry", "hold", "exit"}:
        _fail("RenderedSpanChunk keyframes are invalid")
    previous_frame = -1
    for name in ("entry", "hold", "exit"):
        record = _exact(keyframes[name], _KEYFRAME_KEYS, f"keyframes.{name}")
        frame = _frame(record["frame"], f"keyframes.{name}.frame")
        if frame <= previous_frame or frame >= frames:
            _fail("RenderedSpanChunk keyframe order is invalid")
        previous_frame = frame
        _job_file(
            job_dir,
            {key: record[key] for key in _FILE_KEYS},
            f"keyframes.{name}",
        )
    renderer = _exact(rendered["renderer"], _RENDERER_KEYS, "renderer")
    brief_renderers = [entry["brief"]["render"] for entry in actual_entries]
    if (
        renderer["dependency_id"] != DEPENDENCY_ID
        or renderer["primary_renderer"] != PRIMARY_RENDERER
        or any(
            renderer[field] != brief_renderer[field]
            for brief_renderer in brief_renderers
            for field in {
                "entrypoint", "implementation_sha256", "adapter_version",
            }
        )
    ):
        _fail("RenderedSpanChunk renderer identity changed")
    _identifier(renderer["adapter_id"], "renderer.adapter_id")
    _validate_component_artifacts(
        rendered["component_artifacts"],
        plan=plan,
        span=span,
        chunk=chunk,
        job_dir=job_dir,
        brief_bundle=brief_bundle,
    )
    try:
        expected_identity = sha256_json(
            {key: copy.deepcopy(item) for key, item in rendered.items() if key != "render_identity"}
        )
    except (TypeError, ValueError):
        _fail("RenderedSpanChunk must contain finite JSON")
    if _sha(rendered["render_identity"], "render_identity") != expected_identity:
        _fail("RenderedSpanChunk render_identity changed")
    return copy.deepcopy(rendered)


__all__ = [
    "RenderSpanError", "SpanExecutionRequest", "chunk_spec_sha256",
    "validate_render_spans", "select_span_chunk", "validate_rendered_span_chunk",
    "validate_job_file",
]

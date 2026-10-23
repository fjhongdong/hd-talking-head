"""VisualPlan v4 canary contracts over complete, approved span chunks."""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import contract_artifacts, semantic_events, state, talkcraft_binding, visual_plan
from .render_span import (
    SpanExecutionRequest,
    validate_job_file,
    validate_rendered_span_chunk,
)
from .talkcraft_contract import DEFAULT_CARD_REGISTRY


MAX_CANARY_FRAMES = 720


class VisualSpanContractError(ValueError):
    pass


_PLAN_CHUNK_KEYS = {
    "span_id", "span_mode", "span_start_frame", "span_end_frame",
    "scene_brief_sha256", "chunk_id", "start_frame", "end_frame",
    "spec_sha256", "execution_targets",
}
_ASSEMBLY_KEYS = {
    "schema_version", "kind", "visual_plan_sha256", "chunks",
    "compositor", "output_audio_streams", "chunk_boundary_alpha",
    "assembly_spec_sha256",
}
_ASSEMBLY_CHUNK_KEYS = {
    "span_id", "chunk_id", "source_start_frame", "source_end_frame",
    "output_start_frame", "output_end_frame", "apply_span_entry_alpha",
    "apply_span_exit_alpha",
}
_APPROVAL_KEYS = {
    "job_id", "visual_plan_artifact_sha256",
    "production_brief_bundle_artifact_sha256",
    "production_brief_bundle_sha256", "registry_version", "registry_sha256",
}
_MANIFEST_KEYS = {
    "schema_version", "job_id", "visual_plan_sha256", "assembly_spec",
    "chunks", "track", "track_probe", "canary_sha256",
}
_MANIFEST_CHUNK_KEYS = {"span_id", "chunk_id", "visual_approval", "rendered"}
_FILE_KEYS = {"job_path", "sha256", "bytes"}
_TRACK_PROBE_KEYS = {
    "container", "codec", "pixel_format", "width", "height", "fps",
    "frame_count", "duration", "audio_streams",
}
_ASSETS_MANIFEST_KEYS = {
    "schema_version", "artifact_kind", "scope", "content_role", "job_id",
    "visual_plan_sha256", "chunks", "assets_sha256",
}
_ASSETS_CHUNK_KEYS = {
    "span_id", "chunk_id", "visual_approval", "rendered",
    "materialized_mp4", "source",
}
_ASSET_SOURCE_KEYS = {"kind", "manifest"}
_FRESH_SOURCE_KEYS = {"kind"}


def _fail(message: str) -> None:
    raise VisualSpanContractError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} fields are invalid")
    return value


def enumerate_plan_chunks(plan: object) -> list[dict[str, Any]]:
    """Return every v4 chunk exactly once in approved plan order."""

    try:
        checked = visual_plan.validate_visual_plan(plan)
    except visual_plan.VisualPlanError as error:
        raise VisualSpanContractError(str(error)) from None
    if checked["schema_version"] != 4:
        _fail("span chunk enumeration requires VisualPlan v4")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for span in checked["render_spans"]:
        for chunk in span["chunks"]:
            chunk_id = chunk["chunk_id"]
            if chunk_id in seen:
                _fail("chunk_id must be globally unique")
            seen.add(chunk_id)
            result.append({
                "span_id": span["span_id"],
                "span_mode": span["mode"],
                "span_start_frame": span["start_frame"],
                "span_end_frame": span["end_frame"],
                "scene_brief_sha256": span["scene_brief_sha256"],
                "chunk_id": chunk_id,
                "start_frame": chunk["start_frame"],
                "end_frame": chunk["end_frame"],
                "spec_sha256": chunk["spec_sha256"],
                "execution_targets": copy.deepcopy(chunk["execution_targets"]),
            })
    return result


def select_canary_chunks(
    plan: object,
    *,
    requested: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Select complete TalkCraft chunks in plan order within 720 frames."""

    eligible = [
        chunk for chunk in enumerate_plan_chunks(plan) if chunk["execution_targets"]
    ]
    if not eligible:
        _fail("VisualPlan v4 contains no TalkCraft execution chunk")
    by_id = {chunk["chunk_id"]: chunk for chunk in eligible}
    if requested is None:
        candidates = eligible
    else:
        if (
            type(requested) not in {list, tuple}
            or not requested
            or any(type(item) is not str for item in requested)
            or len(requested) != len(set(requested))
            or any(item not in by_id for item in requested)
        ):
            _fail("requested canary chunk ids are invalid")
        positions = [eligible.index(by_id[item]) for item in requested]
        if positions != sorted(positions):
            _fail("requested canary chunks must preserve plan order")
        candidates = [by_id[item] for item in requested]
    selected: list[dict[str, Any]] = []
    frames = 0
    for chunk in candidates:
        duration = chunk["end_frame"] - chunk["start_frame"]
        if frames + duration > MAX_CANARY_FRAMES:
            if requested is not None:
                _fail("requested canary chunks exceed 720 frames")
            break
        selected.append(copy.deepcopy(chunk))
        frames += duration
    if not selected:
        _fail("no complete TalkCraft chunk fits the canary")
    return selected


def build_assembly_spec(
    plan: object,
    chunks: Sequence[Mapping[str, Any]],
    *,
    kind: str = "canary",
) -> dict[str, Any]:
    try:
        checked = visual_plan.validate_visual_plan(plan)
    except visual_plan.VisualPlanError as error:
        raise VisualSpanContractError(str(error)) from None
    if checked["schema_version"] != 4 or kind not in {"canary", "assets"}:
        _fail("span assembly requires VisualPlan v4 and a supported kind")
    authoritative = enumerate_plan_chunks(checked)
    by_id = {chunk["chunk_id"]: chunk for chunk in authoritative}
    if type(chunks) not in {list, tuple} or not chunks:
        _fail("assembly chunks must be a non-empty ordered sequence")
    positions: list[int] = []
    normalized: list[dict[str, Any]] = []
    output_start = 0
    for index, raw in enumerate(chunks):
        chunk = _exact(raw, _PLAN_CHUNK_KEYS, f"chunks[{index}]")
        expected = by_id.get(chunk["chunk_id"])
        if expected != chunk:
            _fail("assembly chunk differs from the approved plan")
        positions.append(authoritative.index(expected))
        frames = chunk["end_frame"] - chunk["start_frame"]
        normalized.append({
            "span_id": chunk["span_id"],
            "chunk_id": chunk["chunk_id"],
            "source_start_frame": chunk["start_frame"],
            "source_end_frame": chunk["end_frame"],
            "output_start_frame": output_start,
            "output_end_frame": output_start + frames,
            "apply_span_entry_alpha": (
                chunk["start_frame"] == chunk["span_start_frame"]
            ),
            "apply_span_exit_alpha": (
                chunk["end_frame"] == chunk["span_end_frame"]
            ),
        })
        output_start += frames
    if positions != sorted(set(positions)):
        _fail("assembly chunks must be unique and preserve plan order")
    if kind == "assets" and positions != list(range(len(authoritative))):
        _fail("assets assembly must cover every plan chunk")
    unsigned = {
        "schema_version": "span-assembly-spec/v1",
        "kind": kind,
        "visual_plan_sha256": checked["visual_plan_sha256"],
        "chunks": normalized,
        "compositor": "ffmpeg-concat-silent-v1",
        "output_audio_streams": 0,
        "chunk_boundary_alpha": False,
    }
    return {
        **unsigned,
        "assembly_spec_sha256": contract_artifacts.sha256_json(unsigned),
    }


def _stable_approval(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(binding[key]) for key in _APPROVAL_KEYS}


def _track_probe(value: object, frames: int) -> dict[str, Any]:
    probe = _exact(value, _TRACK_PROBE_KEYS, "track_probe")
    if (
        probe["container"] != "mp4"
        or probe["codec"] != "h264"
        or probe["pixel_format"] != "yuv420p"
        or type(probe["width"]) is not int
        or type(probe["height"]) is not int
        or type(probe["fps"]) is not int
        or type(probe["frame_count"]) is not int
        or type(probe["audio_streams"]) is not int
        or probe["width"] != 1080
        or probe["height"] != 1920
        or probe["fps"] != 24
        or probe["frame_count"] != frames
        or type(probe["duration"]) not in {int, float}
        or not math.isfinite(float(probe["duration"]))
        or abs(float(probe["duration"]) - frames / 24) > 1e-6
        or probe["audio_streams"] != 0
    ):
        _fail("span canary track probe is invalid")
    return copy.deepcopy(probe)


def validate_canary_manifest(
    job: state.JobState,
    plan: object,
    manifest: object,
    *,
    brief_bundles: Mapping[str, object],
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    value = _exact(manifest, _MANIFEST_KEYS, "SpanCanaryManifest")
    if value["schema_version"] != "talkcraft-span-canary-manifest/v1":
        _fail("unsupported span canary manifest schema")
    try:
        checked_plan = visual_plan.validate_visual_plan(plan)
    except visual_plan.VisualPlanError as error:
        raise VisualSpanContractError(str(error)) from None
    if (
        value["job_id"] != job.job_id
        or value["visual_plan_sha256"] != checked_plan["visual_plan_sha256"]
    ):
        _fail("span canary manifest plan identity changed")
    event_plan = _optional_semantic_event_plan(job, checked_plan)
    chunks = value["chunks"]
    if type(chunks) is not list or not chunks:
        _fail("span canary manifest must contain chunks")
    requested: list[str] = []
    for index, raw in enumerate(chunks):
        item = _exact(raw, _MANIFEST_CHUNK_KEYS, f"chunks[{index}]")
        if type(item["chunk_id"]) is not str:
            _fail("span canary chunk id is invalid")
        requested.append(item["chunk_id"])
    selected = select_canary_chunks(
        checked_plan,
        requested=requested,
    )
    if len(chunks) != len(selected):
        _fail("span canary chunk count changed")
    expected_spec = build_assembly_spec(checked_plan, selected, kind="canary")
    if _exact(value["assembly_spec"], _ASSEMBLY_KEYS, "assembly_spec") != expected_spec:
        _fail("span canary assembly spec changed")
    normalized_chunks: list[dict[str, Any]] = []
    for index, (raw, expected_chunk) in enumerate(zip(chunks, selected)):
        item = _exact(raw, _MANIFEST_CHUNK_KEYS, f"chunks[{index}]")
        if (
            item["span_id"] != expected_chunk["span_id"]
            or item["chunk_id"] != expected_chunk["chunk_id"]
        ):
            _fail("span canary chunk order changed")
        bundle = brief_bundles.get(item["chunk_id"])
        if bundle is None:
            _fail("span canary brief bundle is missing")
        request = SpanExecutionRequest(
            checked_plan, item["span_id"], item["chunk_id"]
        )
        binding = talkcraft_binding.bind_approved_brief_bundle(
            job,
            request,
            bundle,
            registry_path=registry_path,
            semantic_event_plan=event_plan,
        )
        if _exact(item["visual_approval"], _APPROVAL_KEYS, "visual_approval") != _stable_approval(binding):
            _fail("span canary visual approval changed")
        rendered = validate_rendered_span_chunk(
            item["rendered"],
            request,
            bundle,
            job_dir=job.job_dir,
            registry_path=registry_path,
        )
        talkcraft_binding.revalidate_approved_binding(
            job.job_dir,
            request,
            bundle,
            binding,
            registry_path=registry_path,
            semantic_event_plan=event_plan,
        )
        normalized_chunks.append({
            "span_id": item["span_id"],
            "chunk_id": item["chunk_id"],
            "visual_approval": _stable_approval(binding),
            "rendered": rendered,
        })
    frames = sum(item["rendered"]["frames"] for item in normalized_chunks)
    if frames > MAX_CANARY_FRAMES:
        _fail("span canary exceeds 720 frames")
    track = _exact(value["track"], _FILE_KEYS, "track")
    validate_job_file(job.job_dir, track, "span canary track")
    normalized_probe = _track_probe(value["track_probe"], frames)
    unsigned = {
        "schema_version": "talkcraft-span-canary-manifest/v1",
        "job_id": job.job_id,
        "visual_plan_sha256": checked_plan["visual_plan_sha256"],
        "assembly_spec": expected_spec,
        "chunks": normalized_chunks,
        "track": copy.deepcopy(track),
        "track_probe": normalized_probe,
    }
    if value["canary_sha256"] != contract_artifacts.sha256_json(unsigned):
        _fail("span canary manifest identity changed")
    return {**unsigned, "canary_sha256": value["canary_sha256"]}


def _approved_stage_artifact(
    job: state.JobState,
    stage_id: str,
    supplied: object,
    *,
    required_path: str,
) -> dict[str, Any]:
    record = _exact(supplied, _FILE_KEYS, f"{stage_id} manifest reference")
    stage = job.stages.get(stage_id)
    if type(stage) is not dict or stage.get("status") != "approved":
        _fail(f"{stage_id} must be approved")
    matches = [
        item for item in stage.get("artifacts", [])
        if type(item) is dict and item.get("path") == required_path
    ]
    if len(matches) != 1 or record != {
        "job_path": matches[0].get("path"),
        "sha256": matches[0].get("sha256"),
        "bytes": matches[0].get("bytes"),
    }:
        _fail(f"{stage_id} manifest is not the approved artifact")
    validate_job_file(job.job_dir, record, f"approved {stage_id} manifest")
    return copy.deepcopy(record)


def _optional_semantic_event_plan(
    job: state.JobState,
    checked_plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Load the approved event plan when a visual direction publishes one."""

    stage = job.stages.get("visual_direction")
    if type(stage) is not dict:
        _fail("visual_direction stage is unavailable")
    matches = [
        item for item in stage.get("artifacts", [])
        if type(item) is dict
        and item.get("path") == "07-visual-direction/semantic-events.json"
    ]
    if not matches:
        return None
    if len(matches) != 1:
        _fail("semantic event plan artifact is ambiguous")
    record = {
        "job_path": matches[0].get("path"),
        "sha256": matches[0].get("sha256"),
        "bytes": matches[0].get("bytes"),
    }
    artifact_path = _approved_stage_artifact(
        job,
        "visual_direction",
        record,
        required_path="07-visual-direction/semantic-events.json",
    )
    try:
        payload = contract_artifacts.read_json_artifact(
            job.job_dir / artifact_path["job_path"]
        )
        return semantic_events.validate_semantic_event_plan(
            payload,
            visual_plan=checked_plan,
            expected_visual_plan_sha256=checked_plan["visual_plan_sha256"],
        )
    except (contract_artifacts.ContractArtifactError, semantic_events.SemanticEventError) as error:
        raise VisualSpanContractError(str(error)) from None


def _eligible_talkcraft_chunks(plan: object) -> list[dict[str, Any]]:
    return [
        chunk for chunk in enumerate_plan_chunks(plan)
        if chunk["execution_targets"]
    ]


def validate_chunk_assets_manifest(
    job: state.JobState,
    plan: object,
    manifest: object,
    *,
    approved_canary: object,
    brief_bundles: Mapping[str, object],
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    """Validate every TalkCraft chunk asset without claiming a full visual track."""

    value = _exact(
        manifest, _ASSETS_MANIFEST_KEYS, "TalkCraftChunkAssetsManifest"
    )
    if (
        value["schema_version"] != "talkcraft-chunk-assets-manifest/v1"
        or value["artifact_kind"] != "talkcraft_chunk_assets"
        or value["scope"] != "all_talkcraft_chunks_in_plan"
        or value["content_role"] != "final_composited_chunks"
    ):
        _fail("unsupported TalkCraft chunk assets manifest")
    try:
        current = state.load_job(job.job_dir)
        checked_plan = visual_plan.validate_visual_plan(plan)
    except (OSError, state.WorkflowError, visual_plan.VisualPlanError) as error:
        raise VisualSpanContractError(str(error)) from None
    if (
        current.job_id != job.job_id
        or checked_plan["schema_version"] != 4
        or value["job_id"] != current.job_id
        or value["visual_plan_sha256"] != checked_plan["visual_plan_sha256"]
    ):
        _fail("TalkCraft chunk assets plan identity changed")
    event_plan = _optional_semantic_event_plan(current, checked_plan)
    expected = _eligible_talkcraft_chunks(checked_plan)
    if not expected:
        _fail("VisualPlan v4 contains no TalkCraft chunk assets")
    chunks = value["chunks"]
    if type(chunks) is not list or len(chunks) != len(expected):
        _fail("TalkCraft chunk assets must cover every TalkCraft chunk")

    canary_value = _exact(
        approved_canary, _MANIFEST_KEYS, "approved SpanCanaryManifest"
    )
    canary_records = [
        item for item in current.stages["visual_canary"].get("artifacts", [])
        if type(item) is dict
        and item.get("path")
        == "08-visual-canary/talkcraft-span-canary-manifest.json"
    ]
    if len(canary_records) != 1:
        _fail("approved span canary manifest is unavailable")
    approved_canary_ref = {
        "job_path": canary_records[0].get("path"),
        "sha256": canary_records[0].get("sha256"),
        "bytes": canary_records[0].get("bytes"),
    }
    _approved_stage_artifact(
        current,
        "visual_canary",
        approved_canary_ref,
        required_path="08-visual-canary/talkcraft-span-canary-manifest.json",
    )
    if approved_canary_ref["sha256"] != contract_artifacts.sha256_json(
        canary_value
    ):
        _fail("approved span canary manifest identity changed")
    canary_value = validate_canary_manifest(
        current,
        checked_plan,
        canary_value,
        brief_bundles=brief_bundles,
        registry_path=registry_path,
    )
    canary_chunks = canary_value.get("chunks")
    if type(canary_chunks) is not list:
        _fail("approved span canary chunks are invalid")
    canary_by_id = {
        item.get("chunk_id"): item
        for item in canary_chunks
        if type(item) is dict and type(item.get("chunk_id")) is str
    }
    if len(canary_by_id) != len(canary_chunks):
        _fail("approved span canary chunks are invalid")

    normalized: list[dict[str, Any]] = []
    for index, (raw, expected_chunk) in enumerate(zip(chunks, expected)):
        item = _exact(raw, _ASSETS_CHUNK_KEYS, f"chunks[{index}]")
        if (
            item["span_id"] != expected_chunk["span_id"]
            or item["chunk_id"] != expected_chunk["chunk_id"]
        ):
            _fail("TalkCraft chunk assets changed order or coverage")
        bundle = brief_bundles.get(item["chunk_id"])
        if bundle is None:
            _fail("TalkCraft chunk asset brief bundle is missing")
        request = SpanExecutionRequest(
            checked_plan, item["span_id"], item["chunk_id"]
        )
        binding = talkcraft_binding.bind_approved_brief_bundle(
            current,
            request,
            bundle,
            registry_path=registry_path,
            semantic_event_plan=event_plan,
        )
        stable = _stable_approval(binding)
        if _exact(
            item["visual_approval"], _APPROVAL_KEYS, "visual_approval"
        ) != stable:
            _fail("TalkCraft chunk asset visual approval changed")
        rendered = validate_rendered_span_chunk(
            item["rendered"], request, bundle,
            job_dir=current.job_dir, registry_path=registry_path,
        )
        source = item["source"]
        if type(source) is not dict or type(source.get("kind")) is not str:
            _fail("TalkCraft chunk asset source is invalid")
        approved_chunk = canary_by_id.get(item["chunk_id"])
        if approved_chunk is not None:
            if source["kind"] != "approved_canary":
                _fail("approved canary chunk must be reused")
            source_value = _exact(
                source, _ASSET_SOURCE_KEYS, "approved_canary source"
            )
            canary_ref = _approved_stage_artifact(
                current,
                "visual_canary",
                source_value["manifest"],
                required_path=(
                    "08-visual-canary/talkcraft-span-canary-manifest.json"
                ),
            )
            if (
                canary_ref != approved_canary_ref
                or approved_chunk.get("span_id") != item["span_id"]
                or approved_chunk.get("visual_approval") != stable
                or approved_chunk.get("rendered") != rendered
            ):
                _fail("approved canary chunk identity changed")
        else:
            if source["kind"] == "approved_formal":
                _fail("cross-plan formal chunk reuse is not implemented")
            source_value = _exact(source, _FRESH_SOURCE_KEYS, "fresh source")
            if source_value["kind"] != "fresh":
                _fail("unsupported TalkCraft chunk asset source")
        materialized = _exact(
            item["materialized_mp4"], _FILE_KEYS, "materialized_mp4"
        )
        validate_job_file(current.job_dir, materialized, "materialized chunk")
        if (
            materialized["sha256"] != rendered["video"]["sha256"]
            or materialized["bytes"] != rendered["video"]["bytes"]
        ):
            _fail("materialized TalkCraft chunk is not an exact byte reuse")
        talkcraft_binding.revalidate_approved_binding(
            current.job_dir,
            request,
            bundle,
            binding,
            registry_path=registry_path,
            semantic_event_plan=event_plan,
        )
        normalized.append({
            "span_id": item["span_id"],
            "chunk_id": item["chunk_id"],
            "visual_approval": stable,
            "rendered": rendered,
            "materialized_mp4": copy.deepcopy(materialized),
            "source": copy.deepcopy(source_value),
        })
    unsigned = {
        "schema_version": "talkcraft-chunk-assets-manifest/v1",
        "artifact_kind": "talkcraft_chunk_assets",
        "scope": "all_talkcraft_chunks_in_plan",
        "content_role": "final_composited_chunks",
        "job_id": current.job_id,
        "visual_plan_sha256": checked_plan["visual_plan_sha256"],
        "chunks": normalized,
    }
    if value["assets_sha256"] != contract_artifacts.sha256_json(unsigned):
        _fail("TalkCraft chunk assets manifest identity changed")
    return {**unsigned, "assets_sha256": value["assets_sha256"]}


__all__ = [
    "MAX_CANARY_FRAMES", "VisualSpanContractError", "enumerate_plan_chunks",
    "select_canary_chunks", "build_assembly_spec", "validate_canary_manifest",
    "validate_chunk_assets_manifest", "_optional_semantic_event_plan",
]

"""Validate and publish schema-v3 semantic visual direction plans."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import secrets
import stat
import re
from pathlib import Path
from typing import Callable, Mapping

from . import (
    avatar_profile,
    broll_skill_selection,
    confirmed_content,
    content_analysis,
    contract_artifacts,
    material_usage,
    overlay_alignment,
    overlay_selection,
    segment_render,
    semantic_events,
    state as workflow_state,
)
from .state import JobState, block as _state_block, mark_ready, require_runnable
from .visual_strategy import (
    SOURCE_KINDS,
    VisualStrategyError,
    stable_same_kind_candidates,
    validate_shot_recipe_v2,
    validate_visual_intent,
    validate_visual_strategy,
)
from . import visual_coverage

__all__ = [
    "VisualPlanError",
    "parse_visual_brief_json",
    "validate_visual_plan",
    "block_visual_direction",
    "prepare_visual_direction",
]


class VisualPlanError(RuntimeError):
    """A safe, user-facing visual-direction failure."""


_SCHEMA_UNSUPPORTED = "BROLL_SCHEMA_UNSUPPORTED"
_PLAN_KEYS = {
    "schema_version",
    "content_analysis_sha256",
    "edit_plan_sha256",
    "timeline_map_sha256",
    "edited_aroll_sha256",
    "canvas",
    "duration",
    "segments",
    "source_summary",
    "visual_plan_sha256",
}
_PLAN_V4_KEYS = _PLAN_KEYS | {"render_spans"}
_PLAN_SEGMENT_KEYS = {
    "segment_id",
    "start",
    "end",
    "content_item_ids",
    "visible_text",
    "visual_intent",
    "visual_strategy",
    "candidate_snapshots",
    "bindings",
    "shot_recipe",
}
_DRAFT_KEYS = {"schema_version", "segments"}
_DRAFT_SEGMENT_KEYS = _PLAN_SEGMENT_KEYS - {"shot_recipe"} | {"strategy_revision"}
_MATERIAL_KINDS = {"local_material", "official_material", "external_stock"}
_RECIPE_COMMON_FIELDS = {
    "component_id",
    "kind",
    "semantic_role",
    "layer_role",
    "executor",
    "media_type",
    "render_window",
    "artifact_contract",
}
_SHA256_CHARS = frozenset("0123456789abcdef")
_CONTROL_CHARACTERS = frozenset(chr(value) for value in (*range(0x20), 0x7F))
_LOCK_NAME = ".visual-direction-v3.lock"
_JOURNAL_NAME = ".visual-direction-v3.transaction.json"
_PAYLOAD_FILES = (
    "visual-plan.json",
    "visual-routing.md",
    "material-usage.json",
)
_LEGACY_PAYLOAD_FILES = (
    "visual-plan.json",
    "visual-routing.md",
)
_EVENT_PAYLOAD_FILE = "semantic-events.json"
_JOURNAL_KEYS = {
    "schema_version",
    "generation_id",
    "job_id",
    "base_revision",
    "base_workflow_sha256",
    "new_manifest",
    "previous_manifest",
}

CandidateFreezer = Callable[[str, list[dict[str, object]]], dict[str, object]]
BindingFreezer = Callable[[str, dict[str, object]], dict[str, object]]
StrategyCompiler = Callable[[dict[str, object], dict[str, object]], dict[str, object]]
StateWriter = Callable[[JobState, str, tuple[Path, ...]], None]


def _fail(message: str = "visual direction operation failed") -> VisualPlanError:
    return VisualPlanError(message)


def _schema_gate(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 3
    ):
        raise _fail(_SCHEMA_UNSUPPORTED)
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _fail()


def _deepcopy(value: object, label: str) -> object:
    try:
        return copy.deepcopy(value)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail(f"{label} cannot be copied safely") from None


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise _fail(f"{label} must be non-empty text")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if any(character in _CONTROL_CHARACTERS for character in result):
        raise _fail(f"{label} must not contain control characters")
    return result


def _text_list(value: object, label: str, *, allow_empty: bool = True) -> list[str]:
    if type(value) is not list:
        raise _fail(f"{label} must be a list")
    result = [_text(item, f"{label} item") for item in value]
    if not allow_empty and not result:
        raise _fail(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise _fail(f"{label} must not contain duplicates")
    return result


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float}:
        raise _fail(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise _fail(f"{label} must be a finite positive number")
    return result


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _fail(f"{label} must be a positive integer")
    return value


def _segment_frames(start: float, end: float) -> int:
    duration = end - start
    frames = round(duration * 24)
    if frames < 1 or abs(frames / 24 - duration) > 1e-6:
        raise _fail("segment time range must align to the 24 fps clock")
    return frames


def _sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _SHA256_CHARS for character in value)
    ):
        raise _fail(f"{label} must be a lowercase sha256")
    return value


def _canvas(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"width", "height", "fps"}
        or type(value["width"]) is not int
        or value["width"] != 1080
        or type(value["height"]) is not int
        or value["height"] != 1920
        or type(value["fps"]) is not int
        or value["fps"] != 24
    ):
        raise _fail("canvas must be 1080x1920 at 24 fps")
    return dict(value)


def _component_index(strategy: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        component["component_id"]: component
        for component in strategy["components"]
    }


def _validate_candidate_snapshots(
    value: object,
    components: dict[str, dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    if type(value) is not dict:
        raise _fail("candidate_snapshots must be an object")
    expected = {
        component_id
        for component_id, component in components.items()
        if component["kind"] in _MATERIAL_KINDS
    }
    if set(value) != expected:
        raise _fail("candidate snapshots must match material component ids")
    result: dict[str, list[dict[str, object]]] = {}
    for component_id, candidates in value.items():
        kind = components[component_id]["kind"]
        try:
            result[component_id] = stable_same_kind_candidates(candidates, kind)
        except VisualStrategyError as error:
            raise _fail(str(error)) from None
    return result


def _validate_bindings(
    value: object,
    components: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if type(value) is not dict or set(value) != set(components):
        raise _fail("bindings must match approved component ids")
    result: dict[str, dict[str, object]] = {}
    for component_id, binding in value.items():
        if type(binding) is not dict:
            raise _fail(f"binding for {component_id} must be an object")
        result[component_id] = _deepcopy(binding, f"binding for {component_id}")
    try:
        contract_artifacts.canonical_json_bytes(result)
    except contract_artifacts.ContractArtifactError:
        raise _fail("bindings must be canonical JSON values") from None
    return result


def _prepared_video_binding(component_id, kind, media_type, binding):
    if not {"execution_mode", "source_dimensions"}.intersection(binding):
        return binding, None
    router = _load_router_module()
    try:
        checked = router._canonical_binding(binding, component_id)
        if checked.get("execution_mode") == "reuse_completed_generated_media":
            contract = router._consume_completed_generated_binding(kind, media_type, checked)
        else:
            contract = router._consume_completed_lovart_binding(kind, media_type, checked)
    except router.RouterError as error:
        raise _fail(str(error)) from None
    return checked, contract


def _prevalidate_draft_bindings(
    strategy: dict[str, object],
    bindings: dict[str, dict[str, object]],
    strategy_revision: int,
    segment_frames: int,
) -> None:
    """Use the ShotRecipe authority to reject binding shape before callbacks."""
    recipe_components = []
    components_by_id = {
        component["component_id"]: component for component in strategy["components"]
    }
    ordered_components = [
        components_by_id[component_id]
        for component_id in strategy["composition"]["reading_order"]
    ]
    for index, component in enumerate(ordered_components):
        component_id = component["component_id"]
        kind = component["kind"]
        binding, completed_contract = _prepared_video_binding(
            component_id, kind, component["media_type"], bindings[component_id]
        )
        riso_contract = None
        if binding.get("dependency_id") == "eian-riso-broll":
            router = _load_router_module()
            try:
                riso_contract = router.riso_output_contract(component, strategy["composition"])
            except router.RouterError as error:
                raise _fail(str(error)) from None
        recipe_components.append(
            {
                "component_id": component_id,
                "kind": kind,
                "semantic_role": component["semantic_role"],
                "layer_role": component["layer_role"],
                "executor": (
                    ("generated_media" if bindings[component_id].get("execution_mode") == "reuse_completed_generated_media" else "lovart_existing_video")
                    if completed_contract is not None
                    else
                    "reference_adapter"
                    if binding.get("dependency_id") in {
                        "hd-talking-head-relation-motion",
                        "hd-talking-head-semantic-state",
                        "doudou-remotion-whiteboard",
                        "talkcraft-native-adaptation",
                        "hyperframes-native-adaptation",
                        "paper-collage-hyperframes",
                        "lemo-opuscar",
                        "onetake",
                        "adu-motion-video",
                        "wise-motion",
                        "openfilm-motion-graphics",
                        "eian-riso-broll",
                        "overlay-studio-native",
                        "motion-graphics-native",
                        "whiteboard-video",
                    }
                    else "prevalidation-only"
                ),
                "media_type": component["media_type"],
                "render_window": {
                    "start_frame": 0,
                    "end_frame": segment_frames,
                    "z_index": index * 10,
                    "layout_slot": component["layout_slot"],
                    "opacity": 1.0,
                    "safe_zone": {
                        "top": 64 if strategy["composition"]["family"] == "aroll_with_overlay" else 120,
                        "bottom": 320,
                        "left": 40,
                        "right": 40,
                    },
                },
                "artifact_contract": riso_contract or completed_contract or {
                    "width": 1080,
                    "height": 1920,
                    "fps": 24,
                    "alpha": kind == "code_generated"
                    and binding.get("dependency_id") not in {
                        "hd-talking-head-talkcraft",
                        "hd-talking-head-relation-motion",
                        "hd-talking-head-semantic-state",
                        "paper-collage-ad",
                        "paper-collage-hyperframes",
                        "doudou-remotion-whiteboard",
                        "talkcraft-native-adaptation",
                        "lemo-opuscar",
                        "onetake",
                        "adu-motion-video",
                        "wise-motion",
                        "openfilm-motion-graphics",
                        "whiteboard-video",
                    }
                    and (binding.get("dependency_id") not in {"hyperframes-native-adaptation", "paper-collage-hyperframes"}
                         or strategy["composition"]["family"] == "aroll_with_overlay"),
                },
                **binding,
            }
        )
    try:
        validate_shot_recipe_v2(
            {
                "schema_version": 2,
                "segment_id": strategy["segment_id"],
                "strategy_revision": strategy_revision,
                "mode": strategy["mode"],
                "composition": strategy["composition"],
                "canvas": {"width": 1080, "height": 1920, "fps": 24},
                "components": recipe_components,
                "final_compositor": "ffmpeg",
            }
        )
    except VisualStrategyError as error:
        raise _fail(str(error)) from None


def _validate_cross_binding_identity(
    strategy: dict[str, object],
    bindings: dict[str, dict[str, object]],
    candidate_snapshots: dict[str, list[dict[str, object]]],
    *,
    segment_id: str,
    qualification_context: Mapping[str, object] | None = None,
) -> None:
    if qualification_context is not None:
        required = {"segment_id", "component_id", "dependency_id", "template_id", "recipe_sha256", "qualification_registry"}
        if set(qualification_context) != required:
            raise _fail("qualification context fields are invalid")
        if qualification_context.get("segment_id") != segment_id:
            raise _fail("qualification context target segment is missing")
        target_id = qualification_context.get("component_id")
        if target_id not in {component["component_id"] for component in strategy["components"]}:
            raise _fail("qualification context target component is missing")
    identity_fields = {
        "local_material": "material_id",
        "official_material": "source_id",
        "external_stock": "provider_asset_id",
    }
    for component in strategy["components"]:
        component_id = component["component_id"]
        kind = component["kind"]
        binding = bindings[component_id]
        if kind == "code_generated":
            registry = None
            if qualification_context and qualification_context.get("component_id") == component_id:
                for field in ("dependency_id", "template_id"):
                    if binding.get(field) != qualification_context.get(field):
                        raise _fail("qualification context does not match invocation")
                registry = qualification_context.get("qualification_registry")
            _canonical_validate_invocation_evidence(binding, qualification_registry=registry)
        elif qualification_context and qualification_context.get("component_id") == component_id:
            raise _fail("qualification context target must be code_generated")
        if kind in identity_fields:
            selected_id = candidate_snapshots[component_id][0]["asset_id"]
            if binding.get(identity_fields[kind]) != selected_id:
                raise _fail("material binding does not match its canonical candidate")


def _validate_semantic_segment(
    segment: object,
    *,
    draft: bool,
    qualification_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    expected_keys = _DRAFT_SEGMENT_KEYS if draft else _PLAN_SEGMENT_KEYS
    if type(segment) is not dict or set(segment) != expected_keys:
        raise _fail("visual segment fields are invalid")
    segment_id = _identifier(segment["segment_id"], "segment_id")
    if not segment_render.re_full_segment_id(segment_id):
        raise _fail("segment_id is not renderable")
    start = _number(segment["start"], "segment start")
    end = _number(segment["end"], "segment end")
    if start < 0 or end <= start:
        raise _fail("segment time range is invalid")
    segment_frames = _segment_frames(start, end)
    visible_text = _text_list(segment["visible_text"], "visible_text")
    try:
        intent = validate_visual_intent(segment["visual_intent"])
        strategy = validate_visual_strategy(intent, segment["visual_strategy"])
    except VisualStrategyError as error:
        raise _fail(str(error)) from None
    composition = strategy["composition"]
    base_unenhanced = (
        strategy["mode"] == "none"
        and composition["family"] == "no_broll"
        and not visible_text
    )
    content_item_ids = _text_list(
        segment["content_item_ids"], "content_item_ids", allow_empty=base_unenhanced
    )
    _identifier(intent["segment_id"], "visual intent segment_id")
    _identifier(strategy["segment_id"], "visual strategy segment_id")
    for component in strategy["components"]:
        _identifier(component["component_id"], "visual strategy component_id")
    if intent["segment_id"] != segment_id or strategy["segment_id"] != segment_id:
        raise _fail("semantic contracts must match their visual segment")
    components = _component_index(strategy)
    candidate_snapshots = _validate_candidate_snapshots(
        segment["candidate_snapshots"], components
    )
    bindings = _validate_bindings(segment["bindings"], components)
    _validate_cross_binding_identity(strategy, bindings, candidate_snapshots, segment_id=segment_id, qualification_context=qualification_context)
    normalized = {
        "segment_id": segment_id,
        "start": start,
        "end": end,
        "content_item_ids": content_item_ids,
        "visible_text": visible_text,
        "visual_intent": intent,
        "visual_strategy": strategy,
        "candidate_snapshots": candidate_snapshots,
        "bindings": bindings,
    }
    if draft:
        strategy_revision = _positive_integer(
            segment["strategy_revision"], "strategy_revision"
        )
        _prevalidate_draft_bindings(
            strategy,
            bindings,
            strategy_revision,
            segment_frames,
        )
        normalized["strategy_revision"] = strategy_revision
        return normalized

    try:
        recipe = validate_shot_recipe_v2(segment["shot_recipe"])
    except VisualStrategyError as error:
        raise _fail(str(error)) from None
    _identifier(recipe["segment_id"], "shot recipe segment_id")
    for component in recipe["components"]:
        _identifier(component["component_id"], "shot recipe component_id")
        if component["render_window"]["end_frame"] > segment_frames:
            raise _fail("shot recipe exceeds the segment frame range")
    strategy_by_id = {
        component["component_id"]: component for component in strategy["components"]
    }
    approved_components = [
        strategy_by_id[component_id]
        for component_id in strategy["composition"]["reading_order"]
    ]
    if (
        recipe["segment_id"] != segment_id
        or recipe["mode"] != strategy["mode"]
        or recipe["composition"] != strategy["composition"]
        or [item["component_id"] for item in recipe["components"]]
        != strategy["composition"]["reading_order"]
    ):
        raise _fail("shot recipe does not match the approved semantic strategy")
    for approved, compiled in zip(approved_components, recipe["components"]):
        if (
            compiled["kind"] != approved["kind"]
            or compiled["semantic_role"] != approved["semantic_role"]
            or compiled["layer_role"] != approved["layer_role"]
            or compiled["media_type"] != approved["media_type"]
            or compiled["render_window"]["layout_slot"] != approved["layout_slot"]
        ):
            raise _fail("shot recipe component changed the approved strategy")
        recipe_binding = {
            key: value
            for key, value in compiled.items()
            if key not in _RECIPE_COMMON_FIELDS
        }
        expected_binding, completed_contract = _prepared_video_binding(
            approved["component_id"], approved["kind"], approved["media_type"],
            bindings[approved["component_id"]],
        )
        if recipe_binding != expected_binding or (
            completed_contract is not None and (
                compiled["executor"] != ("generated_media" if bindings[approved["component_id"]].get("execution_mode") == "reuse_completed_generated_media" else "lovart_existing_video")
                or compiled["artifact_contract"] != completed_contract
            )
        ):
            raise _fail("shot recipe binding changed after approval")
    normalized["shot_recipe"] = recipe
    return normalized


def _validate_draft(value: object) -> dict[str, object]:
    draft = _schema_gate(value)
    if set(draft) != _DRAFT_KEYS or type(draft["segments"]) is not list or not draft["segments"]:
        raise _fail("visual direction draft fields are invalid")
    segments = [
        _validate_semantic_segment(segment, draft=True)
        for segment in draft["segments"]
    ]
    segment_ids = [segment["segment_id"] for segment in segments]
    if len(segment_ids) != len(set(segment_ids)):
        raise _fail("segment_id must be unique")
    try:
        avatar_profile.validate_plan_avatars(segments)
    except (ValueError, OSError) as error:
        raise _fail(str(error)) from None
    return {"schema_version": 3, "segments": segments}


def parse_visual_brief_json(source: str) -> dict[str, object]:
    """Parse and purely validate a schema-v3 semantic direction draft."""
    try:
        if type(source) is not str:
            raise _fail()
        payload = json.loads(
            source,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
        return _validate_draft(payload)
    except VisualPlanError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail() from None


def _source_summary(segments: list[dict[str, object]]) -> dict[str, int]:
    counts = {kind: 0 for kind in SOURCE_KINDS}
    for segment in segments:
        for component in segment["visual_strategy"]["components"]:
            counts[component["kind"]] += 1
    return {kind: counts[kind] for kind in SOURCE_KINDS if counts[kind]}


def validate_visual_plan(plan: object, *, qualification_context: Mapping[str, object] | None = None) -> dict[str, object]:
    """Strictly validate VisualPlan v3 or the span-aware v4 contract."""
    if (
        type(plan) is not dict
        or type(plan.get("schema_version")) is not int
        or plan.get("schema_version") not in {3, 4}
    ):
        raise _fail(_SCHEMA_UNSUPPORTED)
    checked = plan
    schema_version = checked["schema_version"]
    try:
        if set(checked) != (_PLAN_KEYS if schema_version == 3 else _PLAN_V4_KEYS):
            raise _fail("visual plan fields are invalid")
        for field in (
            "content_analysis_sha256",
            "edit_plan_sha256",
            "timeline_map_sha256",
            "edited_aroll_sha256",
        ):
            _sha256(checked[field], field)
        canvas = _canvas(checked["canvas"])
        duration = _number(checked["duration"], "duration", positive=True)
        if type(checked["segments"]) is not list or not checked["segments"]:
            raise _fail("segments must be a non-empty list")
        if qualification_context is not None:
            required = {"segment_id", "component_id", "dependency_id", "template_id", "recipe_sha256", "qualification_registry"}
            if set(qualification_context) != required:
                raise _fail("qualification context fields are invalid")
            targets = [s for s in checked["segments"] if isinstance(s, dict) and s.get("segment_id") == qualification_context.get("segment_id")]
            if len(targets) != 1 or contract_artifacts.sha256_json(targets[0]["shot_recipe"]) != qualification_context.get("recipe_sha256"):
                raise _fail("qualification context target or recipe is invalid")
        segments = [
            _validate_semantic_segment(segment, draft=False, qualification_context=(qualification_context if qualification_context and isinstance(segment, dict) and segment.get("segment_id") == qualification_context.get("segment_id") else None))
            for segment in checked["segments"]
        ]
        segment_ids = [segment["segment_id"] for segment in segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise _fail("segment_id must be unique")
        try:
            avatar_profile.validate_plan_avatars(segments, source_sha256=checked["edited_aroll_sha256"])
        except (ValueError, OSError) as error:
            raise _fail(str(error)) from None
        previous_end = 0.0
        for segment in segments:
            if abs(segment["start"] - previous_end) > 1e-6:
                raise _fail("segments must form one contiguous timeline")
            previous_end = segment["end"]
        if abs(previous_end - duration) > 1e-6:
            raise _fail("segments must cover the complete duration")
        expected_summary = _source_summary(segments)
        summary = checked["source_summary"]
        if (
            type(summary) is not dict
            or any(
                type(kind) is not str
                or kind not in SOURCE_KINDS
                or type(count) is not int
                or count < 1
                for kind, count in summary.items()
            )
            or summary != expected_summary
        ):
            raise _fail("source_summary must aggregate actual component kinds")
        normalized = {
            "schema_version": schema_version,
            "content_analysis_sha256": checked["content_analysis_sha256"],
            "edit_plan_sha256": checked["edit_plan_sha256"],
            "timeline_map_sha256": checked["timeline_map_sha256"],
            "edited_aroll_sha256": checked["edited_aroll_sha256"],
            "canvas": canvas,
            "duration": duration,
            "segments": segments,
            "source_summary": expected_summary,
        }
        if schema_version == 4:
            from .render_span import RenderSpanError, validate_render_spans

            try:
                normalized["render_spans"] = validate_render_spans(
                    checked["render_spans"],
                    segments=segments,
                    duration_frames=round(duration * 24),
                )
            except RenderSpanError as error:
                raise _fail(str(error)) from None
        _sha256(checked["visual_plan_sha256"], "visual_plan_sha256")
        expected_identity = contract_artifacts.sha256_json(normalized)
        if checked["visual_plan_sha256"] != expected_identity:
            raise _fail("visual_plan_sha256 does not match the canonical plan")
        normalized["visual_plan_sha256"] = expected_identity
        return _deepcopy(normalized, "visual plan")
    except VisualPlanError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail() from None


def block_visual_direction(job: JobState, reason: str) -> None:
    """Block visual direction without consuming an AI attempt."""
    try:
        _text(reason, "reason")
        if any(character in _CONTROL_CHARACTERS for character in reason):
            raise _fail("reason must not contain control characters")
        _state_block(job, "visual_direction", reason, ai_attempts=0)
    except VisualPlanError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail() from None


def _approved_artifact(job: JobState, stage_id: str, relative: str) -> Path:
    stage = job.stages.get(stage_id)
    if type(stage) is not dict or stage.get("status") != "approved":
        raise _fail(f"{stage_id} must be approved")
    records = [
        record
        for record in stage.get("artifacts", [])
        if type(record) is dict and record.get("path") == relative
    ]
    if len(records) != 1:
        raise _fail(f"{relative} must have one approved artifact record")
    path = job.job_dir / relative
    try:
        if (
            contract_artifacts.sha256_file(path) != records[0].get("sha256")
            or path.stat().st_size != records[0].get("bytes")
        ):
            raise _fail(f"{relative} identity changed")
    except OSError:
        raise _fail(f"{relative} identity changed") from None
    return path


def _load_router_module():
    router_path = (
        Path(__file__).resolve().parents[3]
        / "skill-development/hd-talking-head/scripts/broll_capability_router.py"
    )
    specification = importlib.util.spec_from_file_location(
        "hd_talking_head_broll_capability_router", router_path
    )
    if specification is None or specification.loader is None:
        raise _fail("B-roll capability router is unavailable")
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("B-roll capability router is unavailable") from None
    return module


def _canonical_freeze_candidate(
    kind: str, candidates: list[dict[str, object]]
) -> dict[str, object]:
    try:
        return _load_router_module().freeze_candidate(kind, candidates)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail(str(failure)) from None


def _canonical_compile_strategy(
    strategy: dict[str, object], context: dict[str, object]
) -> dict[str, object]:
    try:
        return _load_router_module().compile_strategy(strategy, context)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail(str(failure)) from None


def _canonical_validate_invocation_evidence(
    binding: dict[str, object],
    *,
    qualification_registry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    try:
        return _load_router_module().validate_invocation_evidence(binding, qualification_registry=qualification_registry)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail(str(failure)) from None


def _identity_binding_freezer(
    _kind: str, binding: dict[str, object]
) -> dict[str, object]:
    return _deepcopy(binding, "approved binding")


def _assert_recipe_matches_approved_strategy(
    segment: dict[str, object], recipe: dict[str, object]
) -> None:
    strategy = segment["visual_strategy"]
    strategy_by_id = {
        component["component_id"]: component for component in strategy["components"]
    }
    approved_components = [
        strategy_by_id[component_id]
        for component_id in strategy["composition"]["reading_order"]
    ]
    if (
        recipe["segment_id"] != segment["segment_id"]
        or recipe["strategy_revision"] != segment["strategy_revision"]
        or recipe["mode"] != strategy["mode"]
        or recipe["composition"] != strategy["composition"]
        or len(recipe["components"]) != len(strategy["components"])
    ):
        raise _fail("compiled recipe changed the approved strategy identity")
    for approved, compiled in zip(approved_components, recipe["components"]):
        if (
            compiled["component_id"] != approved["component_id"]
            or compiled["kind"] != approved["kind"]
            or compiled["semantic_role"] != approved["semantic_role"]
            or compiled["layer_role"] != approved["layer_role"]
            or compiled["media_type"] != approved["media_type"]
            or compiled["render_window"]["layout_slot"]
            != approved["layout_slot"]
        ):
            raise _fail("compiled recipe changed an approved component")


def _freeze_and_compile_segment(
    segment: dict[str, object],
    *,
    candidate_freezers: Mapping[str, CandidateFreezer],
    binding_freezers: Mapping[str, BindingFreezer],
    strategy_compiler: StrategyCompiler,
) -> dict[str, object]:
    strategy = segment["visual_strategy"]
    segment_frames = _segment_frames(segment["start"], segment["end"])
    frozen_snapshots: dict[str, list[dict[str, object]]] = {}
    frozen_bindings: dict[str, dict[str, object]] = {}
    for component in strategy["components"]:
        component_id = component["component_id"]
        kind = component["kind"]
        if kind in _MATERIAL_KINDS:
            ranked = segment["candidate_snapshots"][component_id]
            freezer = candidate_freezers.get(kind, _canonical_freeze_candidate)
            selected = freezer(kind, _deepcopy(ranked, "candidate snapshot"))
            if type(selected) is not dict or selected != ranked[0]:
                raise _fail("candidate freezer changed the canonical same-kind selection")
            frozen_snapshots[component_id] = _deepcopy(ranked, "candidate snapshot")
        freezer = binding_freezers.get(kind, _identity_binding_freezer)
        binding = freezer(
            kind,
            _deepcopy(segment["bindings"][component_id], "binding"),
        )
        if type(binding) is not dict:
            raise _fail("binding freezer must return an object")
        frozen_bindings[component_id] = _deepcopy(binding, "frozen binding")
    context = {
        "intent": segment["visual_intent"],
        "candidate_snapshots": frozen_snapshots,
        "bindings": frozen_bindings,
        "strategy_revision": segment["strategy_revision"],
        "segment_frames": segment_frames,
    }
    recipe = strategy_compiler(
        _deepcopy(strategy, "visual strategy"),
        _deepcopy(context, "compile context"),
    )
    try:
        recipe = validate_shot_recipe_v2(recipe)
    except VisualStrategyError as error:
        raise _fail(str(error)) from None
    if any(
        component["render_window"]["start_frame"] != 0
        or component["render_window"]["end_frame"] != segment_frames
        for component in recipe["components"]
    ):
        raise _fail("compiled recipe does not cover the complete segment")
    _assert_recipe_matches_approved_strategy(segment, recipe)
    return {
        key: _deepcopy(value, key)
        for key, value in segment.items()
        if key != "strategy_revision"
    } | {
        "candidate_snapshots": frozen_snapshots,
        "bindings": frozen_bindings,
        "shot_recipe": recipe,
    }


def _validate_reviewed_visual_text(
    value: Mapping[str, object] | None,
    *,
    analysis_record: Mapping[str, object],
    segments: list[dict[str, object]],
) -> list[dict[str, str]]:
    if value is None:
        return []
    if type(value) is not dict or set(value) != {"content_analysis_sha256", "entries"}:
        raise _fail("reviewed visual text envelope is invalid")
    if value["content_analysis_sha256"] != analysis_record["analysis_sha256"]:
        raise _fail("reviewed visual text analysis hash is stale")
    entries = value["entries"]
    if type(entries) is not list:
        raise _fail("reviewed visual text entries must be a list")
    by_segment = {segment["segment_id"]: segment for segment in segments}
    items = {item["id"]: item for item in analysis_record["analysis"]["items"]}
    thesis = analysis_record["analysis"]["thesis"]
    checked: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"segment_id", "text", "source_ref", "source_quote", "reason"}:
            raise _fail("reviewed visual text entry is invalid")
        segment_id = _identifier(entry["segment_id"], "reviewed segment_id")
        text = _text(entry["text"], "reviewed text")
        source_ref = _text(entry["source_ref"], "reviewed source_ref")
        source_quote = _text(entry["source_quote"], "reviewed source_quote")
        reason = _text(entry["reason"], "reviewed reason")
        segment = by_segment.get(segment_id)
        if segment is None or text not in segment["visible_text"]:
            raise _fail("reviewed text is not visible in its segment")
        if source_ref == "thesis":
            expected_quote = thesis
        elif source_ref.startswith("item:") and source_ref[5:] in items:
            item_id = source_ref[5:]
            if item_id not in segment["content_item_ids"]:
                raise _fail("reviewed source item is not selected by its segment")
            expected_quote = items[item_id]["source_text"]
        else:
            raise _fail("reviewed source_ref is unknown")
        if source_quote != expected_quote:
            raise _fail("reviewed source_quote does not match approved content")
        if set(re.findall(r"[A-Za-z0-9]+", text)) - set(re.findall(r"[A-Za-z0-9]+", source_quote)):
            raise _fail("reviewed text introduces unapproved foreign text or numbers")
        key = (segment_id, text, source_ref)
        if key in seen:
            raise _fail("reviewed visual text entry is duplicated")
        seen.add(key)
        checked.append({key: entry[key] for key in ("segment_id", "text", "source_ref", "source_quote", "reason")})
    return checked


def _require_visual_preparation(job):
    if job.stages["visual_direction"]["status"] == "ready_for_review":
        from .visual_confirmation import validate_visual_authorization
        validate_visual_authorization(job)
    else:
        require_runnable(job, "visual_direction")


def _validate_job_context(
    job: JobState,
    draft: dict[str, object],
    reviewed_visual_text: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path, Path, dict[str, object], float, list[dict[str, str]]]:
    _require_visual_preparation(job)
    analysis_record = content_analysis.load_approved_content_analysis(job)
    edit_path = _approved_artifact(
        job, "edit_structure", "06-edit-structure/edit-plan.json"
    )
    timeline_path = _approved_artifact(
        job, "edit_structure", "06-edit-structure/timeline-map.json"
    )
    edited_path = _approved_artifact(
        job, "edit_structure", "06-edit-structure/edited-aroll.mp4"
    )
    try:
        edit_payload = contract_artifacts.read_json_artifact(edit_path)
        timeline_payload = contract_artifacts.read_json_artifact(timeline_path)
    except contract_artifacts.ContractArtifactError:
        raise _fail() from None
    canvas = _canvas(edit_payload.get("canvas"))
    duration = _number(
        timeline_payload.get("output_duration"), "output_duration", positive=True
    )
    items = {
        item["id"]: item
        for item in analysis_record["analysis"]["items"]
    }
    previous_end = 0.0
    for segment in draft["segments"]:
        if abs(segment["start"] - previous_end) > 1e-6:
            raise _fail("segments must form one contiguous timeline")
        previous_end = segment["end"]
        if any(item_id not in items for item_id in segment["content_item_ids"]):
            raise _fail("segment references an unknown content item")
        selected_items = [items[item_id] for item_id in segment["content_item_ids"]]
        if any(item["evidence_status"] == "unsupported" for item in selected_items):
            raise _fail("segment references unsupported content")
        allowed_text = {
            text
            for item in selected_items
            for text in (item["source_text"], *item["keywords"])
        }
        if any(
            text not in allowed_text
            and not any(text in item["source_text"] for item in selected_items)
            for text in segment["visible_text"]
        ):
            reviewed = _validate_reviewed_visual_text(
                reviewed_visual_text, analysis_record=analysis_record, segments=draft["segments"]
            )
            reviewed_text = {entry["text"] for entry in reviewed if entry["segment_id"] == segment["segment_id"]}
            if any(text not in reviewed_text for text in segment["visible_text"] if text not in allowed_text and not any(text in item["source_text"] for item in selected_items)):
                raise _fail("visible text is not grounded in approved content")
    if abs(previous_end - duration) > 1e-6:
        raise _fail("segments must cover the complete edited duration")
    reviewed = _validate_reviewed_visual_text(
        reviewed_visual_text, analysis_record=analysis_record, segments=draft["segments"]
    )
    return analysis_record, edit_path, timeline_path, edited_path, canvas, duration, reviewed


def _review_text(plan: dict[str, object], reviewed_visual_text: list[dict[str, str]] | None = None,
                 skill_selection: dict[str, object] | None = None,
                 overlay_alignment_report: list[dict] | None = None,
                 overlay_selection_report: list[dict] | None = None,
                 numbering: dict[str, int] | None = None) -> str:
    lines = [
        "# 本视频贴片与 B-roll 总表",
        "",
        "时间统一为剪后正文时间，不含封面入场。确认整张表后，按表制作并直接交付成片。",
        "",
    ]
    if skill_selection is not None:
        def cell(value):
            return str(value).replace("|", "／").replace("\n", "<br>")

        queries = {(q.get("segment_id"), q.get("component_id")): q
                   for q in (skill_selection.get("motion_queries") or [])}
        motion_review = skill_selection.get("motion_review") or {}
        checks = {(c.get("segment_id"), c.get("component_id")): c
                  for c in motion_review.get("checks", [])}
        ordered = sorted(plan["segments"], key=lambda s: (s["start"], s["segment_id"]))
        if numbering is None:
            from .visual_confirmation import number_visual_rows
            numbering = {row["row_id"]: row["number"] for row in number_visual_rows([
                {"row_id": segment["segment_id"] + ":" + component["component_id"]}
                for segment in ordered for component in segment["visual_strategy"]["components"]])}
        lines.extend(["## 贴片与 B-roll 完整清单（用户确认）", "", "| 编号 | 时间 | 类型 | 剪后原话 | 语义 | 检索标签 | 具体动效模板/素材来源 |", "|---|---|---|---|---|---|---|"])
        for segment in ordered:
            for component in segment["visual_strategy"]["components"]:
                key = (segment["segment_id"], component["component_id"])
                query, check = queries.get(key, {}), checks.get(key, {})
                binding = segment.get("bindings", {}).get(component["component_id"], {})
                template = (binding.get("template_id") or check.get("selected")
                            or binding.get("source_id") or binding.get("material_id")
                            or binding.get("asset_id") or binding.get("snapshot_path")
                            or binding.get("job_path") or component["kind"])
                if check.get("template_title"):
                    template = check["template_title"] + " · " + template
                tags = query.get("tags", [])
                kind = "贴片" if component.get("layer_role") == "annotation" else "B-roll"
                lines.append("| {number} | {start:.3f}–{end:.3f}s | {kind} | {spoken} | {semantic} | {tags} | `{template}` |".format(
                    number=numbering[segment["segment_id"] + ":" + component["component_id"]],
                    start=segment["start"], end=segment["end"], kind=kind,
                    spoken=cell(check.get("spoken_text", motion_review.get("spoken_segments", {}).get(segment["segment_id"], ""))),
                    semantic=cell(segment["visual_intent"].get("statement", "")),
                    tags=cell("、".join(tags)) if tags else "—（素材引用）", template=cell(template)))
        lines.append("")
        lines.extend(["## 内部选型与整片协调记录", "", "```json",
                      json.dumps(skill_selection, ensure_ascii=False, sort_keys=True),
                      "```", ""])
    if reviewed_visual_text:
        lines.extend(["## 内部屏显语义核对", "", "```json", json.dumps({"content_analysis_sha256": plan["content_analysis_sha256"], "entries": reviewed_visual_text}, ensure_ascii=False, sort_keys=True), "```", ""])
    if overlay_alignment_report:
        lines.extend(["## 原生贴片实际词锚与时钟", "", "```json",
                      json.dumps(overlay_alignment_report, ensure_ascii=False, sort_keys=True),
                      "```", ""])
    if overlay_selection_report:
        lines.extend(["## A-roll 语义选型与结构重复复核", "", "```json",
                      json.dumps(overlay_selection_report, ensure_ascii=False, sort_keys=True),
                      "```", ""])
    for segment in plan["segments"]:
        lines.extend(
            [
                f"## {segment['segment_id']} · {segment['visual_strategy']['mode']}",
                "",
                f"- 时间：{segment['start']:.3f}s–{segment['end']:.3f}s",
                "- 组件："
                + (
                    "、".join(
                        f"{component['component_id']} ({component['kind']})"
                        for component in segment["visual_strategy"]["components"]
                    )
                    or "无（保留 A-roll）"
                ),
                "",
            ]
        )
    return "\n".join(lines)


def _entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        raise _fail("visual transaction entry is inaccessible") from None
    return True


def _read_regular(path: Path) -> bytes:
    try:
        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise _fail("visual transaction file is not an owned regular file")
        payload = path.read_bytes()
        after = os.lstat(path)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or after.st_size != len(payload)
        ):
            raise _fail("visual transaction file changed while reading")
        return payload
    except VisualPlanError:
        raise
    except OSError:
        raise _fail("visual transaction file is inaccessible") from None


def _strict_json_bytes(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except VisualPlanError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise _fail(f"{label} is invalid") from None
    if type(value) is not dict:
        raise _fail(f"{label} is invalid")
    return value


def _file_record(name: str, payload: bytes) -> dict[str, object]:
    return {
        "path": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _validate_file_record(
    value: object, *, allowed_files: tuple[str, ...] = _PAYLOAD_FILES,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"path", "sha256", "bytes"}
        or value["path"] not in allowed_files
        or type(value["bytes"]) is not int
        or value["bytes"] < 0
    ):
        raise _fail("visual ownership record is invalid")
    _sha256(value["sha256"], "visual ownership sha256")
    return dict(value)


def _validate_manifest(value: object) -> dict[str, object]:
    keys = {
        "schema_version",
        "generation_id",
        "job_id",
        "base_revision",
        "published_revision",
        "files",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or value["schema_version"] not in {3, 4}
        or type(value["generation_id"]) is not str
        or len(value["generation_id"]) != 32
        or any(character not in _SHA256_CHARS for character in value["generation_id"])
        or type(value["job_id"]) is not str
        or type(value["base_revision"]) is not int
        or value["base_revision"] < 0
        or type(value["published_revision"]) is not int
        or value["published_revision"] < 0
        or value["published_revision"] != value["base_revision"] + 1
        or type(value["files"]) is not list
    ):
        raise _fail("visual ownership manifest is invalid")
    paths = [record.get("path") if type(record) is dict else None for record in value["files"]]
    if value["schema_version"] == 3 and tuple(paths) in {
        _LEGACY_PAYLOAD_FILES, _PAYLOAD_FILES,
    }:
        allowed_files = tuple(paths)
    elif value["schema_version"] == 4 and tuple(paths) == _PAYLOAD_FILES + (_EVENT_PAYLOAD_FILE,):
        allowed_files = _PAYLOAD_FILES + (_EVENT_PAYLOAD_FILE,)
    else:
        raise _fail("visual ownership manifest is invalid")
    files = [_validate_file_record(record, allowed_files=allowed_files) for record in value["files"]]
    if [record["path"] for record in files] != list(allowed_files):
        raise _fail("visual ownership manifest is invalid")
    result = dict(value)
    result["files"] = files
    return result


def _generation_artifacts(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = [
        {**record, "path": f"07-visual-direction/{record['path']}"}
        for record in manifest["files"]
    ]
    ownership = contract_artifacts.canonical_json_bytes(manifest)
    records.append(
        {
            **_file_record("ownership.json", ownership),
            "path": "07-visual-direction/ownership.json",
        }
    )
    return records


def _load_generation(
    path: Path,
    *,
    job_id: str,
    expected_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        before = os.lstat(path)
        if not stat.S_ISDIR(before.st_mode):
            raise _fail("visual generation is not an owned directory")
        manifest_data = _read_regular(path / "ownership.json")
        manifest = _validate_manifest(
            _strict_json_bytes(manifest_data, "visual ownership manifest")
        )
        expected_names = {record["path"] for record in manifest["files"]} | {"ownership.json"}
        if set(os.listdir(path)) != expected_names:
            raise _fail("visual generation contains unknown entries")
        if (
            manifest["job_id"] != job_id
            or contract_artifacts.canonical_json_bytes(manifest) != manifest_data
            or (expected_manifest is not None and manifest != expected_manifest)
        ):
            raise _fail("visual generation ownership does not match")
        for record in manifest["files"]:
            payload = _read_regular(path / str(record["path"]))
            if (
                hashlib.sha256(payload).hexdigest() != record["sha256"]
                or len(payload) != record["bytes"]
            ):
                raise _fail("visual generation payload identity changed")
        after = os.lstat(path)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise _fail("visual generation identity changed")
        return manifest
    except VisualPlanError:
        raise
    except OSError:
        raise _fail("visual generation is not an owned directory") from None


def _validate_journal(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != _JOURNAL_KEYS
        or value["schema_version"] != 3
        or type(value["generation_id"]) is not str
        or len(value["generation_id"]) != 32
        or any(character not in _SHA256_CHARS for character in value["generation_id"])
        or type(value["job_id"]) is not str
        or type(value["base_revision"]) is not int
        or value["base_revision"] < 0
    ):
        raise _fail("visual transaction journal is invalid")
    _sha256(value["base_workflow_sha256"], "base workflow sha256")
    new_manifest = _validate_manifest(value["new_manifest"])
    previous = value["previous_manifest"]
    if previous is not None:
        previous = _validate_manifest(previous)
    if (
        new_manifest["generation_id"] != value["generation_id"]
        or new_manifest["job_id"] != value["job_id"]
        or new_manifest["base_revision"] != value["base_revision"]
        or (
            previous is not None
            and (
                previous["job_id"] != value["job_id"]
                or previous["generation_id"] == value["generation_id"]
            )
        )
    ):
        raise _fail("visual transaction journal is invalid")
    result = dict(value)
    result["new_manifest"] = new_manifest
    result["previous_manifest"] = previous
    return result


def _read_journal(path: Path) -> tuple[dict[str, object], bytes]:
    payload = _read_regular(path)
    journal = _validate_journal(_strict_json_bytes(payload, "visual journal"))
    if contract_artifacts.canonical_json_bytes(journal) != payload:
        raise _fail("visual transaction journal is not canonical")
    return journal, payload


def _write_journal(path: Path, journal: dict[str, object]) -> bytes:
    checked = _validate_journal(journal)
    payload = contract_artifacts.canonical_json_bytes(checked)
    if _entry_exists(path):
        raise _fail("visual transaction journal already exists")
    contract_artifacts.write_bytes_atomic(path, payload)
    if _read_regular(path) != payload:
        raise _fail("visual transaction journal write failed")
    return payload


def _remove_journal(path: Path, expected: bytes) -> None:
    if _read_regular(path) != expected:
        raise _fail("visual transaction journal changed")
    os.unlink(path)
    workflow_state._fsync_directory(path.parent)


def _write_generation(
    path: Path,
    plan_payload: bytes,
    review_payload: bytes,
    receipt_payload: bytes,
    semantic_events_payload: bytes | None,
    manifest: dict[str, object],
) -> None:
    path.mkdir(mode=0o700)
    contract_artifacts.write_bytes_atomic(path / "visual-plan.json", plan_payload)
    contract_artifacts.write_bytes_atomic(path / "visual-routing.md", review_payload)
    contract_artifacts.write_bytes_atomic(
        path / "material-usage.json", receipt_payload
    )
    if semantic_events_payload is not None:
        contract_artifacts.write_bytes_atomic(
            path / _EVENT_PAYLOAD_FILE, semantic_events_payload
        )
    contract_artifacts.write_json_artifact(path / "ownership.json", manifest)
    workflow_state._fsync_directory(path)
    workflow_state._fsync_directory(path.parent)


def _remove_generation(
    path: Path,
    manifest: dict[str, object],
) -> None:
    if not _entry_exists(path):
        return
    expected = {
        record["path"]: record for record in manifest["files"]
    } | {
        "ownership.json": _file_record(
            "ownership.json", contract_artifacts.canonical_json_bytes(manifest)
        )
    }
    named = os.lstat(path)
    if not stat.S_ISDIR(named.st_mode):
        raise _fail("refusing to remove an unknown visual generation")
    actual_names = set(os.listdir(path))
    if not actual_names.issubset(expected):
        raise _fail("refusing to remove a changed visual generation")
    for name in sorted(actual_names):
        payload = _read_regular(path / name)
        record = expected[name]
        if (
            len(payload) != record["bytes"]
            or hashlib.sha256(payload).hexdigest() != record["sha256"]
        ):
            raise _fail("refusing to remove a changed visual generation")
    for index, name in enumerate(sorted(actual_names)):
        os.unlink(path / name)
        if index == 0:
            _crash_checkpoint("cleanup_partial")
    os.rmdir(path)
    workflow_state._fsync_directory(path.parent)


def _acquire_job_lock(job_directory: Path) -> int:
    path = job_directory / _LOCK_NAME
    descriptor = -1
    locked = False
    try:
        descriptor = os.open(
            str(path),
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise _fail("visual direction lock is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        named = os.lstat(path)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise _fail("visual direction lock changed")
        return descriptor
    except BaseException:
        if descriptor >= 0:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)
        raise


def _release_job_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _synchronize_job(job: JobState, persisted: JobState) -> None:
    job.root = persisted.root
    job.job_dir = persisted.job_dir
    job.job_id = persisted.job_id
    job.inputs = persisted.inputs
    job.revision = persisted.revision
    job.expected_revision = persisted.expected_revision
    job.expected_sha256 = persisted.expected_sha256
    job.expected_bytes = persisted.expected_bytes
    job.version = persisted.version
    job.stages.clear()
    job.stages.update(copy.deepcopy(persisted.stages))


def _reduced_records(value: object) -> list[dict[str, object]] | None:
    if type(value) is not list:
        return None
    result = []
    for record in value:
        if type(record) is not dict or not {"path", "sha256", "bytes"}.issubset(record):
            return None
        result.append(
            {key: record[key] for key in ("path", "sha256", "bytes")}
        )
    return result


def _stage_references(
    job: JobState, manifest: dict[str, object]
) -> bool:
    stage = job.stages["visual_direction"]
    expected = _generation_artifacts(manifest)
    def production_records(records):
        reduced = _reduced_records(records)
        return ([r for r in reduced if r["path"].startswith("07-visual-direction/")]
                if reduced is not None else None)
    return (
        production_records(stage.get("artifacts")) == expected
        or production_records(stage.get("lineage")) == expected
    )


def _workflow_state_kind(
    persisted: JobState, journal: dict[str, object]
) -> str:
    if (
        persisted.job_id != journal["job_id"]
        or persisted.version != 2
    ):
        return "other"
    if (
        persisted.revision == journal["base_revision"]
        and persisted.expected_sha256 == journal["base_workflow_sha256"]
    ):
        return "old"
    if _stage_references(persisted, journal["new_manifest"]):
        return "new"
    previous = journal["previous_manifest"]
    if previous is not None and _stage_references(persisted, previous):
        return "old"
    stage = persisted.stages["visual_direction"]
    if previous is None and not stage["artifacts"] and not stage["lineage"]:
        return "old"
    return "other"


def _stage_path(
    job_directory: Path, journal: dict[str, object]
) -> Path:
    return job_directory / (
        f".visual-direction-v3.stage-{journal['generation_id']}"
    )


def _layout_kind(
    job_directory: Path, journal: dict[str, object]
) -> str:
    target = job_directory / "07-visual-direction"
    stage = _stage_path(job_directory, journal)
    new = journal["new_manifest"]
    previous = journal["previous_manifest"]
    target_manifest = None
    stage_manifest = None
    if _entry_exists(target):
        target_manifest = _load_generation(target, job_id=str(journal["job_id"]))
    if _entry_exists(stage):
        stage_manifest = _load_generation(stage, job_id=str(journal["job_id"]))
    if target_manifest == previous and stage_manifest == new:
        return "before_swap"
    if target_manifest == new and stage_manifest == previous:
        return "after_swap"
    if previous is not None and target_manifest == new and stage_manifest is None:
        return "after_swap_cleaned"
    if previous is None and target_manifest is None and stage_manifest == new:
        return "before_swap"
    if previous is None and target_manifest == new and stage_manifest is None:
        return "after_swap"
    raise _fail("visual transaction layout is ambiguous")


def _rollback_layout(
    job_directory: Path,
    journal: dict[str, object],
    layout: str,
) -> None:
    target = job_directory / "07-visual-direction"
    stage = _stage_path(job_directory, journal)
    if layout == "after_swap_cleaned":
        raise _fail("previous visual generation is unavailable for rollback")
    if layout == "after_swap":
        if journal["previous_manifest"] is not None:
            workflow_state._atomic_exchange_rename(target, stage)
        else:
            workflow_state._atomic_noreplace_rename(target, stage)
        workflow_state._fsync_directory(job_directory)
    _remove_generation(
        stage,
        journal["new_manifest"],
    )


def _finalize_layout(
    job_directory: Path,
    journal: dict[str, object],
    layout: str,
) -> None:
    if layout not in {"after_swap", "after_swap_cleaned"}:
        raise _fail("committed visual generation is not active")
    if journal["previous_manifest"] is not None and layout == "after_swap":
        _remove_generation(
            _stage_path(job_directory, journal),
            journal["previous_manifest"],
        )


def _recover_visual_transaction(
    job: JobState,
) -> tuple[str, Path | None]:
    journal_path = job.job_dir / _JOURNAL_NAME
    if not _entry_exists(journal_path):
        return "none", None
    journal, journal_bytes = _read_journal(journal_path)
    if journal["job_id"] != job.job_id:
        raise _fail("visual transaction belongs to another job")
    persisted = workflow_state.load_job(job.job_dir)
    workflow_kind = _workflow_state_kind(persisted, journal)
    stage = _stage_path(job.job_dir, journal)
    target = job.job_dir / "07-visual-direction"

    reserved_layout = False
    if not _entry_exists(stage):
        if journal["previous_manifest"] is not None:
            if _entry_exists(target):
                reserved_layout = (
                    _load_generation(target, job_id=job.job_id)
                    == journal["previous_manifest"]
                )
        else:
            reserved_layout = not _entry_exists(target)
    if reserved_layout:
        if workflow_kind != "old":
            raise _fail("visual transaction workflow state is ambiguous")
        if journal["previous_manifest"] is not None:
            _load_generation(
                target,
                job_id=job.job_id,
                expected_manifest=journal["previous_manifest"],
            )
        elif _entry_exists(target):
            raise _fail("foreign visual target appeared")
        _remove_journal(journal_path, journal_bytes)
        _synchronize_job(job, persisted)
        return "old", None

    try:
        layout = _layout_kind(job.job_dir, journal)
    except VisualPlanError:
        if workflow_kind == "new" and _entry_exists(stage):
            _load_generation(
                target,
                job_id=job.job_id,
                expected_manifest=journal["new_manifest"],
            )
            if journal["previous_manifest"] is None:
                _synchronize_job(job, persisted)
                return "committed", target / "visual-plan.json"
            try:
                _remove_generation(stage, journal["previous_manifest"])
                _remove_journal(journal_path, journal_bytes)
            except Exception:
                pass
            _synchronize_job(job, persisted)
            return "committed", target / "visual-plan.json"
        if workflow_kind == "old" and _entry_exists(stage):
            _remove_generation(
                stage,
                journal["new_manifest"],
            )
            if journal["previous_manifest"] is not None:
                _load_generation(
                    target,
                    job_id=job.job_id,
                    expected_manifest=journal["previous_manifest"],
                )
            elif _entry_exists(target):
                raise _fail("foreign visual target appeared")
            _remove_journal(journal_path, journal_bytes)
            _synchronize_job(job, persisted)
            return "old", None
        else:
            raise

    if workflow_kind == "new":
        try:
            _finalize_layout(job.job_dir, journal, layout)
            _remove_journal(journal_path, journal_bytes)
        except Exception:
            pass
        _synchronize_job(job, persisted)
        return "committed", target / "visual-plan.json"
    if workflow_kind == "old":
        _rollback_layout(job.job_dir, journal, layout)
        _remove_journal(journal_path, journal_bytes)
        _synchronize_job(job, persisted)
        return "old", None
    raise _fail("visual transaction conflicts with another workflow revision")


def _recover_before_context(job: JobState) -> None:
    workflow_state._validate_job(job)
    if job.version != 2:
        raise _fail("visual direction requires a full-v2 job")
    if not _entry_exists(job.job_dir / _JOURNAL_NAME):
        return
    descriptor = _acquire_job_lock(job.job_dir)
    committed = False
    try:
        recovered, _ = _recover_visual_transaction(job)
        committed = recovered == "committed"
    finally:
        try:
            _release_job_lock(descriptor)
        except Exception:
            if not committed:
                raise


def _exact_persisted_job(job: JobState) -> JobState:
    persisted = workflow_state.load_job(job.job_dir)
    if (
        job.job_id != persisted.job_id
        or job.version != persisted.version
        or job.inputs != persisted.inputs
        or job.revision != persisted.revision
        or job.expected_revision != persisted.expected_revision
        or job.expected_sha256 != persisted.expected_sha256
        or job.expected_bytes != persisted.expected_bytes
        or job.stages != persisted.stages
    ):
        raise _fail("workflow changed before visual publication")
    return persisted


def _crash_checkpoint(name: str) -> None:
    if os.environ.get("HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT") == name:
        os._exit(91)


def _publish_plan_generation(
    job: JobState,
    plan: dict[str, object],
    semantic_events_payload: bytes | None,
    state_writer: StateWriter,
    reviewed_visual_text: list[dict[str, str]] | None = None,
    skill_selection: dict[str, object] | None = None,
    overlay_alignment_report: list[dict] | None = None,
    overlay_selection_report: list[dict] | None = None,
) -> Path:
    descriptor = _acquire_job_lock(job.job_dir)
    journal_path = job.job_dir / _JOURNAL_NAME
    transaction_started = False
    committed = False
    try:
        recovered, _ = _recover_visual_transaction(job)
        if recovered == "committed":
            raise _fail("workflow changed before this visual publication")
        persisted = _exact_persisted_job(job)
        _require_visual_preparation(job)
        target = job.job_dir / "07-visual-direction"
        previous_manifest = None
        if _entry_exists(target):
            try:
                target_entries = os.listdir(target)
            except OSError:
                raise _fail("visual generation is inaccessible") from None
            # The Job initializer creates empty stage directories up front.
            # They are not a published generation and must not block the
            # first atomic directory swap.
            if not target_entries:
                try:
                    target.rmdir()
                except OSError:
                    raise _fail("empty visual target cannot be removed") from None
            else:
                previous_manifest = _load_generation(target, job_id=job.job_id)
                if not _stage_references(persisted, previous_manifest):
                    raise _fail("visual target does not match workflow lineage")
        elif _reduced_records(
            persisted.stages["visual_direction"].get("lineage")
        ):
            raise _fail("workflow lineage requires a visual target")

        generation_id = secrets.token_hex(16)
        stage = job.job_dir / f".visual-direction-v3.stage-{generation_id}"
        plan_payload = contract_artifacts.canonical_json_bytes(plan)
        numbering = None
        if (job.root / "job-context.json").exists() or (job.root / "00-user-provided").exists():
            from .visual_confirmation import approved_numbered_rows
            numbering = {row["row_id"]: row["number"] for row in approved_numbered_rows(job)}
        review_payload = _review_text(plan, reviewed_visual_text, skill_selection,
                                      overlay_alignment_report,
                                      overlay_selection_report, numbering).encode("utf-8")
        published_payload_paths = (
            "07-visual-direction/visual-plan.json",
            "07-visual-direction/visual-routing.md",
        )
        if semantic_events_payload is not None:
            published_payload_paths += (
                "07-visual-direction/semantic-events.json",
            )
        references = material_usage.visual_segment_references(
            plan["segments"],
            consumer_kind="visual_segment",
            artifact_paths_by_segment={
                str(segment["segment_id"]): published_payload_paths
                for segment in plan["segments"]
            },
        )
        receipt = material_usage.build_receipt_for_publication(
            persisted,
            "visual_direction",
            producer="edit.hd.tools.visual_plan",
            producer_version="3",
            stage_input_records=material_usage.current_stage_input_records(
                persisted, "visual_direction"
            ),
            references=references,
            artifact_paths=published_payload_paths,
        )
        receipt_payload = contract_artifacts.canonical_json_bytes(receipt)
        manifest = {
            "schema_version": 4 if semantic_events_payload is not None else 3,
            "generation_id": generation_id,
            "job_id": job.job_id,
            "base_revision": persisted.revision,
            "published_revision": persisted.revision + 1,
            "files": [
                _file_record("visual-plan.json", plan_payload),
                _file_record("visual-routing.md", review_payload),
                _file_record("material-usage.json", receipt_payload),
            ] + ([_file_record(_EVENT_PAYLOAD_FILE, semantic_events_payload)] if semantic_events_payload is not None else []),
        }
        journal = {
            "schema_version": 3,
            "generation_id": generation_id,
            "job_id": job.job_id,
            "base_revision": persisted.revision,
            "base_workflow_sha256": persisted.expected_sha256,
            "new_manifest": manifest,
            "previous_manifest": previous_manifest,
        }
        journal_bytes = _write_journal(journal_path, journal)
        transaction_started = True
        _crash_checkpoint("reserved")
        _write_generation(
            stage,
            plan_payload,
            review_payload,
            receipt_payload,
            semantic_events_payload,
            manifest,
        )
        _load_generation(
            stage, job_id=job.job_id, expected_manifest=manifest
        )
        _crash_checkpoint("staged")

        if previous_manifest is None:
            workflow_state._atomic_noreplace_rename(stage, target)
        else:
            workflow_state._atomic_exchange_rename(stage, target)
        workflow_state._fsync_directory(job.job_dir)
        _crash_checkpoint("swapped")
        writer_failure = None
        try:
            state_writer(
                job,
                "visual_direction",
                tuple(
                    job.job_dir / str(record["path"])
                    for record in _generation_artifacts(manifest)
                ),
            )
        except BaseException as failure:
            writer_failure = failure

        persisted_after = workflow_state.load_job(job.job_dir)
        workflow_kind = _workflow_state_kind(persisted_after, journal)
        layout_after = _layout_kind(job.job_dir, journal)
        if workflow_kind == "new":
            committed = True
            _crash_checkpoint("state_committed")
            try:
                _finalize_layout(job.job_dir, journal, layout_after)
                _remove_journal(journal_path, journal_bytes)
            except Exception:
                pass
            transaction_started = False
            _synchronize_job(job, persisted_after)
            return target / "visual-plan.json"
        if workflow_kind == "old":
            _rollback_layout(job.job_dir, journal, layout_after)
            _remove_journal(journal_path, journal_bytes)
            transaction_started = False
            _synchronize_job(job, persisted_after)
            if writer_failure is not None:
                raise writer_failure
            raise _fail("state writer did not commit the visual generation")
        raise _fail("visual transaction conflicts with another workflow revision")
    except BaseException as failure:
        if transaction_started:
            try:
                recovered, recovered_path = _recover_visual_transaction(job)
                if recovered == "committed" and recovered_path is not None:
                    committed = True
                    return recovered_path
            except Exception as recovery_failure:
                raise recovery_failure from failure
        raise
    finally:
        try:
            _release_job_lock(descriptor)
        except Exception:
            if not committed:
                raise


def _skill_selection_for_publication(
    job: JobState, draft: dict[str, object], treatment_path: Path | None,
) -> dict[str, object] | None:
    """Check selection before any freezer or workflow mutation; never infer a path."""
    managed = ((job.root / "job-context.json").exists()
               or (job.root / "00-user-provided").exists())
    if treatment_path is None:
        if managed:
            raise _fail("B-roll Skill selection is required; provide the Job treatment path")
        return None
    path = Path(treatment_path).resolve()
    if not path.is_relative_to(job.root.resolve()):
        raise _fail("B-roll treatment must belong to the current Job")
    try:
        treatment = contract_artifacts.read_json_artifact(path)
        from .motion_match_cache import validate_reviews
        validate_reviews(Path(__file__).resolve().parents[3], draft, treatment)
        selection = broll_skill_selection.validate_selection(
            Path(__file__).resolve().parents[3], draft, treatment,
        )
        selection["motion_queries"] = treatment.get("motion_queries", [])
        if managed:
            from .motion_capabilities import check_offline_plan
            review = check_offline_plan(Path(__file__).resolve().parents[3], draft,
                                        treatment, job_dir=job.job_dir)
            if review["status"] != "pass":
                raise ValueError("motion semantic/native input check is " + review["status"]
                                 + "; complete cited treatment assessments before publication")
            selection["motion_review"] = review
        return selection
    except (contract_artifacts.ContractArtifactError, ValueError, KeyError, TypeError) as error:
        raise _fail(str(error)) from None


def _check_selected_recipe_bindings(draft, frozen_segments, selection):
    if selection is None:
        return
    originals = {s["segment_id"]: s for s in draft["segments"]}
    frozen = {s["segment_id"]: s for s in frozen_segments}
    for assignment in [*selection["assignments"], *selection.get("overlay_assignments", [])]:
        sid, cid = assignment["segment_id"], assignment["component_id"]
        binding = originals[sid]["bindings"][cid]
        if frozen[sid]["bindings"][cid] != binding:
            raise _fail("binding freezer changed the selected Skill inputs")
        compiled = next(c for c in frozen[sid]["shot_recipe"]["components"] if c["component_id"] == cid)
        # These two preparation fields are consumed by the existing Lovart
        # compiler into its artifact dimensions, not emitted as recipe fields.
        consumed = ({"execution_mode", "source_dimensions"} if binding.get("execution_mode") == "reuse_completed_lovart_video"
                    else {"execution_mode", "media_type", "source_dimensions"} if binding.get("execution_mode") == "reuse_completed_generated_media" else set())
        if any(compiled.get(k) != v for k, v in binding.items() if k not in consumed):
            raise _fail("compiled recipe changed the selected Skill inputs")
        if "source_dimensions" in consumed and any(compiled["artifact_contract"][k] != v for k, v in binding["source_dimensions"].items()):
            raise _fail("compiled recipe changed the selected Lovart source dimensions")


def prepare_visual_direction(
    job: JobState,
    director_brief: Path,
    official_preview_root: Path,
    *,
    candidate_freezers: Mapping[str, CandidateFreezer] | None = None,
    binding_freezers: Mapping[str, BindingFreezer] | None = None,
    strategy_compiler: StrategyCompiler | None = None,
    state_writer: StateWriter | None = None,
    expected_revision: int | None = None,
    expected_workflow_sha256: str | None = None,
    director_brief_sha256: str | None = None,
    director_brief_payload: Mapping[str, object] | None = None,
    semantic_event_plan_payload: Mapping[str, object] | None = None,
    reviewed_visual_text: Mapping[str, object] | None = None,
    treatment_path: Path | None = None,
) -> Path:
    """Freeze approved inputs, compile ShotRecipe v2, and publish a v3 plan."""
    del official_preview_root  # Frozen bindings carry Job-relative snapshot identities.
    if (expected_revision is None) != (expected_workflow_sha256 is None):
        raise _fail("expected workflow checkpoint is incomplete")
    if expected_revision is not None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise _fail("expected workflow revision is invalid")
        _sha256(expected_workflow_sha256, "expected workflow sha256")
    if director_brief_sha256 is not None:
        _sha256(director_brief_sha256, "director brief sha256")
    if director_brief_payload is None:
        try:
            brief = contract_artifacts.read_json_artifact(Path(director_brief))
        except contract_artifacts.ContractArtifactError:
            raise _fail() from None
    else:
        if type(director_brief_payload) is not dict:
            raise _fail("director brief payload must be an object")
        brief = _deepcopy(director_brief_payload, "director brief payload")
    if (
        director_brief_sha256 is not None
        and contract_artifacts.sha256_json(brief) != director_brief_sha256
    ):
        raise _fail("director brief changed before visual publication")

    # The destructive schema gate and all pure contract checks precede every
    # injected freezer, compiler, artifact write, and workflow-state transition.
    draft = _validate_draft(brief)
    if (job.stages["visual_direction"]["status"] == "ready_for_review"
            and any(r["path"].startswith("07-visual-confirmation/") for r in job.stages["visual_direction"]["artifacts"])):
        from .visual_confirmation import validate_realization_draft
        validate_realization_draft(job, draft, contract_artifacts.read_json_artifact(treatment_path))
    skill_selection = _skill_selection_for_publication(job, draft, treatment_path)
    try:
        _recover_before_context(job)
        persisted = _exact_persisted_job(job)
        if expected_revision is not None and (
            persisted.revision != expected_revision
            or persisted.expected_sha256 != expected_workflow_sha256
        ):
            raise _fail("workflow changed before visual publication")
        (
            analysis_record,
            edit_path,
            timeline_path,
            edited_path,
            canvas,
            duration,
            reviewed_entries,
        ) = _validate_job_context(job, draft, reviewed_visual_text)
        if skill_selection is not None:
            coverage_visual = {"duration": duration, "segments": draft["segments"]}
            coverage_treatment = None
            if treatment_path is not None:
                try:
                    coverage_treatment = contract_artifacts.read_json_artifact(Path(treatment_path))
                except contract_artifacts.ContractArtifactError:
                    raise _fail("visual coverage treatment cannot be read") from None
            coverage = visual_coverage.require_density(coverage_visual, treatment=coverage_treatment)
            if coverage["blocking_issues"]:
                raise _fail("visual coverage: " + "; ".join(coverage["blocking_issues"]))
        try:
            overlay_report = overlay_alignment.validate_treatment(job, draft, treatment_path)
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise _fail(f"overlay alignment: {error}") from None
        try:
            treatment_relative = str(Path(treatment_path).relative_to(job.job_dir)) if treatment_path and Path(treatment_path).is_absolute() else treatment_path
            treatment_payload = contract_artifacts.read_json_artifact(overlay_alignment._path(job.job_dir, treatment_relative)) if treatment_path else None
            native_routes = {(row["segment_id"], row["component_id"]): row["route"].removeprefix("hyperframes/") for row in overlay_report}
            overlay_selection_report = overlay_selection.validate_selection(draft, treatment_payload, native_routes)
        except (contract_artifacts.ContractArtifactError, ValueError, OSError, KeyError, TypeError) as error:
            raise _fail(f"overlay selection: {error}") from None
        try:
            confirmed_content.check_confirmed_content(job, {"segments": draft["segments"]})
        except confirmed_content.ConfirmedContentError as error:
            raise _fail(str(error)) from None
        if strategy_compiler is None:
            router = _load_router_module()

            def compile_for_publication(strategy, context):
                try:
                    return router.compile_strategy(strategy, context)
                except BaseException as failure:
                    if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                        raise
                    raise _fail(str(failure)) from None
        else:
            compile_for_publication = strategy_compiler
        frozen_segments = [
            _freeze_and_compile_segment(
                segment,
                candidate_freezers=candidate_freezers or {},
                binding_freezers=binding_freezers or {},
                strategy_compiler=compile_for_publication,
            )
            for segment in draft["segments"]
        ]
        _check_selected_recipe_bindings(draft, frozen_segments, skill_selection)
        plan_without_identity = {
            "schema_version": 3,
            "content_analysis_sha256": analysis_record["analysis_sha256"],
            "edit_plan_sha256": contract_artifacts.sha256_file(edit_path),
            "timeline_map_sha256": contract_artifacts.sha256_file(timeline_path),
            "edited_aroll_sha256": contract_artifacts.sha256_file(edited_path),
            "canvas": canvas,
            "duration": duration,
            "segments": frozen_segments,
            "source_summary": _source_summary(frozen_segments),
        }
        plan = validate_visual_plan(
            {
                **plan_without_identity,
                "visual_plan_sha256": contract_artifacts.sha256_json(
                    plan_without_identity
                ),
            }
        )
        semantic_events_payload = None
        if semantic_event_plan_payload is not None:
            try:
                checked_events = semantic_events.validate_semantic_event_plan(
                    semantic_event_plan_payload,
                    visual_plan=plan,
                    expected_visual_plan_sha256=plan["visual_plan_sha256"],
                )
            except semantic_events.SemanticEventError as error:
                raise _fail(str(error)) from None
            semantic_events_payload = contract_artifacts.canonical_json_bytes(
                checked_events
            )
        writer = state_writer or (
            (lambda current, _stage, paths: workflow_state.mark_visual_ready(current, paths))
            if job.stages["visual_direction"]["status"] == "ready_for_review" else mark_ready
        )
        return _publish_plan_generation(job, plan, semantic_events_payload, writer,
                                        reviewed_entries, skill_selection, overlay_report,
                                        overlay_selection_report)
    except VisualPlanError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail() from None

"""Bind a validated semantic-event plan to TalkCraft brief events."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .contract_artifacts import sha256_json
from .semantic_events import SemanticEventError, validate_semantic_event_plan


class EventBindingError(ValueError):
    """Raised when a TalkCraft brief event is not backed by a semantic event."""


def _fail(message: str) -> None:
    raise EventBindingError(message)


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _frame(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label} must be a non-negative integer frame")
    return value


def build_event_binding_manifest(
    semantic_event_plan: object,
    brief_bundle: Mapping[str, object],
    *,
    span_id: str,
    span_start_frame: int,
    span_end_frame: int,
    span_segment_ids: set[str],
    visual_plan: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return a hash-bound event-to-brief manifest for one approved span bundle.

    The bundle is expected to have passed the existing TalkCraft brief validator.
    This helper adds the semantic-event identity without changing the old brief
    schema, so callers can adopt it incrementally.
    """

    try:
        plan = validate_semantic_event_plan(
            semantic_event_plan,
            visual_plan=visual_plan,
            expected_visual_plan_sha256=(
                visual_plan.get("visual_plan_sha256")
                if type(visual_plan) is dict and visual_plan.get("visual_plan_sha256")
                else None
            ),
        )
    except SemanticEventError as error:
        raise EventBindingError(str(error)) from None
    _identifier(span_id, "span_id")
    _frame(span_start_frame, "span_start_frame")
    _frame(span_end_frame, "span_end_frame")
    if span_end_frame <= span_start_frame:
        _fail("span frame range is invalid")
    if type(span_segment_ids) is not set or not all(isinstance(item, str) for item in span_segment_ids):
        _fail("span_segment_ids must be a set of identifiers")
    if type(brief_bundle) is not dict or type(brief_bundle.get("briefs")) is not list:
        _fail("brief_bundle.briefs must be a list")
    events_by_id = {event["event_id"]: event for event in plan["events"]}
    bindings: list[dict[str, Any]] = []
    for index, entry in enumerate(brief_bundle["briefs"]):
        if type(entry) is not dict or type(entry.get("brief")) is not dict:
            _fail(f"briefs[{index}] is invalid")
        brief = entry["brief"]
        target = brief.get("execution_target")
        target_id = sha256_json(target) if isinstance(target, dict) else ""
        scope = brief.get("frame_scope")
        if type(scope) is not dict:
            _fail(f"briefs[{index}].frame_scope is invalid")
        local_start = scope.get("span_start_frame")
        local_end = scope.get("span_end_frame")
        if type(local_start) is not int or type(local_end) is not int or local_end <= local_start:
            _fail(f"briefs[{index}].frame_scope is invalid")
        raw_events = brief.get("events")
        if type(raw_events) is not list or not raw_events:
            _fail(f"briefs[{index}] must contain semantic events")
        for event_index, raw_event in enumerate(raw_events):
            if type(raw_event) is not dict or type(raw_event.get("anchor_id")) is not str:
                _fail(f"briefs[{index}].events[{event_index}] is invalid")
            event_id = raw_event["anchor_id"]
            semantic = events_by_id.get(event_id)
            if semantic is None:
                _fail(f"briefs[{index}] references unknown semantic event: {event_id}")
            if semantic["segment_id"] not in span_segment_ids:
                _fail(f"semantic event {event_id} does not belong to span {span_id}")
            if semantic["span_id"] is not None and semantic["span_id"] != span_id:
                _fail(f"semantic event {event_id} belongs to a different span")
            frame = _frame(raw_event.get("frame"), f"briefs[{index}].events[{event_index}].frame")
            semantic_start = semantic["start_frame"] - span_start_frame
            semantic_end = semantic["end_frame"] - span_start_frame
            if semantic["start_frame"] < span_start_frame or semantic["end_frame"] > span_end_frame:
                _fail(f"semantic event {event_id} crosses the span boundary")
            if not semantic_start <= frame < semantic_end:
                _fail(f"brief event {event_id} falls outside its semantic event window")
            if not local_start <= frame < local_end:
                _fail(f"brief event {event_id} falls outside its brief frame scope")
            bindings.append({
                "target_sha256": target_id,
                "event_id": event_id,
                "type": raw_event.get("type"),
                "frame": frame,
            })
    if not bindings:
        _fail("event binding manifest must contain bindings")
    unsigned = {
        "schema_version": "talkcraft-event-binding/v1",
        "span_id": span_id,
        "semantic_event_plan_sha256": plan["plan_sha256"],
        "bindings": bindings,
    }
    return {**unsigned, "binding_sha256": sha256_json(unsigned)}


def validate_event_binding_manifest(value: object) -> dict[str, Any]:
    """Validate the deterministic hash of a previously built event manifest."""

    if type(value) is not dict or set(value) != {
        "schema_version", "span_id", "semantic_event_plan_sha256", "bindings", "binding_sha256"
    }:
        raise EventBindingError("event binding manifest fields are invalid")
    if value["schema_version"] != "talkcraft-event-binding/v1":
        raise EventBindingError("unsupported event binding manifest schema")
    unsigned = {key: copy.deepcopy(value[key]) for key in (
        "schema_version", "span_id", "semantic_event_plan_sha256", "bindings"
    )}
    if value["binding_sha256"] != sha256_json(unsigned):
        raise EventBindingError("event binding manifest hash does not match")
    return {**unsigned, "binding_sha256": value["binding_sha256"]}

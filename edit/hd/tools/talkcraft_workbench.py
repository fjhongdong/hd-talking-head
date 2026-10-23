"""Server-side contracts for TalkCraft review and Workbench revisions."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from . import contract_artifacts, semantic_events, talkcraft_contract, visual_plan
from .visual_span_contract import enumerate_plan_chunks


class TalkCraftWorkbenchError(ValueError):
    pass


def _fail(message: str) -> None:
    raise TalkCraftWorkbenchError(message)


def _target_id(target: Mapping[str, object]) -> str:
    if target.get("kind") == "component":
        return f"component:{target.get('segment_id')}:{target.get('component_id')}"
    if target.get("kind") == "boundary":
        return f"boundary:{target.get('boundary_id')}:{target.get('card_slot_id')}"
    _fail("Workbench execution target is invalid")


def _bundle_with_identity(bundle: Mapping[str, object]) -> dict[str, Any]:
    unsigned = {
        "schema_version": "talkcraft-brief-bundle/v1",
        "owner": copy.deepcopy(bundle["owner"]),
        "briefs": copy.deepcopy(bundle["briefs"]),
    }
    return {
        **unsigned,
        "bundle_sha256": contract_artifacts.sha256_json(unsigned),
    }


def build_v4_edit_contract(
    plan: object,
    brief_bundles: Mapping[str, object],
    semantic_event_plan: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Expose safe semantic parameters for Workbench without granting approval."""

    mapping = build_v4_review_mapping(plan)
    checked_events = None
    if semantic_event_plan is not None:
        try:
            checked_events = semantic_events.validate_semantic_event_plan(
                semantic_event_plan,
                expected_visual_plan_sha256=mapping["visual_plan_sha256"],
            )
        except semantic_events.SemanticEventError as error:
            raise TalkCraftWorkbenchError(str(error)) from None
    if type(brief_bundles) is not dict:
        _fail("Workbench brief bundles must be keyed by chunk id")
    targets: list[dict[str, Any]] = []
    expected_chunks = {
        chunk["chunk_id"]: chunk
        for span in mapping["render_spans"]
        for chunk in span["chunks"]
        if chunk["execution_targets"]
    }
    if set(brief_bundles) != set(expected_chunks):
        _fail("Workbench brief bundles differ from TalkCraft chunks")
    for chunk_id, chunk in expected_chunks.items():
        chunk_span_id = next(
            span["span_id"]
            for span in mapping["render_spans"]
            if any(item["chunk_id"] == chunk_id for item in span["chunks"])
        )
        try:
            bundle = talkcraft_contract.validate_draft_brief_bundle(
                brief_bundles[chunk_id]
            )
        except talkcraft_contract.TalkCraftContractError as error:
            raise TalkCraftWorkbenchError(str(error)) from None
        briefs = {
            _target_id(entry["brief"]["execution_target"]): entry["brief"]
            for entry in bundle["briefs"]
        }
        expected_ids = {
            _target_id(target) for target in chunk["execution_targets"]
        }
        if set(briefs) != expected_ids:
            _fail("Workbench brief targets differ from the visual plan")
        for target in chunk["execution_targets"]:
            target_id = _target_id(target)
            brief = briefs[target_id]
            target_contract = {
                "target_id": target_id,
                "chunk_id": chunk_id,
                "card_id": brief["card_id"],
                "parameters": [
                    {
                        "key": "display_text",
                        "type": "text",
                        "default": brief["text"]["display"],
                    },
                    {
                        "key": "theme",
                        "type": "select",
                        "default": brief["style"]["theme"],
                        "options": ["apple-dark", "apple-light"],
                    },
                ],
            }
            if checked_events is not None:
                event_ids = [
                    item.get("anchor_id")
                    for item in brief.get("events", [])
                    if type(item) is dict and type(item.get("anchor_id")) is str
                ]
                event_ids = list(dict.fromkeys(event_ids))
                unknown = [
                    event_id for event_id in event_ids
                    if event_id not in {event["event_id"] for event in checked_events["events"]}
                ]
                if unknown:
                    _fail("Workbench brief references an unknown semantic event")
                event_by_id = {
                    event["event_id"]: event for event in checked_events["events"]
                }
                segment_ids = {
                    overlap["segment_id"]
                    for overlap in chunk["segment_overlaps"]
                }
                for event_id in event_ids:
                    event = event_by_id[event_id]
                    if (
                        event["segment_id"] not in segment_ids
                        or (
                            event["span_id"] is not None
                            and event["span_id"] != chunk_span_id
                        )
                    ):
                        _fail("Workbench brief event is outside its chunk")
                    if (
                        event["start_frame"] < chunk["start_frame"]
                        or event["end_frame"] > chunk["end_frame"]
                    ):
                        _fail("Workbench brief event frame is outside its chunk")
                target_contract["event_ids"] = event_ids
            targets.append(target_contract)
    unsigned = {
        "schema_version": "talkcraft-v4-edit-contract/v1",
        "role": "editable_draft_only",
        "visual_plan_sha256": mapping["visual_plan_sha256"],
        "targets": targets,
    }
    if checked_events is not None:
        unsigned["semantic_event_plan_sha256"] = checked_events["plan_sha256"]
    return {**unsigned, "edit_contract_sha256": contract_artifacts.sha256_json(unsigned)}


def apply_v4_overrides(
    plan: object,
    brief_bundles: Mapping[str, object],
    overrides: object,
    semantic_event_plan: Mapping[str, object] | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply Workbench values to new draft bundles; approved artifacts stay untouched."""

    contract = build_v4_edit_contract(
        plan, brief_bundles, semantic_event_plan=semantic_event_plan
    )
    if type(overrides) is not dict:
        _fail("Workbench overrides must be an object")
    known = {item["target_id"] for item in contract["targets"]}
    if set(overrides) - known:
        _fail("Workbench overrides contain an unknown target")
    result: dict[str, dict[str, Any]] = {}
    for chunk_id, raw_bundle in brief_bundles.items():
        bundle = talkcraft_contract.validate_draft_brief_bundle(raw_bundle)
        entries = []
        for raw_entry in bundle["briefs"]:
            brief = copy.deepcopy(raw_entry["brief"])
            target_id = _target_id(brief["execution_target"])
            values = overrides.get(target_id, {})
            if type(values) is not dict or set(values) - {"display_text", "theme"}:
                _fail("Workbench override fields are invalid")
            if "display_text" in values:
                value = values["display_text"]
                if type(value) is not str or not value.strip() or len(value) > 160:
                    _fail("Workbench display_text is invalid")
                brief["text"]["display"] = value.strip()
            if "theme" in values:
                value = values["theme"]
                if value not in {"apple-dark", "apple-light"}:
                    _fail("Workbench theme is invalid")
                brief["style"]["theme"] = value
            entries.append({
                "brief": brief,
                "brief_sha256": contract_artifacts.sha256_json(brief),
            })
        result[chunk_id] = _bundle_with_identity({
            "owner": bundle["owner"],
            "briefs": entries,
        })
        try:
            talkcraft_contract.validate_draft_brief_bundle(result[chunk_id])
        except talkcraft_contract.TalkCraftContractError as error:
            raise TalkCraftWorkbenchError(str(error)) from None
    return result


def build_v4_review_mapping(
    plan: object,
    *,
    canary_chunk_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Map semantic segments to spans/chunks for display, not approval evidence."""

    try:
        checked = visual_plan.validate_visual_plan(plan)
    except visual_plan.VisualPlanError as error:
        raise TalkCraftWorkbenchError(str(error)) from None
    if checked["schema_version"] != 4:
        _fail("TalkCraft review mapping requires VisualPlan v4")
    if (
        type(canary_chunk_ids) not in {list, tuple}
        or any(type(item) is not str for item in canary_chunk_ids)
        or len(canary_chunk_ids) != len(set(canary_chunk_ids))
    ):
        _fail("canary chunk selection is invalid")
    chunks = enumerate_plan_chunks(checked)
    chunk_ids = [item["chunk_id"] for item in chunks]
    if any(item not in chunk_ids for item in canary_chunk_ids):
        _fail("canary chunk selection is not in the visual plan")
    positions = [chunk_ids.index(item) for item in canary_chunk_ids]
    if positions != sorted(positions):
        _fail("canary chunk selection must preserve plan order")
    selected = set(canary_chunk_ids)
    selected_chunks = [item for item in chunks if item["chunk_id"] in selected]
    if any(not item["execution_targets"] for item in selected_chunks):
        _fail("canary selection must contain TalkCraft execution targets")
    canary_frames = sum(
        item["end_frame"] - item["start_frame"] for item in selected_chunks
    )
    if canary_frames > 720:
        _fail("canary chunk selection exceeds 720 frames")
    canary_output_ranges: dict[str, dict[str, int]] = {}
    output_start = 0
    for chunk in selected_chunks:
        duration = chunk["end_frame"] - chunk["start_frame"]
        canary_output_ranges[chunk["chunk_id"]] = {
            "output_start_frame": output_start,
            "output_end_frame": output_start + duration,
        }
        output_start += duration
    span_by_segment = {
        segment_id: span
        for span in checked["render_spans"]
        for segment_id in span["segment_ids"]
    }
    semantic_segments = []
    for segment in checked["segments"]:
        span = span_by_segment[segment["segment_id"]]
        semantic_segments.append({
            "segment_id": segment["segment_id"],
            "start_frame": round(segment["start"] * 24),
            "end_frame": round(segment["end"] * 24),
            "span_id": span["span_id"],
            "span_mode": span["mode"],
            "chunk_ids": [item["chunk_id"] for item in span["chunks"]],
            "preserved_boundary_ids": [
                item["boundary_id"] for item in span["boundaries"]
                if item["from_segment_id"] == segment["segment_id"]
                or item["to_segment_id"] == segment["segment_id"]
            ],
        })
    spans = []
    for span in checked["render_spans"]:
        spans.append({
            "span_id": span["span_id"],
            "mode": span["mode"],
            "segment_ids": copy.deepcopy(span["segment_ids"]),
            "start_frame": span["start_frame"],
            "end_frame": span["end_frame"],
            "preserved_boundaries": [
                {
                    "boundary_id": item["boundary_id"],
                    "from_segment_id": item["from_segment_id"],
                    "to_segment_id": item["to_segment_id"],
                }
                for item in span["boundaries"]
            ],
            "chunks": [
                {
                    "chunk_id": item["chunk_id"],
                    "start_frame": item["start_frame"],
                    "end_frame": item["end_frame"],
                    "segment_overlaps": [
                        {
                            "segment_id": segment["segment_id"],
                            "start_frame": max(
                                item["start_frame"], round(segment["start"] * 24)
                            ),
                            "end_frame": min(
                                item["end_frame"], round(segment["end"] * 24)
                            ),
                        }
                        for segment in checked["segments"]
                        if max(
                            item["start_frame"], round(segment["start"] * 24)
                        ) < min(
                            item["end_frame"], round(segment["end"] * 24)
                        )
                    ],
                    "execution_targets": copy.deepcopy(item["execution_targets"]),
                    "talkcraft_target_count": len(item["execution_targets"]),
                    "selected_for_canary": item["chunk_id"] in selected,
                    "canary_preview_range": copy.deepcopy(
                        canary_output_ranges.get(item["chunk_id"])
                    ),
                }
                for item in span["chunks"]
            ],
        })
    unsigned = {
        "schema_version": "talkcraft-v4-review-mapping/v1",
        "role": "review_display_only",
        "complete_visual_track": False,
        "visual_plan_sha256": checked["visual_plan_sha256"],
        "semantic_segments": semantic_segments,
        "render_spans": spans,
        "canary_selection": {
            "chunk_ids": list(canary_chunk_ids),
            "total_frames": canary_frames,
            "approval_status": "not_evaluated",
        },
    }
    return {
        **unsigned,
        "review_mapping_sha256": contract_artifacts.sha256_json(unsigned),
    }


__all__ = [
    "TalkCraftWorkbenchError",
    "apply_v4_overrides",
    "build_v4_edit_contract",
    "build_v4_review_mapping",
]

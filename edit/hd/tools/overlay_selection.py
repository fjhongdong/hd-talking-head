"""Explicit semantic review for native A-roll overlays."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Mapping

_ROUTE_BY_TEMPLATE = {
    "hyperframes-grid-card-assemble-portrait-adaptation": "grid-card-assemble",
    "hyperframes-notification-stack-portrait-adaptation": "notification-stack",
    "hyperframes-toggle-flip-portrait-adaptation": "toggle-flip",
    "hyperframes-before-after-wipe-portrait-adaptation": "before-after-wipe",
    "hyperframes/hw-pipeline-portrait": "hw-pipeline",
    "overlay-studio/pin-board": "pin-board",
    "huashu-motion/talking-head-stat": "huashu-stat",
    "motion-graphics-native/callout_pin": "callout-pin",
    "barty-motion-graphics/motion-broll": "barty-motion-graphics/motion-broll",
}
_DEPENDENCY = "hyperframes-native-adaptation"
_PINBOARD_DEPENDENCY = "overlay-studio-native"
_MOTION_GRAPHICS_DEPENDENCY = "motion-graphics-native"
_STRUCTURE = {"grid-card-assemble": "grid-list", "notification-stack": "notification-stack", "toggle-flip": "toggle-rail", "before-after-wipe": "before-after-split", "hw-pipeline": "process-chain", "pin-board": "pin-board"}
_STRUCTURE["huashu-stat"] = "single-metric"
_STRUCTURE["callout-pin"] = "target-callout"
_ACTION = {"grid-card-assemble": "staggered_card_reveal", "notification-stack": "notification_stack", "toggle-flip": "state_toggle", "before-after-wipe": "moving_split_reveal", "hw-pipeline": "three_node_process", "pin-board": "cumulative_pin_drop"}
_ACTION["huashu-stat"] = "native_count_up"
_ACTION["callout-pin"] = "ring_and_label_target"
_BARTY_ROUTE = 'barty-motion-graphics/motion-broll'
_REQUIRED = {"segment_id", "component_id", "intent_relation", "native_route", "visible_action", "visual_structure", "selection_reason"}

def _route(binding: Mapping) -> str:
    template = str(binding.get("template_id", ""))
    route = _ROUTE_BY_TEMPLATE.get(template)
    if route is None:
        raise ValueError(f"A-roll overlay template is not supported: {template}")
    return route

def validate_selection(draft: Mapping, treatment: Mapping | None, native_routes: Mapping) -> list[dict]:
    """Validate an explicit treatment declaration against frozen bindings."""
    expected: dict[tuple[str, str], tuple[Mapping, str, str]] = {}
    capabilities = None
    for segment in draft.get("segments", []):
        if segment.get("visual_strategy", {}).get("composition", {}).get("family") != "aroll_with_overlay":
            continue
        for component_id, binding in segment.get("bindings", {}).items():
            route = _route(binding)
            dependency = ("hyperframes" if route == "hw-pipeline" else
                          (_PINBOARD_DEPENDENCY if route == "pin-board" else
                           (_MOTION_GRAPHICS_DEPENDENCY if route == "callout-pin" else
                            ("huashu-motion-native" if route == "huashu-stat" else _DEPENDENCY))))
            if route == _BARTY_ROUTE:
                dependency = 'barty-motion-graphics'
            if binding.get("dependency_id") != dependency:
                raise ValueError("A-roll overlay dependency does not match the native adapter")
            from .motion_capabilities import overlay_candidates, validate_overlay_capability
            if capabilities is None:
                capabilities = {item["source_route"]: item for item in
                                overlay_candidates(Path(__file__).resolve().parents[3])}
            validate_overlay_capability(route, binding, registered=capabilities)
            key = (segment["segment_id"], component_id)
            if route != "hw-pipeline" and native_routes.get(key) != route:
                raise ValueError("A-roll template differs from the checked native brief route")
            expected[key] = (segment, route, _STRUCTURE.get(route))
    if not expected:
        if isinstance(treatment, Mapping) and (treatment.get("overlay_selection") or treatment.get("repeat_review")):
            raise ValueError("overlay_selection is not allowed without A-roll overlays")
        return []
    if not isinstance(treatment, Mapping) or not isinstance(treatment.get("overlay_selection"), list):
        raise ValueError("overlay_selection declaration is required")
    declared = treatment["overlay_selection"]
    if len(declared) != len(expected):
        raise ValueError("overlay_selection must cover every A-roll overlay exactly once")
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in declared:
        if not isinstance(row, Mapping) or set(row) - _REQUIRED - {"review_reason"} or not _REQUIRED <= set(row):
            raise ValueError("overlay_selection fields are incomplete")
        key = (row["segment_id"], row["component_id"])
        if key in seen or key not in expected:
            raise ValueError("overlay_selection target is missing or duplicated")
        _segment, route, structure = expected[key]
        if route == _BARTY_ROUTE:
            if row['native_route'] != route or any(not isinstance(row.get(k), str) or not row[k].strip()
                    for k in ('intent_relation', 'visible_action', 'visual_structure', 'selection_reason')):
                raise ValueError('Barty overlay needs its actual native action and semantic structure')
            seen.add(key)
            rows.append(dict(row))
            continue
        if row["native_route"] != route or row["visible_action"] != _ACTION[route] or row["visual_structure"] != structure:
            raise ValueError("overlay_selection does not match the native binding structure")
        allowed_relation = {"grid-card-assemble": "parallel", "notification-stack": "reminder", "toggle-flip": "state_change", "before-after-wipe": "compare", "hw-pipeline": "process", "pin-board": "parallel", "huashu-stat": "numeric_emphasis", "callout-pin": "callout"}[route]
        if row["intent_relation"] != allowed_relation:
            raise ValueError("intent_relation is not supported by the native route")
        if not isinstance(row["intent_relation"], str) or not row["intent_relation"].strip() or not isinstance(row["selection_reason"], str) or not row["selection_reason"].strip():
            raise ValueError("overlay_selection semantic declaration is incomplete")
        seen.add(key)
        rows.append(dict(row))
    counts = Counter((row["native_route"], row["visual_structure"]) for row in rows)
    repeated = [key for key, count in counts.items() if count > 1]
    review = treatment.get("repeat_review")
    if repeated:
        if not isinstance(review, list) or not review:
            raise ValueError("repeated native structure requires non-empty repeat_review")
        review_map = {}
        for item in review:
            if not isinstance(item, Mapping) or set(item) != {"native_route", "visual_structure", "reason"} or not all(isinstance(item[k], str) and item[k].strip() for k in item):
                raise ValueError("repeat_review entries require route, structure, and reason")
            key = (item["native_route"], item["visual_structure"])
            review_map[key] = item["reason"]
        if any(key not in review_map for key in repeated):
            raise ValueError("repeat_review does not explain every repeated structure")
        for row in rows:
            key = (row["native_route"], row["visual_structure"])
            if key in review_map:
                row["repeat_review_reason"] = review_map[key]
    return rows

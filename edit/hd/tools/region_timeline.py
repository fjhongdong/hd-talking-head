"""Deterministic 9:16 region timeline and event-level avoidance."""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

from .contract_artifacts import sha256_json


class RegionTimelineError(ValueError):
    """Raised when region evidence or an avoidance request is unsafe."""


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920


def _fail(message: str) -> None:
    raise RegionTimelineError(message)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _int(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _rect(value: object, label: str) -> dict[str, int]:
    if type(value) is not dict or set(value) != {"x", "y", "width", "height"}:
        _fail(f"{label} is invalid")
    rect = {key: _int(value[key], f"{label}.{key}") for key in value}
    if rect["width"] <= 0 or rect["height"] <= 0:
        _fail(f"{label} must have positive dimensions")
    if rect["x"] + rect["width"] > CANVAS_WIDTH or rect["y"] + rect["height"] > CANVAS_HEIGHT:
        _fail(f"{label} is outside the 1080x1920 canvas")
    return rect


def validate_region_timeline(value: object, *, expected_plan_sha256: str | None = None) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_version", "visual_plan_sha256", "regions", "timeline_sha256"
    }:
        _fail("region timeline fields are invalid")
    if value["schema_version"] != "region-timeline/v1":
        _fail("unsupported region timeline schema")
    visual_hash = _text(value["visual_plan_sha256"], "visual_plan_sha256")
    if expected_plan_sha256 is not None and visual_hash != expected_plan_sha256:
        _fail("region timeline belongs to a different visual plan")
    raw_regions = value["regions"]
    if type(raw_regions) is not list:
        _fail("regions must be a list")
    regions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_regions):
        if type(raw) is not dict or set(raw) != {
            "region_id", "role", "start_frame", "end_frame", "rect", "event_id"
        }:
            _fail(f"regions[{index}] fields are invalid")
        region_id = _text(raw["region_id"], f"regions[{index}].region_id")
        if region_id in seen:
            _fail("region_id values must be unique")
        seen.add(region_id)
        start = _int(raw["start_frame"], f"regions[{index}].start_frame")
        end = _int(raw["end_frame"], f"regions[{index}].end_frame")
        if end <= start:
            _fail(f"regions[{index}] must have a positive frame range")
        event_id = raw["event_id"]
        if event_id is not None:
            event_id = _text(event_id, f"regions[{index}].event_id")
        regions.append({
            "region_id": region_id,
            "role": _text(raw["role"], f"regions[{index}].role"),
            "start_frame": start,
            "end_frame": end,
            "rect": _rect(raw["rect"], f"regions[{index}].rect"),
            "event_id": event_id,
        })
    unsigned = {
        "schema_version": value["schema_version"],
        "visual_plan_sha256": visual_hash,
        "regions": regions,
    }
    if value["timeline_sha256"] != sha256_json(unsigned):
        _fail("region timeline hash does not match its contents")
    return {**unsigned, "timeline_sha256": value["timeline_sha256"]}


def build_region_timeline(*, visual_plan_sha256: str, regions: Iterable[Mapping[str, object]]) -> dict[str, Any]:
    unsigned = {
        "schema_version": "region-timeline/v1",
        "visual_plan_sha256": visual_plan_sha256,
        "regions": [copy.deepcopy(dict(item)) for item in regions],
    }
    unsigned["timeline_sha256"] = sha256_json(unsigned)
    return validate_region_timeline(unsigned, expected_plan_sha256=visual_plan_sha256)


def _overlap(first: Mapping[str, int], second: Mapping[str, int]) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def resolve_event_box(
    timeline: Mapping[str, object],
    *,
    event_id: str,
    start_frame: int,
    end_frame: int,
    requested: Mapping[str, object],
    avoid_roles: Iterable[str] = ("presenter", "forbidden"),
) -> dict[str, Any]:
    checked = validate_region_timeline(timeline)
    requested_rect = _rect(dict(requested), "requested")
    obstacles = [
        region for region in checked["regions"]
        if region["role"] in set(avoid_roles)
        and region["start_frame"] < end_frame
        and start_frame < region["end_frame"]
        and region["event_id"] != event_id
    ]
    candidates = [
        requested_rect,
        {**requested_rect, "x": (CANVAS_WIDTH - requested_rect["width"]) // 2, "y": 80},
        {**requested_rect, "x": (CANVAS_WIDTH - requested_rect["width"]) // 2, "y": CANVAS_HEIGHT - requested_rect["height"] - 80},
        {**requested_rect, "x": 80, "y": (CANVAS_HEIGHT - requested_rect["height"]) // 2},
        {**requested_rect, "x": CANVAS_WIDTH - requested_rect["width"] - 80, "y": (CANVAS_HEIGHT - requested_rect["height"]) // 2},
    ]
    for candidate in candidates:
        if candidate["x"] < 0 or candidate["y"] < 0 or candidate["x"] + candidate["width"] > CANVAS_WIDTH or candidate["y"] + candidate["height"] > CANVAS_HEIGHT:
            continue
        blockers = [region["region_id"] for region in obstacles if _overlap(candidate, region["rect"])]
        if not blockers:
            return {"status": "resolved", "event_id": event_id, "rect": candidate, "blockers": []}
    return {
        "status": "manual_review",
        "event_id": event_id,
        "rect": requested_rect,
        "blockers": [region["region_id"] for region in obstacles if _overlap(requested_rect, region["rect"])],
    }

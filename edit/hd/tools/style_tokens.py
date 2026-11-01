"""Shared V5 visual style tokens and scene-level validation."""

from __future__ import annotations

import math
import re
from typing import Any


FPS = 24
WIDTH = 1080
HEIGHT = 1920
TOTAL_SECONDS = 30
TOTAL_FRAMES = FPS * TOTAL_SECONDS
TRANSITION_FRAMES = 12

PALETTE = {
    "ink": "#15152F",
    "cream": "#FFF5DF",
    "cobalt": "#4B5CFF",
    "yellow": "#FFD43B",
    "coral": "#FF5F55",
    "mint": "#42D6BD",
}
TITLE_SIZE_RANGE = range(72, 105)
SUBTITLE_SIZE_RANGE = range(56, 77)

ALLOWED_TRANSITIONS = {
    "none",
    "circle_expand",
    "color_wipe_left",
    "color_wipe_right",
    "color_wipe_up",
}
ALLOWED_LAYOUTS = {
    "full_speaker_minimal",
    "asset_avatar",
    "asset_cutout_edge",
    "full_speaker_emphasis",
    "official_evidence_full",
    "top_asset_bottom_speaker",
}

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SCENE_FIELDS = {
    "id",
    "chapter",
    "spoken_text",
    "semantic_reason",
    "source_scene_id",
    "start",
    "end",
    "start_frame",
    "end_frame",
    "editorial_layout",
    "asset_id",
    "background_source",
    "person_dynamic",
    "transition",
    "transition_frames",
    "primary_accent",
    "secondary_accent",
}


class StyleContractError(ValueError):
    """Raised when a scene violates the V5 style contract."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StyleContractError(f"{field} must be a finite number")
    if not math.isfinite(value):
        raise StyleContractError(f"{field} must be a finite number")
    return float(value)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StyleContractError(f"{field} must be an integer")
    return value


def _safe_id(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise StyleContractError(f"{field} must be a filesystem-safe id")
    return value


def validate_scene_style(scene: object) -> dict:
    """Validate and return one V5 scene without mutating it."""
    if not isinstance(scene, dict):
        raise StyleContractError("scene must be a JSON object")
    missing = SCENE_FIELDS - scene.keys()
    extra = scene.keys() - SCENE_FIELDS
    if missing:
        raise StyleContractError(f"missing scene field: {sorted(missing)[0]}")
    if extra:
        raise StyleContractError(
            f"unsupported scene field: {min(repr(field) for field in extra)}"
        )

    _safe_id(scene["id"], "id")
    _safe_id(scene["source_scene_id"], "source_scene_id")
    _safe_id(scene["asset_id"], "asset_id", nullable=True)
    for field in ("chapter", "spoken_text", "semantic_reason"):
        if not isinstance(scene[field], str) or not scene[field].strip():
            raise StyleContractError(f"{field} must be non-empty text")

    start = _finite_number(scene["start"], "start")
    end = _finite_number(scene["end"], "end")
    start_frame = _integer(scene["start_frame"], "start_frame")
    end_frame = _integer(scene["end_frame"], "end_frame")
    if not 0 <= start < end <= TOTAL_SECONDS:
        raise StyleContractError("scene timing must stay within the 30-second timeline")
    if not 0 <= start_frame < end_frame <= TOTAL_FRAMES:
        raise StyleContractError("scene frames must stay within the 720-frame timeline")
    if start_frame != round(start * FPS) or end_frame != round(end * FPS):
        raise StyleContractError("scene frames must exactly match timing at 24 fps")

    layout = scene["editorial_layout"]
    if not isinstance(layout, str) or layout not in ALLOWED_LAYOUTS:
        raise StyleContractError(f"unsupported editorial_layout: {layout}")
    transition = scene["transition"]
    if not isinstance(transition, str) or transition not in ALLOWED_TRANSITIONS:
        raise StyleContractError(f"unsupported transition: {transition}")
    transition_frames = _integer(scene["transition_frames"], "transition_frames")
    expected_frames = 0 if transition == "none" else TRANSITION_FRAMES
    if transition_frames != expected_frames:
        raise StyleContractError(
            f"transition_frames must be {expected_frames} for {transition}"
        )

    palette_values = set(PALETTE.values())
    primary = scene["primary_accent"]
    secondary = scene["secondary_accent"]
    if not isinstance(primary, str) or primary not in palette_values:
        raise StyleContractError("primary_accent must come from the V5 palette")
    if secondary is not None and (
        not isinstance(secondary, str) or secondary not in palette_values
    ):
        raise StyleContractError("secondary_accent must be null or come from the V5 palette")
    if secondary == primary:
        raise StyleContractError("secondary_accent must differ from primary_accent")
    if scene["person_dynamic"] is not True:
        raise StyleContractError("person_dynamic must be true")
    if scene["background_source"] != "clean_base":
        raise StyleContractError("background_source must be clean_base")
    return scene

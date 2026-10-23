#!/usr/bin/env python3
"""Validate and render the V5 bold subtitle alpha track."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    from .build_visual_plan import VisualPlanError, validate_plan as validate_v5_visual_plan
    from .bold_layouts import LayoutError, display_title
except ImportError:  # pragma: no cover - direct CLI execution
    from build_visual_plan import VisualPlanError, validate_plan as validate_v5_visual_plan
    from bold_layouts import LayoutError, display_title


FPS = 24
WIDTH = 1080
HEIGHT = 1920
TOTAL_FRAMES = 720
SAFE_MARGIN = 44
TEXT_X = 80
TEXT_MAX_WIDTH = WIDTH - 2 * TEXT_X
STYLES = frozenset({"bold_statement", "keyword_block", "cardless_caption"})
EXPECTED_STYLE_COUNTS = {
    "bold_statement": 3,
    "keyword_block": 4,
    "cardless_caption": 2,
}
CARDLESS_SCENES = frozenset({"v5-005", "v5-006"})
PALETTE = {
    "ink": (21, 21, 47, 255),
    "cream": (255, 245, 223, 255),
    "yellow": (255, 212, 59, 255),
    "coral": (255, 95, 85, 255),
    "mint": (66, 214, 189, 255),
    "white": (255, 255, 255, 255),
}

_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path(__file__).resolve().parents[3] / "skill-development/vendor/adu-motion-video/assets/fonts/NotoSansSC.ttf",
)
_PLAN_KEYS = {
    "version", "fps", "width", "height", "frame_count", "duration_s",
    "style_counts", "cues",
}
_CUE_KEYS = {
    "id", "scene_id", "start_s", "end_s", "text", "style", "keyword",
    "keyword_start_s", "label", "accent", "font_size", "shadow_px",
    "card_opacity", "entry_easing", "entry_scale", "stable_frames",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ALPHA_MIN = re.compile(r"lavfi\.signalstats\.YMIN=(\d+(?:\.\d+)?)")
_ALPHA_MAX = re.compile(r"lavfi\.signalstats\.YMAX=(\d+(?:\.\d+)?)")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GENERATION = re.compile(r"^[0-9a-f]{24}$")
_MARKER_KEYS = {
    "generation", "target", "stage", "backup", "new_sha256", "old_sha256", "state",
}


class SubtitleError(RuntimeError):
    """A clean V5 subtitle contract or delivery failure."""


@dataclass
class TargetLock:
    descriptor: int
    directory_fd: int
    name: str
    guard: str
    status: os.stat_result

    def verify(self) -> None:
        try:
            locked = os.fstat(self.descriptor)
            current = os.stat(self.name, dir_fd=self.directory_fd, follow_symlinks=False)
            guarded = os.stat(self.guard, dir_fd=self.directory_fd, follow_symlinks=False)
        except OSError:
            raise SubtitleError("subtitle target lock identity changed") from None
        if (
            not stat.S_ISREG(locked.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or not stat.S_ISREG(guarded.st_mode)
            or not os.path.samestat(locked, self.status)
            or not os.path.samestat(locked, current)
            or not os.path.samestat(locked, guarded)
        ):
            raise SubtitleError("subtitle target lock identity changed")

    def close(self) -> None:
        if self.descriptor < 0:
            return
        descriptor = self.descriptor
        self.descriptor = -1
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _finite(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise SubtitleError("text to normalize must be a string")
    return "".join(character.casefold() for character in value if character.isalnum())


def _lines(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        raise SubtitleError("subtitle text must be non-empty")
    lines = text.splitlines()
    endings = text.splitlines(keepends=True)
    trailing_break = bool(endings) and (not lines or endings[-1] != lines[-1])
    if trailing_break or len(lines) not in {1, 2} or any(not line.strip() for line in lines):
        raise SubtitleError("subtitle text must contain one or two non-empty lines")
    if len(lines) == 2 and normalize_text(lines[0]) == normalize_text(lines[1]):
        raise SubtitleError("subtitle may not repeat the same sentence at top and bottom")
    return lines


def validate_plan(payload: object, duration: float) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) != _PLAN_KEYS:
        raise SubtitleError("subtitle plan has an invalid top-level shape")
    if not _finite(duration) or duration <= 0:
        raise SubtitleError("render duration must be finite and positive")
    if (
        type(payload["version"]) is not int or payload["version"] != 5
        or type(payload["fps"]) is not int or payload["fps"] != FPS
        or type(payload["width"]) is not int or payload["width"] != WIDTH
        or type(payload["height"]) is not int or payload["height"] != HEIGHT
        or type(payload["frame_count"]) is not int or payload["frame_count"] != TOTAL_FRAMES
        or not _finite(payload["duration_s"]) or float(payload["duration_s"]) != float(duration)
    ):
        raise SubtitleError("subtitle plan must be V5 at 1080x1920, 24 fps and 30 seconds")
    counts = payload["style_counts"]
    if (
        not isinstance(counts, dict) or set(counts) != set(EXPECTED_STYLE_COUNTS)
        or any(type(counts[key]) is not int for key in EXPECTED_STYLE_COUNTS)
        or counts != EXPECTED_STYLE_COUNTS
    ):
        raise SubtitleError("subtitle plan style counts do not match the V5 contract")
    cues = payload["cues"]
    if not isinstance(cues, list) or len(cues) != 9:
        raise SubtitleError("subtitle plan must contain exactly nine cues")

    seen: set[str] = set()
    previous_end = 0.0
    actual_counts = {style: 0 for style in STYLES}
    cardless_scenes: set[str] = set()
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or set(cue) != _CUE_KEYS:
            raise SubtitleError(f"cue {index} has an invalid shape")
        cue_id = cue["id"]
        scene_id = cue["scene_id"]
        if (
            not isinstance(cue_id, str) or not _SAFE_ID.fullmatch(cue_id)
            or cue_id in seen or not isinstance(scene_id, str)
            or not _SAFE_ID.fullmatch(scene_id)
        ):
            raise SubtitleError(f"cue {index} ids are invalid")
        seen.add(cue_id)
        start = cue["start_s"]
        end = cue["end_s"]
        if (
            not _finite(start) or not _finite(end) or start < previous_end
            or start < 0 or end <= start or end > duration
        ):
            raise SubtitleError(f"cue {cue_id} timing is invalid")
        previous_end = float(end)
        lines = _lines(cue["text"])

        style = cue["style"]
        if not isinstance(style, str) or style not in STYLES:
            raise SubtitleError(f"cue {cue_id} style is invalid")
        actual_counts[style] += 1
        font_size = cue["font_size"]
        if type(font_size) is not int or not 56 <= font_size <= 76:
            raise SubtitleError(f"cue {cue_id} font size must be 56..76")
        if cue["entry_easing"] != "ease_out_cubic":
            raise SubtitleError(f"cue {cue_id} must use ease_out_cubic")
        if (
            not _finite(cue["entry_scale"]) or not 1.0 <= cue["entry_scale"] <= 1.04
            or type(cue["stable_frames"]) is not int or cue["stable_frames"] < 24
        ):
            raise SubtitleError(f"cue {cue_id} motion exceeds the restrained contract")

        keyword = cue["keyword"]
        keyword_start = cue["keyword_start_s"]
        label = cue["label"]
        accent = cue["accent"]
        shadow = cue["shadow_px"]
        opacity = cue["card_opacity"]
        if type(shadow) is not int or type(opacity) is not int:
            raise SubtitleError(f"cue {cue_id} pixel fields must be exact integers")
        compact = "".join(lines)
        if style == "bold_statement":
            if (
                not isinstance(label, str) or not label.strip() or accent != "coral"
                or keyword is not None or keyword_start is not None
                or shadow != 0 or opacity != 255
            ):
                raise SubtitleError(f"cue {cue_id} bold statement contract is invalid")
        elif style == "keyword_block":
            if (
                label is not None or accent not in {"yellow", "mint"}
                or not isinstance(keyword, str) or not keyword
                or compact.count(keyword) != 1 or shadow != 0 or opacity != 255
                or not _finite(keyword_start) or keyword_start < start or keyword_start >= end
            ):
                raise SubtitleError(f"cue {cue_id} keyword contract is invalid")
        else:
            cardless_scenes.add(scene_id)
            if (
                scene_id not in CARDLESS_SCENES or label is not None or accent is not None
                or keyword is not None or keyword_start is not None
                or type(shadow) is not int or not 3 <= shadow <= 5 or opacity != 0
            ):
                raise SubtitleError(f"cue {cue_id} cardless caption contract is invalid")
    if actual_counts != EXPECTED_STYLE_COUNTS:
        raise SubtitleError("subtitle cues do not match the declared style counts")
    if cardless_scenes != CARDLESS_SCENES:
        raise SubtitleError("cardless captions must be assigned to v5-005 and v5-006")
    return cues


def significant_title_overlap(title: str, subtitle: str) -> bool:
    """Detect exact or meaningful containment without flagging words like AI."""
    normalized_title = normalize_text(title)
    candidates = [normalize_text(subtitle)]
    if isinstance(subtitle, str):
        candidates.extend(normalize_text(line) for line in subtitle.splitlines())
    for candidate in candidates:
        if not normalized_title or not candidate:
            continue
        if normalized_title == candidate:
            return True
        shorter = min(len(normalized_title), len(candidate))
        if shorter >= 4 and (
            normalized_title in candidate or candidate in normalized_title
        ):
            return True
    return False


def validate_visual_titles(
    visual_plan: object, cues: list[dict], duration: float
) -> dict[str, str]:
    if not isinstance(cues, list) or not _finite(duration) or duration <= 0:
        raise SubtitleError("visual title validation input is invalid")
    try:
        validated_visual = validate_v5_visual_plan(visual_plan)
    except VisualPlanError as error:
        raise SubtitleError(f"visual plan contract is invalid: {error}") from error
    checked_cues = []
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise SubtitleError(f"subtitle cue {index} must be an object")
        start, end, text = cue.get("start_s"), cue.get("end_s"), cue.get("text")
        if not _finite(start) or not _finite(end) or not isinstance(text, str):
            raise SubtitleError(f"subtitle cue {index} is malformed")
        checked_cues.append((float(start), float(end), text))
    titles: dict[str, str] = {}
    for index, scene in enumerate(validated_visual["scenes"]):
        if not isinstance(scene, dict):
            raise SubtitleError(f"visual scene {index} must be an object")
        start, end = scene.get("start"), scene.get("end")
        if not _finite(start) or not _finite(end) or start < 0 or end <= start:
            raise SubtitleError(f"visual scene {index} timing is invalid")
        if scene.get("editorial_layout") not in {
            "full_speaker_minimal", "full_speaker_emphasis",
        }:
            continue
        try:
            rendered_title = display_title(scene)
        except LayoutError as error:
            raise SubtitleError(f"visual scene {index} title is invalid: {error}") from error
        titles[scene["id"]] = rendered_title
        for cue_start, cue_end, subtitle in checked_cues:
            if cue_start < min(float(end), float(duration)) and cue_end > float(start):
                if significant_title_overlap(rendered_title, subtitle):
                    raise SubtitleError(f"visual scene {index} title duplicates an active subtitle")
    return titles


def resolve_evidence_scenes(cues: list[dict], visual_plan: object) -> dict[str, dict]:
    """Bind every evidence frame to the scene id declared by its subtitle cue."""
    try:
        validated = validate_v5_visual_plan(visual_plan)
    except VisualPlanError as error:
        raise SubtitleError(f"visual plan contract is invalid: {error}") from error
    scenes = {scene["id"]: scene for scene in validated["scenes"]}
    mapping: dict[str, dict] = {}
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise SubtitleError(f"subtitle cue {index} must be an object")
        cue_id = cue.get("id")
        scene_id = cue.get("scene_id")
        if not isinstance(cue_id, str) or cue_id in mapping or scene_id not in scenes:
            raise SubtitleError(f"subtitle cue {index} has an invalid evidence scene")
        mapping[cue_id] = scenes[scene_id]
    return mapping


def validate_cue_scene_bindings(cues: list[dict], visual_plan: object) -> dict[str, dict]:
    """Validate the one permitted boundary-crossing rule for all nine cues.

    A cue may be wholly inside its declared scene. It may start in the immediately
    preceding scene only when it crosses the declared scene's start, and it may
    never extend beyond the declared scene's end. This uniquely binds the V4
    semantic timings to the eight V5 scene intervals without changing the copy.
    """
    mapping = resolve_evidence_scenes(cues, visual_plan)
    try:
        validated = validate_v5_visual_plan(visual_plan)
    except VisualPlanError as error:
        raise SubtitleError(f"visual plan contract is invalid: {error}") from error
    scenes = validated["scenes"]
    positions = {scene["id"]: index for index, scene in enumerate(scenes)}
    if len(cues) != 9 or len(mapping) != 9:
        raise SubtitleError("subtitle scene binding must cover exactly nine cues")
    for cue in cues:
        scene = mapping[cue["id"]]
        index = positions[scene["id"]]
        cue_start, cue_end = float(cue["start_s"]), float(cue["end_s"])
        scene_start, scene_end = scene.get("start"), scene.get("end")
        if not _finite(scene_start) or not _finite(scene_end):
            raise SubtitleError(f"cue {cue['id']} scene binding has invalid timing")
        scene_start, scene_end = float(scene_start), float(scene_end)
        inside = cue_start >= scene_start and cue_end <= scene_end
        crossing = False
        if index > 0:
            previous = scenes[index - 1]
            previous_start = previous.get("start")
            crossing = (
                _finite(previous_start)
                and float(previous_start) <= cue_start < scene_start < cue_end <= scene_end
            )
        if not inside and not crossing:
            raise SubtitleError(f"cue {cue['id']} scene binding violates the boundary rule")
    return mapping


def _glyph_signature(font: ImageFont.FreeTypeFont, character: str) -> tuple:
    mask = font.getmask(character)
    return mask.size, bytes(mask)


def _font_supports(font: ImageFont.FreeTypeFont, text: str) -> bool:
    missing = {
        _glyph_signature(font, marker) for marker in ("\U0010ffff", "\uffff", "\ufffd")
    }
    return all(
        character.isspace() or _glyph_signature(font, character) not in missing
        for character in set(text)
    )


@lru_cache(maxsize=32)
def find_cjk_font(required_text: str) -> Path:
    if not isinstance(required_text, str) or not required_text:
        raise SubtitleError("required font text must be non-empty")
    for candidate in _FONT_CANDIDATES:
        if not candidate.is_file():
            continue
        try:
            font = ImageFont.truetype(str(candidate), size=32)
        except OSError:
            continue
        if _font_supports(font, required_text):
            return candidate
    raise SubtitleError("a CJK-capable subtitle font is required")


@lru_cache(maxsize=256)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size)
    except OSError as error:
        raise SubtitleError(f"cannot load subtitle font: {path}") from error


def _width(font: ImageFont.FreeTypeFont, text: str) -> int:
    left, _, right, _ = font.getbbox(text)
    return right - left


def _best_split(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str] | None:
    stripped = text.strip()
    candidates = []
    for index in range(1, len(stripped)):
        left = stripped[:index].rstrip()
        right = stripped[index:].lstrip()
        if not left or not right:
            continue
        widths = (_width(font, left), _width(font, right))
        if max(widths) <= max_width:
            candidates.append((max(widths), abs(widths[0] - widths[1]), [left, right]))
    return min(candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def layout_text(
    text: str,
    *,
    font_path: Path,
    preferred_size: int,
    min_size: int,
    max_width: int,
) -> dict[str, Any]:
    if (
        not isinstance(text, str) or not text.strip() or not isinstance(font_path, Path)
        or type(preferred_size) is not int or type(min_size) is not int
        or type(max_width) is not int or preferred_size < min_size or min_size <= 0
        or max_width <= 0
    ):
        raise SubtitleError("text layout input is invalid")
    explicit = _lines(text)
    for size in range(preferred_size, min_size - 1, -1):
        font = _font(str(font_path), size)
        if len(explicit) == 2:
            if all(_width(font, line) <= max_width for line in explicit):
                return {"lines": explicit, "font_size": size}
            continue
        if _width(font, explicit[0]) <= max_width:
            return {"lines": explicit, "font_size": size}
        split = _best_split(explicit[0], font, max_width)
        if split is not None:
            return {"lines": split, "font_size": size}
    raise SubtitleError("subtitle text cannot fit two lines inside the safe area")


def ease_out_cubic(value: float) -> float:
    clamped = min(1.0, max(0.0, value))
    return 1 - (1 - clamped) ** 3


def keyword_animation_window(cue: dict) -> tuple[float, float] | None:
    """Fit one emphasis window before the cue's final 24 stable frames."""
    start = cue.get("keyword_start_s") if isinstance(cue, dict) else None
    end = cue.get("end_s") if isinstance(cue, dict) else None
    stable_frames = cue.get("stable_frames") if isinstance(cue, dict) else None
    if (
        cue.get("style") != "keyword_block" or not _finite(start) or not _finite(end)
        or type(stable_frames) is not int or stable_frames < 24
    ):
        return None
    stable_start = float(end) - stable_frames / FPS
    available = max(0.0, stable_start - float(start))
    duration = min(0.36, max(0.18, available))
    window_end = min(float(start) + duration, stable_start)
    window_start = max(float(cue["start_s"]), window_end - duration)
    if window_end <= window_start:
        return None
    return window_start, window_end


def keyword_scale(cue: dict, timestamp: float) -> float:
    window = keyword_animation_window(cue)
    if window is None or not _finite(timestamp):
        return 1.0
    start, end = window
    duration = end - start
    elapsed = float(timestamp) - start
    if elapsed <= 0 or elapsed >= duration - 1e-9:
        return 1.0
    rise = duration / 3
    if elapsed <= rise:
        return 1.0 + 0.04 * ease_out_cubic(elapsed / rise)
    return 1.04 - 0.04 * ease_out_cubic((elapsed - rise) / (duration - rise))


def _required_text(cues: list[dict]) -> str:
    pieces = ["POINT SOURCE ACTION"]
    for cue in cues:
        for key in ("text", "label", "keyword"):
            if isinstance(cue.get(key), str):
                pieces.append(cue[key])
    return "".join(pieces)


def _active_cue(cues: list[dict], timestamp: float) -> dict | None:
    if not _finite(timestamp):
        raise SubtitleError("subtitle timestamp must be finite")
    return next(
        (cue for cue in cues if float(cue["start_s"]) <= timestamp < float(cue["end_s"])),
        None,
    )


def _opacity(progress: float) -> int:
    return round(255 * ease_out_cubic(progress))


def _tinted(color: tuple[int, int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return color[:3] + (round(color[3] * alpha / 255),)


def _draw_checked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
) -> None:
    left, _, right, _ = draw.textbbox(xy, text, font=font)
    if left < SAFE_MARGIN or right > WIDTH - SAFE_MARGIN:
        raise SubtitleError(f"subtitle text escaped the 44px safe area: {text}")
    draw.text(xy, text, font=font, fill=fill)


def _draw_lines(
    layer: Image.Image,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    *,
    y: int,
    fill: tuple[int, int, int, int],
    line_gap: int = 88,
) -> None:
    draw = ImageDraw.Draw(layer)
    for index, line in enumerate(lines):
        _draw_checked(draw, (TEXT_X, y + index * line_gap), line, font=font, fill=fill)


def _layer_alpha(layer: Image.Image, alpha: int) -> Image.Image:
    if alpha >= 255:
        return layer
    adjusted = layer.copy()
    adjusted.putalpha(adjusted.getchannel("A").point(lambda value: round(value * alpha / 255)))
    return adjusted


def _keyword_line(
    layer: Image.Image,
    *,
    line: str,
    keyword: str,
    y: int,
    font_path: Path,
    size: int,
    scale: float,
    accent: tuple[int, int, int, int],
    body_alpha: int,
    keyword_alpha: int,
) -> None:
    draw = ImageDraw.Draw(layer)
    normal = _font(str(font_path), size)
    if keyword not in line:
        _draw_checked(draw, (TEXT_X, y), line, font=normal, fill=_tinted(PALETTE["cream"], body_alpha))
        return
    prefix, suffix = line.split(keyword, 1)
    x = TEXT_X
    if prefix:
        _draw_checked(draw, (x, y), prefix, font=normal, fill=_tinted(PALETTE["cream"], body_alpha))
        x += _width(normal, prefix)
    emphasized = _font(str(font_path), max(56, round(size * scale)))
    keyword_y = y - max(0, (emphasized.size - normal.size) // 2)
    _draw_checked(draw, (x, keyword_y), keyword, font=emphasized, fill=_tinted(accent, keyword_alpha))
    x += _width(emphasized, keyword)
    if suffix:
        _draw_checked(draw, (x, y), suffix, font=normal, fill=_tinted(PALETTE["cream"], body_alpha))


def render_frame(cues: list[dict], timestamp: float) -> Image.Image:
    """Render one transparent 1080x1920 frame, with subtitles as the final layer."""
    frame = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    cue = _active_cue(cues, timestamp)
    if cue is None:
        return frame
    font_path = find_cjk_font(_required_text(cues))
    layout = layout_text(
        cue["text"], font_path=font_path, preferred_size=cue["font_size"],
        min_size=56, max_width=TEXT_MAX_WIDTH,
    )
    font = _font(str(font_path), layout["font_size"])
    elapsed_frames = max(0.0, (timestamp - float(cue["start_s"])) * FPS)
    panel_alpha = _opacity(elapsed_frames / 5)
    body_alpha = _opacity((elapsed_frames - 2) / 6)
    keyword_alpha = _opacity((elapsed_frames - 5) / 5)
    y_shift = round(18 * (1 - ease_out_cubic(elapsed_frames / 8)))
    style = cue["style"]
    safe_crossing_caption = cue["id"] == "sub-v5-007"

    if style == "bold_statement":
        panel = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(panel)
        draw.rounded_rectangle((54, 1442 + y_shift, 1026, 1856 + y_shift), radius=32, fill=PALETTE["cream"])
        draw.rounded_rectangle((80, 1474 + y_shift, 286, 1542 + y_shift), radius=18, fill=PALETTE["coral"])
        label_font = _font(str(font_path), 32)
        _draw_checked(draw, (100, 1490 + y_shift), cue["label"], font=label_font, fill=PALETTE["cream"])
        frame.alpha_composite(_layer_alpha(panel, panel_alpha))
        body = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        _draw_lines(body, layout["lines"], font, y=1580 + y_shift, fill=PALETTE["ink"], line_gap=92)
        frame.alpha_composite(_layer_alpha(body, body_alpha))
    elif style == "keyword_block" and not safe_crossing_caption:
        panel = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(panel)
        draw.rounded_rectangle((54, 1460 + y_shift, 1026, 1852 + y_shift), radius=28, fill=PALETTE["ink"])
        draw.rectangle((54, 1460 + y_shift, 1026, 1478 + y_shift), fill=PALETTE[cue["accent"]])
        frame.alpha_composite(_layer_alpha(panel, panel_alpha))
        body = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        scale = keyword_scale(cue, timestamp)
        for index, line in enumerate(layout["lines"]):
            _keyword_line(
                body, line=line, keyword=cue["keyword"], y=1570 + y_shift + index * 94,
                font_path=font_path, size=layout["font_size"], scale=scale,
                accent=PALETTE[cue["accent"]], body_alpha=body_alpha,
                keyword_alpha=keyword_alpha,
            )
        frame.alpha_composite(body)
    elif style == "cardless_caption" or safe_crossing_caption:
        # The split layout leaves a clear wall band immediately below its 96 px
        # gradient. The crossing cue stays in that band through the following
        # wipe so it neither covers the face nor breaks its final stable tail.
        cardless_y = 920 if safe_crossing_caption else (980 if cue["scene_id"] == "v5-006" else 1642)
        shadow_px = 4 if safe_crossing_caption else cue["shadow_px"]
        caption_alpha = max(panel_alpha, body_alpha) if safe_crossing_caption else body_alpha
        shadow = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        for index, line in enumerate(layout["lines"]):
            _draw_checked(
                shadow_draw,
                (TEXT_X + shadow_px, cardless_y + y_shift + index * 88 + shadow_px),
                line, font=font, fill=(8, 10, 24, 190),
            )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=shadow_px))
        frame.alpha_composite(_layer_alpha(shadow, caption_alpha))
        body = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        _draw_lines(body, layout["lines"], font, y=cardless_y + y_shift, fill=PALETTE["cream"], line_gap=88)
        frame.alpha_composite(_layer_alpha(body, caption_alpha))
    else:
        raise SubtitleError(f"unsupported subtitle style: {style}")
    return frame


_DEFAULT_FRAME_RENDERER = render_frame


def _close(pipe: object) -> None:
    try:
        pipe.close()
    except BaseException:
        pass


def _reap(process: subprocess.Popen) -> None:
    _close(process.stdin)
    _close(process.stderr)
    try:
        process.terminate()
    except BaseException:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except BaseException:
            pass
        try:
            process.wait()
        except BaseException:
            pass
    except BaseException:
        try:
            process.kill()
        except BaseException:
            pass
        try:
            process.wait()
        except BaseException:
            pass


def encode_webm(
    cues: list[dict],
    descriptor: int,
    duration: float,
    *,
    frame_renderer: Callable[[list[dict], float], Image.Image] = render_frame,
) -> None:
    """Encode into the already-created stage inode through an inherited fd."""
    if type(descriptor) is not int or descriptor < 0 or not _finite(duration) or duration <= 0:
        raise SubtitleError("subtitle encoder input is invalid")
    frames = round(float(duration) * FPS)
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
        "-fflags", "+bitexact",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-deadline", "realtime",
        "-cpu-used", "8", "-row-mt", "1", "-crf", "22", "-b:v", "0",
        "-flags:v", "+bitexact", "-bitexact", "-map_metadata", "-1",
        "-metadata", "creation_time=1970-01-01T00:00:00Z",
        "-write_crc32", "0", "-frames:v", str(frames),
        "-f", "webm", f"pipe:{descriptor}",
    ]
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, pass_fds=(descriptor,),
        )
    except FileNotFoundError as error:
        raise SubtitleError("required command is unavailable: ffmpeg") from error
    assert process.stdin is not None and process.stderr is not None
    try:
        renderer = (
            render_frame if frame_renderer is _DEFAULT_FRAME_RENDERER else frame_renderer
        )
        for frame_index in range(frames):
            process.stdin.write(renderer(cues, frame_index / FPS).tobytes())
        process.stdin.close()
        detail = process.stderr.read().decode("utf-8", errors="replace").strip()
        return_code = process.wait()
    except BaseException:
        _reap(process)
        raise
    process.stderr.close()
    if return_code != 0:
        raise SubtitleError(detail.splitlines()[-1] if detail else "subtitle encoding failed")
    os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)


def _run(command: list[str], *, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, pass_fds=pass_fds,
        )
    except FileNotFoundError as error:
        raise SubtitleError(f"required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "command failed").strip().splitlines()
        raise SubtitleError(detail[-1] if detail else "command failed") from error


def validate_webm_fd(descriptor: int, frames: int) -> dict[str, int | str]:
    if type(descriptor) is not int or descriptor < 0 or type(frames) is not int or frames <= 0:
        raise SubtitleError("subtitle validation input is invalid")
    status = os.fstat(descriptor)
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_size <= 0:
        raise SubtitleError("subtitle track must be one non-empty regular file")
    source = f"/dev/fd/{descriptor}"
    probe = _run([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_name,codec_type,width,height,r_frame_rate,nb_read_frames:stream_tags=alpha_mode",
        "-of", "json", source,
    ], pass_fds=(descriptor,))
    try:
        streams = json.loads(probe.stdout)["streams"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SubtitleError("cannot parse subtitle track metadata") from error
    if not isinstance(streams, list) or len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise SubtitleError("subtitle track must contain one video stream and no audio")
    video = streams[0]
    expected = {
        "codec_name": "vp9", "width": WIDTH, "height": HEIGHT,
        "r_frame_rate": f"{FPS}/1", "nb_read_frames": str(frames),
    }
    if any(video.get(key) != value for key, value in expected.items()):
        raise SubtitleError(f"subtitle track does not match delivery spec: {video}")
    if video.get("tags", {}).get("alpha_mode") != "1":
        raise SubtitleError("subtitle track is missing VP9 alpha metadata")
    os.lseek(descriptor, 0, os.SEEK_SET)
    decoded = _run([
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        "-c:v", "libvpx-vp9", "-i", source, "-map", "0:v:0",
        "-vf", "format=rgba,alphaextract,signalstats,metadata=print:file=-",
        "-f", "null", "-",
    ], pass_fds=(descriptor,))
    minima = [float(value) for value in _ALPHA_MIN.findall(decoded.stdout)]
    maxima = [float(value) for value in _ALPHA_MAX.findall(decoded.stdout)]
    if not minima or not maxima:
        raise SubtitleError("cannot inspect subtitle alpha values")
    alpha_min, alpha_max = round(min(minima)), round(max(maxima))
    if (alpha_min, alpha_max) != (0, 255):
        raise SubtitleError(f"subtitle alpha range must span 0..255, got {alpha_min}..{alpha_max}")
    return {
        "codec": "vp9", "width": WIDTH, "height": HEIGHT, "fps": FPS,
        "frames": frames, "alpha_min": alpha_min, "alpha_max": alpha_max,
    }


def _raw_parent_traversal(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _unsafe_symlink(path: Path, *, include_leaf: bool) -> bool:
    absolute = path.absolute()
    candidates = (absolute, *absolute.parents) if include_leaf else tuple(absolute.parents)
    for candidate in candidates:
        if candidate.parent == Path(candidate.anchor):
            continue
        try:
            if candidate.is_symlink():
                return True
        except OSError:
            return True
    return False


def _safe_regular(path: Path, label: str) -> os.stat_result:
    if not isinstance(path, Path) or _raw_parent_traversal(path) or _unsafe_symlink(path, include_leaf=True):
        raise SubtitleError(f"{label} path contains an unsafe component")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise SubtitleError(f"cannot open {label} safely") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SubtitleError(f"{label} must be one regular unaliased file")
        return status
    finally:
        os.close(descriptor)


def _load_json(value: object, label: str) -> tuple[object, Path | None, os.stat_result | None]:
    if not isinstance(value, Path):
        return value, None, None
    if _raw_parent_traversal(value) or _unsafe_symlink(value, include_leaf=True):
        raise SubtitleError(f"{label} path contains an unsafe component")
    descriptor: int | None = None
    try:
        descriptor = os.open(value, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = None
            status = os.fstat(handle.fileno())
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise SubtitleError(f"{label} must be one regular unaliased file")
            payload = json.load(
                handle,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            after = os.fstat(handle.fileno())
            if not os.path.samestat(status, after) or after.st_nlink != 1:
                raise SubtitleError(f"{label} changed while it was being read")
    except (OSError, json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise SubtitleError(f"cannot read {label}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return payload, value, status


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parent_is_attached(parent: Path, descriptor: int, expected: os.stat_result) -> bool:
    try:
        current = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return False
    try:
        return os.path.samestat(os.fstat(current), expected) and os.path.samestat(os.fstat(descriptor), expected)
    finally:
        os.close(current)


def _open_parent(output: Path) -> tuple[int, os.stat_result]:
    if (
        not isinstance(output, Path) or _raw_parent_traversal(output)
        or output.suffix.lower() != ".webm" or _unsafe_symlink(output, include_leaf=False)
        or output.is_symlink()
    ):
        raise SubtitleError("subtitle output path is unsafe or is not .webm")
    if not output.parent.is_dir():
        raise SubtitleError("subtitle output parent must be an existing directory")
    try:
        descriptor = os.open(
            output.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise SubtitleError("cannot open subtitle output parent safely") from error
    expected = os.fstat(descriptor)
    return descriptor, expected


def _entry_status(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _unlink(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def _copy_at(directory_fd: int, source: str, target: str) -> None:
    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    target_fd = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600, dir_fd=directory_fd,
    )
    try:
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            if (
                target.endswith(".restore.webm")
                and os.environ.get("V5_SUBTITLE_CRASH_POINT") == "during_recovery_mid_restore"
            ):
                os.write(target_fd, chunk[:max(1, len(chunk) // 2)])
                os._exit(87)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                view = view[written:]
        os.fsync(target_fd)
    finally:
        os.close(source_fd)
        os.close(target_fd)


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.lseek(descriptor, offset, os.SEEK_SET)
    return digest.hexdigest()


def _sha256_at(directory_fd: int, name: str, *, missing_ok: bool = False) -> str | None:
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd,
        )
        status = os.fstat(descriptor)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or not os.path.samestat(status, current)
        ):
            raise SubtitleError("subtitle transaction file must be one regular unaliased file")
        return _sha256_fd(descriptor)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise SubtitleError("subtitle transaction file is missing; manual recovery required") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_new_at(directory_fd: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short subtitle transaction write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _marker_name(output_name: str) -> str:
    return f".{output_name}.transaction.json"


def _validate_marker(marker: object, output_name: str) -> dict:
    if not isinstance(marker, dict) or set(marker) != _MARKER_KEYS:
        raise SubtitleError("subtitle transaction marker has an invalid exact schema")
    generation = marker["generation"]
    if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
        raise SubtitleError("subtitle transaction marker generation is invalid")
    target = marker["target"]
    if target != output_name or Path(target).name != target or target in {"", ".", ".."}:
        raise SubtitleError("subtitle transaction marker target is invalid")
    expected_stage = f".{target}.{generation}.stage.webm"
    expected_backup = f".{target}.{generation}.backup.webm"
    if marker["stage"] != expected_stage or Path(marker["stage"]).name != marker["stage"]:
        raise SubtitleError("subtitle transaction marker stage is invalid")
    backup = marker["backup"]
    if backup is not None and (
        backup != expected_backup or Path(backup).name != backup
    ):
        raise SubtitleError("subtitle transaction marker backup is invalid")
    if not isinstance(marker["new_sha256"], str) or not _SHA256.fullmatch(marker["new_sha256"]):
        raise SubtitleError("subtitle transaction marker new sha is invalid")
    old_sha = marker["old_sha256"]
    if backup is None:
        if old_sha is not None:
            raise SubtitleError("subtitle transaction marker old state is inconsistent")
    elif not isinstance(old_sha, str) or not _SHA256.fullmatch(old_sha):
        raise SubtitleError("subtitle transaction marker old sha is invalid")
    if marker["state"] not in {"prepared", "committed"}:
        raise SubtitleError("subtitle transaction marker state is invalid")
    return marker


def _read_marker(directory_fd: int, output_name: str) -> dict:
    name = _marker_name(output_name)
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd,
        )
        status = os.fstat(descriptor)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or not os.path.samestat(status, current) or status.st_size > 16384
        ):
            raise SubtitleError("subtitle transaction marker cannot be read safely")
        data = b""
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            data += chunk
        marker = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except SubtitleError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise SubtitleError("subtitle transaction marker cannot be read safely") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _validate_marker(marker, output_name)


def _write_marker(
    directory_fd: int,
    output_name: str,
    marker: dict,
    *,
    verify=lambda: None,
) -> None:
    marker = _validate_marker(marker, output_name)
    name = _marker_name(output_name)
    temporary = f".{output_name}.{marker['generation']}.marker.tmp"
    data = (
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    verify()
    try:
        _write_new_at(directory_fd, temporary, data)
        verify()
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        verify()
        os.fsync(directory_fd)
        verify()
    finally:
        _unlink(directory_fd, temporary)


def _copy_verified_at(
    directory_fd: int, source: str, target: str, expected_sha256: str,
) -> None:
    if _sha256_at(directory_fd, source) != expected_sha256:
        raise SubtitleError("subtitle transaction source hash changed")
    _copy_at(directory_fd, source, target)
    if _sha256_at(directory_fd, target) != expected_sha256:
        raise SubtitleError("subtitle transaction copy hash mismatch")


def _recover_transaction_locked(directory_fd: int, output_name: str) -> bool:
    if _entry_status(directory_fd, _marker_name(output_name)) is None:
        return False
    marker = _read_marker(directory_fd, output_name)
    target_sha = _sha256_at(directory_fd, output_name, missing_ok=True)
    if target_sha not in {None, marker["old_sha256"], marker["new_sha256"]}:
        raise SubtitleError("subtitle transaction target is unknown; manual recovery required")
    keep_new = marker["state"] == "committed" and target_sha == marker["new_sha256"]
    if keep_new and marker["old_sha256"] is not None:
        old_sha = marker["old_sha256"]
        backup = marker["backup"]
        restore = f".{output_name}.{marker['generation']}.restore.webm"
        restore_sha = _sha256_at(directory_fd, restore, missing_ok=True)
        if restore_sha != old_sha:
            if backup is None or _sha256_at(directory_fd, backup, missing_ok=True) != old_sha:
                raise SubtitleError("committed subtitle cleanup has no full old recovery copy")
            if restore_sha is not None:
                _unlink(directory_fd, restore)
                os.fsync(directory_fd)
            _copy_verified_at(directory_fd, backup, restore, old_sha)
    if not keep_new:
        old_sha = marker["old_sha256"]
        if old_sha is None:
            if target_sha not in {None, marker["new_sha256"]}:
                raise SubtitleError("subtitle transaction target is unknown; manual recovery required")
            _unlink(directory_fd, output_name)
        elif target_sha != old_sha:
            backup = marker["backup"]
            if backup is None or _sha256_at(directory_fd, backup) != old_sha:
                raise SubtitleError("subtitle transaction backup is invalid; manual recovery required")
            restore = f".{output_name}.{marker['generation']}.restore.webm"
            restore_sha = _sha256_at(directory_fd, restore, missing_ok=True)
            if restore_sha is None:
                _copy_verified_at(directory_fd, backup, restore, old_sha)
            elif restore_sha != old_sha:
                # This exact generation-owned restore can only be an interrupted
                # recovery copy. The validated backup remains the source of truth.
                _unlink(directory_fd, restore)
                os.fsync(directory_fd)
                _copy_verified_at(directory_fd, backup, restore, old_sha)
            _crash_checkpoint("during_recovery_after_restore")
            os.replace(restore, output_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
        if old_sha is not None and _sha256_at(directory_fd, output_name) != old_sha:
            raise SubtitleError("subtitle transaction rollback verification failed")

    stage = marker["stage"]
    stage_sha = _sha256_at(directory_fd, stage, missing_ok=True)
    if stage_sha is not None:
        if stage_sha != marker["new_sha256"]:
            raise SubtitleError("subtitle transaction stage hash mismatch; manual recovery required")
        _unlink(directory_fd, stage)
    backup = marker["backup"]
    if backup is not None:
        backup_sha = _sha256_at(directory_fd, backup, missing_ok=True)
        if backup_sha is not None:
            if backup_sha != marker["old_sha256"]:
                raise SubtitleError("subtitle transaction backup hash mismatch; manual recovery required")
            _unlink(directory_fd, backup)
    _unlink(directory_fd, _marker_name(output_name))
    os.fsync(directory_fd)
    return True


def _acquire_target_lock(directory_fd: int, output_name: str) -> TargetLock:
    if Path(output_name).name != output_name or output_name in {"", ".", ".."}:
        raise SubtitleError("subtitle output target name is unsafe")
    name = f".{output_name}.render.lock"
    guard = f".{output_name}.render.guard"

    def verify_identity(descriptor: int) -> os.stat_result:
        locked = os.fstat(descriptor)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        guarded = os.stat(guard, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(locked.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or not stat.S_ISREG(guarded.st_mode)
            or not os.path.samestat(locked, current)
            or not os.path.samestat(locked, guarded)
        ):
            raise OSError("subtitle target lock identity changed")
        return locked

    for _ in range(3):
        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    guard, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd,
                )
            except FileNotFoundError:
                descriptor = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError("unsafe subtitle target lock")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    os.link(
                        name, guard,
                        src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    )
                except FileExistsError:
                    os.close(descriptor)
                    continue
            else:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError("unsafe subtitle target lock guard")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    os.link(
                        guard, name,
                        src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    )
                else:
                    if not os.path.samestat(current, os.fstat(descriptor)):
                        raise OSError("subtitle target lock identity changed")
            status = verify_identity(descriptor)
            return TargetLock(descriptor, directory_fd, name, guard, status)
        except BlockingIOError:
            if descriptor >= 0:
                os.close(descriptor)
            raise SubtitleError("subtitle render is already running") from None
        except OSError:
            if descriptor >= 0:
                os.close(descriptor)
            raise SubtitleError("cannot acquire subtitle target lock") from None
    raise SubtitleError("cannot acquire a stable subtitle target lock")


def _acquire_publication_guard(directory_fd: int, target_lock: TargetLock) -> None:
    target_lock.verify()
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
    except OSError:
        raise SubtitleError("cannot acquire subtitle publication guard") from None
    try:
        target_lock.verify()
    except BaseException:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        raise


def _release_publication_guard(directory_fd: int) -> None:
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
    except OSError:
        raise SubtitleError("cannot release subtitle publication guard") from None


def _guarded_directory_fsync(directory_fd: int, target_lock: TargetLock) -> None:
    target_lock.verify()
    os.fsync(directory_fd)
    target_lock.verify()


def _cleanup_current_generation_before_marker(
    directory_fd: int,
    *,
    output_name: str,
    generation: str,
    stage_name: str,
    backup_name: str,
) -> None:
    marker_name = _marker_name(output_name)
    marker_status = _entry_status(directory_fd, marker_name)
    if marker_status is not None:
        descriptor = os.open(
            marker_name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            data = b""
            while True:
                chunk = os.read(descriptor, 4096)
                if not chunk:
                    break
                data += chunk
            marker = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            marker = None
        finally:
            os.close(descriptor)
        if isinstance(marker, dict) and marker.get("generation") == generation:
            _unlink(directory_fd, marker_name)
    _unlink(directory_fd, stage_name)
    _unlink(directory_fd, backup_name)
    os.fsync(directory_fd)


def _crash_checkpoint(point: str) -> None:
    if os.environ.get("V5_SUBTITLE_CRASH_POINT") == point:
        os._exit(86)


def _cleanup_orphans(directory_fd: int, output_name: str) -> None:
    prefix = f".{output_name}."
    try:
        names = os.listdir(directory_fd)
    except (OSError, TypeError):
        return
    for name in names:
        if not name.startswith(prefix) or not name.endswith((".stage.webm", ".backup.webm")):
            continue
        status = _entry_status(directory_fd, name)
        if status is None or not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SubtitleError("unsafe orphaned subtitle transaction file requires manual recovery")
        _unlink(directory_fd, name)


def validate_webm(path: Path, frames: int) -> dict[str, int | str]:
    _safe_regular(path, "subtitle track")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return validate_webm_fd(descriptor, frames)
    finally:
        os.close(descriptor)


def render_subtitles(
    plan: object,
    *,
    visual_plan: object,
    output: Path,
    duration: float,
    plan_validator: Callable[[object, float], list[dict]] = validate_plan,
    frame_renderer: Callable[[list[dict], float], Image.Image] = render_frame,
) -> dict[str, int | str]:
    """Validate, encode and durably publish one recoverable subtitle track."""
    payload, plan_path, plan_status = _load_json(plan, "subtitle plan")
    visual_payload, visual_path, visual_status = _load_json(visual_plan, "visual plan")
    cues = plan_validator(payload, duration)
    validate_visual_titles(visual_payload, cues, duration)
    validate_cue_scene_bindings(cues, visual_payload)
    directory_fd, parent_status = _open_parent(output)
    generation = secrets.token_hex(12)
    stage_name = f".{output.name}.{generation}.stage.webm"
    backup_name = f".{output.name}.{generation}.backup.webm"
    stage_fd: int | None = None
    target_lock: TargetLock | None = None
    publication_guard = False
    marker_written = False
    preserve_transaction = False
    committed = False
    publication_prepared = False
    target_replaced = False
    try:
        target_lock = _acquire_target_lock(directory_fd, output.name)
        target_lock.verify()
        if _entry_status(directory_fd, _marker_name(output.name)) is not None:
            _acquire_publication_guard(directory_fd, target_lock)
            publication_guard = True
            _recover_transaction_locked(directory_fd, output.name)
            target_lock.verify()
            _release_publication_guard(directory_fd)
            publication_guard = False
        target_lock.verify()
        if not parent_is_attached(output.parent, directory_fd, parent_status):
            raise SubtitleError("subtitle output parent changed before staging")
        existing = _entry_status(directory_fd, output.name)
        if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise SubtitleError("subtitle output must be one regular unaliased file")
        for source_path, source_status in ((plan_path, plan_status), (visual_path, visual_status)):
            if source_path is None or source_status is None:
                continue
            if output.absolute() == source_path.absolute() or (
                existing is not None and os.path.samestat(existing, source_status)
            ):
                raise SubtitleError("subtitle output aliases an input file")
        stage_fd = os.open(
            stage_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        before = os.fstat(stage_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SubtitleError("subtitle stage must be one regular unaliased inode")
        target_lock.verify()
        if frame_renderer is _DEFAULT_FRAME_RENDERER:
            # Preserve the original three-argument call for existing V5 callers
            # and test doubles; Erduo opts into the callback explicitly.
            encode_webm(cues, stage_fd, duration)
        else:
            encode_webm(cues, stage_fd, duration, frame_renderer=frame_renderer)
        target_lock.verify()
        after = os.fstat(stage_fd)
        pinned = _entry_status(directory_fd, stage_name)
        if (
            pinned is None or not stat.S_ISREG(after.st_mode) or after.st_nlink != 1
            or not stat.S_ISREG(pinned.st_mode) or pinned.st_nlink != 1
            or not os.path.samestat(before, after) or not os.path.samestat(after, pinned)
        ):
            raise SubtitleError("subtitle stage inode changed or became aliased during encoding")
        info = validate_webm_fd(stage_fd, frames=round(duration * FPS))
        after_validation = os.fstat(stage_fd)
        if not os.path.samestat(after, after_validation) or after_validation.st_nlink != 1:
            raise SubtitleError("subtitle stage inode changed or became aliased during validation")
        new_sha256 = _sha256_fd(stage_fd)
        if not parent_is_attached(output.parent, directory_fd, parent_status):
            raise SubtitleError("subtitle output parent changed before publication")
        target_lock.verify()
        _acquire_publication_guard(directory_fd, target_lock)
        publication_guard = True
        target_lock.verify()
        publication_prepared = True
        old_sha256 = None
        backup = None
        if existing is not None:
            target_lock.verify()
            old_sha256 = _sha256_at(directory_fd, output.name)
            _copy_verified_at(directory_fd, output.name, backup_name, old_sha256)
            target_lock.verify()
            backup = backup_name
        marker = {
            "generation": generation,
            "target": output.name,
            "stage": stage_name,
            "backup": backup,
            "new_sha256": new_sha256,
            "old_sha256": old_sha256,
            "state": "prepared",
        }
        target_lock.verify()
        _write_marker(directory_fd, output.name, marker, verify=target_lock.verify)
        target_lock.verify()
        marker_written = True
        _crash_checkpoint("before_replace")
        target_lock.verify()
        os.replace(
            stage_name, output.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
        )
        target_replaced = True
        target_lock.verify()
        _crash_checkpoint("after_replace")
        _guarded_directory_fsync(directory_fd, target_lock)
        if _sha256_at(directory_fd, output.name) != new_sha256:
            raise SubtitleError("published subtitle hash does not match the validated stage")
        if not parent_is_attached(output.parent, directory_fd, parent_status):
            raise SubtitleError("subtitle output parent changed before commit")
        target_lock.verify()
        marker["state"] = "committed"
        try:
            _write_marker(directory_fd, output.name, marker, verify=target_lock.verify)
        except BaseException:
            # A failed directory fsync makes the committed marker uncertain.
            # Persist prepared again so the common recovery path restores old.
            marker["state"] = "prepared"
            _write_marker(directory_fd, output.name, marker, verify=target_lock.verify)
            raise
        target_lock.verify()
        committed = True
        _crash_checkpoint("after_commit")
        cleanup_restore = None
        if backup is not None:
            cleanup_restore = f".{output.name}.{generation}.restore.webm"
            target_lock.verify()
            _copy_verified_at(directory_fd, backup, cleanup_restore, old_sha256)
            target_lock.verify()
            _unlink(directory_fd, backup)
            target_lock.verify()
            _guarded_directory_fsync(directory_fd, target_lock)
        target_lock.verify()
        _unlink(directory_fd, _marker_name(output.name))
        target_lock.verify()
        _guarded_directory_fsync(directory_fd, target_lock)
        marker_written = False
        if cleanup_restore is not None:
            # The new track and marker removal are durable. Removing this final
            # redundant old copy needs no further transaction checkpoint.
            target_lock.verify()
            _unlink(directory_fd, cleanup_restore)
            target_lock.verify()
        target_lock.verify()
        return info
    except BaseException as failure:
        if marker_written and not committed:
            try:
                _recover_transaction_locked(directory_fd, output.name)
                marker_written = False
            except BaseException as recovery_error:
                preserve_transaction = True
                raise SubtitleError(
                    f"subtitle transaction recovery failed; manual recovery file: {backup_name}"
                ) from failure
        elif marker_written and committed:
            preserve_transaction = True
        elif publication_prepared and not target_replaced:
            try:
                _cleanup_current_generation_before_marker(
                    directory_fd,
                    output_name=output.name,
                    generation=generation,
                    stage_name=stage_name,
                    backup_name=backup_name,
                )
            except BaseException as cleanup_error:
                preserve_transaction = True
                raise SubtitleError(
                    f"subtitle pre-marker cleanup failed; manual recovery file: {backup_name}"
                ) from failure
        raise
    finally:
        primary_error_active = sys.exc_info()[0] is not None
        cleanup_error: BaseException | None = None
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if not marker_written and not preserve_transaction:
            try:
                _unlink(directory_fd, stage_name)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if target_lock is not None:
            try:
                target_lock.verify()
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if publication_guard:
            try:
                _release_publication_guard(directory_fd)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if target_lock is not None:
            try:
                target_lock.close()
            except BaseException as error:
                cleanup_error = cleanup_error or error
        try:
            os.close(directory_fd)
        except BaseException as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None and not primary_error_active:
            raise cleanup_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--visual-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        info = render_subtitles(
            args.plan, visual_plan=args.visual_plan, output=args.output, duration=args.duration,
        )
        print(json.dumps(info, ensure_ascii=False, sort_keys=True))
        return 0
    except (SubtitleError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""V5 sparse overlays and FFmpeg geometry for the six approved layouts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from .style_tokens import PALETTE
except ImportError:  # pragma: no cover - direct CLI execution
    from style_tokens import PALETTE


WIDTH = 1080
HEIGHT = 1920
FPS = 24
PERSON_GRADE = (
    "eq=brightness=0.01:contrast=1.035:saturation=0.98,"
    "colorbalance=bs=.015:gs=-.005:rs=.005,"
    "unsharp=5:5:.18:3:3:0"
)
AVATAR_SIZE = 340
AVATAR_X = 670
AVATAR_Y = 125
AVATAR_CROPS = {
    "asset_avatar": (1080, 0, 240),
    "official_evidence_full": (1080, 0, 240),
}
RING_WIDTH = 18
SHADOW_OFFSET = 8
CUTOUT_CROP = (580, 850, 250, 600)
CUTOUT_RENDER_HEIGHT = 630
CUTOUT_PERSON_X = 650
CUTOUT_PERSON_Y = 820
CUTOUT_SHADOW_X = 662
CUTOUT_SHADOW_Y = 832
CUTOUT_FADE_ROWS = 10
CUTOUT_SHADOW_TRIM_ROWS = 80


class LayoutError(ValueError):
    """A clean V5 layout-contract failure."""


@dataclass(frozen=True)
class LayoutSpec:
    person_mode: str
    person_width: int = 0
    asset_bottom: int = 0
    speaker_height: int = 0
    gradient_height: int = 0


LAYOUT_SPECS = {
    "full_speaker_minimal": LayoutSpec("full"),
    "asset_avatar": LayoutSpec("avatar", person_width=AVATAR_SIZE),
    "asset_cutout_edge": LayoutSpec("cutout", person_width=430),
    "full_speaker_emphasis": LayoutSpec("full"),
    "official_evidence_full": LayoutSpec("avatar", person_width=AVATAR_SIZE),
    "top_asset_bottom_speaker": LayoutSpec(
        "split", asset_bottom=864, speaker_height=1056, gradient_height=96
    ),
}

RGB = {name: tuple(bytes.fromhex(value[1:])) for name, value in PALETTE.items()}


@lru_cache(maxsize=16)
def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=1 if bold and path.endswith(".ttc") else 0)
        except OSError:
            continue
    raise LayoutError("a CJK font is required for V5 overlays")


DISPLAY_TITLE_OVERRIDES = {
    "v5-001": "结论先行",
    "v5-004": "现场证据",
}

FULL_SPEAKER_DESIGNS = {
    "v5-001": {
        "layout": "full_speaker_minimal",
        "design": "cobalt_left_conclusion",
        "panel": (0, 800, 350, 1390),
        "font_size": 96,
        "lines": ("结论", "先行"),
        "origins": ((58, 900), (58, 1030)),
    },
    "v5-004": {
        "layout": "full_speaker_emphasis",
        "design": "mint_upper_evidence",
        "panel": (740, 80, 1080, 620),
        "font_size": 92,
        "lines": ("现场", "证据"),
        "origins": ((790, 200), (790, 326)),
    },
    "v5-008": {
        "layout": "full_speaker_emphasis",
        "design": "signal_right_closure",
        "panel": (800, 760, 1080, 1390),
        "font_size": 72,
        "lines": ("学习的", "误区"),
        "origins": ((830, 960), (830, 1070)),
    },
}


def display_title(scene: dict[str, Any], *, maximum: int = 11) -> str:
    """Return the exact short title used by a V5 scene overlay."""
    if not isinstance(scene, dict):
        raise LayoutError("scene must be an object")
    value = scene.get("spoken_text")
    if not isinstance(value, str) or not value.strip():
        raise LayoutError("scene spoken_text must be non-empty text")
    scene_id = scene.get("id")
    if scene_id in DISPLAY_TITLE_OVERRIDES:
        return DISPLAY_TITLE_OVERRIDES[scene_id]
    compact = "".join(value.strip().split())
    for separator in ("，", "。", "！", "？", ",", "."):
        compact = compact.split(separator, 1)[0]
    return compact[:maximum]


def _accent(scene: dict[str, Any]) -> tuple[int, int, int]:
    value = scene.get("primary_accent")
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise LayoutError("scene primary_accent must be a hex color")
    try:
        return tuple(bytes.fromhex(value[1:]))
    except ValueError:
        raise LayoutError("scene primary_accent must be a hex color") from None


def overlay_contract(layout: str) -> dict[str, Any]:
    if not isinstance(layout, str) or layout not in LAYOUT_SPECS:
        raise LayoutError("unsupported V5 editorial layout")
    common = {
        "title_count": 0,
        "directional_mark_count": 0,
        "card_count": 0,
        "ring_count": 0,
        "ring_width": 0,
        "shadow_offset": 0,
        "crop": None,
        "source_pill_count": 0,
        "middle_ui_count": 0,
        "bottom_ui_count": 0,
        "cutout": LAYOUT_SPECS[layout].person_mode == "cutout",
        "subtitle_board_count": 0,
        "gradient_height": LAYOUT_SPECS[layout].gradient_height,
    }
    if layout in {"full_speaker_minimal", "full_speaker_emphasis"}:
        common.update(title_count=1, directional_mark_count=1)
    if layout in {"asset_avatar", "official_evidence_full"}:
        common.update(
            ring_count=1,
            ring_width=RING_WIDTH,
            shadow_offset=SHADOW_OFFSET,
            crop="head_shoulders",
        )
    if layout == "official_evidence_full":
        common["source_pill_count"] = 1
    return common


def avatar_crop_for_layout(layout: str) -> tuple[int, int, int]:
    try:
        return AVATAR_CROPS[layout]
    except (KeyError, TypeError):
        raise LayoutError("layout does not support an avatar crop") from None


def cutout_mask_filter() -> str:
    width, height, x, y = CUTOUT_CROP
    return (
        f"format=yuva444p,crop={width}:{height}:{x}:{y},alphaextract,"
        f"scale={LAYOUT_SPECS['asset_cutout_edge'].person_width}:{CUTOUT_RENDER_HEIGHT},"
        f"geq=lum='if(gte(Y,H-{CUTOUT_FADE_ROWS}),"
        f"lum(X,Y)*(H-1-Y)/{CUTOUT_FADE_ROWS - 1},lum(X,Y))'"
    )


def cutout_shadow_mask_filter() -> str:
    width, height, x, y = CUTOUT_CROP
    return (
        f"format=yuva444p,crop={width}:{height}:{x}:{y},alphaextract,"
        f"scale={LAYOUT_SPECS['asset_cutout_edge'].person_width}:{CUTOUT_RENDER_HEIGHT},"
        f"geq=lum='if(gte(Y,H-{CUTOUT_SHADOW_TRIM_ROWS}),0,lum(X,Y))'"
    )


def full_speaker_geometry(scene: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scene, dict):
        raise LayoutError("scene must be an object")
    scene_id = scene.get("id")
    try:
        design = FULL_SPEAKER_DESIGNS[scene_id]
    except (KeyError, TypeError):
        raise LayoutError("full-speaker scene has no approved bold geometry") from None
    if scene.get("editorial_layout") != design["layout"]:
        raise LayoutError("full-speaker scene layout does not match its bold geometry")
    font = _font(design["font_size"], bold=True)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    text_boxes = tuple(
        tuple(int(value) for value in measure.textbbox(origin, line, font=font))
        for origin, line in zip(design["origins"], design["lines"])
    )
    return {
        "design": design["design"],
        "panel": design["panel"],
        "font_size": design["font_size"],
        "lines": design["lines"],
        "origins": design["origins"],
        "text_boxes": text_boxes,
    }


def minimal_title_geometry(scene: dict[str, Any]) -> dict[str, tuple[int, int, int, int]]:
    geometry = full_speaker_geometry(scene)
    boxes = geometry["text_boxes"]
    text = (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )
    return {"block": geometry["panel"], "text": text}


def create_overlay(layout: str, scene: dict[str, Any]) -> Image.Image:
    """Create only the sparse title, direction mark, ring, or source label."""
    if not isinstance(layout, str) or layout not in LAYOUT_SPECS:
        raise LayoutError("unsupported V5 editorial layout")
    if not isinstance(scene, dict):
        raise LayoutError("scene must be an object")
    accent = _accent(scene)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if layout in {"full_speaker_minimal", "full_speaker_emphasis"}:
        geometry = full_speaker_geometry(scene)
        design = geometry["design"]
        if design == "cobalt_left_conclusion":
            draw.rectangle(geometry["panel"], fill=(*RGB["cobalt"], 246))
            draw.polygon(((58, 1290), (300, 1290), (334, 1304), (300, 1318), (58, 1318)), fill=(*RGB["yellow"], 255))
            text_color = RGB["cream"]
        elif design == "mint_upper_evidence":
            draw.polygon(
                ((780, 80), (1080, 80), (1080, 620), (740, 620), (780, 500)),
                fill=(*RGB["mint"], 246),
            )
            draw.polygon(((736, 146), (760, 126), (760, 442), (736, 474)), fill=(*RGB["coral"], 255))
            text_color = RGB["ink"]
        else:
            draw.polygon(
                ((800, 760), (1080, 760), (1080, 1390), (830, 1390), (800, 1340)),
                fill=(*RGB["ink"], 246),
            )
            draw.rectangle((800, 760, 1080, 900), fill=(*RGB["yellow"], 255))
            draw.polygon(((830, 826), (996, 826), (1028, 840), (996, 854), (830, 854)), fill=(*RGB["ink"], 255))
            text_color = RGB["cream"]
        font = _font(geometry["font_size"], bold=True)
        for origin, line in zip(geometry["origins"], geometry["lines"]):
            draw.text(origin, line, font=font, fill=(*text_color, 255))
    elif layout in {"asset_avatar", "official_evidence_full"}:
        outer = (AVATAR_X - 14, AVATAR_Y - 14, AVATAR_X + AVATAR_SIZE + 14, AVATAR_Y + AVATAR_SIZE + 14)
        shifted = tuple(value + (SHADOW_OFFSET if index % 2 == 0 else SHADOW_OFFSET) for index, value in enumerate(outer))
        draw.ellipse(shifted, outline=(*accent, 174), width=RING_WIDTH + 2)
        draw.ellipse(outer, outline=(*accent, 255), width=RING_WIDTH)
        if layout == "official_evidence_full":
            label = "STANFORD · ALI GHODSI"
            draw.rounded_rectangle((38, 46, 430, 116), radius=28, fill=(*RGB["ink"], 226))
            draw.text((66, 66), label, font=_font(25, bold=True), fill=(*RGB["cream"], 255))
    return image


def _timing(duration: float) -> str:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise LayoutError("duration must be a finite positive number")
    return (
        f"fps={FPS},tpad=stop_mode=clone:stop_duration={duration:.9f},"
        f"trim=duration={duration:.9f},setpts=PTS-STARTPTS"
    )


def _base(duration: float) -> str:
    return (
        f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:"
        f"in_range=auto:out_range=tv,crop={WIDTH}:{HEIGHT},{_timing(duration)},{PERSON_GRADE}"
    )


def _asset(index: int, duration: float, output: str = "media") -> str:
    return (
        f"[{index}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:"
        f"in_range=auto:out_range=tv,crop={WIDTH}:{HEIGHT},{_timing(duration)}[{output}]"
    )


def _finish(graph: str) -> str:
    marker = "[outv]"
    if not graph.endswith(marker) or graph.count(marker) != 1:
        raise LayoutError("layout graph must expose exactly one final video output")
    return (
        graph[: -len(marker)]
        + "[v5raw];[v5raw]scale=in_range=auto:out_range=tv,format=yuv420p[outv]"
    )


def build_filter_graph(
    layout: str,
    *,
    duration: float,
    asset_index: int | None,
    alpha_index: int | None,
    layer_index: int,
) -> tuple[str, str]:
    if not isinstance(layout, str) or layout not in LAYOUT_SPECS:
        raise LayoutError("unsupported V5 editorial layout")
    if isinstance(layer_index, bool) or not isinstance(layer_index, int) or layer_index < 1:
        raise LayoutError("overlay input index must be a positive integer")
    timing = _timing(duration)
    layer = f"[{layer_index}:v]format=rgba,{timing}[layer]"

    if layout in {"full_speaker_minimal", "full_speaker_emphasis"}:
        if asset_index is not None or alpha_index is not None:
            raise LayoutError("full-speaker layouts must not receive asset inputs")
        graph = f"[0:v]{_base(duration)}[base];{layer};[base][layer]overlay=0:0:shortest=1[outv]"
        return _finish(graph), layout

    if asset_index is None:
        raise LayoutError(f"{layout} requires a verified asset input")

    if layout in {"asset_avatar", "official_evidence_full"}:
        crop_size, crop_x, crop_y = avatar_crop_for_layout(layout)
        person = (
            f"[0:v]{_base(duration)},crop={crop_size}:{crop_size}:{crop_x}:{crop_y},"
            f"scale={AVATAR_SIZE}:{AVATAR_SIZE},format=rgba,"
            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            "a='if(lte(hypot(X-W/2,Y-H/2),W/2-8),255,0)'[person]"
        )
        graph = (
            f"{_asset(asset_index, duration)};{person};{layer};"
            f"[media][person]overlay={AVATAR_X}:{AVATAR_Y}:shortest=1[withperson];"
            "[withperson][layer]overlay=0:0:shortest=1[outv]"
        )
        return _finish(graph), layout

    if layout == "asset_cutout_edge":
        if alpha_index is None:
            raise LayoutError("asset_cutout_edge requires a validated alpha input")
        width = LAYOUT_SPECS[layout].person_width
        crop_width, crop_height, crop_x, crop_y = CUTOUT_CROP
        person = (
            f"[{alpha_index}:v]{timing},format=yuva444p,"
            f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},"
            "split=2[personcolor][personalpha];"
            f"[personcolor]scale={width}:{CUTOUT_RENDER_HEIGHT},format=rgb24,"
            f"{PERSON_GRADE}[gradedperson];"
            f"[personalpha]alphaextract,scale={width}:{CUTOUT_RENDER_HEIGHT},"
            "format=gray,split=2[personmaskraw][shadowmaskraw];"
            f"[personmaskraw]geq=lum='if(gte(Y,H-{CUTOUT_FADE_ROWS}),"
            f"lum(X,Y)*(H-1-Y)/{CUTOUT_FADE_ROWS - 1},lum(X,Y))'[personmask];"
            f"[shadowmaskraw]geq=lum='if(gte(Y,H-{CUTOUT_SHADOW_TRIM_ROWS}),"
            "0,lum(X,Y))'[shadowmask];"
            "[gradedperson][personmask]alphamerge[person];"
            f"color=c=0xFF5F55:s={width}x{CUTOUT_RENDER_HEIGHT}:r={FPS}:"
            f"d={duration:.9f},format=rgb24[shadowcolor];"
            "[shadowcolor][shadowmask]alphamerge[personshadow]"
        )
        graph = (
            f"{_asset(asset_index, duration)};{person};{layer};"
            f"[media][personshadow]overlay={CUTOUT_SHADOW_X}:{CUTOUT_SHADOW_Y}:shortest=1[depth];"
            f"[depth][person]overlay={CUTOUT_PERSON_X}:{CUTOUT_PERSON_Y}:shortest=1[withperson];"
            "[withperson][layer]overlay=0:0:shortest=1[outv]"
        )
        return _finish(graph), layout

    if layout == "top_asset_bottom_speaker":
        if alpha_index is not None:
            raise LayoutError("split layout must use the original room background, not a cutout")
        split = LAYOUT_SPECS[layout]
        asset_top = (
            f"[{asset_index}:v]scale={WIDTH}:{split.asset_bottom + split.gradient_height // 2}:"
            "force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{split.asset_bottom + split.gradient_height // 2},{timing},format=rgba,"
            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            "a='if(lt(Y,816),255,if(gt(Y,912),0,255*(912-Y)/96))'[assettop]"
        )
        graph = (
            f"color=c=0x15152F:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.9f}[splitcanvas];"
            f"[0:v]{_base(duration)},crop=1080:1056:0:300[speakerbottom];"
            "[splitcanvas][speakerbottom]overlay=0:864:shortest=1[speaker];"
            f"{asset_top};{layer};"
            "[speaker][assettop]overlay=0:0:shortest=1[media];"
            "[media][layer]overlay=0:0:shortest=1[outv]"
        )
        return _finish(graph), layout

    raise LayoutError("unsupported V5 editorial layout")

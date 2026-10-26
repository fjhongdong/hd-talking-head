"""Approved cover direction bound to one content map and one person reference."""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

from . import content_analysis, contract_artifacts, material_usage, state


REQUIRED_DIRECTION_KEYS = {
    "output_aspect_ratio",
    "title",
    "subtitle",
    "person_reference",
    "pose",
    "expression",
    "environment",
    "props",
    "composition",
    "palette",
    "typography",
    "safe_zones",
    "prompt_allow",
    "prompt_deny",
}
_AROLL_INPUT_KEYS = {"source", "timestamp"}
_MATERIAL_INPUT_KEYS = {"source", "material_id"}
_AROLL_RECORD_KEYS = {
    "source", "timestamp", "path", "sha256", "bytes", "video_sha256",
}
_MATERIAL_RECORD_KEYS = {
    "source", "material_id", "path", "sha256", "bytes", "material_sha256",
}
_COMPOSITION_KEYS = {
    "style_id", "person_side", "person_width_ratio", "blank_width_ratio",
}
_PALETTE_KEYS = {"background", "font_color", "accent_color"}
_TYPOGRAPHY_KEYS = {"font_style"}
_SAFE_ZONE_KEYS = {"safe_margin_ratio"}
_PUNK_STYLE = "interleaved-title-editorial-poster"
_STYLE = re.compile(rf"(?:style-(?:0[1-9]|10)|{_PUNK_STYLE})\Z")
_BACKGROUND = re.compile(r"[a-z]+(?:-[a-z]+)*\Z")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OUTPUT_ASPECT_RATIOS = {"16:9", "9:16", "3:4", "1:1"}
_PREVIEW_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "3:4": (1080, 1440),
    "1:1": (1080, 1080),
}
_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path(__file__).resolve().parents[3] / "skill-development/vendor/adu-motion-video/assets/fonts/NotoSansSC.ttf",
)


class CoverDirectionError(ValueError):
    """Raised when a cover direction is invalid, stale, or not approved."""


def _object(value: Any, keys: set[str], label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CoverDirectionError(f"{label} schema is invalid")
    return dict(value)


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or value != value.strip() or (
        not allow_empty and not value
    ):
        raise CoverDirectionError(f"{label} must be text")
    return value


def _number(value: Any, label: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CoverDirectionError(f"{label} must be a finite number")
    result = float(value)
    if result < low or result > high:
        raise CoverDirectionError(f"{label} is outside the allowed range")
    return result


def _text_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if type(value) is not list or any(
        type(item) is not str or not item.strip() or item != item.strip()
        for item in value
    ):
        raise CoverDirectionError(f"{label} must be a text list")
    if not allow_empty and not value:
        raise CoverDirectionError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise CoverDirectionError(f"{label} contains duplicates")
    return list(value)


def _person_input(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CoverDirectionError("person_reference schema is invalid")
    source = value.get("source")
    keys = _AROLL_INPUT_KEYS if source == "current-aroll-video" else (
        _MATERIAL_INPUT_KEYS if source == "user-material" else set()
    )
    if set(value) != keys:
        raise CoverDirectionError("person_reference schema is invalid")
    result = dict(value)
    if source == "current-aroll-video":
        result["timestamp"] = _number(
            result["timestamp"], "person_reference timestamp", 0.0, 86400.0
        )
    else:
        result["material_id"] = _text(
            result["material_id"], "person_reference material_id"
        )
    return result


def _user_material(job: state.JobState, material_id: str) -> tuple[bytes, str]:
    index_path = job.root / "00-user-provided" / "material-index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoverDirectionError("user material index is unavailable") from exc
    materials = payload.get("materials") if isinstance(payload, Mapping) else None
    if type(materials) is not list:
        raise CoverDirectionError("user material index is invalid")
    matches = [
        record for record in materials
        if isinstance(record, Mapping) and record.get("material_id") == material_id
    ]
    if len(matches) != 1:
        raise CoverDirectionError("user material reference is unavailable")
    record = matches[0]
    if record.get("status", "active") != "active":
        raise CoverDirectionError("user material is withdrawn or superseded")
    imported = record.get("imported_path")
    expected_sha = record.get("sha256")
    expected_bytes = record.get("size_bytes")
    if (
        record.get("media_type") != "images"
        or type(imported) is not str
        or not imported
        or type(expected_sha) is not str
        or _SHA.fullmatch(expected_sha) is None
        or type(expected_bytes) is not int
        or expected_bytes <= 0
    ):
        raise CoverDirectionError("user material reference is invalid")
    relative = Path(imported)
    source = job.root / relative
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(job.root.resolve(strict=True))
        if source.is_symlink() or not resolved.is_file():
            raise OSError
        data = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise CoverDirectionError("user material reference is unavailable") from exc
    if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha:
        raise CoverDirectionError("user material reference identity changed")
    return data, expected_sha


def _frame_at(video: Path, timestamp: float) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-ss", f"{timestamp:.6f}", "-i", str(video), "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "png", "-",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CoverDirectionError("unable to extract the A-roll reference frame") from exc
    if not result.stdout:
        raise CoverDirectionError("A-roll reference frame is empty")
    return result.stdout


def _validated_png(source: bytes) -> bytes:
    if type(source) is not bytes or not source:
        raise CoverDirectionError("A-roll reference frame is invalid")
    try:
        with Image.open(io.BytesIO(source)) as image:
            image.load()
            if image.width < 64 or image.height < 64:
                raise ValueError
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG", optimize=False)
            return output.getvalue()
    except (OSError, ValueError) as exc:
        raise CoverDirectionError("A-roll reference frame is invalid") from exc


def _read_direction_preview(
    job: state.JobState,
    source_path: Path,
    output_aspect_ratio: str,
) -> bytes:
    if not source_path.is_absolute():
        raise CoverDirectionError("direction preview path must be absolute")
    output = job.job_dir / "03-cover-direction"
    try:
        resolved = source_path.resolve(strict=True)
        resolved.relative_to(job.job_dir.resolve(strict=True))
        stat = resolved.stat()
        if (
            source_path.is_symlink()
            or source_path != resolved
            or not resolved.is_file()
            or stat.st_nlink != 1
            or resolved in {
                (output / "cover-direction.json").resolve(),
                (output / "direction-preview.png").resolve(),
                (output / "review.html").resolve(),
                (output / "person-reference.png").resolve(),
            }
        ):
            raise OSError
        data = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise CoverDirectionError("direction preview path is invalid") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError
            image.load()
            if image.size != _PREVIEW_SIZES[output_aspect_ratio]:
                raise ValueError
    except (OSError, ValueError, KeyError) as exc:
        raise CoverDirectionError("direction preview PNG is invalid") from exc
    return data


def _traceable_title(title: str, analysis: Mapping[str, Any]) -> None:
    semantic = analysis["analysis"]
    sources = [semantic["thesis"], semantic["hook"]]
    for item in semantic["items"]:
        if (
            item["priority"] in {"critical", "high"}
            and item["evidence_status"] != "unsupported"
        ):
            sources.append(item["source_text"])
            sources.extend(item["keywords"])
    if not any(title in source for source in sources):
        raise CoverDirectionError(
            "cover title must be traceable to the approved content analysis"
        )


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return any(low <= codepoint <= high for low, high in (
        (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
        (0x20000, 0x2EBEF), (0x2F800, 0x2FA1F), (0x30000, 0x323AF),
    ))


def _normalize_direction(
    raw: Mapping[str, Any],
    analysis: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping) or not REQUIRED_DIRECTION_KEYS.issubset(raw) or (
        set(raw) - REQUIRED_DIRECTION_KEYS - {"support_line"}
    ):
        raise CoverDirectionError("cover direction schema is invalid")
    value = dict(raw)
    output_aspect_ratio = _text(
        value["output_aspect_ratio"], "output_aspect_ratio"
    )
    if output_aspect_ratio not in _OUTPUT_ASPECT_RATIOS:
        raise CoverDirectionError("output_aspect_ratio is invalid")
    title = _text(value["title"], "title")
    if not 4 <= len(title) <= 8 or any(not _is_han(character) for character in title):
        raise CoverDirectionError("title must contain four to eight Han characters")
    _traceable_title(title, analysis)
    subtitle = _text(value["subtitle"], "subtitle", allow_empty=True)
    person = _person_input(value["person_reference"])
    if person["source"] != reference["source"]:
        raise CoverDirectionError("person_reference source changed")
    if person["source"] == "current-aroll-video":
        if person["timestamp"] != reference["timestamp"]:
            raise CoverDirectionError("person_reference timestamp changed")
    elif person["material_id"] != reference["material_id"]:
        raise CoverDirectionError("person_reference material changed")

    composition = _object(value["composition"], _COMPOSITION_KEYS, "composition")
    style_id = _text(composition["style_id"], "style_id")
    if _STYLE.fullmatch(style_id) is None:
        raise CoverDirectionError("style_id is invalid")
    side = composition["person_side"]
    if side not in {"left", "right"}:
        raise CoverDirectionError("person_side is invalid")
    person_ratio = _number(
        composition["person_width_ratio"], "person_width_ratio", 0.10, 0.80
    )
    blank_ratio = _number(
        composition["blank_width_ratio"], "blank_width_ratio", 0.10, 0.80
    )
    if style_id == "style-07" and not (
        0.25 <= person_ratio <= 0.35 and 0.60 <= blank_ratio <= 0.70
    ):
        raise CoverDirectionError("style-07 composition is invalid")
    support_line = None
    if "support_line" in value:
        support_line = _text(value["support_line"], "support_line")
        if (len(support_line) > 24 or any(ord(character) < 32 for character in support_line)
                or style_id != "style-07" or output_aspect_ratio != "9:16"):
            raise CoverDirectionError("support_line is only valid for 9:16 style-07")

    palette = _object(value["palette"], _PALETTE_KEYS, "palette")
    background = _text(palette["background"], "background")
    if _BACKGROUND.fullmatch(background) is None:
        raise CoverDirectionError("background must be a prompt-safe slug")
    for key in ("font_color", "accent_color"):
        if _COLOR.fullmatch(_text(palette[key], key)) is None:
            raise CoverDirectionError(f"{key} is invalid")
    typography = _object(value["typography"], _TYPOGRAPHY_KEYS, "typography")
    if typography["font_style"] != "heavy-sans":
        raise CoverDirectionError("font_style must be heavy-sans")
    safe_zones = _object(value["safe_zones"], _SAFE_ZONE_KEYS, "safe_zones")
    margin = _number(
        safe_zones["safe_margin_ratio"], "safe_margin_ratio",
        0.04 if style_id == _PUNK_STYLE or (
            style_id == "style-07" and output_aspect_ratio == "9:16"
        ) else 0.10,
        0.15,
    )

    normalized = {
        "output_aspect_ratio": output_aspect_ratio,
        "title": title,
        "subtitle": subtitle,
        "person_reference": dict(reference),
        "pose": _text(value["pose"], "pose"),
        "expression": _text(value["expression"], "expression"),
        "environment": _text(value["environment"], "environment"),
        "props": _text_list(value["props"], "props", allow_empty=True),
        "composition": {
            "style_id": style_id,
            "person_side": side,
            "person_width_ratio": person_ratio,
            "blank_width_ratio": blank_ratio,
        },
        "palette": {
            "background": background,
            "font_color": palette["font_color"].upper(),
            "accent_color": palette["accent_color"].upper(),
        },
        "typography": {"font_style": "heavy-sans"},
        "safe_zones": {"safe_margin_ratio": margin},
        "prompt_allow": _text_list(value["prompt_allow"], "prompt_allow"),
        "prompt_deny": _text_list(value["prompt_deny"], "prompt_deny"),
    }
    if support_line is not None:
        normalized["support_line"] = support_line
    return normalized


def _preview_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(str(path), size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_person_card(
    source: bytes, size: tuple[int, int], radius: int,
) -> Image.Image:
    with Image.open(io.BytesIO(source)) as decoded:
        person = ImageOps.fit(
            decoded.convert("RGB"), size, method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.38),
        )
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255,
    )
    card = person.convert("RGBA")
    card.putalpha(mask)
    return card


def _render_direction_preview(
    direction: Mapping[str, Any], person_png: bytes,
) -> bytes:
    width, height = _PREVIEW_SIZES[direction["output_aspect_ratio"]]
    unit = min(width, height)
    canvas = Image.new("RGB", (width, height), "#08141F")
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        progress = y / max(height - 1, 1)
        color = (
            round(8 + 5 * progress),
            round(20 + 7 * progress),
            round(31 + 16 * progress),
        )
        draw.line((0, y, width, y), fill=color)

    margin = round(width * 0.065)
    title_font = _preview_font(round(unit * 0.080))
    subtitle_font = _preview_font(round(unit * 0.041))
    label_font = _preview_font(round(unit * 0.026))
    small_font = _preview_font(round(unit * 0.020))
    micro_font = _preview_font(round(unit * 0.016))
    white = "#F7F4EC"
    yellow = direction["palette"]["accent_color"]
    cyan = "#5FE4E8"
    coral = "#FF6B5E"

    draw.rounded_rectangle(
        (margin, round(height * 0.035), margin + round(width * 0.28),
         round(height * 0.075)),
        radius=round(unit * 0.018), outline=cyan, width=max(2, round(unit * 0.003)),
    )
    draw.text(
        (margin + round(unit * 0.018), round(height * 0.043)),
        "COVER DIRECTION · 9:16" if width < height else "COVER DIRECTION",
        font=micro_font, fill=cyan,
    )
    draw.text(
        (margin, round(height * 0.105)), direction["title"],
        font=title_font, fill=white, stroke_width=max(1, round(unit * 0.002)),
        stroke_fill="#08141F",
    )
    draw.text(
        (margin, round(height * 0.105) + round(unit * 0.105)),
        direction["subtitle"], font=subtitle_font, fill=yellow,
    )
    if direction.get("support_line"):
        draw.text(
            (margin, round(height * 0.105) + round(unit * 0.17)),
            direction["support_line"], font=label_font, fill=white,
        )
    draw.line(
        (margin, round(height * 0.255), width - margin, round(height * 0.255)),
        fill="#344B5D", width=max(2, round(unit * 0.003)),
    )

    panel = (
        margin, round(height * 0.29), width - margin, round(height * 0.83),
    )
    draw.rounded_rectangle(
        panel, radius=round(unit * 0.03), fill="#111A25",
        outline="#3E5265", width=max(2, round(unit * 0.003)),
    )
    panel_left, panel_top, panel_right, panel_bottom = panel
    draw.text(
        (panel_left + round(unit * 0.03), panel_top + round(unit * 0.025)),
        "AI 模型表层", font=label_font, fill=white,
    )

    person_on_right = direction["composition"]["person_side"] == "right"
    content_left = panel_left + round(unit * 0.035)
    content_right = round(width * (0.53 if person_on_right else 0.47))
    if not person_on_right:
        content_left = round(width * 0.53)
        content_right = panel_right - round(unit * 0.035)

    chip_width = max(round(unit * 0.24), round((content_right - content_left) * 0.56))
    chip_height = round(unit * 0.16)
    chip_x = content_left
    chip_y = panel_top + round(unit * 0.11)
    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + chip_width, chip_y + chip_height),
        radius=round(unit * 0.014), fill="#172B3C", outline=cyan,
        width=max(2, round(unit * 0.003)),
    )
    pin = max(3, round(unit * 0.006))
    for index in range(5):
        px = chip_x + round(chip_width * (index + 1) / 6)
        draw.line((px, chip_y - pin * 2, px, chip_y), fill=cyan, width=pin)
        draw.line(
            (px, chip_y + chip_height, px, chip_y + chip_height + pin * 2),
            fill=cyan, width=pin,
        )
    draw.text(
        (chip_x + round(unit * 0.025), chip_y + round(unit * 0.045)),
        "MODEL CHIP", font=small_font, fill=cyan,
    )

    block_y = chip_y + chip_height + round(unit * 0.055)
    block_height = round(unit * 0.055)
    for index, color in enumerate(("#25435D", "#315675", "#3E6A8E")):
        y0 = block_y + index * round(unit * 0.068)
        draw.rounded_rectangle(
            (content_left, y0, content_right, y0 + block_height),
            radius=round(unit * 0.009), fill=color, outline="#8FC5DD",
            width=max(1, round(unit * 0.002)),
        )
    draw.text(
        (content_left, block_y + round(unit * 0.22)),
        "TRANSFORMER LAYERS", font=micro_font, fill="#B9DDF0",
    )

    network_top = block_y + round(unit * 0.29)
    nodes = [
        (content_left + round((content_right - content_left) * x),
         network_top + round(unit * y))
        for x, y in ((0.08, 0.02), (0.48, 0.00), (0.88, 0.04),
                     (0.28, 0.13), (0.68, 0.14), (0.50, 0.25))
    ]
    for first, second in ((0, 3), (1, 3), (1, 4), (2, 4), (3, 5), (4, 5)):
        draw.line((*nodes[first], *nodes[second]), fill="#587C94", width=max(2, pin // 2))
    for x, y in nodes:
        draw.ellipse(
            (x - pin * 2, y - pin * 2, x + pin * 2, y + pin * 2),
            fill=yellow, outline="#FFF4B8", width=max(1, pin // 2),
        )
    draw.text(
        (content_left, network_top + round(unit * 0.30)),
        "NEURAL NETWORK", font=micro_font, fill="#B9DDF0",
    )

    tear_center = round(width * 0.54)
    tear_half = max(round(unit * 0.065), round(width * 0.055))
    tear_top = panel_top + round(unit * 0.065)
    tear_bottom = panel_bottom - round(unit * 0.065)
    left_edge = []
    right_edge = []
    teeth = 10
    for index in range(teeth + 1):
        y = round(tear_top + (tear_bottom - tear_top) * index / teeth)
        offset = round(unit * (0.015 if index % 2 else -0.010))
        left_edge.append((tear_center - tear_half + offset, y))
        right_edge.append((tear_center + tear_half - offset, y))
    opening = [*left_edge, *reversed(right_edge)]
    draw.polygon(opening, fill="#F3C94D", outline="#FFF2A3")
    inner_labels = ("认知", "行业经验", "岗位上下文", "工作流程")
    for index, text_value in enumerate(inner_labels):
        y = round(tear_top + (tear_bottom - tear_top) * (index + 1) / 5)
        box = draw.textbbox((0, 0), text_value, font=micro_font)
        text_width = box[2] - box[0]
        draw.text(
            (tear_center - text_width // 2, y), text_value,
            font=micro_font, fill="#18140A",
        )

    card_width = round(width * (0.34 if width < height else 0.25))
    card_height = round(height * (0.28 if width < height else 0.50))
    card_x = (
        panel_right - card_width - round(unit * 0.03)
        if person_on_right else panel_left + round(unit * 0.03)
    )
    card_y = panel_bottom - card_height - round(unit * 0.035)
    card = _rounded_person_card(
        person_png, (card_width, card_height), radius=round(unit * 0.025),
    )
    canvas.paste(card, (card_x, card_y), card)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_width, card_y + card_height),
        radius=round(unit * 0.025), outline=yellow,
        width=max(3, round(unit * 0.005)),
    )
    draw.text(
        (card_x + round(unit * 0.018), card_y + round(unit * 0.018)),
        "人物 / 撕开动作区域", font=micro_font, fill=yellow,
        stroke_width=max(1, round(unit * 0.002)), stroke_fill="#08141F",
    )
    arrow_y = card_y + round(card_height * 0.72)
    arrow_start = card_x + round(card_width * 0.44)
    direction_sign = -1 if person_on_right else 1
    arrow_end = arrow_start + direction_sign * round(unit * 0.15)
    draw.line(
        (arrow_start, arrow_y, arrow_end, arrow_y), fill=coral,
        width=max(4, round(unit * 0.008)),
    )
    draw.polygon(
        ((arrow_end, arrow_y),
         (arrow_end - direction_sign * round(unit * 0.025), arrow_y - round(unit * 0.018)),
         (arrow_end - direction_sign * round(unit * 0.025), arrow_y + round(unit * 0.018))),
        fill=coral,
    )

    footer_y = round(height * 0.87)
    draw.text(
        (margin, footer_y), "外层：AI 模型结构", font=small_font, fill="#A8C4D4",
    )
    draw.text(
        (margin, footer_y + round(unit * 0.05)),
        "撕开后：认知 × 经验 × 上下文 × 流程", font=small_font, fill=yellow,
    )
    draw.text(
        (margin, footer_y + round(unit * 0.11)),
        "构图样板，非最终生成图", font=micro_font, fill="#7890A0",
    )

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text(
        "cover_direction_semantics",
        "model-chip transformer-layers neural-network cognition-context-workflow",
    )
    output = io.BytesIO()
    canvas.save(output, format="PNG", pnginfo=metadata, optimize=False)
    return output.getvalue()


def render_direction_board(record: Mapping[str, Any]) -> str:
    direction = record["direction"]
    props = "、".join(direction["props"]) or "无"
    allowed = "、".join(direction["prompt_allow"])
    denied = "、".join(direction["prompt_deny"])
    escaped = lambda value: html.escape(str(value), quote=True)
    support_markup = (
        f'<div class="support">{escaped(direction["support_line"])}</div>'
        if direction.get("support_line") else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<title>封面方向审核</title>
<style>
body{{margin:0;background:#121212;color:#f5f0e8;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}
main{{max-width:1200px;margin:0 auto;padding:48px}} .board{{display:grid;grid-template-columns:minmax(360px,48%) 1fr;gap:32px;align-items:start}}
.preview{{width:100%;height:auto;max-height:84vh;object-fit:contain;border-radius:24px;background:#08141f}}
h1{{font-size:58px;line-height:1.02;margin:0 0 10px}}
.sub{{font-size:28px;color:#ffd84d}} dl{{display:grid;grid-template-columns:7em 1fr;gap:12px 20px}}
.support{{font-size:20px;color:#f5f0e8;margin-top:6px}}
dt{{color:#a9a9a9}} dd{{margin:0}} code{{word-break:break-all}}
</style><main><div class="board">
<img class="preview" src="direction-preview.png" alt="封面方向构图样板预览，不是正式封面">
<section><h1>{escaped(direction['title'])}</h1><div class="sub">{escaped(direction['subtitle'])}</div>{support_markup}
<p>构图样板，非最终生成图</p>
<dl><dt>动作</dt><dd>{escaped(direction['pose'])}</dd><dt>表情</dt><dd>{escaped(direction['expression'])}</dd>
<dt>环境</dt><dd>{escaped(direction['environment'])}</dd><dt>道具</dt><dd>{escaped(props)}</dd>
<dt>输出比例</dt><dd>{escaped(direction['output_aspect_ratio'])}</dd>
<dt>构图</dt><dd>{escaped(direction['composition'])}</dd><dt>色板</dt><dd>{escaped(direction['palette'])}</dd>
<dt>必须出现</dt><dd>{escaped(allowed)}</dd><dt>禁止出现</dt><dd>{escaped(denied)}</dd>
<dt>方向 SHA</dt><dd><code>{escaped(record['direction_sha256'])}</code></dd></dl></section>
</div></main></html>"""


def prepare_cover_direction(
    job: state.JobState,
    direction: Mapping[str, Any],
    *,
    frame_reader: Callable[[Path, float], bytes] | None = None,
    direction_preview: Path | None = None,
) -> Dict[str, Any]:
    state.require_runnable(job, "cover_direction")
    composition = direction.get("composition") if isinstance(direction, Mapping) else None
    if (
        isinstance(composition, Mapping)
        and composition.get("style_id") == _PUNK_STYLE
        and direction_preview is None
    ):
        raise CoverDirectionError("Punk cover direction requires an explicit PNG preview")
    preview_bytes = None
    if direction_preview is not None:
        preview_bytes = _read_direction_preview(
            job, direction_preview, direction.get("output_aspect_ratio")
            if isinstance(direction, Mapping) and isinstance(
                direction.get("output_aspect_ratio"), str
            ) else ""
        )
    analysis = content_analysis.load_approved_content_analysis(job)
    person_input = _person_input(
        direction.get("person_reference") if isinstance(direction, Mapping) else None,
    )
    if person_input["source"] == "current-aroll-video":
        timestamp = person_input["timestamp"]
        video = job.root / job.inputs["video"]["path"]
        source = (frame_reader or _frame_at)(video, timestamp)
        reference_identity = {
            "source": "current-aroll-video",
            "timestamp": timestamp,
            "video_sha256": job.inputs["video"]["sha256"],
        }
    else:
        source, material_sha256 = _user_material(
            job, person_input["material_id"]
        )
        reference_identity = {
            "source": "user-material",
            "material_id": person_input["material_id"],
            "material_sha256": material_sha256,
        }
    png = _validated_png(source)
    output = job.job_dir / "03-cover-direction"
    reference_path = output / "person-reference.png"
    reference = {
        **reference_identity,
        "path": "03-cover-direction/person-reference.png",
        "sha256": hashlib.sha256(png).hexdigest(),
        "bytes": len(png),
    }
    normalized = _normalize_direction(direction, analysis, reference)
    contract_artifacts.write_bytes_atomic(reference_path, png)
    base = {
        "schema_version": 1,
        "content_analysis_sha256": analysis["analysis_sha256"],
        "direction": normalized,
    }
    record = {**base, "direction_sha256": contract_artifacts.sha256_json(base)}
    record_path = output / "cover-direction.json"
    review_path = output / "review.html"
    preview_path = output / "direction-preview.png"
    contract_artifacts.write_json_artifact(record_path, record)
    contract_artifacts.write_bytes_atomic(
        preview_path,
        preview_bytes if preview_bytes is not None
        else _render_direction_preview(normalized, png),
    )
    contract_artifacts.write_text_artifact(review_path, render_direction_board(record))
    references = []
    if reference_identity["source"] == "user-material":
        references.append(
            {
                "material_id": reference_identity["material_id"],
                "material_sha256": reference_identity["material_sha256"],
                "consumer_kind": "cover_reference",
                "consumer_id": "cover-direction",
                "binding_path": "/direction/person_reference/material_id",
                "artifact_paths": [
                    "03-cover-direction/person-reference.png",
                    "03-cover-direction/direction-preview.png",
                ],
            }
        )
    material_usage.publish_and_mark_ready(
        job,
        "cover_direction",
        (record_path, preview_path, review_path, reference_path),
        producer="edit.hd.tools.cover_direction",
        producer_version="1",
        stage_input_records=material_usage.current_stage_input_records(
            job, "cover_direction"
        ),
        references=references,
    )
    return record


def _validate_reference(job: state.JobState, reference: Mapping[str, Any]) -> None:
    if not isinstance(reference, Mapping):
        raise CoverDirectionError("person_reference schema is invalid")
    source_kind = reference.get("source")
    keys = _AROLL_RECORD_KEYS if source_kind == "current-aroll-video" else (
        _MATERIAL_RECORD_KEYS if source_kind == "user-material" else set()
    )
    value = _object(reference, keys, "person_reference")
    if value["path"] != "03-cover-direction/person-reference.png" or (
        type(value["bytes"]) is not int
        or value["bytes"] <= 0
        or type(value["sha256"]) is not str
        or _SHA.fullmatch(value["sha256"]) is None
    ):
        raise CoverDirectionError("person_reference identity is invalid")
    if source_kind == "current-aroll-video":
        if value["video_sha256"] != job.inputs["video"]["sha256"]:
            raise CoverDirectionError("person_reference identity is invalid")
    else:
        _data, material_sha256 = _user_material(job, value["material_id"])
        if value["material_sha256"] != material_sha256:
            raise CoverDirectionError("person_reference identity changed")
    path = job.job_dir / value["path"]
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise CoverDirectionError("person_reference is unavailable") from exc
    if len(source) != value["bytes"] or hashlib.sha256(source).hexdigest() != value["sha256"]:
        raise CoverDirectionError("person_reference identity changed")


def load_approved_cover_direction(job: state.JobState) -> Dict[str, Any]:
    if "cover_direction" not in job.stages:
        raise CoverDirectionError("cover_direction is unavailable for legacy workflow")
    if job.stages["cover_direction"]["status"] != "approved":
        raise CoverDirectionError("cover_direction must be approved")
    record = contract_artifacts.read_json_artifact(
        job.job_dir / "03-cover-direction" / "cover-direction.json"
    )
    if set(record) != {
        "schema_version", "content_analysis_sha256", "direction", "direction_sha256",
    } or record["schema_version"] != 1:
        raise CoverDirectionError("cover_direction record is invalid")
    analysis = content_analysis.load_approved_content_analysis(job)
    if record["content_analysis_sha256"] != analysis["analysis_sha256"]:
        raise CoverDirectionError("cover_direction content identity changed")
    _validate_reference(job, record["direction"].get("person_reference", {}))
    reference = record["direction"]["person_reference"]
    person_input = (
        {"source": reference["source"], "timestamp": reference["timestamp"]}
        if reference["source"] == "current-aroll-video"
        else {"source": reference["source"], "material_id": reference["material_id"]}
    )
    normalized = _normalize_direction(
        {**record["direction"], "person_reference": person_input},
        analysis,
        reference,
    )
    base = {
        "schema_version": 1,
        "content_analysis_sha256": analysis["analysis_sha256"],
        "direction": normalized,
    }
    expected = contract_artifacts.sha256_json(base)
    if record["direction_sha256"] != expected:
        raise CoverDirectionError("cover_direction identity changed")
    return {**base, "direction_sha256": expected}

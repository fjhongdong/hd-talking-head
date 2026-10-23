from __future__ import annotations

import json
import hashlib
import io
import ctypes
import errno
import fcntl
import math
import os
import re
import secrets
import select
import stat
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from edit.v5.tools import bold_subtitles
from edit.hd.tools import state, visual_plan as visual_plan_module


__all__ = [
    "SubtitleError",
    "validate_subtitle_plan",
    "render_subtitle_frame",
    "build_final_overlay_command",
    "prepare_subtitles",
]


_TYPES = ("emphasis", "statement", "source", "action")
_TOP_KEYS = {"version", "canvas", "source_bindings", "layout_counts", "cues"}
_CANVAS_KEYS = {"width", "height", "fps", "frames", "duration"}
_BINDING_KEYS = {
    "word_transcript", "timeline_map", "edited_aroll", "visual_plan",
    "asset_manifest", "visual_track",
}
_FILE_KEYS = {"path", "sha256", "bytes"}
_CUE_KEYS = {
    "id", "type", "segment_id", "start", "end", "text",
    "emphasis_words", "safe_zones", "box",
}
_EVENT_CUE_KEYS = _CUE_KEYS | {"event_id"}
_ZONE_KEYS = {"face", "subtitle", "source", "chart"}
_RECT_KEYS = {"x", "y", "width", "height"}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OUTPUT_NAMES = {
    "subtitle-plan.json", "subtitles.webm", "subtitles.srt", "contact-sheet.png",
}
_ASSET_KEYS = {
    "path", "sha256", "bytes", "type", "segment_id", "generation_id",
    "requested_duration", "used_duration", "frames", "source_label",
    "source_preview", "selection",
}
_MANIFEST_KEYS = {
    "version", "generation_id", "visual_plan", "inputs", "canvas", "duration",
    "frames", "routing_summary", "ai_attempts", "assets",
}
_LOCK_NAME = ".06-subtitles.lock"
_LOCK_BYTES = b"HD subtitles lock v1\n"
_TRANSACTION_NAME = ".06-subtitles.transaction.json"

OUTLINE = (8, 8, 10, 255)
WHITE = (250, 249, 245, 255)
WARM_YELLOW = (255, 196, 42, 255)
_CUE_TARGET_MIN = 8
_CUE_TARGET_MAX = 14
_CUE_TARGET_CENTER = 11
_ART_WORD_OFFSETS = (0, -4, 3, -2, 4, -3)
_ART_WORD_ROTATION = 5.0
_ART_WORD_SHADOW_OFFSET = 4


class SubtitleError(RuntimeError):
    """A safe, user-facing subtitle-stage failure."""


class _PinnedFile:
    def __init__(
        self,
        path: Path,
        descriptor: int,
        status: os.stat_result,
        sha256: str,
        size: int,
    ) -> None:
        self.path = path
        self.descriptor = descriptor
        self.status = status
        self.sha256 = sha256
        self.size = size

    def close(self) -> None:
        if self.descriptor >= 0:
            descriptor = self.descriptor
            self.descriptor = -1
            os.close(descriptor)


def _checkpoint(name: str) -> None:
    if os.environ.get("HD_SUBTITLES_CRASH_CHECKPOINT") == name:
        os._exit(91)


def _fail() -> SubtitleError:
    return SubtitleError("subtitle operation failed")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _fail()


def parse_subtitle_plan_json(source: str) -> dict[str, object]:
    if type(source) is not str:
        raise _fail()
    try:
        payload = json.loads(
            source,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError, SubtitleError):
        raise _fail() from None
    return validate_subtitle_plan(payload)


def _number(value: object, *, positive: bool = False) -> float:
    if type(value) not in {int, float}:
        raise _fail()
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise _fail()
    return result


def _text(value: object) -> str:
    if type(value) is not str or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise _fail()
    return value


def _record(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _FILE_KEYS:
        raise _fail()
    path = _text(value["path"])
    relative = Path(path)
    if (
        relative.is_absolute()
        or path in {".", ".."}
        or "." in relative.parts
        or ".." in relative.parts
        or "\\" in path
        or type(value["sha256"]) is not str
        or _SHA256.fullmatch(value["sha256"]) is None
        or type(value["bytes"]) is not int
        or value["bytes"] < 0
    ):
        raise _fail()
    return value


def _digest_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)
    return digest.hexdigest(), size


def _safe_relative(value: object) -> Path:
    path = _text(value)
    relative = Path(path)
    if (
        relative.is_absolute() or path in {".", ".."}
        or "." in relative.parts or ".." in relative.parts
        or "\\" in path
    ):
        raise _fail()
    return relative


def _reject_symlinks(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            status = os.lstat(current)
        except OSError:
            raise _fail() from None
        if stat.S_ISLNK(status.st_mode):
            raise _fail()


def _pin(path: Path, record: object) -> _PinnedFile:
    checked = _record(record)
    _reject_symlinks(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        status = os.fstat(descriptor)
        visible = os.lstat(path)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or not stat.S_ISREG(visible.st_mode) or visible.st_nlink != 1
            or not os.path.samestat(status, visible)
        ):
            raise _fail()
        sha256, size = _digest_descriptor(descriptor)
        if (
            checked["sha256"] != sha256 or checked["bytes"] != size
            or path.name != _safe_relative(checked["path"]).name
        ):
            raise _fail()
        return _PinnedFile(path, descriptor, status, sha256, size)
    except BaseException:
        if "descriptor" in locals():
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _fail() from None


def _verify_pin(pin: _PinnedFile) -> None:
    try:
        descriptor_status = os.fstat(pin.descriptor)
        visible = os.lstat(pin.path)
        digest = _digest_descriptor(pin.descriptor)
    except OSError:
        raise _fail() from None
    if (
        descriptor_status.st_nlink != 1 or visible.st_nlink != 1
        or not os.path.samestat(pin.status, descriptor_status)
        or not os.path.samestat(pin.status, visible)
        or digest != (pin.sha256, pin.size)
    ):
        raise _fail()


def _descriptor_bytes(pin: _PinnedFile, maximum: int = 32 * 1024 * 1024) -> bytes:
    if pin.size > maximum:
        raise _fail()
    position = os.lseek(pin.descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(pin.descriptor, 0, os.SEEK_SET)
        result = bytearray()
        while len(result) <= maximum:
            block = os.read(pin.descriptor, min(1024 * 1024, maximum + 1 - len(result)))
            if not block:
                return bytes(result)
            result.extend(block)
    finally:
        os.lseek(pin.descriptor, position, os.SEEK_SET)
    raise _fail()


def _strict_json(source: bytes) -> object:
    try:
        return json.loads(
            source.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, SubtitleError):
        raise _fail() from None


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _stage_records(
    job: state.JobState,
    stage_id: str,
    directory_name: str,
    expected_names: set[str] | None = None,
) -> dict[str, tuple[dict[str, object], _PinnedFile]]:
    stage_record = job.stages.get(stage_id)
    if type(stage_record) is not dict or stage_record.get("status") != "approved":
        raise _fail()
    artifacts = stage_record.get("artifacts")
    if type(artifacts) is not list:
        raise _fail()
    result: dict[str, tuple[dict[str, object], _PinnedFile]] = {}
    try:
        for artifact in artifacts:
            checked = _record(artifact)
            relative = _safe_relative(checked["path"])
            try:
                local = relative.relative_to(directory_name)
            except ValueError:
                raise _fail()
            local_name = local.as_posix()
            if local_name in {"", "."} or local_name in result:
                raise _fail()
            result[local_name] = (
                checked,
                _pin(job.job_dir.joinpath(*relative.parts), checked),
            )
        if expected_names is not None and set(result) != expected_names:
            raise _fail()
        return result
    except BaseException:
        for _record_value, pin in result.values():
            try:
                pin.close()
            except OSError:
                pass
        raise _fail() from None


def _rect(value: object, *, width: int, height: int) -> dict[str, int]:
    if type(value) is not dict or set(value) != _RECT_KEYS:
        raise _fail()
    if any(type(value[key]) is not int for key in _RECT_KEYS):
        raise _fail()
    if (
        value["x"] < 0 or value["y"] < 0
        or value["width"] <= 0 or value["height"] <= 0
        or value["x"] + value["width"] > width
        or value["y"] + value["height"] > height
    ):
        raise _fail()
    return value


def _intersects(left: dict[str, int], right: dict[str, int]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


def validate_subtitle_plan(payload: object) -> dict[str, object]:
    """Validate the complete dynamic HD subtitle plan with a closed schema."""
    try:
        if type(payload) is not dict or set(payload) != _TOP_KEYS:
            raise _fail()
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise _fail()
        canvas = payload["canvas"]
        if type(canvas) is not dict or set(canvas) != _CANVAS_KEYS:
            raise _fail()
        if (
            type(canvas["width"]) is not int or canvas["width"] != 1080
            or type(canvas["height"]) is not int or canvas["height"] != 1920
            or type(canvas["fps"]) is not int or canvas["fps"] != 24
            or type(canvas["frames"]) is not int or canvas["frames"] <= 0
        ):
            raise _fail()
        duration = _number(canvas["duration"], positive=True)
        if canvas["frames"] != round(duration * 24) or abs(duration - canvas["frames"] / 24) > 1e-6:
            raise _fail()
        bindings = payload["source_bindings"]
        if type(bindings) is not dict or set(bindings) != _BINDING_KEYS:
            raise _fail()
        for binding in bindings.values():
            _record(binding)
        counts = payload["layout_counts"]
        if (
            type(counts) is not dict or set(counts) != set(_TYPES)
            or any(type(counts[name]) is not int or counts[name] < 0 for name in _TYPES)
        ):
            raise _fail()
        cues = payload["cues"]
        if type(cues) is not list:
            raise _fail()
        seen: set[str] = set()
        actual = {name: 0 for name in _TYPES}
        previous_end = 0.0
        for cue in cues:
            if type(cue) is not dict or set(cue) not in (_CUE_KEYS, _EVENT_CUE_KEYS):
                raise _fail()
            cue_id = _text(cue["id"])
            segment_id = _text(cue["segment_id"])
            if (
                _SAFE_ID.fullmatch(cue_id) is None or cue_id in seen
                or _SAFE_ID.fullmatch(segment_id) is None
            ):
                raise _fail()
            if "event_id" in cue and _SAFE_ID.fullmatch(_text(cue["event_id"])) is None:
                raise _fail()
            seen.add(cue_id)
            cue_type = cue["type"]
            if cue_type not in _TYPES:
                raise _fail()
            actual[cue_type] += 1
            start = _number(cue["start"])
            end = _number(cue["end"])
            sample_index = min(
                canvas["frames"] - 2,
                max(1, round(((start + end) / 2) * canvas["fps"])),
            )
            sample_time = sample_index / canvas["fps"]
            if (
                start < previous_end
                or start < 1 / canvas["fps"]
                or end <= start
                or end > duration - 1 / canvas["fps"]
                or not start <= sample_time < end
            ):
                raise _fail()
            previous_end = end
            text = _text(cue["text"])
            emphasis = cue["emphasis_words"]
            if type(emphasis) is not list:
                raise _fail()
            emphasis = [_text(word) for word in emphasis]
            if emphasis and not any(word in text for word in emphasis):
                raise _fail()
            zones = cue["safe_zones"]
            if type(zones) is not dict or set(zones) != _ZONE_KEYS:
                raise _fail()
            for zone in zones.values():
                if zone is not None:
                    _rect(zone, width=canvas["width"], height=canvas["height"])
            box = _rect(cue["box"], width=canvas["width"], height=canvas["height"])
            subtitle_zone = zones["subtitle"]
            if subtitle_zone is None or not (
                subtitle_zone["x"] <= box["x"]
                and subtitle_zone["y"] <= box["y"]
                and box["x"] + box["width"]
                <= subtitle_zone["x"] + subtitle_zone["width"]
                and box["y"] + box["height"]
                <= subtitle_zone["y"] + subtitle_zone["height"]
            ):
                raise _fail()
            forbidden = [zones[name] for name in ("face", "source", "chart") if zones[name] is not None]
            forbidden.append({"x": 0, "y": 1800, "width": 1080, "height": 120})
            if any(_intersects(box, zone) for zone in forbidden):
                raise _fail()
        if actual != counts:
            raise _fail()
        return payload
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(error, SubtitleError):
            raise error from None
        raise _fail() from None


def _cue_opacity(cue: dict[str, object], timestamp: float) -> float:
    start = float(cue["start"])
    end = float(cue["end"])
    if timestamp < start or timestamp >= end:
        return 0.0
    fade = min(0.15, (end - start) / 2)
    if fade <= 0:
        return 0.0
    opacity = min(1.0, (timestamp - start) / fade, (end - timestamp) / fade)
    if opacity >= 1.0 - 1e-9:
        return 1.0
    return max(0.0, opacity)


def _art_word_geometry(
    text: str, font_path: Path, body_size: int,
) -> dict[str, object]:
    art_size = round(body_size * 1.3)
    font = ImageFont.truetype(str(font_path), art_size)
    offsets = [
        _ART_WORD_OFFSETS[index % len(_ART_WORD_OFFSETS)]
        for index in range(len(text))
    ]
    advances = [float(font.getlength(character)) for character in text]
    positions: list[float] = []
    cursor = 0.0
    left = top = math.inf
    right = bottom = -math.inf
    for character, offset, advance in zip(text, offsets, advances):
        positions.append(cursor)
        glyph = font.getbbox(character, stroke_width=2)
        left = min(left, cursor + glyph[0])
        top = min(top, offset + glyph[1])
        right = max(right, cursor + glyph[2] + _ART_WORD_SHADOW_OFFSET)
        bottom = max(bottom, offset + glyph[3] + _ART_WORD_SHADOW_OFFSET)
        cursor += advance
    if not positions or not all(math.isfinite(value) for value in (left, top, right, bottom)):
        raise _fail()
    padding = 3
    unrotated_width = max(1, math.ceil(right - left) + padding * 2)
    unrotated_height = max(1, math.ceil(bottom - top) + padding * 2)
    radians = math.radians(_ART_WORD_ROTATION)
    rotated_width = math.ceil(
        abs(unrotated_width * math.cos(radians))
        + abs(unrotated_height * math.sin(radians))
    ) + 2
    rotated_height = math.ceil(
        abs(unrotated_width * math.sin(radians))
        + abs(unrotated_height * math.cos(radians))
    ) + 2
    return {
        "font": font,
        "font_size": art_size,
        "offsets": offsets,
        "positions": positions,
        "origin": (padding - left, padding - top),
        "unrotated_size": (unrotated_width, unrotated_height),
        "rotated_size": (rotated_width, rotated_height),
    }


def _render_art_word_unrotated(
    text: str, font_path: Path, body_size: int,
) -> tuple[Image.Image, dict[str, object]]:
    """Render one deterministic group of upright, baseline-offset glyphs."""
    geometry = _art_word_geometry(text, font_path, body_size)
    layer = Image.new("RGBA", geometry["unrotated_size"], (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    origin_x, origin_y = geometry["origin"]
    font = geometry["font"]
    for character, x, offset in zip(
        text, geometry["positions"], geometry["offsets"]
    ):
        draw.text(
            (
                origin_x + x + _ART_WORD_SHADOW_OFFSET,
                origin_y + offset + _ART_WORD_SHADOW_OFFSET,
            ),
            character,
            font=font,
            fill=(8, 8, 10, 176),
            stroke_width=2,
            stroke_fill=(8, 8, 10, 176),
        )
    for character, x, offset in zip(
        text, geometry["positions"], geometry["offsets"]
    ):
        draw.text(
            (origin_x + x, origin_y + offset),
            character,
            font=font,
            fill=WARM_YELLOW,
            stroke_width=2,
            stroke_fill=OUTLINE,
        )
    alpha_box = layer.getchannel("A").getbbox()
    if alpha_box is None:
        raise _fail()
    layer = layer.crop(alpha_box)
    metadata = {
        "text": text,
        "font_size": geometry["font_size"],
        "rotation_degrees": 0.0,
        "glyph_rotations": [0] * len(text),
        "baseline_offsets": list(geometry["offsets"]),
    }
    return layer, metadata


def _render_art_word(
    text: str, font_path: Path, body_size: int,
) -> tuple[Image.Image, dict[str, object]]:
    """Rotate one completed upright-glyph group counterclockwise."""
    layer, metadata = _cached_art_word_template(
        text,
        str(font_path),
        body_size,
        tuple(_ART_WORD_OFFSETS),
        _ART_WORD_ROTATION,
    )
    return layer.copy(), {
        **metadata,
        "glyph_rotations": list(metadata["glyph_rotations"]),
        "baseline_offsets": list(metadata["baseline_offsets"]),
    }


@lru_cache(maxsize=1024)
def _cached_art_word_template(
    text: str,
    font_path: str,
    body_size: int,
    offsets: tuple[int, ...],
    rotation: float,
) -> tuple[Image.Image, dict[str, object]]:
    if offsets != tuple(_ART_WORD_OFFSETS):
        raise _fail()
    layer, metadata = _render_art_word_unrotated(
        text, Path(font_path), body_size
    )
    resampling = getattr(Image, "Resampling", Image)
    metadata = {**metadata, "rotation_degrees": rotation}
    return (
        layer.rotate(
            rotation,
            resample=resampling.BICUBIC,
            expand=True,
        ),
        metadata,
    )


def _visible_emphasis(text: str, candidates: object) -> str:
    if not candidates:
        return ""
    for candidate in candidates:
        visible = str(candidate).strip()
        if visible and visible in text:
            return visible
    return next((word for word in text.split() if word), "")


def _semantic_emphasis(text: str, keywords: list[str]) -> str:
    best: tuple[int, int, int, int, str] | None = None
    for keyword_index, keyword in enumerate(keywords):
        compact_keyword = "".join(str(keyword).split())
        folded_keyword = compact_keyword.casefold()
        if len(folded_keyword) < 2:
            continue
        for start in range(len(text)):
            for end in range(start + 2, len(text) + 1):
                candidate = text[start:end]
                compact_candidate = "".join(candidate.split())
                if len(compact_candidate) < 2:
                    continue
                if compact_candidate.casefold() not in folded_keyword:
                    continue
                if len(compact_candidate) < len(compact_keyword) and (
                    candidate.startswith("的") or candidate.endswith("不")
                ):
                    continue
                if compact_candidate.isascii() and compact_candidate.isalnum():
                    if start > 0 and text[start - 1].isascii() and text[start - 1].isalnum():
                        continue
                    if end < len(text) and text[end].isascii() and text[end].isalnum():
                        continue
                keyword_position = folded_keyword.rfind(compact_candidate.casefold())
                score = (
                    _visible_glyph_count([{"text": candidate}]),
                    keyword_position,
                    -keyword_index,
                    -start,
                    candidate,
                )
                if best is None or score > best:
                    best = score
    return "" if best is None else best[-1]


def _semantic_emphasis_assignments(
    texts: list[str], keywords: list[str]
) -> list[str]:
    assignments = ["" for _text in texts]
    exact_keywords: set[int] = set()
    exact_matches: list[tuple[int, int, int, int, str]] = []
    for keyword_index, keyword in enumerate(keywords):
        visible_keyword = str(keyword).strip()
        if not visible_keyword:
            continue
        for cue_index, text in enumerate(texts):
            occurrence = re.search(
                re.escape(visible_keyword), text, flags=re.IGNORECASE
            )
            if occurrence is None:
                continue
            exact_keywords.add(keyword_index)
            exact_matches.append((
                _visible_glyph_count([{"text": visible_keyword}]),
                -keyword_index,
                -cue_index,
                cue_index,
                occurrence.group(0),
            ))
    for _length, _keyword_rank, _cue_rank, cue_index, candidate in sorted(
        exact_matches, reverse=True
    ):
        if not assignments[cue_index]:
            assignments[cue_index] = candidate

    matches: list[tuple[tuple[int, int, int, int], int, int, str]] = []
    for keyword_index, keyword in enumerate(keywords):
        if keyword_index in exact_keywords:
            continue
        compact_keyword = "".join(str(keyword).split()).casefold()
        for cue_index, text in enumerate(texts):
            if assignments[cue_index]:
                continue
            candidate = _semantic_emphasis(text, [keyword])
            if not candidate:
                continue
            score = (
                _visible_glyph_count([{"text": candidate}]),
                compact_keyword.rfind("".join(candidate.split()).casefold()),
                -keyword_index,
                -cue_index,
            )
            matches.append((score, cue_index, keyword_index, candidate))
    used_keywords: set[int] = set()
    for _score, cue_index, keyword_index, candidate in sorted(
        matches, reverse=True
    ):
        if keyword_index in used_keywords or assignments[cue_index]:
            continue
        assignments[cue_index] = candidate
        used_keywords.add(keyword_index)
    return assignments


def _display_span(text: str, start: int, end: int) -> tuple[str, int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return text[start:end], start, end


def _art_line_width(
    text: str,
    display_start: int,
    display_end: int,
    emphasis_start: int,
    emphasis_end: int,
    font_path: Path,
    body_size: int,
    art_width: int,
) -> float:
    if display_start <= emphasis_start and emphasis_end <= display_end:
        return (
            _font_text_width(
                str(font_path), body_size, text[display_start:emphasis_start]
            )
            + art_width
            + _font_text_width(
                str(font_path), body_size, text[emphasis_end:display_end]
            )
        )
    return _font_text_width(
        str(font_path), body_size, text[display_start:display_end]
    )


def _compute_art_word_layout(
    text: str,
    emphasis: str,
    font_path_value: str,
    box_x: int,
    box_y: int,
    box_width: int,
    box_height: int,
    cue_type: str,
) -> tuple[
    tuple[str, ...], int, tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...], tuple[int, ...],
]:
    if cue_type not in _TYPES:
        raise _fail()
    font_path = Path(font_path_value)
    emphasis_start = text.find(emphasis)
    emphasis_end = emphasis_start + len(emphasis)
    if emphasis_start < 0:
        raise _fail()
    max_width = box_width - 48
    max_height = box_height - 8
    for body_size in range(64, 35, -1):
        geometry = _art_word_geometry(emphasis, font_path, body_size)
        art_width, art_height = geometry["rotated_size"]
        raw_candidates = [((0, len(text)),)]
        raw_candidates.extend(
            ((0, boundary), (boundary, len(text)))
            for boundary in range(1, len(text))
            if not emphasis_start < boundary < emphasis_end
        )
        candidates: list[tuple[float, float, list[tuple[str, int, int]], list[int]]] = []
        for raw_lines in raw_candidates:
            display = [_display_span(text, start, end) for start, end in raw_lines]
            if any(line is None for line in display):
                continue
            lines = [line for line in display if line is not None]
            containing = [
                index for index, (_line, start, end) in enumerate(lines)
                if start <= emphasis_start and emphasis_end <= end
            ]
            if len(containing) != 1:
                continue
            widths = [
                _art_line_width(
                    text, start, end, emphasis_start, emphasis_end,
                    font_path, body_size, art_width,
                )
                for _line, start, end in lines
            ]
            if max(widths) > max_width:
                continue
            heights = [body_size + 10 for _line in lines]
            heights[containing[0]] = max(heights[containing[0]], art_height + 4)
            total_height = sum(heights) - 10
            if total_height > max_height:
                continue
            imbalance = 0.0 if len(widths) == 1 else abs(widths[0] - widths[1])
            candidates.append((max(widths), imbalance, lines, heights))
        if not candidates:
            continue
        one_line = [candidate for candidate in candidates if len(candidate[2]) == 1]
        chosen = one_line[0] if one_line else min(candidates, key=lambda item: item[:2])
        lines = chosen[2]
        display_spans = [(start, end) for _line, start, end in lines]
        boundaries = [span[0] for span in display_spans[1:]]
        return (
            tuple(line for line, _start, _end in lines),
            body_size,
            tuple(zip(
                [0, *boundaries], [*boundaries, len(text)]
            )),
            tuple(display_spans),
            tuple(chosen[3]),
        )
    raise bold_subtitles.SubtitleError(
        "subtitle text cannot fit inside the safe area"
    )


@lru_cache(maxsize=1024)
def _cached_art_word_layout(
    text: str,
    emphasis: str,
    font_path: str,
    box_x: int,
    box_y: int,
    box_width: int,
    box_height: int,
    cue_type: str,
) -> tuple[
    tuple[str, ...], int, tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...], tuple[int, ...],
]:
    return _compute_art_word_layout(
        text, emphasis, font_path, box_x, box_y, box_width, box_height,
        cue_type,
    )


def _layout_text_with_art_word(
    text: str,
    emphasis: str,
    font_path: Path,
    box: dict[str, int],
    cue_type: str,
) -> dict[str, object]:
    lines, size, line_spans, display_spans, line_heights = (
        _cached_art_word_layout(
            text,
            emphasis,
            str(font_path),
            box["x"],
            box["y"],
            box["width"],
            box["height"],
            cue_type,
        )
    )
    return {
        "lines": list(lines),
        "font_size": size,
        "line_spans": list(line_spans),
        "display_spans": list(display_spans),
        "line_heights": list(line_heights),
    }


def render_subtitle_frame(
    cues: list[dict[str, object]], timestamp: float
) -> Image.Image:
    """Render one deterministic transparent HD subtitle frame."""
    frame = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if type(cues) is not list or type(timestamp) not in {int, float} or not math.isfinite(timestamp):
        raise _fail()
    active = next(
        (
            cue for cue in cues
            if float(cue["start"]) <= float(timestamp) < float(cue["end"])
        ),
        None,
    )
    if active is None:
        return frame
    text = str(active["text"])
    font_path = bold_subtitles.find_cjk_font(
        "".join(str(cue["text"]) for cue in cues)
    )
    box = active["box"]
    cue_type = active["type"]
    if cue_type not in _TYPES:
        raise _fail()
    emphasis = _visible_emphasis(text, active["emphasis_words"])
    layout = (
        _layout_text_for_box(text, font_path, box, cue_type)
        if not emphasis
        else _layout_text_with_art_word(text, emphasis, font_path, box, cue_type)
    )
    font = ImageFont.truetype(str(font_path), layout["font_size"])
    draw = ImageDraw.Draw(frame)
    x, y = box["x"], box["y"]
    lines = layout["lines"]
    emphasis_start = text.find(emphasis) if emphasis else -1
    emphasis_end = emphasis_start + len(emphasis) if emphasis_start >= 0 else -1
    art_layer = None
    if emphasis:
        art_layer, _metadata = _render_art_word(
            emphasis, font_path, layout["font_size"]
        )
    line_heights = layout.get(
        "line_heights", [layout["font_size"] + 10] * len(lines)
    )
    total_height = sum(line_heights) - 10
    text_y = y + (box["height"] - total_height) // 2
    draw.rectangle((x, y, x + 2, y + box["height"] - 1), fill=WARM_YELLOW)
    line_top = text_y
    for index, line in enumerate(lines):
        line_start, line_end = layout["display_spans"][index]
        contains_emphasis = (
            emphasis_start >= 0
            and line_start <= emphasis_start
            and emphasis_end <= line_end
        )
        if contains_emphasis and art_layer is not None:
            line_width = _art_line_width(
                text, line_start, line_end, emphasis_start, emphasis_end,
                font_path, layout["font_size"], art_layer.width,
            )
        else:
            line_width = draw.textlength(line, font=font)
        text_x = x + (box["width"] - line_width) / 2
        line_height = line_heights[index]
        line_y = line_top + (line_height - (layout["font_size"] + 10)) / 2
        if not contains_emphasis or art_layer is None:
            draw.text(
                (text_x, line_y), line, font=font, fill=WHITE,
                stroke_width=1, stroke_fill=OUTLINE,
            )
        else:
            before = text[line_start:emphasis_start]
            after = text[emphasis_end:line_end]
            if before:
                draw.text(
                    (text_x, line_y), before, font=font, fill=WHITE,
                    stroke_width=1, stroke_fill=OUTLINE,
                )
            art_x = text_x + draw.textlength(before, font=font)
            art_y = line_top + (line_height - art_layer.height) / 2
            frame.alpha_composite(
                art_layer, (round(art_x), round(art_y))
            )
            if after:
                after_x = art_x + art_layer.width
                draw.text(
                    (after_x, line_y), after, font=font, fill=WHITE,
                    stroke_width=1, stroke_fill=OUTLINE,
                )
        line_top += line_height
    opacity = _cue_opacity(active, timestamp)
    if opacity < 1.0:
        frame.putalpha(
            frame.getchannel("A").point(lambda value: round(value * opacity))
        )
    return frame


def _validate_words(value: object) -> list[dict[str, object]]:
    if type(value) is not dict or set(value) != {"version", "words"}:
        raise _fail()
    if type(value["version"]) is not int or value["version"] != 1:
        raise _fail()
    words = value["words"]
    if type(words) is not list or not words:
        raise _fail()
    previous_end = 0.0
    for word in words:
        if type(word) is not dict or set(word) != {"text", "start", "end"}:
            raise _fail()
        _text(word["text"])
        start = _number(word["start"])
        end = _number(word["end"])
        if start < previous_end or end <= start:
            raise _fail()
        previous_end = end
    return words


def _validate_timeline(
    value: object,
    *,
    workflow_version: int = 2,
) -> dict[str, object]:
    keys = {
        "version", "source_duration", "output_duration", "has_deletion",
        "audio_policy", "render_adapter", "segments",
    }
    if type(value) is not dict or set(value) != keys:
        raise _fail()
    if type(value["version"]) is not int or value["version"] != 1:
        raise _fail()
    source_duration = _number(value["source_duration"], positive=True)
    output_duration = _number(value["output_duration"], positive=True)
    if type(value["has_deletion"]) is not bool or type(value["audio_policy"]) is not str:
        raise _fail()
    if workflow_version == 1:
        expected_adapter = (
            "local-ffmpeg-trim-concat"
            if value["has_deletion"]
            else "local-ffmpeg-no-cut"
        )
    elif workflow_version == 2:
        expected_adapter = (
            "video-use/helpers/render.py"
            if value["has_deletion"]
            else "native-ffmpeg-no-cut"
        )
    else:
        raise _fail()
    if value["render_adapter"] != expected_adapter:
        raise _fail()
    segments = value["segments"]
    if type(segments) is not list or not segments:
        raise _fail()
    # The edit timeline is authored on the audio clock; rendered video is
    # quantized to 24 fps. Allow one frame of per-cut rounding while retaining
    # exact continuity and the published output duration.
    frame_tolerance = 1.0 / 24.0 + 1e-6
    source_cursor = 0.0
    timeline_cursor = 0.0
    for segment in segments:
        if type(segment) is not dict or set(segment) != {
            "source_start", "source_end", "timeline_start", "timeline_end",
        }:
            raise _fail()
        source_start = _number(segment["source_start"])
        source_end = _number(segment["source_end"])
        timeline_start = _number(segment["timeline_start"])
        timeline_end = _number(segment["timeline_end"])
        if (
            source_start < source_cursor or source_end <= source_start
            or abs(timeline_start - timeline_cursor) > 1e-6
            or timeline_end <= timeline_start
            or abs((source_end - source_start) - (timeline_end - timeline_start)) > frame_tolerance
        ):
            raise _fail()
        source_cursor = source_end
        timeline_cursor = timeline_end
    if abs(timeline_cursor - output_duration) > 1e-6 or source_cursor > source_duration + 1e-6:
        raise _fail()
    return value


def _map_words(
    words: list[dict[str, object]], timeline: dict[str, object]
) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    spoken_intervals: set[int] = set()
    for word in words:
        source_start = float(word["start"])
        source_end = float(word["end"])
        for interval_index, interval in enumerate(timeline["segments"]):
            overlap_start = max(source_start, float(interval["source_start"]))
            overlap_end = min(source_end, float(interval["source_end"]))
            if overlap_end <= overlap_start:
                continue
            text = str(word["text"])
            if (interval_index not in spoken_intervals and text.strip()
                    and all(character in "，,。.!！？?；;、：:" for character in text.strip())):
                # A cut can leave the false start's trailing punctuation before
                # the first retained word. It no longer belongs to this speech.
                continue
            offset = float(interval["timeline_start"]) - float(interval["source_start"])
            mapped.append(
                {
                    "text": word["text"],
                    "start": overlap_start + offset,
                    "end": overlap_end + offset,
                }
            )
            if any(character.isalnum() for character in text):
                spoken_intervals.add(interval_index)
            break
    if not mapped:
        raise _fail()
    return mapped


def _layout_type(segment: dict[str, object]) -> str:
    return {
        "arroll": "emphasis",
        "ai": "statement",
        "official": "source",
        "code": "action",
    }[segment["implementation"]]


def _layout_box(segment: dict[str, object], cue_type: str) -> dict[str, int]:
    zone = segment["safe_zones"]["subtitle"]
    if zone is None:
        raise _fail()
    x, y, width, height = (
        zone["x"], zone["y"], zone["width"], zone["height"]
    )
    variants = {
        "emphasis": (0, 0, 0, 40),
        "statement": (24, 12, 48, 28),
        "source": (0, 24, 120, 32),
        "action": (72, 20, 144, 40),
    }
    dx, dy, dw, dh = variants[cue_type]
    box = {
        "x": x + dx,
        "y": y + dy,
        "width": width - dw,
        "height": height - dh,
    }
    _rect(box, width=1080, height=1920)
    return box


@lru_cache(maxsize=32768)
def _font_text_width(font_path: str, size: int, text: str) -> float:
    font = bold_subtitles._font(font_path, size)
    return float(font.getlength(text))


def _layout_lines_at_size(
    text: str,
    font_path: str,
    size: int,
    max_width: int,
) -> list[str] | None:
    explicit = bold_subtitles._lines(text)
    if len(explicit) == 2:
        if all(
            _font_text_width(font_path, size, line) <= max_width
            for line in explicit
        ):
            return explicit
        return None
    stripped = explicit[0].strip()
    if _font_text_width(font_path, size, stripped) <= max_width:
        return [stripped]
    best: tuple[float, float, list[str]] | None = None
    for index in range(1, len(stripped)):
        left = stripped[:index].rstrip()
        right = stripped[index:].lstrip()
        if not left or not right:
            continue
        widths = (
            _font_text_width(font_path, size, left),
            _font_text_width(font_path, size, right),
        )
        if max(widths) > max_width:
            continue
        candidate = (max(widths), abs(widths[0] - widths[1]), [left, right])
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return None if best is None else best[2]


@lru_cache(maxsize=1024)
def _cached_text_layout(
    text: str,
    font_path: str,
    box_x: int,
    box_y: int,
    box_width: int,
    box_height: int,
    cue_type: str,
) -> tuple[
    tuple[str, ...], int, tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...],
]:
    if cue_type not in _TYPES:
        raise _fail()
    available_height = box_height - 32
    maximum_width = box_width - 48
    low, high = 36, 64
    best: tuple[list[str], int] | None = None
    while low <= high:
        size = (low + high) // 2
        lines = _layout_lines_at_size(text, font_path, size, maximum_width)
        total_height = 0 if lines is None else len(lines) * (size + 10) - 10
        if lines is not None and len(lines) <= 2 and total_height <= available_height:
            best = (lines, size)
            low = size + 1
        else:
            high = size - 1
    if best is None:
        raise bold_subtitles.SubtitleError(
            "subtitle text cannot fit inside the safe area"
        )
    display_lines = [line.strip() for line in best[0]]
    if any(not line for line in display_lines):
        raise bold_subtitles.SubtitleError(
            "subtitle text cannot fit inside the safe area"
        )
    display_spans = []
    cursor = 0
    for line in display_lines:
        start = text.find(line, cursor)
        if start < cursor:
            raise bold_subtitles.SubtitleError(
                "subtitle text cannot fit inside the safe area"
            )
        end = start + len(line)
        display_spans.append((start, end))
        cursor = end
    boundaries = [span[0] for span in display_spans[1:]]
    line_spans = list(zip(
        [0, *boundaries],
        [*boundaries, len(text)],
    ))
    return (
        tuple(display_lines), best[1], tuple(line_spans), tuple(display_spans),
    )


def _layout_text_for_box(
    text: str,
    font_path: Path,
    box: dict[str, int],
    cue_type: str,
) -> dict[str, object]:
    lines, size, line_spans, display_spans = _cached_text_layout(
        text, str(font_path), box["x"], box["y"], box["width"], box["height"],
        cue_type,
    )
    return {
        "lines": list(lines),
        "font_size": size,
        "line_spans": list(line_spans),
        "display_spans": list(display_spans),
    }


def _word_interval_fits(
    words: list[dict[str, object]],
    left: int,
    right: int,
    box: dict[str, int],
    font_path: Path,
    cue_type: str,
    cache: dict[tuple[object, ...], bool],
) -> bool:
    key = (
        left, right, box["x"], box["y"], box["width"], box["height"],
        cue_type, str(font_path),
    )
    if key in cache:
        return cache[key]
    try:
        _layout_text_for_box(
            "".join(str(word["text"]) for word in words[left:right]),
            font_path,
            box,
            cue_type,
        )
    except bold_subtitles.SubtitleError:
        cache[key] = False
    else:
        cache[key] = True
    return cache[key]


def _split_words_for_box(
    words: list[dict[str, object]],
    box: dict[str, int],
    font_path: Path,
    cue_type: str,
    layout_cache: dict[tuple[object, ...], bool] | None = None,
) -> list[list[dict[str, object]]]:
    cache = {} if layout_cache is None else layout_cache
    chunks: list[list[dict[str, object]]] = []
    left = 0
    while left < len(words):
        low, high = left + 1, len(words)
        best = left
        while low <= high:
            right = (low + high) // 2
            if _word_interval_fits(
                words, left, right, box, font_path, cue_type, cache,
            ):
                best = right
                low = right + 1
            else:
                high = right - 1
        if best == left:
            raise _fail()
        chunks.append(words[left:best])
        left = best
    return chunks


def _chunk_times(
    chunk: list[dict[str, object]],
    *,
    segment_start: float,
    segment_end: float,
    duration: float,
) -> tuple[float, float]:
    return (
        round(max(segment_start, float(chunk[0]["start"]), 1 / 24), 3),
        round(
            min(segment_end, float(chunk[-1]["end"]), duration - 1 / 24),
            3,
        ),
    )


def _chunk_has_sample_frame(
    chunk: list[dict[str, object]],
    *,
    segment_start: float,
    segment_end: float,
    duration: float,
) -> bool:
    start, end = _chunk_times(
        chunk,
        segment_start=segment_start,
        segment_end=segment_end,
        duration=duration,
    )
    frames = round(duration * 24)
    sample_index = min(frames - 2, max(1, round(((start + end) / 2) * 24)))
    sample_time = sample_index / 24
    return end > start and start <= sample_time < end


def _protected_word_boundaries(
    words: list[dict[str, object]],
    phrases: list[str],
) -> set[int]:
    text = "".join(str(word["text"]) for word in words)
    word_boundaries = []
    offset = 0
    for index, word in enumerate(words[:-1], 1):
        offset += len(str(word["text"]))
        word_boundaries.append((index, offset))
    protected = set()
    for phrase in phrases:
        occurrence = text.find(phrase)
        while occurrence >= 0:
            end = occurrence + len(phrase)
            protected.update(
                index for index, boundary in word_boundaries
                if occurrence < boundary < end
            )
            occurrence = text.find(phrase, occurrence + 1)
    return protected


def _visible_glyph_count(words: list[dict[str, object]]) -> int:
    return sum(
        not character.isspace()
        for word in words
        for character in str(word["text"])
    )


def _partition_subtitle_words(
    words: list[dict[str, object]],
    chunks: list[list[dict[str, object]]],
    *,
    box: dict[str, int],
    font_path: Path,
    cue_type: str,
    segment_start: float,
    segment_end: float,
    duration: float,
    protected_boundaries: set[int],
    layout_cache: dict[tuple[object, ...], bool],
) -> list[list[dict[str, object]]]:
    def has_sample(chunk: list[dict[str, object]]) -> bool:
        return _chunk_has_sample_frame(
            chunk, segment_start=segment_start, segment_end=segment_end,
            duration=duration,
        )

    original_boundaries = []
    offset = 0
    for chunk in chunks[:-1]:
        offset += len(chunk)
        original_boundaries.append(offset)

    word_count = len(words)
    glyph_prefix = [0]
    for word in words:
        glyph_prefix.append(glyph_prefix[-1] + _visible_glyph_count([word]))
    eligible_ends: list[list[tuple[int, int, bool]]] = [[] for _ in range(word_count)]
    for left in range(word_count):
        for right in range(left + 1, word_count + 1):
            glyph_count = glyph_prefix[right] - glyph_prefix[left]
            if glyph_count > _CUE_TARGET_MAX:
                break
            if _word_interval_fits(
                words, left, right, box, font_path, cue_type, layout_cache,
            ):
                candidate = words[left:right]
                eligible_ends[left].append((
                    right, glyph_count, has_sample(candidate),
                ))
        if not eligible_ends[left]:
            raise _fail()

    nodes: list[tuple[int, int]] = [(0, 0)]
    current: dict[int, tuple[tuple[int, int, int, int], int, int]] = {
        0: ((0, 0, 0, 0), 0, 0),
    }
    solution_score: tuple[int, int, int, int] | None = None
    solution_node = 0
    solution_chunk_count = 0

    def boundaries(node_id: int) -> tuple[int, ...]:
        result = []
        while node_id:
            node_id, end = nodes[node_id]
            result.append(end)
        return tuple(reversed(result))

    for chunk_count in range(1, word_count + 1):
        next_candidates: dict[int, tuple[tuple[int, int, int, int], int, int]] = {}
        for left, (score, node_id, rank) in current.items():
            for right, glyph_count, sample_ok in eligible_ends[left]:
                if right < word_count and right in protected_boundaries:
                    continue
                if not sample_ok:
                    continue
                out_of_range = score[0] + int(
                    glyph_count < _CUE_TARGET_MIN or glyph_count > _CUE_TARGET_MAX
                )
                range_penalty = score[1] + max(0, _CUE_TARGET_MIN - glyph_count) + max(
                    0, glyph_count - _CUE_TARGET_MAX
                )
                center_distance = score[2] + abs(glyph_count - _CUE_TARGET_CENTER)
                boundary_shift = score[3]
                if right < word_count:
                    boundary_index = chunk_count - 1
                    if boundary_index < len(original_boundaries):
                        boundary_shift += abs(
                            right - original_boundaries[boundary_index]
                        )
                    elif original_boundaries:
                        boundary_shift += min(
                            abs(right - original) for original in original_boundaries
                        )
                next_score = (
                    out_of_range,
                    range_penalty,
                    center_distance,
                    boundary_shift,
                )
                if right == word_count:
                    if solution_score is None or next_score < solution_score:
                        solution_score = next_score
                        solution_node = node_id
                        solution_chunk_count = chunk_count
                    elif next_score == solution_score:
                        candidate_solution = (boundaries(node_id), chunk_count)
                        current_solution = (
                            boundaries(solution_node), solution_chunk_count,
                        )
                        if candidate_solution < current_solution:
                            solution_node = node_id
                            solution_chunk_count = chunk_count
                    continue
                current_candidate = next_candidates.get(right)
                if (
                    current_candidate is None
                    or next_score < current_candidate[0]
                    or (next_score == current_candidate[0] and rank < current_candidate[2])
                ):
                    next_candidates[right] = (next_score, node_id, rank)
        current = {}
        for rank, (right, (score, parent, parent_rank)) in enumerate(sorted(
            next_candidates.items(), key=lambda item: (item[1][2], item[0]),
        )):
            nodes.append((parent, right))
            current[right] = (score, len(nodes) - 1, rank)
        if not current:
            break
    if solution_score is None:
        raise _fail()
    solution = boundaries(solution_node)
    cuts = [0, *solution, word_count]
    # Rebalance existing cue boundaries toward audible pauses, without adding
    # cues or treating timing gaps as a Chinese word-segmentation guarantee.
    for index in range(1, len(cuts) - 1):
        left, original, right = cuts[index - 1:index + 2]
        best = None
        for boundary in range(left + 1, right):
            gap_ms = round(1000 * (
                float(words[boundary]["start"])
                - float(words[boundary - 1]["end"])
            ))
            if gap_ms < 200 or boundary in protected_boundaries:
                continue
            counts = (glyph_prefix[boundary] - glyph_prefix[left],
                      glyph_prefix[right] - glyph_prefix[boundary])
            if min(counts) < (_CUE_TARGET_MIN + 1) // 2 or max(counts) > _CUE_TARGET_MAX:
                continue
            if not all(
                _word_interval_fits(words, start, end, box, font_path,
                                    cue_type, layout_cache)
                and has_sample(words[start:end])
                for start, end in ((left, boundary), (boundary, right))
            ):
                continue
            candidate_score = (
                -gap_ms,
                sum(count < _CUE_TARGET_MIN for count in counts),
                sum(max(0, _CUE_TARGET_MIN - count) for count in counts),
                sum(abs(count - _CUE_TARGET_CENTER) for count in counts),
                abs(boundary - original),
                boundary,
            )
            if best is None or candidate_score < best:
                best = candidate_score
        if best is not None:
            cuts[index] = best[-1]
    partition = [
        words[cuts[index]:cuts[index + 1]]
        for index in range(len(cuts) - 1)
    ]
    if not all(
        _word_interval_fits(
            words, cuts[index], cuts[index + 1], box, font_path, cue_type,
            layout_cache,
        ) and has_sample(chunk)
        for index, chunk in enumerate(partition)
    ):
        raise _fail()
    return partition


def _build_plan(
    *,
    records: dict[str, dict[str, object]],
    words: list[dict[str, object]],
    timeline: dict[str, object],
    visual_plan: dict[str, object],
) -> dict[str, object]:
    mapped = _map_words(words, timeline)
    duration = float(visual_plan["duration"])
    cues: list[dict[str, object]] = []
    used_words: set[int] = set()
    font_path = bold_subtitles.find_cjk_font(
        "".join(str(word["text"]) for word in mapped)
    )
    for segment in visual_plan["segments"]:
        segment_start = float(segment["start"])
        segment_end = float(segment["end"])
        indices = [
            index for index, word in enumerate(mapped)
            if index not in used_words
            and segment_start <= (float(word["start"]) + float(word["end"])) / 2 < segment_end
        ]
        if not indices:
            continue
        used_words.update(indices)
        if segment["implementation"] != "arroll":
            continue
        selected = [mapped[index] for index in indices]
        cue_type = _layout_type(segment)
        box = _layout_box(segment, cue_type)
        layout_cache: dict[tuple[object, ...], bool] = {}
        chunks = _split_words_for_box(
            selected, box, font_path, cue_type, layout_cache,
        )
        keywords = [str(keyword["text"]) for keyword in segment["keywords"]]
        selected_text = "".join(str(word["text"]) for word in selected)
        if any(
            keyword
            and keyword in selected_text
            and _visible_glyph_count([{"text": keyword}]) > _CUE_TARGET_MAX
            for keyword in keywords
        ):
            raise _fail()
        protected_boundaries = _protected_word_boundaries(
            selected,
            keywords,
        )
        chunks = _partition_subtitle_words(
            selected,
            chunks,
            box=box,
            font_path=font_path,
            cue_type=cue_type,
            segment_start=segment_start,
            segment_end=segment_end,
            duration=duration,
            protected_boundaries=protected_boundaries,
            layout_cache=layout_cache,
        )
        chunk_details: list[tuple[str, float, float]] = []
        for chunk in chunks:
            text = "".join(str(word["text"]) for word in chunk)
            cue_start, cue_end = _chunk_times(
                chunk,
                segment_start=segment_start,
                segment_end=segment_end,
                duration=duration,
            )
            chunk_details.append((text, cue_start, cue_end))
        emphasis_words = _semantic_emphasis_assignments(
            [text for text, _start, _end in chunk_details], keywords
        )
        for (text, cue_start, cue_end), emphasis_word in zip(
            chunk_details, emphasis_words
        ):
            cues.append(
                {
                    "id": f"cue-{len(cues) + 1:03d}",
                    "type": cue_type,
                    "segment_id": segment["segment_id"],
                    "start": cue_start,
                    "end": cue_end,
                    "text": text,
                    "emphasis_words": [emphasis_word] if emphasis_word else [],
                    "safe_zones": segment["safe_zones"],
                    "box": box,
                }
            )
    if used_words != set(range(len(mapped))):
        raise _fail()
    counts = {name: 0 for name in _TYPES}
    for cue in cues:
        counts[cue["type"]] += 1
    plan = {
        "version": 1,
        "canvas": {
            "width": 1080, "height": 1920, "fps": 24,
            "frames": round(duration * 24), "duration": duration,
        },
        "source_bindings": records,
        "layout_counts": counts,
        "cues": cues,
    }
    return validate_subtitle_plan(plan)


def _srt_time(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _srt_bytes(cues: list[dict[str, object]]) -> bytes:
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{_srt_time(float(cue['start']))} --> {_srt_time(float(cue['end']))}\n{cue['text']}\n"
        )
    if not blocks:
        return b""
    return ("\n".join(blocks) + "\n").encode("utf-8")


def _parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value)
    if match is None:
        raise _fail()
    hours, minutes, seconds, millis = map(int, match.groups())
    if minutes >= 60 or seconds >= 60:
        raise _fail()
    return round(hours * 3600 + minutes * 60 + seconds + millis / 1000, 3)


def parse_srt(source: str) -> list[tuple[float, float, str]]:
    if type(source) is not str or "\r" in source:
        raise _fail()
    if source == "":
        return []
    blocks = source.rstrip("\n").split("\n\n")
    result: list[tuple[float, float, str]] = []
    for index, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if len(lines) != 3 or lines[0] != str(index) or " --> " not in lines[1]:
            raise _fail()
        start, end = lines[1].split(" --> ", 1)
        text = _text(lines[2])
        start_value, end_value = _parse_srt_time(start), _parse_srt_time(end)
        if end_value <= start_value:
            raise _fail()
        result.append((start_value, end_value, text))
    return result


def _contact_sheet(
    descriptor: int, cues: list[dict[str, object]]
) -> bytes:
    images = []
    for cue in cues[:4]:
        frame_index = round(
            ((float(cue["start"]) + float(cue["end"])) / 2) * 24
        )
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-c:v", "libvpx-vp9", "-i", f"/dev/fd/{descriptor}",
                    "-vf", f"select=eq(n\\,{frame_index})", "-vsync", "0",
                    "-frames:v", "1", "-c:v", "png", "-f", "image2pipe", "-",
                ],
                check=True,
                capture_output=True,
                pass_fds=(descriptor,),
                timeout=120,
            )
            image = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
            image.load()
        except (OSError, subprocess.SubprocessError, Image.UnidentifiedImageError):
            raise _fail() from None
        background = Image.new("RGBA", image.size, (32, 48, 64, 255))
        background.alpha_composite(image)
        images.append(background.convert("RGB").resize((270, 480), Image.Resampling.LANCZOS))
    while len(images) < 4:
        images.append(Image.new("RGB", (270, 480), (32, 48, 64)))
    sheet = Image.new("RGB", (1080, 480), (32, 48, 64))
    for index, image in enumerate(images):
        sheet.paste(image, (index * 270, 0))
    output = io.BytesIO()
    sheet.save(output, format="PNG", optimize=False)
    return output.getvalue()


def build_final_overlay_command(
    edited_aroll: Path, subtitles: Path, output: Path
) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
        "-i", str(edited_aroll), "-c:v", "libvpx-vp9", "-i", str(subtitles),
        "-filter_complex", "[0:v][1:v]overlay[vout]",
        "-map", "[vout]", "-map", "0:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", str(output),
    ]


def _validate_manifest(
    manifest: object,
    *,
    directory: Path,
    workflow_records: dict[str, tuple[dict[str, object], _PinnedFile]],
    visual_plan_record: dict[str, object],
    expected_inputs: dict[str, object],
    expected_canvas: dict[str, object],
    expected_duration: float,
    expected_routing_summary: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    if type(manifest) is not dict or set(manifest) != _MANIFEST_KEYS:
        raise _fail()
    if type(manifest["version"]) is not int or manifest["version"] != 1:
        raise _fail()
    if type(manifest["generation_id"]) is not str or _SHA256.fullmatch(manifest["generation_id"]) is None:
        raise _fail()
    if (
        manifest["visual_plan"] != visual_plan_record
        or manifest["inputs"] != expected_inputs
    ):
        raise _fail()
    canvas = manifest["canvas"]
    duration = _number(manifest["duration"], positive=True)
    manifest_canvas = {
        "width": expected_canvas["width"],
        "height": expected_canvas["height"],
        "fps": float(expected_canvas["fps"]),
    }
    expected_frames = round(expected_duration * 24)
    if (
        canvas != manifest_canvas
        or duration != expected_duration
        or manifest["frames"] != expected_frames
        or manifest["routing_summary"] != expected_routing_summary
        or type(manifest["frames"]) is not int
        or manifest["frames"] != round(duration * 24)
        or type(manifest["ai_attempts"]) is not int
        or manifest["ai_attempts"] < 0
        or type(manifest["assets"]) is not list
    ):
        raise _fail()
    assets: dict[str, dict[str, object]] = {}
    for asset in manifest["assets"]:
        if type(asset) is not dict or set(asset) != _ASSET_KEYS:
            raise _fail()
        checked = _record({key: asset[key] for key in _FILE_KEYS})
        relative = _safe_relative(checked["path"])
        if relative.name in assets or checked["path"] in assets:
            raise _fail()
        assets[checked["path"]] = asset
    expected = {"asset-manifest.json", *assets}
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise _fail()
    if set(workflow_records) != expected:
        raise _fail()
    visual_tracks = [asset for asset in assets.values() if asset["type"] == "visual-track"]
    if (
        len(visual_tracks) != 1
        or visual_tracks[0]["path"] != "visual-track.mp4"
        or type(visual_tracks[0]["frames"]) is not int
        or visual_tracks[0]["frames"] != expected_frames
    ):
        raise _fail()
    return manifest, visual_tracks[0]


def _write_new(path: Path, source: bytes) -> None:
    descriptor = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(source)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise _fail()
            view = view[count:]
        os.fsync(descriptor)
    except BaseException:
        raise _fail() from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _snapshot(directory: Path) -> list[dict[str, object]]:
    actual = {path.name for path in directory.iterdir()}
    if actual != _OUTPUT_NAMES:
        raise _fail()
    records = []
    for name in sorted(actual):
        path = directory / name
        status = os.lstat(path)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise _fail()
        source = path.read_bytes()
        records.append(
            {
                "path": f"06-subtitles/{name}",
                "sha256": hashlib.sha256(source).hexdigest(),
                "bytes": len(source),
            }
        )
    return records


def _verify_alpha_frame(
    descriptor: int,
    frame_index: int,
    cue: dict[str, object] | None,
) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        "-c:v", "libvpx-vp9", "-i", f"/dev/fd/{descriptor}",
        "-vf", f"select=eq(n\\,{frame_index}),format=rgba,alphaextract",
        "-vsync", "0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            pass_fds=(descriptor,),
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        raise _fail() from None
    _check_alpha_mask(result.stdout, cue)


def _check_alpha_mask(raw: bytes, cue: dict[str, object] | None) -> None:
    if len(raw) != 1080 * 1920:
        raise _fail()
    mask = Image.frombytes("L", (1080, 1920), raw).point(
        lambda value: 255 if value >= 128 else 0
    )
    bbox = mask.getbbox()
    if cue is None:
        if bbox is not None:
            raise _fail()
        return
    if bbox is None:
        raise _fail()
    box = cue["box"]
    if not (
        box["x"] - 2 <= bbox[0] <= bbox[2] <= box["x"] + box["width"] + 2
        and box["y"] - 2 <= bbox[1] <= bbox[3] <= box["y"] + box["height"] + 2
    ):
        raise _fail()
    for name in ("face", "source", "chart"):
        zone = cue["safe_zones"][name]
        if zone is not None and mask.crop(
            (zone["x"], zone["y"], zone["x"] + zone["width"], zone["y"] + zone["height"])
        ).getbbox() is not None:
            raise _fail()
    if mask.crop((0, 1800, 1080, 1920)).getbbox() is not None:
        raise _fail()


def _verify_alpha_frames(
    descriptor: int, samples: list[tuple[int, dict[str, object] | None]],
) -> None:
    """Decode selected subtitle frames in bounded passes, preserving every alpha check."""
    if not samples:
        return
    ordered = sorted(samples, key=lambda item: item[0])
    if any(frame < 0 or (index and frame == ordered[index - 1][0])
           for index, (frame, _) in enumerate(ordered)):
        raise _fail()
    for start in range(0, len(ordered), 100):
        _verify_alpha_frame_batch(descriptor, ordered[start:start + 100])


def _verify_alpha_frame_batch(
    descriptor: int, ordered: list[tuple[int, dict[str, object] | None]],
) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    selection = "+".join(f"eq(n\\,{frame})" for frame, _ in ordered)
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        "-c:v", "libvpx-vp9", "-i", f"/dev/fd/{descriptor}",
        "-vf", f"select={selection},format=rgba,alphaextract",
        "-vsync", "0", "-frames:v", str(len(ordered)),
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            pass_fds=(descriptor,),
        )
    except OSError:
        raise _fail() from None
    deadline = time.monotonic() + 300
    try:
        assert process.stdout is not None
        for _, cue in ordered:
            raw = bytearray()
            while len(raw) < 1080 * 1920:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select(
                    [process.stdout], [], [], remaining,
                )[0]:
                    raise _fail()
                chunk = os.read(process.stdout.fileno(), 1080 * 1920 - len(raw))
                if not chunk:
                    raise _fail()
                raw.extend(chunk)
            _check_alpha_mask(bytes(raw), cue)
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise _fail()
        if os.read(process.stdout.fileno(), 1):
            raise _fail()
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _verify_rendered_geometry(
    descriptor: int, cues: list[dict[str, object]], frames: int
) -> None:
    _verify_alpha_frame(descriptor, 0, None)
    _verify_alpha_frame(descriptor, frames - 1, None)
    for cue in cues:
        index = round(((float(cue["start"]) + float(cue["end"])) / 2) * 24)
        _verify_alpha_frame(descriptor, min(frames - 2, max(1, index)), cue)


def _encode_transparent_webm_fd(descriptor: int, frames: int) -> None:
    if (
        type(descriptor) is not int
        or descriptor < 0
        or type(frames) is not int
        or frames <= 0
    ):
        raise _fail()
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-y",
        "-fflags", "+bitexact", "-f", "lavfi", "-i",
        "color=c=black@0.0:s=1080x1920:r=24,format=rgba", "-an",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
        "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1",
        "-lossless", "1", "-flags:v", "+bitexact", "-bitexact",
        "-map_metadata", "-1", "-metadata", "creation_time=1970-01-01T00:00:00Z",
        "-write_crc32", "0", "-frames:v", str(frames),
        "-f", "webm", f"pipe:{descriptor}",
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=(descriptor,),
            timeout=120,
        )
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except (OSError, subprocess.SubprocessError):
        raise _fail() from None


def _validate_transparent_webm_fd(descriptor: int, frames: int) -> None:
    status = os.fstat(descriptor)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
        or status.st_size <= 0
    ):
        raise _fail()
    source = f"/dev/fd/{descriptor}"
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-count_frames", "-show_entries",
                "stream=codec_name,codec_type,width,height,r_frame_rate,nb_read_frames:stream_tags=alpha_mode",
                "-of", "json", source,
            ],
            check=True,
            capture_output=True,
            text=True,
            pass_fds=(descriptor,),
            timeout=120,
        )
        alpha = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-c:v", "libvpx-vp9", "-i", source, "-map", "0:v:0",
                "-vf", "format=rgba,alphaextract,signalstats,metadata=print:file=-",
                "-f", "null", "-",
            ],
            check=True,
            capture_output=True,
            text=True,
            pass_fds=(descriptor,),
            timeout=120,
        )
        streams = json.loads(probe.stdout)["streams"]
        maxima = [
            float(line.split("=", 1)[1])
            for line in alpha.stdout.splitlines()
            if line.startswith("lavfi.signalstats.YMAX=")
        ]
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise _fail() from None
    expected = {
        "codec_name": "vp9",
        "codec_type": "video",
        "width": 1080,
        "height": 1920,
        "r_frame_rate": "24/1",
        "nb_read_frames": str(frames),
        "tags": {"alpha_mode": "1"},
    }
    if streams != [expected] or len(maxima) != frames or any(maxima):
        raise _fail()
    os.lseek(descriptor, 0, os.SEEK_SET)


def _acquire_lock(job_dir: Path) -> tuple[int, os.stat_result]:
    path = job_dir / _LOCK_NAME
    if not os.path.lexists(path):
        try:
            _write_new(path, _LOCK_BYTES)
            _fsync_directory(job_dir)
        except SubtitleError:
            if not os.path.lexists(path):
                raise
    _reject_symlinks(path)
    try:
        descriptor = os.open(
            path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        status = os.fstat(descriptor)
        visible = os.lstat(path)
        source = os.pread(descriptor, len(_LOCK_BYTES) + 1, 0)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or not os.path.samestat(status, visible) or source != _LOCK_BYTES
        ):
            raise _fail()
        return descriptor, status
    except BaseException:
        if "descriptor" in locals():
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _fail() from None


def _verify_lock(job_dir: Path, descriptor: int, expected: os.stat_result) -> None:
    try:
        current = os.fstat(descriptor)
        visible = os.lstat(job_dir / _LOCK_NAME)
    except OSError:
        raise _fail() from None
    if (
        current.st_nlink != 1 or visible.st_nlink != 1
        or not os.path.samestat(current, expected)
        or not os.path.samestat(current, visible)
        or os.pread(descriptor, len(_LOCK_BYTES) + 1, 0) != _LOCK_BYTES
    ):
        raise _fail()


def _atomic_rename(source: Path, destination: Path, *, exchange: bool) -> bool:
    if source.parent != destination.parent:
        raise _fail()
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if hasattr(library, "renameatx_np"):
        operation = library.renameatx_np
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        flags = 0x00000002 if exchange else 0x00000004
        result = operation(-2, source_bytes, -2, destination_bytes, flags)
    elif hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        flags = 0x2 if exchange else 0x1
        result = operation(-100, source_bytes, -100, destination_bytes, flags)
    else:
        raise _fail()
    if result == 0:
        return True
    error = ctypes.get_errno()
    if not exchange and error in {errno.EEXIST, errno.ENOTEMPTY}:
        return False
    raise _fail()


def _records_match(directory: Path, records: object) -> bool:
    try:
        if type(records) is not list:
            return False
        expected = {Path(record["path"]).name: record for record in records}
        if set(expected) != _OUTPUT_NAMES or not directory.is_dir():
            return False
        if {path.name for path in directory.iterdir()} != _OUTPUT_NAMES:
            return False
        for name, record in expected.items():
            checked = _record(record)
            path = directory / name
            status = os.lstat(path)
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                return False
            source = path.read_bytes()
            if (
                hashlib.sha256(source).hexdigest() != checked["sha256"]
                or len(source) != checked["bytes"]
            ):
                return False
        return True
    except (OSError, SubtitleError, TypeError, KeyError):
        return False


def _old_generation_matches(job: state.JobState, target: Path) -> bool:
    lineage = job.stages["subtitles"].get("lineage")
    if type(lineage) is not list or len(lineage) != len(_OUTPUT_NAMES):
        return False
    try:
        parent = os.lstat(target)
        expected = {Path(record["path"]).name: record for record in lineage}
        if set(expected) != _OUTPUT_NAMES or {path.name for path in target.iterdir()} != _OUTPUT_NAMES:
            return False
        for name, record in expected.items():
            path = target / name
            status = os.lstat(path)
            source = path.read_bytes()
            if (
                status.st_dev != record["device"] or status.st_ino != record["inode"]
                or parent.st_dev != record["parent_device"]
                or parent.st_ino != record["parent_inode"]
                or len(source) != record["bytes"]
                or hashlib.sha256(source).hexdigest() != record["sha256"]
            ):
                return False
        return True
    except (OSError, KeyError, TypeError):
        return False


def _artifact_records_match(job: state.JobState, records: list[dict[str, object]]) -> bool:
    artifacts = job.stages["subtitles"].get("artifacts")
    return type(artifacts) is list and artifacts == records


def _write_transaction(job: state.JobState, payload: dict[str, object]) -> None:
    marker = job.job_dir / _TRANSACTION_NAME
    if os.path.lexists(marker):
        raise _fail()
    _write_new(marker, _canonical_json(payload))
    _fsync_directory(job.job_dir)


def _load_transaction(job: state.JobState) -> dict[str, object] | None:
    marker = job.job_dir / _TRANSACTION_NAME
    if not os.path.lexists(marker):
        return None
    pin = _pin(
        marker,
        {
            "path": _TRANSACTION_NAME,
            "sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
            "bytes": len(marker.read_bytes()),
        },
    )
    try:
        payload = _strict_json(_descriptor_bytes(pin, 1024 * 1024))
    finally:
        pin.close()
    keys = {
        "version", "job_id", "base_revision", "workflow_sha256",
        "workflow_bytes", "had_target", "stage", "target", "new_records",
    }
    if (
        type(payload) is not dict or set(payload) != keys
        or payload["version"] != 1 or type(payload["version"]) is not int
        or payload["job_id"] != job.job_id
        or type(payload["base_revision"]) is not int
        or type(payload["workflow_sha256"]) is not str
        or _SHA256.fullmatch(payload["workflow_sha256"]) is None
        or type(payload["workflow_bytes"]) is not int
        or type(payload["had_target"]) is not bool
        or payload["target"] != "06-subtitles"
        or type(payload["stage"]) is not str
        or not payload["stage"].startswith(".06-subtitles.stage-")
        or "/" in payload["stage"] or "\\" in payload["stage"]
        or type(payload["new_records"]) is not list
    ):
        raise _fail()
    return payload


def _retire_known(path: Path, job_dir: Path) -> None:
    if not os.path.lexists(path):
        return
    destination = job_dir / f".06-subtitles.retained-{secrets.token_hex(16)}"
    if not _atomic_rename(path, destination, exchange=False):
        raise _fail()
    _fsync_directory(job_dir)


def _synchronize_job(target: state.JobState, source: state.JobState) -> None:
    target.root = source.root
    target.job_dir = source.job_dir
    target.job_id = source.job_id
    target.inputs = source.inputs
    target.revision = source.revision
    target.stages = source.stages
    target.expected_revision = source.expected_revision
    target.expected_sha256 = source.expected_sha256
    target.expected_bytes = source.expected_bytes


def _finish_transaction(
    job: state.JobState,
    payload: dict[str, object],
    lock_descriptor: int,
    lock_status: os.stat_result,
) -> Path | None:
    _verify_lock(job.job_dir, lock_descriptor, lock_status)
    target = job.job_dir / "06-subtitles"
    stage_path = job.job_dir / payload["stage"]
    records = payload["new_records"]
    current = state.load_job(job.job_dir)
    _synchronize_job(job, current)
    status = job.stages["subtitles"]["status"]
    if status in {"ready_for_review", "approved"}:
        if not _artifact_records_match(job, records) or not _records_match(target, records):
            raise _fail()
        if os.path.lexists(stage_path):
            _retire_known(stage_path, job.job_dir)
        _retire_known(job.job_dir / _TRANSACTION_NAME, job.job_dir)
        return target / "subtitles.webm"
    if status not in {"pending", "needs_revision"}:
        raise _fail()
    base_matches = (
        job.revision == payload["base_revision"]
        and job.expected_sha256 == payload["workflow_sha256"]
        and job.expected_bytes == payload["workflow_bytes"]
    )
    if not base_matches:
        target_is_old = bool(payload["had_target"]) and _old_generation_matches(job, target)
        target_is_absent = not payload["had_target"] and not os.path.lexists(target)
        if (
            not _records_match(stage_path, records)
            or not (target_is_old or target_is_absent)
        ):
            raise _fail()
        _retire_known(job.job_dir / _TRANSACTION_NAME, job.job_dir)
        _retire_known(stage_path, job.job_dir)
        return None
    output_pins: list[_PinnedFile] = []
    try:
        target_is_old = bool(payload["had_target"]) and _old_generation_matches(job, target)
        target_is_new = _records_match(target, records) and not target_is_old
        if not target_is_new:
            if not _records_match(stage_path, records):
                raise _fail()
            if payload["had_target"]:
                if not _old_generation_matches(job, target):
                    raise _fail()
                if not _atomic_rename(stage_path, target, exchange=True):
                    raise _fail()
            else:
                if os.path.lexists(target) or not _atomic_rename(
                    stage_path, target, exchange=False
                ):
                    raise _fail()
            _fsync_directory(job.job_dir)
            target_is_new = True
        if not target_is_new or not _records_match(target, records):
            raise _fail()
        for record in records:
            output_pins.append(
                _pin(target / Path(record["path"]).name, record)
            )
        _checkpoint("after-install")
        _verify_lock(job.job_dir, lock_descriptor, lock_status)
        state.mark_ready(
            job,
            "subtitles",
            [target / Path(record["path"]).name for record in records],
        )
        for pin in output_pins:
            _verify_pin(pin)
        if not _records_match(target, records) or not _artifact_records_match(job, records):
            raise _fail()
    except BaseException as failure:
        committed = (
            job.stages["subtitles"]["status"] in {"ready_for_review", "approved"}
            and _artifact_records_match(job, records)
            and _records_match(target, records)
        )
        if not committed and _records_match(target, records):
            restored = False
            if payload["had_target"] and _old_generation_matches(job, stage_path):
                restored = _atomic_rename(stage_path, target, exchange=True)
            elif not payload["had_target"] and not os.path.lexists(stage_path):
                restored = _atomic_rename(target, stage_path, exchange=False)
            if not restored:
                raise _fail() from failure
            _fsync_directory(job.job_dir)
            _retire_known(job.job_dir / _TRANSACTION_NAME, job.job_dir)
        elif job.stages["subtitles"]["status"] in {"ready_for_review", "approved"}:
            state.revise(job, "subtitles", "subtitle output identity changed")
        raise
    finally:
        for pin in output_pins:
            try:
                pin.close()
            except OSError:
                pass
    _checkpoint("after-workflow")
    if os.path.lexists(stage_path):
        _retire_known(stage_path, job.job_dir)
    _retire_known(job.job_dir / _TRANSACTION_NAME, job.job_dir)
    return target / "subtitles.webm"


def _publish_generation(
    job: state.JobState,
    stage: Path,
    records: list[dict[str, object]],
    lock_descriptor: int,
    lock_status: os.stat_result,
) -> Path:
    target = job.job_dir / "06-subtitles"
    had_target = os.path.lexists(target)
    if had_target and not _old_generation_matches(job, target):
        raise _fail()
    if job.expected_sha256 is None or job.expected_bytes is None:
        raise _fail()
    payload = {
        "version": 1,
        "job_id": job.job_id,
        "base_revision": job.revision,
        "workflow_sha256": job.expected_sha256,
        "workflow_bytes": job.expected_bytes,
        "had_target": had_target,
        "stage": stage.name,
        "target": target.name,
        "new_records": records,
    }
    _write_transaction(job, payload)
    _checkpoint("prepared")
    return _finish_transaction(job, payload, lock_descriptor, lock_status)


def prepare_subtitles(job: state.JobState) -> Path:
    """Build one complete offline subtitle generation and stop for review."""
    if job.version == 2:
        from . import subtitles_v2

        return subtitles_v2.prepare_subtitles_v2(job)
    pins: list[_PinnedFile] = []
    stage: Path | None = None
    generation_records: list[dict[str, object]] | None = None
    lock_descriptor: int | None = None
    lock_status: os.stat_result | None = None
    try:
        lock_descriptor, lock_status = _acquire_lock(job.job_dir)
        pending = _load_transaction(job)
        if pending is not None:
            recovered = _finish_transaction(
                job, pending, lock_descriptor, lock_status
            )
            if recovered is not None:
                return recovered
        state.require_runnable(job, "subtitles")
        speech = _stage_records(
            job, "speech_cleanup", "02-speech-cleanup"
        )
        pins.extend(pin for _record_value, pin in speech.values())
        edits = _stage_records(
            job,
            "edit_structure",
            "03-edit-structure",
            {"edit-plan.json", "edited-aroll.mp4", "timeline-map.json"},
        )
        pins.extend(pin for _record_value, pin in edits.values())
        direction = _stage_records(
            job,
            "visual_direction",
            "04-visual-direction",
            {"visual-plan.json", "storyboard.svg", "visual-routing.md"},
        )
        pins.extend(pin for _record_value, pin in direction.values())
        assets = _stage_records(job, "visual_assets", "05-visual-assets")
        pins.extend(pin for _record_value, pin in assets.values())
        if (
            "word-transcript.json" not in speech
            or "asset-manifest.json" not in assets
            or "visual-track.mp4" not in assets
        ):
            raise _fail()
        words = _validate_words(_strict_json(_descriptor_bytes(speech["word-transcript.json"][1])))
        timeline = _validate_timeline(
            _strict_json(_descriptor_bytes(edits["timeline-map.json"][1])),
            workflow_version=job.version,
        )
        visual_payload = visual_plan_module.validate_visual_plan(
            _strict_json(_descriptor_bytes(direction["visual-plan.json"][1]))
        )
        if (
            visual_payload["canvas"] != {"width": 1080, "height": 1920, "fps": 24.0}
            or float(visual_payload["duration"])
            != round(float(timeline["output_duration"]) * 24) / 24
        ):
            raise _fail()
        manifest, track_asset = _validate_manifest(
            _strict_json(_descriptor_bytes(assets["asset-manifest.json"][1])),
            directory=job.job_dir / "05-visual-assets",
            workflow_records=assets,
            visual_plan_record=direction["visual-plan.json"][0],
            expected_inputs=visual_payload["source_bindings"],
            expected_canvas=visual_payload["canvas"],
            expected_duration=float(visual_payload["duration"]),
            expected_routing_summary=visual_payload["routing_summary"],
        )
        track_record = {
            key: track_asset[key] for key in _FILE_KEYS
        }
        if track_record != {
            **assets["visual-track.mp4"][0],
            "path": "visual-track.mp4",
        }:
            raise _fail()
        records = {
            "word_transcript": speech["word-transcript.json"][0],
            "timeline_map": edits["timeline-map.json"][0],
            "edited_aroll": edits["edited-aroll.mp4"][0],
            "visual_plan": direction["visual-plan.json"][0],
            "asset_manifest": assets["asset-manifest.json"][0],
            "visual_track": assets["visual-track.mp4"][0],
        }
        plan = _build_plan(
            records=records,
            words=words,
            timeline=timeline,
            visual_plan=visual_payload,
        )
        stage = job.job_dir / f".06-subtitles.stage-{secrets.token_hex(16)}"
        stage.mkdir(mode=0o700)
        _write_new(stage / "subtitle-plan.json", _canonical_json(plan))
        webm = stage / "subtitles.webm"
        descriptor = os.open(
            webm,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if plan["cues"]:
                bold_subtitles.encode_webm(
                    plan["cues"],
                    descriptor,
                    float(plan["canvas"]["duration"]),
                    frame_renderer=render_subtitle_frame,
                )
                bold_subtitles.validate_webm_fd(
                    descriptor, plan["canvas"]["frames"]
                )
            else:
                _encode_transparent_webm_fd(
                    descriptor, plan["canvas"]["frames"]
                )
                _validate_transparent_webm_fd(
                    descriptor, plan["canvas"]["frames"]
                )
            _verify_rendered_geometry(descriptor, plan["cues"], plan["canvas"]["frames"])
            contact_source = _contact_sheet(descriptor, plan["cues"])
        finally:
            os.close(descriptor)
        srt_source = _srt_bytes(plan["cues"])
        _write_new(stage / "subtitles.srt", srt_source)
        if parse_srt(srt_source.decode("utf-8")) != [
            (cue["start"], cue["end"], cue["text"]) for cue in plan["cues"]
        ]:
            raise _fail()
        _write_new(stage / "contact-sheet.png", contact_source)
        _fsync_directory(stage)
        generation_records = _snapshot(stage)
        for pin in pins:
            _verify_pin(pin)
        _verify_lock(job.job_dir, lock_descriptor, lock_status)
        output = _publish_generation(
            job, stage, generation_records, lock_descriptor, lock_status
        )
        stage = None
        return output
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail() from None
    finally:
        for pin in pins:
            try:
                pin.close()
            except OSError:
                pass
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_descriptor)
            except OSError:
                pass
        if (
            stage is not None
            and stage.exists()
            and not os.path.lexists(job.job_dir / _TRANSACTION_NAME)
        ):
            try:
                os.rename(
                    stage,
                    job.job_dir / f".06-subtitles.retained-{secrets.token_hex(16)}",
                )
                _fsync_directory(job.job_dir)
            except OSError:
                pass

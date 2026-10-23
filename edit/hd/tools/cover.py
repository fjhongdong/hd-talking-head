"""Strict gbro-cover-design rendering primitives for the HD workflow."""

from __future__ import annotations

import copy
import base64
import ctypes
import errno
import fcntl
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from edit.v5.tools import openlux_images
from edit.hd.tools import material_usage, state

__all__ = [
    "CoverError",
    "validate_cover_brief",
    "select_face_frame",
    "render_cover_base",
    "render_local_text",
    "prepare_cover",
]


class CoverError(RuntimeError):
    """A sanitized cover-stage failure."""


_BRIEF_KEYS = {
    "version", "generator", "title", "style_id", "face_frame", "rounds",
    "subtitle", "base_generation", "base_prompt", "person_composite", "text_layer",
}
_HEADLINE_KEYS = {"primary", "highlight", "conclusion"}
_REFERENCE_SCENE_KEYS = {"sha256", "bytes"}
_AROLL_FACE_KEYS = {"source", "timestamp", "sha256"}
_USER_FACE_KEYS = {"source", "material_id", "sha256"}
_ROUND_KEYS = {"style_and_title", "references", "visual_details"}
_STYLE_KEYS = {"selection", "title", "reason"}
_REFERENCE_KEYS = {"face_source", "extras"}
_DETAIL_KEYS = {
    "person_side", "person_width_ratio", "blank_width_ratio", "expression",
    "background", "font_style", "font_color", "safe_margin_ratio",
}
_TEXT_KEYS = {"engine", "side", "font_style", "color", "safe_margin_ratio"}
_PERSON_KEYS = {"source", "method", "side", "person_width_ratio"}
_SHA = re.compile(r"[0-9a-f]{64}")
_STYLE = re.compile(r"style-(?:0[1-9]|10)")
_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path(__file__).resolve().parents[3] / "skill-development/vendor/adu-motion-video/assets/fonts/NotoSansSC.ttf",
)
_ASPECT_OUTPUTS = {
    "16:9": ("cover-16x9.png", (1920, 1080)),
    "9:16": ("cover-9x16.png", (1080, 1920)),
    "3:4": ("cover-3x4.png", (1080, 1440)),
    "1:1": ("cover-1x1.png", (1080, 1080)),
}
_FALLBACK_REASON = 'alternative: "aroll-code-cover"'
_LOCK_NAME = ".07-cover.lock"
_LOCK_BYTES = b"HD-COVER-LOCK-v1\n"
_CLAIM_PREFIX = ".07-cover-attempt-"
_TRANSACTION_NAME = ".07-cover.transaction.json"
_AI_MARKER_NAME = ".07-cover.ai.json"


def _fail() -> CoverError:
    return CoverError("cover stage failed validation")


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _write_new(path: Path, source: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(source)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short write")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _strict_json(source: bytes) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    return json.loads(
        source.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


def _read_file(path: Path, limit: int = 128 * 1024 * 1024) -> bytes:
    status = os.lstat(path)
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_size > limit:
        raise _fail()
    source = path.read_bytes()
    if len(source) != status.st_size:
        raise _fail()
    return source


def _pinned_read(
    path: Path, limit: int = 128 * 1024 * 1024,
) -> tuple[bytes, os.stat_result, os.stat_result]:
    parent_descriptor = os.open(
        path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        parent_status = os.fstat(parent_descriptor)
        visible_parent = os.lstat(path.parent)
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or not os.path.samestat(parent_status, visible_parent)
        ):
            raise _fail()
        descriptor = os.open(
            path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or status.st_size < 0 or status.st_size > limit
        ):
            raise _fail()
        chunks = []
        offset = 0
        while offset < status.st_size:
            chunk = os.pread(descriptor, min(1024 * 1024, status.st_size - offset), offset)
            if not chunk:
                raise _fail()
            chunks.append(chunk)
            offset += len(chunk)
        source = b"".join(chunks)
        final_status = os.fstat(descriptor)
        visible = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        final_parent = os.fstat(parent_descriptor)
        if (
            not os.path.samestat(status, final_status)
            or not os.path.samestat(status, visible)
            or not os.path.samestat(parent_status, final_parent)
            or len(source) != status.st_size
        ):
            raise _fail()
        return source, status, parent_status
    except CoverError:
        raise
    except OSError:
        raise _fail() from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(parent_descriptor)
        except OSError:
            pass


def _identity(path: Path, expected: dict[str, object]) -> dict[str, object]:
    expected_sha256 = expected.get("sha256")
    expected_bytes = expected.get("bytes")
    if (
        type(expected_sha256) is not str or _SHA.fullmatch(expected_sha256) is None
        or type(expected_bytes) is not int or expected_bytes < 0
    ):
        raise _fail()
    parent_descriptor = os.open(
        path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        parent = os.fstat(parent_descriptor)
        visible_parent = os.lstat(path.parent)
        if not stat.S_ISDIR(parent.st_mode) or not os.path.samestat(parent, visible_parent):
            raise _fail()
        descriptor = os.open(
            path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or status.st_size != expected_bytes
        ):
            raise _fail()
        digest = hashlib.sha256()
        offset = 0
        while offset < status.st_size:
            chunk = os.pread(descriptor, min(1024 * 1024, status.st_size - offset), offset)
            if not chunk:
                raise _fail()
            digest.update(chunk)
            offset += len(chunk)
        final_status = os.fstat(descriptor)
        visible = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        final_parent = os.fstat(parent_descriptor)
        if (
            digest.hexdigest() != expected_sha256
            or not os.path.samestat(status, final_status)
            or not os.path.samestat(status, visible)
            or not os.path.samestat(parent, final_parent)
        ):
            raise _fail()
        return {
            "path": expected["path"],
            "sha256": expected_sha256,
            "bytes": expected_bytes,
            "device": status.st_dev,
            "inode": status.st_ino,
            "parent_device": parent.st_dev,
            "parent_inode": parent.st_ino,
        }
    except CoverError:
        raise
    except OSError:
        raise _fail() from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(parent_descriptor)
        except OSError:
            pass


def _artifact(
    job: state.JobState, stage_id: str, directory: str, name: str,
) -> tuple[Path, dict[str, object]]:
    stage_record = job.stages.get(stage_id)
    if type(stage_record) is not dict or stage_record.get("status") != "approved":
        raise _fail()
    matches = []
    for record in stage_record.get("artifacts", []):
        if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
            raise _fail()
        if record["path"] == f"{directory}/{name}":
            matches.append(record)
    if len(matches) != 1:
        raise _fail()
    path = job.job_dir / directory / name
    return path, _identity(path, matches[0])


def _source_bindings(job: state.JobState) -> dict[str, dict[str, object]]:
    inputs = {}
    for name in ("video", "script"):
        record = job.inputs.get(name)
        if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
            raise _fail()
        inputs[name] = _identity(job.root / record["path"], record)
    artifact_bindings = (
        {
            "content_analysis": (
                "content_analysis", "02-content-analysis", "content-analysis.json"
            ),
            "cover_direction": (
                "cover_direction", "03-cover-direction", "cover-direction.json"
            ),
            "person_reference": (
                "cover_direction", "03-cover-direction", "person-reference.png"
            ),
        }
        if job.version == 2
        else {
            "visual_plan": (
                "visual_direction", "04-visual-direction", "visual-plan.json"
            ),
            "asset_manifest": (
                "visual_assets", "05-visual-assets", "asset-manifest.json"
            ),
            "subtitle_plan": (
                "subtitles", "06-subtitles", "subtitle-plan.json"
            ),
            "subtitles_webm": ("subtitles", "06-subtitles", "subtitles.webm"),
        }
    )
    for key, arguments in artifact_bindings.items():
        _path, inputs[key] = _artifact(job, *arguments)
    return inputs


def _cover_directory_name(job: state.JobState) -> str:
    return "04-cover" if job.version == 2 else "07-cover"


def _reference_scene_source(
    job: state.JobState,
    path: Path | None,
    expected: dict[str, object],
) -> tuple[bytes, dict[str, object]]:
    if not isinstance(path, Path):
        raise _fail()
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(job.root.absolute()).as_posix()
    except ValueError:
        raise _fail() from None
    source, status, parent = _pinned_read(
        absolute, openlux_images.MAX_IMAGE_BYTES
    )
    if (
        hashlib.sha256(source).hexdigest() != expected["sha256"]
        or len(source) != expected["bytes"]
    ):
        raise _fail()
    return source, {
        "path": relative,
        "sha256": expected["sha256"],
        "bytes": expected["bytes"],
        "device": status.st_dev,
        "inode": status.st_ino,
        "parent_device": parent.st_dev,
        "parent_inode": parent.st_ino,
    }


def _approved_png_source(
    job: state.JobState,
    path: Path | None,
    *,
    expected_sha256: str | None = None,
    expected_size: tuple[int, int] | None = None,
) -> tuple[bytes, dict[str, object]]:
    if not isinstance(path, Path) or (
        expected_sha256 is not None and _SHA.fullmatch(expected_sha256) is None
    ):
        raise _fail()
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(job.root.absolute()).as_posix()
    except ValueError:
        raise _fail() from None
    source, status, parent = _pinned_read(
        absolute, openlux_images.MAX_IMAGE_BYTES
    )
    digest = hashlib.sha256(source).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise _fail()
    try:
        with Image.open(io.BytesIO(source)) as image:
            if image.format != "PNG" or image.mode != "RGB" or (
                expected_size is not None and image.size != expected_size
            ):
                raise _fail()
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise _fail() from None
    return source, {
        "path": relative,
        "sha256": digest,
        "bytes": len(source),
        "device": status.st_dev,
        "inode": status.st_ino,
        "parent_device": parent.st_dev,
        "parent_inode": parent.st_ino,
    }


def _workflow_binding(job: state.JobState) -> dict[str, object]:
    path = job.job_dir / "workflow.json"
    source, status, _parent = _pinned_read(path, 8 * 1024 * 1024)
    if (
        job.expected_sha256 != hashlib.sha256(source).hexdigest()
        or job.expected_bytes != len(source)
    ):
        raise _fail()
    return {
        "revision": job.revision,
        "sha256": hashlib.sha256(source).hexdigest(),
        "bytes": len(source),
        "device": status.st_dev,
        "inode": status.st_ino,
    }


def _verify_bindings(
    job: state.JobState,
    workflow: dict[str, object],
    bindings: dict[str, dict[str, object]],
) -> None:
    refreshed = state.load_job(job.job_dir)
    if (
        refreshed.revision != workflow["revision"]
        or refreshed.expected_sha256 != workflow["sha256"]
        or refreshed.expected_bytes != workflow["bytes"]
    ):
        raise _fail()
    current = _source_bindings(refreshed)
    if current != bindings:
        raise _fail()


def _acquire_lock(job_dir: Path) -> int:
    path = job_dir / _LOCK_NAME
    if not os.path.lexists(path):
        try:
            _write_new(path, _LOCK_BYTES)
            _fsync_directory(job_dir)
        except FileExistsError:
            pass
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        status = os.fstat(descriptor)
        visible = os.lstat(path)
        if (
            not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
            or not os.path.samestat(status, visible)
            or os.pread(descriptor, len(_LOCK_BYTES) + 1, 0) != _LOCK_BYTES
        ):
            raise _fail()
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise _fail() from None


def _claim_generation(job_dir: Path, generation_id: str) -> None:
    if _SHA.fullmatch(generation_id) is None:
        raise _fail()
    claim = job_dir / f"{_CLAIM_PREFIX}{generation_id}.json"
    _write_new(claim, _canonical({"version": 1, "generation_id": generation_id}))
    _fsync_directory(job_dir)


def _ledger_contains(job_dir: Path, generation_id: str) -> bool:
    if _SHA.fullmatch(generation_id) is None:
        raise _fail()
    claim = job_dir / f"{_CLAIM_PREFIX}{generation_id}.json"
    if not os.path.lexists(claim):
        return False
    try:
        payload = _strict_json(_read_file(claim, 1024 * 1024))
    except (OSError, UnicodeError, ValueError):
        raise _fail() from None
    return (
        type(payload) is dict
        and set(payload) == {"version", "generation_id"}
        and payload["version"] == 1
        and payload["generation_id"] == generation_id
    )


def _write_ai_marker(job: state.JobState, payload: dict[str, object]) -> None:
    marker = job.job_dir / _AI_MARKER_NAME
    if os.path.lexists(marker):
        raise _fail()
    _write_new(marker, _canonical(payload))
    _fsync_directory(job.job_dir)


def _load_ai_marker(job: state.JobState) -> dict[str, object] | None:
    marker = job.job_dir / _AI_MARKER_NAME
    if not os.path.lexists(marker):
        return None
    try:
        payload = _strict_json(_read_file(marker, 1024 * 1024))
    except (OSError, UnicodeError, ValueError):
        raise _fail() from None
    if (
        type(payload) is not dict
        or set(payload) != {
            "version", "job_id", "generation_id", "stage", "base_revision",
            "workflow_sha256", "claimed", "stage_device", "stage_inode",
            "brief_sha256", "brief_bytes", "brief_device", "brief_inode",
        }
        or payload["version"] != 1
        or payload["job_id"] != job.job_id
        or type(payload["generation_id"]) is not str
        or _SHA.fullmatch(payload["generation_id"]) is None
        or type(payload["stage"]) is not str
        or not payload["stage"].startswith(".07-cover.stage-")
        or "/" in payload["stage"] or "\\" in payload["stage"]
        or type(payload["base_revision"]) is not int
        or type(payload["workflow_sha256"]) is not str
        or _SHA.fullmatch(payload["workflow_sha256"]) is None
        or payload["claimed"] is not True
        or type(payload["stage_device"]) is not int
        or type(payload["stage_inode"]) is not int
        or type(payload["brief_sha256"]) is not str
        or _SHA.fullmatch(payload["brief_sha256"]) is None
        or type(payload["brief_bytes"]) is not int
        or type(payload["brief_device"]) is not int
        or type(payload["brief_inode"]) is not int
    ):
        raise _fail()
    return payload


def _remove_ai_marker(job_dir: Path, payload: dict[str, object]) -> None:
    marker = job_dir / _AI_MARKER_NAME
    _retire_verified_file(marker, _canonical(payload))


def _partial_stage_matches(stage: Path, payload: dict[str, object]) -> bool:
    try:
        status = os.lstat(stage)
        if (
            not stat.S_ISDIR(status.st_mode)
            or status.st_dev != payload["stage_device"]
            or status.st_ino != payload["stage_inode"]
            or {item.name for item in stage.iterdir()} != {"cover-brief.json"}
        ):
            return False
        source, brief_status, _parent = _pinned_read(stage / "cover-brief.json")
        return (
            hashlib.sha256(source).hexdigest() == payload["brief_sha256"]
            and len(source) == payload["brief_bytes"]
            and brief_status.st_dev == payload["brief_device"]
            and brief_status.st_ino == payload["brief_inode"]
        )
    except (CoverError, OSError, KeyError, TypeError):
        return False


def _remove_partial_stage(job: state.JobState, payload: dict[str, object]) -> None:
    stage = job.job_dir / str(payload["stage"])
    _retire_verified_directory(
        stage, lambda candidate: _partial_stage_matches(candidate, payload)
    )


def _clear_ai_marker_for_transaction(
    job: state.JobState, transaction: dict[str, object]
) -> None:
    marker = _load_ai_marker(job)
    if marker is None:
        return
    if (
        marker["stage"] != transaction["stage"]
        or marker["base_revision"] != transaction["base_revision"]
        or marker["workflow_sha256"] != transaction["workflow_sha256"]
        or not marker["claimed"]
    ):
        raise _fail()
    _remove_ai_marker(job.job_dir, marker)


def _generation_id(
    job: state.JobState,
    workflow: dict[str, object],
    bindings: dict[str, dict[str, object]],
    brief: dict[str, object],
) -> str:
    return hashlib.sha256(_canonical({
        "job_id": job.job_id,
        "workflow": workflow,
        "source_bindings": bindings,
        "brief_sha256": hashlib.sha256(_canonical(brief)).hexdigest(),
    })).hexdigest()


def _dict(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise _fail()
    return value


def _text(value: object, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value.strip()) or value != value.strip():
        raise _fail()
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise _fail()
    return float(value)


def _ratio(value: object, low: float, high: float) -> float:
    checked = _number(value)
    if checked < low or checked > high:
        raise _fail()
    return checked


def _color(value: object) -> str:
    checked = _text(value)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", checked):
        raise _fail()
    return checked.upper()


def _title(value: object) -> str:
    checked = _text(value)
    if not 4 <= len(checked) <= 8 or any(not _is_han(char) for char in checked):
        raise _fail()
    return checked


def _headline_text(value: object) -> str:
    checked = _text(value)
    if len(checked) > 12 or any(ord(character) < 32 for character in checked):
        raise _fail()
    return checked


def _headline_lines(value: object) -> list[str]:
    if type(value) is str:
        return [_headline_text(value)]
    if type(value) is not list or not 1 <= len(value) <= 2:
        raise _fail()
    return [_headline_text(item) for item in value]


def _person_protection_boxes(value: object) -> list[list[float]]:
    if type(value) is not list or not 1 <= len(value) <= 8:
        raise _fail()
    boxes = []
    for item in value:
        if type(item) is not list or len(item) != 4:
            raise _fail()
        coordinates = [_number(coordinate) for coordinate in item]
        left, top, right, bottom = coordinates
        if not (
            0.0 <= left < right <= 1.0
            and 0.0 <= top < bottom <= 1.0
        ):
            raise _fail()
        boxes.append(coordinates)
    return boxes


def _reference_scene(value: object) -> dict[str, object]:
    checked = _dict(value, _REFERENCE_SCENE_KEYS)
    if _SHA.fullmatch(_text(checked["sha256"])) is None:
        raise _fail()
    if type(checked["bytes"]) is not int or checked["bytes"] <= 0:
        raise _fail()
    return checked


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return any(low <= codepoint <= high for low, high in (
        (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
        (0x20000, 0x2EBEF), (0x2F800, 0x2FA1F), (0x30000, 0x323AF),
    ))


def _scene_prompt(details: dict[str, object]) -> str:
    background = details["background"]
    if type(background) is not str or re.fullmatch(r"[a-z]+(?:-[a-z]+)*", background) is None:
        raise _fail()
    side = details["person_side"]
    ratio = round(_number(details["person_width_ratio"]) * 100)
    margin = round(_number(details["safe_margin_ratio"]) * 100)
    return (
        f"3:4 portrait composition. Create a clean {background} editorial scene "
        f"background with calm depth. Reserve the {side} side for a local foreground "
        f"composite occupying {ratio} percent. Preserve {margin} percent safe margins. "
        "No people. No text. No letters. No words. No typography. No captions. "
        "No logos. No watermarks."
    )


def validate_cover_brief(
    payload: object, *, expected_face_sha256: str | None = None,
    expected_face_timestamp: float | None = None,
) -> dict[str, object]:
    """Return a detached, strict gbro brief suitable for model/local rendering."""
    if type(payload) is not dict:
        raise _fail()
    keys = frozenset(payload)
    optional_keys = {
        "headline", "reference_scene", "output_aspect_ratio",
        "person_protection_boxes", "support_line",
    }
    if not _BRIEF_KEYS.issubset(keys) or not keys.issubset(
        _BRIEF_KEYS | optional_keys
    ):
        raise _fail()
    root = payload
    full_image_mode = root["base_generation"] == "approved_full_image"
    if root["version"] != 1 or root["generator"] != (
        "punk-cover" if full_image_mode else "gbro-cover-design"
    ):
        raise _fail()
    if (
        "output_aspect_ratio" in root
        and root["output_aspect_ratio"] not in _ASPECT_OUTPUTS
    ):
        raise _fail()
    title = _title(root["title"])
    style_id = _text(root["style_id"])
    if _STYLE.fullmatch(style_id) is None:
        raise _fail()
    subtitle = _text(root["subtitle"], nonempty=False)
    if style_id == "style-01":
        headline = _dict(root.get("headline"), _HEADLINE_KEYS)
        if _headline_text(headline["primary"]) != title:
            raise _fail()
        highlight_lines = _headline_lines(headline["highlight"])
        if len(highlight_lines) > 1 and root.get("output_aspect_ratio") != "9:16":
            raise _fail()
        conclusion_lines = _headline_lines(headline["conclusion"])
        if len(conclusion_lines) > 1 and root.get("output_aspect_ratio") != "9:16":
            raise _fail()
    elif "headline" in root:
        raise _fail()

    if type(root["face_frame"]) is not dict:
        raise _fail()
    face = root["face_frame"]
    face_source = face.get("source")
    if face_source == "current-aroll-video" and set(face) == _AROLL_FACE_KEYS:
        face_timestamp: float | None = _number(face["timestamp"])
        if face_timestamp < 0:
            raise _fail()
    elif face_source == "user-material" and set(face) == _USER_FACE_KEYS:
        face_timestamp = None
        material_id = _text(face["material_id"])
        if re.fullmatch(r"material-[0-9]{4,}", material_id) is None:
            raise _fail()
    else:
        raise _fail()
    face_sha = _text(face["sha256"])
    if _SHA.fullmatch(face_sha) is None:
        raise _fail()
    if expected_face_sha256 is not None and face_sha != expected_face_sha256:
        raise _fail()
    if (
        expected_face_timestamp is not None
        and face_timestamp != _number(expected_face_timestamp)
    ):
        raise _fail()

    rounds = _dict(root["rounds"], _ROUND_KEYS)
    first = _dict(rounds["style_and_title"], _STYLE_KEYS)
    if first["selection"] != style_id or _title(first["title"]) != title:
        raise _fail()
    _text(first["reason"])
    references = _dict(rounds["references"], _REFERENCE_KEYS)
    if references["face_source"] != face_source or type(references["extras"]) is not list:
        raise _fail()
    if references["extras"]:
        raise _fail()
    details = _dict(rounds["visual_details"], _DETAIL_KEYS)
    if details["person_side"] not in {"left", "right"}:
        raise _fail()
    if style_id == "style-07":
        _ratio(details["person_width_ratio"], 0.25, 0.35)
        _ratio(details["blank_width_ratio"], 0.60, 0.70)
    else:
        _ratio(details["person_width_ratio"], 0.10, 0.80)
        _ratio(details["blank_width_ratio"], 0.10, 0.80)
    _text(details["expression"])
    _text(details["background"])
    if details["font_style"] != "heavy-sans":
        raise _fail()
    _color(details["font_color"])
    margin_min = 0.04 if style_id == "style-07" and root.get("output_aspect_ratio") == "9:16" else 0.10
    _ratio(details["safe_margin_ratio"], margin_min, 0.15)

    reference_mode = root["base_generation"] == "reference_person_scene_no_text"
    if full_image_mode:
        if "reference_scene" in root or "person_protection_boxes" in root:
            raise _fail()
    elif reference_mode:
        if "reference_scene" not in root:
            raise _fail()
        _reference_scene(root["reference_scene"])
    elif root["base_generation"] != "scene_only_no_people_no_text" or "reference_scene" in root:
        raise _fail()
    creator_portrait = style_id == "style-07" and root.get("output_aspect_ratio") == "9:16"
    if creator_portrait and (not subtitle or details["person_side"] != "right"):
        raise _fail()
    if "support_line" in root:
        support_line = _text(root["support_line"])
        if (
            not creator_portrait or len(support_line) > 24
            or any(ord(character) < 32 for character in support_line)
        ):
            raise _fail()
    requires_protection = (
        reference_mode
        and style_id in {"style-01", "style-07"}
        and root.get("output_aspect_ratio") == "9:16"
    )
    if requires_protection != ("person_protection_boxes" in root):
        raise _fail()
    if requires_protection:
        _person_protection_boxes(root["person_protection_boxes"])
    prompt = _text(root["base_prompt"])
    if full_image_mode:
        if len(prompt) > 16_000:
            raise _fail()
    elif reference_mode and face_source == "user-material":
        if len(prompt) > 8_000 or re.search(r"[\u3400-\u9fff]", prompt):
            raise _fail()
        normalized_prompt = prompt.lower()
        forbids_text = (
            "no text" in normalized_prompt
            or re.search(r"avoid:[^\n]*any text", normalized_prompt) is not None
        )
        if not forbids_text or "watermark" not in normalized_prompt:
            raise _fail()
    elif prompt != _scene_prompt(details):
        raise _fail()

    composite = _dict(root["person_composite"], _PERSON_KEYS)
    person_min, person_max = (0.25, 0.35) if style_id == "style-07" else (0.10, 0.80)
    expected_method = (
        "approved-preview-integrated" if full_image_mode else
        "generated-reference-person" if reference_mode else
        "local-foreground-cutout"
    )
    if (
        composite["source"] != face_source
        or composite["method"] != expected_method
        or composite["side"] != details["person_side"]
        or _ratio(composite["person_width_ratio"], person_min, person_max)
        != _ratio(details["person_width_ratio"], person_min, person_max)
    ):
        raise _fail()

    layer = _dict(root["text_layer"], _TEXT_KEYS)
    expected_side = "right" if details["person_side"] == "left" else "left"
    expected_engine = "approved-preview-integrated" if full_image_mode else "Pillow"
    if layer["engine"] != expected_engine or layer["side"] != expected_side:
        raise _fail()
    if layer["font_style"] != details["font_style"]:
        raise _fail()
    if _color(layer["color"]) != _color(details["font_color"]):
        raise _fail()
    if _ratio(layer["safe_margin_ratio"], margin_min, 0.15) != _ratio(
        details["safe_margin_ratio"], margin_min, 0.15
    ):
        raise _fail()
    return copy.deepcopy(root)


def _approved_headline_conclusion(direction: dict[str, object]) -> str:
    candidates = direction.get("prompt_allow")
    if type(candidates) is not list:
        raise _fail()
    production_terms = (
        "人物", "脸", "头肩", "双手", "手部", "手臂", "参考图",
        "中文", "标题", "文字", "字体", "完整", "无遮挡", "安全区",
    )
    for candidate in reversed(candidates):
        if (
            type(candidate) is str
            and 1 <= len(candidate) <= 12
            and not any(term in candidate for term in production_terms)
        ):
            return _headline_text(candidate)
    return _headline_text(direction["subtitle"] or direction["title"])


def _brief_from_approved_direction(
    record: dict[str, object], *, generated_scene: Path | None = None,
    generated_scene_prompt: str | None = None,
    approved_preview_prompt: str | None = None,
    headline_highlight_lines: list[str] | None = None,
    headline_conclusion_lines: list[str] | None = None,
    person_protection_boxes: list[list[float]] | None = None,
) -> dict[str, object]:
    direction = record["direction"]
    reference = direction["person_reference"]
    composition = direction["composition"]
    palette = direction["palette"]
    typography = direction["typography"]
    safe_zones = direction["safe_zones"]
    title = direction["title"]
    subtitle = direction["subtitle"] or title
    has_headline_override = (
        headline_highlight_lines is not None
        or headline_conclusion_lines is not None
    )
    if has_headline_override and (
        composition["style_id"] != "style-01"
        or direction["output_aspect_ratio"] != "9:16"
    ):
        raise _fail()
    details = {
        "person_side": composition["person_side"],
        "person_width_ratio": composition["person_width_ratio"],
        "blank_width_ratio": composition["blank_width_ratio"],
        "expression": direction["expression"],
        "background": palette["background"],
        "font_style": typography["font_style"],
        "font_color": palette["font_color"],
        "safe_margin_ratio": safe_zones["safe_margin_ratio"],
    }
    text_side = "right" if composition["person_side"] == "left" else "left"
    reference_source = reference["source"]
    if reference_source == "current-aroll-video":
        face_frame = {
            "source": reference_source,
            "timestamp": reference["timestamp"],
            "sha256": reference["sha256"],
        }
        base_generation = "scene_only_no_people_no_text"
        base_prompt = _scene_prompt(details)
        composite_method = "local-foreground-cutout"
        reference_scene = None
    elif reference_source == "user-material":
        if approved_preview_prompt is None and (
            generated_scene is None or generated_scene_prompt is None
        ):
            raise CoverError(
                "approved user-material cover requires generated_scene and prompt"
            )
        face_frame = {
            "source": reference_source,
            "material_id": reference["material_id"],
            "sha256": reference["sha256"],
        }
        if approved_preview_prompt is None:
            scene_source = _read_file(generated_scene, openlux_images.MAX_IMAGE_BYTES)
            base_generation = "reference_person_scene_no_text"
            base_prompt = generated_scene_prompt
            composite_method = "generated-reference-person"
            reference_scene = {
                "sha256": hashlib.sha256(scene_source).hexdigest(),
                "bytes": len(scene_source),
            }
        else:
            reference_scene = None
    else:
        raise _fail()
    if approved_preview_prompt is not None:
        if generated_scene is not None or generated_scene_prompt is not None:
            raise _fail()
        base_generation = "approved_full_image"
        base_prompt = _text(approved_preview_prompt)
        composite_method = "approved-preview-integrated"
    brief: dict[str, object] = {
        "version": 1,
        "generator": (
            "punk-cover" if approved_preview_prompt is not None
            else "gbro-cover-design"
        ),
        "output_aspect_ratio": direction["output_aspect_ratio"],
        "title": title,
        "subtitle": subtitle,
        "style_id": composition["style_id"],
        "face_frame": face_frame,
        "rounds": {
            "style_and_title": {
                "selection": composition["style_id"],
                "title": title,
                "reason": (
                    "使用已通过人工审核的封面内容、人物动作和主题环境"
                ),
            },
            "references": {
                "face_source": reference_source,
                "extras": [],
            },
            "visual_details": details,
        },
        "base_generation": base_generation,
        "base_prompt": base_prompt,
        "person_composite": {
            "source": reference_source,
            "method": composite_method,
            "side": composition["person_side"],
            "person_width_ratio": composition["person_width_ratio"],
        },
        "text_layer": {
            "engine": (
                "approved-preview-integrated" if approved_preview_prompt is not None
                else "Pillow"
            ),
            "side": text_side,
            "font_style": typography["font_style"],
            "color": palette["font_color"],
            "safe_margin_ratio": safe_zones["safe_margin_ratio"],
        },
    }
    if composition["style_id"] == "style-01":
        highlight: str | list[str] = subtitle
        conclusion: str | list[str] = _approved_headline_conclusion(direction)
        if headline_highlight_lines is not None:
            approved_lines = _headline_lines(headline_highlight_lines)
            if (
                direction["output_aspect_ratio"] != "9:16"
                or "".join(approved_lines).replace(" ", "")
                != highlight.replace(" ", "")
            ):
                raise _fail()
            highlight = approved_lines
        if headline_conclusion_lines is not None:
            approved_lines = _headline_lines(headline_conclusion_lines)
            if (
                direction["output_aspect_ratio"] != "9:16"
                or "".join(approved_lines).replace(" ", "")
                != conclusion.replace(" ", "")
            ):
                raise _fail()
            conclusion = approved_lines
        brief["headline"] = {
            "primary": title,
            "highlight": highlight,
            "conclusion": conclusion,
        }
    if composition["style_id"] == "style-07" and direction.get("support_line"):
        brief["support_line"] = direction["support_line"]
    if reference_scene is not None:
        brief["reference_scene"] = reference_scene
        if (
            composition["style_id"] in {"style-01", "style-07"}
            and direction["output_aspect_ratio"] == "9:16"
        ):
            brief["person_protection_boxes"] = _person_protection_boxes(
                person_protection_boxes
            )
        elif person_protection_boxes is not None:
            raise _fail()
    elif person_protection_boxes is not None:
        raise _fail()
    return brief


def select_face_frame(
    video: Path,
    candidates: Iterable[dict[str, object] | float] | None = None,
    *,
    frame_reader: Callable[[Path, float], bytes] | None = None,
    quality_probe: Callable[[bytes], dict[str, object]] | None = None,
) -> dict[str, object]:
    """Choose the highest-scoring frame after strict face-quality filtering."""
    if not isinstance(video, Path):
        raise _fail()
    reader = frame_reader or _default_frame_reader
    probe = quality_probe or _default_quality_probe
    if candidates is None:
        candidates = _default_candidate_times(video)
    accepted: list[tuple[float, float, dict[str, object], bytes]] = []
    for candidate in candidates:
        if type(candidate) is dict:
            if set(candidate) != {
                "timestamp", "eyes_closed", "blur_score", "overexposed_ratio",
                "face_ratio", "score",
            }:
                raise _fail()
            timestamp = _number(candidate["timestamp"])
        elif type(candidate) in (int, float):
            timestamp = _number(candidate)
        else:
            raise _fail()
        if timestamp < 0:
            raise _fail()
        try:
            frame_source = reader(video, timestamp)
            measurements = probe(frame_source)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            continue
        if type(measurements) is not dict or set(measurements) != {
            "eyes_closed", "blur_score", "overexposed_ratio", "face_ratio", "score",
        }:
            raise _fail()
        if type(measurements["eyes_closed"]) is not bool:
            raise _fail()
        blur = _number(measurements["blur_score"])
        exposure = _number(measurements["overexposed_ratio"])
        face_ratio = _number(measurements["face_ratio"])
        score = _number(measurements["score"])
        if (
            not measurements["eyes_closed"]
            and blur >= 40.0
            and 0.0 <= exposure <= 0.25
            and 0.08 <= face_ratio <= 0.65
        ):
            accepted.append((score, -timestamp, measurements, frame_source))
    if not accepted:
        raise _fail()
    selected = max(accepted, key=lambda item: (item[0], item[1]))
    timestamp = -selected[1]
    try:
        source = selected[3]
        if type(source) is not bytes or not source:
            raise ValueError
        with Image.open(io.BytesIO(source)) as image:  # type: ignore[name-defined]
            image.load()
    except (OSError, ValueError):
        raise _fail() from None
    return {
        "source": "current-aroll-video",
        "timestamp": timestamp,
        "sha256": hashlib.sha256(source).hexdigest(),
        "bytes": source,
    }


def _default_candidate_times(video: Path) -> list[float]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video),
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        duration = float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        raise _fail() from None
    if not math.isfinite(duration) or duration <= 0:
        raise _fail()
    return [round(duration * ratio, 6) for ratio in (0.15, 0.30, 0.50, 0.70, 0.85)]


def _default_frame_reader(video: Path, timestamp: float) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-ss", f"{timestamp:.6f}", "-i", str(video), "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "png", "-",
            ],
            check=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        raise _fail() from None
    if not result.stdout:
        raise _fail()
    return result.stdout


def _default_quality_probe(source: bytes) -> dict[str, object]:
    try:
        import cv2
        import numpy as np

        encoded = np.frombuffer(source, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        eye_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"
        )
        faces = face_detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
        )
        if len(faces) != 1:
            raise ValueError
        x, y, width, height = max(faces, key=lambda item: item[2] * item[3])
        face_gray = gray[y:y + height, x:x + width]
        eyes = eye_detector.detectMultiScale(
            face_gray[: max(1, int(height * 0.65))],
            scaleFactor=1.1, minNeighbors=4, minSize=(8, 8),
        )
        blur = float(cv2.Laplacian(face_gray, cv2.CV_64F).var())
        overexposed = float(np.count_nonzero(gray >= 245) / gray.size)
        face_ratio = float((width * height) / (gray.shape[0] * gray.shape[1]))
        score = blur + face_ratio * 500.0 - overexposed * 200.0
        return {
            "eyes_closed": len(eyes) < 2,
            "blur_score": blur,
            "overexposed_ratio": overexposed,
            "face_ratio": face_ratio,
            "score": score,
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise _fail() from None


def render_cover_base(response: dict[str, object], output_stem: Path) -> Path:
    """Persist one OpenLux response using only the public V5 image API."""
    try:
        return openlux_images.save_image_response(response, output_stem)
    except (openlux_images.OpenLuxError, OSError, ValueError):
        raise _fail() from None


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size, index=0)
            except OSError:
                continue
    raise _fail()


def _fit_font(draw: ImageDraw.ImageDraw, title: str, max_width: int, max_height: int) -> ImageFont.FreeTypeFont:
    for size in range(max(36, max_height // 3), 35, -4):
        font = _font(size)
        box = draw.multiline_textbbox((0, 0), title, font=font, spacing=size // 5)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font
    raise _fail()


def _default_person_mask(source: bytes) -> bytes:
    try:
        import cv2
        import numpy as np

        encoded = np.frombuffer(source, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError
        height, width = frame.shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        background = np.zeros((1, 65), dtype=np.float64)
        foreground = np.zeros((1, 65), dtype=np.float64)
        rectangle = (
            max(1, width // 12), max(1, height // 50),
            max(2, width * 5 // 6), max(2, height * 48 // 50),
        )
        cv2.grabCut(
            frame, mask, rectangle, background, foreground, 5, cv2.GC_INIT_WITH_RECT
        )
        binary = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
        binary = cv2.GaussianBlur(binary, (0, 0), sigmaX=1.2, sigmaY=1.2)
        success, encoded_mask = cv2.imencode(".png", binary)
        if not success:
            raise ValueError
        return bytes(encoded_mask)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise _fail() from None


def _person_layer(
    source: bytes,
    mask_provider: Callable[[bytes], bytes] | None,
) -> Image.Image:
    try:
        with Image.open(io.BytesIO(source)) as frame:
            person = frame.convert("RGBA")
        mask_source = (mask_provider or _default_person_mask)(source)
        if type(mask_source) is not bytes or not mask_source:
            raise ValueError
        with Image.open(io.BytesIO(mask_source)) as decoded_mask:
            mask = decoded_mask.convert("L")
        if mask.size != person.size:
            raise ValueError
        bbox = mask.getbbox()
        nonzero = sum(mask.point(lambda value: 1 if value >= 128 else 0).getdata())
        coverage = nonzero / (mask.width * mask.height)
        if bbox is None or not 0.08 <= coverage <= 0.90:
            raise ValueError
        person.putalpha(mask)
        return person.crop(bbox)
    except CoverError:
        raise
    except (OSError, ValueError):
        raise _fail() from None


def _place_person(
    canvas: Image.Image,
    layer: Image.Image,
    brief: dict[str, object],
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    composite = brief["person_composite"]
    width = round(canvas.width * float(composite["person_width_ratio"]))
    height = round(layer.height * width / layer.width)
    maximum_height = round(canvas.height * 0.80)
    if height > maximum_height:
        height = maximum_height
        width = round(layer.width * height / layer.height)
    resized = layer.resize((width, height), Image.Resampling.LANCZOS)
    margin = round(canvas.width * 0.10)
    x = margin if composite["side"] == "left" else canvas.width - margin - width
    y = canvas.height - round(canvas.height * 0.10) - height
    result = canvas.convert("RGBA")
    if brief["style_id"] == "style-01":
        alpha = resized.getchannel("A")
        outline = alpha.filter(ImageFilter.MaxFilter(15))
        outline_layer = Image.new("RGBA", resized.size, (255, 214, 0, 0))
        outline_layer.putalpha(outline)
        result.alpha_composite(outline_layer, (x, y))
    result.alpha_composite(resized, (x, y))
    alpha_box = resized.getchannel("A").getbbox()
    if alpha_box is None:
        raise _fail()
    person_box = (
        x + alpha_box[0], y + alpha_box[1],
        x + alpha_box[2], y + alpha_box[3],
    )
    return result.convert("RGB"), person_box


def _impact_font(text: str, max_width: int, maximum_size: int) -> ImageFont.FreeTypeFont:
    path = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    for size in range(maximum_size, 47, -4):
        try:
            font = ImageFont.truetype(str(path), size=size, index=0)
        except OSError:
            font = _font(size)
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
    raise _fail()


def _impact_headline_layout_9x16(
    size: tuple[int, int], brief: dict[str, object],
    person_boxes: list[tuple[int, int, int, int]] | None = None,
) -> dict[str, object]:
    width, height = size
    headline = brief["headline"]
    margin = round(width * 0.10)
    region_left, region_right = margin, width - margin
    max_width = region_right - region_left
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    highlight_lines = _headline_lines(headline["highlight"])
    conclusion_lines = _headline_lines(headline["conclusion"])
    if brief["person_composite"]["side"] != "right":
        raise _fail()
    if person_boxes is None:
        normalized_boxes = _person_protection_boxes(
            brief.get("person_protection_boxes")
        )
        person_boxes = [
            (
                round(width * box[0]), round(height * box[1]),
                round(width * box[2]), round(height * box[3]),
            )
            for box in normalized_boxes
        ]
    if not person_boxes:
        raise _fail()
    for box in person_boxes:
        if (
            type(box) is not tuple or len(box) != 4
            or any(type(value) is not int for value in box)
            or not (0 <= box[0] < box[2] <= width)
            or not (0 <= box[1] < box[3] <= height)
        ):
            raise _fail()

    outer_stroke = max(5, round(width * 0.008))
    inner_stroke = max(2, round(width * 0.003))
    shadow_offset = max(5, round(width * 0.009))
    upper_content_width = max_width
    padding_x = round(width * 0.030)
    padding_y = round(width * 0.012)
    primary_font = _impact_font(
        headline["primary"],
        upper_content_width - 2 * outer_stroke - shadow_offset,
        round(width * 0.112),
    )
    highlight_maximum_sizes = (
        [round(width * 0.142)]
        if len(highlight_lines) == 1
        else [round(width * 0.128), round(width * 0.138)]
    )
    highlight_fonts = [
        _impact_font(
            text, upper_content_width - 2 * padding_x,
            highlight_maximum_sizes[index],
        )
        for index, text in enumerate(highlight_lines)
    ]
    conclusion_max_width = (
        round(width * 0.58) - region_left - 2 * outer_stroke - shadow_offset
    )
    conclusion_maximum_sizes = (
        [round(width * 0.082)]
        if len(conclusion_lines) == 1
        else [round(width * 0.076), round(width * 0.082)]
    )
    conclusion_fonts = [
        _impact_font(text, conclusion_max_width, conclusion_maximum_sizes[index])
        for index, text in enumerate(conclusion_lines)
    ]
    y = round(width * 0.025) + outer_stroke
    primary_box = measure.textbbox(
        (region_left + outer_stroke, y), headline["primary"],
        font=primary_font, anchor="lt",
        stroke_width=outer_stroke,
    )
    y = primary_box[3] + round(width * 0.022)

    highlights: list[dict[str, object]] = []
    minimum_widths = (
        [round(width * 0.68)]
        if len(highlight_lines) == 1
        else [round(width * 0.68), round(width * 0.58)]
    )
    angles = [-1.5] if len(highlight_lines) == 1 else [-1.7, -1.1]
    for index, text in enumerate(highlight_lines):
        font = highlight_fonts[index]
        text_box = measure.textbbox((0, 0), text, font=font, anchor="lt")
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        panel_width = min(
            upper_content_width,
            max(minimum_widths[index], text_width + 2 * padding_x),
        )
        panel_height = text_height + 2 * padding_y
        angle = angles[index]
        rotated_width, rotated_height = Image.new(
            "RGBA", (panel_width, panel_height), (0, 0, 0, 0)
        ).rotate(angle, resample=Image.Resampling.BICUBIC, expand=True).size
        if region_left + rotated_width > region_right:
            raise _fail()
        item = {
            "text": text,
            "box": (
                region_left, y, region_left + rotated_width, y + rotated_height,
            ),
            "font": font,
            "maximum_size": highlight_maximum_sizes[index],
            "text_size": (text_width, text_height),
            "panel_size": (panel_width, panel_height),
            "padding": (padding_x - text_box[0], padding_y - text_box[1]),
            "angle": angle,
            "radius": 0,
            "panel_shadow": False,
        }
        highlights.append(item)
        y = item["box"][3] + round(width * (0.017 if index == 0 else 0.021))

    conclusions: list[dict[str, object]] = []
    for index, text in enumerate(conclusion_lines):
        font = conclusion_fonts[index]
        box = measure.textbbox(
            (region_left + outer_stroke, y), text, font=font, anchor="lt",
            stroke_width=outer_stroke,
        )
        if box[2] + shadow_offset > round(width * 0.58):
            raise _fail()
        conclusions.append({"text": text, "box": box, "font": font})
        y = box[3] + round(width * 0.007)
    accent_height = max(7, round(width * 0.009))
    accent_top = conclusions[-1]["box"][3] + round(width * 0.006)
    accent_right = round(width * 0.58)
    accent_gap = round(width * 0.012)
    for guard in person_boxes:
        if not (
            accent_top + accent_height <= guard[1]
            or guard[3] <= accent_top
        ):
            accent_right = min(accent_right, guard[0] - accent_gap)
    if accent_right <= region_left + round(width * 0.20):
        raise _fail()
    accent_box = (
        region_left, accent_top,
        accent_right, accent_top + accent_height,
    )
    content_bottom = accent_box[3]
    content_limit = round(height * 0.41)
    if content_bottom > content_limit:
        raise _fail()
    primary_shadow_box = tuple(value + shadow_offset for value in primary_box)
    conclusion_boxes = []
    for item in conclusions:
        box = item["box"]
        conclusion_boxes.extend([
            box,
            tuple(value + shadow_offset for value in box),
        ])
    drawn_boxes = [
        primary_box,
        primary_shadow_box,
        *(item["box"] for item in highlights),
        *conclusion_boxes,
        accent_box,
    ]
    for box in drawn_boxes:
        if (
            box[0] < region_left or box[2] > region_right
            or box[1] < 0 or box[3] > height
        ):
            raise _fail()
        for guard in person_boxes:
            if not (
                box[2] <= guard[0]
                or guard[2] <= box[0]
                or box[3] <= guard[1]
                or guard[3] <= box[1]
            ):
                raise _fail()
    shade_fade_start = min(round(height * 0.31), content_bottom)
    shade_bottom = min(content_limit, shade_fade_start + round(width * 0.05))
    return {
        "primary": {"box": primary_box, "font": primary_font},
        "highlight": highlights[0],
        "highlights": highlights,
        "conclusion": conclusions[0],
        "conclusions": conclusions,
        "accent": {"box": accent_box},
        "outer_stroke": outer_stroke,
        "inner_stroke": inner_stroke,
        "shadow_offset": shadow_offset,
        "shade_fade_start": shade_fade_start,
        "shade_bottom": shade_bottom,
        "content_bottom": content_bottom,
        "drawn_boxes": drawn_boxes,
        "person_guards": person_boxes,
        "portrait_9x16": True,
    }


def _impact_headline_layout(
    size: tuple[int, int], brief: dict[str, object],
    person_boxes: list[tuple[int, int, int, int]] | None = None,
) -> dict[str, object]:
    if brief.get("output_aspect_ratio") == "9:16":
        return _impact_headline_layout_9x16(size, brief, person_boxes)
    width, height = size
    unit = min(width, height)
    headline = brief["headline"]
    margin = round(width * 0.10)
    if "output_aspect_ratio" in brief:
        if brief["text_layer"]["side"] == "left":
            region_left, region_right = margin, round(width * 0.52)
        else:
            region_left, region_right = round(width * 0.48), width - margin
    else:
        region_left, region_right = margin, width - margin
    max_width = region_right - region_left
    padded_max_width = max_width - round(unit * 0.06)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    primary_font = _impact_font(
        headline["primary"], max_width, round(unit * 0.11)
    )
    highlight_font = _impact_font(
        headline["highlight"], padded_max_width, round(unit * 0.13)
    )
    conclusion_font = _impact_font(
        headline["conclusion"], max_width, round(unit * 0.10)
    )
    outer_stroke = max(5, round(unit * 0.008))
    inner_stroke = max(2, round(unit * 0.003))
    shadow_offset = max(5, round(unit * 0.009))
    line_gap = max(4, round(unit * 0.006))

    y = round(unit * 0.045)
    primary_box = measure.textbbox(
        (region_left, y), headline["primary"], font=primary_font, anchor="lt",
        stroke_width=outer_stroke,
    )
    y = primary_box[3] + line_gap

    highlight_text_box = measure.textbbox(
        (0, 0), headline["highlight"], font=highlight_font, anchor="lt"
    )
    padding_x = round(unit * 0.025)
    padding_y = round(unit * 0.010)
    highlight_width = highlight_text_box[2] + 2 * padding_x
    highlight_height = highlight_text_box[3] + 2 * padding_y
    highlight_angle = -2.5
    poster_width = highlight_width + 2 * shadow_offset
    poster_height = highlight_height + 2 * shadow_offset
    radians = math.radians(abs(highlight_angle))
    rotated_width = round(
        poster_width * math.cos(radians) + poster_height * math.sin(radians)
    )
    rotated_height = round(
        poster_width * math.sin(radians) + poster_height * math.cos(radians)
    )
    highlight_x = region_left
    highlight_box = (
        highlight_x, y, highlight_x + rotated_width, y + rotated_height,
    )
    y = highlight_box[3] + line_gap

    conclusion_x = region_left + round(unit * 0.035)
    conclusion_box = measure.textbbox(
        (conclusion_x, y), headline["conclusion"], font=conclusion_font,
        anchor="lt", stroke_width=outer_stroke,
    )
    accent_height = max(7, round(unit * 0.009))
    accent_top = conclusion_box[3] + max(2, round(unit * 0.002))
    accent_box = (
        region_left + round(max_width * 0.45), accent_top,
        region_right - round(unit * 0.02), accent_top + accent_height,
    )
    content_bottom = accent_box[3]
    content_limit_ratio = 0.72 if width > height else 0.37
    if content_bottom > round(height * content_limit_ratio):
        raise _fail()
    shade_fade_start = min(
        round(height * (0.66 if width > height else 0.32)),
        content_bottom + round(unit * 0.008),
    )
    shade_bottom = min(
        round(height * content_limit_ratio),
        shade_fade_start + round(unit * 0.045),
    )
    return {
        "primary": {"box": primary_box, "font": primary_font},
        "highlight": {
            "box": highlight_box,
            "font": highlight_font,
            "text_size": (highlight_text_box[2], highlight_text_box[3]),
            "panel_size": (highlight_width, highlight_height),
            "padding": (padding_x, padding_y),
            "angle": highlight_angle,
            "radius": 0,
        },
        "conclusion": {"box": conclusion_box, "font": conclusion_font},
        "accent": {"box": accent_box},
        "outer_stroke": outer_stroke,
        "inner_stroke": inner_stroke,
        "shadow_offset": shadow_offset,
        "shade_fade_start": shade_fade_start,
        "shade_bottom": shade_bottom,
        "content_bottom": content_bottom,
    }


def _render_impact_headline(
    image: Image.Image, brief: dict[str, object],
    person_boxes: list[tuple[int, int, int, int]] | None = None,
) -> Image.Image:
    canvas = image.convert("RGBA")
    layout = _impact_headline_layout(canvas.size, brief, person_boxes)
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    fade_start = layout["shade_fade_start"]
    fade_bottom = layout["shade_bottom"]
    shade_draw.rectangle((0, 0, canvas.width, fade_start), fill=(3, 6, 12, 190))
    fade = max(1, fade_bottom - fade_start)
    for offset in range(fade):
        alpha = round(190 * (1 - offset / fade) ** 2)
        shade_draw.line(
            (0, fade_start + offset, canvas.width, fade_start + offset),
            fill=(3, 6, 12, alpha),
        )
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas)
    headline = brief["headline"]
    outer_stroke = layout["outer_stroke"]
    inner_stroke = layout["inner_stroke"]
    shadow_offset = layout["shadow_offset"]
    primary = layout["primary"]
    primary_xy = primary["box"][:2]
    shadow_xy = (
        primary_xy[0] + shadow_offset, primary_xy[1] + shadow_offset,
    )
    draw.text(
        shadow_xy, headline["primary"], font=primary["font"], anchor="lt",
        fill="#05070B", stroke_width=outer_stroke, stroke_fill="#05070B",
    )
    draw.text(
        primary_xy, headline["primary"], font=primary["font"], anchor="lt",
        fill="#FFFFFF", stroke_width=inner_stroke, stroke_fill="#FFFFFF",
    )

    if layout.get("portrait_9x16"):
        for highlight in layout["highlights"]:
            panel_width, panel_height = highlight["panel_size"]
            poster = Image.new(
                "RGBA", (panel_width, panel_height), "#FFD600",
            )
            poster_draw = ImageDraw.Draw(poster)
            poster_draw.text(
                highlight["padding"], highlight["text"],
                font=highlight["font"], anchor="lt", fill="#080B10",
                stroke_width=inner_stroke, stroke_fill="#080B10",
            )
            rotated = poster.rotate(
                highlight["angle"], resample=Image.Resampling.BICUBIC,
                expand=True,
            )
            canvas.alpha_composite(rotated, highlight["box"][:2])
    else:
        highlight = layout["highlight"]
        panel_width, panel_height = highlight["panel_size"]
        padding_x, padding_y = highlight["padding"]
        poster = Image.new(
            "RGBA",
            (panel_width + 2 * shadow_offset, panel_height + 2 * shadow_offset),
            (0, 0, 0, 0),
        )
        poster_draw = ImageDraw.Draw(poster)
        poster_draw.rectangle(
            (shadow_offset, shadow_offset, panel_width + shadow_offset,
             panel_height + shadow_offset),
            fill=(0, 0, 0, 210),
        )
        poster_draw.rectangle((0, 0, panel_width, panel_height), fill="#FFD600")
        poster_draw.text(
            (padding_x, padding_y), headline["highlight"],
            font=highlight["font"], anchor="lt", fill="#080B10",
            stroke_width=inner_stroke, stroke_fill="#080B10",
        )
        rotated = poster.rotate(
            highlight["angle"], resample=Image.Resampling.BICUBIC, expand=True,
        )
        canvas.alpha_composite(rotated, highlight["box"][:2])
    draw = ImageDraw.Draw(canvas)

    conclusions = (
        layout["conclusions"]
        if layout.get("portrait_9x16") else [layout["conclusion"]]
    )
    for conclusion in conclusions:
        conclusion_xy = conclusion["box"][:2]
        shadow_xy = (
            conclusion_xy[0] + shadow_offset,
            conclusion_xy[1] + shadow_offset,
        )
        conclusion_text = (
            conclusion["text"]
            if layout.get("portrait_9x16") else headline["conclusion"]
        )
        draw.text(
            shadow_xy, conclusion_text, font=conclusion["font"], anchor="lt",
            fill="#05070B", stroke_width=outer_stroke, stroke_fill="#05070B",
        )
        draw.text(
            conclusion_xy, conclusion_text, font=conclusion["font"],
            anchor="lt", fill="#FFFFFF", stroke_width=inner_stroke,
            stroke_fill="#FFFFFF",
        )
    accent = layout["accent"]["box"]
    rise = max(3, round(canvas.width * 0.004))
    draw.polygon(
        ((accent[0], accent[3] - rise), (accent[2], accent[1]),
         (accent[2], accent[3]), (accent[0], accent[3])),
        fill="#FF3B30",
    )
    return canvas.convert("RGB")


def _render_creator_portrait(
    image: Image.Image, brief: dict[str, object],
    person_boxes: list[tuple[int, int, int, int]] | None,
) -> Image.Image:
    """Locally typeset the approved copy as a creator-style visual headline."""
    width, height = image.size
    if width * 16 != height * 9 or brief["person_composite"]["side"] != "right":
        raise _fail()
    if person_boxes is None:
        person_boxes = [
            (round(width * x0), round(height * y0),
             round(width * x1), round(height * y1))
            for x0, y0, x1, y1 in _person_protection_boxes(
                brief.get("person_protection_boxes")
            )
        ]
    if not person_boxes:
        raise _fail()
    margin = round(width * float(brief["text_layer"]["safe_margin_ratio"]))
    available = width - 2 * margin
    title = brief["title"]
    emphasis = brief["subtitle"]
    if not emphasis:
        raise _fail()
    support_text = brief.get("support_line", "")
    if len(emphasis) > 9:
        if support_text:
            raise _fail()
        lead, separator, tail = emphasis.partition("，")
        if not separator or not lead or not tail:
            raise _fail()
        emphasis, support_text = lead + separator, tail
    if len(emphasis) > 9:
        raise _fail()
    bold_font_path = Path(
        "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
        "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"
    )
    def creator_font(size: int) -> ImageFont.FreeTypeFont:
        if bold_font_path.exists():
            return ImageFont.truetype(str(bold_font_path), size, index=11)
        return _impact_font("真正淘汰你的", width * 2, size)

    def text_sprite(
        value: str, font: ImageFont.FreeTypeFont, target_width: int,
        fill: str, outline: str, stroke: int,
    ) -> Image.Image:
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bounds = measure.textbbox(
            (0, 0), value, font=font, anchor="lt", stroke_width=stroke
        )
        padding = stroke + 4
        sprite = Image.new(
            "RGBA",
            (bounds[2] - bounds[0] + 2 * padding,
             bounds[3] - bounds[1] + 2 * padding),
            (0, 0, 0, 0),
        )
        ImageDraw.Draw(sprite).text(
            (padding - bounds[0], padding - bounds[1]), value,
            font=font, anchor="lt", fill=fill,
            stroke_width=stroke, stroke_fill=outline,
        )
        if sprite.width > target_width:
            sprite = sprite.resize(
                (target_width, sprite.height), Image.Resampling.LANCZOS
            )
        return sprite

    title_sprite = text_sprite(
        title, creator_font(round(width * 0.165)),
        round(width * 0.78), "#FFFFFF", "#05070B",
        max(7, round(width * 0.009)),
    )
    shear = round(title_sprite.height * 0.18)
    title_sprite = title_sprite.transform(
        (title_sprite.width + shear, title_sprite.height),
        Image.Transform.AFFINE, (1, -0.18, 0, 0, 1, 0),
        resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0),
    ).rotate(2, resample=Image.Resampling.BICUBIC, expand=True)
    if title_sprite.width > available:
        title_sprite = title_sprite.resize(
            (available, title_sprite.height), Image.Resampling.LANCZOS
        )
    title_y = round(height * 0.045)
    title_box = (
        margin, title_y, margin + title_sprite.width, title_y + title_sprite.height,
    )
    pad_x = round(width * 0.018)
    pad_y = round(width * 0.010)
    panel_width = available - round(width * 0.010)
    emphasis_sprite = text_sprite(
        emphasis, creator_font(round(width * 0.165)),
        panel_width - 2 * pad_x, "#080B10", "#080B10", 2,
    )
    emphasis_shear = round(emphasis_sprite.height * 0.10)
    emphasis_sprite = emphasis_sprite.transform(
        (emphasis_sprite.width + emphasis_shear, emphasis_sprite.height),
        Image.Transform.AFFINE, (1, -0.10, 0, 0, 1, 0),
        resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0),
    )
    if emphasis_sprite.width > panel_width - 2 * pad_x:
        emphasis_sprite = emphasis_sprite.resize(
            (panel_width - 2 * pad_x, emphasis_sprite.height),
            Image.Resampling.LANCZOS,
        )
    panel = Image.new(
        "RGBA", (panel_width, emphasis_sprite.height + 2 * pad_y), "#FFD600"
    )
    panel.alpha_composite(
        emphasis_sprite,
        ((panel_width - emphasis_sprite.width) // 2, pad_y),
    )
    panel = panel.rotate(-3, resample=Image.Resampling.BICUBIC, expand=True)
    if panel.width > available:
        panel = panel.resize((available, panel.height), Image.Resampling.LANCZOS)
    panel_y = round(height * 0.14)
    panel_box = (margin, panel_y, margin + panel.width, panel_y + panel.height)
    support_sprite = None
    support_box = None
    if support_text:
        support_sprite = text_sprite(
            support_text, creator_font(round(width * 0.056)),
            available - 2 * pad_x, "#FFFFFF", "#05070B", 3,
        )
        support_y = panel_box[3] - round(width * 0.008)
        support_x = margin + pad_x
        support_limit = min(
            [width - margin - support_x]
            + [guard[0] - support_x - round(width * 0.04)
               for guard in person_boxes
               if support_y + support_sprite.height > guard[1]
               and support_y < guard[3]]
        )
        if support_limit < round(width * 0.30):
            raise _fail()
        if support_sprite.width > round(support_limit * 1.35):
            raise _fail()
        if support_sprite.width > support_limit:
            support_sprite = support_sprite.resize(
                (support_limit, support_sprite.height), Image.Resampling.LANCZOS
            )
        support_box = (
            support_x, support_y,
            support_x + support_sprite.width,
            support_y + support_sprite.height,
        )
    for box in (title_box, panel_box, *([support_box] if support_box else [])):
        if box[0] < margin or box[2] > width - margin or box[3] > round(height * 0.42):
            raise _fail()
        for guard in person_boxes:
            if not (box[2] <= guard[0] or guard[2] <= box[0]
                    or box[3] <= guard[1] or guard[3] <= box[1]):
                raise _fail()
    shadow_dx = round(width * 0.008)
    shadow_dy = round(width * 0.011)
    decoration_boxes = [
        (panel_box[0] + shadow_dx, panel_box[1] + shadow_dy,
         panel_box[2] + shadow_dx, panel_box[3] + shadow_dy),
        (round(width * 0.86), round(height * 0.08),
         round(width * 0.99), round(height * 0.17)),
    ]
    if support_box is not None:
        decoration_boxes.append((
            support_box[0] - round(width * 0.012),
            support_box[1] - round(width * 0.005),
            support_box[2] + round(width * 0.012),
            support_box[3] + round(width * 0.024),
        ))
    for box in decoration_boxes:
        if box[0] < 0 or box[2] > width or box[3] > round(height * 0.42):
            raise _fail()
        for guard in person_boxes:
            if not (box[2] <= guard[0] or guard[2] <= box[0]
                    or box[3] <= guard[1] or guard[3] <= box[1]):
                raise _fail()
    canvas = image.convert("RGBA")
    shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    fade_end = max(
        (support_box or panel_box)[3] + round(width * 0.04),
        round(height * 0.28),
    )
    for y in range(fade_end):
        alpha = round(175 * (1 - y / fade_end) ** 1.5)
        shade_draw.line((0, y, width, y), fill=(2, 5, 10, alpha))
    canvas = Image.alpha_composite(canvas, shade)
    burst = ImageDraw.Draw(canvas)
    burst.polygon(
        ((round(width * 0.86), round(height * 0.125)),
         (round(width * 0.89), round(height * 0.08)),
         (round(width * 0.885), round(height * 0.13))),
        fill="#FFD600",
    )
    burst.polygon(
        ((round(width * 0.91), round(height * 0.137)),
         (round(width * 0.955), round(height * 0.09)),
         (round(width * 0.94), round(height * 0.149))),
        fill="#FFD600",
    )
    burst.polygon(
        ((round(width * 0.95), round(height * 0.156)),
         (round(width * 0.99), round(height * 0.14)),
         (round(width * 0.965), round(height * 0.17))),
        fill="#FFD600",
    )
    canvas.alpha_composite(title_sprite, title_box[:2])
    shadow = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    shadow.putalpha(panel.getchannel("A"))
    canvas.alpha_composite(
        shadow, (panel_box[0] + shadow_dx, panel_box[1] + shadow_dy),
    )
    canvas.alpha_composite(panel, panel_box[:2])
    if support_box is not None and support_sprite is not None:
        draw = ImageDraw.Draw(canvas)
        support_pad_x = round(width * 0.012)
        support_pad_y = round(width * 0.005)
        draw.rectangle(
            (support_box[0] - support_pad_x, support_box[1] - support_pad_y,
             support_box[2] + support_pad_x, support_box[3] + support_pad_y),
            fill="#06080C",
        )
        canvas.alpha_composite(support_sprite, support_box[:2])
        underline_y = support_box[3] + support_pad_y + round(width * 0.006)
        draw.line(
            (support_box[0] - support_pad_x, underline_y,
             support_box[2] + support_pad_x, underline_y - round(width * 0.01)),
            fill="#FFD600", width=max(4, round(width * 0.008)),
        )
    return canvas.convert("RGB")


def _render_one(
    base: Image.Image,
    brief: dict[str, object],
    size: tuple[int, int],
    person: Image.Image | None = None,
) -> Image.Image:
    image = ImageOps.fit(base.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    person_boxes = None
    if person is not None:
        image, person_box = _place_person(image, person, brief)
        person_boxes = [person_box]
    if brief["style_id"] == "style-07" and brief.get("output_aspect_ratio") == "9:16":
        return _render_creator_portrait(image, brief, person_boxes)
    if brief["style_id"] == "style-01":
        return _render_impact_headline(image, brief, person_boxes)
    draw = ImageDraw.Draw(image)
    layer = brief["text_layer"]
    margin = round(size[0] * float(layer["safe_margin_ratio"]))
    left_half = layer["side"] == "left"
    x0 = margin if left_half else size[0] // 2
    x1 = size[0] // 2 if left_half else size[0] - margin
    y0, y1 = round(size[1] * 0.18), round(size[1] * 0.82)
    title = brief["title"]
    subtitle = brief.get("subtitle") or ""
    if "淘汰" in title:
        title_parts = [title.split("淘汰", 1)[0], "淘汰", title.split("淘汰", 1)[1]]
    else:
        split = (len(title) + 1) // 2
        title_parts = [title[:split], title[split:]]
    title_parts = [part for part in title_parts if part]
    max_height = round((y1 - y0) * 0.72)
    regular_font = _fit_font(draw, "\n".join(title_parts), x1 - x0, max_height)
    keyword_font = ImageFont.truetype(
        regular_font.path, max(regular_font.size, round(regular_font.size * 1.12))
    ) if hasattr(regular_font, "path") else regular_font
    line_fonts = [keyword_font if part == "淘汰" else regular_font for part in title_parts]
    line_heights = [draw.textbbox((0, 0), part, font=font)[3] for part, font in zip(title_parts, line_fonts)]
    total_height = sum(line_heights) + round(regular_font.size * 0.08) * (len(title_parts) - 1)
    y = y0 + max(0, (y1 - y0 - total_height) // 2)
    for part, font, line_height in zip(title_parts, line_fonts, line_heights):
        box = draw.textbbox((0, 0), part, font=font)
        width = box[2] - box[0]
        x = x0 + (x1 - x0 - width) // 2
        color = "#FFD84D" if part == "淘汰" else layer["color"]
        draw.text((x, y), part, font=font, fill=color, stroke_width=max(1, font.size // 80), stroke_fill=color)
        y += line_height + round(regular_font.size * 0.08)
    if subtitle:
        subtitle_lines = subtitle.replace("，", "，\n", 1)
        subtitle_font = _fit_font(
            draw, subtitle_lines, x1 - x0, round(size[1] * 0.09),
        )
        subtitle_box = draw.multiline_textbbox(
            (0, 0), subtitle_lines, font=subtitle_font,
            spacing=subtitle_font.size // 6, align="center",
        )
        subtitle_width = subtitle_box[2] - subtitle_box[0]
        subtitle_x = x0 + (x1 - x0 - subtitle_width) // 2
        subtitle_y = min(
            round(size[1] * 0.68),
            y + round(regular_font.size * 0.30),
        )
        draw.text(
            (subtitle_x, subtitle_y), subtitle_lines, font=subtitle_font,
            fill="#FFD84D", stroke_width=max(1, subtitle_font.size // 100),
            stroke_fill="#FFD84D",
        )
    return image


def render_local_text(
    base_path: Path,
    brief: object,
    output_directory: Path,
    *,
    delivery_size: tuple[int, int],
    person_frame: bytes | None = None,
    person_mask_provider: Callable[[bytes], bytes] | None = None,
    person_layer: Image.Image | None = None,
) -> list[Path]:
    """Render accurate Chinese locally onto the approved aspect and delivery canvas."""
    checked = validate_cover_brief(brief)
    if (
        type(delivery_size) is not tuple or len(delivery_size) != 2
        or any(type(value) is not int or value <= 0 or value > 8192 for value in delivery_size)
    ):
        raise _fail()
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        integrated_person = (
            checked["person_composite"]["method"] == "generated-reference-person"
        )
        if person_layer is not None and (person_frame is not None or integrated_person):
            raise _fail()
        person = (
            person_layer
            if person_layer is not None
            else _person_layer(person_frame, person_mask_provider)
            if person_frame is not None and not integrated_person
            else None
        )
        with Image.open(base_path) as source:
            source.load()
            outputs = []
            aspect = checked.get("output_aspect_ratio")
            specs = (
                (_ASPECT_OUTPUTS[aspect],)
                if aspect is not None
                else (
                    ("cover-3x4.png", (1080, 1440)),
                    ("cover-9x16.png", (1080, 1920)),
                )
            )
            for name, size in (*specs, ("cover-delivery-raster.png", delivery_size)):
                path = output_directory / name
                _render_one(source, checked, size, person).save(
                    path, format="PNG", optimize=False
                )
                outputs.append(path)
            return outputs
    except CoverError:
        raise
    except (OSError, ValueError):
        raise _fail() from None


def _output_records(
    directory: Path, job: state.JobState, expected_names: set[str],
) -> list[dict[str, object]]:
    if {path.name for path in directory.iterdir()} != expected_names:
        raise _fail()
    records = []
    for name in sorted(expected_names):
        path = directory / name
        source = _read_file(path)
        records.append({
            "path": f"{_cover_directory_name(job)}/{name}",
            "sha256": hashlib.sha256(source).hexdigest(),
            "bytes": len(source),
        })
    return records


def _records_match(directory: Path, records: list[dict[str, object]]) -> bool:
    try:
        expected = {Path(record["path"]).name: record for record in records}
        expected_names = set(expected)
        if (
            not directory.is_dir()
            or {path.name for path in directory.iterdir()} != expected_names
        ):
            return False
        return all(
            _identity(directory / name, record)["sha256"] == record["sha256"]
            for name, record in expected.items()
        )
    except (CoverError, OSError, KeyError, TypeError):
        return False


def _old_target_matches(job: state.JobState, target: Path) -> bool:
    lineage = job.stages["cover"].get("lineage")
    if type(lineage) is not list or not lineage:
        return False
    try:
        expected = {Path(record["path"]).name: record for record in lineage}
        if {path.name for path in target.iterdir()} != set(expected):
            return False
        parent = os.lstat(target)
        for name, record in expected.items():
            path = target / name
            status = os.lstat(path)
            source = _read_file(path)
            if (
                status.st_dev != record["device"] or status.st_ino != record["inode"]
                or parent.st_dev != record["parent_device"]
                or parent.st_ino != record["parent_inode"]
                or hashlib.sha256(source).hexdigest() != record["sha256"]
                or len(source) != record["bytes"]
            ):
                return False
        return True
    except (OSError, KeyError, TypeError, CoverError):
        return False


def _previous_cover_base(
    job: state.JobState, brief: dict[str, object],
) -> tuple[bytes, dict[str, object]]:
    target = job.job_dir / _cover_directory_name(job)
    if not _old_target_matches(job, target):
        raise _fail()
    lineage = job.stages["cover"]["lineage"]
    records = {
        Path(record["path"]).name: record
        for record in lineage
        if type(record) is dict and "path" in record
    }
    if "cover-base.png" not in records or "cover-brief.json" not in records:
        raise _fail()
    previous_brief_source, _brief_status, _brief_parent = _pinned_read(
        target / "cover-brief.json", 8 * 1024 * 1024
    )
    previous_brief = validate_cover_brief(_strict_json(previous_brief_source))
    previous_without_headline = copy.deepcopy(previous_brief)
    current_without_headline = copy.deepcopy(brief)
    previous_without_headline.pop("headline", None)
    current_without_headline.pop("headline", None)
    if _canonical(previous_without_headline) != _canonical(current_without_headline):
        raise _fail()
    base_record = records["cover-base.png"]
    base_source, status, parent = _pinned_read(
        target / "cover-base.png", openlux_images.MAX_IMAGE_BYTES
    )
    if (
        hashlib.sha256(base_source).hexdigest() != base_record["sha256"]
        or len(base_source) != base_record["bytes"]
        or status.st_dev != base_record["device"]
        or status.st_ino != base_record["inode"]
        or parent.st_dev != base_record["parent_device"]
        or parent.st_ino != base_record["parent_inode"]
    ):
        raise _fail()
    return base_source, {
        "path": f"{_cover_directory_name(job)}/cover-base.png",
        "sha256": base_record["sha256"],
        "bytes": base_record["bytes"],
    }


def _lineage_matches(directory: Path, lineage: object) -> bool:
    if type(lineage) is not list or not lineage:
        return False
    try:
        expected = {Path(record["path"]).name: record for record in lineage}
        if {path.name for path in directory.iterdir()} != set(expected):
            return False
        parent = os.lstat(directory)
        for name, record in expected.items():
            path = directory / name
            status = os.lstat(path)
            source = _read_file(path)
            if (
                status.st_dev != record["device"] or status.st_ino != record["inode"]
                or parent.st_dev != record["parent_device"]
                or parent.st_ino != record["parent_inode"]
                or hashlib.sha256(source).hexdigest() != record["sha256"]
                or len(source) != record["bytes"]
            ):
                return False
        return True
    except (OSError, KeyError, TypeError, CoverError):
        return False


def _artifacts_match(job: state.JobState, records: list[dict[str, object]]) -> bool:
    return job.stages["cover"].get("artifacts") == records


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
    target.version = source.version


def _checkpoint(name: str) -> None:
    if os.environ.get("HD_COVER_CRASH_CHECKPOINT") == name:
        os._exit(86)


def _write_transaction(job: state.JobState, payload: dict[str, object]) -> None:
    marker = job.job_dir / _TRANSACTION_NAME
    if os.path.lexists(marker):
        raise _fail()
    _write_new(marker, _canonical(payload))
    _fsync_directory(job.job_dir)


def _load_transaction(job: state.JobState) -> dict[str, object] | None:
    marker = job.job_dir / _TRANSACTION_NAME
    if not os.path.lexists(marker):
        return None
    try:
        payload = _strict_json(_read_file(marker, 2 * 1024 * 1024))
    except (OSError, UnicodeError, ValueError):
        raise _fail() from None
    keys = {
        "version", "job_id", "base_revision", "workflow_sha256",
        "workflow_bytes", "stage", "target", "backup", "had_target",
        "new_records", "old_lineage",
    }
    if (
        type(payload) is not dict or set(payload) != keys
        or payload["version"] != 1 or type(payload["version"]) is not int
        or payload["job_id"] != job.job_id
        or type(payload["base_revision"]) is not int
        or type(payload["workflow_sha256"]) is not str
        or _SHA.fullmatch(payload["workflow_sha256"]) is None
        or type(payload["workflow_bytes"]) is not int
        or type(payload["had_target"]) is not bool
        or payload["target"] != _cover_directory_name(job)
        or type(payload["stage"]) is not str
        or not payload["stage"].startswith(".07-cover.stage-")
        or "/" in payload["stage"] or "\\" in payload["stage"]
        or type(payload["backup"]) is not str
        or not payload["backup"].startswith(".07-cover.backup-")
        or "/" in payload["backup"] or "\\" in payload["backup"]
        or type(payload["new_records"]) is not list
        or type(payload["old_lineage"]) is not list
    ):
        raise _fail()
    return payload


def _remove_marker(job_dir: Path, payload: dict[str, object]) -> None:
    marker = job_dir / _TRANSACTION_NAME
    _retire_verified_file(marker, _canonical(payload))


def _atomic_noreplace(source: Path, destination: Path) -> bool:
    if source.parent != destination.parent:
        raise _fail()
    library = ctypes.CDLL(None, use_errno=True)
    if hasattr(library, "renameatx_np"):
        operation = library.renameatx_np
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = operation(-2, os.fsencode(source), -2, os.fsencode(destination), 0x4)
    elif hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = operation(-100, os.fsencode(source), -100, os.fsencode(destination), 0x1)
    else:
        raise _fail()
    if result == 0:
        return True
    if ctypes.get_errno() in {errno.EEXIST, errno.ENOTEMPTY}:
        return False
    raise _fail()


def _retire_verified_directory(
    path: Path,
    verifier: Callable[[Path], bool],
) -> None:
    if not os.path.lexists(path):
        return
    before = os.lstat(path)
    if not stat.S_ISDIR(before.st_mode) or not verifier(path):
        raise _fail()
    retired = path.parent / f".07-cover.retained-{secrets.token_hex(16)}"
    if not _atomic_noreplace(path, retired):
        raise _fail()
    moved = os.lstat(retired)
    if not os.path.samestat(before, moved) or not verifier(retired):
        if not os.path.lexists(path):
            if not _atomic_noreplace(retired, path):
                raise _fail()
        raise _fail()
    # The random retirement name is created only after identity verification;
    # cleanup never follows the public/transaction name that can be exchanged.
    shutil.rmtree(retired)
    _fsync_directory(path.parent)


def _retire_verified_file(path: Path, expected: bytes) -> None:
    if not os.path.lexists(path):
        return
    source, before, _parent = _pinned_read(path, max(len(expected), 1))
    if source != expected:
        raise _fail()
    retired = path.parent / f".07-cover.retained-{secrets.token_hex(16)}"
    if not _atomic_noreplace(path, retired):
        raise _fail()
    moved_source, moved, _moved_parent = _pinned_read(retired, max(len(expected), 1))
    if not os.path.samestat(before, moved) or moved_source != expected:
        if not os.path.lexists(path):
            if not _atomic_noreplace(retired, path):
                raise _fail()
        raise _fail()
    retired.unlink()
    _fsync_directory(path.parent)


def _remove_new_directory(path: Path, records: list[dict[str, object]]) -> None:
    _retire_verified_directory(path, lambda candidate: _records_match(candidate, records))


def _remove_old_directory(path: Path, lineage: object) -> None:
    _retire_verified_directory(path, lambda candidate: _lineage_matches(candidate, lineage))


def _finish_transaction(
    job: state.JobState, payload: dict[str, object]
) -> Path | None:
    target = job.job_dir / _cover_directory_name(job)
    stage = job.job_dir / payload["stage"]
    backup = job.job_dir / payload["backup"]
    records = payload["new_records"]
    current = state.load_job(job.job_dir)
    _synchronize_job(job, current)
    status = job.stages["cover"]["status"]
    if status in {"ready_for_review", "approved"}:
        if not _artifacts_match(job, records) or not _records_match(target, records):
            raise _fail()
        _remove_new_directory(stage, records)
        _remove_old_directory(backup, payload["old_lineage"])
        _clear_ai_marker_for_transaction(job, payload)
        _remove_marker(job.job_dir, payload)
        return target / "cover-delivery-raster.png"
    if status not in {"pending", "needs_revision"}:
        raise _fail()
    base_matches = (
        job.revision == payload["base_revision"]
        and job.expected_sha256 == payload["workflow_sha256"]
        and job.expected_bytes == payload["workflow_bytes"]
    )
    target_is_new = _records_match(target, records)
    if not base_matches:
        if target_is_new:
            if payload["had_target"]:
                if not _lineage_matches(backup, payload["old_lineage"]):
                    raise _fail()
                _remove_new_directory(target, records)
                os.rename(backup, target)
            else:
                _remove_new_directory(target, records)
        elif payload["had_target"]:
            if os.path.lexists(target):
                if not _lineage_matches(target, payload["old_lineage"]):
                    raise _fail()
            else:
                if not _lineage_matches(backup, payload["old_lineage"]):
                    raise _fail()
                os.rename(backup, target)
                _fsync_directory(job.job_dir)
        elif os.path.lexists(target):
            raise _fail()
        _remove_new_directory(stage, records)
        _remove_old_directory(backup, payload["old_lineage"])
        _clear_ai_marker_for_transaction(job, payload)
        _remove_marker(job.job_dir, payload)
        _fsync_directory(job.job_dir)
        return None
    if not target_is_new:
        if not _records_match(stage, records):
            raise _fail()
        if payload["had_target"]:
            if os.path.lexists(backup):
                if not _lineage_matches(backup, payload["old_lineage"]):
                    raise _fail()
                if os.path.lexists(target):
                    raise _fail()
            else:
                if not _lineage_matches(target, payload["old_lineage"]):
                    raise _fail()
                os.rename(target, backup)
                _fsync_directory(job.job_dir)
                _checkpoint("after-backup")
            os.rename(stage, target)
        else:
            if os.path.lexists(target):
                raise _fail()
            os.rename(stage, target)
        _fsync_directory(job.job_dir)
    if not _records_match(target, records):
        raise _fail()
    _checkpoint("after-install")
    try:
        state.mark_ready(
            job, "cover", [target / Path(item["path"]).name for item in records]
        )
    except BaseException as error:
        try:
            refreshed = state.load_job(job.job_dir)
            committed = (
                refreshed.stages["cover"]["status"] in {"ready_for_review", "approved"}
                and _artifacts_match(refreshed, records)
                and _records_match(target, records)
            )
        except BaseException:
            committed = False
        if committed:
            _synchronize_job(job, refreshed)
        else:
            if not _records_match(target, records):
                raise _fail() from error
            _remove_new_directory(target, records)
            if payload["had_target"]:
                if not _lineage_matches(backup, payload["old_lineage"]):
                    raise _fail() from error
                os.rename(backup, target)
            _remove_new_directory(stage, records)
            _clear_ai_marker_for_transaction(job, payload)
            _remove_marker(job.job_dir, payload)
            _fsync_directory(job.job_dir)
            raise
    if not _artifacts_match(job, records) or not _records_match(target, records):
        raise _fail()
    _checkpoint("after-workflow")
    _remove_new_directory(stage, records)
    _remove_old_directory(backup, payload["old_lineage"])
    _clear_ai_marker_for_transaction(job, payload)
    _remove_marker(job.job_dir, payload)
    _fsync_directory(job.job_dir)
    return target / "cover-delivery-raster.png"


def _publish(
    job: state.JobState,
    stage: Path,
    records: list[dict[str, object]],
) -> Path:
    target = job.job_dir / _cover_directory_name(job)
    backup = job.job_dir / f".07-cover.backup-{secrets.token_hex(16)}"
    had_target = os.path.lexists(target)
    if (
        had_target
        and job.version == 2
        and job.stages["cover"]["status"] == "pending"
        and job.stages["cover"].get("lineage", []) == []
    ):
        try:
            target_status = os.lstat(target)
            if not stat.S_ISDIR(target_status.st_mode) or any(target.iterdir()):
                raise _fail()
            os.rmdir(target)
            _fsync_directory(job.job_dir)
            had_target = False
        except CoverError:
            raise
        except OSError:
            raise _fail() from None
    if had_target and not _old_target_matches(job, target):
        raise _fail()
    if job.expected_sha256 is None or job.expected_bytes is None:
        raise _fail()
    payload = {
        "version": 1,
        "job_id": job.job_id,
        "base_revision": job.revision,
        "workflow_sha256": job.expected_sha256,
        "workflow_bytes": job.expected_bytes,
        "stage": stage.name,
        "target": target.name,
        "backup": backup.name,
        "had_target": had_target,
        "new_records": records,
        "old_lineage": copy.deepcopy(job.stages["cover"].get("lineage", [])),
    }
    _write_transaction(job, payload)
    _checkpoint("prepared")
    return _finish_transaction(job, payload)


def _block_after_ai(job: state.JobState) -> None:
    try:
        state.block(job, "cover", "cover image generation failed", 1)
    except BaseException:
        raise _fail() from None


def review_cover(job: state.JobState) -> dict[str, object]:
    """Validate and locate existing review images without rendering or approval."""
    from . import qa_delivery_v2

    job = state.load_job(job.job_dir)
    if job.version != 2:
        raise CoverError("cover review requires full-v2")
    try:
        sources = qa_delivery_v2._validated_cover_sources(job, for_review=True)
        def read_bound(path: Path) -> bytes:
            data = _read_file(path)
            record = {"path": path.relative_to(job.job_dir).as_posix(),
                      "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if job.stages["cover"]["artifacts"].count(record) != 1:
                raise CoverError("cover review snapshot changed")
            return data

        images = {}
        image_paths = {"final": sources["cover/cover-delivery-raster.png"]}
        for name, path in image_paths.items():
            data = read_bound(path)
            images[name] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "mime_type": "image/png",
                            "base64": base64.b64encode(data).decode("ascii")}
        if not _records_match(job.job_dir / "04-cover", job.stages["cover"]["artifacts"]):
            raise CoverError("cover artifacts changed during review")
        current = state.load_job(job.job_dir)
        if current.revision != job.revision or current.stages != job.stages:
            raise CoverError("cover workflow changed during review")
    except (qa_delivery_v2.DeliveryV2Error, OSError, ValueError) as exc:
        raise CoverError("cover review is unavailable") from exc
    return {
        "stage": "cover", "job_id": job.job_id, "revision": job.revision,
        "final_image": str(sources["cover/cover-delivery-raster.png"]),
        "images": images,
        "review_instruction": "仅展示 images.final 内已校验的完整封面图片字节，不重新打开路径；人工检查标题、主题动作和人物辨识度，不自动批准。",
    }


def prepare_cover(
    job: state.JobState,
    *,
    brief: object | None = None,
    face_candidates: Iterable[dict[str, object] | float] | None = None,
    frame_reader: Callable[[Path, float], bytes] | None = None,
    quality_probe: Callable[[bytes], dict[str, object]] | None = None,
    person_mask_provider: Callable[[bytes], bytes] | None = None,
    generated_scene: Path | None = None,
    generated_scene_prompt: str | None = None,
    approved_preview: Path | None = None,
    approved_preview_sha256: str | None = None,
    approved_preview_prompt: str | None = None,
    approved_base: Path | None = None,
    headline_highlight_lines: list[str] | None = None,
    headline_conclusion_lines: list[str] | None = None,
    person_protection_boxes: list[list[float]] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: Callable[..., dict[str, object]] | None = None,
) -> Path:
    """Build one atomic cover generation and stop at ready-for-review."""
    if (approved_preview is None) != (approved_preview_sha256 is None):
        raise CoverError("approved preview requires its exact SHA-256")
    if approved_base is not None and approved_preview is None:
        raise CoverError("approved base requires an approved preview")
    if approved_preview_prompt is not None and (
        approved_preview is None or approved_base is not None
    ):
        raise CoverError("complete-image approval requires only the approved preview")
    if approved_preview is not None and (
        job.version != 2
        or headline_highlight_lines is not None
        or headline_conclusion_lines is not None
    ):
        raise CoverError("approved preview requires an unchanged full-v2 direction")
    direction_record: dict[str, object] | None = None
    if job.version == 2:
        if brief is not None:
            raise CoverError(
                "full-v2 cover uses approved cover_direction; brief is not accepted"
            )
        if job.stages.get("cover_direction", {}).get("status") != "approved":
            raise CoverError("cover_direction must be approved")
        try:
            from edit.hd.tools import cover_direction

            direction_record = cover_direction.load_approved_cover_direction(job)
        except cover_direction.CoverDirectionError as exc:
            raise CoverError(str(exc)) from exc
        resolved_brief: object = _brief_from_approved_direction(
            direction_record,
            generated_scene=generated_scene,
            generated_scene_prompt=generated_scene_prompt,
            approved_preview_prompt=approved_preview_prompt,
            headline_highlight_lines=headline_highlight_lines,
            headline_conclusion_lines=headline_conclusion_lines,
            person_protection_boxes=person_protection_boxes,
        )
    else:
        if brief is None:
            raise CoverError("legacy cover requires brief")
        if (
            headline_highlight_lines is not None
            or headline_conclusion_lines is not None
            or person_protection_boxes is not None
        ):
            raise CoverError("legacy cover does not accept headline line overrides")
        resolved_brief = brief
    lock_descriptor: int | None = None
    stage: Path | None = None
    ai_claimed = False
    stage_guard: dict[str, object] | None = None
    ai_marker_payload: dict[str, object] | None = None
    try:
        lock_descriptor = _acquire_lock(job.job_dir)
        pending = _load_transaction(job)
        if pending is not None:
            recovered = _finish_transaction(job, pending)
            if recovered is not None:
                return recovered
        abandoned = _load_ai_marker(job)
        if abandoned is not None:
            ledger_claimed = _ledger_contains(
                job.job_dir, str(abandoned["generation_id"])
            )
            if abandoned["claimed"] and not ledger_claimed:
                raise _fail()
            same_generation = (
                abandoned["base_revision"] == job.revision
                and abandoned["workflow_sha256"] == job.expected_sha256
            )
            if ledger_claimed and same_generation:
                _block_after_ai(job)
                try:
                    _remove_partial_stage(job, abandoned)
                except CoverError:
                    pass
                _remove_ai_marker(job.job_dir, abandoned)
                raise _fail()
            try:
                _remove_partial_stage(job, abandoned)
            except CoverError:
                pass
            _remove_ai_marker(job.job_dir, abandoned)
        try:
            state.require_runnable(job, "cover")
        except state.WorkflowError:
            raise _fail() from None
        cover_stage = job.stages["cover"]
        fallback = (
            cover_stage["status"] == "needs_revision"
            and cover_stage["reason"] == _FALLBACK_REASON
        )
        if approved_preview is not None and fallback:
            raise _fail()
        if (
            cover_stage["status"] == "needs_revision"
            and not fallback
            and "alternative" in str(cover_stage["reason"])
        ):
            raise _fail()
        core_bindings = _source_bindings(job)
        bindings = copy.deepcopy(core_bindings)
        workflow = _workflow_binding(job)
        if job.version == 2:
            if direction_record is None:
                raise _fail()
            aspect = direction_record["direction"]["output_aspect_ratio"]
            if aspect not in _ASPECT_OUTPUTS:
                raise _fail()
            _aspect_name, (width, height) = _ASPECT_OUTPUTS[aspect]
            reference = direction_record["direction"]["person_reference"]
            reference_source = _read_file(
                job.job_dir / reference["path"], openlux_images.MAX_IMAGE_BYTES
            )
            if reference["source"] == "current-aroll-video":
                selected = {
                    "source": reference["source"],
                    "timestamp": reference["timestamp"],
                    "sha256": reference["sha256"],
                    "bytes": reference_source,
                }
            elif reference["source"] == "user-material":
                selected = {
                    "source": reference["source"],
                    "material_id": reference["material_id"],
                    "sha256": reference["sha256"],
                    "bytes": reference_source,
                }
                bindings["person_reference"] = _identity(
                    job.job_dir / reference["path"],
                    {
                        "path": reference["path"],
                        "sha256": reference["sha256"],
                        "bytes": reference["bytes"],
                    },
                )
            else:
                raise _fail()
        else:
            visual_path, _visual_record = _artifact(
                job, "visual_direction", "04-visual-direction", "visual-plan.json"
            )
            visual_payload = _strict_json(
                _read_file(visual_path, 32 * 1024 * 1024)
            )
            if (
                type(visual_payload) is not dict
                or type(visual_payload.get("canvas")) is not dict
            ):
                raise _fail()
            canvas = visual_payload["canvas"]
            if set(canvas) != {"width", "height", "fps"}:
                raise _fail()
            width, height = canvas["width"], canvas["height"]
            if (
                type(width) is not int
                or type(height) is not int
                or not 1 <= width <= 8192
                or not 1 <= height <= 8192
            ):
                raise _fail()
            selected = select_face_frame(
                job.root / job.inputs["video"]["path"],
                face_candidates,
                frame_reader=frame_reader,
                quality_probe=quality_probe,
            )
        checked = validate_cover_brief(
            resolved_brief, expected_face_sha256=selected["sha256"],
            expected_face_timestamp=selected.get("timestamp"),
        )
        approved_preview_source: bytes | None = None
        if approved_preview is not None:
            approved_preview_source, bindings["approved_preview"] = (
                _approved_png_source(
                    job, approved_preview,
                    expected_sha256=approved_preview_sha256,
                    expected_size=(width, height),
                )
            )
        reference_mode = (
            checked["base_generation"] == "reference_person_scene_no_text"
        )
        full_image_mode = checked["base_generation"] == "approved_full_image"
        if full_image_mode and approved_preview_source is None:
            raise _fail()
        scene_source: bytes | None = None
        approved_base_source: bytes | None = None
        if reference_mode:
            if approved_base is not None:
                raise _fail()
            scene_source, bindings["reference_scene"] = _reference_scene_source(
                job, generated_scene, checked["reference_scene"]
            )
        elif generated_scene is not None:
            raise _fail()
        elif approved_preview_source is not None and not full_image_mode:
            if approved_base is None:
                raise _fail()
            approved_base_source, bindings["approved_base"] = (
                _approved_png_source(job, approved_base)
            )
        if approved_preview_source is not None and (
            approved_preview_source == scene_source
            or approved_preview_source == approved_base_source
        ):
            raise _fail()
        reused_base_source: bytes | None = None
        title_only_revision = (
            job.version == 2
            and (
                headline_highlight_lines is not None
                or headline_conclusion_lines is not None
            )
            and cover_stage["status"] == "needs_revision"
            and bool(cover_stage.get("lineage"))
            and not fallback
            and not reference_mode
            and approved_preview_source is None
        )
        if title_only_revision:
            reused_base_source, bindings["reused_cover_base"] = (
                _previous_cover_base(job, checked)
            )
        prepared_person = None
        if not reference_mode and approved_preview_source is None:
            prepared_person = _person_layer(
                selected["bytes"], person_mask_provider
            )
            if (
                checked.get("output_aspect_ratio") == "9:16"
                and checked["style_id"] == "style-01"
            ):
                _render_one(
                    Image.new("RGB", (width, height), "#080C16"),
                    checked, (width, height), prepared_person,
                )
        generation_id = _generation_id(job, workflow, bindings, checked)
        if (
            not fallback and not reference_mode and reused_base_source is None
            and approved_preview_source is None
            and _ledger_contains(job.job_dir, generation_id)
        ):
            _block_after_ai(job)
            raise _fail()
        stage = job.job_dir / f".07-cover.stage-{secrets.token_hex(16)}"
        stage.mkdir(mode=0o700)
        _write_new(stage / "cover-brief.json", _canonical(checked))
        stage_status = os.lstat(stage)
        brief_source, brief_status, _brief_parent = _pinned_read(
            stage / "cover-brief.json"
        )
        stage_guard = {
            "stage": stage.name,
            "stage_device": stage_status.st_dev,
            "stage_inode": stage_status.st_ino,
            "brief_sha256": hashlib.sha256(brief_source).hexdigest(),
            "brief_bytes": len(brief_source),
            "brief_device": brief_status.st_dev,
            "brief_inode": brief_status.st_ino,
        }
        base = stage / "cover-base.png"
        mode = (
            "approved-full-image" if full_image_mode else
            "approved-preview-reuse" if approved_preview_source is not None else
            "title-only-base-reuse" if reused_base_source is not None else
            "aroll-code-cover" if fallback else
            "reference-scene-import" if reference_mode else
            "openlux"
        )
        if full_image_mode:
            pass
        elif reused_base_source is not None:
            _write_new(base, reused_base_source)
        elif approved_base_source is not None:
            _write_new(base, approved_base_source)
        elif fallback:
            with Image.open(io.BytesIO(selected["bytes"])) as image:
                ImageOps.fit(
                    image.convert("RGB"), (1024, 1536), method=Image.Resampling.LANCZOS
                ).save(base, format="PNG")
        elif reference_mode:
            if scene_source is None:
                raise _fail()
            _write_new(base, scene_source)
        else:
            if type(api_key) is not str or not api_key.strip():
                raise _fail()
            resolved_base = base_url or openlux_images.DEFAULT_BASE_URL
            if type(resolved_base) is not str or not resolved_base:
                raise _fail()
            ai_marker_payload = {
                "version": 1,
                "job_id": job.job_id,
                "generation_id": generation_id,
                "base_revision": job.revision,
                "workflow_sha256": str(job.expected_sha256),
                "claimed": True,
                **stage_guard,
            }
            _claim_generation(job.job_dir, generation_id)
            ai_claimed = True
            _write_ai_marker(job, ai_marker_payload)
            _checkpoint("after-claim")
            request = provider or openlux_images.request_image
            try:
                response = request(
                    checked["base_prompt"], api_key=api_key.strip(),
                    base_url=resolved_base,
                )
                generated = render_cover_base(response, stage / "cover-base")
                if generated != base:
                    os.rename(generated, base)
                _fsync_directory(stage)
                _checkpoint("after-base")
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                _block_after_ai(job)
                raise _fail() from None
        if approved_preview_source is not None:
            aspect_name = _ASPECT_OUTPUTS[checked["output_aspect_ratio"]][0]
            rendered = [stage / aspect_name, stage / "cover-delivery-raster.png"]
            for path in rendered:
                _write_new(path, approved_preview_source)
        else:
            rendered = render_local_text(
                base, checked, stage, delivery_size=(width, height),
                person_layer=prepared_person,
            )
        _fsync_directory(stage)
        _checkpoint("after-local-render")
        preliminary = []
        public_directory = _cover_directory_name(job)
        preliminary_names = [
            "cover-brief.json",
            *([] if full_image_mode else ["cover-base.png"]),
            *(path.name for path in rendered),
        ]
        for name in preliminary_names:
            source = _read_file(stage / name)
            preliminary.append({
                "path": f"{public_directory}/{name}",
                "sha256": hashlib.sha256(source).hexdigest(),
                "bytes": len(source),
            })
        report = {
            "version": 3,
            "generator": checked["generator"],
            "generation_id": generation_id,
            "mode": mode,
            "base_reused": reused_base_source is not None,
            "base_generation": checked["base_generation"],
            "output_aspect_ratio": checked.get("output_aspect_ratio"),
            "direction_sha256": (
                direction_record["direction_sha256"]
                if direction_record is not None
                else None
            ),
            "reference_sha256": selected["sha256"],
            "model": (
                "approved-preview-pixels" if approved_preview_source is not None
                else "local-base-reuse" if reused_base_source is not None
                else "local-approved-reference" if fallback or reference_mode
                else "openlux-images"
            ),
            "prompt": checked["base_prompt"],
            "workflow": workflow,
            "source_bindings": bindings,
            "face_frame": {
                key: selected[key]
                for key in ("source", "material_id", "timestamp", "sha256")
                if key in selected
            },
            "person_composite": {
                **checked["person_composite"],
                **({"method": "approved-preview-integrated"}
                   if approved_preview_source is not None else {}),
                "frame_sha256": selected["sha256"],
                **(
                    {
                        "video_binding": bindings["video"],
                        "frame_timestamp": selected["timestamp"],
                    }
                    if "timestamp" in selected
                    else {
                        "reference_binding": bindings["person_reference"],
                        "material_id": selected["material_id"],
                    }
                ),
            },
            "alternative_evidence": (
                {
                    "reason": _FALLBACK_REASON,
                    "workflow_revision": workflow["revision"],
                    "workflow_sha256": workflow["sha256"],
                }
                if fallback else None
            ),
            "canvas": {"width": width, "height": height},
            "artifacts": preliminary,
            "output_sha256": {
                Path(item["path"]).name: item["sha256"] for item in preliminary
            },
        }
        _write_new(stage / "cover-report.json", _canonical(report))
        _fsync_directory(stage)
        expected_names = {*preliminary_names, "cover-report.json"}
        references = []
        if selected["source"] == "user-material":
            # `selected["sha256"]` is the normalized person-reference PNG
            # used by the renderer; the material-usage receipt must bind the
            # original active user material identity instead.
            person_reference = (
                direction_record["direction"]["person_reference"]
                if direction_record is not None
                else None
            )
            material_sha256 = (
                person_reference["material_sha256"]
                if isinstance(person_reference, dict)
                else selected["sha256"]
            )
            references.append(
                {
                    "material_id": selected["material_id"],
                    "material_sha256": material_sha256,
                    "consumer_kind": "cover_render",
                    "consumer_id": "cover",
                    "binding_path": "/face_frame/material_id",
                    "artifact_paths": [
                        f"{public_directory}/{name}"
                        for name in sorted(expected_names)
                        if name != "cover-brief.json"
                    ],
                }
            )
        material_usage.write_staged_receipt(
            job,
            "cover",
            stage,
            job.job_dir / public_directory,
            sorted(expected_names),
            producer="edit.hd.tools.cover",
            producer_version="1",
            stage_input_records=material_usage.current_stage_input_records(
                job, "cover"
            ),
            references=references,
        )
        expected_names.add("material-usage.json")
        records = _output_records(stage, job, expected_names)
        _verify_bindings(job, workflow, core_bindings)
        if reference_mode:
            current_scene = _identity(generated_scene, bindings["reference_scene"])
            if current_scene != bindings["reference_scene"]:
                raise _fail()
        if approved_preview_source is not None:
            if _identity(approved_preview, bindings["approved_preview"]) != bindings["approved_preview"]:
                raise _fail()
            if approved_base_source is not None and (
                _identity(approved_base, bindings["approved_base"]) != bindings["approved_base"]
            ):
                raise _fail()
        output = _publish(job, stage, records)
        stage = None
        return output
    except (KeyboardInterrupt, SystemExit):
        raise
    except CoverError:
        if (
            ai_claimed
            and not os.path.lexists(job.job_dir / _TRANSACTION_NAME)
            and job.stages["cover"]["status"] not in {"blocked", "ready_for_review", "approved"}
        ):
            _block_after_ai(job)
        raise
    except BaseException:
        if (
            ai_claimed
            and not os.path.lexists(job.job_dir / _TRANSACTION_NAME)
            and job.stages["cover"]["status"] not in {"blocked", "ready_for_review", "approved"}
        ):
            _block_after_ai(job)
        raise _fail() from None
    finally:
        if (
            stage is not None and stage.exists()
            and not os.path.lexists(job.job_dir / _TRANSACTION_NAME)
        ):
            try:
                if stage_guard is None:
                    raise _fail()
                _remove_partial_stage(job, stage_guard)
                if ai_marker_payload is not None:
                    _remove_ai_marker(job.job_dir, ai_marker_payload)
            except (CoverError, OSError):
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

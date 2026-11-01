#!/usr/bin/env python3
"""Build the reproducible 30-second V5 visual plan from the V4 plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Sequence


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from style_tokens import (  # noqa: E402
    FPS,
    HEIGHT,
    PALETTE,
    SUBTITLE_SIZE_RANGE,
    TITLE_SIZE_RANGE,
    TRANSITION_FRAMES,
    WIDTH,
    StyleContractError,
    validate_scene_style,
)


TOTAL_SECONDS = 30
TOTAL_FRAMES = FPS * TOTAL_SECONDS
CLEAN_BASE_SHA256 = "fa61c402aeba0133d40735e4cb1cf0911b5a9ed8d40ce9c2857226d1f8e76260"

SCENE_CONTRACT = (
    ("v5-001", 0, 4, "full_speaker_minimal", None, "none", 0),
    ("v5-002", 4, 8, "asset_avatar", "v5-concept-002", "circle_expand", 12),
    ("v5-003", 8, 12, "asset_cutout_edge", "v5-concept-003", "color_wipe_right", 12),
    ("v5-004", 12, 16, "full_speaker_emphasis", None, "color_wipe_left", 12),
    ("v5-005", 16, 20, "official_evidence_full", "v5-official-005", "circle_expand", 12),
    ("v5-006", 20, 24, "top_asset_bottom_speaker", "v5-concept-006", "color_wipe_up", 12),
    ("v5-007", 24, 28, "asset_cutout_edge", "v5-concept-007", "color_wipe_left", 12),
    ("v5-008", 28, 30, "full_speaker_emphasis", None, "color_wipe_right", 12),
)

PRIMARY_ACCENTS = (
    PALETTE["cobalt"],
    PALETTE["yellow"],
    PALETTE["coral"],
    PALETTE["mint"],
    PALETTE["cobalt"],
    PALETTE["yellow"],
    PALETTE["coral"],
    PALETTE["mint"],
)

ASSET_CONTRACTS = [
    {"id": "v5-concept-002", "kind": "concept", "key": "ability_threshold", "label": "能力阈值"},
    {"id": "v5-concept-003", "kind": "concept", "key": "moving_standard", "label": "标准迁移"},
    {"id": "v5-official-005", "kind": "official_evidence", "key": "official_evidence", "label": "官方证据"},
    {"id": "v5-concept-006", "kind": "concept", "key": "three_layer_structure", "label": "三层结构"},
    {"id": "v5-concept-007", "kind": "concept", "key": "learning_paths", "label": "学习路径"},
]

PLAN_FIELDS = {
    "version",
    "duration",
    "fps",
    "width",
    "height",
    "clean_base_sha256",
    "style_contract",
    "asset_contracts",
    "scenes",
}

_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"file:/+[^\s,，。；;（）()\[\]{}<>《》\"'“”‘’]+"
    r"|[A-Za-z]:[\\/][^\s,，。；;（）()\[\]{}<>《》\"'“”‘’]+"
    r"|\\\\[^\s,，。；;（）()\[\]{}<>《》\"'“”‘’]+"
    r"|(?<!/)/(?!/)[^\s,，。；;（）()\[\]{}<>《》\"'“”‘’]+"
    r")",
    re.IGNORECASE,
)


class VisualPlanError(ValueError):
    """A clean, user-facing V5 visual-plan failure."""


def _reject_nonfinite(value: str) -> None:
    raise VisualPlanError(f"non-finite JSON value is not allowed: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VisualPlanError(f"duplicate JSON key is not allowed: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(
                source,
                parse_constant=_reject_nonfinite,
                object_pairs_hook=_reject_duplicate_keys,
            )
    except VisualPlanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VisualPlanError(f"cannot read valid JSON from {path}: {error}") from error


def _validate_source(source: object) -> list[dict]:
    if not isinstance(source, dict):
        raise VisualPlanError("source plan must be a JSON object")
    scenes = source.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < len(SCENE_CONTRACT):
        raise VisualPlanError("source plan must contain at least 8 scenes")
    required_text = ("spoken_text", "chapter", "semantic_reason", "source_scene_id")
    for index, scene in enumerate(scenes[:8], start=1):
        if not isinstance(scene, dict):
            raise VisualPlanError(f"source scene {index} must be a JSON object")
        for field in required_text:
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise VisualPlanError(f"source scene {index} {field} must be non-empty text")
    return scenes


def _style_contract() -> dict:
    return {
        "palette": dict(PALETTE),
        "title_size_range": [TITLE_SIZE_RANGE.start, TITLE_SIZE_RANGE.stop - 1],
        "subtitle_size_range": [
            SUBTITLE_SIZE_RANGE.start,
            SUBTITLE_SIZE_RANGE.stop - 1,
        ],
        "transition_frames": TRANSITION_FRAMES,
    }


def _contains_forbidden_string(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden_string(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_string(item) for item in value)
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/").casefold()
    if "blurred_person_background" in normalized:
        return True
    if _PATH_TOKEN.search(value):
        return True
    if normalized.startswith("file:"):
        return True
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(value).is_absolute():
        return True
    return (
        "edit/v3/" in normalized or "edit/v4/" in normalized
    ) and normalized.endswith(
        (".mp4", ".mov", ".mkv", ".webm")
    )


def validate_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise VisualPlanError("plan must be a JSON object")
    missing = PLAN_FIELDS - plan.keys()
    extra = plan.keys() - PLAN_FIELDS
    if missing:
        raise VisualPlanError(f"missing plan field: {sorted(missing)[0]}")
    if extra:
        raise VisualPlanError(f"unsupported plan field: {sorted(extra)[0]}")
    if plan["version"] != 5 or plan["duration"] != TOTAL_SECONDS or plan["fps"] != FPS:
        raise VisualPlanError("plan must be V5 and exactly 30 seconds at 24 fps")
    if (
        type(plan["width"]) is not int
        or type(plan["height"]) is not int
        or plan["width"] != WIDTH
        or plan["height"] != HEIGHT
    ):
        raise VisualPlanError(f"canvas must be exactly {WIDTH}x{HEIGHT} integer pixels")
    if plan["clean_base_sha256"] != CLEAN_BASE_SHA256:
        raise VisualPlanError("clean_base_sha256 does not match the approved clean base")
    if plan["style_contract"] != _style_contract():
        raise VisualPlanError("style_contract does not match the approved V5 tokens")
    if plan["asset_contracts"] != ASSET_CONTRACTS:
        raise VisualPlanError("asset_contracts do not match the approved V5 mapping")
    if _contains_forbidden_string(plan):
        raise VisualPlanError("plan contains a forbidden path or legacy visual value")

    scenes = plan["scenes"]
    if not isinstance(scenes, list) or len(scenes) != len(SCENE_CONTRACT):
        raise VisualPlanError("plan must contain exactly 8 scenes")
    ids: set[str] = set()
    previous_end = 0
    previous_frame = 0
    for index, (scene, contract) in enumerate(zip(scenes, SCENE_CONTRACT)):
        try:
            validate_scene_style(scene)
        except StyleContractError as error:
            raise VisualPlanError(f"scene {index + 1}: {error}") from error
        if scene["id"] in ids:
            raise VisualPlanError(f"duplicate scene id: {scene['id']}")
        ids.add(scene["id"])
        scene_id, start, end, layout, asset_id, transition, transition_frames = contract
        actual = (
            scene["id"],
            scene["start"],
            scene["end"],
            scene["editorial_layout"],
            scene["asset_id"],
            scene["transition"],
            scene["transition_frames"],
        )
        if actual != (scene_id, start, end, layout, asset_id, transition, transition_frames):
            raise VisualPlanError(f"scene {index + 1} does not match the approved V5 contract")
        if scene["start"] != previous_end or scene["start_frame"] != previous_frame:
            raise VisualPlanError("scene timeline must be contiguous from zero")
        previous_end = scene["end"]
        previous_frame = scene["end_frame"]
    if previous_end != TOTAL_SECONDS or previous_frame != TOTAL_FRAMES:
        raise VisualPlanError("scene timeline must end at exactly 30 seconds and 720 frames")
    return plan


def build_plan(source_path: Path | str) -> dict:
    source_path = Path(source_path)
    source = _load_json(source_path)
    source_scenes = _validate_source(source)
    scenes = []
    for index, (source_scene, contract) in enumerate(zip(source_scenes, SCENE_CONTRACT)):
        scene_id, start, end, layout, asset_id, transition, transition_frames = contract
        scenes.append(
            {
                "id": scene_id,
                "chapter": source_scene["chapter"],
                "spoken_text": source_scene["spoken_text"],
                "semantic_reason": source_scene["semantic_reason"],
                "source_scene_id": source_scene["source_scene_id"],
                "start": start,
                "end": end,
                "start_frame": start * FPS,
                "end_frame": end * FPS,
                "editorial_layout": layout,
                "asset_id": asset_id,
                "background_source": "clean_base",
                "person_dynamic": True,
                "transition": transition,
                "transition_frames": transition_frames,
                "primary_accent": PRIMARY_ACCENTS[index],
                "secondary_accent": None,
            }
        )
    plan = {
        "version": 5,
        "duration": TOTAL_SECONDS,
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "clean_base_sha256": CLEAN_BASE_SHA256,
        "style_contract": _style_contract(),
        "asset_contracts": [dict(asset) for asset in ASSET_CONTRACTS],
        "scenes": scenes,
    }
    return validate_plan(plan)


def _has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    platform_aliases = (
        {Path("/tmp"), Path("/var")} if sys.platform == "darwin" else set()
    )
    for component in (*reversed(absolute.parents), absolute):
        if component == Path(absolute.anchor) or component in platform_aliases:
            continue
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise VisualPlanError(
                f"cannot safely inspect path component: {component}"
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            return True
    return False


def _validate_paths(source: Path, output: Path) -> tuple[Path, Path]:
    try:
        source = source.expanduser()
        output = output.expanduser()
    except RuntimeError as error:
        raise VisualPlanError("cannot safely expand source or output path") from error
    if ".." in source.parts or ".." in output.parts:
        raise VisualPlanError("source and output paths must not contain parent traversal")
    if _has_symlink_component(source) or _has_symlink_component(output):
        raise VisualPlanError("source and output must not be symbolic-link chains")
    source_absolute = Path(os.path.abspath(source))
    output_absolute = Path(os.path.abspath(output))
    if str(source_absolute).casefold() == str(output_absolute).casefold():
        raise VisualPlanError("output path must differ from source path")
    if not source_absolute.is_file():
        raise VisualPlanError(f"source file does not exist: {source}")
    if output_absolute.exists():
        try:
            if os.path.samefile(source_absolute, output_absolute):
                raise VisualPlanError("output path must not alias the source file")
        except VisualPlanError:
            raise
        except OSError as error:
            raise VisualPlanError("cannot safely compare source and output paths") from error
    return source, output


def _atomic_write_json(plan: dict, output: Path) -> None:
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        file_nofollow = os.O_NOFOLLOW
    except AttributeError as error:
        raise VisualPlanError("secure dirfd publishing is not supported") from error
    try:
        directory_fd = os.open(output.parent, directory_flags)
    except OSError as error:
        raise VisualPlanError("cannot securely open the output directory") from error

    publish_token = secrets.token_hex(8)
    temporary_name = f".{output.name}.{publish_token}.tmp"
    backup_name = f".{output.name}.{publish_token}.bak"
    temporary_exists = False
    backup_exists = False
    preserve_backup = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | file_nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        temporary_exists = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(plan, destination, ensure_ascii=False, indent=2, allow_nan=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())

        read_descriptor = os.open(
            temporary_name,
            os.O_RDONLY | file_nofollow,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(read_descriptor, "r", encoding="utf-8") as staged:
                staged_plan = json.load(
                    staged,
                    parse_constant=_reject_nonfinite,
                    object_pairs_hook=_reject_duplicate_keys,
                )
        except (UnicodeError, json.JSONDecodeError) as error:
            raise VisualPlanError("cannot read valid staged JSON") from error
        validate_plan(staged_plan)

        try:
            old_descriptor = os.open(
                output.name,
                os.O_RDONLY | file_nofollow,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            old_descriptor = None
        except OSError as error:
            raise VisualPlanError("cannot securely read the existing output") from error
        if old_descriptor is not None:
            try:
                backup_descriptor = os.open(
                    backup_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | file_nofollow,
                    0o600,
                    dir_fd=directory_fd,
                )
                backup_exists = True
                with os.fdopen(old_descriptor, "rb") as old_output, os.fdopen(
                    backup_descriptor, "wb"
                ) as backup:
                    while True:
                        chunk = old_output.read(64 * 1024)
                        if not chunk:
                            break
                        backup.write(chunk)
                    backup.flush()
                    os.fsync(backup.fileno())
            except Exception:
                try:
                    os.close(old_descriptor)
                except OSError:
                    pass
                raise

        try:
            current_directory_fd = os.open(output.parent, directory_flags)
        except OSError as error:
            raise VisualPlanError("output directory changed during publish") from error
        try:
            stable = os.fstat(directory_fd)
            current = os.fstat(current_directory_fd)
            if (stable.st_dev, stable.st_ino) != (current.st_dev, current.st_ino):
                raise VisualPlanError("output directory changed during publish")
        finally:
            os.close(current_directory_fd)

        try:
            os.replace(
                temporary_name,
                output.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        except (NotImplementedError, TypeError) as error:
            raise VisualPlanError("secure dirfd replace is not supported") from error
        temporary_exists = False

        try:
            current_directory_fd = os.open(output.parent, directory_flags)
        except OSError:
            current_directory_fd = None
        directory_matches = False
        if current_directory_fd is not None:
            try:
                stable = os.fstat(directory_fd)
                current = os.fstat(current_directory_fd)
                directory_matches = (stable.st_dev, stable.st_ino) == (
                    current.st_dev,
                    current.st_ino,
                )
            finally:
                os.close(current_directory_fd)

        if not directory_matches:
            try:
                if backup_exists:
                    os.replace(
                        backup_name,
                        output.name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                    backup_exists = False
                else:
                    try:
                        os.unlink(output.name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
            except Exception as error:
                preserve_backup = backup_exists
                recovery = (
                    f"manual recovery required from {backup_name}"
                    if backup_exists
                    else "manual recovery required in the displaced output directory"
                )
                raise VisualPlanError(
                    f"output directory changed and rollback failed; {recovery}"
                ) from error
            raise VisualPlanError(
                "output directory changed during publish; published data was rolled back"
            )

        if backup_exists:
            os.unlink(backup_name, dir_fd=directory_fd)
            backup_exists = False
    finally:
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        if backup_exists and not preserve_backup:
            try:
                os.unlink(backup_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="V4 visual plan path")
    parser.add_argument("--output", type=Path, required=True, help="V5 output path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source, output = _validate_paths(args.source, args.output)
        plan = build_plan(source)
        _atomic_write_json(plan, output)
    except (VisualPlanError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 2
    layouts = len({scene["editorial_layout"] for scene in plan["scenes"]})
    print(f"scenes={len(plan['scenes'])} frames={TOTAL_FRAMES} layouts={layouts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

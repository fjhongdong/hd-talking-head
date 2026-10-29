"""Compose approved B-roll component artifacts into one vertical segment."""

from __future__ import annotations

import hashlib
import fcntl
import json
import math
import os
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from . import (
    avatar_profile,
    broll_component_executor,
    broll_media,
    broll_systems,
    contract_artifacts,
    state,
    visual_strategy,
)


FPS = 24
WIDTH = 1080
HEIGHT = 1920
SOFT_SAFE_BOTTOM = 1700
RENDERER_CONTRACT_VERSION = "hd-segment-component-compositor-v7-aroll-overlay"
_HASH_CHUNK_SIZE = 1024 * 1024
_SHA256 = frozenset("0123456789abcdef")
_JOURNAL_SUFFIX = ".publication-journal.json"
_JOURNAL_KEYS = {
    "schema_version",
    "job_id",
    "segment_id",
    "generation_identity",
    "owner_nonce",
    "stage_name",
    "stage_identity",
    "state",
    "process_identity",
}
_JOURNAL_STATES = (
    "planned",
    "rendering",
    "complete",
    "publishing",
    "published",
    "exit_unconfirmed",
)
_FORMAL_OUTPUTS = {"segment.mp4", "segment-manifest.json", "keyframes"}
_KEYFRAME_NAMES = ("entry", "hold", "exit")


class SegmentRenderError(RuntimeError):
    """Raised when approved components cannot produce an exact segment."""


class _PreserveStageError(SegmentRenderError):
    """Raised when failure recovery must retain the current staging directory."""

    def __init__(self, message: str, *, pid: int, pgrp: int) -> None:
        super().__init__(message)
        self.pid = pid
        self.pgrp = pgrp


@dataclass(frozen=True)
class RenderedSegment:
    segment_id: str
    video_path: str
    video_sha256: str
    video_bytes: int
    frames: int
    generation_identity: str
    composition_family: str
    composition: dict[str, object]
    arroll_job_path: str
    arroll_sha256: str
    arroll_bytes: int
    component_artifacts: list[dict[str, object]]
    output_probe: dict[str, object]
    keyframes: dict[str, dict[str, object]]


@dataclass(frozen=True)
class _PreparedRender:
    recipe: dict[str, Any]
    family: str
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...]
    frames: int


@dataclass(frozen=True)
class _ApprovedArroll:
    job_path: str
    sha256: str
    byte_count: int


@dataclass
class _OutputRoot:
    path: Path
    pinned_job: broll_media._PinnedJob
    descriptors: list[int]
    identities: list[tuple[int, int, int]]

    @classmethod
    def open(cls, job: state.JobState, output_dir: Path) -> "_OutputRoot":
        job_path = Path(os.path.abspath(os.fspath(job.job_dir)))
        output_path = Path(os.path.abspath(os.fspath(output_dir)))
        try:
            relative = output_path.relative_to(job_path)
        except (TypeError, ValueError, OSError):
            raise SegmentRenderError(
                "output directory must be within the current Job"
            ) from None
        if not relative.parts or ".." in relative.parts:
            raise SegmentRenderError("output directory must be within the current Job")
        try:
            pinned = broll_media._PinnedJob.open(job)
        except broll_media.BrollMediaError:
            raise SegmentRenderError("Job artifact root is unavailable") from None
        descriptors: list[int] = []
        identities: list[tuple[int, int, int]] = []
        parent = pinned.descriptor
        try:
            for part in relative.parts:
                try:
                    visible = os.stat(part, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                    visible = os.stat(part, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(visible.st_mode):
                    raise SegmentRenderError("output directory identity changed")
                descriptor = os.open(part, _directory_flags(), dir_fd=parent)
                opened = os.fstat(descriptor)
                identity = _directory_identity(opened)
                if identity != _directory_identity(visible):
                    os.close(descriptor)
                    raise SegmentRenderError("output directory identity changed")
                descriptors.append(descriptor)
                identities.append(identity)
                parent = descriptor
            pinned.verify_visible()
            return cls(output_path, pinned, descriptors, identities)
        except SegmentRenderError:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            pinned.close()
            raise
        except (OSError, broll_media.BrollMediaError):
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            pinned.close()
            raise SegmentRenderError("output directory identity changed") from None

    def verify(self) -> None:
        try:
            self.pinned_job.verify_visible()
            parent = self.pinned_job.descriptor
            for descriptor, identity, name in zip(
                self.descriptors,
                self.identities,
                self.path.relative_to(self.pinned_job.path).parts,
            ):
                current = os.fstat(descriptor)
                visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (
                    _directory_identity(current) != identity
                    or _directory_identity(visible) != identity
                ):
                    raise SegmentRenderError("output directory identity changed")
                parent = descriptor
        except SegmentRenderError:
            raise
        except (OSError, ValueError, broll_media.BrollMediaError):
            raise SegmentRenderError("output directory identity changed") from None

    def close(self) -> None:
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()
        self.pinned_job.close()


def expected_frames(segment: Mapping[str, Any]) -> int:
    try:
        start = segment["start"]
        end = segment["end"]
    except (KeyError, TypeError) as exc:
        raise SegmentRenderError("segment timing is invalid") from exc
    if (
        type(start) not in {int, float}
        or type(end) not in {int, float}
        or not math.isfinite(float(start))
        or not math.isfinite(float(end))
    ):
        raise SegmentRenderError("segment timing is invalid")
    duration = float(end) - float(start)
    frames = round(duration * FPS)
    if duration <= 0 or frames <= 0 or abs(frames / FPS - duration) > 1e-6:
        raise SegmentRenderError("segment timing must align to the 24 fps clock")
    return frames


def _sha256_text(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact_identity(
    artifact: broll_component_executor.ComponentArtifact,
) -> dict[str, object]:
    return {
        field: _plain(getattr(artifact, field))
        for field in artifact.__dataclass_fields__
    }


def generation_identity(
    job: state.JobState,
    segment: Mapping[str, Any],
    visual_plan_sha256: str,
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    arroll: _ApprovedArroll,
) -> str:
    composition = segment.get("shot_recipe", {}).get("composition", {})
    if composition.get("presenter_mode") == "bottom_window":
        try:
            avatar = avatar_profile.validate_avatar(composition.get("avatar"), frames=expected_frames(segment))
        except (ValueError, OSError) as error:
            raise SegmentRenderError(str(error)) from None
        if avatar["profile"]["source_sha256"] != arroll.sha256:
            raise SegmentRenderError("avatar source differs from the current A-roll")
    if (
        type(visual_plan_sha256) is not str
        or len(visual_plan_sha256) != 64
        or any(character not in _SHA256 for character in visual_plan_sha256)
    ):
        raise SegmentRenderError("visual plan identity is invalid")
    return contract_artifacts.sha256_json(
        {
            "schema_version": 4,
            "job_id": job.job_id,
            # The parent manifest binds plan approval. Other shots changing must
            # not invalidate this exact segment, its A-roll or component evidence.
            "segment": _plain(segment),
            "arroll": {
                "job_path": arroll.job_path,
                "sha256": arroll.sha256,
                "bytes": arroll.byte_count,
            },
            "artifacts": [_artifact_identity(artifact) for artifact in artifacts],
            "renderer_version": RENDERER_CONTRACT_VERSION,
        }
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _input_sha(recipe: Mapping[str, Any], component_id: str) -> str:
    return _sha256_text({"recipe": recipe, "component_id": component_id})


def _valid_sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256 for character in value)
    )


def _validate_probe_record(
    artifact: broll_component_executor.ComponentArtifact,
) -> None:
    probe = artifact.media_probe
    contract = artifact.artifact_contract
    keys = {
        "media_type",
        "container",
        "codec",
        "pixel_format",
        "alpha",
        "width",
        "height",
        "fps",
        "frame_count",
        "duration",
    }
    if (
        not isinstance(probe, Mapping)
        or set(probe) != keys
        or not isinstance(contract, Mapping)
        or set(contract) != {"width", "height", "fps", "alpha"}
        or artifact.media_type != artifact.artifact_media_type
        or artifact.artifact_media_type not in {"image", "video"}
        or probe.get("media_type") != artifact.artifact_media_type
        or type(probe.get("container")) is not str
        or type(probe.get("codec")) is not str
        or type(probe.get("pixel_format")) is not str
        or type(probe.get("alpha")) is not bool
        or probe["alpha"] is not contract["alpha"]
        or type(probe.get("width")) is not int
        or probe["width"] != contract["width"]
        or type(probe.get("height")) is not int
        or probe["height"] != contract["height"]
        or type(probe.get("frame_count")) is not int
        or probe["frame_count"] <= 0
    ):
        raise SegmentRenderError("component media contract is invalid")
    if artifact.artifact_media_type == "image":
        pixel_formats = {"rgba"} if contract["alpha"] else {"rgb24"}
        if (
            probe["container"] != "png"
            or probe["codec"] != "png"
            or probe["pixel_format"] not in pixel_formats
            or probe["fps"] is not None
            or probe["frame_count"] != 1
            or probe["duration"] is not None
        ):
            raise SegmentRenderError("component media contract is invalid")
        return
    expected = (
        {("mov", "prores_ks", "yuva444p10le"), ("mov", "prores_ks", "yuva444p12le"), ("mov", "qtrle", "argb")}
        if contract["alpha"]
        else {("mp4", "h264", "yuv420p")}
    )
    fps = probe.get("fps")
    duration = probe.get("duration")
    if (
        (probe["container"], probe["codec"], probe["pixel_format"]) not in expected
        or type(fps) not in {int, float}
        or not math.isfinite(float(fps))
        or float(fps) != FPS
        or type(duration) not in {int, float}
        or not math.isfinite(float(duration))
        or float(duration) <= 0
        or abs(float(duration) - probe["frame_count"] / FPS) > 1e-6
    ):
        raise SegmentRenderError("component media contract is invalid")


def _validate_artifact(
    job: state.JobState,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    artifact: object,
    frames: int,
) -> broll_component_executor.ComponentArtifact:
    if type(artifact) is not broll_component_executor.ComponentArtifact:
        raise SegmentRenderError("component artifact type is invalid")
    window = component["render_window"]
    evidence = artifact.invocation_evidence
    qa = artifact.qa
    if (
        artifact.schema_version != 1
        or artifact.status != "success"
        or artifact.error_code is not None
        or artifact.job_id != job.job_id
        or artifact.segment_id != recipe["segment_id"]
        or artifact.component_id != component["component_id"]
        or artifact.kind != component["kind"]
        or artifact.strategy_revision != recipe["strategy_revision"]
        or artifact.source_media_type != component["media_type"]
        or _plain(artifact.render_window) != window
        or artifact.z_index != window["z_index"]
        or artifact.layout_slot != window["layout_slot"]
        or artifact.opacity != window["opacity"]
        or _plain(artifact.safe_zone) != window["safe_zone"]
        or _plain(artifact.artifact_contract) != component["artifact_contract"]
        or artifact.input_sha256 != _input_sha(recipe, artifact.component_id)
        or not _valid_sha(artifact.input_sha256)
        or not _valid_sha(artifact.output_sha256)
        or type(artifact.byte_count) is not int
        or artifact.byte_count <= 0
        or not isinstance(evidence, Mapping)
        or evidence.get("output_job_path") != artifact.job_path
        or evidence.get("output_sha256") != artifact.output_sha256
        or not isinstance(qa, Mapping)
        or qa.get("passed") is not True
        or type(window["start_frame"]) is not int
        or type(window["end_frame"]) is not int
        or not 0 <= window["start_frame"] < window["end_frame"] <= frames
    ):
        raise SegmentRenderError("component artifact binding is invalid")
    _validate_probe_record(artifact)
    if (
        artifact.artifact_media_type == "video"
        and artifact.media_probe["frame_count"]
        < window["end_frame"] - window["start_frame"]
    ):
        raise SegmentRenderError("component video is shorter than its approved window")
    return artifact


def _prepare_render(
    job: state.JobState,
    segment: Mapping[str, Any],
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
) -> _PreparedRender:
    if type(artifacts) is not tuple:
        raise SegmentRenderError("component artifacts must be a tuple")
    if not isinstance(segment, Mapping):
        raise SegmentRenderError("approved segment is invalid")
    segment_id = segment.get("segment_id")
    if type(segment_id) is not str or not re_full_segment_id(segment_id):
        raise SegmentRenderError("segment_id is invalid")
    frames = expected_frames(segment)
    try:
        recipe = visual_strategy.validate_shot_recipe_v2(segment.get("shot_recipe"))
    except (visual_strategy.VisualStrategyError, AttributeError, TypeError):
        raise SegmentRenderError("approved ShotRecipe v2 is invalid") from None
    if recipe["segment_id"] != segment_id or len(recipe["components"]) != len(artifacts):
        raise SegmentRenderError("component artifacts do not match ShotRecipe v2")
    strategy = segment.get("visual_strategy")
    if not isinstance(strategy, Mapping):
        raise SegmentRenderError("approved visual composition is unavailable")
    try:
        composition = visual_strategy.validate_composition_contract(
            strategy.get("composition"),
            strategy.get("components"),
            strategy.get("mode"),
        )
    except (visual_strategy.VisualStrategyError, AttributeError, TypeError):
        raise SegmentRenderError("approved visual composition is invalid") from None
    if (
        strategy.get("segment_id") != segment_id
        or strategy.get("mode") != recipe["mode"]
        or composition != recipe["composition"]
    ):
        raise SegmentRenderError("approved visual composition does not match recipe")
    strategy_components = strategy.get("components")
    if type(strategy_components) is not list or len(strategy_components) != len(
        recipe["components"]
    ):
        raise SegmentRenderError("approved visual components do not match recipe")
    strategy_by_id = {
        component.get("component_id"): component
        for component in strategy_components
        if isinstance(component, Mapping)
    }
    if len(strategy_by_id) != len(strategy_components):
        raise SegmentRenderError("approved visual components do not match recipe")
    ordered_strategy_components = [
        strategy_by_id[component_id]
        for component_id in composition["reading_order"]
    ]
    for approved, compiled in zip(
        ordered_strategy_components, recipe["components"]
    ):
        if any(
            approved.get(field) != compiled.get(field)
            for field in (
                "component_id",
                "kind",
                "semantic_role",
                "layer_role",
                "media_type",
            )
        ) or approved.get("layout_slot") != compiled["render_window"]["layout_slot"]:
            raise SegmentRenderError("approved visual components do not match recipe")
    family = recipe["composition"]["family"]
    checked = tuple(
        _validate_artifact(job, recipe, component, artifact, frames)
        for component, artifact in zip(recipe["components"], artifacts)
    )
    if family == "no_broll":
        if checked or recipe["mode"] != "none":
            raise SegmentRenderError("approved A-roll composition is invalid")
    else:
        try:
            broll_systems.validate_composition(recipe, checked)
        except broll_systems.BrollSystemError:
            raise SegmentRenderError("approved component composition is invalid") from None
    return _PreparedRender(recipe=recipe, family=family, artifacts=checked, frames=frames)


def _layout(
    artifact: broll_component_executor.ComponentArtifact,
    layer_role: str,
) -> tuple[int, int, int, int, bool]:
    slot = artifact.layout_slot
    allowed_slots = visual_strategy.LAYER_ROLE_LAYOUT_SLOTS.get(layer_role)
    if allowed_slots is None or slot not in allowed_slots:
        raise SegmentRenderError("approved layout slot does not match layer role")
    zone = artifact.safe_zone
    if (
        not isinstance(zone, Mapping)
        or set(zone) != {"top", "bottom", "left", "right"}
        or any(type(zone[side]) is not int or zone[side] < 0 for side in zone)
    ):
        raise SegmentRenderError("component layout margins are invalid")
    left = zone["left"]
    right = zone["right"]
    top = zone["top"]
    bottom = zone["bottom"]
    transparent_layer = layer_role != "base"
    full_canvas_background = (
        layer_role == "base"
        and slot in {"full_frame", "background_blur"}
        and all(zone[side] == 0 for side in ("top", "bottom", "left", "right"))
    )
    width = WIDTH - left - right
    visible_bottom = HEIGHT if full_canvas_background else min(HEIGHT - bottom, SOFT_SAFE_BOTTOM)
    height = visible_bottom - top
    if (
        width <= 0
        or height <= 0
        or (not full_canvas_background and HEIGHT - bottom > SOFT_SAFE_BOTTOM)
    ):
        raise SegmentRenderError("component layout overlaps the subtitle area")
    return left, top, width, height, transparent_layer


def build_filter_graph(
    recipe: Mapping[str, Any],
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    *,
    frames: int,
) -> str:
    """Build the sole frame-level composition graph for approved artifacts."""

    if type(frames) is not int or frames <= 0 or type(artifacts) is not tuple:
        raise SegmentRenderError("composition timeline is invalid")
    components = recipe.get("components")
    if type(components) is not list or len(components) != len(artifacts):
        raise SegmentRenderError("composition components are invalid")
    composition = recipe.get("composition")
    if not isinstance(composition, Mapping):
        raise SegmentRenderError("approved composition is invalid")
    presenter_mode = composition.get("presenter_mode")
    if presenter_mode not in visual_strategy.PRESENTER_MODES:
        raise SegmentRenderError("approved presenter mode is invalid")
    relation_exits: list[tuple[dict[str, Any], tuple[int, int]]] = []
    try:
        for component in components:
            exit_window = visual_strategy.native_motion_exit_window(component)
            if exit_window is not None:
                relation_exits.append((component, exit_window))
    except visual_strategy.VisualStrategyError as error:
        raise SegmentRenderError(str(error)) from None
    relation_exit: tuple[int, int] | None = None
    if relation_exits:
        if len(components) != 1 or len(relation_exits) != 1:
            raise SegmentRenderError(
                "native motion exit requires one unambiguous component"
            )
        component, relation_exit = relation_exits[0]
        window = component.get("render_window")
        if (
            presenter_mode != "bottom_window"
            or component.get("layer_role") != "base"
            or not isinstance(window, Mapping)
            or window.get("start_frame") != 0
            or window.get("end_frame") != frames
            or relation_exit[1] != frames
            or relation_exit[1] - relation_exit[0] < 2
        ):
            raise SegmentRenderError(
                "native motion exit requires a full-window base bottom composition"
            )
    if presenter_mode == "full_frame":
        filters = [
            "[0:v]fps=24,"
            "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            # The approved timeline is audio-clock based and can be a
            # fraction of a frame longer than the encoded A-roll stream.
            # Clone the final frame before trimming so presenter-only spans
            # still satisfy the exact frame contract.
            "tpad=stop_mode=clone:stop_duration=1,"
            f"trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS[canvas_0]"
        ]
    else:
        filters = [
            f"color=c=black:s=1080x1920:r=24:d={frames / FPS:.6f},"
            f"trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS[canvas_0]"
        ]
    components_by_id = {
        component.get("component_id"): component
        for component in components
        if type(component) is dict
    }
    if len(components_by_id) != len(components):
        raise SegmentRenderError("composition components are invalid")
    ordered = sorted(
        enumerate(artifacts), key=lambda item: (item[1].z_index, item[0])
    )
    canvas_index = 0
    for input_position, artifact in ordered:
        if type(artifact) is not broll_component_executor.ComponentArtifact:
            raise SegmentRenderError("component artifact type is invalid")
        component = components_by_id.get(artifact.component_id)
        if type(component) is not dict or component.get("kind") != artifact.kind:
            raise SegmentRenderError("composition components are invalid")
        left, top, width, height, transparent_layer = _layout(
            artifact, str(component.get("layer_role"))
        )
        start = artifact.render_window["start_frame"]
        end = artifact.render_window["end_frame"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= frames
            or type(artifact.opacity) is not float
            or not 0.0 <= artifact.opacity <= 1.0
        ):
            raise SegmentRenderError("component render window is invalid")
        source = input_position + 1
        duration = end - start
        filters.append(
            f"[{source}:v]fps=24,trim=start_frame=0:end_frame={duration},"
            f"setpts=PTS-STARTPTS+{start}/24/TB,format=rgba[component_{input_position}_input]"
        )
        if composition.get("family") == "aroll_with_overlay":
            # These are full-canvas transparent layers, already laid out in
            # source pixels. Do not shrink the approved graphic into a B-roll box.
            filters.append(
                f"[component_{input_position}_input]"
                f"crop={width}:{height}:{left}:{top},"
                f"pad=1080:1920:{left}:{top}:color=black@0,"
                f"colorchannelmixer=aa={artifact.opacity:.6f}[component_{input_position}]"
            )
            next_canvas = canvas_index + 1
            filters.append(
                f"[canvas_{canvas_index}][component_{input_position}]"
                f"overlay=0:0:eof_action=pass:shortest=0:"
                f"enable='between(n,{start},{end - 1})'[canvas_{next_canvas}]"
            )
            canvas_index = next_canvas
            continue
        if transparent_layer:
            filters.append(
                f"[component_{input_position}_input]"
                f"null[component_{input_position}_source]"
            )
        else:
            filters.append(
                f"[component_{input_position}_input]split=2"
                f"[component_{input_position}_source]"
                f"[component_{input_position}_background_source]"
            )
        filters.append(
            f"[component_{input_position}_source]"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"format=rgba[component_{input_position}_foreground]"
        )
        if transparent_layer:
            filters.append(
                f"color=c=black@0.0:s=1080x1920:r=24:d={frames / FPS:.6f},"
                f"format=rgba[component_{input_position}_background]"
            )
        else:
            filters.append(
                f"[component_{input_position}_background_source]"
                f"scale=1080:1920:flags=lanczos,"
                f"gblur=sigma=24,format=rgba[component_{input_position}_background]"
            )
        x = f"{left}+({width}-w)/2"
        y = f"{top}+({height}-h)/2"
        filters.append(
            f"[component_{input_position}_background]"
            f"[component_{input_position}_foreground]"
            f"overlay=x='{x}':y='{y}':eof_action=pass:shortest=0,"
            f"colorchannelmixer=aa={artifact.opacity:.6f}[component_{input_position}]"
        )
        next_canvas = canvas_index + 1
        filters.append(
            f"[canvas_{canvas_index}][component_{input_position}]"
            f"overlay=0:0:eof_action=pass:shortest=0:"
            f"enable='between(n,{start},{end - 1})'[canvas_{next_canvas}]"
        )
        canvas_index = next_canvas
    if presenter_mode == "bottom_window":
        try:
            avatar = avatar_profile.validate_avatar(composition.get("avatar"), frames=frames)
            filters.extend(avatar_profile.filter_chain(
                avatar, frames=frames, fade_out=relation_exit is None
            ))
        except (ValueError, OSError) as error:
            raise SegmentRenderError(str(error)) from None
        position = ({"x": 0, "y": 0} if "entrance" in avatar or "exit" in avatar else avatar["position"])
        next_canvas = canvas_index + 1
        filters.append(
            f"[canvas_{canvas_index}][presenter]"
            f"overlay={position['x']}:{position['y']}:eof_action=pass:shortest=0[canvas_{next_canvas}]"
        )
        canvas_index = next_canvas
    if relation_exit is not None:
        exit_start, exit_end = relation_exit
        last_frame = exit_end - 1
        denominator = last_frame - exit_start
        filters.extend(
            (
                "[0:v]fps=24,"
                "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS,"
                "format=rgba[relation_aroll]",
                f"[canvas_{canvas_index}]null[relation_composite]",
                "[relation_composite][relation_aroll]"
                "blend=all_expr='"
                # blend's N is one-based, unlike the approved frame windows.
                f"if(lt(N-1\\,{exit_start})\\,A\\,"
                f"if(gte(N-1\\,{last_frame})\\,B\\,"
                f"A*({last_frame}-(N-1))/{denominator}+"
                f"B*((N-1)-{exit_start})/{denominator}))'"
                "[relation_exit]",
                "[relation_exit]scale=in_range=auto:out_range=tv,format=yuv420p,setparams=range=limited[out]",
            )
        )
    else:
        # Phone footage may be full-range (yuvj420p). Convert sample values as
        # well as the range tag; merely requesting yuv420p retains the PC flag.
        filters.append(f"[canvas_{canvas_index}]scale=in_range=auto:out_range=tv,format=yuv420p,setparams=range=limited[out]")
    return ";".join(filters)


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise SegmentRenderError("component snapshot write failed")
        offset += written


def _hash_fd(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        block = os.read(descriptor, _HASH_CHUNK_SIZE)
        if not block:
            break
        digest.update(block)
        size += len(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), size


def _snapshot_job_file(
    pinned_job: broll_media._PinnedJob,
    job_path: str,
    expected_sha256: str,
    expected_bytes: int,
    destination: Path,
    *,
    label: str,
) -> None:
    relative = PurePosixPath(job_path)
    if (
        relative.is_absolute()
        or relative == PurePosixPath(".")
        or ".." in relative.parts
        or "\\" in job_path
        or not relative.parts
    ):
        raise SegmentRenderError(f"{label} path is invalid")
    opened: list[int] = []
    directories: list[tuple[int, int, str, tuple[int, int, int]]] = []
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        parent = pinned_job.descriptor
        for part in relative.parts[:-1]:
            visible = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(visible.st_mode):
                raise SegmentRenderError(f"{label} path changed")
            descriptor = os.open(part, _directory_flags(), dir_fd=parent)
            opened.append(descriptor)
            identity = _directory_identity(os.fstat(descriptor))
            if identity != _directory_identity(visible):
                raise SegmentRenderError(f"{label} path changed")
            directories.append((descriptor, parent, part, identity))
            parent = descriptor
        visible_before = os.stat(
            relative.parts[-1], dir_fd=parent, follow_symlinks=False
        )
        if not stat.S_ISREG(visible_before.st_mode) or visible_before.st_nlink != 1:
            raise SegmentRenderError(f"{label} file is invalid")
        source_fd = os.open(relative.parts[-1], _file_flags(), dir_fd=parent)
        opened.append(source_fd)
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _file_identity(before) != _file_identity(visible_before)
        ):
            raise SegmentRenderError(f"{label} path changed")
        destination_fd = os.open(
            destination,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            block = os.read(source_fd, _HASH_CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
            byte_count += len(block)
            _write_all(destination_fd, block)
        os.fsync(destination_fd)
        after = os.fstat(source_fd)
        visible_after = os.stat(
            relative.parts[-1], dir_fd=parent, follow_symlinks=False
        )
        for descriptor, directory_parent, name, identity in directories:
            current = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=directory_parent, follow_symlinks=False)
            if (
                _directory_identity(current) != identity
                or _directory_identity(visible) != identity
            ):
                raise SegmentRenderError(f"{label} path changed")
        snapshot_sha, snapshot_size = _hash_fd(destination_fd)
        if (
            _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible_after)
            or digest.hexdigest() != expected_sha256
            or byte_count != expected_bytes
            or (snapshot_sha, snapshot_size)
            != (expected_sha256, expected_bytes)
        ):
            raise SegmentRenderError(f"{label} bytes changed")
    except SegmentRenderError:
        raise
    except (OSError, TypeError, ValueError):
        raise SegmentRenderError(f"{label} snapshot failed") from None
    finally:
        if destination_fd is not None:
            try:
                os.close(destination_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _snapshot_inputs(
    job: state.JobState,
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    stage: Path,
    arroll: _ApprovedArroll,
) -> tuple[Path, tuple[Path, ...]]:
    inputs = stage / "inputs"
    inputs.mkdir(mode=0o700)
    arroll_snapshot = inputs / "arroll.mp4"
    try:
        pinned_job = broll_media._PinnedJob.open(job)
    except broll_media.BrollMediaError:
        raise SegmentRenderError("Job artifact root is unavailable") from None
    snapshots: list[Path] = []
    try:
        _snapshot_job_file(
            pinned_job,
            arroll.job_path,
            arroll.sha256,
            arroll.byte_count,
            arroll_snapshot,
            label="edited A-roll",
        )
        for index, artifact in enumerate(artifacts):
            suffix = (
                ".png"
                if artifact.artifact_media_type == "image"
                else ".mov"
                if artifact.artifact_contract["alpha"]
                else ".mp4"
            )
            destination = inputs / f"component-{index:03d}{suffix}"
            _snapshot_job_file(
                pinned_job,
                artifact.job_path,
                artifact.output_sha256,
                artifact.byte_count,
                destination,
                label="component artifact",
            )
            snapshots.append(destination)
        pinned_job.verify_visible()
    except broll_media.BrollMediaError:
        raise SegmentRenderError("Job artifact root changed") from None
    finally:
        pinned_job.close()
    return arroll_snapshot, tuple(snapshots)


def _approve_aroll(
    job: state.JobState,
    source: Path,
    expected_sha256: str,
    expected_bytes: int,
) -> _ApprovedArroll:
    if not _valid_sha(expected_sha256) or type(expected_bytes) is not int or expected_bytes <= 0:
        raise SegmentRenderError("edited A-roll approval is invalid")
    try:
        job_path = Path(os.path.abspath(os.fspath(job.job_dir)))
        source_path = Path(os.path.abspath(os.fspath(source)))
        relative = source_path.relative_to(job_path)
    except (AttributeError, TypeError, ValueError, OSError):
        raise SegmentRenderError("edited A-roll must be within the current Job") from None
    if not relative.parts or ".." in relative.parts:
        raise SegmentRenderError("edited A-roll must be within the current Job")
    job_relative = PurePosixPath(*relative.parts).as_posix()
    try:
        pinned = broll_media._PinnedJob.open(job)
    except broll_media.BrollMediaError:
        raise SegmentRenderError("Job artifact root is unavailable") from None
    try:
        actual_path, digest, size, _identity = broll_media._resolve_frozen_file(
            pinned, job_relative, expected_sha256
        )
        pinned.verify_visible()
    except broll_media.BrollMediaError:
        raise SegmentRenderError("edited A-roll bytes changed") from None
    finally:
        pinned.close()
    if (
        Path(actual_path) != source_path
        or digest != expected_sha256
        or size != expected_bytes
    ):
        raise SegmentRenderError("edited A-roll bytes changed")
    return _ApprovedArroll(job_relative, digest, size)


def _verify_current_inputs(
    job: state.JobState,
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    arroll: _ApprovedArroll,
) -> None:
    try:
        pinned = broll_media._PinnedJob.open(job)
    except broll_media.BrollMediaError:
        raise SegmentRenderError("Job artifact root is unavailable") from None
    try:
        try:
            _path, digest, size, _identity = broll_media._resolve_frozen_file(
                pinned, arroll.job_path, arroll.sha256
            )
        except broll_media.BrollMediaError:
            raise SegmentRenderError("edited A-roll bytes changed") from None
        if (digest, size) != (arroll.sha256, arroll.byte_count):
            raise SegmentRenderError("edited A-roll bytes changed")
        for artifact in artifacts:
            try:
                _path, digest, size, _identity = broll_media._resolve_frozen_file(
                    pinned, artifact.job_path, artifact.output_sha256
                )
            except broll_media.BrollMediaError:
                raise SegmentRenderError("component artifact bytes changed") from None
            if (digest, size) != (artifact.output_sha256, artifact.byte_count):
                raise SegmentRenderError("component artifact bytes changed")
        pinned.verify_visible()
    except broll_media.BrollMediaError:
        raise SegmentRenderError("Job artifact root changed") from None
    finally:
        pinned.close()


def _ffmpeg_command(
    arroll_snapshot: Path,
    artifact_snapshots: tuple[Path, ...],
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    graph: str,
    output: Path,
    segment_start: float,
    frames: int,
) -> tuple[str, ...]:
    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-xerror",
        "-v",
        "error",
        "-ss",
        f"{segment_start:.6f}",
        "-i",
        str(arroll_snapshot),
    ]
    for artifact, snapshot in zip(artifacts, artifact_snapshots):
        if artifact.artifact_media_type == "image":
            command.extend(("-loop", "1", "-framerate", "24"))
        command.extend(("-i", str(snapshot)))
    command.extend(
        (
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-frames:v",
            str(frames),
            "-r",
            "24",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-movflags",
            "+faststart",
            "-y",
            str(output),
        )
    )
    return tuple(command)


def _process_group_exists(pgrp: int) -> bool:
    try:
        os.killpg(pgrp, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    pid = process.pid
    # FFmpeg starts a new session, so the launch pid is the recorded group id.
    pgrp = pid

    def wait_for_complete_exit() -> bool:
        for _ in range(5):
            leader_exited = process.poll() is not None
            group_exited = not _process_group_exists(pgrp)
            if leader_exited and group_exited:
                return True
            if leader_exited:
                time.sleep(0.05)
                continue
            try:
                process.wait(timeout=0.05)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return process.poll() is not None and not _process_group_exists(pgrp)

    if wait_for_complete_exit():
        return
    for group_signal in (signal.SIGTERM, signal.SIGKILL):
        if _process_group_exists(pgrp):
            try:
                os.killpg(pgrp, group_signal)
            except OSError:
                pass
        if wait_for_complete_exit():
            return
    for stop in (process.terminate, process.kill):
        if process.poll() is not None:
            break
        try:
            stop()
        except OSError:
            pass
        if wait_for_complete_exit():
            return
    if process.poll() is not None and not _process_group_exists(pgrp):
        return
    raise _PreserveStageError(
        "FFmpeg process did not stop", pid=pid, pgrp=pgrp
    )


def _default_ffmpeg_runner(command: tuple[str, ...], timeout: float) -> None:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout, stderr=stderr
            )
        _terminate_process(process)
    except _PreserveStageError:
        raise
    except subprocess.TimeoutExpired:
        if process is not None:
            _terminate_process(process)
        raise
    except BaseException:
        if process is not None:
            _terminate_process(process)
        raise
    finally:
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


def _default_probe(path: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = stream.get("duration", payload.get("format", {}).get("duration"))
        return {**stream, "duration": duration}
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise SegmentRenderError("rendered segment probe failed") from exc


def _probe_matches(probe: Mapping[str, object], frames: int) -> bool:
    try:
        width = probe["width"]
        height = probe["height"]
        frame_count = probe["nb_read_frames"]
        duration = probe["duration"]
        return (
            type(width) in {int, str}
            and int(width) == WIDTH
            and type(height) in {int, str}
            and int(height) == HEIGHT
            and probe["r_frame_rate"] == "24/1"
            and type(frame_count) in {int, str}
            and int(frame_count) == frames
            and type(duration) in {int, float, str}
            and math.isfinite(float(duration))
            and abs(float(duration) - frames / FPS) <= 1e-3
            and probe["codec_name"] == "h264"
            and probe["pix_fmt"] == "yuv420p"
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _default_frame_extractor(video: Path, timestamp: float, output: Path) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-xerror",
                "-v",
                "error",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "scale=1080:1920:flags=lanczos",
                "-y",
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SegmentRenderError("segment keyframe extraction failed") from exc


def _hash_file(path: Path) -> tuple[str, int]:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _file_flags())
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SegmentRenderError("rendered segment file is invalid")
        return _hash_fd(descriptor)
    except SegmentRenderError:
        raise
    except OSError:
        raise SegmentRenderError("rendered segment file is unavailable") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _directory_flags())
        os.fsync(descriptor)
    except OSError:
        raise SegmentRenderError("output directory synchronization failed") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _journal_path(output_root: Path, segment_id: str) -> Path:
    return output_root / f".{segment_id}{_JOURNAL_SUFFIX}"


def _stage_identity(path: Path) -> dict[str, int]:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise SegmentRenderError("render staging identity is unavailable") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise SegmentRenderError("render staging identity is invalid")
    return {
        "dev": metadata.st_dev,
        "ino": metadata.st_ino,
        "mode": metadata.st_mode,
    }


def _new_journal(
    job: state.JobState,
    segment_id: str,
    identity: str,
    nonce: str,
    stage: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "segment_id": segment_id,
        "generation_identity": identity,
        "owner_nonce": nonce,
        "stage_name": stage.name,
        "stage_identity": _stage_identity(stage),
        "state": "planned",
        "process_identity": None,
    }


def _write_journal(
    output_root: Path,
    journal: Mapping[str, object],
    transaction_state: str,
    *,
    process_identity: Mapping[str, int] | None = None,
) -> dict[str, object]:
    if transaction_state not in _JOURNAL_STATES:
        raise SegmentRenderError("publication journal state is invalid")
    payload = dict(journal)
    payload["state"] = transaction_state
    payload["process_identity"] = (
        None if process_identity is None else dict(process_identity)
    )
    try:
        contract_artifacts.write_json_artifact(
            _journal_path(output_root, str(payload["segment_id"])), payload
        )
    except (KeyError, contract_artifacts.ContractArtifactError):
        raise SegmentRenderError("publication journal could not be recorded") from None
    return payload


def _read_journal(output_root: Path, segment_id: str) -> dict[str, object] | None:
    path = _journal_path(output_root, segment_id)
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise SegmentRenderError("publication journal is unavailable") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SegmentRenderError("publication journal is invalid")
    try:
        journal = contract_artifacts.read_json_artifact(path)
    except contract_artifacts.ContractArtifactError:
        raise SegmentRenderError("publication journal is invalid") from None
    stage_identity = journal.get("stage_identity")
    process_identity = journal.get("process_identity")
    if (
        set(journal) != _JOURNAL_KEYS
        or journal.get("schema_version") != 1
        or journal.get("segment_id") != segment_id
        or type(journal.get("job_id")) is not str
        or not _valid_sha(journal.get("generation_identity"))
        or type(journal.get("owner_nonce")) is not str
        or len(journal["owner_nonce"]) != 32
        or any(character not in _SHA256 for character in journal["owner_nonce"])
        or journal.get("stage_name")
        != f".{segment_id}.stage-{journal['owner_nonce']}"
        or type(stage_identity) is not dict
        or set(stage_identity) != {"dev", "ino", "mode"}
        or any(type(stage_identity[field]) is not int for field in stage_identity)
        or journal.get("state") not in _JOURNAL_STATES
        or (
            process_identity is not None
            and (
                type(process_identity) is not dict
                or set(process_identity) != {"pid", "pgrp"}
                or any(
                    type(process_identity[field]) is not int
                    or process_identity[field] <= 0
                    for field in process_identity
                )
            )
        )
        or (journal.get("state") == "exit_unconfirmed")
        != (process_identity is not None)
    ):
        raise SegmentRenderError("publication journal is invalid")
    return journal


def _process_identity_exists(pid: int, pgrp: int) -> bool:
    try:
        actual_pgrp = os.getpgid(pid)
    except ProcessLookupError:
        actual_pgrp = None
    except OSError:
        return True
    if actual_pgrp == pgrp:
        return True
    return _process_group_exists(pgrp)


def _remove_journal(output_root: Path, segment_id: str) -> None:
    try:
        _journal_path(output_root, segment_id).unlink()
    except FileNotFoundError:
        return
    except OSError:
        raise SegmentRenderError("publication journal could not be closed") from None
    _fsync_directory(output_root)


def _recover_journal(
    output_root: Path,
    job: state.JobState,
    segment_id: str,
    identity: str,
    target: Path,
) -> dict[str, object] | None:
    journal = _read_journal(output_root, segment_id)
    if journal is None:
        return None
    if journal["job_id"] != job.job_id:
        raise SegmentRenderError("publication journal belongs to another Job")
    same_generation = journal["generation_identity"] == identity
    stage = output_root / str(journal["stage_name"])
    stage_exists = stage.exists()
    target_exists = target.exists()
    expected_identity = journal["stage_identity"]
    if stage_exists and _stage_identity(stage) != expected_identity:
        raise SegmentRenderError("render staging identity changed")
    if target_exists and stage_exists:
        raise SegmentRenderError("publication state is inconsistent")
    if journal["state"] == "exit_unconfirmed":
        process_identity = journal["process_identity"]
        if _process_identity_exists(
            process_identity["pid"], process_identity["pgrp"]
        ):
            raise SegmentRenderError("process exit is not confirmed")
    if target_exists and not same_generation:
        raise SegmentRenderError("existing segment generation has another identity")
    if stage_exists:
        try:
            shutil.rmtree(stage)
        except OSError:
            raise SegmentRenderError("render staging could not be recovered") from None
        _remove_journal(output_root, segment_id)
        return None
    if not target_exists and journal["state"] in {
        "planned",
        "rendering",
        "complete",
        "exit_unconfirmed",
    }:
        _remove_journal(output_root, segment_id)
        return None
    if (
        target_exists
        and journal["state"] in {"publishing", "published"}
        and _stage_identity(target) == expected_identity
    ):
        return journal
    raise SegmentRenderError("publication journal does not match current output")


def _fsync_file(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _file_flags())
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SegmentRenderError("published artifact is invalid")
        os.fsync(descriptor)
    except SegmentRenderError:
        raise
    except OSError:
        raise SegmentRenderError("published artifact synchronization failed") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_segment_lock(output_root: Path, segment_id: str) -> int:
    path = output_root / f".{segment_id}.render.lock"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SegmentRenderError("segment render lock is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor
    except SegmentRenderError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise SegmentRenderError("segment render lock is unavailable") from None


def _close_segment_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _keyframe_moments(frames: int) -> dict[str, float]:
    duration = frames / FPS
    last_frame = (frames - 1) / FPS
    return {
        "entry": min(duration / 4, 0.35, last_frame),
        "hold": min(duration / 2, last_frame),
        "exit": min(
            max(duration - min(duration / 4, 0.35), duration / 2),
            last_frame,
        ),
    }


def _keyframes(
    video: Path,
    stage: Path,
    target: Path,
    frames: int,
    extractor: Callable[[Path, float, Path], None],
) -> dict[str, dict[str, object]]:
    directory = stage / "keyframes"
    directory.mkdir(mode=0o700)
    moments = _keyframe_moments(frames)
    records: dict[str, dict[str, object]] = {}
    for name, timestamp in moments.items():
        output = directory / f"{name}.png"
        try:
            extractor(video, timestamp, output)
        except SegmentRenderError:
            raise
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise SegmentRenderError("segment keyframe extraction failed") from None
        if not output.is_file():
            raise SegmentRenderError("segment keyframe is unavailable")
        digest, byte_count = _hash_file(output)
        records[name] = {
            "path": str(target / "keyframes" / output.name),
            "sha256": digest,
            "bytes": byte_count,
            "timestamp": timestamp,
        }
    return records


def _load_existing(
    target: Path,
    identity: str,
    segment_id: str,
    frames: int,
    family: str,
    composition: Mapping[str, object],
    arroll: _ApprovedArroll,
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    probe: Callable[[Path], Mapping[str, object]],
) -> RenderedSegment:
    try:
        entries = {entry.name: entry for entry in os.scandir(target)}
    except OSError:
        raise SegmentRenderError("existing segment generation is incomplete") from None
    if set(entries) != _FORMAL_OUTPUTS or any(
        not entries[name].is_file(follow_symlinks=False)
        for name in ("segment.mp4", "segment-manifest.json")
    ) or not entries["keyframes"].is_dir(follow_symlinks=False):
        raise SegmentRenderError("existing segment generation is incomplete")
    manifest = target / "segment-manifest.json"
    try:
        value = contract_artifacts.read_json_artifact(manifest)
        if set(value) != set(RenderedSegment.__dataclass_fields__):
            raise SegmentRenderError("existing segment generation is incomplete")
        rendered = RenderedSegment(**value)
    except (TypeError, ValueError, contract_artifacts.ContractArtifactError):
        raise SegmentRenderError("existing segment generation is incomplete") from None
    video = target / "segment.mp4"
    if (
        rendered.segment_id != segment_id
        or rendered.generation_identity != identity
        or rendered.video_path != str(video)
        or rendered.frames != frames
        or rendered.composition_family != family
        or rendered.composition != _plain(composition)
        or rendered.arroll_job_path != arroll.job_path
        or rendered.arroll_sha256 != arroll.sha256
        or rendered.arroll_bytes != arroll.byte_count
        or rendered.component_artifacts
        != [_artifact_identity(artifact) for artifact in artifacts]
    ):
        raise SegmentRenderError("existing segment generation has another identity")
    digest, byte_count = _hash_file(video)
    try:
        actual_probe = dict(probe(video))
    except SegmentRenderError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise SegmentRenderError("rendered segment probe failed") from None
    if (
        (digest, byte_count) != (rendered.video_sha256, rendered.video_bytes)
        or _hash_file(video) != (digest, byte_count)
        or rendered.output_probe != actual_probe
        or not _probe_matches(actual_probe, frames)
    ):
        raise SegmentRenderError("existing segment generation is incomplete")
    if type(rendered.keyframes) is not dict or set(rendered.keyframes) != set(
        _KEYFRAME_NAMES
    ):
        raise SegmentRenderError("existing segment generation is incomplete")
    keyframe_directory = target / "keyframes"
    try:
        keyframe_entries = {entry.name: entry for entry in os.scandir(keyframe_directory)}
    except OSError:
        raise SegmentRenderError("existing segment generation is incomplete") from None
    expected_keyframe_files = {f"{name}.png" for name in _KEYFRAME_NAMES}
    if set(keyframe_entries) != expected_keyframe_files or any(
        not entry.is_file(follow_symlinks=False) for entry in keyframe_entries.values()
    ):
        raise SegmentRenderError("existing segment generation is incomplete")
    moments = _keyframe_moments(frames)
    for name in _KEYFRAME_NAMES:
        record = rendered.keyframes[name]
        expected_path = target / "keyframes" / f"{name}.png"
        if (
            type(record) is not dict
            or set(record) != {"path", "sha256", "bytes", "timestamp"}
            or record["path"] != str(expected_path)
            or not _valid_sha(record["sha256"])
            or type(record["bytes"]) is not int
            or record["bytes"] <= 0
            or type(record["timestamp"]) not in {int, float}
            or float(record["timestamp"]) != moments[name]
            or _hash_file(expected_path) != (record["sha256"], record["bytes"])
        ):
            raise SegmentRenderError("existing segment generation is incomplete")
    return rendered


def _restore_rendered_value(
    value: object,
) -> tuple[
    RenderedSegment,
    tuple[broll_component_executor.ComponentArtifact, ...],
]:
    rendered_fields = set(RenderedSegment.__dataclass_fields__)
    artifact_fields = set(
        broll_component_executor.ComponentArtifact.__dataclass_fields__
    )
    if type(value) is not dict or set(value) != rendered_fields:
        raise SegmentRenderError("rendered segment record is invalid")
    component_values = value.get("component_artifacts")
    if type(component_values) is not list or any(
        type(item) is not dict or set(item) != artifact_fields
        for item in component_values
    ):
        raise SegmentRenderError("rendered component artifact record is invalid")
    try:
        rendered = RenderedSegment(**value)
        artifacts = tuple(
            broll_component_executor.ComponentArtifact(**item)
            for item in component_values
        )
    except (TypeError, ValueError):
        raise SegmentRenderError("rendered segment record is invalid") from None
    return rendered, artifacts


def load_rendered_segment_replay(
    job: state.JobState,
    segment: Mapping[str, Any],
    value: object,
    *,
    output_dir: Path,
    visual_plan_sha256: str,
    arroll_source: Path,
    arroll_sha256: str,
    arroll_bytes: int,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
) -> RenderedSegment:
    """Load one existing segment after its bytes and render record both match."""

    expected, artifacts = _restore_rendered_value(value)
    prepared = _prepare_render(job, segment, artifacts)
    arroll = _approve_aroll(
        job,
        Path(arroll_source),
        arroll_sha256,
        arroll_bytes,
    )
    _verify_current_inputs(job, artifacts, arroll)
    identity = generation_identity(
        job,
        segment,
        visual_plan_sha256,
        artifacts,
        arroll,
    )
    root_path = Path(output_dir)
    try:
        root_metadata = os.lstat(root_path)
    except OSError:
        raise SegmentRenderError("existing segment generation is incomplete") from None
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise SegmentRenderError("existing segment generation is incomplete")
    output_root = _OutputRoot.open(job, root_path)
    try:
        output_root.verify()
        replay_probe = (
            probe
            if probe is not None
            else lambda _path: dict(expected.output_probe)
        )
        result = _load_existing(
            output_root.path / str(segment.get("segment_id")),
            identity,
            str(segment.get("segment_id")),
            prepared.frames,
            prepared.family,
            prepared.recipe["composition"],
            arroll,
            artifacts,
            replay_probe,
        )
        if asdict(result) != _plain(value) or result != expected:
            raise SegmentRenderError("existing segment generation has another identity")
        _verify_current_inputs(job, artifacts, arroll)
        output_root.verify()
        return result
    finally:
        output_root.close()


def _render_segment_video(
    job: state.JobState,
    segment: Mapping[str, Any],
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    *,
    output_dir: Path,
    visual_plan_sha256: str,
    arroll_source: Path,
    arroll_sha256: str,
    arroll_bytes: int,
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
    allow_no_broll: bool,
) -> RenderedSegment:
    prepared = _prepare_render(job, segment, artifacts)
    if (prepared.recipe["mode"] == "none") is not allow_no_broll:
        raise SegmentRenderError("segment renderer does not match the approved mode")
    arroll = _approve_aroll(job, Path(arroll_source), arroll_sha256, arroll_bytes)
    identity = generation_identity(
        job, segment, visual_plan_sha256, artifacts, arroll
    )
    segment_id = str(segment["segment_id"])
    selected_probe = probe or _default_probe
    output_root = _OutputRoot.open(job, Path(output_dir))
    lock_descriptor: int | None = None
    stage: Path | None = None
    journal: dict[str, object] | None = None
    publication_replaced = False
    try:
        lock_descriptor = _open_segment_lock(output_root.path, segment_id)
        output_root.verify()
        _verify_current_inputs(job, artifacts, arroll)
        target = output_root.path / segment_id
        pending_publication = _recover_journal(
            output_root.path, job, segment_id, identity, target
        )
        if target.exists():
            try:
                target_metadata = os.lstat(target)
            except OSError:
                raise SegmentRenderError(
                    "existing segment generation is incomplete"
                ) from None
            if not stat.S_ISDIR(target_metadata.st_mode):
                raise SegmentRenderError("existing segment generation is incomplete")
            result = _load_existing(
                target,
                identity,
                segment_id,
                prepared.frames,
                prepared.family,
                prepared.recipe["composition"],
                arroll,
                artifacts,
                selected_probe,
            )
            if pending_publication is not None:
                _fsync_directory(output_root.path)
                _write_journal(
                    output_root.path, pending_publication, "published"
                )
                _remove_journal(output_root.path, segment_id)
            return result

        nonce = secrets.token_hex(16)
        stage = output_root.path / f".{segment_id}.stage-{nonce}"
        try:
            stage.mkdir(mode=0o700)
        except OSError:
            raise SegmentRenderError("segment staging could not be created") from None
        try:
            journal = _new_journal(job, segment_id, identity, nonce, stage)
            journal = _write_journal(output_root.path, journal, "planned")
            journal = _write_journal(output_root.path, journal, "rendering")
            arroll_snapshot, artifact_snapshots = _snapshot_inputs(
                job, artifacts, stage, arroll
            )
            graph = build_filter_graph(
                prepared.recipe, prepared.artifacts, frames=prepared.frames
            )
            stage_video = stage / "segment.mp4"
            command = _ffmpeg_command(
                arroll_snapshot,
                artifact_snapshots,
                artifacts,
                graph,
                stage_video,
                float(segment["start"]),
                prepared.frames,
            )
            try:
                (ffmpeg_runner or _default_ffmpeg_runner)(
                    command, max(240.0, prepared.frames * 1.25)
                )
            except (OSError, subprocess.SubprocessError):
                raise SegmentRenderError("component composition failed") from None
            if not stage_video.is_file():
                raise SegmentRenderError("component composition failed")
            journal = _write_journal(output_root.path, journal, "complete")
            before_probe = _hash_file(stage_video)
            try:
                output_probe = dict(selected_probe(stage_video))
            except SegmentRenderError:
                raise
            except BaseException as failure:
                if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                    raise
                raise SegmentRenderError("rendered segment probe failed") from None
            after_probe = _hash_file(stage_video)
            if before_probe != after_probe or not _probe_matches(
                output_probe, prepared.frames
            ):
                raise SegmentRenderError("rendered segment contract is invalid")
            keyframes = _keyframes(
                stage_video,
                stage,
                target,
                prepared.frames,
                frame_extractor or _default_frame_extractor,
            )
            if _hash_file(stage_video) != before_probe:
                raise SegmentRenderError(
                    "rendered segment changed during keyframe extraction"
                )
            shutil.rmtree(stage / "inputs")
            result = RenderedSegment(
                segment_id=segment_id,
                video_path=str(target / "segment.mp4"),
                video_sha256=before_probe[0],
                video_bytes=before_probe[1],
                frames=prepared.frames,
                generation_identity=identity,
                composition_family=prepared.family,
                composition=_plain(prepared.recipe["composition"]),
                arroll_job_path=arroll.job_path,
                arroll_sha256=arroll.sha256,
                arroll_bytes=arroll.byte_count,
                component_artifacts=[
                    _artifact_identity(artifact) for artifact in artifacts
                ],
                output_probe=output_probe,
                keyframes=keyframes,
            )
            try:
                contract_artifacts.write_json_artifact(
                    stage / "segment-manifest.json", asdict(result)
                )
            except contract_artifacts.ContractArtifactError:
                raise SegmentRenderError(
                    "segment manifest could not be recorded"
                ) from None
            for formal_path in (
                stage_video,
                *(stage / "keyframes" / f"{name}.png" for name in _KEYFRAME_NAMES),
                stage / "segment-manifest.json",
            ):
                _fsync_file(formal_path)
            if _stage_identity(stage) != journal["stage_identity"]:
                raise SegmentRenderError("render staging identity changed")
            _fsync_directory(stage / "keyframes")
            _fsync_directory(stage)
            journal = _write_journal(output_root.path, journal, "publishing")
            output_root.verify()
            if _stage_identity(stage) != journal["stage_identity"]:
                raise SegmentRenderError("render staging identity changed")
            os.replace(stage, target)
            stage = None
            publication_replaced = True
            if _stage_identity(target) != journal["stage_identity"]:
                raise SegmentRenderError("published directory identity changed")
            _fsync_directory(output_root.path)
            output_root.verify()
            journal = _write_journal(output_root.path, journal, "published")
            _remove_journal(output_root.path, segment_id)
            return result
        except _PreserveStageError as failure:
            if stage is not None and journal is not None:
                _write_journal(
                    output_root.path,
                    journal,
                    "exit_unconfirmed",
                    process_identity={"pid": failure.pid, "pgrp": failure.pgrp},
                )
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            if stage is not None and not publication_replaced:
                if (
                    journal is not None
                    and stage.exists()
                    and _stage_identity(stage) == journal["stage_identity"]
                ):
                    shutil.rmtree(stage, ignore_errors=True)
                    _remove_journal(output_root.path, segment_id)
            raise
    finally:
        if lock_descriptor is not None:
            _close_segment_lock(lock_descriptor)
        output_root.close()


def render_segment_video(
    job: state.JobState,
    segment: Mapping[str, Any],
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...],
    *,
    output_dir: Path,
    visual_plan_sha256: str,
    arroll_source: Path,
    arroll_sha256: str,
    arroll_bytes: int,
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
) -> RenderedSegment:
    """Compose one approved B-roll recipe from completed component artifacts."""

    return _render_segment_video(
        job,
        segment,
        artifacts,
        output_dir=output_dir,
        visual_plan_sha256=visual_plan_sha256,
        arroll_source=arroll_source,
        arroll_sha256=arroll_sha256,
        arroll_bytes=arroll_bytes,
        ffmpeg_runner=ffmpeg_runner,
        probe=probe,
        frame_extractor=frame_extractor,
        allow_no_broll=False,
    )


def render_arroll_segment(
    job: state.JobState,
    segment: Mapping[str, Any],
    *,
    artifacts: tuple[broll_component_executor.ComponentArtifact, ...] = (),
    output_dir: Path,
    visual_plan_sha256: str,
    arroll_source: Path,
    arroll_sha256: str,
    arroll_bytes: int,
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
) -> RenderedSegment:
    """Render approved full-frame A-roll, optionally with bound alpha annotations."""

    return _render_segment_video(
        job,
        segment,
        artifacts,
        output_dir=output_dir,
        visual_plan_sha256=visual_plan_sha256,
        arroll_source=arroll_source,
        arroll_sha256=arroll_sha256,
        arroll_bytes=arroll_bytes,
        ffmpeg_runner=ffmpeg_runner,
        probe=probe,
        frame_extractor=frame_extractor,
        allow_no_broll=True,
    )


def re_full_segment_id(value: str) -> bool:
    return (
        len(value) == 7
        and value.startswith("seg-")
        and value[4:].isdigit()
        and value[4:] != "000"
    )


def assemble_visual_track(
    segments: list[RenderedSegment],
    output: Path,
    *,
    assembler: Callable[[list[Path], Path], None] | None = None,
) -> Path:
    if not segments:
        raise SegmentRenderError("visual track has no segments")
    paths = [Path(segment.video_path) for segment in segments]
    output.parent.mkdir(parents=True, exist_ok=True)
    if assembler is not None:
        assembler(paths, output)
    else:
        command = [
            "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
            "-filter_complex_threads", "1",
        ]
        for path in paths:
            command.extend(["-threads", "1", "-i", str(path)])
        graph = ";".join(
            f"[{index}:v:0]settb=1/{FPS},setpts=N[v{index}]"
            for index in range(len(paths))
        )
        inputs = "".join(f"[v{index}]" for index in range(len(paths)))
        graph += (
            f";{inputs}concat=n={len(paths)}:v=1:a=0,"
            f"settb=1/{FPS},setpts=N[v]"
        )
        command.extend([
            "-filter_complex", graph, "-map", "[v]", "-an",
            "-c:v", "libx264", "-qp", "0", "-preset", "fast",
            "-threads", "4", "-pix_fmt", "yuv420p",
            "-fps_mode:v", "passthrough", "-enc_time_base:v", f"1:{FPS}",
            "-video_track_timescale", str(FPS * 1000), "-y", str(output),
        ])
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=max(300, sum(segment.frames for segment in segments) * 4),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            error = SegmentRenderError("segment concat failed")
            stderr = getattr(exc, "stderr", None)
            if stderr:
                error.add_note(stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else str(stderr))
            raise error from exc
    if not output.is_file():
        raise SegmentRenderError("visual track was not created")
    return output


__all__ = [
    "FPS",
    "WIDTH",
    "HEIGHT",
    "RENDERER_CONTRACT_VERSION",
    "RenderedSegment",
    "SegmentRenderError",
    "assemble_visual_track",
    "build_filter_graph",
    "expected_frames",
    "generation_identity",
    "load_rendered_segment_replay",
    "render_arroll_segment",
    "render_segment_video",
]

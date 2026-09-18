"""Render a five-family SemanticState avatar-composite review canary.

This maintenance tool consumes already-qualified case-2 artifacts and the real
segment compositor. It creates a new review directory; it never edits the
qualification evidence, registry, or a production Job. Human approval remains
an explicit later gate.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import NamedTuple


FAMILIES = ("replacement", "threshold", "delay", "hierarchy", "feedback")
FRAMES = 120
FPS = 24
WIDTH = 1080
HEIGHT = 1920
SAMPLE_FRAMES = {"entry": 10, "stable": 72, "exit_start": 108,
                 "exit_mid": 114, "last": 119}
PIXEL_QA_THRESHOLDS = {
    "stable_threshold": 4,
    "presence_threshold": 8,
    "exit_threshold": 4,
}


class SelectedCase(NamedTuple):
    family: str
    case_id: str
    folder: Path
    case_evidence: dict
    reviewed_registry: dict
    brief: dict
    recipe: dict
    execution: dict
    sample_bytes: bytes
    json_bytes_by_key: dict


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def json_bytes(value: bytes, *, label: str) -> dict:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not a JSON object") from error
    if type(parsed) is not dict:
        raise ValueError(f"{label} must contain one JSON object")
    return parsed


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def proof(path: Path, *, root: Path) -> dict:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def snapshot_bytes(path: Path, *, label: str, maximum: int = 16 * 1024 * 1024) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{label} snapshot cannot be opened") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= maximum:
            raise ValueError(f"{label} snapshot is not a bounded regular file")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"{label} snapshot ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise ValueError(f"{label} changed while being snapshotted")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def freeze_external_inputs(source_aroll: Path, avatar_review: Path) -> tuple[bytes, bytes]:
    source = snapshot_bytes(
        source_aroll, label="source A-roll", maximum=256 * 1024 * 1024
    )
    review = snapshot_bytes(avatar_review, label="avatar review")
    json_bytes(review, label="avatar review")
    return source, review


def confined_regular_file(base_root: Path, relative: str, *, label: str) -> Path:
    if (
        type(relative) is not str
        or not relative
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
    ):
        raise ValueError(f"{label} path is invalid")
    root = base_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path contains a symbolic link")
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError(f"{label} path escapes the evidence root") from None
    if not path.is_file():
        raise ValueError(f"{label} proof path is not a file")
    return path


def verified_bound_snapshot(
    base_root: Path,
    value: object,
    *,
    label: str,
    include_bytes: bool = False,
    maximum: int = 256 * 1024 * 1024,
) -> tuple[Path, bytes]:
    expected_fields = {"path", "sha256"}
    if include_bytes:
        expected_fields.add("bytes")
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError(f"{label} proof is invalid")
    relative = value.get("path")
    digest = value.get("sha256")
    if (
        type(relative) is not str
        or not relative
        or type(digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or (
            include_bytes
            and (type(value.get("bytes")) is not int or value["bytes"] < 0)
        )
    ):
        raise ValueError(f"{label} proof is invalid")
    path = confined_regular_file(base_root, relative, label=label)
    # Hash only the frozen bytes consumed below; a separate path hash would
    # reintroduce a validation-to-consumption race.
    content = snapshot_bytes(path, label=label, maximum=maximum)
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"{label} SHA-256 differs from reviewed qualification")
    if include_bytes and value["bytes"] != len(content):
        raise ValueError(f"{label} byte count differs from reviewed qualification")
    return path, content


def verified_snapshot(
    skill_root: Path, value: object, *, label: str
) -> tuple[Path, bytes]:
    return verified_bound_snapshot(skill_root, value, label=label)


def require_fields(value: object, expected: set[str], *, label: str) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{label} fields are invalid")
    return value


def validate_canary_receipt(
    skill_root: Path, receipt_path: Path, receipt: dict
) -> tuple[Path, bytes, Path, bytes]:
    """Validate the complete machine evidence frozen before human approval."""
    root = skill_root.resolve(strict=True)
    canary_root = receipt_path.parent.resolve(strict=True)
    expected_ids = [
        f"hd-talking-head/semantic-state-{family}" for family in FAMILIES
    ]
    require_fields(receipt, {
        "schema_version", "status", "human_approval_claimed", "scope",
        "project_root", "qualification_root", "qualification_evidence",
        "source_aroll", "avatar_review", "avatar", "cases", "montage",
        "contact_sheet", "invocations",
    }, label="canary receipt")
    project_root = receipt.get("project_root")
    qualification_root_value = receipt.get("qualification_root")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "machine_verified_pending_human_review"
        or receipt.get("human_approval_claimed") is not False
        or receipt.get("scope") != (
            "five reviewed-but-unregistered SemanticState case-2 clips "
            "composed with one measured head-and-shoulders avatar"
        )
        or type(project_root) is not str
        or not Path(project_root).is_absolute()
        or type(qualification_root_value) is not str
        or not Path(qualification_root_value).is_absolute()
    ):
        raise ValueError("canary receipt identity is invalid")
    qualification_root = Path(qualification_root_value).resolve(strict=True)
    try:
        qualification_root.relative_to(root)
    except ValueError:
        raise ValueError("canary receipt qualification root escapes the Skill") from None

    qualification = require_fields(
        receipt.get("qualification_evidence"),
        {"status", "report", "families"},
        label="canary receipt qualification evidence",
    )
    qualification_families = qualification.get("families")
    if (
        qualification.get("status") != "reviewed"
        or type(qualification_families) is not list
        or len(qualification_families) != len(FAMILIES)
    ):
        raise ValueError("canary receipt qualification evidence is invalid")
    report_path, _ = verified_snapshot(
        root, qualification.get("report"), label="qualification report"
    )
    if report_path != (qualification_root / "qualification-report.json").resolve(strict=True):
        raise ValueError("canary receipt qualification report is not canonical")

    reviewed_by_family = {}
    for family, template_id, evidence in zip(
        FAMILIES, expected_ids, qualification_families
    ):
        evidence = require_fields(
            evidence,
            {"family", "template_id", "reviewed_registry", "source_registry"},
            label=f"{family} qualification evidence",
        )
        if evidence.get("family") != family or evidence.get("template_id") != template_id:
            raise ValueError(f"{family} qualification identity is invalid")
        reviewed_registry_path, _ = verified_snapshot(
            root, evidence.get("reviewed_registry"),
            label=f"{family} reviewed registry",
        )
        source_registry_path, _ = verified_snapshot(
            root, evidence.get("source_registry"),
            label=f"{family} source registry",
        )
        if reviewed_registry_path != (
            qualification_root / family / "reviewed-registry.json"
        ).resolve(strict=True):
            raise ValueError(f"{family} reviewed registry is not canonical")
        if source_registry_path != (
            qualification_root / family / "qualification" / "source-registry.json"
        ).resolve(strict=True):
            raise ValueError(f"{family} source registry is not canonical")
        reviewed_by_family[family] = evidence

    source_aroll = require_fields(
        receipt.get("source_aroll"),
        {"declared_absolute_path", "declared_snapshot_sha256", "consumed_snapshot"},
        label="source A-roll receipt",
    )
    avatar_review = require_fields(
        receipt.get("avatar_review"),
        {"declared_absolute_path", "declared_snapshot_sha256", "consumed_snapshot"},
        label="avatar review receipt",
    )
    frozen_inputs = (
        (source_aroll, "frozen-external-inputs/source-aroll.mp4", "source A-roll"),
        (avatar_review, "frozen-external-inputs/avatar-review.json", "avatar review"),
    )
    frozen_input_paths = {}
    for value, expected_path, label in frozen_inputs:
        declared = value.get("declared_absolute_path")
        digest = value.get("declared_snapshot_sha256")
        if (
            type(declared) is not str
            or not Path(declared).is_absolute()
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError(f"{label} declared identity is invalid")
        consumed_path, consumed_bytes = verified_bound_snapshot(
            canary_root, value.get("consumed_snapshot"),
            label=f"{label} consumed snapshot", include_bytes=True,
        )
        if consumed_path != (canary_root / expected_path).resolve(strict=True):
            raise ValueError(f"{label} consumed snapshot is not canonical")
        if digest != hashlib.sha256(consumed_bytes).hexdigest():
            raise ValueError(f"{label} declared SHA-256 differs from consumed snapshot")
        frozen_input_paths[label] = consumed_path

    avatar = require_fields(
        receipt.get("avatar"), {"profile", "position", "crop"}, label="avatar"
    )
    profile = require_fields(
        avatar.get("profile"),
        {"schema_version", "framing", "source_sha256", "diameter", "border_width", "border_color"},
        label="avatar profile",
    )
    position = require_fields(
        avatar.get("position"), {"x", "y"}, label="avatar position"
    )
    crop = require_fields(avatar.get("crop"), {"size", "anchors"}, label="avatar crop")
    if (
        profile.get("schema_version") != 1
        or profile.get("framing") != "head-shoulders"
        or profile.get("source_sha256") != source_aroll["declared_snapshot_sha256"]
        or type(profile.get("diameter")) is not int
        or profile["diameter"] <= 0
        or type(profile.get("border_width")) is not int
        or profile["border_width"] < 0
        or type(profile.get("border_color")) is not str
        or any(type(position.get(key)) is not int for key in ("x", "y"))
        or type(crop.get("size")) is not int
        or crop["size"] <= 0
        or type(crop.get("anchors")) is not list
        or len(crop["anchors"]) < 2
    ):
        raise ValueError("avatar receipt is invalid")

    ffprobe = validation_tool("HD_FFPROBE", "ffprobe")
    ffmpeg = validation_tool("HD_FFMPEG", "ffmpeg")
    cases = receipt.get("cases")
    if type(cases) is not list or len(cases) != len(FAMILIES):
        raise ValueError("canary receipt does not contain exactly five cases")
    stable_frame_paths = []
    for family, template_id, case in zip(FAMILIES, expected_ids, cases):
        case = require_fields(case, {
            "family", "case_id", "template_id", "reviewed_registry",
            "reviewed_input", "consumed_snapshot", "composite", "media",
            "avatar_safe_area", "pixel_qa", "frames",
        }, label=f"{family} canary case")
        if (
            case.get("family") != family
            or case.get("case_id") != "case-2"
            or case.get("template_id") != template_id
            or case.get("reviewed_registry") != reviewed_by_family[family]["reviewed_registry"]
        ):
            raise ValueError(f"{family} canary case identity is invalid")

        reviewed_input = require_fields(
            case.get("reviewed_input"), {"brief", "recipe", "receipt", "sample"},
            label=f"{family} reviewed input",
        )
        reviewed_hashes = {}
        reviewed_names = {
            "brief": "brief.json", "recipe": "recipe.json",
            "receipt": "execution.json", "sample": "sample.mp4",
        }
        for key, name in reviewed_names.items():
            path, content = verified_snapshot(
                root, reviewed_input.get(key), label=f"{family} reviewed {key}"
            )
            if path != (qualification_root / family / "case-2" / name).resolve(strict=True):
                raise ValueError(f"{family} reviewed {key} is not canonical")
            reviewed_hashes[key] = hashlib.sha256(content).hexdigest()

        consumed = require_fields(
            case.get("consumed_snapshot"), {"brief", "recipe", "execution", "sample"},
            label=f"{family} consumed snapshots",
        )
        consumed_names = {
            "brief": ("brief.json", "brief"),
            "recipe": ("recipe.json", "recipe"),
            "execution": ("execution.json", "receipt"),
            "sample": ("sample.mp4", "sample"),
        }
        consumed_paths = {}
        for key, (name, reviewed_key) in consumed_names.items():
            path, content = verified_bound_snapshot(
                canary_root, consumed.get(key),
                label=f"{family} consumed {key}", include_bytes=True,
            )
            if path != (canary_root / family / "reviewed-input" / name).resolve(strict=True):
                raise ValueError(f"{family} consumed {key} is not canonical")
            if hashlib.sha256(content).hexdigest() != reviewed_hashes[reviewed_key]:
                raise ValueError(f"{family} consumed {key} differs from reviewed input")
            consumed_paths[key] = path

        composite_path, _ = verified_bound_snapshot(
            canary_root, case.get("composite"),
            label=f"{family} composite", include_bytes=True,
        )
        if composite_path != (canary_root / family / "composite.mp4").resolve(strict=True):
            raise ValueError(f"{family} composite is not canonical")
        media = require_fields(
            case.get("media"),
            {"width", "height", "fps", "frames", "video_streams", "audio_streams", "codec", "pixel_format"},
            label=f"{family} media",
        )
        if (
            media.get("width") != WIDTH
            or media.get("height") != HEIGHT
            or media.get("fps") != FPS
            or media.get("frames") != FRAMES
            or media.get("video_streams") != 1
            or media.get("audio_streams") != 0
            or media.get("codec") != "h264"
            or media.get("pixel_format") not in {"yuv420p", "yuvj420p"}
        ):
            raise ValueError(f"{family} media contract is invalid")
        observed_media = probe_exact_video(
            ffprobe, composite_path, expected_frames=FRAMES,
            label=f"{family} composite",
        )
        if observed_media != media:
            raise ValueError(f"{family} media receipt differs from the actual composite")

        safe = require_fields(
            case.get("avatar_safe_area"),
            {"x", "y", "outer_size", "soft_safe_bottom", "status"},
            label=f"{family} avatar safe area",
        )
        outer_size = profile["diameter"] + 2 * profile["border_width"]
        if (
            safe.get("x") != position["x"]
            or safe.get("y") != position["y"]
            or safe.get("outer_size") != outer_size
            or safe.get("soft_safe_bottom") != 1700
            or safe.get("status") != "verified"
            or safe["y"] + outer_size > safe["soft_safe_bottom"]
        ):
            raise ValueError(f"{family} avatar safe area is invalid")

        pixel = require_fields(
            case.get("pixel_qa"),
            {"stable_outside_avatar_mae", "stable_payoff_mae", "avatar_presence_mae", "final_full_frame_mae", "final_avatar_roi_mae", "stable_threshold", "presence_threshold", "exit_threshold", "status"},
            label=f"{family} pixel QA",
        )
        numeric_fields = set(pixel) - {"status"}
        if (
            pixel.get("status") != "verified"
            or any(type(pixel.get(key)) not in (int, float) for key in numeric_fields)
            or pixel["stable_threshold"] != PIXEL_QA_THRESHOLDS["stable_threshold"]
            or pixel["presence_threshold"] != PIXEL_QA_THRESHOLDS["presence_threshold"]
            or pixel["exit_threshold"] != PIXEL_QA_THRESHOLDS["exit_threshold"]
            or pixel["stable_outside_avatar_mae"] >= pixel["stable_threshold"]
            or pixel["stable_payoff_mae"] >= pixel["stable_threshold"]
            or pixel["avatar_presence_mae"] <= pixel["presence_threshold"]
            or pixel["final_full_frame_mae"] >= pixel["exit_threshold"]
            or pixel["final_avatar_roi_mae"] >= pixel["exit_threshold"]
        ):
            raise ValueError(f"{family} pixel QA is invalid")

        frames = require_fields(
            case.get("frames"), set(SAMPLE_FRAMES), label=f"{family} frame proofs"
        )
        frame_paths = {}
        for role, frame_number in SAMPLE_FRAMES.items():
            frame = require_fields(
                frames.get(role), {"frame", "path", "sha256", "bytes"},
                label=f"{family} {role} frame",
            )
            if frame.get("frame") != frame_number:
                raise ValueError(f"{family} {role} frame number is invalid")
            path, _ = verified_bound_snapshot(
                canary_root,
                {key: frame[key] for key in ("path", "sha256", "bytes")},
                label=f"{family} {role} frame", include_bytes=True,
            )
            expected = canary_root / family / "frames" / f"{role}-{frame_number:03}.png"
            if path != expected.resolve(strict=True):
                raise ValueError(f"{family} {role} frame is not canonical")
            frame_paths[role] = path

        avatar_box = (
            position["x"], position["y"],
            position["x"] + outer_size, position["y"] + outer_size,
        )
        with tempfile.TemporaryDirectory(
            prefix=f"semantic-canary-{family}-pixel-qa-"
        ) as directory:
            scratch = Path(directory)
            original_stable = scratch / "reviewed-sample-stable.png"
            source_last = scratch / "source-aroll-last.png"
            try:
                extract_frame(
                    ffmpeg, consumed_paths["sample"], SAMPLE_FRAMES["stable"],
                    original_stable, [],
                )
                extract_frame(
                    ffmpeg, frozen_input_paths["source A-roll"], SAMPLE_FRAMES["last"],
                    source_last, [],
                )
                observed_pixel = assert_pixel_qa(
                    original_stable,
                    frame_paths["stable"],
                    source_last,
                    frame_paths["last"],
                    avatar_box,
                    **PIXEL_QA_THRESHOLDS,
                )
            except AssertionError as error:
                raise ValueError(
                    f"{family} pixel QA recomputation failed: {error}"
                ) from None
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                raise ValueError(
                    f"{family} pixel QA source frame decode failed"
                ) from error
        for key in (
            "stable_outside_avatar_mae", "stable_payoff_mae",
            "avatar_presence_mae", "final_full_frame_mae",
            "final_avatar_roi_mae",
        ):
            if not math.isclose(pixel[key], observed_pixel[key], rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"{family} pixel QA receipt differs from recomputation")
        stable_frame_paths.append(frame_paths["stable"])

    montage = require_fields(
        receipt.get("montage"), {"path", "sha256", "bytes", "frames", "duration_sec"},
        label="canary montage",
    )
    montage_path, montage_bytes = verified_bound_snapshot(
        canary_root,
        {key: montage[key] for key in ("path", "sha256", "bytes")},
        label="canary montage", include_bytes=True,
    )
    if (
        montage_path != (canary_root / "semantic-state-5family-avatar-canary.mp4").resolve(strict=True)
        or montage.get("frames") != FRAMES * len(FAMILIES)
        or montage.get("duration_sec") != 25
    ):
        raise ValueError("canary montage contract is invalid")
    probe_exact_video(
        ffprobe, montage_path, expected_frames=FRAMES * len(FAMILIES),
        label="canary montage",
    )
    verify_montage_sequence(ffmpeg, montage_path, stable_frame_paths)
    contact = require_fields(
        receipt.get("contact_sheet"), {"path", "sha256", "bytes"},
        label="canary contact sheet",
    )
    contact_path, contact_bytes = verified_bound_snapshot(
        canary_root, contact, label="canary contact sheet", include_bytes=True,
    )
    if contact_path != (canary_root / "contact-sheet.png").resolve(strict=True):
        raise ValueError("canary contact sheet is not canonical")

    invocations = receipt.get("invocations")
    if type(invocations) is not list or not invocations:
        raise ValueError("canary receipt invocations are invalid")
    for invocation in invocations:
        invocation = require_fields(
            invocation, {"argv", "exit_code", "stderr_tail"},
            label="canary invocation",
        )
        if (
            type(invocation.get("argv")) is not list
            or not invocation["argv"]
            or any(type(item) is not str or not item for item in invocation["argv"])
            or invocation.get("exit_code") != 0
            or type(invocation.get("stderr_tail")) is not str
        ):
            raise ValueError("canary receipt invocation is invalid")
    return montage_path, montage_bytes, contact_path, contact_bytes


def validate_human_approval(skill_root: Path, review_path: Path) -> dict:
    """Validate a separate human decision bound to the frozen canary bytes."""
    root = skill_root.resolve(strict=True)
    review_path = review_path.resolve(strict=True)
    try:
        review_path.relative_to(root)
    except ValueError:
        raise ValueError("human approval must be inside the master Skill") from None
    review = json_bytes(
        snapshot_bytes(review_path, label="human approval"), label="human approval"
    )
    expected_fields = {
        "schema_version", "status", "human_approval_claimed", "scope",
        "reviewer", "reviewed_at", "approval_reference", "families",
        "template_ids", "canary_receipt", "montage", "contact_sheet",
    }
    expected_ids = [
        f"hd-talking-head/semantic-state-{family}" for family in FAMILIES
    ]
    if (
        set(review) != expected_fields
        or review.get("schema_version") != 1
        or review.get("status") != "approved"
        or review.get("human_approval_claimed") is not True
        or review.get("scope") != "five-family SemanticState avatar-composite canary"
        or review.get("reviewer") != "User"
        or type(review.get("approval_reference")) is not str
        or not review["approval_reference"].startswith("thread-")
        or type(review.get("reviewed_at")) is not str
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", review["reviewed_at"]) is None
        or review.get("families") != list(FAMILIES)
        or review.get("template_ids") != expected_ids
    ):
        raise ValueError("human approval fields are invalid")

    receipt_path, receipt_bytes = verified_snapshot(
        root, review.get("canary_receipt"), label="canary receipt"
    )
    montage_path, montage_bytes = verified_snapshot(
        root, review.get("montage"), label="montage"
    )
    contact_path, contact_bytes = verified_snapshot(
        root, review.get("contact_sheet"), label="contact sheet"
    )
    receipt = json_bytes(receipt_bytes, label="canary receipt")
    receipt_montage_path, receipt_montage_bytes, receipt_contact_path, receipt_contact_bytes = (
        validate_canary_receipt(root, receipt_path, receipt)
    )
    if montage_path.resolve() != receipt_montage_path:
        raise ValueError("approved montage path differs from canary receipt")
    if contact_path.resolve() != receipt_contact_path:
        raise ValueError("approved contact sheet path differs from canary receipt")
    if hashlib.sha256(receipt_montage_bytes).hexdigest() != hashlib.sha256(montage_bytes).hexdigest():
        raise ValueError("montage SHA-256 differs from canary receipt")
    if hashlib.sha256(receipt_contact_bytes).hexdigest() != hashlib.sha256(contact_bytes).hexdigest():
        raise ValueError("contact sheet SHA-256 differs from canary receipt")
    return copy.deepcopy(review)


def select_reviewed_cases(
    skill_root: Path, qualification_root: Path
) -> tuple[list[SelectedCase], dict]:
    skill_root = skill_root.resolve(strict=True)
    qualification_root = qualification_root.resolve(strict=True)
    try:
        qualification_root.relative_to(skill_root)
    except ValueError:
        raise ValueError("qualification root must be inside the master Skill") from None
    report_path = qualification_root / "qualification-report.json"
    report_bytes = snapshot_bytes(report_path, label="qualification report")
    report = json_bytes(report_bytes, label="qualification report")
    families = report.get("families")
    if (
        report.get("status") != "reviewed"
        or report.get("human_approval_claimed") is not False
        or type(families) is not list
        or [item.get("family") for item in families if type(item) is dict] != list(FAMILIES)
    ):
        raise ValueError("qualification report is not the reviewed five-family set")

    selected = []
    report_records = []
    for family, report_item in zip(FAMILIES, families):
        template_id = f"hd-talking-head/semantic-state-{family}"
        if (
            set(report_item) != {
                "family", "template_id", "case_count", "action_frames_verified",
                "reviewed_registry",
            }
            or report_item.get("template_id") != template_id
            or report_item.get("case_count") != 2
            or report_item.get("action_frames_verified") != 6
        ):
            raise ValueError(f"{family} qualification summary is invalid")
        registry_path, registry_bytes = verified_snapshot(
            skill_root, report_item["reviewed_registry"],
            label=f"{family} reviewed registry",
        )
        registry = json_bytes(registry_bytes, label=f"{family} reviewed registry")
        templates = registry.get("templates")
        if type(templates) is not list or len(templates) != 1:
            raise ValueError(f"{family} reviewed registry must contain one template")
        template = templates[0]
        execution_qa = template.get("execution_qa") if type(template) is dict else None
        cases = execution_qa.get("cases") if type(execution_qa) is dict else None
        if (
            type(template) is not dict
            or type(execution_qa) is not dict
            or template.get("template_id") != template_id
            or template.get("semantic_families") != [family]
            or template.get("visual_qa", {}).get("status") != "approved"
            or template.get("action_sequence_qa", {}).get("status") != "approved"
            or execution_qa.get("status") != "reviewed"
            or type(cases) is not list
            or len(cases) != 2
        ):
            raise ValueError(f"{family} reviewed template evidence is invalid")
        source_registry_path, source_registry_bytes = verified_snapshot(
            skill_root, execution_qa.get("source_registry"),
            label=f"{family} source registry",
        )
        expected_folder = qualification_root / family / "case-2"
        expected = {
            "brief": expected_folder / "brief.json",
            "recipe": expected_folder / "recipe.json",
            "receipt": expected_folder / "execution.json",
            "sample": expected_folder / "sample.mp4",
        }
        selected_case = None
        for case in cases:
            if type(case) is not dict:
                continue
            sample = case.get("sample")
            if type(sample) is dict and sample.get("path") == expected["sample"].relative_to(skill_root).as_posix():
                selected_case = case
                break
        if selected_case is None:
            raise ValueError(f"{family} reviewed registry has no case-2 evidence")
        checked_case = {}
        frozen = {}
        for key, expected_path in expected.items():
            actual, content = verified_snapshot(
                skill_root, selected_case.get(key), label=f"{family} case-2 {key}"
            )
            if actual != expected_path.resolve(strict=True):
                raise ValueError(f"{family} case-2 {key} path is not canonical")
            checked_case[key] = copy.deepcopy(selected_case[key])
            frozen[key] = content
        selected.append(SelectedCase(
            family, "case-2", expected_folder, checked_case,
            copy.deepcopy(report_item["reviewed_registry"]),
            json_bytes(frozen["brief"], label=f"{family} case-2 brief"),
            json_bytes(frozen["recipe"], label=f"{family} case-2 recipe"),
            json_bytes(frozen["receipt"], label=f"{family} case-2 execution"),
            frozen["sample"],
            {key: frozen[key] for key in ("brief", "recipe", "receipt")},
        ))
        report_records.append({
            "family": family,
            "template_id": template_id,
            "reviewed_registry": copy.deepcopy(report_item["reviewed_registry"]),
            "source_registry": {
                "path": source_registry_path.relative_to(skill_root).as_posix(),
                "sha256": hashlib.sha256(source_registry_bytes).hexdigest(),
            },
        })
    return selected, {
        "status": "reviewed",
        "report": {
            "path": report_path.relative_to(skill_root).as_posix(),
            "sha256": hashlib.sha256(report_bytes).hexdigest(),
        },
        "families": report_records,
    }


def with_avatar(recipe: dict, avatar: dict) -> dict:
    composed = copy.deepcopy(recipe)
    composition = composed.get("composition")
    components = composed.get("components")
    if (
        type(composition) is not dict
        or composition.get("presenter_mode") != "bottom_window"
        or type(components) is not list
        or len(components) != 1
    ):
        raise ValueError("qualified recipe is not a single bottom-window composition")
    composition["avatar"] = copy.deepcopy(avatar)
    return composed


def load_bound_avatar(review: dict, source_aroll: Path) -> dict:
    avatar = copy.deepcopy(review.get("avatar"))
    if type(avatar) is not dict or type(avatar.get("profile")) is not dict:
        raise ValueError("composition review does not contain an avatar profile")
    if avatar["profile"].get("source_sha256") != sha256(source_aroll):
        raise ValueError("avatar profile source SHA-256 differs from the source A-roll")
    return avatar


def checked_artifact_payload(execution: dict) -> dict:
    artifact = execution.get("artifact")
    if type(artifact) is not dict:
        raise ValueError("execution artifact is missing")
    probe = artifact.get("media_probe")
    if (
        artifact.get("status") != "success"
        or artifact.get("artifact_media_type") != "video"
        or type(probe) is not dict
        or probe.get("width") != WIDTH
        or probe.get("height") != HEIGHT
        or float(probe.get("fps", 0)) != FPS
        or probe.get("frame_count") != FRAMES
    ):
        raise ValueError("qualified artifact must be a complete 1080x1920 video with 120 frames")
    return copy.deepcopy(artifact)


def run_command(argv: list[str], records: list[dict], *, timeout: int = 180) -> str:
    process = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    records.append({
        "argv": argv,
        "exit_code": process.returncode,
        "stderr_tail": process.stderr[-4000:],
    })
    if process.returncode:
        raise RuntimeError(
            f"command failed with exit {process.returncode}: {process.stderr[-1200:]}"
        )
    return process.stdout


def validation_tool(environment_name: str, executable: str) -> Path:
    configured = os.environ.get(environment_name)
    candidate = configured or shutil.which(executable)
    if not candidate:
        raise ValueError(f"media probe tool is unavailable: {executable}")
    path = Path(candidate).resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"media probe tool is not executable: {executable}")
    return path


def probe_exact_video(
    ffprobe: Path, video: Path, *, expected_frames: int, label: str
) -> dict:
    try:
        raw = run_command([
            str(ffprobe), "-v", "error", "-count_frames", "-show_streams",
            "-of", "json", str(video),
        ], [], timeout=20)
        streams = json.loads(raw).get("streams", [])
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise ValueError(f"{label} media probe failed") from error
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        raise ValueError(f"{label} media probe found an invalid stream layout")
    stream = video_streams[0]
    try:
        frames = int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} media probe has an invalid frame count") from error
    if (
        stream.get("width") != WIDTH
        or stream.get("height") != HEIGHT
        or stream.get("avg_frame_rate") != "24/1"
        or frames != expected_frames
    ):
        raise ValueError(
            f"{label} media probe differs from 1080x1920/24fps/{expected_frames} frames"
        )
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "frames": frames,
        "video_streams": 1,
        "audio_streams": 0,
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
    }


def verify_montage_sequence(
    ffmpeg: Path, montage: Path, stable_frames: list[Path]
) -> None:
    if len(stable_frames) != len(FAMILIES):
        raise ValueError("canary montage sequence lacks five stable frame proofs")
    with tempfile.TemporaryDirectory(prefix="semantic-canary-sequence-") as directory:
        scratch = Path(directory)
        for index, stable in enumerate(stable_frames):
            frame_number = index * FRAMES + SAMPLE_FRAMES["stable"]
            decoded = scratch / f"segment-{index:02}.png"
            try:
                run_command([
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-threads", "1", "-i", str(montage), "-vf",
                    f"select=eq(n\\,{frame_number})", "-frames:v", "1",
                    "-threads", "1", str(decoded),
                ], [], timeout=20)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                raise ValueError("canary montage sequence decode failed") from error
            if image_mae(stable, decoded) >= 2:
                raise ValueError(
                    f"canary montage segment {index + 1} differs from its composite"
                )


def probe_video(ffprobe: Path, video: Path, records: list[dict]) -> dict:
    raw = run_command([
        str(ffprobe), "-v", "error", "-count_frames", "-show_streams",
        "-of", "json", str(video),
    ], records)
    value = json.loads(raw)
    streams = value.get("streams", [])
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        raise ValueError("canary must have one video stream and no audio")
    stream = video_streams[0]
    frames = int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0)
    if (
        stream.get("width") != WIDTH
        or stream.get("height") != HEIGHT
        or stream.get("avg_frame_rate") != "24/1"
        or frames != FRAMES
    ):
        raise ValueError("canary media contract differs from 1080x1920/24fps/120 frames")
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "frames": frames,
        "video_streams": 1,
        "audio_streams": 0,
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
    }


def extract_frame(
    ffmpeg: Path,
    video: Path,
    frame: int,
    destination: Path,
    records: list[dict],
) -> None:
    run_command([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-threads", "1", "-i", str(video), "-vf", f"select=eq(n\\,{frame})",
        "-frames:v", "1", "-threads", "1", str(destination),
    ], records)


def image_mae(first: Path, second: Path, *, crop=None) -> float:
    from PIL import Image, ImageChops, ImageStat

    with Image.open(first) as left_source, Image.open(second) as right_source:
        left = left_source.convert("RGB")
        right = right_source.convert("RGB")
        if crop is not None:
            left = left.crop(crop)
            right = right.crop(crop)
        if left.size != right.size:
            raise ValueError("pixel evidence dimensions differ")
        difference = ImageChops.difference(left, right)
        return sum(ImageStat.Stat(difference).mean) / 3


def masked_mae(
    first: Path,
    second: Path,
    *,
    excluded_box: tuple[int, int, int, int],
    region: tuple[int, int, int, int] | None = None,
) -> float:
    from PIL import Image, ImageChops, ImageDraw, ImageStat

    with Image.open(first) as left_source, Image.open(second) as right_source:
        left = left_source.convert("RGB")
        right = right_source.convert("RGB")
        if left.size != right.size:
            raise ValueError("pixel evidence dimensions differ")
        mask = Image.new("L", left.size, 255)
        ImageDraw.Draw(mask).rectangle(excluded_box, fill=0)
        difference = ImageChops.difference(left, right)
        if region is not None:
            difference = difference.crop(region)
            mask = mask.crop(region)
        if mask.getbbox() is None:
            raise ValueError("pixel evidence mask is empty")
        return sum(ImageStat.Stat(difference, mask=mask).mean) / 3


def assert_pixel_qa(
    poster: Path,
    stable: Path,
    source_last: Path,
    composite_last: Path,
    avatar_box: tuple[int, int, int, int],
    *,
    stable_threshold: float = 4,
    presence_threshold: float = 8,
    exit_threshold: float = 4,
) -> dict:
    from PIL import Image

    with Image.open(poster) as image:
        width, height = image.size
    payoff_region = (0, round(height * 0.70), width, round(height * 0.89))
    payoff_mae = masked_mae(
        poster, stable, excluded_box=avatar_box, region=payoff_region
    )
    if payoff_mae >= stable_threshold:
        raise AssertionError(f"stable payoff drift MAE={payoff_mae:.3f}")
    outside_mae = masked_mae(poster, stable, excluded_box=avatar_box)
    if outside_mae >= stable_threshold:
        raise AssertionError(f"stable poster drift MAE={outside_mae:.3f}")
    presence_mae = image_mae(poster, stable, crop=avatar_box)
    if presence_mae <= presence_threshold:
        raise AssertionError(f"avatar is absent or visually unchanged MAE={presence_mae:.3f}")
    exit_roi_mae = image_mae(source_last, composite_last, crop=avatar_box)
    if exit_roi_mae >= exit_threshold:
        raise AssertionError(f"exit avatar ROI residue MAE={exit_roi_mae:.3f}")
    exit_full_mae = image_mae(source_last, composite_last)
    if exit_full_mae >= exit_threshold:
        raise AssertionError(f"final A-roll return drift MAE={exit_full_mae:.3f}")
    return {
        "stable_outside_avatar_mae": outside_mae,
        "stable_payoff_mae": payoff_mae,
        "avatar_presence_mae": presence_mae,
        "final_full_frame_mae": exit_full_mae,
        "final_avatar_roi_mae": exit_roi_mae,
        "stable_threshold": stable_threshold,
        "presence_threshold": presence_threshold,
        "exit_threshold": exit_threshold,
        "status": "verified",
    }


@contextmanager
def owned_staging(target: Path):
    if target.exists():
        raise ValueError("output directory must be new")
    if not target.parent.is_dir():
        raise ValueError("output parent must already exist")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        yield staging
        if target.exists():
            raise ValueError("output directory appeared during publication")
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def montage_command(ffmpeg: Path, clips: list[Path], output: Path) -> list[str]:
    if len(clips) != len(FAMILIES):
        raise ValueError("review montage requires exactly five clips")
    argv = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-filter_complex_threads", "1", "-threads", "1",
    ]
    for clip in clips:
        argv.extend(("-i", str(clip)))
    inputs = "".join(f"[{index}:v]" for index in range(len(clips)))
    argv.extend((
        "-filter_complex", f"{inputs}concat=n={len(clips)}:v=1:a=0[out]",
        "-map", "[out]", "-an", "-frames:v", str(FRAMES * len(clips)),
        "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(output),
    ))
    return argv


def make_contact_sheet(frames: list[tuple[str, Path]], destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    thumb_size = (270, 480)
    label_height = 44
    canvas = Image.new("RGB", (thumb_size[0] * len(frames), thumb_size[1] + label_height), "#111111")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (label, frame) in enumerate(frames):
        with Image.open(frame) as source:
            thumb = source.convert("RGB").resize(thumb_size)
        x = index * thumb_size[0]
        canvas.paste(thumb, (x, 0))
        draw.text((x + 12, thumb_size[1] + 14), label, fill="white", font=font)
    canvas.save(destination, format="PNG")


def replace_staging_path(value: object, staging: Path) -> object:
    if isinstance(value, str):
        return value.replace(str(staging), "$CANARY")
    if isinstance(value, list):
        return [replace_staging_path(item, staging) for item in value]
    if isinstance(value, dict):
        return {key: replace_staging_path(item, staging) for key, item in value.items()}
    return value


def render_into(
    args: argparse.Namespace,
    *,
    project_root: Path,
    qualification_root: Path,
    source_aroll_declared_path: Path,
    avatar_review_declared_path: Path,
    source_aroll_bytes: bytes,
    avatar_review_bytes: bytes,
    output: Path,
) -> dict:
    from edit.hd.tools import avatar_profile, segment_render
    from edit.hd.tools.broll_component_executor import ComponentArtifact

    skill_root = Path(__file__).resolve().parents[1]
    input_dir = output / "frozen-external-inputs"
    input_dir.mkdir()
    source_aroll = input_dir / "source-aroll.mp4"
    avatar_review_path = input_dir / "avatar-review.json"
    source_aroll.write_bytes(source_aroll_bytes)
    avatar_review_path.write_bytes(avatar_review_bytes)
    review = json_bytes(avatar_review_bytes, label="avatar review")
    avatar = load_bound_avatar(review, source_aroll)
    if avatar["profile"]["source_sha256"] != hashlib.sha256(source_aroll_bytes).hexdigest():
        raise ValueError("avatar profile is not bound to the frozen source A-roll")
    avatar_profile.validate_avatar(avatar, frames=FRAMES)
    selected, qualification_evidence = select_reviewed_cases(
        skill_root, qualification_root
    )
    records: list[dict] = []
    case_receipts = []
    stable_frames: list[tuple[str, Path]] = []

    for item in selected:
        family_dir = output / item.family
        family_dir.mkdir()
        snapshot_dir = family_dir / "reviewed-input"
        snapshot_dir.mkdir()
        snapshot_names = {
            "brief": "brief.json", "recipe": "recipe.json",
            "receipt": "execution.json",
        }
        for key, name in snapshot_names.items():
            (snapshot_dir / name).write_bytes(item.json_bytes_by_key[key])
        sample_path = snapshot_dir / "sample.mp4"
        sample_path.write_bytes(item.sample_bytes)
        recipe = copy.deepcopy(item.recipe)
        brief = copy.deepcopy(item.brief)
        template_id = f"hd-talking-head/semantic-state-{item.family}"
        components = recipe.get("components")
        if (
            brief.get("motion", {}).get("family") != item.family
            or type(components) is not list
            or len(components) != 1
            or components[0].get("template_id") != template_id
        ):
            raise ValueError(f"{item.family} case-2 semantic identity is invalid")
        artifact_payload = checked_artifact_payload(copy.deepcopy(item.execution))
        if (
            artifact_payload.get("output_sha256") != hashlib.sha256(item.sample_bytes).hexdigest()
            or artifact_payload.get("component_id") != f"semantic-state-{item.family}"
        ):
            raise ValueError(f"{item.family} sample differs from its execution receipt")
        artifact = ComponentArtifact(**artifact_payload)
        composed_recipe = with_avatar(recipe, avatar)
        graph = segment_render.build_filter_graph(
            composed_recipe, (artifact,), frames=FRAMES
        )
        video = family_dir / "composite.mp4"
        run_command([
            str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-filter_complex_threads", "1", "-threads", "1",
            "-i", str(source_aroll), "-i", str(sample_path),
            "-filter_complex", graph, "-map", "[out]", "-an",
            "-frames:v", str(FRAMES), "-c:v", "libx264", "-threads", "1",
            "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(video),
        ], records, timeout=300)
        media = probe_video(args.ffprobe, video, records)

        frame_dir = family_dir / "frames"
        frame_dir.mkdir()
        frame_proofs = {}
        for role, frame in SAMPLE_FRAMES.items():
            path = frame_dir / f"{role}-{frame:03}.png"
            extract_frame(args.ffmpeg, video, frame, path, records)
            frame_proofs[role] = {"frame": frame, **proof(path, root=output)}
        original_stable = frame_dir / "original-stable-072.png"
        source_last = frame_dir / "source-last-119.png"
        extract_frame(args.ffmpeg, sample_path, SAMPLE_FRAMES["stable"], original_stable, records)
        extract_frame(args.ffmpeg, source_aroll, SAMPLE_FRAMES["last"], source_last, records)

        outer = avatar["profile"]["diameter"] + 2 * avatar["profile"]["border_width"]
        avatar_box = (
            avatar["position"]["x"], avatar["position"]["y"],
            avatar["position"]["x"] + outer, avatar["position"]["y"] + outer,
        )
        try:
            pixel_qa = assert_pixel_qa(
                original_stable,
                frame_dir / "stable-072.png",
                source_last,
                frame_dir / "last-119.png",
                avatar_box,
            )
        except AssertionError as error:
            raise AssertionError(f"{item.family}: {error}") from None
        stable_frames.append((item.family, frame_dir / "stable-072.png"))
        case_receipts.append({
            "family": item.family,
            "case_id": item.case_id,
            "template_id": template_id,
            "reviewed_registry": item.reviewed_registry,
            "reviewed_input": item.case_evidence,
            "consumed_snapshot": {
                "brief": proof(snapshot_dir / "brief.json", root=output),
                "recipe": proof(snapshot_dir / "recipe.json", root=output),
                "execution": proof(snapshot_dir / "execution.json", root=output),
                "sample": proof(sample_path, root=output),
            },
            "composite": proof(video, root=output),
            "media": media,
            "avatar_safe_area": {
                "x": avatar["position"]["x"],
                "y": avatar["position"]["y"],
                "outer_size": outer,
                "soft_safe_bottom": 1700,
                "status": "verified",
            },
            "pixel_qa": pixel_qa,
            "frames": frame_proofs,
        })

    montage = output / "semantic-state-5family-avatar-canary.mp4"
    clips = [output / family / "composite.mp4" for family in FAMILIES]
    run_command(montage_command(args.ffmpeg, clips, montage), records, timeout=300)
    montage_raw = run_command([
        str(args.ffprobe), "-v", "error", "-show_streams", "-of", "json", str(montage),
    ], records)
    montage_streams = json.loads(montage_raw).get("streams", [])
    montage_video = [stream for stream in montage_streams if stream.get("codec_type") == "video"]
    if len(montage_video) != 1 or any(stream.get("codec_type") == "audio" for stream in montage_streams):
        raise ValueError("review montage stream contract is invalid")
    montage_frames = int(montage_video[0].get("nb_frames") or 0)
    if montage_frames != FRAMES * len(FAMILIES):
        raise ValueError("review montage does not contain all five exact clips")

    contact_sheet = output / "contact-sheet.png"
    make_contact_sheet(stable_frames, contact_sheet)
    receipt = {
        "schema_version": 1,
        "status": "machine_verified_pending_human_review",
        "human_approval_claimed": False,
        "scope": "five reviewed-but-unregistered SemanticState case-2 clips composed with one measured head-and-shoulders avatar",
        "project_root": str(project_root),
        "qualification_root": str(qualification_root),
        "qualification_evidence": qualification_evidence,
        "source_aroll": {
            "declared_absolute_path": str(source_aroll_declared_path),
            "declared_snapshot_sha256": hashlib.sha256(source_aroll_bytes).hexdigest(),
            "consumed_snapshot": proof(source_aroll, root=output),
        },
        "avatar_review": {
            "declared_absolute_path": str(avatar_review_declared_path),
            "declared_snapshot_sha256": hashlib.sha256(avatar_review_bytes).hexdigest(),
            "consumed_snapshot": proof(avatar_review_path, root=output),
        },
        "avatar": avatar,
        "cases": case_receipts,
        "montage": {**proof(montage, root=output), "frames": montage_frames, "duration_sec": 25},
        "contact_sheet": proof(contact_sheet, root=output),
        "invocations": replace_staging_path(records, output),
    }
    write_json(output / "canary-receipt.json", receipt)
    return receipt


def render(args: argparse.Namespace) -> Path:
    project_root = args.project_root.resolve(strict=True)
    qualification_root = args.qualification_root.resolve(strict=True)
    source_aroll = args.source_aroll.resolve(strict=True)
    avatar_review_path = args.avatar_review.resolve(strict=True)
    target = args.output.resolve()
    target.relative_to(Path(__file__).resolve().parents[1])
    sys.path.insert(0, str(project_root))
    source_aroll_bytes, avatar_review_bytes = freeze_external_inputs(
        source_aroll, avatar_review_path
    )

    with owned_staging(target) as staging:
        receipt = render_into(
            args,
            project_root=project_root,
            qualification_root=qualification_root,
            source_aroll_declared_path=source_aroll,
            avatar_review_declared_path=avatar_review_path,
            source_aroll_bytes=source_aroll_bytes,
            avatar_review_bytes=avatar_review_bytes,
            output=staging,
        )
    print(json.dumps({
        "status": receipt["status"],
        "output": str(target),
        "montage": str(target / "semantic-state-5family-avatar-canary.mp4"),
        "contact_sheet": str(target / "contact-sheet.png"),
        "families": len(receipt["cases"]),
    }, ensure_ascii=False))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--source-aroll", type=Path, required=True)
    parser.add_argument("--avatar-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    render(parser.parse_args())


if __name__ == "__main__":
    main()

"""Persistent state for the HD talking-head workflow."""

from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LEGACY_V1_STAGE_IDS = (
    "inspect", "speech_cleanup", "edit_structure", "visual_direction",
    "visual_assets", "subtitles", "cover", "preview", "delivery",
)
FULL_V2_STAGE_IDS = (
    "inspect", "content_analysis", "cover_direction", "cover",
    "speech_cleanup", "edit_structure", "visual_direction", "visual_canary",
    "visual_assets", "subtitles", "preview", "delivery",
)
FULL_V2_DEPENDENCIES = {
    "inspect": (),
    "content_analysis": ("inspect",),
    "cover_direction": ("content_analysis",),
    "cover": ("cover_direction",),
    "speech_cleanup": ("inspect",),
    "edit_structure": ("speech_cleanup",),
    "visual_direction": ("content_analysis", "edit_structure"),
    "visual_canary": ("visual_direction",),
    "visual_assets": ("visual_direction", "visual_canary"),
    "subtitles": ("content_analysis", "edit_structure", "visual_assets"),
    "preview": ("cover", "edit_structure", "visual_assets", "subtitles"),
    "delivery": ("preview",),
}
# Compatibility alias for existing callers and legacy fixtures. New Skill jobs
# request ``profile="full-v2"`` explicitly instead of silently migrating v1.
STAGE_IDS = LEGACY_V1_STAGE_IDS
_ALL_STAGE_IDS = tuple(dict.fromkeys((*LEGACY_V1_STAGE_IDS, *FULL_V2_STAGE_IDS)))
STAGE_STATUSES = (
    "pending", "ready_for_review", "approved", "needs_revision", "blocked",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_WORKFLOW_FILE = "workflow.json"
_TRANSACTION_PREFIX = ".workflow."
_TRANSACTION_KINDS = ("stage", "backup", "marker", "recovery")
_TRANSACTION_SUFFIXES = tuple(
    f".{suffix}" for suffix in (*_TRANSACTION_KINDS, "quarantine", "retained")
)
_RETAINED_NAME = re.compile(
    r"\.workflow\.([0-9a-f]{32})\.(stage|backup|marker|recovery)\."
    r"([0-9a-f]{64})\.(0|[1-9][0-9]*)\.retained\Z"
)
_CASCADE_REASON_PREFIX = "cascade-event:v1:"


def _cascade_event(reason: object) -> dict[str, object] | None:
    if type(reason) is not str or not reason.startswith(_CASCADE_REASON_PREFIX):
        return None
    parts = reason.split(":")
    if (
        len(parts) != 4
        or parts[:2] != ["cascade-event", "v1"]
        or parts[2] not in _ALL_STAGE_IDS
        or not parts[3].isdigit()
        or parts[3] != str(int(parts[3]))
        or int(parts[3]) <= 0
    ):
        return None
    return {"trigger_stage": parts[2], "revision": int(parts[3])}


def _cascade_reason(trigger_stage: str, revision: int) -> str:
    return f"{_CASCADE_REASON_PREFIX}{trigger_stage}:{revision}"


class WorkflowError(Exception):
    """Raised when workflow state or a requested transition is invalid."""


class _CommittedWorkflowError(WorkflowError):
    """The workflow was committed, but cleanup durability could not be confirmed."""


class _QuarantineError(WorkflowError):
    """An unknown entry was isolated instead of being removed."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"workflow cleanup failed; manual recovery required from {path.name}"
        )


class _CasConflict(WorkflowError):
    """The persisted workflow no longer matches the caller's loaded state."""


@dataclass
class JobState:
    root: Path
    job_dir: Path
    job_id: str
    inputs: dict[str, dict[str, Any]]
    revision: int
    stages: dict[str, dict[str, Any]]
    expected_revision: int | None = None
    expected_sha256: str | None = None
    expected_bytes: int | None = None
    version: int = 1


def _stage_ids_for_version(version: int) -> tuple[str, ...]:
    if type(version) is not int:
        raise _error()
    if version == 1:
        return LEGACY_V1_STAGE_IDS
    if version == 2:
        return FULL_V2_STAGE_IDS
    raise _error()


def stage_ids_for(job: JobState) -> tuple[str, ...]:
    if not isinstance(job, JobState):
        raise _error()
    return _stage_ids_for_version(job.version)


def dependencies_for(job: JobState, stage_id: str) -> tuple[str, ...]:
    """Return the authoritative direct dependencies for one workflow stage."""
    if not isinstance(job, JobState) or stage_id not in stage_ids_for(job):
        raise _error()
    return tuple(_dependencies_for_version(job.version)[stage_id])


def _dependencies_for_version(version: int) -> dict[str, tuple[str, ...]]:
    stage_ids = _stage_ids_for_version(version)
    if version == 1:
        return {
            stage_id: stage_ids[:index]
            for index, stage_id in enumerate(stage_ids)
        }
    return FULL_V2_DEPENDENCIES


def _transitive_dependents(version: int, trigger_stage: str) -> tuple[str, ...]:
    stage_ids = _stage_ids_for_version(version)
    if trigger_stage not in stage_ids:
        raise _error()
    if version == 1:
        return stage_ids[stage_ids.index(trigger_stage):]
    affected = {trigger_stage}
    changed = True
    while changed:
        changed = False
        for candidate, dependencies in FULL_V2_DEPENDENCIES.items():
            if candidate not in affected and affected.intersection(dependencies):
                affected.add(candidate)
                changed = True
    return tuple(stage_id for stage_id in stage_ids if stage_id in affected)


def current_stage(job: JobState) -> str | None:
    _validate_job(job)
    return next(
        (
            stage_id
            for stage_id in stage_ids_for(job)
            if job.stages[stage_id]["status"] != "approved"
        ),
        None,
    )


@dataclass
class _PinnedFile:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int


@dataclass
class _PinnedTransactionFile:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int


@dataclass
class _PinnedBackup:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int


def _error() -> WorkflowError:
    """Keep filesystem details, including user paths, out of workflow errors."""
    return WorkflowError("invalid workflow state")


def _raw_path(value: Path | str) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise _error() from exc
    if not isinstance(raw, str) or "\x00" in raw or "\\" in raw or ".." in raw.split("/"):
        raise _error()
    return raw


def _absolute_path(value: Path | str) -> Path:
    path = Path(_raw_path(value))
    return path if path.is_absolute() else Path.cwd() / path


def _assert_no_symlinks(path: Path) -> None:
    """Reject a symlink at any component, without resolving through it."""
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _error()
    except (OSError, ValueError) as exc:
        raise _error() from exc


def _assert_directory(path: Path) -> None:
    _assert_no_symlinks(path)
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise _error()
    except (OSError, ValueError) as exc:
        raise _error() from exc


def _assert_regular(path: Path) -> None:
    _assert_no_symlinks(path)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise _error()
    except (OSError, ValueError) as exc:
        raise _error() from exc


def _entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _error() from exc
    return True


def _assert_exclusive_regular(path: Path) -> None:
    _assert_no_symlinks(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except (OSError, ValueError) as exc:
        raise _error() from exc
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1 or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise _error()
    except (OSError, ValueError) as exc:
        raise _error() from exc
    finally:
        os.close(descriptor)


def _safe_relative(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise _error()
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error()
    return tuple(parts)


def _assert_artifact_path(value: Any) -> None:
    parts = _safe_relative(value)
    if len(parts) == 1 and _is_transaction_name(parts[0]):
        raise _error()


def _is_transaction_name(name: str) -> bool:
    return name == _WORKFLOW_FILE or (
        name.startswith(_TRANSACTION_PREFIX)
        and name.endswith(_TRANSACTION_SUFFIXES)
    )


def _retained_payload_is_valid(payload: Any) -> bool:
    if (type(payload) is not dict or type(payload.get("version")) is not int
            or payload["version"] not in {1, 2}
            or not isinstance(payload.get("job_id"), str)
            or not _SHA256_RE.fullmatch(payload["job_id"])
            or type(payload.get("revision")) is not int or payload["revision"] < 0
            or type(payload.get("inputs")) is not dict
            or set(payload["inputs"]) != {"video", "script"}
            or type(payload.get("stages")) is not dict
            or set(payload["stages"]) != set(
                _stage_ids_for_version(payload["version"])
            )):
        return False
    try:
        lineage_modes = [type(stage) is dict and "lineage" in stage
                         for stage in payload["stages"].values()]
        if any(lineage_modes) and not all(lineage_modes):
            return False
        stage_keys = {"status", "reason", "artifacts", "ai_attempts"}
        if all(lineage_modes):
            stage_keys.add("lineage")
        if payload["version"] == 2:
            stage_keys.add("artifact_scope")
        for record in payload["inputs"].values():
            if (type(record) is not dict or set(record) != {"path", "sha256", "bytes"}
                    or not isinstance(record["sha256"], str)
                    or not _SHA256_RE.fullmatch(record["sha256"])
                    or type(record["bytes"]) is not int or record["bytes"] < 0):
                return False
            _safe_relative(record["path"])
        for stage_id, stage in payload["stages"].items():
            if (type(stage) is not dict or set(stage) != stage_keys
                    or stage["status"] not in STAGE_STATUSES
                    or (stage["reason"] is not None and type(stage["reason"]) is not str)
                    or type(stage["ai_attempts"]) is not int or stage["ai_attempts"] < 0
                    or type(stage["artifacts"]) is not list):
                return False
            for artifact in stage["artifacts"]:
                if (type(artifact) is not dict or set(artifact) != {"path", "sha256", "bytes"}
                        or not isinstance(artifact["sha256"], str)
                        or not _SHA256_RE.fullmatch(artifact["sha256"])
                        or type(artifact["bytes"]) is not int or artifact["bytes"] < 0):
                    return False
                _assert_artifact_path(artifact["path"])
            if all(lineage_modes):
                if type(stage["lineage"]) is not list:
                    return False
                for record in stage["lineage"]:
                    _validate_lineage(record)
            if payload["version"] == 2 and (
                type(stage["artifact_scope"]) is not list
                or any(
                    type(value) is not str or not value
                    for value in stage["artifact_scope"]
                )
            ):
                return False
            if (
                stage["reason"] is not None
                and stage["reason"].startswith(_CASCADE_REASON_PREFIX)
            ):
                event = _cascade_event(stage["reason"])
                if (
                    stage["status"] != "pending"
                    or type(event) is not dict
                    or stage_id not in _transitive_dependents(
                        payload["version"], event["trigger_stage"]
                    )[1:]
                    or event["revision"] > payload["revision"]
                ):
                    return False
        _validate_stage_topology(payload["stages"], payload["version"])
    except WorkflowError:
        return False
    return True


def _is_valid_retained_entry(path: Path) -> bool:
    match = _RETAINED_NAME.fullmatch(path.name)
    if match is None:
        return False
    kind, expected_sha256, expected_size = match.group(2, 3, 4)
    descriptor: int | None = None
    try:
        _assert_no_symlinks(path)
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1 or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            return False
        actual_sha256, actual_size = _digest_descriptor(descriptor)
        if actual_sha256 != expected_sha256 or actual_size != int(expected_size):
            return False
        payload = json.loads(
            _read_descriptor(descriptor).decode("utf-8"),
            object_pairs_hook=_strict_object, parse_constant=_reject_nonfinite,
        )
        if kind in {"stage", "backup"}:
            return _retained_payload_is_valid(payload)
        if kind in {"marker", "recovery"}:
            return (type(payload) is dict and set(payload) == {
                "version", "target", "sha256", "bytes"
            } and type(payload["version"]) is int and payload["version"] == 1
                    and payload["target"] == _WORKFLOW_FILE
                    and isinstance(payload["sha256"], str)
                    and _SHA256_RE.fullmatch(payload["sha256"])
                    and type(payload["bytes"]) is int and payload["bytes"] >= 0)
    except (OSError, UnicodeError, TypeError, ValueError, WorkflowError):
        return False
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor)
    return False


def _has_pending_recovery(directory: Path) -> bool:
    try:
        for entry in directory.iterdir():
            if not entry.name.startswith(_TRANSACTION_PREFIX):
                continue
            if entry.name.endswith(".retained"):
                if not _is_valid_retained_entry(entry):
                    return True
            elif entry.name.endswith((
                ".stage", ".backup", ".marker", ".recovery", ".quarantine",
            )):
                return True
        return False
    except OSError as exc:
        raise _error() from exc


def _assert_no_recovery_backup(directory: Path) -> None:
    if _has_pending_recovery(directory):
        raise WorkflowError("workflow recovery is pending")


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise _error() from exc
    return digest.hexdigest(), size


def _digest_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise _error() from exc
    return digest.hexdigest(), size


def _bound_record(base: Path, path: Path) -> dict[str, Any]:
    path = _absolute_path(path)
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise _error() from exc
    _assert_exclusive_regular(path)
    sha256, size = _digest(path)
    return {"path": relative.as_posix(), "sha256": sha256, "bytes": size}


def _validate_record(base: Path, record: Any) -> None:
    if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
        raise _error()
    parts = _safe_relative(record["path"])
    sha256, size = record["sha256"], record["bytes"]
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise _error()
    if type(size) is not int or size < 0:
        raise _error()
    path = base.joinpath(*parts)
    _assert_exclusive_regular(path)
    current_sha256, current_size = _digest(path)
    if current_sha256 != sha256 or current_size != size:
        raise _error()


def _pin_record(base: Path, record: dict[str, Any]) -> _PinnedFile:
    _validate_record(base, record)
    path = base.joinpath(*_safe_relative(record["path"]))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise _error() from exc
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1 or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise _error()
        sha256, size = _digest_descriptor(descriptor)
        if sha256 != record["sha256"] or size != record["bytes"]:
            raise _error()
        return _PinnedFile(path, descriptor, opened.st_dev, opened.st_ino, sha256, size)
    except BaseException:
        os.close(descriptor)
        raise


def _verify_pins(pins: Iterable[_PinnedFile]) -> None:
    for pinned in pins:
        _assert_exclusive_regular(pinned.path)
        try:
            opened = os.fstat(pinned.descriptor)
            named = os.lstat(pinned.path)
        except OSError as exc:
            raise _error() from exc
        if (opened.st_nlink != 1 or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (pinned.device, pinned.inode)
                or (named.st_dev, named.st_ino) != (pinned.device, pinned.inode)):
            raise _error()
        sha256, size = _digest_descriptor(pinned.descriptor)
        if sha256 != pinned.sha256 or size != pinned.size:
            raise _error()


def _stage_record(version: int = 1) -> dict[str, Any]:
    record = {
        "status": "pending", "reason": None, "artifacts": [],
        "ai_attempts": 0, "lineage": [],
    }
    if version == 2:
        record["artifact_scope"] = []
    return record


def _validate_stage_topology(
    stages: dict[str, dict[str, Any]], version: int = 1,
) -> None:
    """Validate a legacy prefix or the approved dependencies of a v2 DAG."""

    stage_ids = _stage_ids_for_version(version)
    dependencies = _dependencies_for_version(version)
    for stage_id in stage_ids:
        status = stages[stage_id]["status"]
        if status != "pending" and any(
            stages[dependency]["status"] != "approved"
            for dependency in dependencies[stage_id]
        ):
            raise _error()


def _job_id(inputs: dict[str, dict[str, Any]]) -> str:
    return hashlib.sha256(
        f"{inputs['video']['sha256']}:{inputs['script']['sha256']}".encode("ascii")
    ).hexdigest()


def _job_location(root: Path, job_id: str) -> Path:
    return root / "edit" / "hd" / "jobs" / job_id


def _prepare_job_directory(root: Path, job_id: str) -> Path:
    _assert_directory(root)
    current = root
    try:
        for name in ("edit", "hd", "jobs", job_id):
            current /= name
            if current.exists():
                _assert_directory(current)
            else:
                current.mkdir()
                _assert_directory(current)
    except OSError as exc:
        raise _error() from exc
    return current


def create_job(
    root: Path, video: Path, script: Path, *, profile: str = "full-v2",
) -> JobState:
    if profile not in {"legacy-v1", "full-v2"}:
        raise WorkflowError("unsupported workflow profile")
    version = 1 if profile == "legacy-v1" else 2
    stage_ids = _stage_ids_for_version(version)
    root = _absolute_path(root)
    _assert_directory(root)
    inputs = {"video": _bound_record(root, video), "script": _bound_record(root, script)}
    job_id = _job_id(inputs)
    job_dir = _job_location(root, job_id)
    if job_dir.exists():
        _assert_directory(job_dir)
        existing = load_job(job_dir)
        if existing.inputs != inputs or existing.version != version:
            raise _error()
        return existing
    job = JobState(root, _prepare_job_directory(root, job_id), job_id, inputs, 0,
                   {stage_id: _stage_record(version) for stage_id in stage_ids},
                   version=version)
    save_job(job)
    return job


def _payload(job: JobState) -> dict[str, Any]:
    return {"version": job.version, "job_id": job.job_id, "inputs": job.inputs,
            "revision": job.revision, "stages": job.stages}


def _validate_lineage(record: Any) -> None:
    keys = {
        "path", "sha256", "bytes", "device", "inode",
        "parent_device", "parent_inode",
    }
    if type(record) is not dict or set(record) != keys:
        raise _error()
    _assert_artifact_path(record["path"])
    if not isinstance(record["sha256"], str) or not _SHA256_RE.fullmatch(record["sha256"]):
        raise _error()
    if type(record["bytes"]) is not int or record["bytes"] < 0:
        raise _error()
    for key in ("device", "parent_device"):
        if type(record[key]) is not int or record[key] < 0:
            raise _error()
    for key in ("inode", "parent_inode"):
        if type(record[key]) is not int or record[key] <= 0:
            raise _error()


def _validate_job(job: JobState, *, pin_files: bool = False) -> list[_PinnedFile]:
    if not isinstance(job, JobState) or not isinstance(job.job_id, str):
        raise _error()
    if not _SHA256_RE.fullmatch(job.job_id):
        raise _error()
    root = _absolute_path(job.root)
    if root != job.root:
        raise _error()
    _assert_directory(root)
    expected_dir = _job_location(root, job.job_id)
    if job.job_dir != expected_dir:
        raise _error()
    _assert_directory(expected_dir)
    _assert_no_recovery_backup(expected_dir)
    if type(job.inputs) is not dict or set(job.inputs) != {"video", "script"}:
        raise _error()
    for record in job.inputs.values():
        _validate_record(root, record)
    if _job_id(job.inputs) != job.job_id:
        raise _error()
    if type(job.revision) is not int or job.revision < 0:
        raise _error()
    stage_ids = stage_ids_for(job)
    expected = (job.expected_revision, job.expected_sha256, job.expected_bytes)
    if any(value is None for value in expected):
        if any(value is not None for value in expected):
            raise _error()
    elif (type(job.expected_revision) is not int or job.expected_revision < 0
          or not isinstance(job.expected_sha256, str)
          or not _SHA256_RE.fullmatch(job.expected_sha256)
          or type(job.expected_bytes) is not int or job.expected_bytes < 0):
        raise _error()
    if type(job.stages) is not dict or set(job.stages) != set(stage_ids):
        raise _error()
    for stage_id, stage in job.stages.items():
        expected_stage_keys = {
            "status", "reason", "artifacts", "ai_attempts", "lineage"
        }
        if job.version == 2:
            expected_stage_keys.add("artifact_scope")
        if type(stage) is not dict or set(stage) != expected_stage_keys:
            raise _error()
        if stage["status"] not in STAGE_STATUSES:
            raise _error()
        if stage["reason"] is not None and type(stage["reason"]) is not str:
            raise _error()
        if type(stage["ai_attempts"]) is not int or stage["ai_attempts"] < 0:
            raise _error()
        if type(stage["artifacts"]) is not list:
            raise _error()
        for artifact in stage["artifacts"]:
            if type(artifact) is not dict:
                raise _error()
            _assert_artifact_path(artifact.get("path"))
            _validate_record(expected_dir, artifact)
        if type(stage["lineage"]) is not list:
            raise _error()
        for record in stage["lineage"]:
            _validate_lineage(record)
        if job.version == 2 and (
            type(stage["artifact_scope"]) is not list
            or any(type(value) is not str or not value for value in stage["artifact_scope"])
        ):
            raise _error()
        cascade_event = _cascade_event(stage["reason"])
        if stage["reason"] is not None and stage["reason"].startswith(
            _CASCADE_REASON_PREFIX
        ):
            if (
                stage["status"] != "pending"
                or type(cascade_event) is not dict
                or stage_id not in _transitive_dependents(
                    job.version, cascade_event["trigger_stage"]
                )[1:]
                or cascade_event["revision"] > job.revision
            ):
                raise _error()
    _validate_stage_topology(job.stages, job.version)
    if not pin_files:
        return []
    pins: list[_PinnedFile] = []
    try:
        for record in job.inputs.values():
            pins.append(_pin_record(root, record))
        for stage_id in stage_ids:
            stage = job.stages[stage_id]
            for artifact in stage["artifacts"]:
                pins.append(_pin_record(expected_dir, artifact))
    except BaseException:
        _close_pins(pins)
        raise
    return pins


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _read_payload(workflow: Path) -> dict[str, Any]:
    _assert_exclusive_regular(workflow)
    try:
        with workflow.open("r", encoding="utf-8") as handle:
            payload = json.load(handle, object_pairs_hook=_strict_object,
                                parse_constant=_reject_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _error() from exc
    if type(payload) is not dict or set(payload) != {
        "version", "job_id", "inputs", "revision", "stages"
    }:
        raise _error()
    if type(payload["version"]) is not int or payload["version"] not in {1, 2}:
        raise _error()
    return payload


def _normalize_stage_schema(stages: object, version: int = 1) -> None:
    if type(stages) is not dict:
        return
    legacy = {"status", "reason", "artifacts", "ai_attempts"}
    current = legacy | {"lineage"}
    if version == 2:
        current.add("artifact_scope")
    shapes = [
        set(stage) if type(stage) is dict else set()
        for stage in stages.values()
    ]
    if version == 1 and shapes and all(shape == legacy for shape in shapes):
        for stage in stages.values():
            stage["lineage"] = []
    elif any(shape != current for shape in shapes):
        raise _error()


def load_job(job_dir: Path) -> JobState:
    job_dir = _absolute_path(job_dir)
    if (len(job_dir.parents) < 4 or job_dir.parent.name != "jobs"
            or job_dir.parent.parent.name != "hd"
            or job_dir.parent.parent.parent.name != "edit"
            or not _SHA256_RE.fullmatch(job_dir.name)):
        raise _error()
    _assert_directory(job_dir)
    _assert_no_recovery_backup(job_dir)
    root = job_dir.parents[3]
    workflow = job_dir / "workflow.json"
    payload = _read_payload(workflow)
    sha256, size = _digest(workflow)
    if _read_payload(workflow) != payload:
        raise _error()
    _normalize_stage_schema(payload["stages"], payload["version"])
    job = JobState(root, job_dir, payload["job_id"], payload["inputs"],
                   payload["revision"], payload["stages"], payload["revision"],
                   sha256, size, payload["version"])
    _validate_job(job)
    return job


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(directory), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_transaction_file(
    transaction: _PinnedTransactionFile, path: Path | None = None,
) -> None:
    path = transaction.path if path is None else path
    _assert_no_symlinks(path)
    try:
        opened = os.fstat(transaction.descriptor)
        named = os.lstat(path)
    except (OSError, ValueError) as exc:
        raise _error() from exc
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1 or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (transaction.device, transaction.inode)
            or (named.st_dev, named.st_ino) != (transaction.device, transaction.inode)):
        raise _error()
    sha256, size = _digest_descriptor(transaction.descriptor)
    if sha256 != transaction.sha256 or size != transaction.size:
        raise _error()


def _descriptor_is_closed(descriptor: int) -> bool:
    try:
        os.fstat(descriptor)
    except OSError as exc:
        return exc.errno == errno.EBADF
    return False


def _close_descriptor(descriptor: int) -> BaseException | None:
    first_error: BaseException | None = None
    try:
        os.close(descriptor)
    except BaseException as exc:
        first_error = exc
        if not _descriptor_is_closed(descriptor):
            try:
                os.close(descriptor)
            except BaseException:
                pass
    return first_error


def _close_transaction_file(
    transaction: _PinnedTransactionFile | None,
) -> BaseException | None:
    if transaction is not None:
        return _close_descriptor(transaction.descriptor)
    return None


def _close_backup(backup: _PinnedBackup | None) -> BaseException | None:
    if backup is not None:
        return _close_descriptor(backup.descriptor)
    return None


def _close_pins(pins: Iterable[_PinnedFile]) -> BaseException | None:
    first_error: BaseException | None = None
    for pinned in pins:
        error = _close_descriptor(pinned.descriptor)
        if first_error is None and error is not None:
            first_error = error
    return first_error


def _owned_transaction_entry(path: Path, device: int, inode: int) -> bool:
    try:
        named = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _error() from exc
    return (stat.S_ISREG(named.st_mode) and named.st_nlink == 1
            and (named.st_dev, named.st_ino) == (device, inode))


def _transaction_kind(path: Path) -> str:
    for kind in _TRANSACTION_KINDS:
        if path.name.endswith(f".{kind}"):
            return kind
    raise _error()


def _fresh_transaction_path(
    directory: Path, kind: str, suffix: str, *, sha256: str | None = None,
    size: int | None = None,
) -> Path:
    for _ in range(16):
        token = secrets.token_hex(16)
        if suffix == "retained":
            if sha256 is None or size is None:
                raise _error()
            name = f"{_TRANSACTION_PREFIX}{token}.{kind}.{sha256}.{size}.retained"
        else:
            name = f"{_TRANSACTION_PREFIX}{token}.{kind}.{suffix}"
        candidate = directory / name
        if not _entry_exists(candidate):
            return candidate
    raise _error()


def _open_stable_transaction_directory(directory: Path) -> int:
    _assert_directory(directory)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(directory), flags)
    except (OSError, ValueError) as exc:
        raise _error() from exc
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(directory)
        if (not stat.S_ISDIR(opened.st_mode) or not stat.S_ISDIR(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise _error()
    except BaseException:
        _close_descriptor(descriptor)
        raise
    return descriptor


def _atomic_transaction_rename(
    source: Path, destination: Path, *, darwin_flags: int, linux_flags: int,
    no_replace: bool,
) -> None:
    if (source.parent != destination.parent or source.name in {"", ".", ".."}
            or destination.name in {"", ".", ".."}):
        raise _error()
    descriptor = _open_stable_transaction_directory(source.parent)
    operation_error: BaseException | None = None
    try:
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            rename = getattr(library, "renameatx_np", None)
            flags = darwin_flags
        elif sys.platform.startswith("linux"):
            rename = getattr(library, "renameat2", None)
            flags = linux_flags
        else:
            rename = None
            flags = 0
        if rename is None:
            raise _error()
        rename.argtypes = (
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            descriptor, os.fsencode(source.name), descriptor, os.fsencode(destination.name), flags,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            if error_number == errno.ENOENT:
                raise FileNotFoundError(error_number, "transaction entry is absent")
            if no_replace and error_number == errno.EEXIST:
                raise _CasConflict("workflow update conflict")
            raise _error()
    except BaseException as exc:
        operation_error = exc
    close_error = _close_descriptor(descriptor)
    if operation_error is not None:
        raise operation_error
    if close_error is not None:
        if isinstance(close_error, (OSError, ValueError)):
            raise _error() from None
        raise close_error


def _atomic_noreplace_rename(source: Path, destination: Path) -> None:
    """Move sibling entries without ever replacing an existing destination."""
    _atomic_transaction_rename(
        source, destination, darwin_flags=0x00000004, linux_flags=0x00000001,
        no_replace=True,
    )


def _atomic_exchange_rename(source: Path, destination: Path) -> None:
    """Atomically exchange sibling entries without a replacement window."""
    _atomic_transaction_rename(
        source, destination, darwin_flags=0x00000002, linux_flags=0x00000002,
        no_replace=False,
    )


def _rename_owned_entry(source: Path, destination: Path, verify) -> None:
    try:
        _atomic_noreplace_rename(source, destination)
    except BaseException as failure:
        try:
            verify(destination)
        except BaseException:
            if _entry_exists(destination):
                raise _QuarantineError(destination) from None
            raise failure
        return
    try:
        verify(destination)
    except BaseException:
        raise _QuarantineError(destination) from None


def _quarantine_owned_entry(path: Path, kind: str, verify) -> Path:
    quarantine = _fresh_transaction_path(path.parent, kind, "quarantine")
    _rename_owned_entry(path, quarantine, verify)
    return quarantine


def _retire_owned_entry(
    path: Path, kind: str, sha256: str, size: int, verify,
) -> Path:
    quarantine = _quarantine_owned_entry(path, kind, verify)
    retained = _fresh_transaction_path(
        path.parent, kind, "retained", sha256=sha256, size=size,
    )
    try:
        _rename_owned_entry(quarantine, retained, verify)
    except _QuarantineError:
        raise
    except BaseException:
        if _entry_exists(quarantine):
            raise _QuarantineError(quarantine) from None
        raise
    _fsync_directory(path.parent)
    return retained


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise _error() from exc
    return b"".join(chunks)


def _verify_backup_descriptor(backup: _PinnedBackup) -> None:
    try:
        opened = os.fstat(backup.descriptor)
    except OSError as exc:
        raise _error() from exc
    if (not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (backup.device, backup.inode)):
        raise _error()
    sha256, size = _digest_descriptor(backup.descriptor)
    if sha256 != backup.sha256 or size != backup.size:
        raise _error()


def _verify_backup(backup: _PinnedBackup, expected_links: int) -> None:
    _verify_backup_at(backup, backup.path, expected_links)


def _verify_backup_at(
    backup: _PinnedBackup, path: Path, expected_links: int,
) -> None:
    _verify_backup_descriptor(backup)
    _assert_no_symlinks(path)
    try:
        named = os.lstat(path)
        opened = os.fstat(backup.descriptor)
    except (OSError, ValueError) as exc:
        raise _error() from exc
    if (not stat.S_ISREG(named.st_mode) or opened.st_nlink != expected_links
            or named.st_nlink != expected_links
            or (named.st_dev, named.st_ino) != (backup.device, backup.inode)):
        raise _error()


def _unlink_transaction_file(transaction: _PinnedTransactionFile) -> None:
    try:
        os.lstat(transaction.path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _error() from exc
    _retire_owned_entry(
        transaction.path, _transaction_kind(transaction.path), transaction.sha256,
        transaction.size, lambda path: _verify_transaction_file(transaction, path),
    )


def _unlink_backup(backup: _PinnedBackup, expected_links: int) -> None:
    try:
        os.lstat(backup.path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _error() from exc
    _retire_owned_entry(
        backup.path, "backup", backup.sha256, backup.size,
        lambda path: _verify_backup_at(backup, path, expected_links),
    )


def _quarantine_created_transaction(
    path: Path, descriptor: int, created: os.stat_result,
) -> None:
    opened = os.fstat(descriptor)
    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (created.st_dev, created.st_ino)):
        raise _error()
    sha256, size = _digest_descriptor(descriptor)
    transaction = _PinnedTransactionFile(
        path, descriptor, opened.st_dev, opened.st_ino, sha256, size,
    )
    _quarantine_owned_entry(
        path, _transaction_kind(path),
        lambda candidate: _verify_transaction_file(transaction, candidate),
    )


def _write_transaction_file(
    directory: Path, suffix: str, data: bytes,
) -> _PinnedTransactionFile:
    descriptor, name = tempfile.mkstemp(
        prefix=_TRANSACTION_PREFIX, suffix=suffix, dir=directory
    )
    transaction_file = Path(name)
    created: os.stat_result | None = None
    pinned: _PinnedTransactionFile | None = None
    unowned_pinned_descriptor: int | None = None
    durable_data = False
    failure: BaseException | None = None
    try:
        created = os.fstat(descriptor)
        if (not stat.S_ISREG(created.st_mode) or created.st_nlink != 1
                or not _owned_transaction_entry(transaction_file, created.st_dev, created.st_ino)):
            raise _error()
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short transaction write")
            remaining = remaining[written:]
        os.fsync(descriptor)
        if not _owned_transaction_entry(transaction_file, created.st_dev, created.st_ino):
            raise _error()
        durable_data = True
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        unowned_pinned_descriptor = os.open(str(transaction_file), flags)
        opened = os.fstat(unowned_pinned_descriptor)
        pinned = _PinnedTransactionFile(
            transaction_file, unowned_pinned_descriptor, opened.st_dev, opened.st_ino,
            hashlib.sha256(data).hexdigest(), len(data),
        )
        unowned_pinned_descriptor = None
        _verify_transaction_file(pinned)
    except BaseException as exc:
        failure = exc
    if failure is None:
        original_close_error = _close_descriptor(descriptor)
        if original_close_error is not None:
            failure = original_close_error
    if failure is not None:
        if unowned_pinned_descriptor is not None:
            _close_descriptor(unowned_pinned_descriptor)
            unowned_pinned_descriptor = None
        if pinned is not None:
            try:
                _retire_owned_entry(
                    pinned.path, _transaction_kind(pinned.path), pinned.sha256,
                    pinned.size, lambda path: _verify_transaction_file(pinned, path),
                )
            except BaseException:
                pass
        elif (created is not None and durable_data
              and not _descriptor_is_closed(descriptor)):
            try:
                owned = _PinnedTransactionFile(
                    transaction_file, descriptor, created.st_dev, created.st_ino,
                    hashlib.sha256(data).hexdigest(), len(data),
                )
                _retire_owned_entry(
                    owned.path, _transaction_kind(owned.path), owned.sha256, owned.size,
                    lambda path: _verify_transaction_file(owned, path),
                )
            except BaseException:
                try:
                    _quarantine_created_transaction(transaction_file, descriptor, created)
                except BaseException:
                    pass
        elif created is not None and not _descriptor_is_closed(descriptor):
            try:
                _quarantine_created_transaction(transaction_file, descriptor, created)
            except BaseException:
                pass
        _close_transaction_file(pinned)
        if not _descriptor_is_closed(descriptor):
            _close_descriptor(descriptor)
        raise failure
    if pinned is None:
        raise _error()
    return pinned


def _write_stage(directory: Path, data: bytes) -> _PinnedTransactionFile:
    return _write_transaction_file(directory, ".stage", data)


def _write_recovery_marker(directory: Path, data: bytes) -> _PinnedTransactionFile:
    marker_data = (json.dumps({
        "version": 1,
        "target": _WORKFLOW_FILE,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    marker = _write_transaction_file(directory, ".recovery", marker_data)
    try:
        _fsync_directory(directory)
    except BaseException:
        try:
            _unlink_transaction_file(marker)
        finally:
            _close_transaction_file(marker)
        raise
    return marker


def _clear_recovery_marker(marker: _PinnedTransactionFile) -> None:
    _unlink_transaction_file(marker)


def _verify_expected_workflow(
    path: Path, revision: int, sha256: str, size: int,
) -> None:
    try:
        _assert_exclusive_regular(path)
        if _digest(path) != (sha256, size):
            raise _error()
        payload = _read_payload(path)
        if payload["revision"] != revision or _digest(path) != (sha256, size):
            raise _error()
    except BaseException:
        raise _CasConflict("workflow update conflict") from None


def _backup_existing(
    target: Path, expected_revision: int, expected_sha256: str, expected_bytes: int,
) -> _PinnedBackup:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source = os.open(str(target), flags)
    except OSError as exc:
        raise _error() from exc
    backup: _PinnedBackup | None = None
    try:
        opened = os.fstat(source)
        named = os.lstat(target)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1 or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise _error()
        sha256, size = _digest_descriptor(source)
        if (sha256, size) != (expected_sha256, expected_bytes):
            raise _CasConflict("workflow update conflict")
        _verify_expected_workflow(
            target, expected_revision, expected_sha256, expected_bytes,
        )
        data = _read_descriptor(source)
        named = os.lstat(target)
        if ((named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or named.st_nlink != 1
                or _digest_descriptor(source) != (sha256, size)):
            raise _error()
        transaction = _write_transaction_file(target.parent, ".backup", data)
        backup = _PinnedBackup(
            transaction.path, transaction.descriptor, transaction.device,
            transaction.inode, transaction.sha256, transaction.size,
        )
        _verify_backup(backup, 1)
        named = os.lstat(target)
        if ((named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or named.st_nlink != 1
                or _digest_descriptor(source) != (sha256, size)):
            raise _CasConflict("workflow update conflict")
        _verify_expected_workflow(
            target, expected_revision, expected_sha256, expected_bytes,
        )
        return backup
    except BaseException:
        _close_backup(backup)
        raise
    finally:
        _close_descriptor(source)


def _entry_identity(path: Path) -> tuple[int, int, int, int]:
    """Return the lstat identity of one directory entry without following it."""
    try:
        named = os.lstat(path)
    except (OSError, ValueError) as exc:
        raise _error() from exc
    return named.st_dev, named.st_ino, named.st_mode, named.st_nlink


def _matches_entry_identity(path: Path, identity: tuple[int, int, int, int]) -> bool:
    try:
        return _entry_identity(path) == identity
    except WorkflowError:
        return False


def _verify_rollback_stage(
    rollback_stage: _PinnedTransactionFile, backup: _PinnedBackup,
    path: Path | None = None,
) -> None:
    _verify_backup_descriptor(backup)
    _verify_transaction_file(rollback_stage, path)
    if (rollback_stage.sha256, rollback_stage.size) != (backup.sha256, backup.size):
        raise _error()


def _record_rollback_uncertainty(
    directory: Path, published: _PinnedTransactionFile,
) -> None:
    """Leave a durable marker when an inverse exchange cannot be proven."""
    marker = _write_recovery_marker(directory, _read_descriptor(published.descriptor))
    close_error = _close_transaction_file(marker)
    if close_error is not None:
        raise _error() from None


def _retire_rollback_stage(
    rollback_stage: _PinnedTransactionFile, backup: _PinnedBackup,
) -> None:
    _retire_owned_entry(
        rollback_stage.path, "stage", rollback_stage.sha256, rollback_stage.size,
        lambda path: _verify_rollback_stage(rollback_stage, backup, path),
    )


def _restore_backup_with_exchange(
    target: Path, backup: _PinnedBackup, published: _PinnedTransactionFile,
) -> None:
    """Restore a backup without ever replacing an unverified public target."""
    _verify_backup_descriptor(backup)
    rollback_stage = _write_stage(target.parent, _read_descriptor(backup.descriptor))
    try:
        _verify_rollback_stage(rollback_stage, backup)
        target_identity = _entry_identity(target)
        rollback_identity = _entry_identity(rollback_stage.path)
        target_was_published = True
        try:
            _verify_transaction_file(published, target)
        except WorkflowError:
            target_was_published = False
        try:
            _atomic_exchange_rename(rollback_stage.path, target)
        except BaseException:
            if _matches_entry_identity(rollback_stage.path, rollback_identity):
                try:
                    _retire_rollback_stage(rollback_stage, backup)
                except BaseException:
                    pass
                raise
        try:
            _verify_rollback_stage(rollback_stage, backup, target)
            _verify_transaction_file(published, rollback_stage.path)
        except BaseException:
            try:
                _atomic_exchange_rename(rollback_stage.path, target)
            except BaseException:
                if (not _matches_entry_identity(target, target_identity)
                        or not _matches_entry_identity(
                            rollback_stage.path, rollback_identity,
                        )):
                    _record_rollback_uncertainty(target.parent, published)
                    try:
                        _unlink_transaction_file(rollback_stage)
                    except BaseException:
                        pass
                    raise _CasConflict("workflow update conflict") from None
            try:
                if target_was_published:
                    _verify_transaction_file(published, target)
                elif not _matches_entry_identity(target, target_identity):
                    raise _error()
                _verify_rollback_stage(rollback_stage, backup)
            except BaseException:
                _record_rollback_uncertainty(target.parent, published)
                try:
                    _unlink_transaction_file(rollback_stage)
                except BaseException:
                    pass
                raise _CasConflict("workflow update conflict") from None
            _retire_rollback_stage(rollback_stage, backup)
            raise _CasConflict("workflow update conflict") from None
        try:
            _fsync_directory(target.parent)
            _verify_rollback_stage(rollback_stage, backup, target)
            _verify_transaction_file(published, rollback_stage.path)
        except BaseException:
            try:
                _retire_owned_entry(
                    rollback_stage.path, "stage", published.sha256, published.size,
                    lambda path: _verify_transaction_file(published, path),
                )
            except BaseException:
                pass
            raise
        _retire_owned_entry(
            rollback_stage.path, "stage", published.sha256, published.size,
            lambda path: _verify_transaction_file(published, path),
        )
    finally:
        _close_transaction_file(rollback_stage)


def _rollback_exchanged_publication(
    transaction: _PinnedTransactionFile, target: Path, expected_revision: int,
    expected_sha256: str, expected_bytes: int,
) -> None:
    try:
        _atomic_exchange_rename(transaction.path, target)
        _verify_transaction_file(transaction, transaction.path)
        _verify_expected_workflow(
            target, expected_revision, expected_sha256, expected_bytes,
        )
    except BaseException:
        raise _CasConflict("workflow update conflict") from None


def _publish_transaction(
    transaction: _PinnedTransactionFile, target: Path, *, expected_revision: int | None,
    expected_sha256: str | None, expected_bytes: int | None,
) -> None:
    _verify_transaction_file(transaction)
    if expected_revision is None:
        try:
            _atomic_noreplace_rename(transaction.path, target)
            _verify_transaction_file(transaction, target)
            _fsync_directory(target.parent)
            _verify_transaction_file(transaction, target)
        except _CasConflict:
            raise
        except BaseException:
            raise
        return
    exchange_failure: BaseException | None = None
    try:
        _atomic_exchange_rename(transaction.path, target)
    except BaseException as failure:
        try:
            _verify_transaction_file(transaction, target)
        except BaseException:
            raise failure
        exchange_failure = failure
    try:
        _verify_transaction_file(transaction, target)
        _verify_expected_workflow(
            transaction.path, expected_revision, expected_sha256, expected_bytes,
        )
    except BaseException:
        _rollback_exchanged_publication(
            transaction, target, expected_revision, expected_sha256, expected_bytes,
        )
        raise _CasConflict("workflow update conflict") from None
    try:
        _retire_owned_entry(
            transaction.path, "stage", expected_sha256, expected_bytes,
            lambda path: _verify_expected_workflow(
                path, expected_revision, expected_sha256, expected_bytes,
            ),
        )
    except _CasConflict:
        raise
    except BaseException:
        raise
    try:
        _verify_transaction_file(transaction, target)
    except BaseException:
        raise _CasConflict("workflow update conflict") from None
    if exchange_failure is not None:
        raise exchange_failure
    _fsync_directory(target.parent)
    try:
        _verify_transaction_file(transaction, target)
    except BaseException:
        raise _CasConflict("workflow update conflict") from None


def _restore_previous(
    target: Path, backup: _PinnedBackup | None,
    published: _PinnedTransactionFile | None,
) -> None:
    if backup is None:
        if published is None:
            raise _error()
        try:
            _retire_owned_entry(
                target, "stage", published.sha256, published.size,
                lambda candidate: _verify_transaction_file(published, candidate),
            )
        except FileNotFoundError:
            pass
        _fsync_directory(target.parent)
        return
    else:
        if published is None:
            raise _error()
        _restore_backup_with_exchange(target, backup, published)
        return


def _target_matches_backup(target: Path, backup: _PinnedBackup | None) -> bool:
    if backup is None:
        return False
    try:
        _assert_exclusive_regular(target)
        _verify_backup_descriptor(backup)
        return _digest(target) == (backup.sha256, backup.size)
    except WorkflowError:
        return False


def _manual_recovery_error(
    backup: _PinnedBackup | None, recovery_marker: _PinnedTransactionFile | None,
) -> WorkflowError:
    recoveries = (backup.path if backup is not None else None,
                  recovery_marker.path if recovery_marker is not None else None)
    for recovery in recoveries:
        if recovery is not None and _entry_exists(recovery):
            return WorkflowError(
                f"workflow rollback failed; manual recovery required from {recovery.name}"
            )
    return WorkflowError("workflow rollback failed; manual recovery required")


def _recovery_pending_error(
    backup: _PinnedBackup | None, recovery_marker: _PinnedTransactionFile | None,
) -> WorkflowError:
    recoveries = (backup.path if backup is not None else None,
                  recovery_marker.path if recovery_marker is not None else None)
    for recovery in recoveries:
        if recovery is not None and _entry_exists(recovery):
            return WorkflowError(
                f"workflow cleanup failed; recovery is pending from {recovery.name}"
            )
    return WorkflowError("workflow cleanup failed; recovery is pending")


def _validate_cascade_transition(
    job: JobState,
    authorization: tuple[str, int] | None,
    resolution: tuple[str, str] | None,
) -> None:
    stage_ids = stage_ids_for(job)
    events = {
        stage_id: _cascade_event(job.stages[stage_id]["reason"])
        for stage_id in stage_ids
    }
    if job.expected_revision is None:
        if any(event is not None for event in events.values()):
            raise _error()
        return
    workflow = job.job_dir / "workflow.json"
    has_current_event = any(event is not None for event in events.values())
    if has_current_event:
        persisted = _read_payload(workflow)
        persisted_sha256, persisted_bytes = _digest(workflow)
        if _read_payload(workflow) != persisted:
            raise _error()
    else:
        try:
            persisted = _read_payload(workflow)
            persisted_sha256, persisted_bytes = _digest(workflow)
            if _read_payload(workflow) != persisted:
                return
        except (WorkflowError, OSError):
            return
        if (
            persisted["revision"] != job.expected_revision
            or persisted_sha256 != job.expected_sha256
            or persisted_bytes != job.expected_bytes
        ):
            return
    _normalize_stage_schema(persisted["stages"], persisted["version"])
    if (
        persisted["version"] != job.version
        or persisted["revision"] != job.expected_revision
        or persisted_sha256 != job.expected_sha256
        or persisted_bytes != job.expected_bytes
    ):
        raise _CasConflict("workflow update conflict")
    persisted_events = {
        stage_id: _cascade_event(stage["reason"])
        for stage_id, stage in persisted["stages"].items()
    }
    if not any(
        event is not None for event in (*events.values(), *persisted_events.values())
    ):
        return
    introduced = {
        stage_id
        for stage_id in stage_ids
        if events[stage_id] is not None
        and events[stage_id]
        != _cascade_event(persisted["stages"][stage_id]["reason"])
    }
    if authorization is not None:
        if not (
            resolution is None
            and type(authorization) is tuple
            and len(authorization) == 2
            and authorization[0] in stage_ids
            and type(authorization[1]) is int
        ):
            raise _error()
        trigger_stage, event_revision = authorization
        affected = _transitive_dependents(job.version, trigger_stage)
        downstream = affected[1:]
        event = {"trigger_stage": trigger_stage, "revision": event_revision}
        event_reason = _cascade_reason(trigger_stage, event_revision)
        if (
            event_revision != persisted["revision"] + 1
            or job.revision != event_revision
            or introduced != set(downstream)
            or any(
                job.stages[stage_id] != persisted["stages"][stage_id]
                for stage_id in stage_ids if stage_id not in affected
            )
        ):
            raise _error()
        trigger = job.stages[trigger_stage]
        if not (
            trigger["status"] == "needs_revision"
            and type(trigger["reason"]) is str
            and trigger["artifacts"] == []
            and trigger["ai_attempts"] == 0
            and _cascade_event(trigger["reason"]) is None
        ):
            raise _error()
        for stage_id in downstream:
            stage = job.stages[stage_id]
            if not (
                stage["status"] == "pending"
                and stage["reason"] == event_reason
                and stage["artifacts"] == []
                and stage["ai_attempts"] == 0
                and events[stage_id] == event
                and (
                    job.version == 1 or stage["artifact_scope"] == []
                )
            ):
                raise _error()
        return

    changed = {
        stage_id
        for stage_id in stage_ids
        if persisted_events[stage_id] is not None
        and job.stages[stage_id] != persisted["stages"][stage_id]
    }
    if resolution is None:
        if introduced or changed or job.revision != persisted["revision"]:
            raise _error()
        return
    if (
        introduced
        or type(resolution) is not tuple
        or len(resolution) != 2
        or resolution[0] not in stage_ids
        or resolution[1] not in {"mark_ready", "visual_ready", "approve", "block"}
        or job.revision != persisted["revision"] + 1
        or any(
            job.stages[stage_id] != persisted["stages"][stage_id]
            for stage_id in stage_ids if stage_id != resolution[0]
        )
    ):
        raise _error()
    stage_id, operation = resolution
    before = persisted["stages"][stage_id]
    after = job.stages[stage_id]
    if operation == "mark_ready":
        valid = (
            before["status"] in {"pending", "needs_revision"}
            and after["status"] == "ready_for_review"
            and after["reason"] is None
            and after["lineage"] == []
            and after["ai_attempts"] == before["ai_attempts"]
            and (job.version == 1 or after["artifact_scope"] == [])
        )
    elif operation == "visual_ready":
        valid = (
            stage_id == "visual_direction"
            and before["status"] in {"pending", "needs_revision", "ready_for_review"}
            and after["status"] == "ready_for_review"
            and after["reason"] is None
            and after["lineage"] == before["lineage"]
            and after["ai_attempts"] == before["ai_attempts"]
            and (job.version == 1 or after["artifact_scope"] == [])
        )
    elif operation == "approve":
        valid = (
            before["status"] == "ready_for_review"
            and after["status"] == "approved"
            and after["reason"] is None
            and after["artifacts"] == before["artifacts"]
            and after["ai_attempts"] == before["ai_attempts"]
            and after["lineage"] == before["lineage"]
            and (
                job.version == 1
                or after["artifact_scope"] == before["artifact_scope"]
            )
        )
    else:
        valid = (
            before["status"] in {"pending", "needs_revision"}
            and after["status"] == "blocked"
            and type(after["reason"]) is str
            and after["artifacts"] == []
            and after["lineage"] == before["lineage"]
            and (
                job.version == 1
                or after["artifact_scope"] == before["artifact_scope"]
            )
        )
    if not valid:
        raise _error()


def save_job(
    job: JobState,
    *,
    pins: list[_PinnedFile] | None = None,
    _cascade_transition: tuple[str, int] | None = None,
    _cascade_resolution: tuple[str, str] | None = None,
) -> None:
    if pins is None:
        pins = _validate_job(job, pin_files=True)
    else:
        try:
            _validate_job(job)
        except BaseException:
            _close_pins(pins)
            raise
    if job.expected_revision is None:
        if job.revision != 0:
            _close_pins(pins)
            raise _error()
    elif job.revision not in {job.expected_revision, job.expected_revision + 1}:
        _close_pins(pins)
        raise _error()
    try:
        _validate_cascade_transition(
            job, _cascade_transition, _cascade_resolution,
        )
    except BaseException:
        _close_pins(pins)
        raise
    stage: _PinnedTransactionFile | None = None
    backup: _PinnedBackup | None = None
    recovery_marker: _PinnedTransactionFile | None = None
    target: Path | None = None
    replace_attempted = False
    publish_durable = False
    rollback_succeeded = False
    cleanup_path: Path | None = None
    try:
        _verify_pins(pins)
        data = (json.dumps(_payload(job), ensure_ascii=False, indent=2, sort_keys=True,
                           allow_nan=False) + "\n").encode("utf-8")
        target = job.job_dir / "workflow.json"
        _assert_no_recovery_backup(job.job_dir)
        target_exists = _entry_exists(target)
        if target_exists:
            if job.expected_revision is None:
                raise _CasConflict("workflow update conflict")
            backup = _backup_existing(
                target, job.expected_revision, job.expected_sha256, job.expected_bytes,
            )
        else:
            recovery_marker = _write_recovery_marker(job.job_dir, data)
        stage = _write_stage(job.job_dir, data)
        _verify_pins(pins)
        if backup is not None:
            _verify_backup(backup, 1)
        replace_attempted = True
        _publish_transaction(
            stage, target,
            expected_revision=job.expected_revision if backup is not None else None,
            expected_sha256=job.expected_sha256 if backup is not None else None,
            expected_bytes=job.expected_bytes if backup is not None else None,
        )
        _verify_pins(pins)
        if backup is not None:
            _verify_backup(backup, 1)
        publish_durable = True
        if recovery_marker is not None:
            cleanup_path = recovery_marker.path
            _clear_recovery_marker(recovery_marker)
            close_error = _close_transaction_file(recovery_marker)
            recovery_marker = None
            if close_error is not None:
                raise _CommittedWorkflowError(
                    "workflow committed but descriptor cleanup failed"
                )
        if backup is not None:
            cleanup_path = backup.path
            _unlink_backup(backup, 1)
            close_error = _close_backup(backup)
            backup = None
            if close_error is not None:
                raise _CommittedWorkflowError(
                    "workflow committed but descriptor cleanup failed"
                )
    except _CasConflict:
        if backup is not None:
            raise _manual_recovery_error(backup, recovery_marker) from None
        raise
    except BaseException as failure:
        if (not isinstance(failure, _QuarantineError)
                and publish_durable and cleanup_path is not None):
            if not _entry_exists(cleanup_path):
                if recovery_marker is not None:
                    _close_transaction_file(recovery_marker)
                    recovery_marker = None
                _close_backup(backup)
                backup = None
                raise _CommittedWorkflowError(
                    "workflow committed but cleanup durability is pending"
                ) from None
            try:
                _restore_previous(target, backup, stage)
            except _QuarantineError:
                raise
            except BaseException:
                raise _manual_recovery_error(backup, recovery_marker) from None
            rollback_succeeded = True
            raise _recovery_pending_error(backup, recovery_marker) from None
        if replace_attempted:
            if _target_matches_backup(target, backup):
                rollback_succeeded = True
            else:
                try:
                    _restore_previous(target, backup, stage)
                except _QuarantineError:
                    raise
                except BaseException:
                    raise _manual_recovery_error(backup, recovery_marker) from None
                rollback_succeeded = True
        if recovery_marker is not None and (rollback_succeeded or not replace_attempted):
            try:
                _clear_recovery_marker(recovery_marker)
            except BaseException:
                raise _manual_recovery_error(backup, recovery_marker) from None
            _close_transaction_file(recovery_marker)
            recovery_marker = None
        if backup is not None and (rollback_succeeded or not replace_attempted):
            try:
                _unlink_backup(backup, 1)
            except BaseException:
                raise _manual_recovery_error(backup, recovery_marker) from None
            _close_backup(backup)
            backup = None
        raise
    finally:
        active_failure = sys.exc_info()[1] is not None
        close_error: BaseException | None = None
        try:
            if stage is not None:
                _unlink_transaction_file(stage)
        finally:
            for closer in (
                lambda: _close_transaction_file(stage),
                lambda: _close_transaction_file(recovery_marker),
                lambda: _close_backup(backup),
                lambda: _close_pins(pins),
            ):
                error = closer()
                if close_error is None and error is not None:
                    close_error = error
        if close_error is not None and not active_failure:
            if publish_durable:
                raise _CommittedWorkflowError(
                    "workflow committed but descriptor cleanup failed"
                ) from None
            raise WorkflowError("workflow descriptor cleanup failed") from None
    job.expected_revision = job.revision
    job.expected_sha256 = hashlib.sha256(data).hexdigest()
    job.expected_bytes = len(data)


def _stage(job: JobState, stage_id: str) -> dict[str, Any]:
    if stage_id not in stage_ids_for(job):
        raise WorkflowError("unknown workflow stage")
    return job.stages[stage_id]


def _restore_job_snapshot(
    job: JobState, stages: dict[str, dict[str, Any]], revision: int,
) -> None:
    job.stages.clear()
    job.stages.update(stages)
    job.revision = revision


def _synchronize_committed_job(job: JobState) -> None:
    persisted = load_job(job.job_dir)
    job.root = persisted.root
    job.job_dir = persisted.job_dir
    job.job_id = persisted.job_id
    job.inputs = persisted.inputs
    job.revision = persisted.revision
    job.expected_revision = persisted.expected_revision
    job.expected_sha256 = persisted.expected_sha256
    job.expected_bytes = persisted.expected_bytes
    job.version = persisted.version
    job.stages.clear()
    job.stages.update(persisted.stages)


def require_runnable(job: JobState, stage_id: str) -> None:
    _validate_job(job)
    if job.version == 2:
        from .startup import require_startup
        require_startup(job)
    stage = _stage(job, stage_id)
    if stage["status"] not in {"pending", "needs_revision"}:
        raise WorkflowError("workflow stage is not runnable")
    if current_stage(job) != stage_id:
        raise WorkflowError("workflow stage is not the current review stage")
    dependencies = _dependencies_for_version(job.version)[stage_id]
    if any(
        job.stages[dependency]["status"] != "approved"
        for dependency in dependencies
    ):
        raise WorkflowError("workflow stage prerequisites are not approved")


def _artifact_record(job: JobState, path: Path) -> dict[str, Any]:
    record = _bound_record(job.job_dir, path)
    _assert_artifact_path(record["path"])
    return record


def mark_ready(job: JobState, stage_id: str, artifacts: Iterable[Path]) -> None:
    require_runnable(job, stage_id)
    stage = _stage(job, stage_id)
    previous_stages = copy.deepcopy(job.stages)
    previous_revision = job.revision
    updates = {
        "status": "ready_for_review",
        "reason": None,
        "lineage": [],
        "artifacts": [_artifact_record(job, path) for path in artifacts],
    }
    if job.version == 2:
        updates["artifact_scope"] = []
    stage.update(**updates)
    job.revision += 1
    try:
        save_job(job, _cascade_resolution=(stage_id, "mark_ready"))
    except _CommittedWorkflowError:
        _synchronize_committed_job(job)
        raise
    except BaseException:
        _restore_job_snapshot(job, previous_stages, previous_revision)
        raise


def mark_visual_ready(job: JobState, artifacts: Iterable[Path]) -> None:
    """Replace the visual candidate after proposal approval, preserving lineage."""
    stage = _stage(job, "visual_direction")
    if stage["status"] == "ready_for_review":
        if current_stage(job) != "visual_direction":
            raise WorkflowError("visual direction is not the current stage")
    else:
        require_runnable(job, "visual_direction")
    previous_stages = copy.deepcopy(job.stages)
    previous_revision = job.revision
    stage.update(status="ready_for_review", reason=None,
                 artifacts=[_artifact_record(job, path) for path in artifacts], artifact_scope=[])
    job.revision += 1
    try:
        save_job(job, _cascade_resolution=("visual_direction", "visual_ready"))
    except _CommittedWorkflowError:
        _synchronize_committed_job(job)
        raise
    except BaseException:
        _restore_job_snapshot(job, previous_stages, previous_revision)
        raise


def approve(job: JobState, stage_id: str) -> None:
    pins = _validate_job(job, pin_files=True)
    try:
        stage = _stage(job, stage_id)
        if stage["status"] != "ready_for_review":
            raise WorkflowError("only a ready stage can be approved")
    except BaseException:
        _close_pins(pins)
        raise
    previous_stage = stage.copy()
    previous_revision = job.revision
    stage.update(status="approved", reason=None)
    job.revision += 1
    try:
        save_job(
            job, pins=pins,
            _cascade_resolution=(stage_id, "approve"),
        )
    except _CommittedWorkflowError:
        _synchronize_committed_job(job)
        raise
    except BaseException:
        stage.clear()
        stage.update(previous_stage)
        job.revision = previous_revision
        raise


def revise(
    job: JobState, stage_id: str, reason: str,
    artifact_scope: tuple[str, ...] = (),
) -> None:
    if type(reason) is not str:
        raise WorkflowError("workflow revision reason must be text")
    if (
        type(artifact_scope) is not tuple
        or any(type(value) is not str or not value for value in artifact_scope)
        or len(set(artifact_scope)) != len(artifact_scope)
        or (artifact_scope and getattr(job, "version", 1) != 2)
    ):
        raise WorkflowError("invalid workflow artifact scope")
    pins = _validate_job(job, pin_files=True)
    try:
        _stage(job, stage_id)
        stage_ids = stage_ids_for(job)
        affected_ids = _transitive_dependents(job.version, stage_id)
        lineages: dict[str, list[dict[str, Any]]] = {}
        pin_index = len(job.inputs)
        for current_id in stage_ids:
            records = []
            for artifact in job.stages[current_id]["artifacts"]:
                pin = pins[pin_index]
                pin_index += 1
                parent = os.lstat(pin.path.parent)
                if not stat.S_ISDIR(parent.st_mode):
                    raise _error()
                records.append({
                    **artifact, "device": pin.device, "inode": pin.inode,
                    "parent_device": parent.st_dev, "parent_inode": parent.st_ino,
                })
            lineages[current_id] = records
        if pin_index != len(pins):
            raise _error()
    except BaseException:
        _close_pins(pins)
        raise
    previous_stages = copy.deepcopy(job.stages)
    previous_revision = job.revision
    event_revision = job.revision + 1
    for position, affected_id in enumerate(affected_ids):
        stage = job.stages[affected_id]
        lineage = lineages[affected_id] if stage["artifacts"] else stage["lineage"]
        updates = {
            "status": "needs_revision" if position == 0 else "pending",
            "reason": (
                reason if position == 0
                else _cascade_reason(stage_id, event_revision)
            ),
            "artifacts": [],
            "ai_attempts": 0,
            "lineage": lineage,
        }
        if job.version == 2:
            updates["artifact_scope"] = list(artifact_scope) if position == 0 else []
        stage.update(**updates)
    job.revision += 1
    try:
        save_job(
            job,
            pins=pins,
            _cascade_transition=(stage_id, event_revision),
        )
    except _CommittedWorkflowError:
        _synchronize_committed_job(job)
        raise
    except BaseException:
        _restore_job_snapshot(job, previous_stages, previous_revision)
        raise


def block(job: JobState, stage_id: str, reason: str, ai_attempts: int) -> None:
    if type(reason) is not str:
        raise WorkflowError("workflow block reason must be text")
    if type(ai_attempts) is not int or ai_attempts < 0:
        raise WorkflowError("ai_attempts must be a non-negative integer")
    require_runnable(job, stage_id)
    stage = _stage(job, stage_id)
    previous_stages = copy.deepcopy(job.stages)
    previous_revision = job.revision
    stage.update(status="blocked", reason=reason, artifacts=[], ai_attempts=ai_attempts)
    job.revision += 1
    try:
        save_job(job, _cascade_resolution=(stage_id, "block"))
    except _CommittedWorkflowError:
        _synchronize_committed_job(job)
        raise
    except BaseException:
        _restore_job_snapshot(job, previous_stages, previous_revision)
        raise

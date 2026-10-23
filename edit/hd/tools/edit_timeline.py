"""Build reviewable cleanup decisions and render an approved A-roll timeline."""

from __future__ import annotations

import hashlib
import copy
import errno
import fcntl
import json
import math
import os
import re
import secrets
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .state import JobState, load_job, mark_ready, require_runnable, revise
from .cleanup_risk import assess_cleanup_risk


class EditTimelineError(RuntimeError):
    """A safe, user-facing edit-timeline failure."""


@dataclass
class _PinnedFile:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int
    links: int = 1


@dataclass(frozen=True)
class _TreeSnapshot:
    device: int
    inode: int
    records: dict[str, tuple[int, int, str, int]]


def _close_pin(pin: _PinnedFile) -> None:
    descriptor = pin.descriptor
    pin.descriptor = -1
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


_SEGMENT_KEYS = {
    "action",
    "word_start",
    "word_end",
    "source_start",
    "source_end",
    "original_sentence",
    "cleaned_sentence",
    "reason",
    "breathing_padding",
}


def _finite_number(value: Any) -> float:
    if type(value) not in {int, float}:
        raise EditTimelineError("invalid edit plan")
    number = float(value)
    if not math.isfinite(number):
        raise EditTimelineError("invalid edit plan")
    return number


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EditTimelineError("invalid edit plan")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise EditTimelineError("invalid edit plan")


def _fail() -> EditTimelineError:
    return EditTimelineError("edit timeline operation failed")


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
    except OSError:
        raise _fail() from None
    return digest.hexdigest(), size


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _fail()
    except (OSError, ValueError):
        raise _fail() from None


def _pin_record(base: Path, record: Any) -> _PinnedFile:
    if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
        raise _fail()
    if type(record["path"]) is not str or not record["path"]:
        raise _fail()
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise _fail()
    path = base.joinpath(*relative.parts)
    _reject_symlink_components(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        digest, size = _digest_descriptor(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or not os.path.samestat(opened, named)
            or type(record["sha256"]) is not str
            or digest != record["sha256"]
            or type(record["bytes"]) is not int
            or size != record["bytes"]
        ):
            raise _fail()
        return _PinnedFile(path, descriptor, opened.st_dev, opened.st_ino, digest, size)
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _verify_pin(pinned: _PinnedFile) -> None:
    _reject_symlink_components(pinned.path)
    try:
        opened = os.fstat(pinned.descriptor)
        named = os.lstat(pinned.path)
    except OSError:
        raise _fail() from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or opened.st_nlink != pinned.links
        or named.st_nlink != pinned.links
        or (opened.st_dev, opened.st_ino) != (pinned.device, pinned.inode)
        or (named.st_dev, named.st_ino) != (pinned.device, pinned.inode)
        or _digest_descriptor(pinned.descriptor) != (pinned.sha256, pinned.size)
    ):
        raise _fail()


def _descriptor_bytes(descriptor: int, maximum: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise _fail()
        os.lseek(descriptor, 0, os.SEEK_SET)
        return b"".join(chunks)
    except OSError:
        raise _fail() from None


def _strict_json_bytes(source: bytes) -> Any:
    try:
        text = source.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, EditTimelineError):
        raise _fail() from None


def _write_exclusive(path: Path, source: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(source)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise _fail()
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        raise
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _json_bytes(payload: Any) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _fail() from None


def _make_stage(job_dir: Path, target_name: str) -> Path:
    stage = job_dir / f".{target_name}.stage-{secrets.token_hex(16)}"
    try:
        stage.mkdir(mode=0o700)
        _fsync_directory(job_dir)
    except BaseException:
        raise _fail() from None
    return stage


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise _fail() from None


def _snapshot_tree(
    directory: Path,
    expected_names: set[str],
    *,
    allow_partial: bool = False,
) -> _TreeSnapshot:
    try:
        directory_status = os.lstat(directory)
        names = set(os.listdir(directory))
    except OSError:
        raise _fail() from None
    if (
        not stat.S_ISDIR(directory_status.st_mode)
        or (not allow_partial and names != expected_names)
        or (allow_partial and not names <= expected_names)
    ):
        raise _fail()
    records: dict[str, tuple[int, int, str, int]] = {}
    for name in sorted(names):
        path = directory / name
        descriptor: int | None = None
        try:
            descriptor = os.open(
                str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            named = os.lstat(path)
            digest, size = _digest_descriptor(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not os.path.samestat(opened, named)
            ):
                raise _fail()
            records[name] = (opened.st_dev, opened.st_ino, digest, size)
        except BaseException:
            raise _fail() from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    try:
        directory_after = os.lstat(directory)
    except OSError:
        raise _fail() from None
    if not os.path.samestat(directory_status, directory_after):
        raise _fail()
    return _TreeSnapshot(
        directory_status.st_dev,
        directory_status.st_ino,
        records,
    )


def _tree_matches(directory: Path, expected: _TreeSnapshot) -> bool:
    try:
        return _snapshot_tree(directory, set(expected.records)) == expected
    except EditTimelineError:
        return False


def _retained_path(path: Path, label: str) -> Path:
    return path.parent / f".{path.name}.{label}.retained-{secrets.token_hex(16)}"


def _truncate_snapshot(directory: Path, snapshot: _TreeSnapshot) -> None:
    pins: list[_PinnedFile] = []
    try:
        if not _tree_matches(directory, snapshot):
            raise _fail()
        for name, expected in snapshot.records.items():
            pin = _pin_path(directory / name)
            pins.append(pin)
            if (
                pin.device,
                pin.inode,
                pin.sha256,
                pin.size,
            ) != expected:
                raise _fail()
        if not _tree_matches(directory, snapshot):
            raise _fail()
        for pin in pins:
            _verify_pin(pin)
        for pin in pins:
            os.ftruncate(pin.descriptor, 0)
            os.fsync(pin.descriptor)
    except BaseException:
        raise _fail() from None
    finally:
        for pin in pins:
            _close_pin(pin)


def _discard_directory(
    directory: Path,
    expected_names: set[str],
    *,
    allow_partial: bool = False,
) -> None:
    try:
        if not _entry_exists(directory):
            return
        snapshot = _snapshot_tree(
            directory, expected_names, allow_partial=allow_partial,
        )
        retained = _retained_path(directory, "generation")
        _replace(directory, retained)
        _fsync_directory(directory.parent)
        if not _tree_matches(retained, snapshot):
            raise _fail()
        _truncate_snapshot(retained, snapshot)
    except BaseException:
        raise _fail() from None


_replace = os.replace


def _file_record(pin: _PinnedFile) -> dict[str, Any]:
    return {
        "device": pin.device,
        "inode": pin.inode,
        "sha256": pin.sha256,
        "bytes": pin.size,
    }


def _pin_path(
    path: Path, expected: Any | None = None, *, expected_links: int = 1,
) -> _PinnedFile:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(path), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        digest, size = _digest_descriptor(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != expected_links
            or not os.path.samestat(opened, named)
        ):
            raise _fail()
        pin = _PinnedFile(
            path, descriptor, opened.st_dev, opened.st_ino, digest, size,
            expected_links,
        )
        if expected is not None and _file_record(pin) != expected:
            raise _fail()
        return pin
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _fail() from None


def _pin_read_only_path(path: Path) -> _PinnedFile:
    _reject_symlink_components(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        digest, size = _digest_descriptor(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not os.path.samestat(opened, named)
        ):
            raise _fail()
        return _PinnedFile(
            path, descriptor, opened.st_dev, opened.st_ino, digest, size,
        )
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _fail() from None


def _create_empty_pin(path: Path) -> _PinnedFile:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(path),
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not os.path.samestat(opened, named)
        ):
            raise _fail()
        return _PinnedFile(
            path, descriptor, opened.st_dev, opened.st_ino,
            hashlib.sha256(b"").hexdigest(), 0,
        )
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _fail() from None


def _rewrite_pin(pin: _PinnedFile, source: bytes) -> None:
    try:
        _verify_pin(pin)
        os.ftruncate(pin.descriptor, 0)
        os.lseek(pin.descriptor, 0, os.SEEK_SET)
        view = memoryview(source)
        while view:
            written = os.write(pin.descriptor, view)
            if written <= 0:
                raise _fail()
            view = view[written:]
        os.fsync(pin.descriptor)
        pin.sha256 = hashlib.sha256(source).hexdigest()
        pin.size = len(source)
        _verify_pin(pin)
    except BaseException:
        raise _fail() from None


def _retire_pin(pin: _PinnedFile, label: str) -> None:
    retained = _retained_path(pin.path, label)
    try:
        _verify_pin(pin)
        _replace(pin.path, retained)
        _fsync_directory(pin.path.parent)
        pin.path = retained
        _verify_pin(pin)
        os.ftruncate(pin.descriptor, 0)
        os.fsync(pin.descriptor)
    except BaseException:
        raise _fail() from None
    finally:
        _close_pin(pin)


def _lock_descriptor(lock: _PinnedFile) -> None:
    try:
        fcntl.flock(lock.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as failure:
        if failure.errno in {errno.EACCES, errno.EAGAIN}:
            raise _fail() from None
        raise _fail() from None
    _verify_pin(lock)


def _acquire_transaction_lock(
    job: JobState,
    target: Path,
    stage: Path,
    backup: Path,
    stage_id: str,
    restore_ready: bool,
    old_tree: _TreeSnapshot | None,
    new_tree: _TreeSnapshot,
    request_binding: dict[str, Any] | None = None,
) -> tuple[_PinnedFile, _PinnedFile]:
    parent = target.parent
    target_name = target.name
    generation = stage.name.rsplit("-", 1)[-1]
    if (
        len(generation) != 32
        or any(character not in "0123456789abcdef" for character in generation)
    ):
        raise _fail()
    path = parent / f".{target_name}.lock"
    marker_stage = _create_empty_pin(
        parent / f".{target_name}.marker-stage-{generation}",
    )
    try:
        lock_stage = _create_empty_pin(
            parent / f".{target_name}.lock-stage-{generation}",
        )
    except BaseException:
        _close_pin(marker_stage)
        raise _fail() from None
    installed = False
    canonical: _PinnedFile | None = None
    returned = False
    try:
        binding = (
            _validated_request_binding(request_binding)
            if request_binding is not None else None
        )
        payload = {
            "version": 4 if binding is not None else 3,
            "phase": "acquiring",
            "target": target_name,
            "generation": generation,
            "operation": stage_id,
            "stage": stage.name,
            "backup": backup.name,
            "marker": _marker_path(parent, target_name).name,
            "marker_stage": {
                "name": marker_stage.path.name,
                "device": marker_stage.device,
                "inode": marker_stage.inode,
            },
            "restore_ready": restore_ready,
            "old_tree": _tree_payload(old_tree),
            "new_tree": _tree_payload(new_tree),
            "committed_artifacts": _tree_artifacts_payload(target_name, new_tree),
            "workflow_before": {
                "revision": job.revision,
                "stage": copy.deepcopy(job.stages[stage_id]),
            },
            "lock_stage": {
                "name": lock_stage.path.name,
                "device": lock_stage.device,
                "inode": lock_stage.inode,
            },
            **({"request_binding": binding} if binding is not None else {}),
        }
        source = _json_bytes(payload)
        if (
            os.environ.get("HD_EDIT_TIMELINE_CRASH_CHECKPOINT")
            == "lock_stage_partial_write"
            or os.environ.get("HD_EDIT_TIMELINE_HOLD_CHECKPOINT")
            == "lock_stage_partial_write"
        ):
            _rewrite_pin(lock_stage, source[:max(1, len(source) // 2)])
            _crash_checkpoint("lock_stage_partial_write")
        _rewrite_pin(lock_stage, source)
        _crash_checkpoint("lock_stage_fsync")
        _lock_descriptor(lock_stage)
        os.link(str(lock_stage.path), str(path))
        installed = True
        lock_stage.links = 2
        _crash_checkpoint("lock_canonical_installed")
        _fsync_directory(parent)
        _crash_checkpoint("lock_canonical_dirsync")
        canonical = _pin_path(
            path, _file_record(lock_stage), expected_links=2,
        )
        if (canonical.device, canonical.inode) != (
            lock_stage.device, lock_stage.inode,
        ):
            raise _fail()
        _close_pin(canonical)
        canonical = None
        lock_stage.path = path
        _verify_pin(lock_stage)
        returned = True
        return lock_stage, marker_stage
    except BaseException:
        if canonical is not None:
            _close_pin(canonical)
        if installed:
            _close_pin(lock_stage)
        raise _fail() from None
    finally:
        if not returned:
            _close_pin(lock_stage)
            _close_pin(marker_stage)


def _release_transaction_lock(lock: _PinnedFile) -> None:
    _retire_pin(lock, "lock")


def _tree_payload(snapshot: _TreeSnapshot | None) -> Any:
    if snapshot is None:
        return None
    return {
        "device": snapshot.device,
        "inode": snapshot.inode,
        "records": {
            name: {
                "device": record[0],
                "inode": record[1],
                "sha256": record[2],
                "bytes": record[3],
            }
            for name, record in snapshot.records.items()
        },
    }


def _validated_request_binding(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"sha256", "bytes"}
        or type(value["sha256"]) is not str
        or len(value["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in value["sha256"])
        or type(value["bytes"]) is not int
        or value["bytes"] < 0
    ):
        raise _fail()
    return {"sha256": value["sha256"], "bytes": value["bytes"]}


def _tree_artifacts_payload(
    target_name: str, snapshot: _TreeSnapshot,
) -> list[dict[str, Any]]:
    return [
        {
            "path": f"{target_name}/{name}",
            "sha256": snapshot.records[name][2],
            "bytes": snapshot.records[name][3],
        }
        for name in sorted(snapshot.records)
    ]


def _tree_lineage_payload(
    target_name: str, snapshot: _TreeSnapshot,
) -> list[dict[str, Any]]:
    return [
        {
            "path": f"{target_name}/{name}",
            "sha256": snapshot.records[name][2],
            "bytes": snapshot.records[name][3],
            "device": snapshot.records[name][0],
            "inode": snapshot.records[name][1],
            "parent_device": snapshot.device,
            "parent_inode": snapshot.inode,
        }
        for name in sorted(snapshot.records)
    ]


def _tree_from_payload(value: Any) -> _TreeSnapshot | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"device", "inode", "records"}:
        raise _fail()
    if (
        type(value["device"]) is not int
        or value["device"] < 0
        or type(value["inode"]) is not int
        or value["inode"] < 0
        or type(value["records"]) is not dict
    ):
        raise _fail()
    records: dict[str, tuple[int, int, str, int]] = {}
    for name, record in value["records"].items():
        if (
            type(name) is not str
            or not name
            or "/" in name
            or "\\" in name
            or type(record) is not dict
            or set(record) != {"device", "inode", "sha256", "bytes"}
            or type(record["device"]) is not int
            or record["device"] < 0
            or type(record["inode"]) is not int
            or record["inode"] < 0
            or type(record["sha256"]) is not str
            or len(record["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in record["sha256"])
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
        ):
            raise _fail()
        records[name] = (
            record["device"], record["inode"], record["sha256"], record["bytes"],
        )
    return _TreeSnapshot(value["device"], value["inode"], records)


def _safe_generation_name(name: Any, target_name: str, kind: str) -> bool:
    prefix = f".{target_name}.{kind}-"
    if type(name) is not str or not name.startswith(prefix):
        return False
    token = name[len(prefix):]
    return len(token) == 32 and all(character in "0123456789abcdef" for character in token)


def _marker_path(parent: Path, target_name: str) -> Path:
    return parent / f".{target_name}.generation.marker"


def _validate_workflow_before_payload(value: Any) -> dict[str, Any]:
    stage = value.get("stage") if type(value) is dict else None
    if type(stage) is dict and set(stage) == {
        "status", "reason", "artifacts", "ai_attempts",
    }:
        stage["lineage"] = []
    stage_keys = {
        "status", "reason", "artifacts", "ai_attempts", "lineage",
    }
    if type(stage) is dict and "artifact_scope" in stage:
        stage_keys.add("artifact_scope")
    if (
        type(value) is not dict
        or set(value) != {"revision", "stage"}
        or type(value["revision"]) is not int
        or value["revision"] < 0
        or type(value["stage"]) is not dict
        or set(value["stage"]) != stage_keys
        or value["stage"]["status"] not in {
            "pending", "ready_for_review", "approved", "needs_revision", "blocked",
        }
        or (
            value["stage"]["reason"] is not None
            and type(value["stage"]["reason"]) is not str
        )
        or type(value["stage"]["artifacts"]) is not list
        or type(value["stage"]["lineage"]) is not list
        or type(value["stage"]["ai_attempts"]) is not int
        or value["stage"]["ai_attempts"] < 0
        or (
            "artifact_scope" in value["stage"]
            and (
                type(value["stage"]["artifact_scope"]) is not list
                or any(
                    type(item) is not str or not item
                    for item in value["stage"]["artifact_scope"]
                )
                or len(set(value["stage"]["artifact_scope"]))
                != len(value["stage"]["artifact_scope"])
            )
        )
    ):
        raise _fail()
    for artifact in value["stage"]["artifacts"]:
        if (
            type(artifact) is not dict
            or set(artifact) != {"path", "sha256", "bytes"}
            or type(artifact["path"]) is not str
            or not artifact["path"]
            or type(artifact["sha256"]) is not str
            or len(artifact["sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in artifact["sha256"]
            )
            or type(artifact["bytes"]) is not int
            or artifact["bytes"] < 0
        ):
            raise _fail()
    lineage_keys = {
        "path", "sha256", "bytes", "device", "inode",
        "parent_device", "parent_inode",
    }
    for record in value["stage"]["lineage"]:
        if type(record) is not dict or set(record) != lineage_keys:
            raise _fail()
        path = record["path"]
        if type(path) is not str or not path or "\x00" in path or "\\" in path:
            raise _fail()
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise _fail()
        if len(parts) == 1 and (
            parts[0] == "workflow.json"
            or (
                parts[0].startswith(".workflow.")
                and parts[0].endswith(
                    (".stage", ".backup", ".marker", ".recovery",
                     ".quarantine", ".retained")
                )
            )
        ):
            raise _fail()
        if (
            type(record["sha256"]) is not str
            or len(record["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in record["sha256"])
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
            or type(record["device"]) is not int
            or record["device"] < 0
            or type(record["parent_device"]) is not int
            or record["parent_device"] < 0
            or type(record["inode"]) is not int
            or record["inode"] <= 0
            or type(record["parent_inode"]) is not int
            or record["parent_inode"] <= 0
        ):
            raise _fail()
    return value


def _strict_lock_payload(
    lock: _PinnedFile, target_name: str,
) -> dict[str, Any]:
    payload = _strict_json_bytes(_descriptor_bytes(lock.descriptor, 256 * 1024))
    base_keys = {
        "version", "phase", "target", "generation", "operation", "stage",
        "backup", "marker", "marker_stage", "restore_ready", "old_tree",
        "new_tree", "committed_artifacts", "workflow_before", "lock_stage",
    }
    if type(payload) is not dict or type(payload.get("version")) is not int:
        raise _fail()
    if payload["version"] == 3 and set(payload) == base_keys:
        request_binding = None
    elif payload["version"] == 4 and set(payload) == base_keys | {"request_binding"}:
        request_binding = _validated_request_binding(payload["request_binding"])
    else:
        raise _fail()
    lock_stage = payload["lock_stage"]
    marker_stage = payload["marker_stage"]
    if (
        payload["phase"] != "acquiring"
        or payload["target"] != target_name
        or type(payload["generation"]) is not str
        or len(payload["generation"]) != 32
        or any(
            character not in "0123456789abcdef"
            for character in payload["generation"]
        )
        or type(payload["operation"]) is not str
        or not payload["operation"]
        or not _safe_generation_name(payload["stage"], target_name, "stage")
        or payload["stage"].rsplit("-", 1)[-1] != payload["generation"]
        or not _safe_generation_name(payload["backup"], target_name, "backup")
        or payload["marker"] != _marker_path(lock.path.parent, target_name).name
        or type(marker_stage) is not dict
        or set(marker_stage) != {"name", "device", "inode"}
        or not _safe_generation_name(
            marker_stage["name"], target_name, "marker-stage",
        )
        or marker_stage["name"].rsplit("-", 1)[-1] != payload["generation"]
        or type(marker_stage["device"]) is not int
        or marker_stage["device"] < 0
        or type(marker_stage["inode"]) is not int
        or marker_stage["inode"] < 0
        or type(payload["restore_ready"]) is not bool
        or type(lock_stage) is not dict
        or set(lock_stage) != {"name", "device", "inode"}
        or not _safe_generation_name(lock_stage["name"], target_name, "lock-stage")
        or lock_stage["name"].rsplit("-", 1)[-1] != payload["generation"]
        or type(lock_stage["device"]) is not int
        or lock_stage["device"] < 0
        or type(lock_stage["inode"]) is not int
        or lock_stage["inode"] < 0
    ):
        raise _fail()
    payload["old_tree"] = _tree_from_payload(payload["old_tree"])
    payload["new_tree"] = _tree_from_payload(payload["new_tree"])
    if payload["new_tree"] is None:
        raise _fail()
    if payload["committed_artifacts"] != _tree_artifacts_payload(
        target_name, payload["new_tree"],
    ):
        raise _fail()
    payload["workflow_before"] = _validate_workflow_before_payload(
        payload["workflow_before"],
    )
    payload["request_binding"] = request_binding
    return payload


def _write_generation_marker(
    job: JobState,
    target: Path,
    stage: Path,
    backup: Path,
    stage_id: str,
    restore_ready: bool,
    lock: _PinnedFile,
    marker_stage: _PinnedFile,
    old_tree: _TreeSnapshot | None,
    new_tree: _TreeSnapshot,
    request_binding: dict[str, Any] | None = None,
) -> _PinnedFile:
    marker = _marker_path(target.parent, target.name)
    generation = stage.name.rsplit("-", 1)[-1]
    installed = False
    canonical: _PinnedFile | None = None
    try:
        binding = (
            _validated_request_binding(request_binding)
            if request_binding is not None else None
        )
        payload = {
            "version": 3 if binding is not None else 2,
            "generation": generation,
            "target": target.name,
            "stage": stage.name,
            "backup": backup.name,
            "stage_id": stage_id,
            "restore_ready": restore_ready,
            "old_tree": _tree_payload(old_tree),
            "new_tree": _tree_payload(new_tree),
            "lock": {"device": lock.device, "inode": lock.inode},
            "marker_stage": {
                "name": marker_stage.path.name,
                "device": marker_stage.device,
                "inode": marker_stage.inode,
            },
            "workflow_before": {
                "revision": job.revision,
                "stage": copy.deepcopy(job.stages[stage_id]),
            },
            **({"request_binding": binding} if binding is not None else {}),
        }
        source = _json_bytes(payload)
        if (
            os.environ.get("HD_EDIT_TIMELINE_CRASH_CHECKPOINT")
            == "marker_stage_partial_write"
            or os.environ.get("HD_EDIT_TIMELINE_HOLD_CHECKPOINT")
            == "marker_stage_partial_write"
        ):
            _rewrite_pin(marker_stage, source[:max(1, len(source) // 2)])
            _crash_checkpoint("marker_stage_partial_write")
        _rewrite_pin(marker_stage, source)
        _crash_checkpoint("marker_stage_fsync")
        _verify_pin(lock)
        _verify_pin(marker_stage)
        os.link(str(marker_stage.path), str(marker))
        installed = True
        marker_stage.links = 2
        _crash_checkpoint("marker_canonical_installed")
        _fsync_directory(target.parent)
        _crash_checkpoint("marker_canonical_dirsync")
        canonical = _pin_path(
            marker, _file_record(marker_stage), expected_links=2,
        )
        if (canonical.device, canonical.inode) != (
            marker_stage.device, marker_stage.inode,
        ):
            _close_pin(canonical)
            raise _fail()
        _verify_pin(lock)
        _verify_pin(marker_stage)
        _verify_pin(canonical)
        return canonical
    except BaseException:
        if canonical is not None:
            _close_pin(canonical)
        if not installed:
            try:
                _retire_pin(marker_stage, "marker-stage")
            except EditTimelineError:
                _close_pin(marker_stage)
        raise
    finally:
        _close_pin(marker_stage)


def _read_generation_marker(
    parent: Path,
    target_name: str,
    stage_id: str,
    restore_ready: bool,
    request_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], _PinnedFile, _PinnedFile]:
    marker = _pin_path(
        _marker_path(parent, target_name), expected_links=2,
    )
    try:
        payload = _strict_json_bytes(_descriptor_bytes(marker.descriptor, 256 * 1024))
        base_keys = {
            "version", "generation", "target", "stage", "backup", "stage_id",
            "restore_ready", "old_tree", "new_tree", "lock", "marker_stage",
            "workflow_before",
        }
        if type(payload) is not dict or type(payload.get("version")) is not int:
            raise _fail()
        if payload["version"] == 2 and set(payload) == base_keys:
            marker_binding = None
        elif payload["version"] == 3 and set(payload) == base_keys | {"request_binding"}:
            marker_binding = _validated_request_binding(payload["request_binding"])
        else:
            raise _fail()
        expected_binding = (
            _validated_request_binding(request_binding)
            if request_binding is not None else None
        )
        if marker_binding != expected_binding:
            raise _fail()
        if (
            payload["target"] != target_name
            or payload["stage_id"] != stage_id
            or type(payload["restore_ready"]) is not bool
            or payload["restore_ready"] != restore_ready
            or not _safe_generation_name(payload["stage"], target_name, "stage")
            or not _safe_generation_name(payload["backup"], target_name, "backup")
            or type(payload["generation"]) is not str
            or payload["stage"].rsplit("-", 1)[-1] != payload["generation"]
            or type(payload["lock"]) is not dict
            or set(payload["lock"]) != {"device", "inode"}
            or type(payload["lock"]["device"]) is not int
            or payload["lock"]["device"] < 0
            or type(payload["lock"]["inode"]) is not int
            or payload["lock"]["inode"] < 0
            or type(payload["marker_stage"]) is not dict
            or set(payload["marker_stage"]) != {"name", "device", "inode"}
            or not _safe_generation_name(
                payload["marker_stage"]["name"], target_name, "marker-stage",
            )
            or payload["marker_stage"]["name"].rsplit("-", 1)[-1]
            != payload["generation"]
            or type(payload["marker_stage"]["device"]) is not int
            or payload["marker_stage"]["device"] < 0
            or type(payload["marker_stage"]["inode"]) is not int
            or payload["marker_stage"]["inode"] < 0
        ):
            raise _fail()
        payload["workflow_before"] = _validate_workflow_before_payload(
            payload["workflow_before"],
        )
        payload["old_tree"] = _tree_from_payload(payload["old_tree"])
        payload["new_tree"] = _tree_from_payload(payload["new_tree"])
        if payload["new_tree"] is None:
            raise _fail()
        payload["request_binding"] = marker_binding
        lock = _pin_path(
            parent / f".{target_name}.lock", expected_links=2,
        )
        if (lock.device, lock.inode) != (
            payload["lock"]["device"], payload["lock"]["inode"],
        ):
            raise _fail()
        _lock_descriptor(lock)
        lock_payload = _strict_lock_payload(lock, target_name)
        if (
            lock_payload["generation"] != payload["generation"]
            or lock_payload["operation"] != stage_id
            or lock_payload["stage"] != payload["stage"]
            or lock_payload["backup"] != payload["backup"]
            or lock_payload["marker_stage"] != payload["marker_stage"]
            or lock_payload["restore_ready"] != restore_ready
            or lock_payload["old_tree"] != payload["old_tree"]
            or lock_payload["new_tree"] != payload["new_tree"]
            or lock_payload["workflow_before"] != payload["workflow_before"]
            or lock_payload["request_binding"] != marker_binding
        ):
            raise _fail()
        lock_stage_record = lock_payload["lock_stage"]
        lock_stage = _pin_path(
            parent / lock_stage_record["name"],
            _file_record(lock),
            expected_links=2,
        )
        if (lock_stage.device, lock_stage.inode) != (lock.device, lock.inode):
            raise _fail()
        _close_pin(lock_stage)
        marker_stage = _pin_path(
            parent / payload["marker_stage"]["name"],
            _file_record(marker),
            expected_links=2,
        )
        if (marker_stage.device, marker_stage.inode) != (marker.device, marker.inode):
            raise _fail()
        _close_pin(marker_stage)
        _verify_pin(marker)
        _verify_pin(lock)
        return payload, marker, lock
    except BaseException:
        if "lock_stage" in locals():
            _close_pin(lock_stage)
        if "marker_stage" in locals():
            _close_pin(marker_stage)
        if "lock" in locals():
            _close_pin(lock)
        _close_pin(marker)
        raise _fail() from None


def _finalize_transaction_metadata(marker: _PinnedFile, lock: _PinnedFile) -> None:
    _retire_pin(marker, "marker")
    _crash_checkpoint("marker_retired")
    _release_transaction_lock(lock)


def _preserve_unknown_tree(path: Path, label: str) -> None:
    if not _entry_exists(path):
        return
    retained = _retained_path(path, label)
    _replace(path, retained)
    _fsync_directory(path.parent)


def _crash_checkpoint(name: str) -> None:
    if os.environ.get("HD_EDIT_TIMELINE_HOLD_CHECKPOINT") == name:
        ready_value = os.environ.get("HD_EDIT_TIMELINE_HOLD_READY_FILE")
        if not ready_value:
            raise _fail()
        ready = Path(ready_value)
        if not ready.is_absolute():
            raise _fail()
        _write_exclusive(ready, b"ready\n")
        _fsync_directory(ready.parent)
        if os.environ.get("HD_EDIT_TIMELINE_HOLD_EXIT") == "1":
            os._exit(91)
        release_value = os.environ.get("HD_EDIT_TIMELINE_HOLD_RELEASE_FILE")
        if not release_value:
            raise _fail()
        release = Path(release_value)
        if not release.is_absolute():
            raise _fail()
        deadline = time.monotonic() + 60.0
        while not _entry_exists(release):
            if time.monotonic() >= deadline:
                raise _fail()
            time.sleep(0.01)
    if os.environ.get("HD_EDIT_TIMELINE_CRASH_CHECKPOINT") == name:
        os._exit({
            "workflow_restored": 92,
            "workflow_restored_marker_present": 93,
        }.get(name, 91))


def _rollback_generation(
    target: Path,
    stage: Path,
    backup: Path,
    old_tree: _TreeSnapshot | None,
    new_tree: _TreeSnapshot,
) -> None:
    if _tree_matches(target, new_tree):
        if _entry_exists(stage):
            _preserve_unknown_tree(stage, "unexpected-stage")
        _replace(target, stage)
        _fsync_directory(target.parent)
    elif _entry_exists(target) and not (
        old_tree is not None and _tree_matches(target, old_tree)
    ):
        _preserve_unknown_tree(target, "foreign-target")
    if old_tree is not None:
        if not _tree_matches(target, old_tree):
            if not _tree_matches(backup, old_tree) or _entry_exists(target):
                raise _fail()
            _replace(backup, target)
            _fsync_directory(target.parent)
        if not _tree_matches(target, old_tree):
            raise _fail()
    elif _entry_exists(target):
        raise _fail()
    if _tree_matches(stage, new_tree):
        try:
            _discard_directory(stage, set(new_tree.records))
        except EditTimelineError:
            pass
    elif _entry_exists(stage):
        _preserve_unknown_tree(stage, "foreign-stage")


def _swap_generation(
    job: JobState,
    target: Path,
    stage: Path,
    expected_names: set[str],
    ready: Callable[[list[Path]], None],
    *,
    old_expected_names: set[str] | None = None,
    expected_old_tree: _TreeSnapshot | None = None,
    request_binding: dict[str, Any] | None = None,
    stage_id: str,
    restore_ready: bool,
    is_committed: Callable[[], bool],
    prepare: Callable[[], None] | None = None,
) -> None:
    parent = target.parent
    if not _safe_generation_name(stage.name, target.name, "stage"):
        raise _fail()
    backup = parent / f".{target.name}.backup-{secrets.token_hex(16)}"
    new_tree = _snapshot_tree(stage, expected_names)
    old_names = old_expected_names or expected_names
    if expected_old_tree is not None:
        if set(expected_old_tree.records) != old_names:
            raise _fail()
        old_tree = expected_old_tree
    else:
        old_tree = (
            _snapshot_tree(target, old_names) if _entry_exists(target) else None
        )
    lock, marker_stage = _acquire_transaction_lock(
        job, target, stage, backup, stage_id, restore_ready, old_tree, new_tree,
        request_binding,
    )
    marker: _PinnedFile | None = None
    committed = False
    try:
        _crash_checkpoint("lock_durable")
        if not _tree_matches(stage, new_tree) or (
            old_tree is not None and not _tree_matches(target, old_tree)
        ) or (old_tree is None and _entry_exists(target)):
            try:
                _release_transaction_lock(lock)
            except EditTimelineError:
                _close_pin(lock)
            raise _fail()
        try:
            marker = _write_generation_marker(
                job, target, stage, backup, stage_id, restore_ready,
                lock, marker_stage, old_tree, new_tree, request_binding,
            )
        except BaseException:
            if not _entry_exists(_marker_path(parent, target.name)):
                try:
                    _release_transaction_lock(lock)
                except EditTimelineError:
                    _close_pin(lock)
            else:
                _close_pin(lock)
            raise
        _crash_checkpoint("marker_durable")
        _verify_pin(lock)
        _verify_pin(marker)
        try:
            if prepare is not None:
                prepare()
                _verify_pin(lock)
                _verify_pin(marker)
            if old_tree is not None:
                _verify_pin(lock)
                _replace(target, backup)
                _fsync_directory(parent)
                if not _tree_matches(backup, old_tree):
                    raise _fail()
            _crash_checkpoint("old_generation_moved")
            if not _tree_matches(stage, new_tree):
                raise _fail()
            _verify_pin(lock)
            _replace(stage, target)
            _fsync_directory(parent)
            if not _tree_matches(target, new_tree):
                raise _fail()
            _crash_checkpoint("new_generation_moved")
            _verify_pin(lock)
            ready([target / name for name in sorted(expected_names)])
            committed = True
            _crash_checkpoint("workflow_ready")
        except BaseException:
            if is_committed() and _tree_matches(target, new_tree):
                committed = True
            else:
                _rollback_generation(target, stage, backup, old_tree, new_tree)
                if marker is not None:
                    _finalize_transaction_metadata(marker, lock)
                    marker = None
                _sync_job(job, load_job(job.job_dir))
                raise
        if old_tree is not None and _tree_matches(backup, old_tree):
            try:
                _discard_directory(backup, set(old_tree.records))
            except EditTimelineError:
                pass
        if marker is not None:
            try:
                _finalize_transaction_metadata(marker, lock)
                marker = None
            except EditTimelineError:
                if committed:
                    _close_pin(marker)
                    _close_pin(lock)
                else:
                    raise
    finally:
        _close_pin(marker_stage)
        if marker is not None and not committed:
            _close_pin(marker)
        _close_pin(lock)


def _marker_tombstone_matches(
    parent: Path, target_name: str, marker_stage_record: dict[str, Any],
) -> bool:
    marker_stage: _PinnedFile | None = None
    try:
        marker_stage = _pin_path(
            parent / marker_stage_record["name"], expected_links=2,
        )
        if (
            (marker_stage.device, marker_stage.inode)
            != (marker_stage_record["device"], marker_stage_record["inode"])
            or marker_stage.sha256 != hashlib.sha256(b"").hexdigest()
            or marker_stage.size != 0
        ):
            return False
        prefix = f"..{target_name}.generation.marker.marker.retained-"
        retained = []
        for name in os.listdir(parent):
            if not name.startswith(prefix):
                continue
            token = name[len(prefix):]
            if len(token) != 32 or any(
                character not in "0123456789abcdef" for character in token
            ):
                continue
            try:
                entry = os.lstat(parent / name)
            except OSError:
                return False
            if (entry.st_dev, entry.st_ino) == (
                marker_stage.device, marker_stage.inode,
            ):
                retained.append(name)
        return len(retained) == 1
    except EditTimelineError:
        return False
    finally:
        if marker_stage is not None:
            _close_pin(marker_stage)


def _is_internal_proposal_revision(
    job: JobState,
    before: dict[str, Any],
    current_stage: dict[str, Any],
    restore_ready: bool,
    target_name: str,
    old_tree: _TreeSnapshot | None,
) -> bool:
    return (
        restore_ready
        and old_tree is not None
        and before["stage"]["status"] == "ready_for_review"
        and job.revision == before["revision"] + 1
        and current_stage["status"] == "needs_revision"
        and current_stage["reason"] == _INTERNAL_REVISION_REASON
        and current_stage["artifacts"] == []
        and current_stage["ai_attempts"] == 0
        and _lineage_binds_tree(current_stage["lineage"], target_name, old_tree)
    )


def _is_old_proposal_restoration(
    job: JobState,
    before: dict[str, Any],
    current_stage: dict[str, Any],
    restore_ready: bool,
    target_name: str,
    old_tree: _TreeSnapshot | None,
) -> bool:
    if (
        not restore_ready
        or old_tree is None
        or before["stage"]["status"] != "ready_for_review"
        or not _artifacts_bind_tree(
            before["stage"]["artifacts"], target_name, old_tree,
        )
    ):
        return False
    status = current_stage["status"]
    revision_delta = {"ready_for_review": 2, "approved": 3}.get(status)
    expected_artifacts = _tree_artifacts_payload(target_name, old_tree)
    return (
        revision_delta is not None
        and job.revision == before["revision"] + revision_delta
        and current_stage == {
            "status": status,
            "reason": None,
            "artifacts": expected_artifacts,
            "ai_attempts": 0,
            "lineage": [],
        }
    )


def _valid_orphan_lock_mode(payload: dict[str, Any], target_name: str) -> bool:
    operation = payload["operation"]
    restore_ready = payload["restore_ready"]
    if target_name == "03-edit-structure":
        return operation == "edit_structure" and not restore_ready
    if target_name != "02-speech-cleanup" or operation != "speech_cleanup":
        return False
    old_tree = payload["old_tree"]
    before_stage = payload["workflow_before"]["stage"]
    if restore_ready:
        return (
            old_tree is not None
            and before_stage["status"] == "ready_for_review"
            and _artifacts_bind_tree(
                before_stage["artifacts"], target_name, old_tree,
            )
        )
    return (
        old_tree is not None
        and before_stage["status"] == "needs_revision"
        and before_stage["artifacts"] == []
        and before_stage["ai_attempts"] == 0
        and _lineage_binds_tree(
            before_stage["lineage"], target_name, old_tree,
        )
    )


def _recover_orphan_lock(
    parent: Path,
    target_name: str,
    request_binding: dict[str, Any] | None = None,
) -> bool:
    path = parent / f".{target_name}.lock"
    if not _entry_exists(path):
        return False
    lock = _pin_path(path, expected_links=2)
    try:
        _lock_descriptor(lock)
        payload = _strict_lock_payload(lock, target_name)
        expected_binding = (
            _validated_request_binding(request_binding)
            if request_binding is not None else None
        )
        if payload["request_binding"] != expected_binding:
            raise _fail()
        if not _valid_orphan_lock_mode(payload, target_name):
            raise _fail()
        lock_stage_record = payload["lock_stage"]
        lock_stage = _pin_path(
            parent / lock_stage_record["name"],
            _file_record(lock),
            expected_links=2,
        )
        try:
            if (lock_stage.device, lock_stage.inode) != (lock.device, lock.inode):
                raise _fail()
        finally:
            _close_pin(lock_stage)
        marker_stage_record = payload["marker_stage"]
        try:
            marker_stage_links = os.lstat(
                parent / marker_stage_record["name"],
            ).st_nlink
        except OSError:
            raise _fail() from None
        if marker_stage_links not in {1, 2}:
            raise _fail()
        marker_stage = _pin_path(
            parent / marker_stage_record["name"],
            expected_links=marker_stage_links,
        )
        try:
            if (marker_stage.device, marker_stage.inode) != (
                marker_stage_record["device"], marker_stage_record["inode"],
            ):
                raise _fail()
        finally:
            _close_pin(marker_stage)
        old_tree = payload["old_tree"]
        new_tree = payload["new_tree"]
        target = parent / target_name
        stage = parent / payload["stage"]
        backup = parent / payload["backup"]
        current = load_job(parent)
        current_stage = current.stages[payload["operation"]]
        before = payload["workflow_before"]
        before_matches = (
            current.revision == before["revision"]
            and current_stage == before["stage"]
        )
        revised_proposal = _is_internal_proposal_revision(
            current, before, current_stage, payload["restore_ready"],
            target_name, old_tree,
        )
        restored_proposal = _is_old_proposal_restoration(
            current,
            before,
            current_stage,
            payload["restore_ready"],
            target_name,
            old_tree,
        )
        target_is_new = _tree_matches(target, new_tree)
        committed = (
            current_stage["status"] in {"ready_for_review", "approved"}
            and target_is_new
            and current_stage["artifacts"] == payload["committed_artifacts"]
            and _artifacts_bind_tree(current_stage["artifacts"], target_name, new_tree)
        )
        if committed:
            if not _marker_tombstone_matches(
                parent, target_name, payload["marker_stage"],
            ):
                raise _fail()
            if old_tree is not None and _tree_matches(backup, old_tree):
                try:
                    _discard_directory(backup, set(old_tree.records))
                except EditTimelineError:
                    pass
        elif restored_proposal:
            if (
                old_tree is None
                or not _tree_matches(target, old_tree)
                or not _marker_tombstone_matches(
                    parent, target_name, payload["marker_stage"],
                )
            ):
                raise _fail()
            _rollback_generation(target, stage, backup, old_tree, new_tree)
        elif before_matches and (
            (old_tree is None and not _entry_exists(target))
            or (old_tree is not None and _tree_matches(target, old_tree))
        ):
            if _tree_matches(stage, new_tree):
                try:
                    _discard_directory(stage, set(new_tree.records))
                except EditTimelineError:
                    pass
        elif revised_proposal:
            if (
                old_tree is None
                or not _tree_matches(target, old_tree)
                or not _artifacts_bind_tree(
                    before["stage"]["artifacts"], target_name, old_tree,
                )
                or not _marker_tombstone_matches(
                    parent, target_name, payload["marker_stage"],
                )
            ):
                raise _fail()
            _rollback_generation(target, stage, backup, old_tree, new_tree)
            mark_ready(
                current,
                payload["operation"],
                [target / name for name in sorted(old_tree.records)],
            )
            _crash_checkpoint("workflow_restored")
        elif (
            current_stage["status"] == "needs_revision"
            and current_stage["artifacts"] == []
        ):
            if payload["restore_ready"]:
                raise _fail()
            _rollback_generation(target, stage, backup, old_tree, new_tree)
        else:
            raise _fail()
        _release_transaction_lock(lock)
        return committed
    except BaseException:
        _close_pin(lock)
        raise _fail() from None


def _artifacts_bind_tree(
    artifacts: Any, target_name: str, tree: _TreeSnapshot,
) -> bool:
    if type(artifacts) is not list or len(artifacts) != len(tree.records):
        return False
    seen: set[str] = set()
    for record in artifacts:
        if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
            return False
        path = record["path"]
        if type(path) is not str:
            return False
        relative = Path(path)
        name = relative.name
        if (
            name in seen
            or name not in tree.records
            or path != f"{target_name}/{name}"
            or type(record["sha256"]) is not str
            or record["sha256"] != tree.records[name][2]
            or type(record["bytes"]) is not int
            or record["bytes"] != tree.records[name][3]
        ):
            return False
        seen.add(name)
    return seen == set(tree.records)


def _lineage_binds_tree(
    lineage: Any, target_name: str, tree: _TreeSnapshot,
) -> bool:
    if type(lineage) is not list or len(lineage) != len(tree.records):
        return False
    expected = {
        record["path"]: record
        for record in _tree_lineage_payload(target_name, tree)
    }
    return all(
        type(record) is dict
        and set(record) == {
            "path", "sha256", "bytes", "device", "inode",
            "parent_device", "parent_inode",
        }
        and record.get("path") in expected
        and record == expected[record["path"]]
        for record in lineage
    ) and len({record["path"] for record in lineage}) == len(expected)


def _recover_generation(
    job: JobState,
    target_name: str,
    stage_id: str,
    new_names: set[str],
    *,
    restore_ready: bool,
    allowed_old_names: tuple[set[str], ...],
    request_binding: dict[str, Any] | None = None,
) -> bool:
    parent = job.job_dir
    marker_path = _marker_path(parent, target_name)
    if not _entry_exists(marker_path):
        had_orphan_lock = _entry_exists(parent / f".{target_name}.lock")
        committed = _recover_orphan_lock(
            parent, target_name, request_binding=request_binding,
        )
        if had_orphan_lock:
            _sync_job(job, load_job(parent))
        return committed
    payload, marker, lock = _read_generation_marker(
        parent, target_name, stage_id, restore_ready, request_binding,
    )
    finalized = False
    try:
        _sync_job(job, load_job(parent))
        old_tree = payload["old_tree"]
        new_tree = payload["new_tree"]
        if set(new_tree.records) != new_names:
            raise _fail()
        if old_tree is not None and not any(
            set(old_tree.records) == allowed for allowed in allowed_old_names
        ):
            raise _fail()
        target = parent / target_name
        stage = parent / payload["stage"]
        backup = parent / payload["backup"]
        before = payload["workflow_before"]
        current_stage = job.stages[stage_id]
        status = current_stage["status"]
        before_matches = (
            job.revision == before["revision"]
            and current_stage == before["stage"]
        )
        target_is_new = _tree_matches(target, new_tree)
        committed_status = status in {"ready_for_review", "approved"}
        committed = (
            committed_status
            and target_is_new
            and _artifacts_bind_tree(
                current_stage["artifacts"], target_name, new_tree,
            )
        )
        lineage_shape = (
            status in {"pending", "needs_revision"}
            and current_stage["artifacts"] == []
        )
        lineage_is_new = lineage_shape and _lineage_binds_tree(
            current_stage["lineage"], target_name, new_tree,
        )
        lineage_is_old = (
            lineage_shape
            and old_tree is not None
            and _lineage_binds_tree(
                current_stage["lineage"], target_name, old_tree,
            )
        )
        cold_start_old_side = (
            old_tree is None
            and target_is_new
            and not restore_ready
            and lineage_shape
            and current_stage["lineage"] == []
            and job.revision > before["revision"]
        )
        if committed or lineage_is_new:
            if not target_is_new:
                raise _fail()
            for candidate, snapshot in ((backup, old_tree), (stage, new_tree)):
                if snapshot is not None and _tree_matches(candidate, snapshot):
                    try:
                        _discard_directory(candidate, set(snapshot.records))
                    except EditTimelineError:
                        pass
            try:
                _finalize_transaction_metadata(marker, lock)
                finalized = True
            except EditTimelineError:
                pass
            return committed
        restored_proposal = _is_old_proposal_restoration(
            job, before, current_stage, restore_ready, target_name, old_tree,
        )
        if restored_proposal:
            if old_tree is None or not _tree_matches(target, old_tree):
                raise _fail()
            _finalize_transaction_metadata(marker, lock)
            finalized = True
            return False
        if committed_status and not before_matches:
            raise _fail()
        revised_proposal = _is_internal_proposal_revision(
            job, before, current_stage, restore_ready, target_name, old_tree,
        )
        if (
            not before_matches
            and not revised_proposal
            and not lineage_is_old
            and not cold_start_old_side
        ):
            raise _fail()
        _rollback_generation(target, stage, backup, old_tree, new_tree)
        if restore_ready:
            if old_tree is None:
                raise _fail()
            if revised_proposal:
                mark_ready(
                    job,
                    stage_id,
                    [target / name for name in sorted(old_tree.records)],
                )
                _crash_checkpoint("workflow_restored_marker_present")
        _finalize_transaction_metadata(marker, lock)
        finalized = True
        return False
    finally:
        if not finalized:
            _close_pin(marker)
            _close_pin(lock)


def _sync_job(target: JobState, source: JobState) -> None:
    target.root = source.root
    target.job_dir = source.job_dir
    target.job_id = source.job_id
    target.inputs = source.inputs
    target.revision = source.revision
    target.expected_revision = source.expected_revision
    target.expected_sha256 = source.expected_sha256
    target.expected_bytes = source.expected_bytes
    target.stages.clear()
    target.stages.update(source.stages)


def _validate_words(words: Any) -> list[dict[str, Any]]:
    if type(words) is not list or not words:
        raise EditTimelineError("invalid edit plan")
    previous_end = 0.0
    for word in words:
        if type(word) is not dict or set(word) != {"text", "start", "end"}:
            raise EditTimelineError("invalid edit plan")
        if type(word["text"]) is not str or not word["text"]:
            raise EditTimelineError("invalid edit plan")
        start = _finite_number(word["start"])
        end = _finite_number(word["end"])
        if start < previous_end or end <= start:
            raise EditTimelineError("invalid edit plan")
        previous_end = end
    return words


def _segment_sentence(
    words: list[dict[str, Any]], word_start: int, word_end: int,
) -> str:
    return "".join(str(words[index]["text"]) for index in range(word_start, word_end))


def validate_edit_plan(plan: Any, words: Any) -> dict[str, Any]:
    """Strictly validate decisions that form one continuous word partition."""
    checked_words = _validate_words(words)
    if type(plan) is not dict or type(plan.get("version")) is not int:
        raise EditTimelineError("invalid edit plan")
    if plan["version"] == 1 and set(plan) == {"version", "segments"}:
        reviewed_cut_ranges: list[dict[str, Any]] = []
    elif plan["version"] == 2 and set(plan) == {
        "version", "segments", "reviewed_cut_ranges",
    }:
        reviewed_cut_ranges = plan["reviewed_cut_ranges"]
        if type(reviewed_cut_ranges) is not list or not reviewed_cut_ranges:
            raise EditTimelineError("invalid edit plan")
        previous_end = 0.0
        for cut in reviewed_cut_ranges:
            if type(cut) is not dict or set(cut) != {
                "source_start", "source_end", "reason", "evidence",
            }:
                raise EditTimelineError("invalid edit plan")
            start = _finite_number(cut["source_start"])
            end = _finite_number(cut["source_end"])
            if start < previous_end or end <= start:
                raise EditTimelineError("invalid edit plan")
            if any(
                type(cut[key]) is not str or not cut[key].strip()
                for key in ("reason", "evidence")
            ):
                raise EditTimelineError("invalid edit plan")
            previous_end = end
    else:
        raise EditTimelineError("invalid edit plan")
    segments = plan["segments"]
    if type(segments) is not list or not segments:
        raise EditTimelineError("invalid edit plan")
    expected_word = 0
    for segment in segments:
        if type(segment) is not dict or set(segment) != _SEGMENT_KEYS:
            raise EditTimelineError("invalid edit plan")
        action = segment["action"]
        word_start = segment["word_start"]
        word_end = segment["word_end"]
        if action not in {"keep", "delete"}:
            raise EditTimelineError("invalid edit plan")
        if type(word_start) is not int or type(word_end) is not int:
            raise EditTimelineError("invalid edit plan")
        if word_start != expected_word or word_end <= word_start or word_end > len(checked_words):
            raise EditTimelineError("invalid edit plan")
        if _finite_number(segment["source_start"]) != float(checked_words[word_start]["start"]):
            raise EditTimelineError("invalid edit plan")
        if _finite_number(segment["source_end"]) != float(checked_words[word_end - 1]["end"]):
            raise EditTimelineError("invalid edit plan")
        for key in ("original_sentence", "cleaned_sentence", "reason"):
            if type(segment[key]) is not str:
                raise EditTimelineError("invalid edit plan")
        if not segment["original_sentence"] or not segment["reason"]:
            raise EditTimelineError("invalid edit plan")
        original = _segment_sentence(checked_words, word_start, word_end)
        if segment["original_sentence"] != original:
            raise EditTimelineError("invalid edit plan")
        if (
            action == "delete" and segment["cleaned_sentence"]
        ) or (
            action == "keep" and segment["cleaned_sentence"] != original
        ):
            raise EditTimelineError("invalid edit plan")
        padding = segment["breathing_padding"]
        if type(padding) is not dict or set(padding) != {"before", "after"}:
            raise EditTimelineError("invalid edit plan")
        before = _finite_number(padding["before"])
        after = _finite_number(padding["after"])
        if before < 0 or after < 0:
            raise EditTimelineError("invalid edit plan")
        expected_word = word_end
    if expected_word != len(checked_words):
        raise EditTimelineError("invalid edit plan")
    return plan


def parse_edit_plan_json(source: str, words: Any) -> dict[str, Any]:
    """Parse an edit plan with duplicate-key and non-finite rejection."""
    if type(source) is not str:
        raise EditTimelineError("invalid edit plan")
    try:
        plan = json.loads(
            source,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, TypeError, ValueError, EditTimelineError):
        raise EditTimelineError("invalid edit plan") from None
    return validate_edit_plan(plan, words)


def _validate_transcript_correction_manifest(manifest: Any) -> dict[str, Any]:
    if type(manifest) is not dict or set(manifest) != {
        "version", "source", "corrections",
    }:
        raise _fail()
    if type(manifest["version"]) is not int or manifest["version"] != 1:
        raise _fail()
    source = manifest["source"]
    if type(source) is not dict or set(source) != {"path", "sha256", "bytes"}:
        raise _fail()
    if source["path"] not in {
        "02-speech-cleanup/word-transcript.json",
        "05-speech-cleanup/word-transcript.json",
    }:
        raise _fail()
    digest = source["sha256"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or type(source["bytes"]) is not int
        or source["bytes"] < 0
    ):
        raise _fail()
    corrections = manifest["corrections"]
    if type(corrections) is not list or not corrections:
        raise _fail()
    previous_end = 0
    for correction in corrections:
        if type(correction) is not dict or set(correction) != {
            "word_start", "word_end", "expected_words", "replacement_texts", "reason",
        }:
            raise _fail()
        word_start = correction["word_start"]
        word_end = correction["word_end"]
        if (
            type(word_start) is not int
            or type(word_end) is not int
            or word_start < previous_end
            or word_end <= word_start
        ):
            raise _fail()
        expected_words = correction["expected_words"]
        replacement_texts = correction["replacement_texts"]
        count = word_end - word_start
        if (
            type(expected_words) is not list
            or type(replacement_texts) is not list
            or len(expected_words) != count
            or len(replacement_texts) != count
        ):
            raise _fail()
        expected_previous_end = 0.0
        for expected in expected_words:
            if type(expected) is not dict or set(expected) != {"text", "start", "end"}:
                raise _fail()
            if (
                type(expected["text"]) is not str
                or not expected["text"].strip()
            ):
                raise _fail()
            start = _finite_number(expected["start"])
            end = _finite_number(expected["end"])
            if start < expected_previous_end or end <= start:
                raise _fail()
            expected_previous_end = end
        if any(
            type(text) is not str or not text.strip()
            for text in replacement_texts
        ):
            raise _fail()
        if type(correction["reason"]) is not str or not correction["reason"].strip():
            raise _fail()
        previous_end = word_end
    return manifest


def parse_transcript_corrections_json(text: str) -> dict[str, Any]:
    """Parse an exact, position-bound v1 transcript correction manifest."""
    if type(text) is not str:
        raise _fail()
    try:
        manifest = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, TypeError, ValueError, EditTimelineError):
        raise _fail() from None
    return _validate_transcript_correction_manifest(manifest)


def apply_transcript_corrections(
    words: Any, manifest: Any,
) -> list[dict[str, Any]]:
    """Replace text only after exact old text/timestamp matching."""
    checked_words = _validate_words(words)
    checked_manifest = _validate_transcript_correction_manifest(manifest)
    corrected = copy.deepcopy(checked_words)
    for correction in checked_manifest["corrections"]:
        word_start = correction["word_start"]
        word_end = correction["word_end"]
        if word_end > len(corrected):
            raise _fail()
        for offset, expected in enumerate(correction["expected_words"]):
            actual = checked_words[word_start + offset]
            if (
                actual["text"] != expected["text"]
                or actual["start"] != expected["start"]
                or actual["end"] != expected["end"]
            ):
                raise _fail()
        for offset, replacement in enumerate(correction["replacement_texts"]):
            corrected[word_start + offset]["text"] = replacement
    return corrected


def _timeline_intervals(
    plan: dict[str, Any],
    media_duration: float,
) -> list[tuple[float, float]]:
    duration = _finite_number(media_duration)
    if duration <= 0:
        raise EditTimelineError("invalid cleanup source")
    reviewed_cut_ranges = plan.get("reviewed_cut_ranges", [])
    if not any(segment["action"] == "delete" for segment in plan["segments"]) and not reviewed_cut_ranges:
        return [(0.0, duration)]
    intervals: list[tuple[float, float]] = []
    for index, segment in enumerate(plan["segments"]):
        if segment["action"] != "keep":
            continue
        padding = segment["breathing_padding"]
        start = max(0.0, float(segment["source_start"]) - float(padding["before"]))
        end = min(
            duration,
            float(segment["source_end"]) + float(padding["after"]),
        )
        if index == 0:
            start = 0.0
        if index == len(plan["segments"]) - 1:
            end = duration
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    cuts = [
        (float(segment["source_start"]), float(segment["source_end"]))
        for segment in plan["segments"]
        if segment["action"] == "delete"
    ] + [
        (float(cut["source_start"]), float(cut["source_end"]))
        for cut in reviewed_cut_ranges
    ]
    for delete_start, delete_end in cuts:
        if delete_start < 0 or delete_end > duration:
            raise EditTimelineError("invalid cleanup source")
        remaining: list[tuple[float, float]] = []
        for start, end in intervals:
            if delete_end <= start or delete_start >= end:
                remaining.append((start, end))
                continue
            if start < delete_start:
                remaining.append((start, delete_start))
            if delete_end < end:
                remaining.append((delete_end, end))
        intervals = remaining
    if not intervals or any(end <= start for start, end in intervals):
        raise EditTimelineError("invalid cleanup source")
    return intervals


def build_cleanup_proposal(
    script: str,
    words: Any,
    plan: Any,
    *,
    media_duration: float,
) -> dict[str, Any]:
    """Freeze the four human-review outputs of the cleanup stage."""
    if type(script) is not str or not script.strip():
        raise EditTimelineError("invalid cleanup source")
    checked_words = _validate_words(words)
    checked_plan = validate_edit_plan(plan, checked_words)
    deleted = [
        checked_words[index]["text"]
        for segment in checked_plan["segments"]
        if segment["action"] == "delete"
        for index in range(segment["word_start"], segment["word_end"])
    ]
    intervals = _timeline_intervals(checked_plan, media_duration)
    if any(float(word["end"]) > float(media_duration) for word in checked_words):
        raise EditTimelineError("word transcript exceeds cleanup media duration")
    return {
        "version": 1,
        "word_transcript": {"version": 1, "words": checked_words},
        "diff_summary": {
            "version": 1,
            "original_script": script,
            "cleaned_script": "".join(
                segment["cleaned_sentence"]
                for segment in checked_plan["segments"]
                if segment["action"] == "keep"
            ),
            "deleted_words": deleted,
            "deleted_word_count": len(deleted),
            "risk_assessment": assess_cleanup_risk(
                checked_words, checked_plan, media_duration=media_duration,
            ),
            **(
                {"reviewed_cut_ranges": copy.deepcopy(
                    checked_plan["reviewed_cut_ranges"]
                )}
                if checked_plan["version"] == 2 else {}
            ),
        },
        "cleanup_proposal": checked_plan,
        "estimated_duration": {
            "version": 1,
            "seconds": sum(end - start for start, end in intervals),
            "source_seconds": float(media_duration),
        },
    }


_TASK2_NAMES = {"speech-16k.wav", "whisper.json", "report.json"}
_PROPOSAL_NAMES = _TASK2_NAMES | {
    "word-transcript.json",
    "diff-summary.json",
    "cleanup-proposal.json",
    "estimated-duration.json",
}
_V2_TASK2_NAMES = {"speech-16k.wav", "scribe.json", "report.json"}
_V2_PROPOSAL_NAMES = (_PROPOSAL_NAMES - {"whisper.json"}) | {"scribe.json"}
_INTERNAL_REVISION_REASON = "生成完整口播整理提案"
_INTERNAL_ROLLBACK_REASON = "恢复上一代口播整理提案"


def _task2_artifact_pins(job: JobState) -> dict[str, _PinnedFile]:
    stage = job.stages.get("speech_cleanup")
    if type(stage) is not dict or stage.get("status") != "ready_for_review":
        raise _fail()
    artifacts = stage.get("artifacts")
    if type(artifacts) is not list or len(artifacts) not in {
        len(_TASK2_NAMES), len(_PROPOSAL_NAMES),
    }:
        raise _fail()
    expected_names = _TASK2_NAMES if len(artifacts) == len(_TASK2_NAMES) else _PROPOSAL_NAMES
    result: dict[str, _PinnedFile] = {}
    try:
        for record in artifacts:
            pin = _pin_record(job.job_dir, record)
            if pin.path.parent != job.job_dir / "02-speech-cleanup":
                os.close(pin.descriptor)
                raise _fail()
            if pin.path.name not in expected_names or pin.path.name in result:
                os.close(pin.descriptor)
                raise _fail()
            result[pin.path.name] = pin
        if set(result) != expected_names:
            raise _fail()
        return result
    except BaseException:
        for pin in result.values():
            try:
                os.close(pin.descriptor)
            except OSError:
                pass
        raise


def _transcript_words(report: _PinnedFile) -> list[dict[str, Any]]:
    payload = _strict_json_bytes(_descriptor_bytes(report.descriptor, 16 * 1024 * 1024))
    if type(payload) is not dict or set(payload) != {
        "version", "runtime", "script", "transcript"
    }:
        raise _fail()
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise _fail()
    transcript = payload["transcript"]
    if type(transcript) is not dict or set(transcript) != {
        "word_count", "first", "last", "words"
    }:
        raise _fail()
    words = _validate_words(transcript["words"])
    if type(transcript["word_count"]) is not int or transcript["word_count"] != len(words):
        raise _fail()
    if (
        _finite_number(transcript["first"]) != float(words[0]["start"])
        or _finite_number(transcript["last"]) != float(words[-1]["end"])
    ):
        raise _fail()
    return words


def _script_text(job: JobState) -> tuple[_PinnedFile, str]:
    pin = _pin_record(job.root, job.inputs.get("script"))
    try:
        source = _descriptor_bytes(pin.descriptor, 16 * 1024 * 1024)
        text = source.decode("utf-8", errors="strict")
        if not text.strip():
            raise _fail()
        return pin, text
    except BaseException:
        try:
            os.close(pin.descriptor)
        except OSError:
            pass
        raise


def _restore_proposal_state(job: JobState, old_paths: list[Path]) -> None:
    persisted = load_job(job.job_dir)
    status = persisted.stages["speech_cleanup"]["status"]
    if status == "ready_for_review":
        revise(persisted, "speech_cleanup", _INTERNAL_ROLLBACK_REASON)
    elif status != "needs_revision":
        raise _fail()
    mark_ready(persisted, "speech_cleanup", old_paths)
    _sync_job(job, persisted)


def generate_cleanup_proposal(job: JobState, plan: Any) -> Path:
    """Extend the bound Task-2 generation, then stop again for human review."""
    if job.version == 2:
        from . import speech_edit_v2

        return speech_edit_v2.prepare_cleanup_proposal(job, plan)
    if _recover_generation(
        job,
        "02-speech-cleanup",
        "speech_cleanup",
        _PROPOSAL_NAMES,
        restore_ready=True,
        allowed_old_names=(_TASK2_NAMES, _PROPOSAL_NAMES),
    ):
        return job.job_dir / "02-speech-cleanup" / "cleanup-proposal.json"
    pins: dict[str, _PinnedFile] = {}
    inspect_pins: dict[str, _PinnedFile] = {}
    script_pin: _PinnedFile | None = None
    stage: Path | None = None
    revised = False
    revision_before_swap = job.revision
    old_names = set(_TASK2_NAMES)
    try:
        pins = _task2_artifact_pins(job)
        old_names = set(pins)
        inspect_pins = _stage_artifact_pins(
            job, "inspect", "01-inspect", {"report.json"},
        )
        script_pin, script = _script_text(job)
        words = _transcript_words(pins["report.json"])
        profile = _inspect_profile(inspect_pins["report.json"], job.inputs["video"])
        proposal = build_cleanup_proposal(
            script,
            words,
            plan,
            media_duration=profile["duration"],
        )
        stage = _make_stage(job.job_dir, "02-speech-cleanup")
        for name in sorted(_TASK2_NAMES):
            _write_exclusive(stage / name, _descriptor_bytes(pins[name].descriptor, 2**31))
        output_payloads = {
            "word-transcript.json": proposal["word_transcript"],
            "diff-summary.json": proposal["diff_summary"],
            "cleanup-proposal.json": proposal["cleanup_proposal"],
            "estimated-duration.json": proposal["estimated_duration"],
        }
        for name, payload in output_payloads.items():
            _write_exclusive(stage / name, _json_bytes(payload))
        _fsync_directory(stage)
        for pin in (*pins.values(), *inspect_pins.values(), script_pin):
            _verify_pin(pin)

        def prepare_revision() -> None:
            nonlocal revised
            try:
                revise(job, "speech_cleanup", _INTERNAL_REVISION_REASON)
            finally:
                revised = (
                    job.stages["speech_cleanup"]["status"] == "needs_revision"
                )

        _swap_generation(
            job,
            job.job_dir / "02-speech-cleanup",
            stage,
            _PROPOSAL_NAMES,
            lambda artifacts: mark_ready(job, "speech_cleanup", artifacts),
            old_expected_names=old_names,
            stage_id="speech_cleanup",
            restore_ready=True,
            is_committed=lambda: (
                job.stages["speech_cleanup"]["status"] == "ready_for_review"
            ),
            prepare=prepare_revision,
        )
        stage = None
        return job.job_dir / "02-speech-cleanup" / "cleanup-proposal.json"
    except BaseException as failure:
        if revised:
            try:
                persisted = load_job(job.job_dir)
                old_tree = _snapshot_tree(
                    job.job_dir / "02-speech-cleanup", old_names,
                )
                internal_revision = (
                    persisted.revision == revision_before_swap + 1
                    and persisted.stages["speech_cleanup"]["status"]
                    == "needs_revision"
                    and persisted.stages["speech_cleanup"]["reason"]
                    == _INTERNAL_REVISION_REASON
                    and persisted.stages["speech_cleanup"]["artifacts"] == []
                    and persisted.stages["speech_cleanup"]["ai_attempts"] == 0
                    and _lineage_binds_tree(
                        persisted.stages["speech_cleanup"]["lineage"],
                        "02-speech-cleanup", old_tree,
                    )
                )
                if internal_revision:
                    _restore_proposal_state(
                        job,
                        [
                            job.job_dir / "02-speech-cleanup" / name
                            for name in sorted(old_names)
                        ],
                    )
                else:
                    _sync_job(job, persisted)
            except BaseException:
                raise _fail() from None
        if isinstance(failure, EditTimelineError):
            raise failure from None
        raise _fail() from None
    finally:
        for pin in pins.values():
            try:
                os.close(pin.descriptor)
            except OSError:
                pass
        for pin in inspect_pins.values():
            try:
                os.close(pin.descriptor)
            except OSError:
                pass
        if script_pin is not None:
            try:
                os.close(script_pin.descriptor)
            except OSError:
                pass
        if stage is not None:
            try:
                _discard_directory(stage, _PROPOSAL_NAMES)
            except EditTimelineError:
                pass


def _cleanup_lineage_pins(
    job: JobState,
    *,
    generation_name: str = "02-speech-cleanup",
) -> dict[str, _PinnedFile]:
    stage = job.stages.get("speech_cleanup")
    if (
        type(stage) is not dict
        or stage.get("status") != "needs_revision"
        or stage.get("artifacts") != []
    ):
        raise _fail()
    lineage = stage.get("lineage")
    proposal_names = _V2_PROPOSAL_NAMES if job.version == 2 else _PROPOSAL_NAMES
    allowed_name_sets = (
        (proposal_names, {*proposal_names, "material-usage.json"})
        if job.version == 2
        else (proposal_names,)
    )
    allowed_names = set().union(*allowed_name_sets)
    allowed_lengths = {len(names) for names in allowed_name_sets}
    if type(lineage) is not list or len(lineage) not in allowed_lengths:
        raise _fail()
    result: dict[str, _PinnedFile] = {}
    try:
        for record in lineage:
            if type(record) is not dict or set(record) != {
                "path", "sha256", "bytes", "device", "inode",
                "parent_device", "parent_inode",
            }:
                raise _fail()
            artifact = {key: record[key] for key in ("path", "sha256", "bytes")}
            pin = _pin_record(job.job_dir, artifact)
            if pin.path.parent != job.job_dir / generation_name:
                _close_pin(pin)
                raise _fail()
            name = pin.path.name
            if name not in allowed_names or name in result:
                _close_pin(pin)
                raise _fail()
            try:
                parent = os.lstat(pin.path.parent)
            except OSError:
                _close_pin(pin)
                raise _fail() from None
            if (
                (pin.device, pin.inode) != (record["device"], record["inode"])
                or not stat.S_ISDIR(parent.st_mode)
                or (parent.st_dev, parent.st_ino)
                != (record["parent_device"], record["parent_inode"])
            ):
                _close_pin(pin)
                raise _fail()
            result[name] = pin
        result_names = set(result)
        if not any(result_names == names for names in allowed_name_sets):
            raise _fail()
        if "material-usage.json" in result:
            from . import material_usage

            receipt = _strict_json_bytes(_descriptor_bytes(
                result["material-usage.json"].descriptor, 16 * 1024 * 1024
            ))
            material_usage.validate_receipt(
                job, "speech_cleanup", receipt,
                published_artifacts=[result[name].path for name in sorted(proposal_names)],
            )
        elif job.version == 2:
            summary = _strict_json_bytes(_descriptor_bytes(
                result["diff-summary.json"].descriptor, 16 * 1024 * 1024
            ))
            # Only pre-receipt generations may use the controlled upgrade path.
            # A current generation already carries a bound terminology report,
            # so removing only its material receipt must fail closed.
            if "terminology_review" in summary:
                raise _fail()
        return result
    except BaseException:
        for pin in result.values():
            _close_pin(pin)
        raise


def _cleanup_lineage_tree(
    pins: dict[str, _PinnedFile],
    lineage_by_name: dict[str, dict[str, Any]],
    *,
    proposal_names: set[str] = _PROPOSAL_NAMES,
    include_material_receipt: bool = False,
) -> _TreeSnapshot:
    expected_names = proposal_names | ({"material-usage.json"} if include_material_receipt else set())
    if set(pins) != expected_names or set(lineage_by_name) != expected_names:
        raise _fail()
    parent_identities = {
        (record["parent_device"], record["parent_inode"])
        for record in lineage_by_name.values()
    }
    if len(parent_identities) != 1:
        raise _fail()
    records: dict[str, tuple[int, int, str, int]] = {}
    for name in sorted(expected_names):
        pin = pins[name]
        lineage_record = lineage_by_name[name]
        expected = (
            lineage_record["device"],
            lineage_record["inode"],
            lineage_record["sha256"],
            lineage_record["bytes"],
        )
        actual = (pin.device, pin.inode, pin.sha256, pin.size)
        if actual != expected:
            raise _fail()
        records[name] = expected
    parent_device, parent_inode = next(iter(parent_identities))
    return _TreeSnapshot(parent_device, parent_inode, records)


def _verify_cleanup_lineage_pin(pin: _PinnedFile, record: dict[str, Any]) -> None:
    _verify_pin(pin)
    try:
        parent = os.lstat(pin.path.parent)
    except OSError:
        raise _fail() from None
    if (
        (pin.device, pin.inode) != (record["device"], record["inode"])
        or not stat.S_ISDIR(parent.st_mode)
        or (parent.st_dev, parent.st_ino)
        != (record["parent_device"], record["parent_inode"])
    ):
        raise _fail()


def _rebase_cleanup_plan_text(
    plan: dict[str, Any], words: list[dict[str, Any]],
) -> dict[str, Any]:
    rebased = copy.deepcopy(plan)
    for segment in rebased["segments"]:
        sentence = _segment_sentence(
            words, segment["word_start"], segment["word_end"],
        )
        segment["original_sentence"] = sentence
        if segment["action"] == "keep":
            segment["cleaned_sentence"] = sentence
    return rebased


def _correction_audit_run(
    manifest: dict[str, Any], manifest_pin: _PinnedFile,
) -> dict[str, Any]:
    return {
        "source": copy.deepcopy(manifest["source"]),
        "manifest": {
            "path": manifest_pin.path.name,
            "sha256": manifest_pin.sha256,
            "bytes": manifest_pin.size,
        },
        "changes": [
            {
                "word_start": correction["word_start"],
                "word_end": correction["word_end"],
                "before": [word["text"] for word in correction["expected_words"]],
                "after": list(correction["replacement_texts"]),
                "reason": correction["reason"],
            }
            for correction in manifest["corrections"]
        ],
    }


def _correction_audit_runs(summary: Any) -> list[dict[str, Any]]:
    base_keys = {
        "version", "original_script", "cleaned_script",
        "deleted_words", "deleted_word_count",
    }
    optional_keys = {"transcript_corrections", "risk_assessment", "reviewed_cut_ranges"}
    if (
        type(summary) is not dict
        or not base_keys.issubset(summary)
        or not set(summary).issubset(base_keys | optional_keys)
    ):
        raise _fail()
    deleted = summary["deleted_words"]
    if (
        type(summary["version"]) is not int
        or summary["version"] != 1
        or type(summary["original_script"]) is not str
        or not summary["original_script"].strip()
        or type(summary["cleaned_script"]) is not str
        or type(deleted) is not list
        or any(type(word) is not str or not word for word in deleted)
        or type(summary["deleted_word_count"]) is not int
        or summary["deleted_word_count"] != len(deleted)
    ):
        raise _fail()
    if "transcript_corrections" not in summary:
        return []
    audit = summary["transcript_corrections"]
    if (
        type(audit) is not dict
        or set(audit) != {"version", "runs"}
        or type(audit["version"]) is not int
        or audit["version"] != 1
        or type(audit["runs"]) is not list
        or not audit["runs"]
    ):
        raise _fail()
    for run in audit["runs"]:
        if type(run) is not dict or set(run) != {"source", "manifest", "changes"}:
            raise _fail()
        source = run["source"]
        manifest = run["manifest"]
        if (
            type(source) is not dict
            or set(source) != {"path", "sha256", "bytes"}
            or source["path"] not in {
                "02-speech-cleanup/word-transcript.json",
                "05-speech-cleanup/word-transcript.json",
            }
            or type(manifest) is not dict
            or set(manifest) != {"path", "sha256", "bytes"}
            or type(manifest["path"]) is not str
            or not manifest["path"]
            or Path(manifest["path"]).name != manifest["path"]
        ):
            raise _fail()
        for binding in (source, manifest):
            digest = binding["sha256"]
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or type(binding["bytes"]) is not int
                or binding["bytes"] < 0
            ):
                raise _fail()
        changes = run["changes"]
        if type(changes) is not list or not changes:
            raise _fail()
        for change in changes:
            if type(change) is not dict or set(change) != {
                "word_start", "word_end", "before", "after", "reason",
            }:
                raise _fail()
            word_start = change["word_start"]
            word_end = change["word_end"]
            before = change["before"]
            after = change["after"]
            if (
                type(word_start) is not int
                or type(word_end) is not int
                or word_end <= word_start
                or type(before) is not list
                or type(after) is not list
                or len(before) != word_end - word_start
                or len(after) != word_end - word_start
                or any(type(text) is not str or not text for text in (*before, *after))
                or type(change["reason"]) is not str
                or not change["reason"].strip()
            ):
                raise _fail()
    return copy.deepcopy(audit["runs"])


def generate_corrected_cleanup_proposal(
    job: JobState, corrections: Path,
) -> Path:
    """Publish one corrected seven-artifact speech-cleanup generation."""
    generation_name = (
        "05-speech-cleanup" if job.version == 2 else "02-speech-cleanup"
    )
    task2_names = _V2_TASK2_NAMES if job.version == 2 else _TASK2_NAMES
    proposal_names = _V2_PROPOSAL_NAMES if job.version == 2 else _PROPOSAL_NAMES
    target = job.job_dir / generation_name
    pins: dict[str, _PinnedFile] = {}
    manifest_pin: _PinnedFile | None = None
    stage: Path | None = None
    try:
        corrections_path = Path(corrections)
        if not corrections_path.is_absolute():
            corrections_path = Path.cwd() / corrections_path
        manifest_pin = _pin_read_only_path(corrections_path)
        request_binding = {
            "sha256": manifest_pin.sha256,
            "bytes": manifest_pin.size,
        }
        if job.version != 2 and _recover_generation(
            job,
            generation_name,
            "speech_cleanup",
            _PROPOSAL_NAMES,
            restore_ready=False,
            allowed_old_names=(_PROPOSAL_NAMES,),
            request_binding=request_binding,
        ):
            return target / "cleanup-proposal.json"
        require_runnable(job, "speech_cleanup")
        if job.stages["speech_cleanup"]["status"] != "needs_revision":
            raise _fail()
        lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])
        lineage_by_name = {Path(record["path"]).name: record for record in lineage}
        pins = _cleanup_lineage_pins(job, generation_name=generation_name)
        old_tree = _cleanup_lineage_tree(
            pins,
            lineage_by_name,
            proposal_names=proposal_names,
            include_material_receipt="material-usage.json" in pins,
        )
        manifest = parse_transcript_corrections_json(
            _descriptor_bytes(manifest_pin.descriptor, 4 * 1024 * 1024).decode(
                "utf-8", errors="strict",
            )
        )
        source_record = lineage_by_name.get("word-transcript.json")
        if type(source_record) is not dict or manifest["source"] != {
            key: source_record[key] for key in ("path", "sha256", "bytes")
        }:
            raise _fail()
        words = _word_transcript(pins["word-transcript.json"])
        corrected_words = apply_transcript_corrections(words, manifest)
        old_plan = _strict_json_bytes(
            _descriptor_bytes(pins["cleanup-proposal.json"].descriptor, 16 * 1024 * 1024)
        )
        validate_edit_plan(old_plan, words)
        rebased_plan = _rebase_cleanup_plan_text(old_plan, corrected_words)
        old_summary = _strict_json_bytes(
            _descriptor_bytes(pins["diff-summary.json"].descriptor, 16 * 1024 * 1024)
        )
        old_estimate = _strict_json_bytes(
            _descriptor_bytes(pins["estimated-duration.json"].descriptor, 1024 * 1024)
        )
        history_summary = {
            key: copy.deepcopy(value)
            for key, value in old_summary.items()
            if key != "terminology_review"
        }
        if job.version == 2:
            from . import content_analysis, material_usage, terminology_review

            approved_content = content_analysis.load_approved_content_analysis(job)
            if "terminology_review" in old_summary:
                old_report = old_summary["terminology_review"]
                if old_report.get("content_analysis_sha256") == approved_content["analysis_sha256"]:
                    terminology_review.validate_bound_report(
                        old_report, words=words,
                        content_record=approved_content, summary=history_summary,
                    )
                else:
                    old_receipt = _strict_json_bytes(
                        _descriptor_bytes(pins["material-usage.json"].descriptor, 1024 * 1024)
                    )
                    current_receipt = material_usage.load_current_receipt(job, "content_analysis")
                    if (type(old_receipt) is not dict
                            or type(old_receipt.get("stage_revision")) is not int
                            or current_receipt["stage_revision"] <= old_receipt["stage_revision"]):
                        raise _fail()
                    current_terms = terminology_review._approved_content_terms(approved_content)
                    prior_terms = old_report.get("approved_terms")
                    if (type(prior_terms) is not list
                            or any(type(term) is not str or not term.strip() for term in prior_terms)
                            or len(prior_terms) != len(set(prior_terms))
                            or not set(prior_terms).issubset(current_terms)
                            or type(old_report.get("content_analysis_sha256")) is not str
                            or not re.fullmatch(r"[0-9a-f]{64}", old_report["content_analysis_sha256"])
                            or set(old_report) != {"version", "content_analysis_sha256", "approved_terms", "report"}
                            or old_report["version"] != 1):
                        raise _fail()
                    expected_report = terminology_review.build_report_with_history(
                        words, approved_terms=prior_terms, summary=history_summary,
                    )
                    if old_report["report"] != expected_report:
                        raise _fail()
        elif "terminology_review" in old_summary:
            raise _fail()
        audit_runs = _correction_audit_runs(history_summary)
        if (
            type(old_estimate) is not dict
            or set(old_estimate) != {"version", "seconds", "source_seconds"}
            or old_estimate["version"] != 1
        ):
            raise _fail()
        # Advisory fields are derived data, not trusted instructions. Recompute
        # against the pinned old transcript/plan before accepting a correction.
        if "risk_assessment" in old_summary:
            expected_risk = build_cleanup_proposal(
                old_summary["original_script"], words, old_plan,
                media_duration=_finite_number(old_estimate["source_seconds"]),
            )["diff_summary"]["risk_assessment"]
            if _json_bytes(old_summary["risk_assessment"]) != _json_bytes(expected_risk):
                raise _fail()
        if "reviewed_cut_ranges" in old_summary and (
            _json_bytes(old_summary["reviewed_cut_ranges"])
            != _json_bytes(old_plan.get("reviewed_cut_ranges"))
        ):
            raise _fail()
        proposal = build_cleanup_proposal(
            old_summary["original_script"],
            corrected_words,
            rebased_plan,
            media_duration=_finite_number(old_estimate["source_seconds"]),
        )
        proposal["diff_summary"]["transcript_corrections"] = {
            "version": 1,
            "runs": [
                *audit_runs,
                _correction_audit_run(manifest, manifest_pin),
            ],
        }
        if job.version == 2:
            proposal["diff_summary"]["terminology_review"] = (
                terminology_review.build_bound_report(
                    corrected_words,
                    content_record=approved_content,
                    summary=proposal["diff_summary"],
                )
            )
        stage = _make_stage(job.job_dir, generation_name)
        for name in sorted(task2_names):
            _write_exclusive(
                stage / name, _descriptor_bytes(pins[name].descriptor, 2**31),
            )
        for name, payload in {
            "word-transcript.json": proposal["word_transcript"],
            "diff-summary.json": proposal["diff_summary"],
            "cleanup-proposal.json": proposal["cleanup_proposal"],
            "estimated-duration.json": proposal["estimated_duration"],
        }.items():
            _write_exclusive(stage / name, _json_bytes(payload))
        _fsync_directory(stage)
        for name, pin in pins.items():
            _verify_cleanup_lineage_pin(pin, lineage_by_name[name])
        _verify_pin(manifest_pin)
        if job.version == 2:
            from . import speech_edit_v2

            speech_edit_v2._publish(
                job,
                stage,
                target,
                tuple(sorted(proposal_names)),
                stage_id="speech_cleanup",
            )
        else:
            _swap_generation(
                job,
                target,
                stage,
                _PROPOSAL_NAMES,
                lambda artifacts: mark_ready(job, "speech_cleanup", artifacts),
                old_expected_names=_PROPOSAL_NAMES,
                expected_old_tree=old_tree,
                request_binding=request_binding,
                stage_id="speech_cleanup",
                restore_ready=False,
                is_committed=lambda: (
                    job.stages["speech_cleanup"]["status"] == "ready_for_review"
                ),
            )
        stage = None
        return target / "cleanup-proposal.json"
    except (UnicodeError, EditTimelineError):
        raise _fail() from None
    except BaseException:
        raise _fail() from None
    finally:
        for pin in pins.values():
            _close_pin(pin)
        if manifest_pin is not None:
            _close_pin(manifest_pin)
        publication_owns_stage = False
        if stage is not None and job.version == 2:
            from . import speech_edit_v2

            publication_owns_stage = speech_edit_v2._publication_owns_stage(
                job, target, stage,
            )
        if stage is not None and not publication_owns_stage:
            try:
                _discard_directory(stage, _PROPOSAL_NAMES)
            except EditTimelineError:
                pass


_EDIT_NAMES = {"edit-plan.json", "edited-aroll.mp4", "timeline-map.json"}


def _stage_artifact_pins(
    job: JobState,
    stage_id: str,
    target_name: str,
    expected_names: set[str],
) -> dict[str, _PinnedFile]:
    stage = job.stages.get(stage_id)
    if type(stage) is not dict or stage.get("status") != "approved":
        raise _fail()
    artifacts = stage.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(expected_names):
        raise _fail()
    result: dict[str, _PinnedFile] = {}
    try:
        for record in artifacts:
            pin = _pin_record(job.job_dir, record)
            if pin.path.parent != job.job_dir / target_name:
                os.close(pin.descriptor)
                raise _fail()
            if pin.path.name not in expected_names or pin.path.name in result:
                os.close(pin.descriptor)
                raise _fail()
            result[pin.path.name] = pin
        if set(result) != expected_names:
            raise _fail()
        return result
    except BaseException:
        for pin in result.values():
            try:
                os.close(pin.descriptor)
            except OSError:
                pass
        raise


def _word_transcript(pin: _PinnedFile) -> list[dict[str, Any]]:
    payload = _strict_json_bytes(_descriptor_bytes(pin.descriptor, 16 * 1024 * 1024))
    if (
        type(payload) is not dict
        or set(payload) != {"version", "words"}
        or type(payload["version"]) is not int
        or payload["version"] != 1
    ):
        raise _fail()
    return _validate_words(payload["words"])


def _inspect_profile(pin: _PinnedFile, video_record: dict[str, Any]) -> dict[str, Any]:
    payload = _strict_json_bytes(_descriptor_bytes(pin.descriptor, 4 * 1024 * 1024))
    if type(payload) is not dict or set(payload) != {
        "version", "streams", "video", "audio", "script"
    }:
        raise _fail()
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise _fail()
    streams = payload["streams"]
    video = payload["video"]
    audio = payload["audio"]
    if (
        type(streams) is not dict
        or set(streams) != {"video", "audio"}
        or type(streams["video"]) is not int
        or type(streams["audio"]) is not int
        or streams != {"video": 1, "audio": 1}
    ):
        raise _fail()
    if type(video) is not dict or set(video) != {
        "codec", "width", "height", "sample_aspect_ratio",
        "display_aspect_ratio", "fps", "duration", "path", "sha256", "bytes",
    }:
        raise _fail()
    if type(audio) is not dict or set(audio) != {
        "codec", "sample_rate", "channels", "duration"
    }:
        raise _fail()
    for key in ("width", "height"):
        if type(video[key]) is not int or video[key] <= 0:
            raise _fail()
    fps = _finite_number(video["fps"])
    duration = _finite_number(video["duration"])
    if fps <= 0 or duration <= 0:
        raise _fail()
    if (
        type(video["sample_aspect_ratio"]) is not str
        or type(video["display_aspect_ratio"]) is not str
        or not video["sample_aspect_ratio"]
        or not video["display_aspect_ratio"]
        or type(audio["sample_rate"]) is not int
        or audio["sample_rate"] <= 0
        or type(audio["channels"]) is not int
        or audio["channels"] <= 0
        or _finite_number(audio["duration"]) <= 0
    ):
        raise _fail()
    if (
        video["path"] != video_record["path"]
        or video["sha256"] != video_record["sha256"]
        or video["bytes"] != video_record["bytes"]
    ):
        raise _fail()
    return {
        "width": video["width"],
        "height": video["height"],
        "fps": fps,
        "duration": duration,
    }


def _has_actual_deletion(
    intervals: list[tuple[float, float]],
    duration: float,
) -> bool:
    return not (
        len(intervals) == 1
        and abs(intervals[0][0]) <= 1e-9
        and abs(intervals[0][1] - duration) <= 1e-9
    )


def _ffmpeg_number(value: float) -> str:
    return format(value, ".9f").rstrip("0").rstrip(".") or "0"


def _run_ffmpeg(
    command: list[str],
    *,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
        check=True,
        pass_fds=pass_fds,
    )


def _render_media(
    video: _PinnedFile,
    output: Path,
    plan: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    intervals = _timeline_intervals(plan, profile["duration"])
    deleted = _has_actual_deletion(intervals, profile["duration"])
    descriptor_path = f"/dev/fd/{video.descriptor}"
    base = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", descriptor_path,
    ]
    width = profile["width"]
    height = profile["height"]
    fps = _ffmpeg_number(profile["fps"])
    normalize = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
    )
    if not deleted:
        command = base + [
            "-map", "0:v:0", "-map", "0:a:0", "-vf", normalize,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-r", fps, "-c:a", "copy", "-movflags", "+faststart", str(output),
        ]
        audio_policy = "copy-original-elementary"
        render_adapter = "local-ffmpeg-no-cut"
    else:
        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, (start, end) in enumerate(intervals):
            start_value = _ffmpeg_number(start)
            end_value = _ffmpeg_number(end)
            filters.append(
                f"[0:v:0]trim=start={start_value}:end={end_value},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
            filters.append(
                f"[0:a:0]atrim=start={start_value}:end={end_value},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            concat_inputs.append(f"[v{index}][a{index}]")
        filters.append(
            "".join(concat_inputs)
            + f"concat=n={len(intervals)}:v=1:a=1[vcat][acat]"
        )
        filters.append(f"[vcat]{normalize}[vout]")
        filters.append(
            "[acat]aformat=sample_fmts=fltp:sample_rates=48000:"
            "channel_layouts=stereo[aout]"
        )
        command = base + [
            "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-r", fps, "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(output),
        ]
        audio_policy = "aac-48000-stereo-single-encode"
        render_adapter = "local-ffmpeg-trim-concat"
    _run_ffmpeg(command, pass_fds=(video.descriptor,))
    timeline_segments = []
    cursor = 0.0
    for start, end in intervals:
        length = end - start
        timeline_segments.append(
            {
                "source_start": start,
                "source_end": end,
                "timeline_start": cursor,
                "timeline_end": cursor + length,
            }
        )
        cursor += length
    return {
        "version": 1,
        "source_duration": profile["duration"],
        "output_duration": cursor,
        "has_deletion": deleted,
        "audio_policy": audio_policy,
        "render_adapter": render_adapter,
        "segments": timeline_segments,
    }, audio_policy


def render_edit(job: JobState) -> Path:
    """Render the approved cleanup plan and stop for edit-structure review."""
    if job.version == 2:
        from . import speech_edit_v2

        return speech_edit_v2.render_edit(job)
    if _recover_generation(
        job,
        "03-edit-structure",
        "edit_structure",
        _EDIT_NAMES,
        restore_ready=False,
        allowed_old_names=(_EDIT_NAMES,),
    ):
        return job.job_dir / "03-edit-structure" / "edited-aroll.mp4"
    require_runnable(job, "edit_structure")
    pins: list[_PinnedFile] = []
    stage: Path | None = None
    try:
        video = _pin_record(job.root, job.inputs.get("video"))
        pins.append(video)
        inspect_pins = _stage_artifact_pins(
            job, "inspect", "01-inspect", {"report.json"},
        )
        pins.extend(inspect_pins.values())
        speech_pins = _stage_artifact_pins(
            job, "speech_cleanup", "02-speech-cleanup", _PROPOSAL_NAMES,
        )
        pins.extend(speech_pins.values())
        words = _word_transcript(speech_pins["word-transcript.json"])
        plan_source = _descriptor_bytes(
            speech_pins["cleanup-proposal.json"].descriptor,
            16 * 1024 * 1024,
        )
        try:
            plan_text = plan_source.decode("utf-8", errors="strict")
        except UnicodeError:
            raise _fail() from None
        plan = parse_edit_plan_json(plan_text, words)
        profile = _inspect_profile(inspect_pins["report.json"], job.inputs["video"])
        stage = _make_stage(job.job_dir, "03-edit-structure")
        timeline_map, audio_policy = _render_media(
            video, stage / "edited-aroll.mp4", plan, profile,
        )
        edit_plan = {
            "version": 1,
            "cleanup_proposal": plan,
            "canvas": {
                "width": profile["width"],
                "height": profile["height"],
                "fps": profile["fps"],
            },
            "audio_policy": audio_policy,
            "downstream_audio_policy": "copy",
        }
        _write_exclusive(stage / "edit-plan.json", _json_bytes(edit_plan))
        _write_exclusive(stage / "timeline-map.json", _json_bytes(timeline_map))
        _fsync_directory(stage)
        for pin in pins:
            _verify_pin(pin)
        target = job.job_dir / "03-edit-structure"
        _swap_generation(
            job,
            target,
            stage,
            _EDIT_NAMES,
            lambda artifacts: mark_ready(job, "edit_structure", artifacts),
            old_expected_names=_EDIT_NAMES,
            stage_id="edit_structure",
            restore_ready=False,
            is_committed=lambda: (
                job.stages["edit_structure"]["status"] == "ready_for_review"
            ),
        )
        stage = None
        return target / "edited-aroll.mp4"
    except BaseException as failure:
        if isinstance(failure, EditTimelineError):
            raise failure from None
        raise _fail() from None
    finally:
        for pin in pins:
            try:
                os.close(pin.descriptor)
            except OSError:
                pass
        if stage is not None:
            try:
                _discard_directory(stage, _EDIT_NAMES, allow_partial=True)
            except EditTimelineError:
                pass

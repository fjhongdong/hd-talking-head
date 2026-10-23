"""Resolve approved ShotRecipe components without searching or generating media."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from . import user_materials, visual_strategy


class BrollMediaError(RuntimeError):
    """Raised when approved component media is unavailable or has changed."""


@dataclass(frozen=True)
class ResolvedComponentMedia:
    component_id: str
    kind: str
    media_type: str
    path: str | None
    sha256: str | None
    provenance: Mapping[str, Any]


_MATERIAL_PATH_FIELDS = {
    "local_material": "job_path",
    "official_material": "snapshot_path",
    "external_stock": "job_path",
}
_RECIPE_COMPONENT_FIELDS = {
    "component_id",
    "kind",
    "semantic_role",
    "executor",
    "media_type",
    "render_window",
    "artifact_contract",
}
_HASH_CHUNK_SIZE = 1024 * 1024


def _media_type(value: object) -> str:
    """Preserve the legacy image/video normalization helper for media probes."""
    aliases = {"image": "image", "images": "image", "video": "video"}
    result = aliases.get(value)
    if result is None:
        raise BrollMediaError("approved B-roll material is not image or video")
    return result


def _fail() -> BrollMediaError:
    return BrollMediaError("approved component media is unavailable or changed")


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _file_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    return flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _close_all(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


@dataclass
class _PinnedJob:
    path: Path
    anchor: str
    names: tuple[str, ...]
    descriptors: list[int]
    identities: tuple[tuple[int, int, int], ...]

    @property
    def descriptor(self) -> int:
        return self.descriptors[-1]

    @classmethod
    def open(cls, job: Any) -> "_PinnedJob":
        path, anchor, names = _job_path(job)
        descriptors: list[int] = []
        identities: list[tuple[int, int, int]] = []
        try:
            visible_anchor = os.lstat(anchor)
            if not stat.S_ISDIR(visible_anchor.st_mode):
                raise _fail()
            descriptor = os.open(anchor, _directory_flags())
            descriptors.append(descriptor)
            opened_anchor = os.fstat(descriptor)
            if _directory_identity(opened_anchor) != _directory_identity(visible_anchor):
                raise _fail()
            identities.append(_directory_identity(opened_anchor))

            for name in names:
                parent = descriptors[-1]
                visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(visible.st_mode):
                    raise _fail()
                descriptor = os.open(name, _directory_flags(), dir_fd=parent)
                descriptors.append(descriptor)
                opened = os.fstat(descriptor)
                if _directory_identity(opened) != _directory_identity(visible):
                    raise _fail()
                identities.append(_directory_identity(opened))
            return cls(path, anchor, names, descriptors, tuple(identities))
        except BrollMediaError:
            _close_all(descriptors)
            raise
        except (OSError, TypeError, ValueError):
            _close_all(descriptors)
            raise _fail() from None

    def verify_visible(self) -> None:
        verification: list[int] = []
        try:
            for descriptor, identity in zip(self.descriptors, self.identities):
                current = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or _directory_identity(current) != identity
                ):
                    raise _fail()

            visible_anchor = os.lstat(self.anchor)
            if (
                not stat.S_ISDIR(visible_anchor.st_mode)
                or _directory_identity(visible_anchor) != self.identities[0]
            ):
                raise _fail()
            descriptor = os.open(self.anchor, _directory_flags())
            verification.append(descriptor)
            if _directory_identity(os.fstat(descriptor)) != self.identities[0]:
                raise _fail()

            for index, name in enumerate(self.names, start=1):
                visible = os.stat(
                    name, dir_fd=verification[-1], follow_symlinks=False
                )
                if (
                    not stat.S_ISDIR(visible.st_mode)
                    or _directory_identity(visible) != self.identities[index]
                ):
                    raise _fail()
                descriptor = os.open(
                    name, _directory_flags(), dir_fd=verification[-1]
                )
                verification.append(descriptor)
                if _directory_identity(os.fstat(descriptor)) != self.identities[index]:
                    raise _fail()
        except BrollMediaError:
            raise
        except (OSError, TypeError, ValueError):
            raise _fail() from None
        finally:
            _close_all(verification)

    def close(self) -> None:
        _close_all(self.descriptors)
        self.descriptors.clear()


def _job_path(job: Any) -> tuple[Path, str, tuple[str, ...]]:
    try:
        raw = os.fspath(job.job_dir)
    except (AttributeError, TypeError):
        raise _fail() from None
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise _fail()
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise _fail()
    anchor = path.anchor
    if not anchor:
        raise _fail()
    return path, anchor, tuple(path.parts[1:])


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    while True:
        try:
            chunk = os.read(descriptor, _HASH_CHUNK_SIZE)
        except InterruptedError:
            continue
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _resolve_frozen_file(
    pinned_job: _PinnedJob,
    relative_value: str,
    expected_sha256: str,
) -> tuple[str, str, int, tuple[int, int, int, int, int, int, int]]:
    relative = PurePosixPath(relative_value)
    parts = relative.parts
    if not parts:
        raise _fail()

    descriptors: list[int] = []
    directories: list[
        tuple[int, int, str, tuple[int, int, int]]
    ] = []
    try:
        parent_descriptor = pinned_job.descriptor
        for part in parts[:-1]:
            visible_directory = os.stat(
                part, dir_fd=parent_descriptor, follow_symlinks=False
            )
            if not stat.S_ISDIR(visible_directory.st_mode):
                raise _fail()
            descriptor = os.open(
                part, _directory_flags(), dir_fd=parent_descriptor
            )
            descriptors.append(descriptor)
            directory_metadata = os.fstat(descriptor)
            if _directory_identity(directory_metadata) != _directory_identity(
                visible_directory
            ):
                raise _fail()
            directories.append(
                (
                    descriptor,
                    parent_descriptor,
                    part,
                    _directory_identity(directory_metadata),
                )
            )
            parent_descriptor = descriptor
        visible_before_open = os.stat(
            parts[-1], dir_fd=parent_descriptor, follow_symlinks=False
        )
        if not stat.S_ISREG(visible_before_open.st_mode):
            raise _fail()
        file_descriptor = os.open(
            parts[-1], _file_flags(), dir_fd=parent_descriptor
        )
        descriptors.append(file_descriptor)

        before = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or visible_before_open.st_nlink != 1
            or _file_identity(before) != _file_identity(visible_before_open)
        ):
            raise _fail()
        digest = _sha256_fd(file_descriptor)
        after = os.fstat(file_descriptor)
        visible = os.stat(parts[-1], dir_fd=parent_descriptor, follow_symlinks=False)
        for descriptor, parent, name, identity in directories:
            current = os.fstat(descriptor)
            visible_directory = os.stat(
                name, dir_fd=parent, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(visible_directory.st_mode)
                or _directory_identity(current) != identity
                or _directory_identity(visible_directory) != identity
            ):
                raise _fail()
        if (
            not stat.S_ISREG(visible.st_mode)
            or before.st_nlink != 1
            or after.st_nlink != 1
            or visible.st_nlink != 1
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
            or digest != expected_sha256.lower()
        ):
            raise _fail()
        return (
            str(pinned_job.path.joinpath(*parts)),
            digest,
            before.st_size,
            _file_identity(before),
        )
    except BrollMediaError:
        raise
    except (OSError, TypeError, ValueError):
        raise _fail() from None
    finally:
        _close_all(descriptors)


def _verify_frozen_file_identity(
    pinned_job: _PinnedJob,
    relative_value: str,
    expected_identity: tuple[int, int, int, int, int, int, int],
) -> None:
    parts = PurePosixPath(relative_value).parts
    descriptors: list[int] = []
    parent = pinned_job.descriptor
    try:
        for part in parts[:-1]:
            visible_directory = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(visible_directory.st_mode):
                raise _fail()
            descriptor = os.open(part, _directory_flags(), dir_fd=parent)
            descriptors.append(descriptor)
            if _directory_identity(os.fstat(descriptor)) != _directory_identity(
                visible_directory
            ):
                raise _fail()
            parent = descriptor
        visible = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(visible.st_mode)
            or visible.st_nlink != 1
            or _file_identity(visible) != expected_identity
        ):
            raise _fail()
        descriptor = os.open(parts[-1], _file_flags(), dir_fd=parent)
        descriptors.append(descriptor)
        if _file_identity(os.fstat(descriptor)) != expected_identity:
            raise _fail()
    except BrollMediaError:
        raise
    except (OSError, TypeError, ValueError):
        raise _fail() from None
    finally:
        _close_all(descriptors)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _provenance(
    component: Mapping[str, Any],
    *,
    status: str,
    byte_size: int | None = None,
) -> Mapping[str, Any]:
    path_field = _MATERIAL_PATH_FIELDS.get(str(component["kind"]))
    omitted = _RECIPE_COMPONENT_FIELDS | {"sha256"}
    if path_field is not None:
        omitted.add(path_field)
    values = {
        key: value
        for key, value in component.items()
        if key not in omitted
    }
    values["status"] = status
    if byte_size is not None:
        values["byte_size"] = byte_size
    if status == "pending_execution" and "sha256" in component:
        values["binding_sha256"] = component["sha256"]
    return _freeze(values)


def resolve_recipe_media(
    job: Any,
    recipe: Mapping[str, Any],
) -> tuple[ResolvedComponentMedia, ...]:
    """Resolve each approved component in order, without executing generators."""
    try:
        checked = visual_strategy.validate_shot_recipe_v2(recipe)
    except visual_strategy.VisualStrategyError:
        raise BrollMediaError("approved ShotRecipe v2 is invalid") from None

    has_frozen_media = any(
        component["kind"] in _MATERIAL_PATH_FIELDS
        for component in checked["components"]
    )
    pinned_job = _PinnedJob.open(job) if has_frozen_media else None

    resolved: list[ResolvedComponentMedia] = []
    final_identities: list[
        tuple[str, tuple[int, int, int, int, int, int, int]]
    ] = []
    try:
        for component in checked["components"]:
            kind = component["kind"]
            if kind == "local_material":
                try:
                    user_materials.assert_active_local_material(
                        job, component["material_id"], component["sha256"])
                except ValueError as exc:
                    raise BrollMediaError(str(exc)) from exc
            path_field = _MATERIAL_PATH_FIELDS.get(kind)
            if path_field is None:
                resolved.append(
                    ResolvedComponentMedia(
                        component_id=component["component_id"],
                        kind=kind,
                        media_type=component["media_type"],
                        path=None,
                        sha256=None,
                        provenance=_provenance(
                            component, status="pending_execution"
                        ),
                    )
                )
                continue

            if pinned_job is None:
                raise _fail()
            path, digest, byte_size, identity = _resolve_frozen_file(
                pinned_job,
                component[path_field],
                component["sha256"],
            )
            final_identities.append((component[path_field], identity))
            resolved.append(
                ResolvedComponentMedia(
                    component_id=component["component_id"],
                    kind=kind,
                    media_type=component["media_type"],
                    path=path,
                    sha256=digest,
                    provenance=_provenance(
                        component,
                        status="frozen_media",
                        byte_size=byte_size,
                    ),
                )
            )
        if pinned_job is not None:
            for relative_value, identity in final_identities:
                _verify_frozen_file_identity(
                    pinned_job, relative_value, identity
                )
            pinned_job.verify_visible()
        return tuple(resolved)
    finally:
        if pinned_job is not None:
            pinned_job.close()

"""Execute one strictly bound ShotRecipe v2 component without kind fallback.

``execute_component`` intentionally accepts only a ``ComponentExecutionRequest``.
The request carries the complete ShotRecipe v2 plus the selected component ID so
the executor can bind every artifact to the canonical recipe identity.  A bare
recipe component is not an accepted compatibility format.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import resource
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from . import broll_media, visual_strategy
from .dependency_contracts import DEPENDENCY_CONTRACTS
from .runtime_contracts import normalize_contracts


ERROR_CODES = frozenset(
    {
        "BROLL_SCHEMA_INVALID",
        "BROLL_TRUTH_CONFLICT",
        "BROLL_PROVIDER_UNCONNECTED",
        "BROLL_DOWNLOAD_REJECTED",
        "BROLL_DEPENDENCY_UNBOUND",
        "BROLL_GENERATION_FAILED",
        "BROLL_RENDER_FAILED",
        "BROLL_COMPOSITE_FAILED",
    }
)
ALLOWED_ACTIONS = ("retry_same_strategy", "replan_visual_direction")

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MATERIAL_KINDS = frozenset(
    {"local_material", "official_material", "external_stock"}
)
_DEPENDENCY_CONTRACTS = {
    key: (value["executor"], value["renderer"]) for key, value in DEPENDENCY_CONTRACTS.items()
}

_LICENSE_KEYS = {
    "schema_version",
    "idempotency_key",
    "search_generation",
    "snapshot_sha256",
    "query_sha256",
    "provider",
    "provider_asset_id",
    "author",
    "asset_page",
    "license_name",
    "license_version",
    "downloaded_at",
    "byte_count",
    "sha256",
    "job_path",
    "license_snapshot",
}
_STOCK_RECEIPT_KEYS = {
    "schema_version",
    "state",
    "idempotency_key",
    "nonce",
    "provider",
    "provider_asset_id",
    "search_generation",
    "snapshot_sha256",
    "query_sha256",
    "staging_job_path",
    "planned_job_path",
    "planned_license_snapshot",
    "license_staging_job_path",
    "media_type",
    "format",
    "mime_type",
    "expected_identity",
    "downloaded_at",
    "byte_count",
    "sha256",
    "actual_width",
    "actual_height",
    "dimensions_source",
    "license_record",
    "license_sha256",
    "license_identity",
}
_MAX_BRIEF_BYTES = 4 * 1024 * 1024
_MAX_LICENSE_BYTES = 1024 * 1024
_MAX_REFERENCE_MEDIA_BYTES = 512 * 1024 * 1024
_MAX_REFERENCE_MEDIA_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
_TERM_GRACE_SECONDS = 0.25
_KILL_GRACE_SECONDS = 1.0
_MAX_ADAPTER_JSON_BYTES = 64 * 1024
_MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
_MAX_ENTRYPOINT_BYTES = 1024 * 1024
_MAX_TIMEOUT_SECONDS = 300.0
_PROBE_KEYS = frozenset(
    {
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
)
_QA_KEYS = frozenset({"passed", "checks"})
_SKILL_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "invocation_id",
        "dependency_id",
        "status",
        "brief_sha256",
        "staged_output_job_path",
        "output_sha256",
        "producer_version",
        "primary_renderer",
        "renderer_version",
    }
)
_NON_RECORD_FIELD_FRAGMENTS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
)
_ARGV_TEMPLATE_TOKENS = {
    "{launcher}": "launcher",
    "{entrypoint}": "entrypoint",
    "{brief_path}": "brief",
    "{output_path}": "output",
    "{media_manifest_fd}": "media_manifest",
}
_ARGV_TEMPLATE_ITEM_KEYS = frozenset({"index", "role", "value"})


class BrollComponentExecutionError(RuntimeError):
    """A stable component execution failure with bounded evidence."""

    def __init__(
        self,
        error_code: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        if error_code not in ERROR_CODES:
            raise ValueError("unknown B-roll execution error code")
        self.error_code = error_code
        self.allowed_actions = ALLOWED_ACTIONS
        self.evidence = _freeze(evidence or {})
        super().__init__(error_code)


class _FrozenDict(dict):
    """A JSON-serializable mapping that rejects every mutation API."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("frozen mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenDict":
        return self


@dataclass(frozen=True)
class ComponentExecutionRequest:
    """The only supported input envelope for one component execution."""

    recipe: Mapping[str, Any]
    component_id: str


@dataclass(frozen=True)
class AdapterResult:
    invocation_evidence: Mapping[str, Any]
    qa: Mapping[str, Any]


@dataclass(frozen=True)
class AdapterContext:
    job_id: str
    job_dir: Path
    segment_id: str
    strategy_revision: int
    component_id: str
    kind: str
    recipe: Mapping[str, Any]
    component: Mapping[str, Any]
    input_sha256: str
    approval_sha256: str
    source_path: Path | None
    source_sha256: str | None
    staging_path: Path
    staging_job_path: str
    output_job_path: str


@dataclass(frozen=True)
class KindAdapter:
    kind: str
    approved_executor: str
    adapter_id: str
    adapter_version: str
    artifact_media_type: str
    invoke: Callable[[AdapterContext], AdapterResult]
    provider: str | None = None
    model: str | None = None
    endpoint_id: str | None = None
    request_only_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactProbe:
    probe_id: str
    probe_version: str
    probe: Callable[[Path, str, Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class ReferenceProcessMedia:
    media_ref: str
    job_path: str
    sha256: str


@dataclass(frozen=True)
class ReferenceProcessAdapter:
    adapter_id: str
    dependency_id: str
    approved_executor: str
    dependency_root: Path
    entrypoint: str
    entrypoint_sha256: str
    producer_version: str
    primary_renderer: str
    renderer_version: str
    artifact_media_type: str
    launcher: Path
    launcher_sha256: str
    argv_template: tuple[str, ...]
    brief_loader: Callable[[Any, Mapping[str, Any], Mapping[str, Any]], bytes]
    self_contained_wrapper: bool
    media_loader: Callable[
        [Any, Mapping[str, Any], Mapping[str, Any], bytes],
        tuple[ReferenceProcessMedia, ...],
    ] | None = None
    timeout_seconds: float = 120.0
    request_only_values: tuple[str, ...] = ()
    qualification_registry_path: str | None = None
    qualification_registry_sha256: str | None = None
    runtime_contracts: dict[str, Any] | None = None


@dataclass(frozen=True)
class SkillInvocationResult:
    invocation_id: str
    receipt: Mapping[str, Any]
    qa: Mapping[str, Any]


@dataclass(frozen=True)
class SkillInvocationAdapter:
    adapter_id: str
    dependency_id: str
    approved_executor: str
    entrypoint: str
    producer_version: str
    primary_renderer: str
    renderer_version: str
    artifact_media_type: str
    brief_loader: Callable[[Any, Mapping[str, Any], Mapping[str, Any]], bytes]
    invoker: Callable[[AdapterContext, bytes], SkillInvocationResult]
    request_only_values: tuple[str, ...] = ()


@dataclass
class _FrozenProcessBinding:
    adapter: ReferenceProcessAdapter
    entrypoint_fd: int
    launcher_fd: int
    entrypoint_identity: tuple[int, int, int, int]
    launcher_identity: tuple[int, int, int, int]

    def close(self) -> None:
        for descriptor in (self.entrypoint_fd, self.launcher_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class _FrozenQualificationRegistry:
    path: Path
    expected_sha256: str
    descriptor: int
    identity: tuple[int, int, int, int]

    def close(self) -> None:
        try:
            os.close(self.descriptor)
        except OSError:
            pass


@dataclass(frozen=True)
class ComponentArtifact(Mapping[str, Any]):
    schema_version: int
    status: str
    job_id: str
    segment_id: str
    component_id: str
    kind: str
    strategy_revision: int
    media_type: str
    render_window: Mapping[str, Any]
    z_index: int
    layout_slot: str
    opacity: float
    safe_zone: Mapping[str, Any]
    artifact_contract: Mapping[str, Any]
    source_media_type: str
    artifact_media_type: str
    media_probe: Mapping[str, Any]
    input_sha256: str
    job_path: str
    byte_count: int
    output_sha256: str
    invocation_evidence: Mapping[str, Any]
    qa: Mapping[str, Any]
    error_code: None

    def __getitem__(self, key: str) -> Any:
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.__dataclass_fields__)

    def __len__(self) -> int:
        return len(self.__dataclass_fields__)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool, bytes, Path)) or value is None:
        return value
    return str(value)


def _raise(code: str, *, evidence: Mapping[str, Any] | None = None) -> None:
    raise BrollComponentExecutionError(code, evidence=evidence)


def _raise_reference_failure(
    adapter: Any, stderr: bytes, evidence: Mapping[str, Any]
) -> None:
    error = BrollComponentExecutionError("BROLL_RENDER_FAILED", evidence=evidence)
    if getattr(adapter, "dependency_id", None) == "huashu-art-motion":
        text = stderr.decode("utf-8", "replace")
        prefix = "Huashu native renderer diagnostic:"
        text = " ".join(line.strip()[len(prefix):].strip()
                          for line in text.splitlines()
                          if line.strip().startswith(prefix))[:2000]
        if text:
            error.add_note(prefix + " " + text)
    elif getattr(adapter, "dependency_id", None) == "paper-collage-ad":
        details = [line.strip() for line in stderr.decode("utf-8", "replace").splitlines()
                   if line.startswith("ValueError: paper output contains a continuous freeze")]
        if details:
            error.add_note("Paper native renderer diagnostic: " + details[-1][:2000])
    raise error


def _canonical_bytes(
    value: object, code: str = "BROLL_SCHEMA_INVALID"
) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _raise(code)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_all(descriptor: int, payload: bytes, code: str) -> None:
    view = memoryview(payload)
    written = 0
    try:
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if type(count) is not int or count <= 0:
                _raise(code)
            written += count
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)


def _non_record_field(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _NON_RECORD_FIELD_FRAGMENTS)


def _validate_json_value(
    value: object,
    *,
    code: str,
    job_dir: Path | None = None,
    depth: int = 0,
) -> None:
    if depth > 32:
        _raise(code)
    if value is None or type(value) in {str, bool, int}:
        if type(value) is str:
            try:
                value.encode("utf-8", "strict")
            except UnicodeError:
                _raise(code)
            if job_dir is not None and str(job_dir) in value:
                _raise(code)
        return
    if type(value) is float:
        if not math.isfinite(value):
            _raise(code)
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, code=code, job_dir=job_dir, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or _non_record_field(key):
                _raise(code)
            _validate_json_value(item, code=code, job_dir=job_dir, depth=depth + 1)
        return
    _raise(code)


def _validated_json_record(
    value: object,
    *,
    code: str,
    job_dir: Path | None = None,
    maximum: int = _MAX_ADAPTER_JSON_BYTES,
) -> dict[str, Any]:
    if type(value) is not dict:
        _raise(code)
    _validate_json_value(value, code=code, job_dir=job_dir)
    payload = _canonical_bytes(value, code)
    if len(payload) > maximum:
        _raise(code)
    return copy.deepcopy(value)


def _filter_adapter_json(value: Any, request_only_values: tuple[str, ...]) -> Any:
    if type(value) is dict:
        return {
            key: _filter_adapter_json(item, request_only_values)
            for key, item in value.items()
        }
    if type(value) is list:
        return [_filter_adapter_json(item, request_only_values) for item in value]
    if type(value) is str:
        filtered = value
        for request_only_value in request_only_values:
            if request_only_value:
                filtered = filtered.replace(request_only_value, "[FILTERED]")
        return filtered
    return value


def _validated_qa(
    value: object, *, code: str, job_dir: Path | None = None
) -> dict[str, Any]:
    qa = _validated_json_record(value, code=code, job_dir=job_dir)
    if set(qa) != _QA_KEYS or qa.get("passed") is not True:
        _raise(code)
    checks = qa.get("checks")
    if (
        type(checks) is not list
        or not checks
        or any(type(item) is not str or not item for item in checks)
        or len(set(checks)) != len(checks)
    ):
        _raise(code)
    return qa


def _approved_unchanged(
    original: ComponentExecutionRequest,
    approval_sha256: str,
) -> None:
    try:
        current = _sha256_bytes(
            _canonical_bytes(
                {"recipe": original.recipe, "component_id": original.component_id}
            )
        )
    except BrollComponentExecutionError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise("BROLL_SCHEMA_INVALID")
    if current != approval_sha256:
        _raise("BROLL_SCHEMA_INVALID")


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _raise("BROLL_SCHEMA_INVALID")
    return value


@dataclass
class _PinnedJob:
    job_id: str
    path: Path
    root_fd: int
    chain_fds: tuple[int, ...]
    chain_checks: tuple[tuple[Path, tuple[int, int, int]], ...]
    identity: tuple[int, int, int]

    def verify(self, code: str) -> None:
        try:
            opened = os.fstat(self.root_fd)
            for path, expected in self.chain_checks:
                visible = os.lstat(path)
                if (
                    not stat.S_ISDIR(visible.st_mode)
                    or (visible.st_dev, visible.st_ino, visible.st_mode)
                    != expected
                ):
                    _raise(code)
        except OSError:
            _raise(code)
        current = (opened.st_dev, opened.st_ino, opened.st_mode)
        if current != self.identity:
            _raise(code)

    def close(self) -> None:
        for descriptor in reversed(self.chain_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _job_context(job: Any) -> _PinnedJob:
    try:
        job_id = _identifier(job.job_id)
        raw = os.fspath(job.job_dir)
    except BrollComponentExecutionError:
        raise
    except (AttributeError, TypeError, ValueError):
        _raise("BROLL_SCHEMA_INVALID")
    if type(raw) is not str or not raw or "\x00" in raw:
        _raise("BROLL_SCHEMA_INVALID")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        _raise("BROLL_SCHEMA_INVALID")
    descriptors: list[int] = []
    chain_checks: list[tuple[Path, tuple[int, int, int]]] = []
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.anchor, flags)
        descriptors.append(descriptor)
        root_metadata = os.fstat(descriptor)
        chain_checks.append(
            (
                Path(path.anchor),
                (root_metadata.st_dev, root_metadata.st_ino, root_metadata.st_mode),
            )
        )
        current = Path(path.anchor)
        for part in path.parts[1:]:
            descriptor = os.open(part, flags, dir_fd=descriptor)
            descriptors.append(descriptor)
            current = current / part
            part_metadata = os.fstat(descriptor)
            chain_checks.append(
                (
                    current,
                    (
                        part_metadata.st_dev,
                        part_metadata.st_ino,
                        part_metadata.st_mode,
                    ),
                )
            )
        metadata = os.fstat(descriptor)
        visible = os.lstat(path)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino, metadata.st_mode)
            != (visible.st_dev, visible.st_ino, visible.st_mode)
        ):
            _raise("BROLL_SCHEMA_INVALID")
    except BrollComponentExecutionError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _raise("BROLL_SCHEMA_INVALID")
    identity = (metadata.st_dev, metadata.st_ino, metadata.st_mode)
    return _PinnedJob(
        job_id,
        path,
        descriptors[-1],
        tuple(descriptors),
        tuple(chain_checks),
        identity,
    )


def _verify_job(job: _PinnedJob, code: str) -> None:
    job.verify(code)


def _open_job_regular(job: _PinnedJob, relative: object, code: str) -> int:
    try:
        parts = _relative_parts(relative)
    except BrollComponentExecutionError:
        _raise(code)
    descriptor = os.dup(job.root_fd)
    file_fd: int | None = None
    try:
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        visible = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(visible.st_mode) or visible.st_nlink != 1:
            _raise(code)
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        metadata = os.fstat(file_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink)
            != (visible.st_dev, visible.st_ino, visible.st_mode, visible.st_nlink)
        ):
            os.close(file_fd)
            file_fd = None
            _raise(code)
        return file_fd
    except BrollComponentExecutionError:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        raise
    except OSError:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        _raise(code)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _relative_parts(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        _raise("BROLL_DOWNLOAD_REJECTED")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")
    return path.parts


def _strict_json(raw: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _raise(code)
            result[key] = value
        return result

    def constant(_value: str) -> None:
        _raise(code)

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
        )
    except BrollComponentExecutionError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        _raise(code)
    if type(value) is not dict:
        _raise(code)
    return value


def _validate_stock_license(
    job: _PinnedJob,
    component: Mapping[str, Any],
) -> None:
    license_fd: int | None = None
    source_fd: int | None = None
    try:
        license_fd = _open_job_regular(
            job, component["license_snapshot"], "BROLL_DOWNLOAD_REJECTED"
        )
        source_fd = _open_job_regular(
            job, component["job_path"], "BROLL_DOWNLOAD_REJECTED"
        )
        license_metadata = os.fstat(license_fd)
        source_metadata = os.fstat(source_fd)
        if license_metadata.st_size > _MAX_LICENSE_BYTES:
            _raise("BROLL_DOWNLOAD_REJECTED")
        raw = b""
        while True:
            block = os.read(license_fd, 64 * 1024)
            if not block:
                break
            raw += block
            if len(raw) > _MAX_LICENSE_BYTES:
                _raise("BROLL_DOWNLOAD_REJECTED")
        source_size = source_metadata.st_size
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise("BROLL_DOWNLOAD_REJECTED")
    finally:
        for descriptor in (license_fd, source_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    value = _strict_json(raw, "BROLL_DOWNLOAD_REJECTED")
    if (
        raw != _canonical_bytes(value, "BROLL_DOWNLOAD_REJECTED") + b"\n"
        or set(value) != _LICENSE_KEYS
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")
    expected = {
        "provider": component["provider"],
        "provider_asset_id": component["provider_asset_id"],
        "author": component["author"],
        "asset_page": component["asset_page"],
        "downloaded_at": component["downloaded_at"],
        "sha256": component["sha256"],
        "job_path": component["job_path"],
        "license_snapshot": component["license_snapshot"],
    }
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or any(value.get(key) != item for key, item in expected.items())
        or type(value.get("byte_count")) is not int
        or value["byte_count"] != source_size
        or type(value.get("license_name")) is not str
        or not value["license_name"]
        or type(value.get("license_version")) is not str
        or not value["license_version"]
        or any(
            type(value.get(key)) is not str
            or _HASH.fullmatch(value[key]) is None
            for key in ("idempotency_key", "snapshot_sha256", "query_sha256")
        )
        or type(value.get("search_generation")) is not str
        or not value["search_generation"]
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")

    key = value["idempotency_key"]
    media_suffix = PurePosixPath(str(component["job_path"])).suffix
    expected_parent = PurePosixPath("stock", key[:2])
    if (
        PurePosixPath(str(component["job_path"]))
        != expected_parent / f"{key}{media_suffix}"
        or PurePosixPath(str(component["license_snapshot"]))
        != expected_parent / f"{key}.license.json"
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")
    receipt_relative = (expected_parent / f"{key}.download.json").as_posix()
    receipt_fd = _open_job_regular(
        job, receipt_relative, "BROLL_DOWNLOAD_REJECTED"
    )
    try:
        receipt_metadata = os.fstat(receipt_fd)
        if receipt_metadata.st_size > _MAX_LICENSE_BYTES:
            _raise("BROLL_DOWNLOAD_REJECTED")
        receipt_raw = b""
        while True:
            block = os.read(receipt_fd, 64 * 1024)
            if not block:
                break
            receipt_raw += block
            if len(receipt_raw) > _MAX_LICENSE_BYTES:
                _raise("BROLL_DOWNLOAD_REJECTED")
        receipt_after = os.fstat(receipt_fd)
        if (
            receipt_metadata.st_dev,
            receipt_metadata.st_ino,
            receipt_metadata.st_size,
            receipt_metadata.st_mtime_ns,
        ) != (
            receipt_after.st_dev,
            receipt_after.st_ino,
            receipt_after.st_size,
            receipt_after.st_mtime_ns,
        ):
            _raise("BROLL_DOWNLOAD_REJECTED")
    except OSError:
        _raise("BROLL_DOWNLOAD_REJECTED")
    finally:
        os.close(receipt_fd)
    receipt = _strict_json(receipt_raw, "BROLL_DOWNLOAD_REJECTED")
    if (
        receipt_raw
        != _canonical_bytes(receipt, "BROLL_DOWNLOAD_REJECTED") + b"\n"
        or set(receipt) != _STOCK_RECEIPT_KEYS
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("state") != "published"
        or type(receipt.get("nonce")) is not str
        or re.fullmatch(r"[0-9a-f]{32}", receipt["nonce"]) is None
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")
    nonce = receipt["nonce"]
    exact = {
        "idempotency_key": key,
        "provider": value["provider"],
        "provider_asset_id": value["provider_asset_id"],
        "search_generation": value["search_generation"],
        "snapshot_sha256": value["snapshot_sha256"],
        "query_sha256": value["query_sha256"],
        "staging_job_path": (
            expected_parent / f".{key}.{nonce}.staging{media_suffix}"
        ).as_posix(),
        "planned_job_path": value["job_path"],
        "planned_license_snapshot": value["license_snapshot"],
        "license_staging_job_path": (
            expected_parent / f".{key}.{nonce}.license.staging.json"
        ).as_posix(),
        "downloaded_at": value["downloaded_at"],
        "byte_count": value["byte_count"],
        "sha256": value["sha256"],
        "license_record": value,
        "license_sha256": _sha256_bytes(raw),
    }
    source_identity = [
        source_metadata.st_dev,
        source_metadata.st_ino,
        source_metadata.st_mode,
        source_metadata.st_nlink,
        source_metadata.st_size,
        source_metadata.st_mtime_ns,
        source_metadata.st_ctime_ns,
    ]
    license_identity = [
        license_metadata.st_dev,
        license_metadata.st_ino,
        license_metadata.st_mode,
    ]
    if (
        any(receipt.get(field) != item for field, item in exact.items())
        or type(receipt.get("expected_identity")) is not list
        or len(receipt["expected_identity"]) != 7
        or any(type(item) is not int for item in receipt["expected_identity"])
        or receipt["expected_identity"][:3] != source_identity[:3]
        or receipt["expected_identity"][3] != 1
        or receipt.get("license_identity") != license_identity
        or type(receipt.get("media_type")) is not str
        or receipt["media_type"] != component["media_type"]
        or type(receipt.get("format")) is not str
        or not receipt["format"]
        or type(receipt.get("mime_type")) is not str
        or not receipt["mime_type"]
        or type(receipt.get("actual_width")) is not int
        or receipt["actual_width"] <= 0
        or type(receipt.get("actual_height")) is not int
        or receipt["actual_height"] <= 0
        or receipt.get("dimensions_source")
        not in {"provider_variant", "url_variant", "probe"}
    ):
        _raise("BROLL_DOWNLOAD_REJECTED")


def _selected_request(
    component: object,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    if type(component) is not ComponentExecutionRequest:
        _raise("BROLL_SCHEMA_INVALID")
    try:
        checked = visual_strategy.validate_shot_recipe_v2(component.recipe)
    except visual_strategy.VisualStrategyError:
        _raise("BROLL_SCHEMA_INVALID")
    component_id = _identifier(component.component_id)
    selected = [
        item for item in checked["components"] if item["component_id"] == component_id
    ]
    if len(selected) != 1:
        _raise("BROLL_SCHEMA_INVALID")
    chosen = selected[0]
    _identifier(checked["segment_id"])
    if chosen["kind"] == "code_generated" and chosen["semantic_role"] == "evidence":
        _raise("BROLL_TRUTH_CONFLICT")
    input_sha = _sha256_bytes(
        _canonical_bytes({"recipe": checked, "component_id": component_id})
    )
    return checked, chosen, input_sha


def _single_recipe(recipe: Mapping[str, Any], component: Mapping[str, Any]) -> dict[str, Any]:
    checked = copy.deepcopy(dict(recipe))
    if sum(
        item.get("component_id") == component.get("component_id")
        for item in checked["components"]
    ) != 1:
        _raise("BROLL_SCHEMA_INVALID")
    return checked


@dataclass
class _PinnedSource:
    descriptor: int
    expected_sha256: str
    identity: tuple[int, int, int, int, int]

    def close(self) -> None:
        try:
            os.close(self.descriptor)
        except OSError:
            pass


def _prepare_source(
    job: Any,
    pinned_job: _PinnedJob,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
) -> _PinnedSource | None:
    kind = component["kind"]
    if kind not in _MATERIAL_KINDS:
        return None
    code = (
        "BROLL_DOWNLOAD_REJECTED"
        if kind == "external_stock"
        else "BROLL_COMPOSITE_FAILED"
    )
    if kind == "external_stock":
        _validate_stock_license(pinned_job, component)
    try:
        resolved_items = broll_media.resolve_recipe_media(
            job, _single_recipe(recipe, component)
        )
    except broll_media.BrollMediaError:
        _raise(code)
    selected = [
        item
        for item in resolved_items
        if item.component_id == component["component_id"]
    ]
    if len(selected) != 1:
        _raise(code)
    resolved = selected[0]
    if resolved.path is None or resolved.sha256 is None:
        _raise(code)
    relative = (
        component["snapshot_path"]
        if kind == "official_material"
        else component["job_path"]
    )
    expected_path = pinned_job.path.joinpath(*_relative_parts(relative))
    try:
        if Path(resolved.path) != expected_path:
            _raise(code)
    except (TypeError, ValueError):
        _raise(code)
    descriptor = _open_job_regular(pinned_job, relative, code)
    try:
        metadata = os.fstat(descriptor)
        digest, size = _hash_fd(descriptor, code)
        after = os.fstat(descriptor)
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_mode,
        )
        if (
            size <= 0
            or digest != resolved.sha256
            or digest != component["sha256"]
            or identity
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_mode,
            )
        ):
            _raise(code)
        return _PinnedSource(descriptor, digest, identity)
    except BaseException:
        os.close(descriptor)
        raise


def _extension(media_type: str, *, alpha: bool) -> str:
    if media_type == "image":
        return ".png"
    if media_type == "video":
        return ".mov" if alpha else ".mp4"
    _raise("BROLL_SCHEMA_INVALID")


def _failure_for(kind: str) -> str:
    if kind == "external_stock":
        return "BROLL_DOWNLOAD_REJECTED"
    if kind == "ai_generated":
        return "BROLL_GENERATION_FAILED"
    if kind == "code_generated":
        return "BROLL_RENDER_FAILED"
    return "BROLL_COMPOSITE_FAILED"


def _snapshot_source(
    source: _PinnedSource,
    transaction: _Transaction,
    code: str,
) -> tuple[Path, list[int]]:
    source_fd = source.descriptor
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    destination = transaction.parent_path / ".staging" / str(transaction.record["nonce"]) / "input.snapshot"
    destination_fd: int | None = None
    try:
        before = os.fstat(source_fd)
        os.lseek(source_fd, 0, os.SEEK_SET)
        destination_fd = os.open(
            "input.snapshot",
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            block = os.read(source_fd, 1024 * 1024)
            if not block:
                break
            byte_count += len(block)
            digest.update(block)
            _write_all(destination_fd, block, code)
        os.fsync(destination_fd)
        after = os.fstat(source_fd)
        snapshot_digest, snapshot_size = _hash_fd(destination_fd, code)
        if (
            byte_count <= 0
            or digest.hexdigest() != source.expected_sha256
            or (snapshot_digest, snapshot_size)
            != (source.expected_sha256, byte_count)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_mode,
            )
            != source.identity
        ):
            _raise(code)
        snapshot = os.fstat(destination_fd)
        return destination, [
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            snapshot.st_dev,
            snapshot.st_ino,
        ]
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        if destination_fd is not None:
            try:
                os.close(destination_fd)
            except OSError:
                pass
        os.close(nonce_fd)


def _validate_adapter_result(
    value: object,
    code: str,
    *,
    job_dir: Path,
    request_only_values: tuple[str, ...],
) -> AdapterResult:
    if type(value) is not AdapterResult:
        _raise(code)
    evidence = _validated_json_record(
        _filter_adapter_json(value.invocation_evidence, request_only_values),
        code=code,
        job_dir=job_dir,
    )
    qa = _validated_qa(
        _filter_adapter_json(value.qa, request_only_values),
        code=code,
        job_dir=job_dir,
    )
    return AdapterResult(invocation_evidence=evidence, qa=qa)


def _validate_probe_record(
    value: object,
    artifact_media_type: str,
    artifact_contract: Mapping[str, Any],
    code: str,
) -> dict[str, Any]:
    """Validate a probe record without invoking a producer or reading a path."""

    if type(value) is not dict or set(value) != _PROBE_KEYS:
        _raise(code)
    record = _validated_json_record(value, code=code)
    contract = artifact_contract
    if (
        artifact_media_type not in {"image", "video"}
        or record.get("media_type") != artifact_media_type
        or type(record.get("container")) is not str
        or type(record.get("codec")) is not str
        or type(record.get("pixel_format")) is not str
        or type(record.get("alpha")) is not bool
        or record["alpha"] is not contract["alpha"]
        or type(record.get("width")) is not int
        or record["width"] != contract["width"]
        or type(record.get("height")) is not int
        or record["height"] != contract["height"]
        or type(record.get("frame_count")) is not int
        or record["frame_count"] <= 0
    ):
        _raise(code)
    if artifact_media_type == "image":
        expected_pixel_formats = {"rgba"} if contract["alpha"] else {"rgb24"}
        if (
            record["container"] != "png"
            or record["codec"] != "png"
            or record["pixel_format"] not in expected_pixel_formats
            or record["fps"] is not None
            or record["frame_count"] != 1
            or record["duration"] is not None
        ):
            _raise(code)
        return record
    expected = (
        {("mov", "prores_ks", "yuva444p10le"), ("mov", "prores_ks", "yuva444p12le"), ("mov", "qtrle", "argb")}
        if contract["alpha"]
        else {("mp4", "h264", "yuv420p")}
    )
    if (
        (record["container"], record["codec"], record["pixel_format"])
        not in expected
        or type(record.get("fps")) not in {int, float}
        or not math.isfinite(float(record["fps"]))
        or float(record["fps"]) != float(contract["fps"])
        or type(record.get("duration")) not in {int, float}
        or not math.isfinite(float(record["duration"]))
        or float(record["duration"]) <= 0
    ):
        _raise(code)
    expected_duration = record["frame_count"] / float(record["fps"])
    if abs(float(record["duration"]) - expected_duration) > 1e-6:
        _raise(code)
    return record


def _validated_probe_fd(
    probe: ArtifactProbe,
    descriptor: int,
    artifact_media_type: str,
    artifact_contract: Mapping[str, Any],
    code: str,
) -> Mapping[str, Any]:
    probe_descriptor: int | None = None
    try:
        before = os.fstat(descriptor)
        before_digest, before_size = _hash_fd(descriptor, code)
        probe_descriptor = os.dup(descriptor)
        probe_before = os.fstat(probe_descriptor)
        if (
            probe_before.st_dev,
            probe_before.st_ino,
            probe_before.st_mode,
            probe_before.st_nlink,
        ) != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
        ):
            _raise(code)
        try:
            value = probe.probe(
                Path(f"/dev/fd/{probe_descriptor}"),
                artifact_media_type,
                _freeze(artifact_contract),
            )
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            _raise(code)
        try:
            probe_after = os.fstat(probe_descriptor)
        except OSError:
            _raise(code)
        if (
            probe_after.st_dev,
            probe_after.st_ino,
            probe_after.st_mode,
            probe_after.st_nlink,
        ) != (
            probe_before.st_dev,
            probe_before.st_ino,
            probe_before.st_mode,
            probe_before.st_nlink,
        ):
            _raise(code)
        record = _validate_probe_record(
            value, artifact_media_type, artifact_contract, code
        )
        after = os.fstat(descriptor)
        after_digest, after_size = _hash_fd(descriptor, code)
    except BrollComponentExecutionError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise(code)
    finally:
        if probe_descriptor is not None:
            try:
                os.close(probe_descriptor)
            except OSError:
                pass
    if (
        (before_digest, before_size) != (after_digest, after_size)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        _raise(code)
    return _freeze(record)


def _runtime_contract_record(value, code="BROLL_DEPENDENCY_UNBOUND"):
    try:
        return normalize_contracts(value)
    except (ValueError, TypeError, KeyError):
        _raise(code)


def _bound_runtime_contract(adapter, code="BROLL_DEPENDENCY_UNBOUND"):
    record = _runtime_contract_record(adapter.runtime_contracts, code)
    argv = adapter.argv_template
    if type(argv) is not tuple or any(type(item) is not str for item in argv):
        _raise(code)
    def argument(flag):
        if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv):
            _raise(code)
        return argv[argv.index(flag) + 1]
    raw = argument("--runtime-contracts").encode("utf-8")
    if len(raw) > 65536 or _runtime_contract_record(_strict_json(raw, code), code) != record:
        _raise(code)
    for key, contract in record.items():
        if argument("--" + key) != contract["path"]:
            _raise(code)
    return record


def _base_process_evidence(adapter: ReferenceProcessAdapter) -> dict[str, Any]:
    value = {
        "kind": "code_generated",
        "approved_executor": adapter.approved_executor,
        "adapter_id": adapter.adapter_id,
        "dependency_id": adapter.dependency_id,
        "invocation_type": "reference_process",
        "invocation_id": None,
        "approved_entrypoint": adapter.entrypoint,
        "entrypoint_sha256": adapter.entrypoint_sha256,
        "launcher_sha256": adapter.launcher_sha256,
        "producer_version": adapter.producer_version,
        "brief_sha256": None,
        "argv": (),
        "pid": None,
        "exit_code": None,
        "timed_out": False,
        "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version,
        "stdout_sha256": None,
        "stderr_sha256": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "unresolved_process_group": False,
        "output_job_path": None,
        "output_sha256": None,
    }
    if adapter.runtime_contracts is not None:
        value["runtime_contracts"] = _bound_runtime_contract(adapter)
    if adapter.qualification_registry_path is not None:
        value["qualification_registry"] = {
            "path": adapter.qualification_registry_path,
            "sha256": adapter.qualification_registry_sha256,
        }
    return value


def _validate_probe(adapter: object) -> ArtifactProbe:
    if (
        type(adapter) is not ArtifactProbe
        or type(adapter.probe_id) is not str
        or not adapter.probe_id
        or type(adapter.probe_version) is not str
        or not adapter.probe_version
        or not callable(adapter.probe)
    ):
        _raise("BROLL_PROVIDER_UNCONNECTED")
    return adapter


def _common_code_binding_valid(adapter: object, component: Mapping[str, Any]) -> bool:
    string_fields = (
        "adapter_id",
        "dependency_id",
        "approved_executor",
        "entrypoint",
        "producer_version",
        "primary_renderer",
        "renderer_version",
        "artifact_media_type",
    )
    return (
        all(
            type(getattr(adapter, field)) is str
            and bool(getattr(adapter, field))
            for field in string_fields
        )
        and adapter.dependency_id == component["dependency_id"]
        and adapter.approved_executor == component["executor"]
        and (
            adapter.dependency_id == "hd-talking-head-talkcraft"
            or adapter.entrypoint == component["entrypoint"]
        )
        and adapter.producer_version == component["producer_version"]
        and adapter.primary_renderer == component["primary_renderer"]
        and adapter.renderer_version == component["renderer_version"]
        and adapter.artifact_media_type in {"image", "video"}
        and callable(adapter.brief_loader)
        and (
            type(adapter) is not ReferenceProcessAdapter
            or adapter.media_loader is None
            or callable(adapter.media_loader)
        )
        and type(adapter.request_only_values) is tuple
        and all(
            type(value) is str and bool(value)
            for value in adapter.request_only_values
        )
    )


def _canonical_process_argv(
    *,
    adapter: ReferenceProcessAdapter | None = None,
    binding: Mapping[str, Any] | None = None,
    entrypoint: str | None = None,
    staging_job_path: str | None = None,
    code: str = "BROLL_DEPENDENCY_UNBOUND",
) -> tuple[list[dict[str, Any]], str, list[str] | None]:
    if (adapter is None) == (binding is None):
        _raise(code)
    if adapter is not None:
        normalized: list[dict[str, Any]] = []
        for index, argument in enumerate(adapter.argv_template):
            token = _ARGV_TEMPLATE_TOKENS.get(argument, "literal")
            value: str | None = None
            if token == "literal":
                value = argument.replace(
                    str(adapter.dependency_root), "$DEPENDENCY_ROOT"
                ).replace(str(adapter.launcher), "$LAUNCHER_PATH")
                for value_index, request_only_value in enumerate(
                    adapter.request_only_values
                ):
                    value = value.replace(
                        request_only_value, f"$REQUEST_ONLY[{value_index}]"
                    )
                if Path(argument).is_absolute():
                    value = f"$PATH[{index}]"
            normalized.append(
                {"index": index, "role": token, "value": value}
            )
        template_sha256 = _sha256_bytes(
            _canonical_bytes(list(adapter.argv_template), code)
        )
    else:
        assert binding is not None
        normalized = binding.get("argv_template")
        template_sha256 = binding.get("argv_template_sha256")
        if (
            type(normalized) is not list
            or not normalized
            or type(template_sha256) is not str
            or _HASH.fullmatch(template_sha256) is None
        ):
            _raise(code)
    if (
        type(normalized) is not list
        or any(
            type(item) is not dict
            or set(item) != _ARGV_TEMPLATE_ITEM_KEYS
            or type(item.get("index")) is not int
            or item["index"] != index
            or type(item.get("role")) is not str
            or item["role"] not in {*_ARGV_TEMPLATE_TOKENS.values(), "literal"}
            or (
                item["role"] == "literal"
                and (type(item.get("value")) is not str or not item["value"])
            )
            or (item["role"] != "literal" and item.get("value") is not None)
            for index, item in enumerate(normalized)
        )
        or any(
            sum(item["role"] == token for item in normalized) != 1
            for token in {"launcher", "entrypoint", "brief", "output"}
        )
        or sum(item["role"] == "media_manifest" for item in normalized)
        not in {0, 1}
    ):
        _raise(code)
    if entrypoint is None and staging_job_path is None:
        return normalized, template_sha256, None
    if (
        type(entrypoint) is not str
        or not entrypoint
        or type(staging_job_path) is not str
        or not staging_job_path
    ):
        _raise(code)
    evidence_values = {
        "launcher": "$LAUNCHER",
        "entrypoint": f"$DEPENDENCY/{entrypoint}",
        "brief": "$JOB/brief.json",
        "output": f"$JOB/{staging_job_path}",
        "media_manifest": "$JOB/reference-media-manifest.json",
    }
    evidence = [
        item["value"]
        if item["role"] == "literal"
        else evidence_values[item["role"]]
        for item in normalized
    ]
    return normalized, template_sha256, evidence


def _validate_code_adapter(
    adapter: object,
    component: Mapping[str, Any],
) -> ReferenceProcessAdapter | SkillInvocationAdapter:
    dependency_id = component["dependency_id"]
    expected = _DEPENDENCY_CONTRACTS.get(dependency_id)
    expected_type = (
        ReferenceProcessAdapter
        if expected is not None and expected[0] == "reference_adapter"
        else SkillInvocationAdapter
    )
    if expected is None or type(adapter) is not expected_type:
        _raise("BROLL_DEPENDENCY_UNBOUND")
    if dependency_id == "hd-talking-head-semantic-state" and adapter.runtime_contracts is None:
        _raise("BROLL_DEPENDENCY_UNBOUND")
    if type(adapter) is ReferenceProcessAdapter and adapter.runtime_contracts is not None:
        _bound_runtime_contract(adapter)
    if not _common_code_binding_valid(adapter, component):
        _raise("BROLL_DEPENDENCY_UNBOUND")
    # Reuse the same single-master policy as visual_direction. The upstream
    # project name does not determine its renderer (html-video also has Remotion).
    from .visual_plan import _load_router_module

    try:
        policy = _load_router_module()
        qualification = None
        if type(adapter) is ReferenceProcessAdapter and (
            adapter.qualification_registry_path is not None
            or adapter.qualification_registry_sha256 is not None
        ):
            if (
                type(adapter.qualification_registry_path) is not str
                or not adapter.qualification_registry_path
                or type(adapter.qualification_registry_sha256) is not str
                or _HASH.fullmatch(adapter.qualification_registry_sha256) is None
            ):
                _raise("BROLL_DEPENDENCY_UNBOUND")
            qualification = {
                "path": adapter.qualification_registry_path,
                "sha256": adapter.qualification_registry_sha256,
            }
        if dependency_id == "hd-talking-head-talkcraft":
            if qualification is None:
                _raise("BROLL_DEPENDENCY_UNBOUND")
            from . import talkcraft_contract

            registry_relative = PurePosixPath(qualification["path"])
            if (
                registry_relative.is_absolute()
                or not registry_relative.parts
                or any(part in {"", ".", ".."} for part in registry_relative.parts)
                or registry_relative.as_posix() != qualification["path"]
            ):
                _raise("BROLL_DEPENDENCY_UNBOUND")
            registry_path = adapter.dependency_root.joinpath(
                *registry_relative.parts
            )
            registry_bytes = registry_path.read_bytes()
            if _sha256_bytes(registry_bytes) != qualification["sha256"]:
                _raise("BROLL_DEPENDENCY_UNBOUND")
            registry = talkcraft_contract.load_card_registry(registry_path)
            prefix = "hd-talking-head/talkcraft/"
            template_id = component.get("template_id")
            card_id = (
                template_id[len(prefix):]
                if type(template_id) is str and template_id.startswith(prefix)
                else None
            )
            card = next(
                (item for item in registry["cards"] if item["card_id"] == card_id),
                None,
            )
            production = card.get("production") if type(card) is dict else None
            if (
                type(production) is not dict
                or production.get("status") != "qualified"
                or component.get("entrypoint") != production.get("derived_entrypoint")
                or component.get("source_entrypoint") != production.get("derived_entrypoint")
                or component.get("source_sha256") != production.get("implementation_sha256")
                or component.get("producer_version") != production.get("adapter_version")
                or component.get("verification_id") != production.get("qualification_id")
            ):
                _raise("BROLL_DEPENDENCY_UNBOUND")
            policy.validate_template_binding(component)
        elif qualification is None:
            policy.validate_template_binding(component)
        else:
            policy.validate_template_binding(
                component, qualification_registry=qualification
            )
    except (OSError, ImportError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        _raise("BROLL_DEPENDENCY_UNBOUND", evidence={"template_policy": str(exc)})
    if type(adapter) is SkillInvocationAdapter:
        if not callable(adapter.invoker):
            _raise("BROLL_DEPENDENCY_UNBOUND")
        return adapter

    if not isinstance(adapter.dependency_root, Path) or not isinstance(
        adapter.launcher, Path
    ):
        _raise("BROLL_DEPENDENCY_UNBOUND")
    root = Path(adapter.dependency_root)
    launcher = Path(adapter.launcher)
    if (
        type(adapter.entrypoint_sha256) is not str
        or _HASH.fullmatch(adapter.entrypoint_sha256) is None
        or type(adapter.launcher_sha256) is not str
        or _HASH.fullmatch(adapter.launcher_sha256) is None
        or type(adapter.argv_template) is not tuple
        or not adapter.argv_template
        or any(type(argument) is not str or not argument for argument in adapter.argv_template)
        or adapter.argv_template.count("{launcher}") != 1
        or adapter.argv_template.count("{entrypoint}") != 1
        or adapter.argv_template.count("{brief_path}") != 1
        or adapter.argv_template.count("{output_path}") != 1
        or adapter.argv_template.count("{media_manifest_fd}")
        != (1 if adapter.media_loader is not None else 0)
        or any(
            "{" in argument or "}" in argument
            for argument_index, argument in enumerate(adapter.argv_template)
            if argument
            not in {
                "{launcher}", "{entrypoint}", "{brief_path}",
                "{output_path}", "{media_manifest_fd}",
            }
            and not (adapter.runtime_contracts is not None
                     and argument_index == adapter.argv_template.index("--runtime-contracts") + 1)
        )
        or type(adapter.timeout_seconds) not in {int, float}
        or not math.isfinite(float(adapter.timeout_seconds))
        or adapter.timeout_seconds <= 0
        or adapter.timeout_seconds > _MAX_TIMEOUT_SECONDS
        or type(adapter.self_contained_wrapper) is not bool
        or adapter.self_contained_wrapper is not True
        or not root.is_absolute()
        or not launcher.is_absolute()
    ):
        _raise("BROLL_DEPENDENCY_UNBOUND")
    entry = PurePosixPath(adapter.entrypoint)
    if (
        entry.is_absolute()
        or not entry.parts
        or any(part in {"", ".", ".."} for part in entry.parts)
    ):
        _raise("BROLL_DEPENDENCY_UNBOUND")
    if ".." in root.parts or not root.anchor:
        _raise("BROLL_DEPENDENCY_UNBOUND")
    approved_entrypoint = str(root.joinpath(*entry.parts))
    approved_launcher = str(launcher)
    launcher_contract_indices = {
        index
        for index, argument in enumerate(adapter.argv_template)
        if index > 0
        and argument == approved_launcher
        and adapter.argv_template[index - 1] == "--node"
        and adapter.runtime_contracts is not None
        and adapter.runtime_contracts.get("node", {}).get("path")
        == approved_launcher
    }
    if any(
        argument == approved_entrypoint
        or (argument == approved_launcher and index not in launcher_contract_indices)
        for index, argument in enumerate(adapter.argv_template)
    ):
        _raise("BROLL_DEPENDENCY_UNBOUND")
    return adapter


def _validate_kind_adapter(
    adapter: object, component: Mapping[str, Any]
) -> KindAdapter:
    if type(adapter) is not KindAdapter:
        _raise("BROLL_PROVIDER_UNCONNECTED")
    required_ai = component["kind"] == "ai_generated"
    string_fields = (
        "kind",
        "approved_executor",
        "adapter_id",
        "adapter_version",
        "artifact_media_type",
    )
    if (
        any(
            type(getattr(adapter, field)) is not str
            or not getattr(adapter, field)
            for field in string_fields
        )
        or adapter.kind != component["kind"]
        or adapter.approved_executor != component["executor"]
        or adapter.artifact_media_type not in {"image", "video"}
        or not callable(adapter.invoke)
        or type(adapter.request_only_values) is not tuple
        or any(
            type(value) is not str or not value
            for value in adapter.request_only_values
        )
        or (
            required_ai
            and (
                type(adapter.provider) is not str
                or not adapter.provider
                or type(adapter.model) is not str
                or not adapter.model
                or type(adapter.endpoint_id) is not str
                or not adapter.endpoint_id
                or adapter.provider != component["provider"]
                or adapter.model != component["model"]
                or adapter.endpoint_id != component["endpoint_id"]
            )
        )
        or (
            not required_ai
            and any(
                value is not None
                for value in (adapter.provider, adapter.model, adapter.endpoint_id)
            )
        )
    ):
        _raise("BROLL_PROVIDER_UNCONNECTED")
    return adapter


def _hash_fd(descriptor: int, code: str) -> tuple[str, int]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return digest.hexdigest(), size
    except OSError:
        _raise(code)


def _freeze_process_binding(
    adapter: ReferenceProcessAdapter,
) -> _FrozenProcessBinding:
    code = "BROLL_DEPENDENCY_UNBOUND"
    entrypoint = adapter.dependency_root.joinpath(
        *PurePosixPath(adapter.entrypoint).parts
    )
    entrypoint_fd: int | None = None
    launcher_fd: int | None = None
    try:
        current = Path(adapter.dependency_root.anchor)
        for part in adapter.dependency_root.parts[1:]:
            current = current / part
            metadata = os.lstat(current)
            if not stat.S_ISDIR(metadata.st_mode):
                _raise(code)
        current = adapter.dependency_root
        for part in PurePosixPath(adapter.entrypoint).parts[:-1]:
            current = current / part
            metadata = os.lstat(current)
            if not stat.S_ISDIR(metadata.st_mode):
                _raise(code)
        current = Path(adapter.launcher.anchor)
        for part in adapter.launcher.parts[1:-1]:
            current = current / part
            metadata = os.lstat(current)
            if not stat.S_ISDIR(metadata.st_mode):
                _raise(code)
        entrypoint_fd = os.open(
            entrypoint,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        launcher_fd = os.open(
            adapter.launcher,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        entry_stat = os.fstat(entrypoint_fd)
        launcher_stat = os.fstat(launcher_fd)
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or entry_stat.st_nlink != 1
            or not stat.S_ISREG(launcher_stat.st_mode)
            or launcher_stat.st_nlink != 1
            or _hash_fd(entrypoint_fd, code)
            != (adapter.entrypoint_sha256, entry_stat.st_size)
            or entry_stat.st_size <= 0
            or _hash_fd(launcher_fd, code)
            != (adapter.launcher_sha256, launcher_stat.st_size)
            or launcher_stat.st_size <= 0
        ):
            _raise(code)
        return _FrozenProcessBinding(
            adapter=adapter,
            entrypoint_fd=entrypoint_fd,
            launcher_fd=launcher_fd,
            entrypoint_identity=(
                entry_stat.st_dev,
                entry_stat.st_ino,
                entry_stat.st_mode,
                entry_stat.st_size,
            ),
            launcher_identity=(
                launcher_stat.st_dev,
                launcher_stat.st_ino,
                launcher_stat.st_mode,
                launcher_stat.st_size,
            ),
        )
    except BrollComponentExecutionError:
        for descriptor in (entrypoint_fd, launcher_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise
    except OSError:
        for descriptor in (entrypoint_fd, launcher_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        _raise(code)


def _freeze_qualification_registry(
    adapter: ReferenceProcessAdapter,
) -> _FrozenQualificationRegistry:
    """Pin one configured Skill-relative candidate registry by FD and identity."""
    code = "BROLL_DEPENDENCY_UNBOUND"
    value = adapter.qualification_registry_path
    expected_sha256 = adapter.qualification_registry_sha256
    if (
        type(value) is not str
        or not value
        or type(expected_sha256) is not str
        or _HASH.fullmatch(expected_sha256) is None
    ):
        _raise(code)
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        _raise(code)
    root = adapter.dependency_root
    descriptor: int | None = None
    try:
        current = Path(root.anchor)
        for part in root.parts[1:]:
            current = current / part
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                _raise(code)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                _raise(code)
        path = root.joinpath(*relative.parts)
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or _hash_fd(descriptor, code)
            != (expected_sha256, metadata.st_size)
        ):
            _raise(code)
        return _FrozenQualificationRegistry(
            path=path,
            expected_sha256=expected_sha256,
            descriptor=descriptor,
            identity=(
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
            ),
        )
    except BrollComponentExecutionError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _raise(code)


def _verify_frozen_qualification_registry(
    frozen: _FrozenQualificationRegistry,
) -> None:
    code = "BROLL_DEPENDENCY_UNBOUND"
    try:
        visible = os.lstat(frozen.path)
        opened = os.fstat(frozen.descriptor)
    except OSError:
        _raise(code)
    visible_identity = (
        visible.st_dev,
        visible.st_ino,
        visible.st_mode,
        visible.st_size,
    )
    opened_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_mode,
        opened.st_size,
    )
    if (
        visible_identity != frozen.identity
        or opened_identity != frozen.identity
        or visible.st_nlink != 1
        or opened.st_nlink != 1
        or _hash_fd(frozen.descriptor, code)[0] != frozen.expected_sha256
    ):
        _raise(code)


def _snapshot_approved_entrypoint(
    binding: _FrozenProcessBinding, nonce_fd: int
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "approved-entrypoint",
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        os.lseek(binding.entrypoint_fd, 0, os.SEEK_SET)
        while True:
            block = os.read(binding.entrypoint_fd, 1024 * 1024)
            if not block:
                break
            _write_all(descriptor, block, "BROLL_DEPENDENCY_UNBOUND")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = os.open(
            "approved-entrypoint",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=nonce_fd,
        )
        if _hash_fd(descriptor, "BROLL_DEPENDENCY_UNBOUND") != (
            binding.adapter.entrypoint_sha256,
            binding.entrypoint_identity[3],
        ):
            _raise("BROLL_DEPENDENCY_UNBOUND")
        result = descriptor
        descriptor = None
        return result
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise("BROLL_DEPENDENCY_UNBOUND")
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _verify_frozen_launcher(binding: _FrozenProcessBinding) -> None:
    adapter = binding.adapter
    try:
        metadata = os.lstat(adapter.launcher)
        opened = os.fstat(binding.launcher_fd)
    except OSError:
        _raise("BROLL_DEPENDENCY_UNBOUND")
    current = (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size)
    if (
        current != binding.launcher_identity
        or (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
        )
        != binding.launcher_identity
        or _hash_fd(binding.launcher_fd, "BROLL_DEPENDENCY_UNBOUND")[0]
        != adapter.launcher_sha256
    ):
        _raise("BROLL_DEPENDENCY_UNBOUND")


def _read_frozen_entrypoint(descriptor: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = bytearray()
        while True:
            block = os.read(descriptor, 64 * 1024)
            if not block:
                break
            payload.extend(block)
            if len(payload) > _MAX_ENTRYPOINT_BYTES:
                _raise("BROLL_DEPENDENCY_UNBOUND")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return bytes(payload)
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise("BROLL_DEPENDENCY_UNBOUND")


def _feed_process_input(
    process: subprocess.Popen[bytes],
    payload: bytes,
    failures: list[BaseException],
) -> None:
    try:
        if process.stdin is None:
            raise OSError("process input pipe is unavailable")
        process.stdin.write(payload)
        process.stdin.flush()
    except BaseException as failure:
        failures.append(failure)
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass


def _group_exists(process_group: int) -> tuple[bool, bool]:
    try:
        os.killpg(process_group, 0)
        return True, False
    except ProcessLookupError:
        return False, False
    except PermissionError:
        return True, True
    except OSError as failure:
        if failure.errno == errno.ESRCH:
            return False, False
        return True, True


def _wait_group_gone(process_group: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exists, denied = _group_exists(process_group)
        if not exists:
            return True
        time.sleep(0.01)
    exists, denied = _group_exists(process_group)
    return not exists and not denied


def _settle_process_group(
    process: subprocess.Popen[bytes], *, parent_was_running: bool
) -> tuple[bool, bool]:
    process_group = process.pid
    exists, denied = _group_exists(process_group)
    if denied:
        return True, False
    if not exists:
        try:
            process.wait(timeout=0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False, False
    descendants_or_parent_terminated = True
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return False, descendants_or_parent_terminated
    except (PermissionError, OSError):
        try:
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return True, descendants_or_parent_terminated
    if parent_was_running:
        try:
            process.wait(timeout=_TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            return True, descendants_or_parent_terminated
    if not _wait_group_gone(process_group, _TERM_GRACE_SECONDS):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError):
            try:
                process.wait(timeout=_KILL_GRACE_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return True, descendants_or_parent_terminated
        try:
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return True, descendants_or_parent_terminated
        except OSError:
            return True, descendants_or_parent_terminated
        if not _wait_group_gone(process_group, _KILL_GRACE_SECONDS):
            return True, descendants_or_parent_terminated
    try:
        process.wait(timeout=_KILL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return True, descendants_or_parent_terminated
    return False, descendants_or_parent_terminated


def _read_process_bounded(
    process: subprocess.Popen[bytes], timeout: float
) -> tuple[bytes, bytes, bool, bool]:
    if process.stdout is None or process.stderr is None:
        return b"", b"", False, True
    streams = {process.stdout.fileno(): bytearray(), process.stderr.fileno(): bytearray()}
    selector = selectors.DefaultSelector()
    for file_descriptor in streams:
        os.set_blocking(file_descriptor, False)
        selector.register(file_descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    timed_out = False
    oversized = False
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _mask in selector.select(min(remaining, 0.05)):
                try:
                    block = os.read(key.fd, 64 * 1024)
                except BlockingIOError:
                    continue
                if block:
                    streams[key.fd].extend(block)
                    if len(streams[key.fd]) > _MAX_PROCESS_OUTPUT_BYTES:
                        oversized = True
                        break
                else:
                    try:
                        selector.unregister(key.fd)
                    except KeyError:
                        pass
            if oversized:
                break
        # Drain only bytes already buffered; descendants must not delay cleanup.
        for _ in range(4):
            ready = selector.select(0)
            if not ready:
                break
            for key, _mask in ready:
                try:
                    block = os.read(key.fd, 64 * 1024)
                except BlockingIOError:
                    continue
                if block:
                    streams[key.fd].extend(block)
                    if len(streams[key.fd]) > _MAX_PROCESS_OUTPUT_BYTES:
                        oversized = True
                else:
                    try:
                        selector.unregister(key.fd)
                    except KeyError:
                        pass
        return (
            bytes(streams[process.stdout.fileno()][:_MAX_PROCESS_OUTPUT_BYTES]),
            bytes(streams[process.stderr.fileno()][:_MAX_PROCESS_OUTPUT_BYTES]),
            timed_out,
            oversized,
        )
    finally:
        selector.close()


def _load_brief(
    job: Any,
    request: ComponentExecutionRequest,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    approval_sha256: str,
    loader: Callable[[Any, Mapping[str, Any], Mapping[str, Any]], bytes],
    code: str,
) -> bytes:
    try:
        brief = loader(job, _freeze(recipe), _freeze(component))
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise(code)
    _approved_unchanged(request, approval_sha256)
    if (
        type(brief) is not bytes
        or not brief
        or len(brief) > _MAX_BRIEF_BYTES
        or _sha256_bytes(brief) != component["brief_sha256"]
    ):
        _raise(code)
    return brief


def _freeze_reference_media(
    *,
    adapter: ReferenceProcessAdapter,
    job: Any,
    pinned_job: _PinnedJob,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    brief: bytes,
    nonce_fd: int,
) -> tuple[int | None, tuple[int, ...]]:
    if adapter.media_loader is None:
        return None, ()
    try:
        requested = adapter.media_loader(
            job, _freeze(recipe), _freeze(component), brief
        )
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise("BROLL_RENDER_FAILED")
    if (
        type(requested) is not tuple
        or any(type(item) is not ReferenceProcessMedia for item in requested)
        or len({item.media_ref for item in requested}) != len(requested)
    ):
        _raise("BROLL_RENDER_FAILED")

    media_fds: list[int] = []
    manifest_fd: int | None = None
    try:
        # Every snapshot stays open until the child exits and is passed through
        # pass_fds.  Reject an impossible manifest before creating partial
        # state; never raise the process or system descriptor limit here.
        soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        required_fds = len(requested) + 8  # media + manifest + parent/child overhead
        if soft_limit != resource.RLIM_INFINITY:
            fd_directory = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
            open_fds = len(os.listdir(fd_directory))
            if open_fds + required_fds >= soft_limit:
                _raise("BROLL_RENDER_FAILED")
        records: list[dict[str, Any]] = []
        # Preflight the actual manifest before creating snapshots.  The old
        # eight-item limit is replaced by the same 4 GiB aggregate budget.
        sizes: list[int] = []
        for item in requested:
            if (
                _IDENTIFIER.fullmatch(item.media_ref) is None
                or _HASH.fullmatch(item.sha256) is None
            ):
                _raise("BROLL_RENDER_FAILED")
            source_fd = _open_job_regular(
                pinned_job, item.job_path, "BROLL_RENDER_FAILED"
            )
            try:
                size = os.fstat(source_fd).st_size
                if not 0 < size <= _MAX_REFERENCE_MEDIA_BYTES:
                    _raise("BROLL_RENDER_FAILED")
                sizes.append(size)
            finally:
                os.close(source_fd)
        if sum(sizes) > _MAX_REFERENCE_MEDIA_TOTAL_BYTES:
            _raise("BROLL_RENDER_FAILED")
        total_bytes = 0
        for index, item in enumerate(requested):
            if (
                _IDENTIFIER.fullmatch(item.media_ref) is None
                or _HASH.fullmatch(item.sha256) is None
            ):
                _raise("BROLL_RENDER_FAILED")
            source_fd = _open_job_regular(
                pinned_job, item.job_path, "BROLL_RENDER_FAILED"
            )
            destination_fd: int | None = None
            try:
                source_before = os.fstat(source_fd)
                if not 0 < source_before.st_size <= _MAX_REFERENCE_MEDIA_BYTES:
                    _raise("BROLL_RENDER_FAILED")
                name = f"reference-media-{index}.snapshot"
                destination_fd = os.open(
                    name,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=nonce_fd,
                )
                digest = hashlib.sha256()
                byte_count = 0
                while True:
                    block = os.read(source_fd, 1024 * 1024)
                    if not block:
                        break
                    byte_count += len(block)
                    total_bytes += len(block)
                    if (byte_count > _MAX_REFERENCE_MEDIA_BYTES
                            or total_bytes > _MAX_REFERENCE_MEDIA_TOTAL_BYTES):
                        _raise("BROLL_RENDER_FAILED")
                    digest.update(block)
                    _write_all(destination_fd, block, "BROLL_RENDER_FAILED")
                os.fsync(destination_fd)
                source_after = os.fstat(source_fd)
                snapshot_sha256, snapshot_bytes = _hash_fd(
                    destination_fd, "BROLL_RENDER_FAILED"
                )
                if (
                    digest.hexdigest() != item.sha256
                    or (snapshot_sha256, snapshot_bytes)
                    != (item.sha256, byte_count)
                    or (
                        source_before.st_dev,
                        source_before.st_ino,
                        source_before.st_mode,
                    )
                    != (
                        source_after.st_dev,
                        source_after.st_ino,
                        source_after.st_mode,
                    )
                ):
                    _raise("BROLL_RENDER_FAILED")
                os.lseek(destination_fd, 0, os.SEEK_SET)
                media_fds.append(destination_fd)
                destination_fd = None
                records.append(
                    {
                        "media_ref": item.media_ref,
                        "fd": media_fds[-1],
                        "sha256": item.sha256,
                        "byte_length": byte_count,
                    }
                )
            finally:
                os.close(source_fd)
                if destination_fd is not None:
                    os.close(destination_fd)

        manifest = {
            "schema_version": "reference-process-media/v1",
            "brief_sha256": _sha256_bytes(brief),
            "media": records,
        }
        manifest_bytes = _canonical_bytes(manifest, "BROLL_RENDER_FAILED") + b"\n"
        write_fd = os.open(
            "reference-media-manifest.json",
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        try:
            _write_all(write_fd, manifest_bytes, "BROLL_RENDER_FAILED")
            os.fsync(write_fd)
        finally:
            os.close(write_fd)
        manifest_fd = os.open(
            "reference-media-manifest.json",
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=nonce_fd,
        )
        return manifest_fd, tuple(media_fds)
    except BaseException:
        if manifest_fd is not None:
            os.close(manifest_fd)
        for descriptor in media_fds:
            os.close(descriptor)
        raise


def _run_reference_process(
    job: Any,
    request: ComponentExecutionRequest,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    approval_sha256: str,
    binding: _FrozenProcessBinding,
    transaction: _Transaction,
    context: AdapterContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    adapter = binding.adapter
    evidence = _base_process_evidence(adapter)
    invocation_id = f"process-{secrets.token_hex(16)}"
    evidence["invocation_id"] = invocation_id
    nonce_fd = _open_recorded_nonce_fd(transaction, "BROLL_RENDER_FAILED")
    approved_entrypoint_fd: int | None = None
    brief_fd: int | None = None
    output_fd: int | None = None
    media_manifest_fd: int | None = None
    media_fds: tuple[int, ...] = ()
    try:
        approved_entrypoint_fd = _snapshot_approved_entrypoint(binding, nonce_fd)
        brief = _load_brief(
            job,
            request,
            recipe,
            component,
            approval_sha256,
            adapter.brief_loader,
            "BROLL_RENDER_FAILED",
        )
        evidence["brief_sha256"] = _sha256_bytes(brief)
        _verify_frozen_launcher(binding)
        write_fd = os.open(
            "brief.json",
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        with os.fdopen(write_fd, "wb") as destination:
            destination.write(brief)
            destination.flush()
            os.fsync(destination.fileno())
        brief_fd = os.open(
            "brief.json",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=nonce_fd,
        )
        output_fd = os.open(
            context.staging_path.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        media_manifest_fd, media_fds = _freeze_reference_media(
            adapter=adapter,
            job=job,
            pinned_job=transaction.job,
            recipe=recipe,
            component=component,
            brief=brief,
            nonce_fd=nonce_fd,
        )
    except BrollComponentExecutionError:
        for descriptor in (
            approved_entrypoint_fd, brief_fd, output_fd,
            media_manifest_fd, *media_fds, nonce_fd,
        ):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise
    except OSError:
        for descriptor in (
            approved_entrypoint_fd, brief_fd, output_fd,
            media_manifest_fd, *media_fds, nonce_fd,
        ):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        _raise("BROLL_RENDER_FAILED", evidence=evidence)
    visible_entrypoint_path = str(
        context.staging_path.parent / "approved-entrypoint"
    )
    entrypoint_path = "-"
    brief_path = f"/dev/fd/{brief_fd}"
    output_path = f"/dev/fd/{output_fd}"
    try:
        frozen_entrypoint = os.fstat(approved_entrypoint_fd)
        visible_entrypoint = os.lstat(visible_entrypoint_path)
    except OSError:
        for descriptor in (
            approved_entrypoint_fd, brief_fd, output_fd,
            media_manifest_fd, *media_fds, nonce_fd,
        ):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _raise("BROLL_DEPENDENCY_UNBOUND")
    if (
        (frozen_entrypoint.st_dev, frozen_entrypoint.st_ino)
        != (visible_entrypoint.st_dev, visible_entrypoint.st_ino)
        or _hash_fd(approved_entrypoint_fd, "BROLL_DEPENDENCY_UNBOUND")[0]
        != adapter.entrypoint_sha256
    ):
        for descriptor in (
            approved_entrypoint_fd, brief_fd, output_fd,
            media_manifest_fd, *media_fds, nonce_fd,
        ):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _raise("BROLL_DEPENDENCY_UNBOUND")
    entrypoint_payload = _read_frozen_entrypoint(approved_entrypoint_fd)
    replacements = {
        "{launcher}": str(adapter.launcher),
        "{entrypoint}": entrypoint_path,
        "{brief_path}": str(brief_path),
        "{output_path}": output_path,
        "{media_manifest_fd}": (
            f"/dev/fd/{media_manifest_fd}"
            if media_manifest_fd is not None
            else ""
        ),
    }
    argv = tuple(replacements.get(argument, argument) for argument in adapter.argv_template)
    _template, _template_sha256, canonical_argv = _canonical_process_argv(
        binding=transaction.adapter_binding,
        entrypoint=adapter.entrypoint,
        staging_job_path=context.staging_job_path,
        code="BROLL_RENDER_FAILED",
    )
    evidence["argv"] = canonical_argv
    process: subprocess.Popen[bytes] | None = None
    input_thread: threading.Thread | None = None
    input_failures: list[BaseException] = []
    try:
        if adapter.runtime_contracts is not None:
            current_runtime = _bound_runtime_contract(adapter, "BROLL_RENDER_FAILED")
            if _canonical_bytes(current_runtime, "BROLL_RENDER_FAILED") != _canonical_bytes(
                transaction.adapter_binding.get("runtime_contracts"), "BROLL_RENDER_FAILED"
            ):
                _raise("BROLL_RENDER_FAILED", evidence=evidence)
        process = subprocess.Popen(
            argv,
            cwd="/",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_PROXY": "*",
                "no_proxy": "*",
                "BROLL_OFFLINE": "1",
                "BROLL_INVOCATION_ID": invocation_id,
            },
            shell=False,
            start_new_session=True,
            pass_fds=(brief_fd, output_fd, *(
                (media_manifest_fd, *media_fds)
                if media_manifest_fd is not None
                else ()
            )),
        )
        evidence["pid"] = process.pid
        input_thread = threading.Thread(
            target=_feed_process_input,
            args=(process, entrypoint_payload, input_failures),
            daemon=True,
        )
        input_thread.start()
        try:
            _verify_frozen_launcher(binding)
        except BrollComponentExecutionError:
            _raise("BROLL_RENDER_FAILED", evidence=evidence)
        stdout, stderr, timed_out, oversized = _read_process_bounded(
            process, float(adapter.timeout_seconds)
        )
        evidence["timed_out"] = timed_out
        parent_was_running = process.poll() is None
        unresolved, terminated = _settle_process_group(
            process, parent_was_running=parent_was_running
        )
        input_thread.join(_KILL_GRACE_SECONDS)
        if input_thread.is_alive():
            unresolved = True
        evidence["unresolved_process_group"] = unresolved
        evidence["descendants_terminated"] = terminated and not timed_out
        evidence["exit_code"] = process.returncode
        evidence["stdout_sha256"] = _sha256_bytes(stdout)
        evidence["stderr_sha256"] = _sha256_bytes(stderr)
        evidence["stdout_bytes"] = len(stdout)
        evidence["stderr_bytes"] = len(stderr)
        try:
            _verify_frozen_launcher(binding)
        except BrollComponentExecutionError:
            _raise("BROLL_RENDER_FAILED", evidence=evidence)
        if (
            unresolved
            or timed_out
            or oversized
            or process.returncode != 0
            or input_failures
        ):
            _raise_reference_failure(adapter, stderr, evidence)
        output_metadata = os.fstat(output_fd)
        visible_output = os.stat(
            context.staging_path.name,
            dir_fd=nonce_fd,
            follow_symlinks=False,
        )
        visible_entrypoint = os.lstat(visible_entrypoint_path)
        if (
            not stat.S_ISREG(output_metadata.st_mode)
            or output_metadata.st_nlink != 1
            or (output_metadata.st_dev, output_metadata.st_ino)
            != (visible_output.st_dev, visible_output.st_ino)
            or (frozen_entrypoint.st_dev, frozen_entrypoint.st_ino)
            != (visible_entrypoint.st_dev, visible_entrypoint.st_ino)
            or _hash_fd(brief_fd, "BROLL_RENDER_FAILED")[0]
            != component["brief_sha256"]
            or _hash_fd(approved_entrypoint_fd, "BROLL_RENDER_FAILED")[0]
            != adapter.entrypoint_sha256
        ):
            _raise("BROLL_RENDER_FAILED", evidence=evidence)
    except BrollComponentExecutionError:
        if process is not None:
            unresolved, terminated = _settle_process_group(
                process, parent_was_running=process.poll() is None
            )
            if unresolved:
                evidence["unresolved_process_group"] = True
            if terminated:
                evidence["descendants_terminated"] = True
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            if process is not None:
                _settle_process_group(
                    process, parent_was_running=process.poll() is None
                )
            raise
        if process is not None:
            unresolved, terminated = _settle_process_group(
                process, parent_was_running=process.poll() is None
            )
            evidence["unresolved_process_group"] = unresolved
            evidence["descendants_terminated"] = terminated
        _raise("BROLL_RENDER_FAILED", evidence=evidence)
    finally:
        if process is not None:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        if input_thread is not None:
            input_thread.join(_KILL_GRACE_SECONDS)
        for descriptor in (
            approved_entrypoint_fd,
            brief_fd,
            output_fd,
            media_manifest_fd,
            *media_fds,
            nonce_fd,
        ):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    _approved_unchanged(request, approval_sha256)
    return evidence, {"passed": True, "checks": ["process_completed"]}


def _run_skill_invocation(
    job: Any,
    request: ComponentExecutionRequest,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    approval_sha256: str,
    adapter: SkillInvocationAdapter,
    context: AdapterContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    brief = _load_brief(
        job,
        request,
        recipe,
        component,
        approval_sha256,
        adapter.brief_loader,
        "BROLL_RENDER_FAILED",
    )
    try:
        result = adapter.invoker(context, brief)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise("BROLL_RENDER_FAILED")
    _approved_unchanged(request, approval_sha256)
    if (
        type(result) is not SkillInvocationResult
        or type(result.invocation_id) is not str
        or _IDENTIFIER.fullmatch(result.invocation_id) is None
    ):
        _raise("BROLL_RENDER_FAILED")
    receipt = _validated_json_record(
        _filter_adapter_json(result.receipt, adapter.request_only_values),
        code="BROLL_RENDER_FAILED",
        job_dir=context.job_dir,
    )
    qa = _validated_qa(
        _filter_adapter_json(result.qa, adapter.request_only_values),
        code="BROLL_RENDER_FAILED",
        job_dir=context.job_dir,
    )
    output_descriptor: int | None = None
    try:
        output_descriptor = os.open(
            context.staging_path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        output_sha256, _output_size = _hash_fd(
            output_descriptor, "BROLL_RENDER_FAILED"
        )
    except OSError:
        _raise("BROLL_RENDER_FAILED")
    finally:
        if output_descriptor is not None:
            os.close(output_descriptor)
    expected_receipt = {
        "schema_version": 1,
        "invocation_id": result.invocation_id,
        "dependency_id": adapter.dependency_id,
        "status": "completed",
        "brief_sha256": _sha256_bytes(brief),
        "staged_output_job_path": context.staging_job_path,
        "output_sha256": output_sha256,
        "producer_version": adapter.producer_version,
        "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version,
    }
    if set(receipt) != _SKILL_RECEIPT_KEYS or receipt != expected_receipt:
        _raise("BROLL_RENDER_FAILED")
    evidence = {
        "kind": "code_generated",
        "approved_executor": adapter.approved_executor,
        "adapter_id": adapter.adapter_id,
        "dependency_id": adapter.dependency_id,
        "invocation_type": "skill_invocation",
        "invocation_id": result.invocation_id,
        "receipt": receipt,
        "approved_entrypoint": adapter.entrypoint,
        "producer_version": adapter.producer_version,
        "brief_sha256": _sha256_bytes(brief),
        "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version,
        "output_job_path": None,
        "output_sha256": None,
    }
    return evidence, qa


def _run_kind_adapter(
    adapter: object,
    context: AdapterContext,
    request: ComponentExecutionRequest,
    code: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    if type(adapter) is not KindAdapter:
        _raise("BROLL_PROVIDER_UNCONNECTED")
    try:
        result = _validate_adapter_result(
            adapter.invoke(context),
            code,
            job_dir=context.job_dir,
            request_only_values=adapter.request_only_values,
        )
    except BrollComponentExecutionError:
        raise
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _raise(code)
    _approved_unchanged(request, context.approval_sha256)
    evidence = {
        "kind": context.kind,
        "approved_executor": adapter.approved_executor,
        "adapter_id": adapter.adapter_id,
        "adapter_version": adapter.adapter_version,
        "adapter_record": copy.deepcopy(result.invocation_evidence),
    }
    if context.kind == "ai_generated":
        evidence.update(
            provider=adapter.provider,
            model=adapter.model,
            endpoint_id=adapter.endpoint_id,
        )
    return evidence, result.qa


_JOURNAL_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "input_sha256",
        "recipe_sha256",
        "segment_id",
        "component_id",
        "strategy_revision",
        "kind",
        "adapter_binding",
        "nonce",
        "nonce_identity",
        "adapter_staging_job_path",
        "staging_job_path",
        "output_job_path",
        "source_sha256",
        "source_identity",
        "output_sha256",
        "byte_count",
        "output_identity",
        "artifact",
    }
)


@dataclass
class _Transaction:
    job: _PinnedJob
    parent_fd: int
    lock_fd: int
    parent_path: Path
    parent_identity: tuple[int, int, int]
    chain_fds: tuple[int, ...]
    chain_checks: tuple[tuple[Path, tuple[int, int, int]], ...]
    journal_name: str
    final_name: str
    record: dict[str, Any]
    recipe: Mapping[str, Any]
    component: Mapping[str, Any]
    input_sha256: str
    artifact_media_type: str
    adapter_binding: Mapping[str, Any]

    def write(self) -> None:
        code = _failure_for(self.record["kind"])
        self.verify_parent(code)
        _validate_transaction_record(self, self.record, code)
        payload = _canonical_bytes(self.record, code) + b"\n"
        temporary = f"{self.journal_name}.next"
        descriptor: int | None = None
        try:
            try:
                existing = os.stat(
                    temporary, dir_fd=self.parent_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                    _raise(code)
                os.unlink(temporary, dir_fd=self.parent_fd)
                os.fsync(self.parent_fd)
            descriptor = os.open(
                temporary,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self.parent_fd,
            )
            _write_all(descriptor, payload, code)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                metadata.st_size != len(payload)
                or _hash_fd(descriptor, code) != (_sha256_bytes(payload), len(payload))
            ):
                _raise(code)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary,
                self.journal_name,
                src_dir_fd=self.parent_fd,
                dst_dir_fd=self.parent_fd,
            )
            os.fsync(self.parent_fd)
            self.verify_parent(code)
        except BrollComponentExecutionError:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                os.unlink(temporary, dir_fd=self.parent_fd)
                os.fsync(self.parent_fd)
            except OSError:
                pass
            raise
        except OSError:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                os.unlink(temporary, dir_fd=self.parent_fd)
            except OSError:
                pass
            _raise(code)

    def close(self) -> None:
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        for descriptor in (self.lock_fd, *reversed(self.chain_fds)):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def verify_parent(self, code: str) -> None:
        self.job.verify(code)
        try:
            opened = os.fstat(self.parent_fd)
            for descriptor, (path, identity) in zip(
                self.chain_fds, self.chain_checks
            ):
                pinned = os.fstat(descriptor)
                visible = os.lstat(path)
                if (
                    not stat.S_ISDIR(pinned.st_mode)
                    or (pinned.st_dev, pinned.st_ino, pinned.st_mode) != identity
                    or (visible.st_dev, visible.st_ino, visible.st_mode) != identity
                ):
                    _raise(code)
        except OSError:
            _raise(code)
        if (
            (opened.st_dev, opened.st_ino, opened.st_mode) != self.parent_identity
        ):
            _raise(code)


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _artifact_from_json(value: object, code: str) -> ComponentArtifact:
    if type(value) is not dict or set(value) != set(ComponentArtifact.__dataclass_fields__):
        _raise(code)
    _validate_json_value(value, code=code)
    if (
        type(value.get("schema_version")) is not int
        or type(value.get("strategy_revision")) is not int
        or type(value.get("z_index")) is not int
        or type(value.get("opacity")) is not float
        or type(value.get("byte_count")) is not int
        or type(value.get("error_code")) is not type(None)
    ):
        _raise(code)
    try:
        return ComponentArtifact(
            **{
                **value,
                "render_window": _freeze(value["render_window"]),
                "safe_zone": _freeze(value["safe_zone"]),
                "artifact_contract": _freeze(value["artifact_contract"]),
                "media_probe": _freeze(value["media_probe"]),
                "invocation_evidence": _freeze(value["invocation_evidence"]),
                "qa": _freeze(value["qa"]),
            }
        )
    except (TypeError, ValueError):
        _raise(code)


def _validate_invocation_evidence(
    value: object,
    *,
    component: Mapping[str, Any],
    binding: Mapping[str, Any],
    adapter_staging_job_path: str,
    output_job_path: str,
    output_sha256: str,
    job_dir: Path,
    code: str,
) -> dict[str, Any]:
    evidence = _validated_json_record(value, code=code, job_dir=job_dir)
    common = {
        "kind": component["kind"],
        "approved_executor": component["executor"],
        "adapter_id": binding["adapter_id"],
        "output_job_path": output_job_path,
        "output_sha256": output_sha256,
        "probe_id": binding["probe_id"],
        "probe_version": binding["probe_version"],
    }
    if any(evidence.get(key) != expected for key, expected in common.items()):
        _raise(code)
    adapter_type = binding["adapter_type"]
    if adapter_type == "kind":
        keys = {
            "kind",
            "approved_executor",
            "adapter_id",
            "adapter_version",
            "adapter_record",
            "output_job_path",
            "output_sha256",
            "probe_id",
            "probe_version",
        }
        if component["kind"] == "ai_generated":
            keys |= {"provider", "model", "endpoint_id"}
        if (
            set(evidence) != keys
            or evidence.get("adapter_version") != binding["adapter_version"]
            or type(evidence.get("adapter_record")) is not dict
        ):
            _raise(code)
        if component["kind"] == "ai_generated" and any(
            evidence.get(key) != component[key]
            for key in ("provider", "model", "endpoint_id")
        ):
            _raise(code)
        return evidence
    if adapter_type == "skill_invocation":
        keys = {
            "kind",
            "approved_executor",
            "adapter_id",
            "dependency_id",
            "invocation_type",
            "invocation_id",
            "receipt",
            "approved_entrypoint",
            "producer_version",
            "brief_sha256",
            "primary_renderer",
            "renderer_version",
            "output_job_path",
            "output_sha256",
            "probe_id",
            "probe_version",
        }
        receipt = evidence.get("receipt")
        if (
            set(evidence) != keys
            or evidence.get("invocation_type") != "skill_invocation"
            or type(evidence.get("invocation_id")) is not str
            or _IDENTIFIER.fullmatch(evidence["invocation_id"]) is None
            or type(receipt) is not dict
            or set(receipt) != _SKILL_RECEIPT_KEYS
            or type(receipt.get("schema_version")) is not int
        ):
            _raise(code)
        expected = {
            "dependency_id": binding["dependency_id"],
            "approved_entrypoint": binding["entrypoint"],
            "producer_version": binding["producer_version"],
            "primary_renderer": binding["primary_renderer"],
            "renderer_version": binding["renderer_version"],
        }
        if any(evidence.get(key) != item for key, item in expected.items()):
            _raise(code)
        if (
            evidence["brief_sha256"] != component["brief_sha256"]
            or type(receipt.get("invocation_id")) is not str
            or type(receipt.get("dependency_id")) is not str
            or type(receipt.get("status")) is not str
            or type(receipt.get("brief_sha256")) is not str
            or type(receipt.get("staged_output_job_path")) is not str
            or type(receipt.get("output_sha256")) is not str
            or type(receipt.get("producer_version")) is not str
            or type(receipt.get("primary_renderer")) is not str
            or type(receipt.get("renderer_version")) is not str
            or _HASH.fullmatch(receipt["brief_sha256"]) is None
            or _HASH.fullmatch(receipt["output_sha256"]) is None
            or receipt["schema_version"] != 1
            or receipt["invocation_id"] != evidence["invocation_id"]
            or receipt["dependency_id"] != binding["dependency_id"]
            or receipt["status"] != "completed"
            or receipt["brief_sha256"] != evidence["brief_sha256"]
            or receipt["output_sha256"] != output_sha256
            or receipt["producer_version"] != binding["producer_version"]
            or receipt["primary_renderer"] != binding["primary_renderer"]
            or receipt["renderer_version"] != binding["renderer_version"]
        ):
            _raise(code)
        return evidence
    if adapter_type != "reference_process":
        _raise(code)
    keys = {
        "kind",
        "approved_executor",
        "adapter_id",
        "dependency_id",
        "invocation_type",
        "invocation_id",
        "approved_entrypoint",
        "entrypoint_sha256",
        "launcher_sha256",
        "producer_version",
        "brief_sha256",
        "argv",
        "pid",
        "exit_code",
        "timed_out",
        "primary_renderer",
        "renderer_version",
        "stdout_sha256",
        "stderr_sha256",
        "stdout_bytes",
        "stderr_bytes",
        "unresolved_process_group",
        "descendants_terminated",
        "output_job_path",
        "output_sha256",
        "probe_id",
        "probe_version",
    }
    expected = {
        "dependency_id": binding["dependency_id"],
        "invocation_type": "reference_process",
        "approved_entrypoint": binding["entrypoint"],
        "entrypoint_sha256": binding["entrypoint_sha256"],
        "launcher_sha256": binding["launcher_sha256"],
        "producer_version": binding["producer_version"],
        "primary_renderer": binding["primary_renderer"],
        "renderer_version": binding["renderer_version"],
        "exit_code": 0,
        "timed_out": False,
        "unresolved_process_group": False,
    }
    if "runtime_contracts" in binding:
        keys.add("runtime_contracts")
        expected["runtime_contracts"] = _runtime_contract_record(binding["runtime_contracts"], code)
    if "qualification_registry" in binding:
        keys.add("qualification_registry")
        expected["qualification_registry"] = binding["qualification_registry"]
    _template, _template_sha256, expected_argv = _canonical_process_argv(
        binding=binding,
        entrypoint=binding["entrypoint"],
        staging_job_path=adapter_staging_job_path,
        code=code,
    )
    if (
        set(evidence) != keys
        or any(evidence.get(key) != item for key, item in expected.items())
        or type(evidence.get("invocation_id")) is not str
        or _IDENTIFIER.fullmatch(evidence["invocation_id"]) is None
        or type(evidence.get("pid")) is not int
        or evidence["pid"] <= 0
        or type(evidence.get("exit_code")) is not int
        or type(evidence.get("timed_out")) is not bool
        or type(evidence.get("unresolved_process_group")) is not bool
        or type(evidence.get("argv")) is not list
        or not evidence["argv"]
        or any(
            type(argument) is not str or not argument
            for argument in evidence["argv"]
        )
        or evidence["argv"] != expected_argv
        or type(evidence.get("descendants_terminated")) is not bool
        or type(evidence.get("stdout_bytes")) is not int
        or evidence["stdout_bytes"] < 0
        or type(evidence.get("stderr_bytes")) is not int
        or evidence["stderr_bytes"] < 0
        or evidence.get("brief_sha256") != component["brief_sha256"]
    ):
        _raise(code)
    for key in ("brief_sha256", "stdout_sha256", "stderr_sha256"):
        if type(evidence.get(key)) is not str or _HASH.fullmatch(evidence[key]) is None:
            _raise(code)
    return evidence


def _validate_replayed_artifact(
    artifact: ComponentArtifact,
    *,
    job: _PinnedJob,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    artifact_media_type: str,
    output_job_path: str,
    input_sha256: str,
    binding: Mapping[str, Any],
    adapter_staging_job_path: str,
    code: str,
) -> None:
    window = component["render_window"]
    rendered_window = _plain_json(artifact.render_window)
    safe_zone = _plain_json(artifact.safe_zone)
    contract_record = _plain_json(artifact.artifact_contract)
    if (
        type(artifact.schema_version) is not int
        or artifact.schema_version != 1
        or artifact.status != "success"
        or artifact.error_code is not None
        or artifact.job_id != job.job_id
        or artifact.segment_id != recipe["segment_id"]
        or artifact.component_id != component["component_id"]
        or artifact.kind != component["kind"]
        or type(artifact.strategy_revision) is not int
        or artifact.strategy_revision != recipe["strategy_revision"]
        or artifact.media_type != artifact_media_type
        or type(rendered_window) is not dict
        or _canonical_bytes(rendered_window, code)
        != _canonical_bytes(window, code)
        or type(artifact.z_index) is not int
        or artifact.z_index != window["z_index"]
        or artifact.layout_slot != window["layout_slot"]
        or type(artifact.opacity) is not float
        or artifact.opacity != window["opacity"]
        or type(safe_zone) is not dict
        or _canonical_bytes(safe_zone, code)
        != _canonical_bytes(window["safe_zone"], code)
        or type(contract_record) is not dict
        or _canonical_bytes(contract_record, code)
        != _canonical_bytes(component["artifact_contract"], code)
        or artifact.source_media_type != component["media_type"]
        or artifact.artifact_media_type != artifact_media_type
        or artifact.job_path != output_job_path
        or type(artifact.status) is not str
        or type(artifact.job_id) is not str
        or type(artifact.segment_id) is not str
        or type(artifact.component_id) is not str
        or type(artifact.kind) is not str
        or type(artifact.media_type) is not str
        or type(artifact.layout_slot) is not str
        or type(artifact.source_media_type) is not str
        or type(artifact.artifact_media_type) is not str
        or type(artifact.input_sha256) is not str
        or _HASH.fullmatch(artifact.input_sha256) is None
        or type(artifact.job_path) is not str
        or artifact.input_sha256 != input_sha256
        or type(artifact.byte_count) is not int
        or artifact.byte_count <= 0
        or type(artifact.output_sha256) is not str
        or _HASH.fullmatch(artifact.output_sha256) is None
    ):
        _raise(code)
    _validate_probe_record(
        _plain_json(artifact.media_probe),
        artifact_media_type,
        component["artifact_contract"],
        code,
    )
    _validated_qa(_plain_json(artifact.qa), code=code)
    _validate_invocation_evidence(
        _plain_json(artifact.invocation_evidence),
        component=component,
        binding=binding,
        adapter_staging_job_path=adapter_staging_job_path,
        output_job_path=output_job_path,
        output_sha256=artifact.output_sha256,
        job_dir=job.path,
        code=code,
    )


def _exact_int_list(value: object, length: int) -> bool:
    return (
        type(value) is list
        and len(value) == length
        and all(type(item) is int for item in value)
    )


def _validate_transaction_record(
    transaction: _Transaction,
    value: object,
    code: str,
) -> ComponentArtifact | None:
    if type(value) is not dict or set(value) != _JOURNAL_KEYS:
        _raise(code)
    _validated_json_record(value, code=code, maximum=1024 * 1024)
    recipe = transaction.recipe
    component = transaction.component
    binding = _plain_json(transaction.adapter_binding)
    expected_output = PurePosixPath(
        "08-visual-assets",
        "components",
        recipe["segment_id"],
        transaction.final_name,
    ).as_posix()
    nonce = value.get("nonce")
    nonce_pattern = (
        rf"{re.escape(component['component_id'])}-"
        rf"r{recipe['strategy_revision']}\.[0-9a-f]{{32}}"
    )
    extension = Path(transaction.final_name).suffix
    nonce_root = PurePosixPath(
        "08-visual-assets",
        "components",
        recipe["segment_id"],
        ".staging",
        str(nonce),
    )
    expected_adapter_staging = (nonce_root / f"output{extension}").as_posix()
    expected_publish_staging = (
        nonce_root / f"publish.snapshot{extension}"
    ).as_posix()
    expected_source_sha = (
        component["sha256"] if component["kind"] in _MATERIAL_KINDS else None
    )
    identity = {
        "schema_version": 2,
        "input_sha256": transaction.input_sha256,
        "recipe_sha256": _sha256_bytes(_canonical_bytes(recipe, code)),
        "segment_id": recipe["segment_id"],
        "component_id": component["component_id"],
        "strategy_revision": recipe["strategy_revision"],
        "kind": component["kind"],
        "adapter_binding": binding,
        "adapter_staging_job_path": expected_adapter_staging,
        "staging_job_path": expected_publish_staging,
        "output_job_path": expected_output,
        "source_sha256": expected_source_sha,
    }
    if (
        type(value.get("schema_version")) is not int
        or type(value.get("strategy_revision")) is not int
        or type(nonce) is not str
        or re.fullmatch(nonce_pattern, nonce) is None
        or any(value.get(key) != expected for key, expected in identity.items())
        or _canonical_bytes(value.get("adapter_binding"), code)
        != _canonical_bytes(binding, code)
        or type(value.get("state")) is not str
        or value["state"]
        not in {"planned", "running", "complete", "publishing", "published"}
    ):
        _raise(code)
    state = value["state"]
    if state == "planned":
        if any(
            value.get(key) is not None
            for key in (
                "nonce_identity",
                "source_identity",
                "output_sha256",
                "byte_count",
                "output_identity",
                "artifact",
            )
        ):
            _raise(code)
        return None
    if not _exact_int_list(value.get("nonce_identity"), 2):
        _raise(code)
    source_identity = value.get("source_identity")
    if component["kind"] in _MATERIAL_KINDS:
        if source_identity is None:
            if state != "running":
                _raise(code)
        elif not _exact_int_list(source_identity, 7):
            _raise(code)
    elif source_identity is not None:
        _raise(code)
    if state == "running":
        if any(
            value.get(key) is not None
            for key in ("output_sha256", "byte_count", "output_identity", "artifact")
        ):
            _raise(code)
        return None
    if (
        type(value.get("output_sha256")) is not str
        or _HASH.fullmatch(value["output_sha256"]) is None
        or type(value.get("byte_count")) is not int
        or value["byte_count"] <= 0
        or type(value.get("artifact")) is not dict
    ):
        _raise(code)
    artifact = _artifact_from_json(value["artifact"], code)
    _validate_replayed_artifact(
        artifact,
        job=transaction.job,
        recipe=recipe,
        component=component,
        artifact_media_type=transaction.artifact_media_type,
        output_job_path=expected_output,
        input_sha256=transaction.input_sha256,
        binding=binding,
        adapter_staging_job_path=value["adapter_staging_job_path"],
        code=code,
    )
    if (
        artifact.output_sha256 != value["output_sha256"]
        or artifact.byte_count != value["byte_count"]
    ):
        _raise(code)
    if binding["adapter_type"] == "skill_invocation":
        evidence = _plain_json(artifact.invocation_evidence)
        if (
            evidence["receipt"]["staged_output_job_path"]
            != value["adapter_staging_job_path"]
        ):
            _raise(code)
    if state == "complete":
        if value.get("output_identity") is not None:
            _raise(code)
    elif state == "publishing":
        if value.get("output_identity") is not None and not _exact_int_list(
            value.get("output_identity"), 2
        ):
            _raise(code)
    elif not _exact_int_list(value.get("output_identity"), 2):
        _raise(code)
    return artifact


def _adapter_binding_record(
    adapter: KindAdapter | ReferenceProcessAdapter | SkillInvocationAdapter,
    probe: ArtifactProbe,
) -> dict[str, Any]:
    if type(adapter) is KindAdapter:
        value = {
            "adapter_type": "kind",
            "adapter_id": adapter.adapter_id,
            "adapter_version": adapter.adapter_version,
            "approved_executor": adapter.approved_executor,
            "artifact_media_type": adapter.artifact_media_type,
        }
    elif type(adapter) is ReferenceProcessAdapter:
        normalized_template, template_sha256, _evidence = (
            _canonical_process_argv(adapter=adapter)
        )
        value = {
            "adapter_type": "reference_process",
            "adapter_id": adapter.adapter_id,
            "dependency_id": adapter.dependency_id,
            "approved_executor": adapter.approved_executor,
            "entrypoint": adapter.entrypoint,
            "entrypoint_sha256": adapter.entrypoint_sha256,
            "launcher_sha256": adapter.launcher_sha256,
            "producer_version": adapter.producer_version,
            "primary_renderer": adapter.primary_renderer,
            "renderer_version": adapter.renderer_version,
            "artifact_media_type": adapter.artifact_media_type,
            "self_contained_wrapper": adapter.self_contained_wrapper,
            "argv_template": normalized_template,
            "argv_template_sha256": template_sha256,
        }
        if adapter.runtime_contracts is not None:
            value["runtime_contracts"] = _bound_runtime_contract(adapter)
        if adapter.qualification_registry_path is not None:
            value["qualification_registry"] = {
                "path": adapter.qualification_registry_path,
                "sha256": adapter.qualification_registry_sha256,
            }
    else:
        value = {
            "adapter_type": "skill_invocation",
            "adapter_id": adapter.adapter_id,
            "dependency_id": adapter.dependency_id,
            "approved_executor": adapter.approved_executor,
            "entrypoint": adapter.entrypoint,
            "producer_version": adapter.producer_version,
            "primary_renderer": adapter.primary_renderer,
            "renderer_version": adapter.renderer_version,
            "artifact_media_type": adapter.artifact_media_type,
        }
    value["probe_id"] = probe.probe_id
    value["probe_version"] = probe.probe_version
    return value


def _open_output_chain(
    job: _PinnedJob,
    parts: tuple[str, ...],
    *,
    create: bool,
    code: str,
) -> tuple[tuple[int, ...], tuple[tuple[Path, tuple[int, int, int]], ...]] | None:
    job.verify(code)
    descriptors: list[int] = []
    checks: list[tuple[Path, tuple[int, int, int]]] = []
    parent = os.dup(job.root_fd)
    current = job.path
    try:
        for part in parts:
            try:
                visible = os.stat(part, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    os.close(parent)
                    return None
                os.mkdir(part, mode=0o700, dir_fd=parent)
                os.fsync(parent)
                visible = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(visible.st_mode):
                _raise(code)
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            opened = os.fstat(child)
            identity = (opened.st_dev, opened.st_ino, opened.st_mode)
            if identity != (visible.st_dev, visible.st_ino, visible.st_mode):
                os.close(child)
                _raise(code)
            descriptors.append(child)
            current = current / part
            checks.append((current, identity))
            os.close(parent)
            parent = os.dup(child)
        os.close(parent)
        job.verify(code)
        return tuple(descriptors), tuple(checks)
    except BrollComponentExecutionError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(parent)
        except OSError:
            pass
        raise
    except OSError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(parent)
        except OSError:
            pass
        _raise(code)


def _open_regular_at(
    parent_fd: int,
    name: str,
    code: str,
    *,
    writable: bool = False,
    create: bool = False,
) -> int | None:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            return None
        before = None
    if before is not None and (
        not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
    ):
        _raise(code)
    flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(
        os, "O_NONBLOCK", 0
    ) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if create and before is None:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
    except FileExistsError:
        if not create:
            _raise(code)
        return _open_regular_at(
            parent_fd, name, code, writable=writable, create=False
        )
    except OSError:
        _raise(code)
    metadata = os.fstat(descriptor)
    try:
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        os.close(descriptor)
        _raise(code)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink)
        != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink)
        or (
            before is not None
            and (before.st_dev, before.st_ino, before.st_mode, before.st_nlink)
            != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink)
        )
    ):
        os.close(descriptor)
        _raise(code)
    return descriptor


def _open_component_lock(
    parent_fd: int, name: str, code: str, *, create: bool
) -> int | None:
    descriptor = _open_regular_at(
        parent_fd, name, code, writable=True, create=create
    )
    if descriptor is None:
        return None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError:
        os.close(descriptor)
        _raise(code)
    return descriptor


def _read_canonical_record_at(
    parent_fd: int, name: str, code: str
) -> dict[str, Any] | None:
    descriptor = _open_regular_at(parent_fd, name, code)
    if descriptor is None:
        return None
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_size > 1024 * 1024:
            _raise(code)
        raw = b""
        while True:
            block = os.read(descriptor, 64 * 1024)
            if not block:
                break
            raw += block
            if len(raw) > 1024 * 1024:
                _raise(code)
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        os.close(descriptor)
    value = _strict_json(raw, code)
    if raw != _canonical_bytes(value, code) + b"\n" or set(value) != _JOURNAL_KEYS:
        _raise(code)
    return value


def _read_published_record_at(parent_fd: int, name: str, code: str) -> dict[str, Any]:
    """Read without recovery; caller must hold the lock and validate identities."""
    current = _read_canonical_record_at(parent_fd, name, code)
    following = _read_canonical_record_at(parent_fd, f"{name}.next", code)
    if current is None or current.get("state") != "published" or following is not None:
        _raise(code)
    return current


def _read_transaction(parent_fd: int, name: str, code: str) -> dict[str, Any] | None:
    next_name = f"{name}.next"
    current = _read_canonical_record_at(parent_fd, name, code)
    following = _read_canonical_record_at(parent_fd, next_name, code)
    if following is None:
        return current
    try:
        if current is None:
            os.replace(
                next_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            return following
        os.unlink(next_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return current
    except OSError:
        _raise(code)


def _remove_tree_at(
    parent_fd: int,
    name: str,
    expected_identity: tuple[int, int] | None,
    code: str,
) -> None:
    descriptor: int | None = None
    try:
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        _raise(code)
    if not stat.S_ISDIR(visible.st_mode) or (
        expected_identity is not None
        and (visible.st_dev, visible.st_ino) != expected_identity
    ):
        _raise(code)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
            _raise(code)
        for child in os.listdir(descriptor):
            child_metadata = os.stat(
                child, dir_fd=descriptor, follow_symlinks=False
            )
            if stat.S_ISDIR(child_metadata.st_mode):
                _remove_tree_at(descriptor, child, None, code)
            elif stat.S_ISREG(child_metadata.st_mode) and child_metadata.st_nlink == 1:
                os.unlink(child, dir_fd=descriptor)
            else:
                _raise(code)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BrollComponentExecutionError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _raise(code)


def _retire_empty_planned_nonce(
    parent_fd: int, name: str, code: str
) -> None:
    descriptor: int | None = None
    try:
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        _raise(code)
    if (
        not stat.S_ISDIR(visible.st_mode)
        or stat.S_IMODE(visible.st_mode) != 0o700
        or visible.st_nlink != 2
    ):
        _raise(code)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink)
            != (visible.st_dev, visible.st_ino, visible.st_mode, visible.st_nlink)
            or os.listdir(descriptor)
        ):
            _raise(code)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_nlink,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_nlink,
        ):
            _raise(code)
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _cleanup_recorded_nonce(
    transaction: _Transaction, code: str
) -> None:
    record = transaction.record
    relative = record.get("staging_job_path")
    identity = record.get("nonce_identity")
    nonce = record.get("nonce")
    if relative is None and identity is None and nonce is None:
        return
    if (
        type(relative) is not str
        or type(nonce) is not str
        or (
            identity is not None
            and not _exact_int_list(identity, 2)
        )
    ):
        _raise(code)
    if not PurePosixPath(relative).is_relative_to(
        PurePosixPath("08-visual-assets", "components", record["segment_id"], ".staging", nonce)
    ):
        _raise(code)
    try:
        staging_fd = os.open(
            ".staging",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=transaction.parent_fd,
        )
    except FileNotFoundError:
        return
    except OSError:
        _raise(code)
    try:
        expected = tuple(identity) if identity is not None else None
        if expected is None:
            _retire_empty_planned_nonce(staging_fd, nonce, code)
        else:
            _remove_tree_at(staging_fd, nonce, expected, code)
    finally:
        os.close(staging_fd)


def _crash_checkpoint(_name: str) -> None:
    """Internal no-op used by subprocess crash-recovery tests."""


def _try_open_recorded_nonce_fd(
    transaction: _Transaction, code: str
) -> int | None:
    record = transaction.record
    nonce = record.get("nonce")
    identity = record.get("nonce_identity")
    expected_nonce = (
        rf"{re.escape(str(record.get('component_id')))}-"
        rf"r{record.get('strategy_revision')}\.[0-9a-f]{{32}}"
    )
    if (
        type(nonce) is not str
        or re.fullmatch(expected_nonce, nonce) is None
        or type(identity) is not list
        or len(identity) != 2
        or any(type(item) is not int for item in identity)
    ):
        _raise(code)
    try:
        staging_fd = os.open(
            ".staging",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=transaction.parent_fd,
        )
        try:
            nonce_fd = os.open(
                nonce,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=staging_fd,
            )
        finally:
            os.close(staging_fd)
        metadata = os.fstat(nonce_fd)
        if [metadata.st_dev, metadata.st_ino] != identity:
            os.close(nonce_fd)
            _raise(code)
        return nonce_fd
    except FileNotFoundError:
        return None
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)


def _open_recorded_nonce_fd(transaction: _Transaction, code: str) -> int:
    descriptor = _try_open_recorded_nonce_fd(transaction, code)
    if descriptor is None:
        _raise(code)
    return descriptor


def _open_nonce_output(
    transaction: _Transaction, job_path: str, code: str
) -> int:
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    try:
        expected_parent = PurePosixPath(
            "08-visual-assets",
            "components",
            transaction.record["segment_id"],
            ".staging",
            transaction.record["nonce"],
        )
        path = PurePosixPath(job_path)
        if path.parent != expected_parent:
            _raise(code)
        descriptor = _open_regular_at(nonce_fd, path.name, code)
        if descriptor is None:
            _raise(code)
        return descriptor
    finally:
        os.close(nonce_fd)


def _create_adapter_output_fd(
    transaction: _Transaction, code: str
) -> int:
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    path = PurePosixPath(transaction.record["adapter_staging_job_path"])
    try:
        return os.open(
            path.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
    except OSError:
        _raise(code)
    finally:
        os.close(nonce_fd)


def _open_source_snapshot_fd(transaction: _Transaction, code: str) -> int:
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    try:
        descriptor = _open_regular_at(nonce_fd, "input.snapshot", code)
        if descriptor is None:
            _raise(code)
        metadata = os.fstat(descriptor)
        identity = transaction.record["source_identity"]
        if (
            not _exact_int_list(identity, 7)
            or (metadata.st_dev, metadata.st_ino) != (identity[5], identity[6])
        ):
            os.close(descriptor)
            _raise(code)
        return descriptor
    finally:
        os.close(nonce_fd)


def _create_publish_snapshot(
    transaction: _Transaction,
    source_fd: int,
    code: str,
) -> tuple[Path, str, int]:
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    destination_fd: int | None = None
    path = PurePosixPath(transaction.record["staging_job_path"])
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _raise(code)
        before_digest, before_size = _hash_fd(source_fd, code)
        destination_fd = os.open(
            path.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=nonce_fd,
        )
        os.lseek(source_fd, 0, os.SEEK_SET)
        while True:
            block = os.read(source_fd, 1024 * 1024)
            if not block:
                break
            _write_all(destination_fd, block, code)
        os.fsync(destination_fd)
        snapshot_digest, snapshot_size = _hash_fd(destination_fd, code)
        snapshot = os.fstat(destination_fd)
        after = os.fstat(source_fd)
        after_digest, after_size = _hash_fd(source_fd, code)
        if (
            before_size <= 0
            or (snapshot_digest, snapshot_size) != (before_digest, before_size)
            or (after_digest, after_size) != (before_digest, before_size)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or snapshot.st_ino == before.st_ino
            or snapshot.st_nlink != 1
        ):
            _raise(code)
        return (
            transaction.job.path.joinpath(*path.parts),
            snapshot_digest,
            snapshot_size,
        )
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        if destination_fd is not None:
            try:
                os.close(destination_fd)
            except OSError:
                pass
        os.close(nonce_fd)


def _validate_final_at(
    transaction: _Transaction, digest: str, byte_count: int, code: str
) -> tuple[int, int]:
    transaction.verify_parent(code)
    descriptor = _open_regular_at(
        transaction.parent_fd, transaction.final_name, code
    )
    if descriptor is None:
        _raise(code)
    try:
        before = os.fstat(descriptor)
        if stat.S_IMODE(before.st_mode) != 0o600:
            _raise(code)
        actual_digest, actual_size = _hash_fd(descriptor, code)
        after = os.fstat(descriptor)
        visible = os.stat(
            transaction.final_name,
            dir_fd=transaction.parent_fd,
            follow_symlinks=False,
        )
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or stat.S_IMODE(after.st_mode) != 0o600
            or stable
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            or (
                visible.st_dev,
                visible.st_ino,
                visible.st_mode,
                visible.st_nlink,
                visible.st_size,
                visible.st_mtime_ns,
            )
            != stable
        ):
            _raise(code)
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if actual_digest != digest or actual_size != byte_count:
        _raise(code)
    return after.st_dev, after.st_ino


def _rollback_owned_final(
    transaction: _Transaction, identity: tuple[int, int] | None
) -> bool:
    if identity is None:
        return True
    try:
        visible = os.stat(
            transaction.final_name,
            dir_fd=transaction.parent_fd,
            follow_symlinks=False,
        )
        if (visible.st_dev, visible.st_ino) != identity:
            return False
        os.unlink(transaction.final_name, dir_fd=transaction.parent_fd)
        os.fsync(transaction.parent_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _publish_transaction(
    transaction: _Transaction,
    staging: Path,
    digest: str,
    byte_count: int,
    code: str,
) -> tuple[Path, tuple[int, int]]:
    transaction.verify_parent(code)
    nonce_fd = _open_recorded_nonce_fd(transaction, code)
    final_owned: tuple[int, int] | None = None
    stage_descriptor: int | None = None
    try:
        stage_descriptor = os.open(
            staging.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=nonce_fd,
        )
        stage_metadata = os.fstat(stage_descriptor)
        if not stat.S_ISREG(stage_metadata.st_mode) or stage_metadata.st_nlink != 1:
            _raise(code)
        stage_digest, stage_size = _hash_fd(stage_descriptor, code)
        os.fsync(stage_descriptor)
        os.close(stage_descriptor)
        stage_descriptor = None
        if stage_digest != digest or stage_size != byte_count:
            _raise(code)
        os.link(
            staging.name,
            transaction.final_name,
            src_dir_fd=nonce_fd,
            dst_dir_fd=transaction.parent_fd,
            follow_symlinks=False,
        )
        linked = os.stat(
            transaction.final_name,
            dir_fd=transaction.parent_fd,
            follow_symlinks=False,
        )
        if (linked.st_dev, linked.st_ino) != (
            stage_metadata.st_dev,
            stage_metadata.st_ino,
        ):
            _raise(code)
        final_owned = (linked.st_dev, linked.st_ino)
        os.fsync(transaction.parent_fd)
        transaction.record["output_identity"] = list(final_owned)
        transaction.write()
        _crash_checkpoint("after_publish_link")
        os.unlink(staging.name, dir_fd=nonce_fd)
        os.fsync(nonce_fd)
        os.fsync(transaction.parent_fd)
        _crash_checkpoint("after_publish_unlink")
        identity = _validate_final_at(transaction, digest, byte_count, code)
        transaction.verify_parent(code)
        return transaction.parent_path / transaction.final_name, identity
    except BrollComponentExecutionError:
        _rollback_owned_final(transaction, final_owned)
        raise
    except OSError:
        _rollback_owned_final(transaction, final_owned)
        _raise(code)
    finally:
        if stage_descriptor is not None:
            try:
                os.close(stage_descriptor)
            except OSError:
                pass
        os.close(nonce_fd)


def _recover_publish(
    transaction: _Transaction, code: str
) -> ComponentArtifact | None:
    record = transaction.record
    artifact = _artifact_from_json(record.get("artifact"), code)
    digest = record.get("output_sha256")
    byte_count = record.get("byte_count")
    if (
        type(digest) is not str
        or _HASH.fullmatch(digest) is None
        or type(byte_count) is not int
        or byte_count <= 0
    ):
        _raise(code)
    nonce_fd = _try_open_recorded_nonce_fd(transaction, code)
    if nonce_fd is None:
        recorded_identity = record.get("output_identity")
        if record["state"] != "publishing" or not _exact_int_list(
            recorded_identity, 2
        ):
            _raise(code)
        try:
            visible = os.stat(
                transaction.final_name,
                dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            record.update(
                state="running",
                output_sha256=None,
                byte_count=None,
                output_identity=None,
                artifact=None,
            )
            transaction.write()
            return None
        except OSError:
            _raise(code)
        if (visible.st_dev, visible.st_ino) != tuple(recorded_identity):
            _raise(code)
        identity = _validate_final_at(transaction, digest, byte_count, code)
        record.update(state="published", output_identity=list(identity))
        transaction.write()
        _crash_checkpoint("after_published_receipt")
        transaction.verify_parent(code)
        return artifact
    staging_name = Path(str(record["staging_job_path"])).name
    final_owned: tuple[int, int] | None = None
    published_durable = False
    try:
        if record["state"] == "complete":
            record["state"] = "publishing"
            transaction.write()
        try:
            stage = os.stat(staging_name, dir_fd=nonce_fd, follow_symlinks=False)
            if not stat.S_ISREG(stage.st_mode) or stage.st_nlink not in {1, 2}:
                _raise(code)
            stage_exists = True
        except FileNotFoundError:
            stage = None
            stage_exists = False
        try:
            final = os.stat(
                transaction.final_name,
                dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(final.st_mode) or final.st_nlink not in {1, 2}:
                _raise(code)
            final_exists = True
        except FileNotFoundError:
            final = None
            final_exists = False
        recorded_identity = record.get("output_identity")
        if recorded_identity is not None:
            expected_identity = tuple(recorded_identity)
            if (
                not final_exists
                or (final.st_dev, final.st_ino) != expected_identity
                or stage_exists
                and (stage.st_dev, stage.st_ino) != expected_identity
            ):
                _raise(code)
            final_owned = expected_identity
        if final_exists and stage_exists:
            if (final.st_dev, final.st_ino) != (stage.st_dev, stage.st_ino):
                _raise(code)
            final_owned = (final.st_dev, final.st_ino)
        elif stage_exists:
            os.link(
                staging_name,
                transaction.final_name,
                src_dir_fd=nonce_fd,
                dst_dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
            os.fsync(transaction.parent_fd)
            linked = os.stat(
                transaction.final_name,
                dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
            if (linked.st_dev, linked.st_ino) != (
                stage.st_dev,
                stage.st_ino,
            ):
                _raise(code)
            final_owned = (linked.st_dev, linked.st_ino)
            os.fsync(transaction.parent_fd)
        elif not final_exists:
            _raise(code)
        if final_owned is None:
            _raise(code)
        if record.get("output_identity") is None:
            record["output_identity"] = list(final_owned)
            transaction.write()
        if stage_exists:
            os.unlink(staging_name, dir_fd=nonce_fd)
            os.fsync(nonce_fd)
            os.fsync(transaction.parent_fd)
        identity = _validate_final_at(transaction, digest, byte_count, code)
        if identity != final_owned:
            _raise(code)
        record.update(state="published", output_identity=list(identity))
        transaction.write()
        published_durable = True
        _crash_checkpoint("after_published_receipt")
        _cleanup_recorded_nonce(transaction, code)
        transaction.verify_parent(code)
        return artifact
    except BrollComponentExecutionError:
        if not published_durable:
            _rollback_owned_final(transaction, final_owned)
        raise
    except OSError:
        if not published_durable:
            _rollback_owned_final(transaction, final_owned)
        _raise(code)
    finally:
        os.close(nonce_fd)


def _transaction_names(
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    artifact_media_type: str,
) -> tuple[tuple[str, ...], str, str, str]:
    parent_parts = (
        "08-visual-assets",
        "components",
        recipe["segment_id"],
    )
    base = f"{component['component_id']}-r{recipe['strategy_revision']}"
    final_name = f"{base}{_extension(artifact_media_type, alpha=component['artifact_contract']['alpha'])}"
    return parent_parts, final_name, f".{base}.transaction.json", f".{base}.lock"


def _new_transaction(
    *,
    job: _PinnedJob,
    chain_fds: tuple[int, ...],
    chain_checks: tuple[tuple[Path, tuple[int, int, int]], ...],
    lock_fd: int,
    journal_name: str,
    final_name: str,
    record: dict[str, Any],
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    input_sha256: str,
    artifact_media_type: str,
    binding: Mapping[str, Any],
) -> _Transaction:
    parent_fd = chain_fds[-1]
    metadata = os.fstat(parent_fd)
    return _Transaction(
        job=job,
        parent_fd=parent_fd,
        lock_fd=lock_fd,
        parent_path=chain_checks[-1][0],
        parent_identity=(metadata.st_dev, metadata.st_ino, metadata.st_mode),
        chain_fds=chain_fds,
        chain_checks=chain_checks,
        journal_name=journal_name,
        final_name=final_name,
        record=record,
        recipe=recipe,
        component=component,
        input_sha256=input_sha256,
        artifact_media_type=artifact_media_type,
        adapter_binding=binding,
    )


def _new_planned_record(
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    input_sha256: str,
    binding: Mapping[str, Any],
    final_name: str,
) -> dict[str, Any]:
    nonce = (
        f"{component['component_id']}-r{recipe['strategy_revision']}."
        f"{secrets.token_hex(16)}"
    )
    parent = PurePosixPath(
        "08-visual-assets", "components", recipe["segment_id"]
    )
    nonce_root = parent / ".staging" / nonce
    extension = Path(final_name).suffix
    return {
        "schema_version": 2,
        "state": "planned",
        "input_sha256": input_sha256,
        "recipe_sha256": _sha256_bytes(_canonical_bytes(recipe)),
        "segment_id": recipe["segment_id"],
        "component_id": component["component_id"],
        "strategy_revision": recipe["strategy_revision"],
        "kind": component["kind"],
        "adapter_binding": _plain_json(binding),
        "nonce": nonce,
        "nonce_identity": None,
        "adapter_staging_job_path": (nonce_root / f"output{extension}").as_posix(),
        "staging_job_path": (
            nonce_root / f"publish.snapshot{extension}"
        ).as_posix(),
        "output_job_path": (parent / final_name).as_posix(),
        "source_sha256": (
            component["sha256"]
            if component["kind"] in _MATERIAL_KINDS
            else None
        ),
        "source_identity": None,
        "output_sha256": None,
        "byte_count": None,
        "output_identity": None,
        "artifact": None,
    }


def _final_absent(transaction: _Transaction, code: str) -> None:
    try:
        visible = os.stat(
            transaction.final_name,
            dir_fd=transaction.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError:
        _raise(code)
    if stat.S_ISREG(visible.st_mode) or visible:
        _raise(code)


def _replay_transaction(
    transaction: _Transaction, code: str
) -> ComponentArtifact | None:
    state = transaction.record["state"]
    if (transaction.record.get("input_sha256") is not None
            and transaction.record.get("input_sha256") != transaction.input_sha256):
        # a recomposed plan rewrote the brief; nothing here is reusable
        return None
    if state not in {"published", "complete", "publishing"}:
        # A crashed or failed earlier render owns nothing worth replaying;
        # the chain lock is held by this execution, so re-render from scratch
        # instead of validating a record that can never publish.
        return None
    artifact = _validate_transaction_record(transaction, transaction.record, code)
    if state == "published":
        if artifact is None:
            _raise(code)
        identity = _validate_final_at(
            transaction,
            transaction.record["output_sha256"],
            transaction.record["byte_count"],
            code,
        )
        if list(identity) != transaction.record["output_identity"]:
            _raise(code)
        _cleanup_recorded_nonce(transaction, code)
        transaction.verify_parent(code)
        return artifact
    if state in {"complete", "publishing"}:
        return _recover_publish(transaction, code)
    return None


def _try_replay_transaction(
    job: _PinnedJob,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    input_sha256: str,
    artifact_media_type: str,
    binding: Mapping[str, Any],
    *, export_only: bool = False,
) -> ComponentArtifact | dict[str, Any] | None:
    code = _failure_for(component["kind"])
    parent_parts, final_name, journal_name, lock_name = _transaction_names(
        recipe, component, artifact_media_type
    )
    opened = _open_output_chain(job, parent_parts, create=False, code=code)
    if opened is None:
        return None
    chain_fds, chain_checks = opened
    parent_fd = chain_fds[-1]
    probe_fd: int | None = None
    next_fd: int | None = None
    try:
        probe_fd = _open_regular_at(parent_fd, journal_name, code)
        next_fd = _open_regular_at(parent_fd, f"{journal_name}.next", code)
    except BaseException:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        raise
    finally:
        for descriptor in (probe_fd, next_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    if probe_fd is None and next_fd is None:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        return None
    try:
        lock_fd = _open_component_lock(parent_fd, lock_name, code, create=False)
    except BaseException:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        raise
    if lock_fd is None:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        _raise(code)
    try:
        record = (_read_published_record_at(parent_fd, journal_name, code) if export_only
                  else _read_transaction(parent_fd, journal_name, code))
        if record is None:
            _raise(code)
        transaction = _new_transaction(
            job=job,
            chain_fds=chain_fds,
            chain_checks=chain_checks,
            lock_fd=lock_fd,
            journal_name=journal_name,
            final_name=final_name,
            record=record,
            recipe=recipe,
            component=component,
            input_sha256=input_sha256,
            artifact_media_type=artifact_media_type,
            binding=binding,
        )
    except BaseException:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        raise
    try:
        if export_only:
            artifact = _validate_transaction_record(transaction, record, code)
            if artifact is None:
                _raise(code)
            identity = _validate_final_at(transaction, record["output_sha256"], record["byte_count"], code)
            if list(identity) != record["output_identity"]:
                _raise(code)
            transaction.verify_parent(code)
            return {"schema_version": 1, **{key: _plain_json(record[key]) for key in (
                "state", "input_sha256", "recipe_sha256", "segment_id", "component_id",
                "strategy_revision", "kind", "adapter_binding", "output_job_path",
                "output_sha256", "byte_count")},
                "artifact_sha256": _sha256_bytes(_canonical_bytes(record["artifact"], code))}
        replay = _replay_transaction(transaction, code)
        if replay is not None:
            return replay
        return None
    finally:
        transaction.close()


def _begin_transaction(
    job: _PinnedJob,
    recipe: Mapping[str, Any],
    component: Mapping[str, Any],
    input_sha256: str,
    artifact_media_type: str,
    binding: Mapping[str, Any],
) -> tuple[_Transaction, ComponentArtifact | None]:
    code = _failure_for(component["kind"])
    parent_parts, final_name, journal_name, lock_name = _transaction_names(
        recipe, component, artifact_media_type
    )
    opened = _open_output_chain(job, parent_parts, create=True, code=code)
    if opened is None:
        _raise(code)
    chain_fds, chain_checks = opened
    parent_fd = chain_fds[-1]
    try:
        lock_fd = _open_component_lock(parent_fd, lock_name, code, create=True)
    except BaseException:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        raise
    if lock_fd is None:
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        _raise(code)
    try:
        record = _read_transaction(parent_fd, journal_name, code)
        if record is None:
            record = _new_planned_record(
                recipe, component, input_sha256, binding, final_name
            )
        transaction = _new_transaction(
            job=job,
            chain_fds=chain_fds,
            chain_checks=chain_checks,
            lock_fd=lock_fd,
            journal_name=journal_name,
            final_name=final_name,
            record=record,
            recipe=recipe,
            component=component,
            input_sha256=input_sha256,
            artifact_media_type=artifact_media_type,
            binding=binding,
        )
    except BaseException:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)
        for descriptor in reversed(chain_fds):
            os.close(descriptor)
        raise
    try:
        replay = _replay_transaction(transaction, code)
        if replay is not None:
            return transaction, replay
        stale_journal = (
            record.get("input_sha256") != input_sha256
            or record.get("recipe_sha256") != _sha256_bytes(_canonical_bytes(recipe))
        )
        if stale_journal:
            # a recomposed plan rewrites every brief; the stale journal is
            # simply replaced by the fresh transaction below
            record = _new_planned_record(
                recipe, component, input_sha256, binding, final_name
            )
            transaction.record = record
        else:
            _validate_transaction_record(transaction, transaction.record, code)
            _final_absent(transaction, code)
        if record["state"] in {"planned", "running"}:
            _cleanup_recorded_nonce(transaction, code)
            transaction.record = _new_planned_record(
                recipe, component, input_sha256, binding, final_name
            )
        transaction.write()
        _crash_checkpoint("after_planned_receipt")
        return transaction, None
    except BaseException:
        transaction.close()
        raise


def _initialize_nonce(
    transaction: _Transaction,
    source: _PinnedSource | None,
    code: str,
) -> tuple[Path, Path, str, str]:
    transaction.verify_parent(code)
    staging_fd: int | None = None
    nonce_fd: int | None = None
    nonce = transaction.record["nonce"]
    try:
        try:
            visible = os.stat(
                ".staging",
                dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            os.mkdir(".staging", mode=0o700, dir_fd=transaction.parent_fd)
            os.fsync(transaction.parent_fd)
            visible = os.stat(
                ".staging",
                dir_fd=transaction.parent_fd,
                follow_symlinks=False,
            )
        if not stat.S_ISDIR(visible.st_mode):
            _raise(code)
        staging_fd = os.open(
            ".staging",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=transaction.parent_fd,
        )
        os.mkdir(nonce, mode=0o700, dir_fd=staging_fd)
        os.fsync(staging_fd)
        nonce_fd = os.open(
            nonce,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=staging_fd,
        )
        metadata = os.fstat(nonce_fd)
        transaction.record["nonce_identity"] = [metadata.st_dev, metadata.st_ino]
        transaction.record["state"] = "running"
        transaction.write()
        _crash_checkpoint("after_nonce_mkdir")
    except BrollComponentExecutionError:
        raise
    except OSError:
        _raise(code)
    finally:
        for descriptor in (nonce_fd, staging_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    nonce_dir = transaction.parent_path / ".staging" / nonce
    adapter_staging = transaction.job.path.joinpath(
        *PurePosixPath(transaction.record["adapter_staging_job_path"]).parts
    )
    if source is not None:
        _source_path, source_identity = _snapshot_source(
            source, transaction, code
        )
        _crash_checkpoint("after_input_snapshot_before_running")
        transaction.record["source_identity"] = source_identity
        transaction.write()
    _crash_checkpoint("after_running_receipt")
    return (
        nonce_dir,
        adapter_staging,
        transaction.record["adapter_staging_job_path"],
        transaction.record["output_job_path"],
    )


def _execute_pinned(
    job: Any,
    component: ComponentExecutionRequest,
    *,
    adapters: Mapping[str, object],
    pinned_job: _PinnedJob,
) -> ComponentArtifact:
    """Execute one component selected from a complete, canonical ShotRecipe v2.

    No bare-component or old-Job compatibility path exists.  Validation and
    truth checks complete before any adapter, process, renderer, or staging I/O.
    """

    request = component
    approval_sha = _sha256_bytes(
        _canonical_bytes(
            {"recipe": request.recipe, "component_id": request.component_id}
        )
    )
    recipe, selected, input_sha = _selected_request(component)
    approved_recipe = _freeze(recipe)
    approved_component = _freeze(selected)
    job_id = pinned_job.job_id
    job_dir = pinned_job.path
    if type(adapters) is not dict:
        _raise("BROLL_SCHEMA_INVALID")
    kind = selected["kind"]
    code = _failure_for(kind)
    artifact_probe = _validate_probe(adapters.get("artifact_probe"))

    if kind == "code_generated":
        registry = adapters.get(kind)
        if type(registry) is not dict:
            _raise("BROLL_DEPENDENCY_UNBOUND")
        candidate = registry.get(selected["dependency_id"])
        if isinstance(candidate, dict):
            candidate = candidate.get((recipe["segment_id"], selected["component_id"]))
        adapter = _validate_code_adapter(candidate, selected)
    else:
        candidate_adapter = adapters.get(kind)
        if isinstance(candidate_adapter, dict):
            candidate_adapter = candidate_adapter.get((recipe["segment_id"], selected["component_id"]))
        adapter = _validate_kind_adapter(candidate_adapter, selected)
    artifact_media_type = adapter.artifact_media_type
    qualification_binding: _FrozenQualificationRegistry | None = None
    try:
        if (
            type(adapter) is ReferenceProcessAdapter
            and adapter.qualification_registry_path is not None
        ):
            qualification_binding = _freeze_qualification_registry(adapter)
        binding_record = _adapter_binding_record(adapter, artifact_probe)
        if qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
        replay = _try_replay_transaction(
            pinned_job,
            recipe,
            selected,
            input_sha,
            artifact_media_type,
            binding_record,
        )
        if replay is not None and qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
    except BaseException:
        if qualification_binding is not None:
            qualification_binding.close()
        raise
    if replay is not None:
        if qualification_binding is not None:
            qualification_binding.close()
        return replay
    process_binding: _FrozenProcessBinding | None = None
    source: _PinnedSource | None = None
    try:
        if type(adapter) is ReferenceProcessAdapter:
            process_binding = _freeze_process_binding(adapter)
        source = _prepare_source(job, pinned_job, recipe, selected)
        transaction, replay = _begin_transaction(
            pinned_job,
            recipe,
            selected,
            input_sha,
            artifact_media_type,
            binding_record,
        )
    except BaseException:
        if process_binding is not None:
            process_binding.close()
        if source is not None:
            source.close()
        if qualification_binding is not None:
            qualification_binding.close()
        raise
    if replay is not None:
        try:
            if qualification_binding is not None:
                _verify_frozen_qualification_registry(qualification_binding)
        finally:
            transaction.close()
            if process_binding is not None:
                process_binding.close()
            if source is not None:
                source.close()
            if qualification_binding is not None:
                qualification_binding.close()
        return replay

    nonce_dir: Path | None = None
    published_path: Path | None = None
    published_identity: tuple[int, int] | None = None
    published_durable = False
    adapter_output_fd: int | None = None
    source_snapshot_fd: int | None = None
    try:
        _verify_job(pinned_job, code)
        nonce_dir, staging, staging_job_path, output_job_path = _initialize_nonce(
            transaction, source, code
        )
        source_path = None
        if source is not None:
            source_snapshot_fd = _open_source_snapshot_fd(transaction, code)
            source_path = Path(f"/dev/fd/{source_snapshot_fd}")
        source_sha = source.expected_sha256 if source is not None else None
        context_staging = staging
        if type(adapter) is not ReferenceProcessAdapter:
            adapter_output_fd = _create_adapter_output_fd(transaction, code)
            context_staging = Path(f"/dev/fd/{adapter_output_fd}")
        context = AdapterContext(
            job_id=job_id,
            job_dir=job_dir,
            segment_id=recipe["segment_id"],
            strategy_revision=recipe["strategy_revision"],
            component_id=selected["component_id"],
            kind=kind,
            recipe=approved_recipe,
            component=approved_component,
            input_sha256=input_sha,
            approval_sha256=approval_sha,
            source_path=source_path,
            source_sha256=source_sha,
            staging_path=context_staging,
            staging_job_path=staging_job_path,
            output_job_path=output_job_path,
        )
        if type(adapter) is ReferenceProcessAdapter:
            if qualification_binding is not None:
                _verify_frozen_qualification_registry(qualification_binding)
            evidence, qa = _run_reference_process(
                job,
                request,
                recipe,
                selected,
                approval_sha,
                process_binding,
                transaction,
                context,
            )
            if qualification_binding is not None:
                _verify_frozen_qualification_registry(qualification_binding)
        elif type(adapter) is SkillInvocationAdapter:
            evidence, qa = _run_skill_invocation(
                job,
                request,
                recipe,
                selected,
                approval_sha,
                adapter,
                context,
            )
        else:
            evidence, qa = _run_kind_adapter(adapter, context, request, code)

        transaction.verify_parent(code)
        if adapter_output_fd is None:
            adapter_output_fd = _open_nonce_output(
                transaction, staging_job_path, code
            )
        try:
            digest, byte_count = _hash_fd(adapter_output_fd, code)
            if byte_count <= 0:
                _raise(code)
            if kind == "ai_generated" and digest != selected["sha256"]:
                _raise("BROLL_GENERATION_FAILED")
            _approved_unchanged(request, approval_sha)
            media_probe = _validated_probe_fd(
                artifact_probe,
                adapter_output_fd,
                artifact_media_type,
                approved_component["artifact_contract"],
                code,
            )
            publish_staging, snapshot_digest, snapshot_size = (
                _create_publish_snapshot(
                    transaction, adapter_output_fd, code
                )
            )
            if (snapshot_digest, snapshot_size) != (digest, byte_count):
                _raise(code)
        finally:
            os.close(adapter_output_fd)
            adapter_output_fd = None
        _approved_unchanged(request, approval_sha)
        evidence = dict(evidence)
        evidence["output_job_path"] = output_job_path
        evidence["output_sha256"] = digest
        evidence["probe_id"] = artifact_probe.probe_id
        evidence["probe_version"] = artifact_probe.probe_version
        window = selected["render_window"]
        artifact = ComponentArtifact(
            schema_version=1,
            status="success",
            job_id=job_id,
            segment_id=recipe["segment_id"],
            component_id=selected["component_id"],
            kind=kind,
            strategy_revision=recipe["strategy_revision"],
            media_type=artifact_media_type,
            render_window=_freeze(window),
            z_index=window["z_index"],
            layout_slot=window["layout_slot"],
            opacity=window["opacity"],
            safe_zone=_freeze(window["safe_zone"]),
            artifact_contract=_freeze(selected["artifact_contract"]),
            source_media_type=selected["media_type"],
            artifact_media_type=artifact_media_type,
            media_probe=_freeze(media_probe),
            input_sha256=input_sha,
            job_path=output_job_path,
            byte_count=byte_count,
            output_sha256=digest,
            invocation_evidence=_freeze(evidence),
            qa=_freeze(qa),
            error_code=None,
        )
        _validate_replayed_artifact(
            artifact,
            job=pinned_job,
            recipe=recipe,
            component=selected,
            artifact_media_type=artifact_media_type,
            output_job_path=output_job_path,
            input_sha256=input_sha,
            binding=binding_record,
            adapter_staging_job_path=transaction.record[
                "adapter_staging_job_path"
            ],
            code=code,
        )
        if qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
        transaction.record.update(
            state="complete",
            output_sha256=digest,
            byte_count=byte_count,
            artifact=_plain_json(dict(artifact)),
        )
        transaction.write()
        _crash_checkpoint("after_complete_receipt")
        transaction.record["state"] = "publishing"
        transaction.write()
        _verify_job(pinned_job, code)
        if qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
        published_path, published_identity = _publish_transaction(
            transaction,
            publish_staging,
            digest,
            byte_count,
            code,
        )
        try:
            if qualification_binding is not None:
                _verify_frozen_qualification_registry(qualification_binding)
        except BaseException:
            if _rollback_owned_final(transaction, published_identity):
                published_path = None
                published_identity = None
                transaction.record.update(
                    state="running",
                    output_sha256=None,
                    byte_count=None,
                    output_identity=None,
                    artifact=None,
                )
                transaction.write()
            raise
        transaction.record.update(
            state="published",
            output_identity=list(published_identity),
        )
        transaction.write()
        _crash_checkpoint("after_published_receipt")
        try:
            _cleanup_recorded_nonce(transaction, code)
        except BrollComponentExecutionError:
            raise
        except OSError:
            _raise(code)
        published_durable = True
        nonce_dir = None
        transaction.verify_parent(code)
        return artifact
    finally:
        active_failure = sys.exc_info()[1]
        if process_binding is not None:
            process_binding.close()
        if qualification_binding is not None:
            qualification_binding.close()
        if source is not None:
            source.close()
        if adapter_output_fd is not None:
            try:
                os.close(adapter_output_fd)
            except OSError:
                pass
        if source_snapshot_fd is not None:
            try:
                os.close(source_snapshot_fd)
            except OSError:
                pass
        try:
            if nonce_dir is not None:
                _cleanup_recorded_nonce(transaction, code)
        except (OSError, BrollComponentExecutionError):
            if (
                not published_durable
                and published_path is not None
                and published_identity is not None
            ):
                rolled_back = _rollback_owned_final(
                    transaction, published_identity
                )
                if rolled_back:
                    transaction.record.update(
                        state="running",
                        output_sha256=None,
                        byte_count=None,
                        output_identity=None,
                        artifact=None,
                    )
                    try:
                        transaction.write()
                    except BrollComponentExecutionError:
                        pass
            if active_failure is None:
                transaction.close()
                _raise(code)
        finally:
            transaction.close()


def export_published_execution_binding(
    job: Any, request: ComponentExecutionRequest, *, adapters: Mapping[str, object]
) -> dict[str, Any]:
    """Inspect a published transaction without recovery, rendering or writes."""
    if type(request) is not ComponentExecutionRequest or type(adapters) is not dict:
        _raise("BROLL_SCHEMA_INVALID")
    recipe, component, input_sha = _selected_request(request)
    probe = _validate_probe(adapters.get("artifact_probe"))
    if component["kind"] == "code_generated":
        registry = adapters.get("code_generated")
        if type(registry) is not dict:
            _raise("BROLL_DEPENDENCY_UNBOUND")
        candidate = registry.get(component["dependency_id"])
        if isinstance(candidate, dict):
            candidate = candidate.get((recipe["segment_id"], component["component_id"]))
        adapter = _validate_code_adapter(candidate, component)
    else:
        candidate_adapter = adapters.get(component["kind"])
        if isinstance(candidate_adapter, dict):
            candidate_adapter = candidate_adapter.get((recipe["segment_id"], component["component_id"]))
        adapter = _validate_kind_adapter(candidate_adapter, component)
    pinned = _job_context(job)
    qualification_binding = None
    try:
        if type(adapter) is ReferenceProcessAdapter and adapter.qualification_registry_path is not None:
            qualification_binding = _freeze_qualification_registry(adapter)
        binding = _adapter_binding_record(adapter, probe)
        if qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
        result = _try_replay_transaction(pinned, recipe, component, input_sha,
                                        adapter.artifact_media_type, binding, export_only=True)
        if qualification_binding is not None:
            _verify_frozen_qualification_registry(qualification_binding)
        if type(result) is not dict:
            _raise(_failure_for(component["kind"]))
        return result
    finally:
        if qualification_binding is not None:
            qualification_binding.close()
        pinned.close()


def execute_component(
    job: Any,
    component: ComponentExecutionRequest,
    *,
    adapters: Mapping[str, object],
) -> ComponentArtifact:
    """Execute one component selected from a complete, canonical ShotRecipe v2.

    No bare-component or old-Job compatibility path exists. Validation and
    adapter binding complete before staging, process, renderer, or network I/O.
    """

    if type(component) is not ComponentExecutionRequest:
        _raise("BROLL_SCHEMA_INVALID")
    _selected_request(component)
    pinned_job = _job_context(job)
    try:
        return _execute_pinned(
            job, component, adapters=adapters, pinned_job=pinned_job
        )
    finally:
        pinned_job.close()


__all__ = [
    "ERROR_CODES",
    "ALLOWED_ACTIONS",
    "BrollComponentExecutionError",
    "ComponentExecutionRequest",
    "AdapterResult",
    "AdapterContext",
    "KindAdapter",
    "ArtifactProbe",
    "ReferenceProcessMedia",
    "ReferenceProcessAdapter",
    "SkillInvocationResult",
    "SkillInvocationAdapter",
    "ComponentArtifact",
    "execute_component",
    "export_published_execution_binding",
]

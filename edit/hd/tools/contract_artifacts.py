"""Strict, deterministic artifact helpers for full-v2 workflow contracts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple


class ContractArtifactError(ValueError):
    """Raised when a contract artifact is malformed or cannot be persisted."""


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractArtifactError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ContractArtifactError(f"non-finite JSON number: {value}")


def canonical_json_bytes(payload: object) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractArtifactError("invalid JSON artifact") from exc
    return (rendered + "\n").encode("utf-8")


def sha256_json(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractArtifactError("unable to read contract artifact") from exc
    return digest.hexdigest()


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    if not isinstance(path, Path) or type(payload) is not bytes:
        raise ContractArtifactError("invalid contract artifact write")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=str(path.parent)
        )
    except OSError as exc:
        raise ContractArtifactError("unable to prepare contract artifact") from exc
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory = os.open(
            str(path.parent),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise ContractArtifactError("unable to publish contract artifact") from exc
    finally:
        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError:
            pass


def write_json_artifact(path: Path, payload: object) -> None:
    write_bytes_atomic(path, canonical_json_bytes(payload))


def write_text_artifact(path: Path, payload: str) -> None:
    if type(payload) is not str:
        raise ContractArtifactError("text artifact must be text")
    write_bytes_atomic(path, payload.encode("utf-8"))


def read_json_artifact(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(
                handle,
                object_pairs_hook=_strict_object,
                parse_constant=_reject_nonfinite,
            )
    except ContractArtifactError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractArtifactError("invalid JSON artifact") from exc
    if type(payload) is not dict:
        raise ContractArtifactError("JSON artifact must be an object")
    return payload

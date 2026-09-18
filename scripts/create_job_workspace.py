#!/usr/bin/env python3
"""Create one isolated talking-head video Job and import user materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


USER_MEDIA_DIRS = ("video", "images", "audio", "documents")
JOB_DIRS = (
    "01-inspect",
    "02-content-analysis",
    "03-cover-direction",
    "04-cover",
    "05-speech-cleanup",
    "06-edit-structure",
    "07-visual-direction",
    "08-visual-canary",
    "09-visual-assets/official",
    "09-visual-assets/code",
    "09-visual-assets/ai",
    "09-visual-assets/arroll-overlays",
    "09-visual-assets/avatar",
    "09-visual-assets/segments",
    "10-subtitles",
    "11-preview",
    "12-delivery",
    "manifests",
    "qa",
    "cache",
    "tmp",
)

VIDEO_SUFFIXES = {
    ".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"
}
IMAGE_SUFFIXES = {
    ".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"
}
AUDIO_SUFFIXES = {
    ".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"
}


class WorkspaceError(RuntimeError):
    """Raised when a Job workspace cannot be created safely."""


def _slug(value: str) -> str:
    normalized = re.sub(r"[^\w\-]+", "-", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip("-_")
    return normalized[:48] or "video"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in IMAGE_SUFFIXES:
        return "images"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return "documents"


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    data = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _unique_job_id(title: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{_slug(title)}-{secrets.token_hex(3)}"


def create_workspace(
    jobs_root: str | Path,
    title: str,
    user_files: Iterable[str | Path] = (),
    *,
    create_output_directories: bool = True,
    inline_script: str | None = None,
    initialization: dict | None = None,
) -> Path:
    """Create and atomically publish one Job directory.

    User files are copied, never moved. Identical bytes share one imported asset
    while each original filename retains a material record.
    """

    if inline_script is not None and (not isinstance(inline_script, str) or not inline_script.strip()):
        raise WorkspaceError("inline script must contain text")
    root = Path(jobs_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    sources = [Path(value).expanduser().resolve() for value in user_files]
    for source in sources:
        if not source.is_file():
            raise WorkspaceError(f"user material is not a regular file: {source}")

    job_id = _unique_job_id(title)
    final_dir = root / job_id
    temporary_dir = root / f".{job_id}.building"
    if final_dir.exists() or temporary_dir.exists():
        raise WorkspaceError(f"job directory already exists: {job_id}")

    try:
        temporary_dir.mkdir()
        user_root = temporary_dir / "00-user-provided"
        for media_dir in USER_MEDIA_DIRS:
            (user_root / media_dir).mkdir(parents=True)
        if create_output_directories:
            for relative in JOB_DIRS:
                (temporary_dir / relative).mkdir(parents=True)

        assets_by_hash: dict[str, dict[str, object]] = {}
        materials: list[dict[str, object]] = []
        entries = [(source, None) for source in sources]
        if inline_script is not None:
            entries.append((Path("inline-script.md"), inline_script.encode("utf-8")))
        for position, (source, inline_bytes) in enumerate(entries, start=1):
            digest = _sha256(source) if inline_bytes is None else hashlib.sha256(inline_bytes).hexdigest()
            asset = assets_by_hash.get(digest)
            if asset is None:
                media_type = _media_type(source)
                suffix = source.suffix.casefold()
                imported_name = f"{digest[:20]}{suffix}"
                imported_relative = Path("00-user-provided") / media_type / imported_name
                imported_path = temporary_dir / imported_relative
                if inline_bytes is None:
                    shutil.copy2(source, imported_path)
                else:
                    with imported_path.open("xb") as handle:
                        handle.write(inline_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                if _sha256(imported_path) != digest:
                    raise WorkspaceError(f"user material changed during copy: {source.name}")
                asset = {
                    "asset_id": f"asset-{digest[:20]}",
                    "imported_path": imported_relative.as_posix(),
                    "media_type": media_type,
                    "sha256": digest,
                    "size_bytes": imported_path.stat().st_size,
                }
                assets_by_hash[digest] = asset

            materials.append(
                {
                    "material_id": f"material-{position:04d}",
                    "asset_id": asset["asset_id"],
                    "original_name": source.name,
                    "imported_path": asset["imported_path"],
                    "media_type": asset["media_type"],
                    "sha256": digest,
                    "size_bytes": asset["size_bytes"],
                }
            )

        index = {
            "schema_version": 1,
            "job_id": job_id,
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "assets": list(assets_by_hash.values()),
            "materials": materials,
        }
        _write_json_atomic(user_root / "material-index.json", index)
        if initialization is not None:
            by_id = {record["material_id"]: record for record in materials}
            primary = {role: by_id[material_id] for role, material_id in
                       initialization["primary_material_ids"].items()}
            record = {key: value for key, value in initialization.items()
                      if key != "primary_material_ids"}
            record.update(
                schema_version=1, phase="imported", workspace=str(final_dir),
                inputs={role: {"path": item["imported_path"], "sha256": item["sha256"],
                               "bytes": item["size_bytes"]} for role, item in primary.items()},
                material_index_sha256=_sha256(user_root / "material-index.json"),
            )
            _write_json_atomic(temporary_dir / "initialization.json", record)
        temporary_dir.rename(final_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    return final_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--user-file", action="append", default=[], type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    job_dir = create_workspace(args.jobs_root, args.title, args.user_file)
    print(job_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

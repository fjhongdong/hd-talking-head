#!/usr/bin/env python3
"""Read-only integrity check for a complete, portable Skill release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


MANIFEST = "skill-development/hd-talking-head/release-manifest.json"
REQUIRED = {
    "SKILL.md", "run.py", "edit/__init__.py", "edit/hd/__init__.py",
    "edit/hd/tools/state.py", "edit/hd/integrations/talkcraft/check_runtime.py",
    "source-repositories/index.json", "runtime-archives/talkcraft.json", "skills/video-use/SKILL.md",
    "skill-development/hd-talking-head/SKILL.md",
    "skill-development/hd-talking-head/scripts/verify_broll_template.py",
    "skill-development/hd-talking-head/references/verified-template-registry.json",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_files(root: Path) -> dict[str, Path]:
    package_root = root.resolve().parents[1]
    files = {}
    excluded = {".git", "node_modules", ".venv", ".cache", ".remotion", "__pycache__"}
    for directory, directories, names in os.walk(package_root):
        base = Path(directory)
        relative = base.relative_to(package_root).as_posix()
        directories[:] = [name for name in directories if name not in excluded and not name.endswith(".egg-info")
            and not (relative == "skill-development" and name == "runtime")
            and not (relative.startswith("skill-development/research/hypit-source") and name == "dist")]
        for name in names:
            path = base / name
            key = path.relative_to(package_root).as_posix()
            if (key == MANIFEST or name in {".DS_Store", ".env", ".env.local", ".env.production"} or path.suffix in {".pyc", ".tsbuildinfo"}
                    or name in {".visual-broll-install.lock", ".punk-cover-install.lock"}):
                continue
            files[key] = path
    return files


def verify_release(root: Path, expected: dict | None = None) -> dict:
    root = root.resolve()
    failures = []
    try:
        package_root = root.parents[1]
        manifest_path = package_root / MANIFEST
        if manifest_path.is_symlink():
            raise ValueError("release manifest must not be a symlink")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "release_id", "files"}:
            raise ValueError("invalid release manifest fields")
        if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise ValueError("unsupported release manifest schema")
        if not isinstance(manifest["release_id"], str) or not manifest["release_id"]:
            raise ValueError("release_id is missing")
        records = manifest["files"]
        if not isinstance(records, dict) or not REQUIRED.issubset(records):
            raise ValueError("required Skill attachments are missing from release manifest")
        for name, digest in records.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
                raise ValueError("invalid manifest path: " + name)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid manifest hash: " + name)
        if expected is not None and manifest != expected:
            failures.append("release manifest differs from the selected source release")
        authoritative = expected["files"] if expected is not None else records
        actual = package_files(root)
        failures.extend("missing: " + name for name in sorted(set(authoritative) - set(actual)))
        failures.extend("unregistered: " + name for name in sorted(set(actual) - set(authoritative)))
        for name in sorted(set(authoritative) & set(actual)):
            path = actual[name]
            parts = [package_root.joinpath(*Path(name).parts[:index]) for index in range(1, len(Path(name).parts) + 1)]
            if any(part.is_symlink() for part in parts):
                failures.append("symlink is not a release asset: " + name)
            elif file_hash(path) != authoritative[name]:
                failures.append("hash mismatch: " + name)
    except (OSError, ValueError, TypeError) as error:
        return {"status": "fail", "root": str(root), "failures": [str(error)]}
    return {
        "status": "fail" if failures else "pass", "root": str(root),
        "release_id": manifest["release_id"], "files_checked": len(records),
        "manifest_sha256": file_hash(package_root / MANIFEST), "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = verify_release(root)
    if report["status"] == "pass":
        manifest = json.loads((root.parents[1] / MANIFEST).read_text(encoding="utf-8"))
        report["peers"] = [verify_release(path, manifest) for path in args.peer]
        if any(peer["status"] != "pass" for peer in report["peers"]):
            report["status"] = "fail"
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

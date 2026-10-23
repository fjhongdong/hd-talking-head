#!/usr/bin/env python3
"""Read-only health check for the qualified HD TalkCraft integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
PRODUCTION = ROOT / "runtime"
UPSTREAM = ROOT / "upstream"


class RuntimeCheckError(ValueError):
    pass


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeCheckError(f"unreadable JSON: {path}") from error
    if type(value) is not dict:
        raise RuntimeCheckError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise RuntimeCheckError(f"unreadable artifact: {path}") from error


def _manifest_pin(render_path: Path) -> str:
    try:
        source = render_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeCheckError(f"unreadable renderer: {render_path}") from error
    matches = re.findall(r'(?m)^const EXPECTED_MANIFEST_SHA256 = "([0-9a-f]{64})";$', source)
    if len(matches) != 1:
        raise RuntimeCheckError("renderer manifest pin is missing or ambiguous")
    return matches[0]


def _check_closure_files(production: Path, files: object) -> None:
    if type(files) is not list or not files:
        raise RuntimeCheckError("TalkCraft closure file list is invalid")
    seen: set[str] = set()
    for record in files:
        if type(record) is not dict or set(record) != {"path", "sha256", "mode"}:
            raise RuntimeCheckError("TalkCraft closure file record is invalid")
        relative = record["path"]
        if type(relative) is not str:
            raise RuntimeCheckError("TalkCraft closure file path is invalid")
        path = PurePosixPath(relative)
        if (
            not relative or path.is_absolute() or ".." in path.parts
            or path.as_posix() != relative or "\\" in relative or relative in seen
        ):
            raise RuntimeCheckError("TalkCraft closure file path is invalid")
        seen.add(relative)
        source = production / relative
        try:
            info = source.lstat()
        except OSError as error:
            raise RuntimeCheckError(f"TalkCraft closure file is missing: {relative}") from error
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != record["mode"]:
            raise RuntimeCheckError(f"TalkCraft closure file type or mode changed: {relative}")
        if _sha256(source) != record["sha256"]:
            raise RuntimeCheckError(f"TalkCraft closure file identity changed: {relative}")


def _check_identity(root: Path, production: Path) -> None:
    manifest_sha = _sha256(production / "closure-manifest.json")
    if manifest_sha != _manifest_pin(production / "render.mjs"):
        raise RuntimeCheckError("TalkCraft runtime closure differs from its renderer pin")
    manifest = _json(production / "closure-manifest.json")
    files = manifest.get("files")
    core = (
        [item for item in files if type(item) is dict and item.get("path") == "render-core.mjs"]
        if type(files) is list else []
    )
    if len(core) != 1 or _sha256(production / "render-core.mjs") != core[0].get("sha256"):
        raise RuntimeCheckError("TalkCraft render core differs from its closure manifest")

    registry_path = production / "card-registry.json"
    registry_sha = _sha256(registry_path)
    registry = _json(registry_path)
    compatibility = registry.get("runtime_compatibility")
    if type(compatibility) is not dict or compatibility.get("target_closure_sha256") != manifest_sha:
        raise RuntimeCheckError("TalkCraft registry targets a different runtime closure")
    relative = compatibility.get("path")
    if type(relative) is not str or not relative.startswith("qualification-evidence/"):
        raise RuntimeCheckError("TalkCraft compatibility record path is invalid")
    record_path = PurePosixPath(relative)
    if record_path.is_absolute() or ".." in record_path.parts or "\\" in relative:
        raise RuntimeCheckError("TalkCraft compatibility record path is invalid")
    record = root / relative
    if _sha256(record) != compatibility.get("sha256"):
        raise RuntimeCheckError("TalkCraft compatibility record identity changed")

    for name in ("card-semantic-index.json", "card-event-capabilities.json"):
        index = _json(production / name)
        if (
            index.get("registry_sha256") != registry_sha
            or index.get("registry_version") != registry.get("registry_version")
        ):
            raise RuntimeCheckError(f"TalkCraft {name} differs from the qualified registry")


def check_runtime(root: Path = ROOT) -> dict[str, object]:
    production = root / "runtime"
    upstream = root / "upstream"
    package = _json(production / "package.json")
    requested = {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }
    if not requested or any(type(name) is not str or type(version) is not str for name, version in requested.items()):
        raise RuntimeCheckError("production dependency declarations are invalid")
    installed: dict[str, str] = {}
    mismatches: list[str] = []
    for name, version in sorted(requested.items()):
        installed_package = production / "node_modules" / name / "package.json"
        try:
            actual = _json(installed_package).get("version")
        except RuntimeCheckError:
            actual = None
        if actual != version:
            mismatches.append(f"{name}: expected {version}, installed {actual or 'missing'}")
        elif type(actual) is str:
            installed[name] = actual
    remotion_versions = {
        version for name, version in requested.items()
        if name == "remotion" or name.startswith("@remotion/")
    }
    if len(remotion_versions) != 1:
        mismatches.append("production Remotion family is not on one exact version")
    subtitle_files = ("Subtitles.tsx", "entry.tsx", "types.ts", "render.mjs")
    for name in subtitle_files:
        if not (root / "subtitles" / name).is_file():
            mismatches.append(f"subtitle adapter missing: subtitles/{name}")
    for name in ("entry.tsx", "types.ts", "render.mjs"):
        if not (root / "aroll-overlay" / name).is_file():
            mismatches.append(f"A-roll overlay adapter missing: aroll-overlay/{name}")
    try:
        paths_version = _json(root / "aroll-overlay/node_modules/@remotion/paths/package.json").get("version")
    except RuntimeCheckError:
        paths_version = None
    if paths_version != "4.0.520":
        mismatches.append("A-roll overlay requires @remotion/paths@4.0.520 in aroll-overlay/node_modules")

    manifest = _json(root / "upstream-manifest.json")
    latest_package = _json(upstream / "runtime" / "package.json")
    optional_tts = upstream / "scripts" / "tts_fishaudio.py"
    workbench_ready = all((upstream / "workbench" / path).is_file() for path in (
        "src/overridesSync.ts", "src/kouboImport.ts", "scripts/link-project.sh"
    ))
    if not workbench_ready:
        mismatches.append("TalkCraft workbench entrypoint missing")
    if mismatches:
        raise RuntimeCheckError("; ".join(mismatches))
    _check_identity(root, production)
    _check_closure_files(production, _json(production / "closure-manifest.json").get("files"))
    return {
        "schema_version": "talkcraft-runtime-health/v1",
        "status": "ok",
        "subtitle_adapter": "video-talkcraft-subtitles-adapter/v1",
        "aroll_overlay_adapter": "talkcraft-aroll-overlay-v1",
        "production_runtime": {
            "remotion": next(iter(remotion_versions)),
            "dependency_count": len(installed),
            "qualification_sensitive": True,
            "automatic_upgrade": False,
        },
        "upstream_baseline": {
            "commit": manifest.get("source", {}).get("commit"),
            "shared_runtime_remotion": latest_package.get("dependencies", {}).get("remotion"),
            "workbench_bidirectional_overrides": workbench_ready,
            "fish_audio_optional": optional_tts.is_file(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    try:
        result = check_runtime(arguments.root.resolve(strict=True))
    except RuntimeCheckError as error:
        print(json.dumps({"status": "fail", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

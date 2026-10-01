#!/usr/bin/env python3
"""Ensure pinned upstream visual Skills exist inside this project."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile


SOURCES = {
    "lemo-opuscar": {
        "url": "https://github.com/lemomo-ai/lemo-opuscar.git",
        "commit": "f3c590dffab39419e2f3018416706e046986fe11",
        "files": ("plugin/skills/lemo-opuscar/SKILL.md", "AGENTS.md",
                  "DIRECTOR.md", "TECHNIQUE.md", "styles/README.md",
                  "core/render/video.mjs", "core/lib.js", "package-lock.json"),
    },
    "onetake": {
        "url": "https://github.com/feitangyuan/onetake.git",
        "commit": "cf09bde3e392c9aa32c4157f80cdbe1fa556685e",
        "files": ("SKILL.md", "lib/motion.js", "templates/comp.html",
                  "scripts/render.py", "scripts/probe.py"),
    },
    "doudou-remotion-whiteboard": {
        "url": "https://github.com/undsky/doudou-remotion-whiteboard-skill.git",
        "commit": "d41f61c889c315b2a590fee61db3a62cf003adc9",
        "files": ("SKILL.md", "index.ts", "components/HandDrawnShapes.tsx",
                  "components/PencilFollower.tsx", "recipes/index.ts",
                  "recipes/01-pencil-sketch.tsx"),
    },
    "gbro-collage-broll": {
        "url": "https://github.com/pyang5166/gbro-collage-broll.git",
        "commit": "a1a4ee2e2abf7d44e460026b706d0c72c2cf8a91",
        "files": ("SKILL.md",),
    },
    "muyang-flat-animation": {
        "url": "https://github.com/yokel1121/muyang-flat-animation.git",
        "commit": "d864f1472866b3f724973385f40c0ddb6159dc38",
        "files": ("muyang-flat-animation/SKILL.md",
                  "muyang-flat-animation/references/style-guide.md",
                  "muyang-flat-animation/references/motion-grammar.md"),
    },
}


class VisualBrollDependencyError(RuntimeError):
    """The selected visual Skill is missing or differs from the tested source."""


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(["git", *arguments], check=False, capture_output=True,
                                text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VisualBrollDependencyError("git is unavailable or timed out") from error
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise VisualBrollDependencyError(detail[-1] if detail else "git command failed")
    return result.stdout.strip()


def _validate_repo(path: Path, source: dict) -> None:
    if path.is_symlink() or not path.is_dir():
        raise VisualBrollDependencyError(f"visual Skill is not a directory: {path}")
    for name in source["files"]:
        file = path / name
        if file.is_symlink() or not file.is_file():
            raise VisualBrollDependencyError(f"visual Skill instruction is missing: {file}")
    if _git("-C", str(path), "rev-parse", "HEAD") != source["commit"]:
        raise VisualBrollDependencyError(f"visual Skill commit changed: {path}")
    if _git("-C", str(path), "status", "--porcelain", "--", *source["files"]):
        raise VisualBrollDependencyError(f"visual Skill instructions have local changes: {path}")


def ensure(project_root: Path, skill_id: str) -> dict[str, str]:
    root = project_root.resolve(strict=True)
    if not (root / "edit/hd/tools/state.py").is_file():
        raise VisualBrollDependencyError(f"not a talking-head project: {root}")
    source = SOURCES[skill_id]
    vendor = root / "skill-development/vendor"
    if vendor.is_symlink() or (vendor.exists() and not vendor.is_dir()):
        raise VisualBrollDependencyError(f"unsafe vendor directory: {vendor}")
    vendor.mkdir(parents=True, exist_ok=True)
    if not vendor.resolve().is_relative_to(root):
        raise VisualBrollDependencyError(f"vendor directory escapes the project: {vendor}")
    lock_fd = os.open(vendor / ".visual-broll-install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        destination = vendor / skill_id
        if destination.exists() or destination.is_symlink():
            _validate_repo(destination, source)
            status = "already_available"
        else:
            with tempfile.TemporaryDirectory(prefix=".visual-broll-install-", dir=vendor) as temporary:
                staged = Path(temporary) / skill_id
                _git("clone", "--depth", "1", "--no-tags", source["url"], str(staged))
                if _git("-C", str(staged), "rev-parse", "HEAD") != source["commit"]:
                    _git("-C", str(staged), "fetch", "--depth", "1", "origin", source["commit"])
                    _git("-C", str(staged), "checkout", "--detach", source["commit"])
                _validate_repo(staged, source)
                staged.rename(destination)
                status = "installed"
    return {"status": status, "skill_id": skill_id,
            "path": str(destination), "commit": source["commit"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--skill", required=True, choices=tuple(SOURCES))
    args = parser.parse_args()
    try:
        result = ensure(args.project_root, args.skill)
        if args.skill in {"lemo-opuscar", "onetake"}:
            prepare_scene_runtime(args.project_root.resolve(), args.skill)
            result["runtime_status"] = "callable"
    except (OSError, VisualBrollDependencyError) as error:
        parser.exit(2, f"visual B-roll Skill unavailable: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def prepare_scene_runtime(project_root: Path, skill_id: str) -> None:
    """Prepare only missing local render dependencies; never run upstream auto-update setup."""
    from upstream_scene_adapter import check_runtime, ONETAKE_PACKAGES
    root = project_root / "skill-development/vendor" / skill_id
    if _git("-C", str(root), "status", "--porcelain", "--untracked-files=no"):
        raise VisualBrollDependencyError("upstream source has local changes; runtime preparation stopped")
    try:
        if skill_id == "lemo-opuscar":
            if not (root / "node_modules/playwright-core/package.json").is_file():
                subprocess.run(["npm", "ci", "--ignore-scripts"], cwd=root, check=True, timeout=240)
        else:
            python = root / ".venv/bin/python"
            if not python.exists():
                base = shutil.which("python3.12")
                if not base:
                    raise VisualBrollDependencyError("Python 3.12 is required for the project render venv")
                subprocess.run([base, "-m", "venv", str(root / ".venv")], check=True, timeout=60)
            modules = "import playwright,numpy,scipy,PIL,matplotlib,fontTools,brotli"
            if subprocess.run([str(python), "-c", modules], capture_output=True).returncode:
                subprocess.run([str(python), "-m", "pip", "install",
                    *[f"{name}=={version}" for name, version in ONETAKE_PACKAGES.items()]], check=True, timeout=240)
            browser = subprocess.run([str(python), "-c",
                "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); "
                "b=p.chromium.launch(); b.close(); p.stop()"], capture_output=True)
            if browser.returncode:
                # Install the upstream browser, not an alternative renderer or cloud provider.
                subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True, timeout=240)
        check_runtime(project_root, skill_id)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise VisualBrollDependencyError(f"project-only scene runtime is unavailable: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())

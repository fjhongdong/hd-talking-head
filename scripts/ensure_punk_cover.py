#!/usr/bin/env python3
"""Ensure the tested Punk cover Skill exists in this project's vendor directory."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path


REPO_URL = "https://github.com/adrianpunk/Punk-Skill.git"
PINNED_COMMIT = "3fe93635e8842ca4f77ae472b8bb1c5a35b4a7d8"
REQUIRED_FILES = (
    "skills/punk-cover/SKILL.md",
    "skills/punk-cover/references/style-catalog.md",
    "skills/punk-cover/references/platform-catalog.md",
    "skills/punk-cover/references/cover-prompt-blueprint.md",
    "styles/interleaved-title-editorial-poster/META.md",
    "styles/interleaved-title-editorial-poster/STYLE.md",
)


class PunkCoverInstallError(RuntimeError):
    """The project-local cover dependency is absent or unsafe to use."""


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments], capture_output=True, text=True,
            check=False, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PunkCoverInstallError("git is unavailable or timed out") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise PunkCoverInstallError(detail[-1] if detail else "git command failed")
    return result.stdout.strip()


def _validate(repo: Path) -> None:
    if repo.is_symlink() or not repo.is_dir():
        raise PunkCoverInstallError(f"Punk dependency is not a directory: {repo}")
    missing = [name for name in REQUIRED_FILES if not (repo / name).is_file()]
    if missing:
        raise PunkCoverInstallError(f"Punk dependency is incomplete: {', '.join(missing)}")
    if _git("-C", str(repo), "rev-parse", "HEAD") != PINNED_COMMIT:
        raise PunkCoverInstallError(f"Punk dependency version differs from tested commit: {repo}")
    if _git("-C", str(repo), "status", "--porcelain", "--", *REQUIRED_FILES):
        raise PunkCoverInstallError(f"Punk dependency has local changes: {repo}")


def ensure_punk_cover(project_root: Path) -> dict[str, str]:
    root = project_root.expanduser().resolve(strict=True)
    if not (root / "edit/hd/tools/state.py").is_file():
        raise PunkCoverInstallError(f"not a talking-head project root: {root}")
    development = root / "skill-development"
    if development.is_symlink() or (development.exists() and not development.is_dir()):
        raise PunkCoverInstallError(f"Skill development directory is unsafe: {development}")
    vendor = development / "vendor"
    if vendor.is_symlink() or (vendor.exists() and not vendor.is_dir()):
        raise PunkCoverInstallError(f"vendor directory is unsafe: {vendor}")
    vendor.mkdir(parents=True, exist_ok=True)
    if not vendor.resolve().is_relative_to(root):
        raise PunkCoverInstallError(f"vendor directory escapes the project: {vendor}")
    lock_path = vendor / ".punk-cover-install.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        destination = vendor / "Punk-Skill"
        if destination.exists() or destination.is_symlink():
            _validate(destination)
            return {"status": "already_available", "path": str(destination), "commit": PINNED_COMMIT}
        with tempfile.TemporaryDirectory(prefix=".punk-cover-install-", dir=vendor) as temporary:
            staged = Path(temporary) / "Punk-Skill"
            _git("clone", "--depth", "1", "--no-tags", REPO_URL, str(staged))
            if _git("-C", str(staged), "rev-parse", "HEAD") != PINNED_COMMIT:
                _git("-C", str(staged), "fetch", "--depth", "1", "origin", PINNED_COMMIT)
                _git("-C", str(staged), "checkout", "--detach", PINNED_COMMIT)
            _validate(staged)
            if destination.exists() or destination.is_symlink():
                _validate(destination)
                return {"status": "already_available", "path": str(destination), "commit": PINNED_COMMIT}
            staged.rename(destination)
    return {"status": "installed", "path": str(destination), "commit": PINNED_COMMIT}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = ensure_punk_cover(args.project_root)
    except (OSError, PunkCoverInstallError) as exc:
        parser.exit(2, f"Punk cover dependency unavailable: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

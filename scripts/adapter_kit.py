#!/usr/bin/env python3
"""Shared helpers for the native B-roll adapters.

Every function here freezes an existing per-adapter behavior byte-for-byte:
hash formulas, source-binding checks, tool discovery and the ffprobe
invocation. Adapters migrate to this module without changing any identity
value or error message. Modules pinned by the verified-template registry
(local_canonical / relation_motion / semantic_state adapters, and
huashu_motion_adapter via its execution_qa attachment) stay on their local
copies until their qualification is re-run. validate_source_binding
normalizes non-string inputs to ValueError with the adapter's own message;
doudou/talkcraft previously raised TypeError for those.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path


_HEX64 = re.compile(r"[a-f0-9]{64}")
_SEGMENT = re.compile(r"seg-[A-Za-z0-9_-]+")


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity_from_bytes(paths) -> str:
    """sha256 over the file bytes joined by NUL separators, streamed."""
    digest = hashlib.sha256()
    for index, path in enumerate(paths):
        if index:
            digest.update(b"\0")
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def identity_from_digests(paths, header_lines=()) -> str:
    """sha256 over header lines plus per-file hex digests, newline-joined."""
    parts = [str(line) for line in header_lines]
    parts += [sha256_file(path) for path in paths]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def validate_source_binding(source, message):
    """Raise ValueError(message) unless source is the frozen four-field tuple."""
    if (type(source) is not dict
            or set(source) != {"aroll_sha256", "segment_id", "start", "end"}
            or not _HEX64.fullmatch(str(source["aroll_sha256"]))
            or not _SEGMENT.fullmatch(str(source["segment_id"]))
            or any(type(source[key]) not in (int, float) or not math.isfinite(source[key])
                   for key in ("start", "end"))
            or not 0 <= source["start"] < source["end"]):
        raise ValueError(message)


def find_tool(*candidates):
    """First existing executable among names (PATH lookup) and file paths."""
    for candidate in candidates:
        found = shutil.which(candidate) if not str(candidate).startswith("/") else candidate
        path = Path(found) if found else None
        if path and path.is_file() and path.stat().st_mode & 0o111:
            return path
    return None


def browser_candidates(project_root):
    """Chrome/headless-shell candidates, project runtime first."""
    project = Path(project_root)
    shell = ".remotion/chrome-headless-shell/{platform}/chrome-headless-shell-{platform}/chrome-headless-shell"
    names = [
        project / shell.format(platform="mac-arm64"),
        project / shell.format(platform="linux-x64"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    resolved = [name for name in names if name.is_file()]
    for which_name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(which_name)
        if found:
            resolved.append(Path(found))
    return resolved


def git_checkout_matches(repo, expected_commit, message):
    """Raise ValueError(message) unless repo is exactly expected_commit, clean."""
    git = shutil.which("git") or "/usr/bin/git"
    head = subprocess.check_output([git, "-C", str(repo), "rev-parse", "HEAD"],
                                   text=True).strip()
    dirty = subprocess.check_output(
        [git, "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], text=True)
    if head != expected_commit or dirty:
        raise ValueError(message)


def ffprobe_json(ffprobe_executable, path, timeout=20):
    """Run the canonical probe invocation and return the parsed JSON."""
    inherited = (int(Path(path).name),) if Path(path).parent == Path("/dev/fd") else ()
    result = subprocess.run(
        [str(ffprobe_executable), "-v", "error", "-count_frames", "-show_streams",
         "-show_format", "-of", "json", str(path)],
        pass_fds=inherited, capture_output=True, text=True, check=True, timeout=timeout)
    return json.loads(result.stdout)


def npm_ci_seed(source, target, *, sentinel, label, timeout=240):
    """Copy pinned package files and npm ci once; refuse configuration drift."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        dst = target / name
        if dst.exists() and dst.read_bytes() != (source / name).read_bytes():
            raise ValueError(f"Existing {label} dependency configuration differs")
        if not dst.exists():
            shutil.copyfile(source / name, dst)
    if not Path(sentinel).is_file():
        subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                       cwd=target, check=True, timeout=timeout)

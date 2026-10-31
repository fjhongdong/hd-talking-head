"""Restore bundled identities and complete pinned source snapshots offline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def _restore_source_snapshot(package: Path, entry: dict, source: Path) -> None:
    """Restore a complete pinned tree only when its source directory is absent."""
    with tempfile.TemporaryDirectory(prefix="hd-source-tree-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        digest = hashlib.sha256()
        with archive.open("wb") as output:
            for name in entry["archives"]:
                part = (package / name).resolve(strict=True)
                if not part.is_relative_to(package):
                    raise ValueError("source archive must be inside the Skill")
                with part.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block); output.write(block)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("bundled complete source archive changed")
        staging = (Path(temporary) / "source").resolve()
        staging.mkdir()
        expected = set(entry["files"]) | set(entry.get("symlinks", {}))
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            actual = set()
            for member in members:
                relative = Path(member.name)
                target = (staging / relative).resolve()
                if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                        or not target.is_relative_to(staging) or member.islnk()
                        or not (member.isfile() or member.isdir() or member.issym())):
                    raise ValueError("invalid bundled complete source path")
                if member.issym():
                    link = Path(member.linkname)
                    if (link.is_absolute() or not (target.parent / link).resolve().is_relative_to(staging)
                            or entry.get("symlinks", {}).get(member.name) != member.linkname):
                        raise ValueError("invalid bundled source symlink")
                if not member.isdir():
                    if member.name in actual:
                        raise ValueError("duplicate bundled source file")
                    actual.add(member.name)
            if actual != expected:
                raise ValueError("bundled source archive differs from its full snapshot")
            bundle.extractall(staging, filter="data")
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, source, symlinks=True)


def bundled_source_revision(package: Path, source: Path) -> str | None:
    """Verify a packaged source subset without borrowing the parent Git identity."""
    package, source = package.resolve(), source.resolve()
    if not source.is_relative_to(package):
        return None
    index = json.loads((package / "source-repositories/index.json").read_text())
    entries = [entry for entry in index["repositories"]
               if entry["path"] == source.relative_to(package).as_posix() and "files" in entry]
    if not entries:
        return None
    if len(entries) != 1 or not entries[0]["files"]:
        raise ValueError("bundled source snapshot is invalid")
    entry = entries[0]
    for relative, expected in entry["files"].items():
        path = source / relative
        if path.is_symlink() or not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError("bundled source file is missing: " + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("bundled source file changed: " + relative)
    if "archives" in entry:
        actual = {p.relative_to(source).as_posix() for p in source.rglob("*")
                  if p.is_file() and not p.is_symlink()}
        links = {p.relative_to(source).as_posix(): str(p.readlink())
                 for p in source.rglob("*") if p.is_symlink()}
        if (actual != set(entry["files"]) or links != entry.get("symlinks", {})
                or any(not (source / name).resolve().is_relative_to(source) for name in links)):
            raise ValueError("bundled complete source tree changed")
    return entry["commit"]


def prepare_sources(package: Path) -> list[dict]:
    package = package.resolve()
    index = json.loads((package / "source-repositories/index.json").read_text())
    results = []
    for entry in index["repositories"]:
        source = (package / entry["path"]).resolve()
        if not source.is_relative_to(package):
            raise ValueError("bundled source path must stay inside the Skill")
        if "files" in entry and "archives" in entry and not source.exists():
            _restore_source_snapshot(package, entry, source)
        if not source.is_dir():
            raise ValueError("bundled source directory is missing: " + entry["path"])
        if "files" in entry:
            revision = bundled_source_revision(package, source)
            results.append({"path": entry["path"], "commit": revision, "status": "ready"})
            continue
        if not (source / ".git").exists():
            with tempfile.TemporaryDirectory(prefix="hd-source-identity-") as temporary:
                archive = Path(temporary) / "source.tar.gz"
                digest = hashlib.sha256()
                with archive.open("wb") as output:
                    for name in entry["archives"]:
                        path = (package / name).resolve()
                        if not path.is_relative_to(package):
                            raise ValueError("source archive must be inside the Skill")
                        with path.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                                output.write(block)
                if digest.hexdigest() != entry["sha256"]:
                    raise ValueError("bundled source identity archive changed")
                staging = Path(temporary) / "unpacked"
                with tarfile.open(archive) as bundle:
                    for member in bundle.getmembers():
                        path = Path(member.name)
                        if (path.is_absolute() or ".." in path.parts or not path.parts
                                or path.parts[0] != ".git" or member.issym() or member.islnk()
                                or not (member.isfile() or member.isdir())):
                            raise ValueError("invalid bundled Git metadata")
                    bundle.extractall(staging, filter="data")
                shutil.copytree(staging / ".git", source / ".git")
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "--show-toplevel", "HEAD"], text=True
        ).splitlines()
        if actual != [str(source), entry["commit"]]:
            raise ValueError("bundled source Git identity differs: " + entry["path"])
        results.append({"path": entry["path"], "commit": entry["commit"], "status": "ready"})
    return results

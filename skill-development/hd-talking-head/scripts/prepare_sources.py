"""Restore bundled upstream Git identities without fetching or changing source files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def prepare_sources(package: Path) -> list[dict]:
    package = package.resolve()
    index = json.loads((package / "source-repositories/index.json").read_text())
    results = []
    for entry in index["repositories"]:
        source = (package / entry["path"]).resolve()
        if not source.is_relative_to(package) or not source.is_dir():
            raise ValueError("bundled source directory is missing: " + entry["path"])
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

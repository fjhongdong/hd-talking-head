"""Compare the project-local vendor sources with their official upstream heads."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.request import ProxyHandler, build_opener

from package_paths import PACKAGE_ROOT


SOURCE_URLS = {
    "vendor/DataMagic": "https://github.com/HKUSTDial/DataMagic.git",
    "vendor/bang-motion": "https://github.com/bangtutorial/bang-motion.git",
    "vendor/barty-motion-graphics": "https://github.com/Barty-Bart/motion-graphics.git",
    "vendor/lemo-wake": "https://github.com/lemomo-ai/lemo-wake.git",
}


def source_entries(package: Path) -> list[dict]:
    dependencies = json.loads((package / "references/dependency-manifest.json").read_text(encoding="utf-8"))
    repositories = SOURCE_URLS | {
        install["destination"]: install["source"]
        for row in dependencies["dependencies"]
        if (install := row.get("install")) and install["method"] == "project-local-clone"
    }
    index = json.loads((package / "archives/sources/index.json").read_text(encoding="utf-8"))
    entries = {
        row["path"]: {
            "path": row["path"], "installed_commit": row["commit"],
            "repository": row.get("repository") or repositories.get(row["path"]),
        }
        for row in index["repositories"]
    }
    talkcraft = json.loads((package / "references/talkcraft-native-source.json").read_text(encoding="utf-8"))
    path = talkcraft["source_root"]
    entries[path] = {"path": path, "installed_commit": talkcraft["commit"], "repository": talkcraft["repository"]}
    for directory in sorted((package / "vendor").iterdir()):
        if directory.is_dir() and not directory.name.startswith("."):
            path = directory.relative_to(package).as_posix()
            entries.setdefault(path, {"path": path, "installed_commit": None, "repository": repositories.get(path)})
    return list(entries.values())


def upstream_head(repository: str) -> tuple[str | None, str]:
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", repository):
        raise ValueError("missing supported official upstream URL")
    slug = repository.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")
    archive_url = f"https://codeload.github.com/{slug}/tar.gz/HEAD"
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(archive_url, timeout=6) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
            # Git puts the archive's exact commit in the global PAX header.
            revision = archive.pax_headers.get("comment", "")
        if re.fullmatch(r"[0-9a-f]{40}", revision):
            return None, revision
    except (OSError, tarfile.TarError):
        pass

    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    args = ["git", "ls-remote", "--symref", repository, "HEAD"]
    try:
        result = subprocess.run(args, env=environment, text=True, capture_output=True, timeout=8)
        if result.returncode:
            direct = {k: v for k, v in environment.items() if k.casefold() not in {"https_proxy", "http_proxy", "all_proxy"}}
            result = subprocess.run(
                [args[0], "-c", "http.https://github.com.proxy=", "-c", "http.proxy=", *args[1:]],
                env=direct, text=True, capture_output=True, timeout=8,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("official upstream is unavailable") from error
    branch = re.search(r"^ref: refs/heads/([^\t]+)\tHEAD$", result.stdout, re.M)
    revision = re.search(r"^([0-9a-f]{40})\tHEAD$", result.stdout, re.M)
    if result.returncode or branch is None or revision is None:
        raise ValueError("official upstream HEAD could not be read")
    return branch[1], revision[1]


def vendor_status(package: Path, sources: list[str] | None = None) -> list[dict]:
    entries = source_entries(package)
    if sources:
        names = {source if source.startswith("vendor/") else f"vendor/{source}" for source in sources}
        if unknown := names - {row["path"] for row in entries}:
            raise ValueError("unknown vendor source: " + ", ".join(sorted(unknown)))
        entries = [row for row in entries if row["path"] in names]

    def compare(row):
        if not row["repository"]:
            return {**row, "status": "unregistered"}
        try:
            branch, revision = upstream_head(row["repository"])
        except ValueError as error:
            return {**row, "status": "unreachable", "reason": str(error)}
        if not (package / row["path"]).is_dir():
            status = "missing"
        elif not row["installed_commit"]:
            status = "unregistered"
        else:
            status = "current" if row["installed_commit"] == revision else "update_available"
        return {**row, "branch": branch, "upstream_commit": revision, "status": status}

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(compare, entries))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="optional names under vendor/")
    args = parser.parse_args()
    try:
        rows = vendor_status(PACKAGE_ROOT, args.sources)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({"vendor": str(PACKAGE_ROOT / "vendor"), "sources": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regenerate release-manifest.json from the current package contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify_skill_release import MANIFEST, REQUIRED, file_hash, package_files
from refresh_capability_pins import INDEX, collect_stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True,
                        help="new unique release id, e.g. 2026-01-01-topic-v145")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    stale = collect_stale(root, index)
    if stale:
        parser.error("capability source pins are stale; review and refresh before release: "
                     + ", ".join(item["candidate_id"] for item in stale))
    files = package_files(root)
    missing = REQUIRED - set(files)
    if missing:
        parser.error("required attachments missing: " + ", ".join(sorted(missing)))
    manifest = {
        "schema_version": 1,
        "release_id": args.release_id,
        "files": {name: file_hash(path) for name, path in sorted(files.items())},
    }
    (root.parents[1] / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({"status": "written", "release_id": args.release_id,
                      "files": len(files)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

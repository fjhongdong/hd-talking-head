#!/usr/bin/env python3
"""Regenerate release-manifest.json from the current package contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify_skill_release import MANIFEST, REQUIRED, file_hash, package_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True,
                        help="new unique release id, e.g. 2026-01-01-topic-v145")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = package_files(root)
    missing = REQUIRED - set(files)
    if missing:
        parser.error("required attachments missing: " + ", ".join(sorted(missing)))
    manifest = {
        "schema_version": 1,
        "release_id": args.release_id,
        "files": {name: file_hash(path) for name, path in sorted(files.items())},
    }
    (root / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({"status": "written", "release_id": args.release_id,
                      "files": len(files)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

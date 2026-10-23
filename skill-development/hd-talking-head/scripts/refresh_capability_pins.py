#!/usr/bin/env python3
"""Audit and refresh reviewed_sources pins in the motion capability index.

Default mode is read-only: it reports every profile whose pinned evidence
digest no longer matches the file on disk. ``--write`` re-pins stale entries
in place, preserving the index JSON format byte-for-byte apart from the
updated digests. Per the capability library contract the maintainer reviews
the reported sources first; this tool only records the decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


INDEX = "references/motion-capability-index.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_stale(skill_root: Path, index: dict) -> list[dict]:
    project_root = skill_root.parents[1]
    index_reference = skill_root.relative_to(project_root).as_posix() + "/" + INDEX
    stale = []
    seen: dict[str, str] = {}
    candidate_ids: set[str] = set()
    duplicates: set[str] = set()
    for profile in index.get("profiles", []):
        candidate_id = profile.get("candidate_id", "<unknown>")
        if candidate_id in candidate_ids:
            duplicates.add(candidate_id)
        candidate_ids.add(candidate_id)
        for reference, pin in profile.get("reviewed_sources", {}).items():
            if reference == index_reference:
                raise SystemExit(f"self-referential pin is invalid: {reference}")
            if reference not in seen:
                path = project_root / reference
                if not path.is_file():
                    raise SystemExit(f"missing evidence file, not a re-pin case: {reference}")
                seen[reference] = sha256_file(path)
            current = seen[reference]
            if current != pin:
                stale.append({
                    "candidate_id": candidate_id,
                    "reference": reference,
                    "pinned": pin,
                    "current": current,
                })
    if duplicates:
        print(f"warning: duplicate candidate_id entries collapse at runtime: {sorted(duplicates)}",
              file=sys.stderr)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true",
                        help="apply the reported digests to the index (default: report only)")
    args = parser.parse_args()

    index_path = args.skill_root / INDEX
    index = json.loads(index_path.read_text(encoding="utf-8"))
    stale = collect_stale(args.skill_root, index)

    if not stale:
        print(json.dumps({"status": "current", "stale_pins": 0}, ensure_ascii=False))
        return 0

    for item in stale:
        print(f"[{item['candidate_id']}] {item['reference']}")
        print(f"    pinned  {item['pinned']}")
        print(f"    current {item['current']}")

    if not args.write:
        print(json.dumps({"status": "stale", "stale_pins": len(stale),
                          "hint": "re-run with --write after reviewing the sources"},
                         ensure_ascii=False))
        return 1

    for profile in index["profiles"]:
        for item in stale:
            if item["candidate_id"] == profile.get("candidate_id"):
                sources = profile.get("reviewed_sources", {})
                if sources.get(item["reference"]) == item["pinned"]:
                    sources[item["reference"]] = item["current"]
    text = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    if text == index_path.read_text(encoding="utf-8"):
        raise SystemExit("write produced no change; refusing to claim success")
    index_path.write_text(text, encoding="utf-8")
    json.loads(index_path.read_text(encoding="utf-8"))
    print(json.dumps({"status": "written", "stale_pins": len(stale)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

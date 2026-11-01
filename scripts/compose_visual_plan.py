#!/usr/bin/env python3
"""Read-only visual preparation helpers; the former plan-composition CLI is retired.

Use the existing semantic match/review/assign workflow for visual planning,
then prepare the selected route's native inputs through its own adapter.
"""

from __future__ import annotations

import json
from pathlib import Path


def calibration_key(start: float, end: float) -> str:
    """Return the shared three-decimal identity used by calibrator output."""
    return f"{start:.3f},{end:.3f}"


def load_calibration(path: Path) -> dict[str, dict]:
    """Load calibration by exact window identity and reject ambiguous keys."""
    if not path.is_file():
        return {}
    result = {}
    for raw_key, avatar in json.loads(path.read_text()).items():
        try:
            lo, hi = (float(x) for x in raw_key.split(","))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"invalid avatar calibration key: {raw_key!r}") from exc
        key = calibration_key(lo, hi)
        if key in result:
            raise SystemExit(f"ambiguous avatar calibration window: {key}")
        result[key] = avatar
    return result


def visual_text_draft_entry(text: str, items: list[dict], content_item_ids: list[str],
                            segment_id: str) -> dict:
    """Build a pending screen-text candidate without claiming human review."""
    import re
    alnums = set(re.findall(r"[A-Za-z0-9]+", text))
    source_ref = source_quote = None
    for item in items:
        if item["id"] not in content_item_ids:
            continue
        source_text = item["source_text"]
        if (text in source_text or source_text in text
                or (alnums and alnums <= set(re.findall(r"[A-Za-z0-9]+", source_text)))):
            source_ref, source_quote = "item:" + item["id"], source_text
            break
    return {
        "segment_id": segment_id,
        "text": text,
        "source_ref": source_ref,
        "source_quote": source_quote,
        "candidate_source_refs": ["item:" + item["id"] for item in items
                                   if item["id"] in content_item_ids],
        "review_status": "pending",
    }


def _word_cut_times(job_dir: Path):
    transcript = json.loads((job_dir / "05-speech-cleanup/word-transcript.json").read_text())
    words = transcript["words"]
    cuts = json.loads((job_dir / "06-edit-structure/timeline-map.json").read_text())["segments"]
    for word in words:
        word["cut"] = None
        for cut in cuts:
            if cut["source_start"] <= word["start"] and word["end"] <= cut["source_end"]:
                word["cut"] = cut["timeline_start"] + (word["start"] - cut["source_start"])
                break
        word["cut_end"] = (word["cut"] + (word["end"] - word["start"])
                           if word["cut"] is not None else None)
    return words


def quantize_windows(resolved: list[dict], duration: float, fps: int = 24) -> list[dict]:
    """Quantize beat windows to frame boundaries without zero-length spans."""
    limit = round(duration * fps) / fps
    result = [dict(entry) for entry in resolved]
    for position, entry in enumerate(result):
        upper = (round(result[position + 1]["wa"] * fps) / fps
                 if position + 1 < len(result) else limit)
        entry["qs"] = max(0.0, min(round(entry["wa"] * fps) / fps, upper))
    for position, entry in enumerate(result):
        lower = entry["qs"]
        upper = (result[position + 1]["qs"]
                 if position + 1 < len(result) else limit)
        entry["qe"] = max(lower + 1 / fps, min(round(entry["wb"] * fps) / fps, upper))
    for a, b in zip(result, result[1:]):
        if a["qe"] > b["qs"] + 1e-6:
            a["qe"] = b["qs"]
    for entry in result:
        if (entry["qs"] >= limit - 1e-9 or entry["qe"] > limit + 1e-9
                or entry["qe"] - entry["qs"] < 1 / fps - 1e-9):
            raise ValueError(f"beat {entry.get('index')} quantizes to fewer than one frame")
    return result


def main() -> int:
    raise SystemExit(
        "compose_visual_plan.py CLI 已停用：先通过现有 "
        "select_motion_capabilities.py match 与 select_broll_skills.py assign/check "
        "完成语义匹配、候选评审和联合分配，再由所选原生 adapter 准备当前 Job 输入。"
        "待审草稿不能代替正式校验。"
    )


if __name__ == "__main__":
    raise SystemExit(main())

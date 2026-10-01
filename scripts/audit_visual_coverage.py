#!/usr/bin/env python3
"""Show the actual subtitle and visual rhythm of a rendered Job plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(visual: dict, subtitles: dict, window_seconds: float = 20.0) -> dict:
    segments = visual["segments"]
    cues = subtitles["render_plan"]["cues"]
    duration = float(visual["duration"])
    windows = []
    cursor = 0.0
    while cursor < duration:
        end = min(cursor + window_seconds, duration)
        in_window = [s for s in segments if s["start"] < end and s["end"] > cursor]
        heard = [c for c in cues if c["start"] < end and c["end"] > cursor]
        broll = [s for s in in_window if s["visual_strategy"]["composition"]["family"] not in {"no_broll", "aroll_with_overlay"}]
        overlays = [s for s in in_window if s["visual_strategy"]["composition"]["family"] == "aroll_with_overlay"]
        windows.append({
            "start": round(cursor, 3),
            "end": round(end, 3),
            "spoken_text": "".join(c["text"] for c in heard),
            "highlight_count": sum(bool(c["emphasis_words"]) for c in heard),
            "broll_ids": [s["segment_id"] for s in broll],
            "overlay_ids": [s["segment_id"] for s in overlays],
            "pure_aroll_seconds": round(sum(
                max(0.0, min(s["end"], end) - max(s["start"], cursor))
                for s in in_window
                if s["visual_strategy"]["composition"]["family"] == "no_broll"
            ), 3),
        })
        cursor = end

    overlays = [s for s in segments if s["visual_strategy"]["composition"]["family"] == "aroll_with_overlay"]
    broll_segments = sorted(
        (s for s in segments if s["visual_strategy"]["composition"]["family"]
         not in {"no_broll", "aroll_with_overlay"}),
        key=lambda s: s["start"],
    )
    # Count the union of B-roll windows; overlays do not end an A-roll gap.
    intervals = []
    for segment in broll_segments:
        start, end = float(segment["start"]), float(segment["end"])
        if intervals and start <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    broll_seconds = sum(end - start for start, end in intervals)
    gaps = []
    previous_end = 0.0
    for start, end in intervals:
        if start > previous_end:
            gaps.append({"start": previous_end, "end": start})
        previous_end = end
    if previous_end < duration:
        gaps.append({"start": previous_end, "end": duration})
    longest_gap = max(gaps, key=lambda g: g["end"] - g["start"], default=None)
    return {
        "duration": duration,
        "highlight_count": sum(bool(c["emphasis_words"]) for c in cues),
        "broll_count": len(broll_segments),
        "broll_seconds": round(broll_seconds, 3),
        "broll_percent": round(broll_seconds / duration * 100, 2) if duration else 0.0,
        "first_broll_start": broll_segments[0]["start"] if broll_segments else None,
        "longest_without_broll_seconds": round(longest_gap["end"] - longest_gap["start"], 3) if longest_gap else 0.0,
        "longest_without_broll_interval": longest_gap,
        "overlay_count": len(overlays),
        "longest_pure_aroll_seconds": round(max((s["end"] - s["start"] for s in segments if s["visual_strategy"]["composition"]["family"] == "no_broll"), default=0.0), 3),
        "overlay_speech": [{
            "segment_id": s["segment_id"],
            "start": s["start"],
            "end": s["end"],
            "intent": s["visual_intent"]["statement"],
            "spoken_text": "".join(c["text"] for c in cues if c["start"] < s["end"] and c["end"] > s["start"]),
        } for s in overlays],
        "windows": windows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-plan", type=Path, required=True)
    parser.add_argument("--subtitle-plan", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=20.0)
    args = parser.parse_args()
    if args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")
    visual = json.loads(args.visual_plan.read_text(encoding="utf-8"))
    subtitles = json.loads(args.subtitle_plan.read_text(encoding="utf-8"))
    print(json.dumps(audit(visual, subtitles, args.window_seconds), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

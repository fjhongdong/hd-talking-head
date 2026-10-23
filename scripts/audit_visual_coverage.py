#!/usr/bin/env python3
"""Show the actual subtitle and visual rhythm of a rendered Job plan."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def require_aroll_window(visual: dict, start: float, end: float) -> list[str]:
    """Limit an overlay-only sample to existing A-roll, before any rendering."""
    if not all(math.isfinite(value) for value in (start, end)) or not 0 <= start < end:
        raise ValueError("Invalid A-roll sample window")
    cursor = start
    selected = []
    for segment in sorted(visual["segments"], key=lambda row: row["start"]):
        if segment["end"] <= start or segment["start"] >= end:
            continue
        strategy = segment["visual_strategy"]
        if strategy["mode"] != "none" or strategy["composition"]["family"] not in {"no_broll", "aroll_with_overlay"}:
            raise ValueError(f"Overlay-only sample would replace B-roll: {segment['segment_id']}")
        if segment["start"] > cursor + 1e-6:
            raise ValueError("A-roll sample window contains an uncovered interval")
        cursor = max(cursor, min(segment["end"], end))
        selected.append(segment["segment_id"])
    if cursor < end - 1e-6 or not selected:
        raise ValueError("A-roll sample window is outside the approved visual plan")
    return selected


def audit(
    visual: dict,
    subtitles: dict,
    window_seconds: float = 20.0,
    content_analysis: dict | None = None,
    require_overlays: bool = False,
    require_density: bool = False,
    treatment: dict | None = None,
) -> dict:
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
    no_broll_segments = sorted(
        (s for s in segments if s["visual_strategy"]["composition"]["family"] == "no_broll"),
        key=lambda s: float(s["start"]),
    )
    pure_aroll_intervals = []
    for segment in no_broll_segments:
        start, end = float(segment["start"]), float(segment["end"])
        if pure_aroll_intervals and start <= pure_aroll_intervals[-1][1]:
            pure_aroll_intervals[-1][1] = max(pure_aroll_intervals[-1][1], end)
        else:
            pure_aroll_intervals.append([start, end])

    needs_review_items = []
    if content_analysis:
        items = content_analysis.get("analysis", {}).get("items", [])
        for item in items:
            if str(item.get("priority", "")).lower() not in {"critical", "high"}:
                continue
            item_id = item.get("id")
            matches = [s for s in segments if item_id in s.get("content_item_ids", [])]
            if not matches or all(
                s["visual_strategy"]["composition"]["family"] == "no_broll" for s in matches
            ):
                needs_review_items.append({
                    "id": item_id,
                    "priority": item.get("priority"),
                    "source_text": item.get("source_text", ""),
                    "matching_segments": [{
                        "segment_id": s["segment_id"],
                        "start": s["start"],
                        "end": s["end"],
                        "rationale": s["visual_strategy"].get("rationale", ""),
                    } for s in matches],
                })

    result = {
        "duration": duration,
        "highlight_count": sum(bool(c["emphasis_words"]) for c in cues),
        "broll_count": len(broll_segments),
        "broll_seconds": round(broll_seconds, 3),
        "broll_percent": round(broll_seconds / duration * 100, 2) if duration else 0.0,
        "first_broll_start": broll_segments[0]["start"] if broll_segments else None,
        "longest_without_broll_seconds": round(longest_gap["end"] - longest_gap["start"], 3) if longest_gap else 0.0,
        "longest_without_broll_interval": longest_gap,
        "overlay_count": len(overlays),
        "longest_pure_aroll_seconds": round(max((end - start for start, end in pure_aroll_intervals), default=0.0), 3),
        "overlay_speech": [{
            "segment_id": s["segment_id"],
            "start": s["start"],
            "end": s["end"],
            "intent": s["visual_intent"]["statement"],
            "spoken_text": "".join(c["text"] for c in cues if c["start"] < s["end"] and c["end"] > s["start"]),
        } for s in overlays],
        "windows": windows,
    }
    if content_analysis is not None:
        result["needs_review_items"] = needs_review_items
    blocking: list[str] = []
    if require_overlays and not overlays:
        blocking.append(
            "require_overlays is enabled, but the visual plan contains no aroll_with_overlay segments"
        )
    if require_density:
        # Density contract: first B-roll within 15s, no silent gap over 15s,
        # overlays never count as B-roll. The 50–65% ratio is a planning
        # reference, so a low ratio blocks only without a written note.
        gap_reasons = {}
        for row in (treatment or {}).get("broll_gap_reasons", []):
            if isinstance(row, dict) and isinstance(row.get("reason"), str) and row["reason"].strip():
                gap_reasons[(round(float(row.get("start", -1), 1)), round(float(row.get("end", -1), 1)))] = row["reason"]
        def _reasoned(interval):
            return gap_reasons.get((round(interval["start"], 1), round(interval["end"], 1)))
        if not broll_segments:
            blocking.append("density gate: the plan has no full-screen B-roll segment")
        else:
            first_start = broll_segments[0]["start"]
            if first_start > 15.0 and not gap_reasons.get((0.0, round(first_start, 1))):
                blocking.append(
                    "density gate: first B-roll starts after 15s "
                    f"({first_start:.1f}s) without a declared reason")
            for gap in gaps:
                if gap["end"] - gap["start"] > 15.0 and not _reasoned(gap):
                    blocking.append(
                        "density gate: no B-roll for "
                        f"{gap['end'] - gap['start']:.1f}s ({gap['start']:.1f}-{gap['end']:.1f}s) "
                        "without a declared reason")
            ratio = broll_seconds / duration * 100 if duration else 0.0
            if ratio < 40.0 and not str((treatment or {}).get("broll_ratio_note", "")).strip():
                blocking.append(
                    f"density gate: B-roll ratio is {ratio:.1f}% (planning reference 50-65%) "
                    "without a declared broll_ratio_note")
    result["blocking_issues"] = blocking
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-plan", type=Path, required=True)
    parser.add_argument("--subtitle-plan", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=20.0)
    parser.add_argument("--content-analysis", type=Path)
    parser.add_argument("--treatment", type=Path)
    parser.add_argument("--require-overlays", action="store_true")
    parser.add_argument("--require-density", action="store_true")
    args = parser.parse_args()
    if args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")
    visual = json.loads(args.visual_plan.read_text(encoding="utf-8"))
    subtitles = json.loads(args.subtitle_plan.read_text(encoding="utf-8"))
    content_analysis = (
        json.loads(args.content_analysis.read_text(encoding="utf-8"))
        if args.content_analysis else None
    )
    treatment = json.loads(args.treatment.read_text(encoding="utf-8")) if args.treatment else None
    result = audit(
        visual,
        subtitles,
        args.window_seconds,
        content_analysis=content_analysis,
        require_overlays=args.require_overlays,
        require_density=args.require_density,
        treatment=treatment,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["blocking_issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

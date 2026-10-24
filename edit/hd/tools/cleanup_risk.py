"""Conservative review hints over validated words and an unchanged edit plan.

This is not a semantic classifier or an authorization to delete audio. Callers
must validate words, the plan, and media bounds before invoking this module.
"""

from bisect import bisect_left, bisect_right
import re
import hashlib
from typing import Any


_PROTECTED = (
    ("negation", re.compile(r"不是|没有|不能|不|没|未|无|并非|否认")),
    ("qualifier", re.compile(r"大约|大概|约|仅|只|至少|至多|最多|最少|超过|不足|可能|也许|通常|部分")),
    ("number", re.compile(r"[0-9０-９]+(?:[.,．][0-9０-９]+)*%?|[零〇一二两三四五六七八九十百千万亿]+")),
    ("condition_or_cause", re.compile(r"如果|除非|只要|只有|否则|因为|所以|因此|导致|取决于|但是|然而")),
)
_SENTENCE_END = re.compile(r"[。！？!?；;\n]")
_INTERRUPTION = re.compile(r"(?:--+|—+|\.\.\.|…+)\s*$")
_UNIT_BOUNDARY = re.compile(r"(?:[。！？!?；;，,、\n]|--+|—+|\.\.\.|…+)\s*$")


def retained_repetitions(
    words: list[dict[str, Any]], plan: dict[str, Any], *, media_duration: float,
) -> list[dict[str, Any]]:
    """Find conservative, still-retained restart/repetition chains.

    This is review evidence only. It never changes the edit plan. Detection is
    based on retained word text and real punctuation/interruption markers, so
    keep-segment boundaries and ASR gaps cannot manufacture a candidate.
    """
    deleted = {
        index
        for segment in plan["segments"]
        if segment["action"] == "delete"
        for index in range(segment["word_start"], segment["word_end"])
    }
    cut_ranges = plan.get("reviewed_cut_ranges", [])
    retained = []
    for index, word in enumerate(words):
        if index in deleted:
            continue
        if any(
            cut["source_start"] <= word["start"]
            and cut["source_end"] >= word["end"]
            for cut in cut_ranges
        ):
            continue
        retained.append((index, word))
    if not retained:
        return []

    # Build units by character, because one ASR word may contain punctuation
    # and therefore contain two restart units itself.
    units: list[dict[str, Any]] = []
    current: list[tuple[int, dict[str, Any]]] = []
    chars: list[str] = []
    for word_index, word in retained:
        for char in str(word["text"]):
            current.append((word_index, word))
            chars.append(char)
            text = "".join(chars)
            if _UNIT_BOUNDARY.search(text):
                units.append({"items": current, "text": text})
                current, chars = [], []
    if current:
        units.append({"items": current, "text": "".join(chars)})

    result: list[dict[str, Any]] = []
    for left_index, left in enumerate(units):
        left_text = left["text"].strip()
        if len(left_text) < 2:
            continue
        # Only directly adjacent units are candidates.  A repeated topic much
        # later in the paragraph is not evidence of a verbal restart.
        for right in units[left_index + 1:left_index + 2]:
            right_text = right["text"].strip()
            # Source gaps may already have been cut out of the EDL.  Only
            # retained adjacency, not the old source distance, limits a pair.
            # A restart is strongest after an interruption, or when the whole
            # short unit is the next unit's prefix.  Do not flag continuous
            # emphatic wording without a real boundary.
            interrupted = bool(_INTERRUPTION.search(left_text))
            clean_left = re.sub(r"(?:--+|—+|\.\.\.|…+|[，,、。！？!?；;]+)$", "", left_text)
            clean_right = re.sub(r"^[，,、。！？!?；;]+", "", right_text)
            prefix = clean_left and clean_right.startswith(clean_left)
            full_sentence_repeat = (
                len(left_text) <= 120 and len(right_text) <= 120
                and bool(_SENTENCE_END.search(left_text))
                and bool(_SENTENCE_END.search(right_text))
                and clean_left == re.sub(r"[。！？!?；;]+$", "", clean_right)
            )
            if not interrupted and not prefix and not full_sentence_repeat:
                continue
            if len(clean_left) < 2 or (len(left_text) > 14 and not full_sentence_repeat):
                continue
            first = min(left["items"][0][0], right["items"][0][0])
            last = max(left["items"][-1][0], right["items"][-1][0]) + 1
            source_start = float(words[first]["start"])
            source_end = float(words[last - 1]["end"])
            context = "".join(words[i]["text"] for i in range(max(0, first - 3), min(len(words), last + 3)))
            digest = hashlib.sha256(f"retained_repetition:{source_start:.6f}:{source_end:.6f}:{clean_left}".encode()).hexdigest()[:16]
            result.append({
                "candidate_id": f"retained-repetition-{digest}",
                "kind": "retained_repetition",
                "word_start": first,
                "word_end": last,
                "source_start": source_start,
                "source_end": source_end,
                "context": context,
                "evidence": "interruption_restart" if interrupted else "repeated_prefix_after_boundary",
                "audition_range": {
                    "source_start": max(0.0, source_start - 0.35),
                    "source_end": min(float(media_duration), source_end + 0.35),
                },
            })
            break
    # Merge overlapping windows from a single restart chain.
    merged: list[dict[str, Any]] = []
    for item in sorted(result, key=lambda x: (x["source_start"], x["source_end"])):
        if merged and item["word_start"] <= merged[-1]["word_end"]:
            merged[-1]["word_end"] = max(merged[-1]["word_end"], item["word_end"])
            merged[-1]["source_end"] = max(merged[-1]["source_end"], item["source_end"])
            merged[-1]["audition_range"]["source_end"] = min(float(media_duration), merged[-1]["source_end"] + 0.35)
        else:
            merged.append(item)
    for item in merged:
        retained_text = "".join(words[i]["text"] for i in range(item["word_start"], item["word_end"]))
        item["context"] = "".join(words[i]["text"] for i in range(max(0, item["word_start"] - 3), min(len(words), item["word_end"] + 3)))
        digest = hashlib.sha256(
            f"retained_repetition:{item['source_start']:.6f}:{item['source_end']:.6f}:{retained_text}".encode()
        ).hexdigest()[:16]
        item["candidate_id"] = f"retained-repetition-{digest}"
    return merged


def assess_cleanup_risk(
    words: list[dict[str, Any]], plan: dict[str, Any], *, media_duration: float,
) -> dict[str, Any]:
    """Build deterministic advisory data; never mutate input or infer approval."""
    text = "".join(word["text"] for word in words)
    offsets = [0]
    for word in words:
        offsets.append(offsets[-1] + len(word["text"]))
    matches = []
    for rule, pattern in _PROTECTED:
        for match in pattern.finditer(text):
            matches.append({
                "rule": rule, "text": match.group(),
                "word_start": bisect_right(offsets, match.start()) - 1,
                "word_end": bisect_left(offsets, match.end()),
            })

    candidates = []

    def candidate(kind, start, end, first, last, reason, evidence):
        affected = "" if first is None else "".join(w["text"] for w in words[first:last])
        protected = [] if first is None else [
            dict(match) for match in matches
            if match["word_start"] < last and match["word_end"] > first
        ]
        rules = sorted({match["rule"] for match in protected})
        risk = "high" if protected else "review"
        if kind == "word_delete" and (
            _SENTENCE_END.search(affected) or len(affected.strip()) >= 12
        ):
            risk = "high"
            rules.append("sentence_or_long_deletion")
        if kind == "reviewed_time_cut":
            rules.append("untranscribed_gap" if first is None else "time_cut_requires_audio_review")
            if first is not None and (start > words[first]["start"] or end < words[last - 1]["end"]):
                rules.append("partial_word_cut")
        before = first if first is not None else bisect_right([w["end"] for w in words], start)
        after = last if last is not None else bisect_left([w["start"] for w in words], end)
        return {
            "kind": kind, "word_start": first, "word_end": last,
            "source_start": float(start), "source_end": float(end),
            "deleted_text": affected if kind == "word_delete" else None,
            "affected_text": affected,
            "context_before": "".join(w["text"] for w in words[max(0, before - 3):before]),
            "context_after": "".join(w["text"] for w in words[after:after + 3]),
            "audition_range": {
                "source_start": max(0.0, float(start) - 0.35),
                "source_end": min(float(media_duration), float(end) + 0.35),
            },
            "reason": reason, "evidence": evidence,
            "risk": risk, "rules": rules,
            "protected_matches": protected, "keep_ref": None,
        }

    for index, segment in enumerate(plan["segments"]):
        if segment["action"] != "delete":
            continue
        item = candidate(
            "word_delete", segment["source_start"], segment["source_end"],
            segment["word_start"], segment["word_end"], segment["reason"], None,
        )
        following = plan["segments"][index + 1] if index + 1 < len(plan["segments"]) else None
        deleted = item["deleted_text"]
        if (
            item["risk"] != "high" and following and following["action"] == "keep"
            and 0 <= float(following["source_start"]) - float(segment["source_end"]) <= 0.25
            and 0 < len(deleted.strip()) <= 3 and deleted == deleted.strip()
            and words[following["word_start"]]["text"].startswith(deleted)
            and len(words[following["word_start"]]["text"]) > len(deleted)
            and not any(
                cut["source_start"] < words[following["word_start"]]["end"]
                and cut["source_end"] > words[following["word_start"]]["start"]
                for cut in plan.get("reviewed_cut_ranges", [])
            )
        ):
            # Only a partial restart, not a repeated complete word/sentence.
            item["risk"] = "low"
            item["rules"].append("adjacent_partial_prefix")
            item["keep_ref"] = {
                "word_start": following["word_start"], "word_end": following["word_start"] + 1,
            }
        if not item["rules"]:
            item["rules"].append("insufficient_mechanical_evidence")
        candidates.append(item)

    starts = [word["start"] for word in words]
    ends = [word["end"] for word in words]
    for cut in plan.get("reviewed_cut_ranges", []):
        start, end = cut["source_start"], cut["source_end"]
        first, last = bisect_right(ends, start), bisect_left(starts, end)
        if first == last:
            first = last = None
        candidates.append(candidate(
            "reviewed_time_cut", start, end, first, last, cut["reason"], cut["evidence"],
        ))
    candidates.sort(key=lambda item: (item["source_start"], item["source_end"], item["kind"]))
    retained = retained_repetitions(words, plan, media_duration=media_duration)
    return {
        "version": 1, "method": "conservative_rules_v1", "advisory_only": True,
        "requires_audio_review": True,
        "counts": {risk: sum(item["risk"] == risk for item in candidates)
                   for risk in ("high", "review", "low")},
        "candidates": candidates,
        "retained_repetitions": retained,
    }

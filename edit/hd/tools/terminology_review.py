"""Conservative, source-bound terminology doubts; never edit speech or copy."""
import copy
import math
import re


def _history_text(tokens):
    result = ""
    for token in tokens:
        if re.search(r"[A-Za-z0-9]$", result) and re.match(r"[A-Za-z0-9]", token):
            result += " "
        result += token
    return result


def build_report_with_history(words, *, approved_terms, summary):
    """Consume validated positional history without making it a global rule.

    Caller must bind summary to an approved artifact before using this report.
    Different contextual corrections remain separate review alternatives.
    """
    from .edit_timeline import _correction_audit_runs
    runs = _correction_audit_runs(summary)
    report = build_report(words, approved_terms=approved_terms)
    for run_index, run in enumerate(runs):
        for change_index, change in enumerate(run["changes"]):
            old, new = _history_text(change["before"]), _history_text(change["after"])
            if old == new:
                continue
            candidates = build_report(words, approved_terms=[], corrections=[{"from": old, "to": new}])
            for doubt in candidates["doubts"]:
                doubt["reason"] = "historical_correction_possible_recurrence"
                doubt["history_reference"] = {
                    "run_index": run_index, "change_index": change_index,
                    "source": dict(run["source"]), "manifest": dict(run["manifest"]),
                    "word_start": change["word_start"], "word_end": change["word_end"],
                    "reason": change["reason"],
                }
                report["doubts"].append(doubt)
    report["doubts"].sort(key=lambda item: item["source_range"][0])
    report["history_run_count"] = len(runs)
    return report


def _approved_content_terms(content_record):
    if (type(content_record) is not dict
            or type(content_record.get("analysis_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", content_record["analysis_sha256"]) is None
            or type(content_record.get("analysis")) is not dict):
        raise ValueError("approved content identity is invalid")
    analysis = content_record["analysis"]
    if type(analysis.get("items")) is not list or type(analysis.get("claims")) is not list:
        raise ValueError("approved content terminology is invalid")
    terms = []
    for item in analysis["items"]:
        if type(item) is not dict or type(item.get("keywords")) is not list:
            raise ValueError("approved content terminology is invalid")
        terms.extend(item["keywords"])
    for claim in analysis["claims"]:
        if (type(claim) is not dict or type(claim.get("entities")) is not list
                or type(claim.get("numbers")) is not list):
            raise ValueError("approved content terminology is invalid")
        terms.extend(claim["entities"])
        terms.extend(claim["numbers"])
    return list(dict.fromkeys(_text(term) for term in terms))


def _without_bound_report(summary):
    if type(summary) is not dict:
        raise ValueError("cleanup summary is invalid")
    return {key: copy.deepcopy(value) for key, value in summary.items()
            if key != "terminology_review"}


def build_bound_report(words, *, content_record, summary):
    """Bind advisory terminology doubts to approved content and current words."""
    terms = _approved_content_terms(content_record)
    report = build_report_with_history(
        words, approved_terms=terms, summary=_without_bound_report(summary),
    )
    return {
        "version": 1,
        "content_analysis_sha256": content_record["analysis_sha256"],
        "approved_terms": terms,
        "report": report,
    }


def validate_bound_report(value, *, words, content_record, summary):
    expected = build_bound_report(
        words, content_record=content_record, summary=summary,
    )
    if type(value) is not dict or value != expected:
        raise ValueError("terminology review identity is invalid")
    return copy.deepcopy(expected)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty terminology text required")
    return value


def build_report(words, *, approved_terms, corrections=()):
    terms = list(dict.fromkeys(_text(term) for term in approved_terms))
    canonical = {}
    for term in terms:
        key = term.casefold()
        if key in canonical and canonical[key] != term:
            raise ValueError("conflicting approved spelling")
        canonical[key] = term
    mapping = {}
    for correction in corrections:
        if not isinstance(correction, dict) or set(correction) != {"from", "to"}:
            raise ValueError("correction requires from/to")
        old, new = _text(correction["from"]), _text(correction["to"])
        if old == new or (old in mapping and mapping[old] != new):
            raise ValueError("conflicting correction")
        if any(key in canonical and canonical[key] != new for key in (old.casefold(), new.casefold())):
            raise ValueError("correction conflicts with approved spelling")
        mapping[old] = new
    chunks, owners = [], []
    previous_end = 0
    for index, word in enumerate(words):
        value = _text(word["text"])
        start, end = word["start"], word["end"]
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in (start, end)):
            raise ValueError("finite source times required")
        if start < previous_end or end <= start:
            raise ValueError("ordered nonoverlapping source times required")
        # Independent Latin ASR tokens need a lexical boundary, unlike CJK.
        if chunks and start - previous_end > .5:
            chunks.append("\n")
            owners.append(None)
        elif chunks and re.search(r"[A-Za-z0-9]$", chunks[-1]) and re.match(r"[A-Za-z0-9]", value):
            chunks.append(" ")
            owners.append(None)
        chunks.append(value)
        owners.extend([index] * len(value))
        previous_end = end
    source = "".join(chunks)
    doubts, seen = [], set()
    candidates = [(old, new, "confirmed_correction_reappeared", 0) for old, new in mapping.items()]
    candidates += [(term, term, "case_variant", re.IGNORECASE) for term in terms if re.search(r"[A-Za-z]", term)]
    for token, expected, reason, flags in candidates:
        pattern = re.escape(token)
        if re.match(r"[A-Za-z0-9]", token):
            pattern = r"(?<![A-Za-z0-9_])" + pattern
        if re.search(r"[A-Za-z0-9]$", token):
            pattern += r"(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, source, flags):
            if reason == "case_variant" and match.group() == expected:
                continue
            key = (match.start(), match.end(), expected)
            if key in seen:
                continue
            seen.add(key)
            indices = list(dict.fromkeys(i for i in owners[match.start():match.end()] if i is not None))
            doubts.append({"observed": match.group(), "expected": expected, "reason": reason,
                           "word_indices": indices, "source_range": [words[indices[0]]["start"], words[indices[-1]]["end"]],
                           "review_required": True})
    doubts.sort(key=lambda item: (item["source_range"][0], item["word_indices"][0], item["expected"]))
    return {"version": 1, "method": "explicit_correction_and_case_rules",
            "max_join_gap_seconds": .5, "latin_split_tokens": "not_combined",
            "automatic_replacement": False, "doubts": doubts}

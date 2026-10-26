"""Validation for the two semantic visual lists used by confirmation."""
from __future__ import annotations
import math

class SemanticVisualPlanError(ValueError):
    pass

def require_interval_coverage(windows, begin, finish, *, label):
    """Cover a required interval with segment windows, within the 24fps clock."""
    def valid(start, end):
        return all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) and 0 <= start < end
    if not valid(begin, finish) or any(not valid(a, b) for a, b in windows):
        raise SemanticVisualPlanError(f"{label}: invalid word span or segment clock")
    right = begin
    for left, end in sorted(windows):
        if left > right + 1 / 24:
            break
        right = max(right, end)
        if right >= finish - 1 / 24:
            return
    raise SemanticVisualPlanError(f"{label}: referenced segments do not cover word span {begin:.3f}–{finish:.3f}s")

def component_use(segment, component):
    """Return the logical use from real composition, not an inner annotation."""
    family = segment.get("visual_strategy", {}).get("composition", {}).get("family")
    if family == "no_broll":
        raise SemanticVisualPlanError("plain A-roll cannot contain a counted visual component")
    return "overlay" if family == "aroll_with_overlay" and component.get("layer_role") == "annotation" else "broll"

def validate_semantic_lists(treatment, director, speech=None):
    lists = treatment.get("semantic_lists")
    if not isinstance(lists, dict) or not isinstance(lists.get("overlay"), list) or not isinstance(lists.get("broll"), list):
        raise SemanticVisualPlanError("treatment.semantic_lists must contain overlay and broll lists")
    words = speech if speech is not None else []
    components = {}
    for seg in director.get("segments", []):
        sid = seg.get("segment_id")
        for comp in seg.get("visual_strategy", {}).get("components", []):
            cid = comp.get("component_id")
            if isinstance(sid, str) and isinstance(cid, str) and cid:
                if (sid, cid) in components:
                    raise SemanticVisualPlanError("visual component identity must be unique")
                components[(sid, cid)] = (seg, comp)
    seen_rows, seen_components, seen_spans, items = set(), set(), set(), []
    for typ in ("overlay", "broll"):
        for row in lists[typ]:
            if not isinstance(row, dict) or not isinstance(row.get("row_id"), str) or not row["row_id"]:
                raise SemanticVisualPlanError("semantic rows need stable row_id")
            rid = row["row_id"]
            if rid in seen_rows:
                raise SemanticVisualPlanError("semantic row_id must be unique")
            seen_rows.add(rid)
            start, end = row.get("start_word"), row.get("end_word")
            if type(start) is not int or type(end) is not int or start < 0 or start >= end:
                raise SemanticVisualPlanError("semantic word span is invalid")
            for key in ("quote", "semantic", "visual_task"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise SemanticVisualPlanError("semantic rows need quote, semantic and visual_task")
            duplicate_key = (start, end, row["semantic"], row["visual_task"])
            if duplicate_key in seen_spans:
                raise SemanticVisualPlanError("duplicate semantic task")
            seen_spans.add(duplicate_key)
            if speech is not None:
                if end > len(words) or row["quote"] != "".join(w["text"] for w in words[start:end]):
                    raise SemanticVisualPlanError("semantic row quote does not match approved cut words")
            refs = row.get("components")
            if not isinstance(refs, list) or not refs:
                raise SemanticVisualPlanError("semantic rows need visual component references")
            local, windows = set(), []
            for ref in refs:
                if not isinstance(ref, dict) or not isinstance(ref.get("segment_id"), str) or not isinstance(ref.get("component_id"), str):
                    raise SemanticVisualPlanError("semantic component reference is invalid")
                key = (ref["segment_id"], ref["component_id"])
                if key in local or key in seen_components or key not in components:
                    raise SemanticVisualPlanError("semantic component reference is duplicate or orphaned")
                local.add(key); seen_components.add(key)
                segment, comp = components[key]
                is_overlay = component_use(segment, comp) == "overlay"
                if (typ == "overlay") != is_overlay:
                    raise SemanticVisualPlanError("semantic row type does not match real composition")
                if speech is not None:
                    windows.append((segment.get("start"), segment.get("end")))
            if speech is not None:
                for word in words[start:end]:
                    require_interval_coverage(windows, word.get("start"), word.get("end"), label=rid)
            item = dict(row); item["type"] = "贴片" if typ == "overlay" else "B-roll"
            items.append(item)
    if set(components) != seen_components:
        raise SemanticVisualPlanError("every visual component must belong to one semantic row")
    return {"overlay_count": len(lists["overlay"]), "broll_count": len(lists["broll"]),
            "items": items, "component_rows": {key: row for row in items for ref in row["components"]
                                                  for key in [(ref["segment_id"], ref["component_id"])]}}

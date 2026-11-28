"""Validation for the two semantic visual lists used by confirmation."""
from __future__ import annotations
import math

OVERLAY_ACTION_FIELDS = ("subject", "initial_state", "movement", "result")

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

def component_semantic_rows(treatment):
    """Index the frozen rows by their already validated component identity."""
    lists = treatment.get("semantic_lists", {})
    return {(ref["segment_id"], ref["component_id"]): row
            for group in ("overlay", "broll") for row in lists.get(group, [])
            for ref in row["components"]}


def component_timing(row, key):
    """Read the optional timing of one physical part of a semantic item."""
    return next((ref.get("timing") for ref in row.get("components", ())
                 if (ref["segment_id"], ref["component_id"]) == key), None)


def _validate_timing(timing, segment, *, label):
    required = {"settled_frame", "visible_until_frame"}
    if (not isinstance(timing, dict) or not required <= set(timing)
            or set(timing) - required - {"action_start_frame"}
            or any(type(frame) is not int for frame in timing.values())):
        raise SemanticVisualPlanError(f"{label}: timing needs integer edited-body frames")
    start = round(segment["start"] * 24)
    end = round(segment["end"] * 24)
    settled = timing["settled_frame"]
    if not start <= settled < timing["visible_until_frame"] <= end:
        raise SemanticVisualPlanError(f"{label}: planned result and hold must fit the component window")
    if "action_start_frame" in timing and not start <= timing["action_start_frame"] < settled:
        raise SemanticVisualPlanError(f"{label}: planned action must start within the window before it settles")


def _validate_required_content(content):
    if not isinstance(content, dict) or not content:
        raise SemanticVisualPlanError("required_content must name at least one visible requirement")
    for key, item in content.items():
        if (not isinstance(key, str) or not key or key == "visual_task"
                or not isinstance(item, dict) or set(item) not in ({"meaning"}, {"meaning", "terms"})
                or not isinstance(item["meaning"], str) or not item["meaning"].strip()):
            raise SemanticVisualPlanError("required_content needs named, recognizable meaning")
        if "terms" in item:
            terms = item["terms"]
            if (not isinstance(terms, list) or not terms
                    or any(not isinstance(term, str) or not term.strip() for term in terms)
                    or len(set(terms)) != len(terms)):
                raise SemanticVisualPlanError("required_content terms must be distinct, nonempty strings")


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
            if "overlay_action" in row:
                action = row["overlay_action"]
                if (typ != "overlay" or not isinstance(action, dict) or set(action) != set(OVERLAY_ACTION_FIELDS)
                        or any(not isinstance(value, str) or not value.strip() for value in action.values())):
                    raise SemanticVisualPlanError("overlay_action needs subject, initial_state, movement and result")
            if "required_content" in row:
                _validate_required_content(row["required_content"])
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
                if "timing" in ref:
                    _validate_timing(ref["timing"], segment, label=rid)
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

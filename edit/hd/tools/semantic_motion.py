"""Versioned, read-only motion planning; no renderer or approval is implied."""

from __future__ import annotations

import copy

from . import content_analysis, state


PATTERNS = {
    "relation": ("reveal_sources", "draw_connections", "reveal_hub"),
    "replacement": ("establish", "replace", "compare"),
    "threshold": ("establish", "cross_threshold", "raise_threshold"),
    "delay": ("establish", "wait", "realize"),
    "hierarchy": ("establish", "reveal_layers", "resolve"),
    "feedback": ("establish", "produce", "feedback_return"),
}
_PLAN_KEYS = {
    "version", "content_item_id", "source_text", "family", "meaningful_change",
    "subjects", "actions", "duration_frames", "read_window", "exit_window",
}
_OBSERVATION_OPERATIONS = {"establish", "compare", "wait"}


class SemanticMotionError(ValueError):
    """A proposed motion cannot be checked without guessing or changing it."""


def _object(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise SemanticMotionError(f"{label} fields are invalid")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or any(ord(c) < 32 for c in value):
        raise SemanticMotionError(f"{label} must be nonempty single-line text")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SemanticMotionError(f"{label} must be an integer >= {minimum}")
    return value


def _ids(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if type(value) is not list or (not value and not allow_empty):
        raise SemanticMotionError(f"{label} must be a list")
    for item in value:
        _text(item, label)
    if len(set(value)) != len(value):
        raise SemanticMotionError(f"{label} contains duplicates")
    return value


def _window(value: dict, duration: int, label: str) -> tuple[int, int]:
    start = _integer(value["start_frame"], f"{label}.start_frame")
    end = _integer(value["end_frame"], f"{label}.end_frame", 1)
    if not start < end <= duration:
        raise SemanticMotionError(f"{label} is outside the local frame range")
    return start, end


def build_motion_plan(draft: object, *, approved_items: object) -> dict:
    """Check a director proposal against items loaded by the existing approval gate.

    This pure helper does not authenticate that gate. The caller must use
    content_analysis.load_approved_content_analysis(job); arbitrary input is not
    proof of approval. State descriptions and semantic fit still need human QA.
    """
    plan = _object(draft, _PLAN_KEYS, "motion plan")
    if type(plan["version"]) is not int or plan["version"] != 1:
        raise SemanticMotionError("motion plan version must be 1")
    item_id = _text(plan["content_item_id"], "content_item_id")
    # The existing content loader validates the full item schema. Here require
    # unique identities and exact original wording, not newly inferred keywords.
    if type(approved_items) is not list or not approved_items:
        raise SemanticMotionError("approved_items must be a nonempty list")
    items = {}
    for item in approved_items:
        if type(item) is not dict:
            raise SemanticMotionError("approved item must be an object")
        key = _text(item.get("id"), "approved item id")
        if key in items:
            raise SemanticMotionError("approved item ids contain duplicates")
        items[key] = item
    item = items.get(item_id)
    status = item.get("evidence_status") if item is not None else None
    if type(status) is not str or status not in {"supported", "needs_user_decision"}:
        raise SemanticMotionError("motion references unknown or unsupported content")
    if type(plan["source_text"]) is not str or not plan["source_text"].strip() or plan["source_text"] != item.get("source_text"):
        raise SemanticMotionError("motion source_text differs from approved content")
    family = _text(plan["family"], "family")
    if family not in PATTERNS:
        raise SemanticMotionError("unsupported motion family")
    _text(plan["meaningful_change"], "meaningful_change")
    duration = _integer(plan["duration_frames"], "duration_frames", 1)

    subjects = plan["subjects"]
    if type(subjects) is not list or not subjects:
        raise SemanticMotionError("subjects must be a nonempty list")
    by_subject = {}
    for subject in subjects:
        _object(subject, {"id", "label", "initial_state", "final_state", "preserve"}, "subject")
        for field in ("id", "label", "initial_state", "final_state"):
            _text(subject[field], f"subject.{field}")
        if subject["id"] in by_subject or type(subject["preserve"]) is not bool:
            raise SemanticMotionError("subject id must be unique and preserve boolean")
        if subject["preserve"] and subject["initial_state"] != subject["final_state"]:
            raise SemanticMotionError("preserved subject must keep the same state")
        by_subject[subject["id"]] = subject

    actions = plan["actions"]
    if type(actions) is not list or len(actions) != len(PATTERNS[family]):
        raise SemanticMotionError("actions must follow the motion family phases")
    by_action, used_subjects = {}, set()
    for index, action in enumerate(actions):
        _object(action, {"id", "operation", "subject_ids", "start_frame", "end_frame", "depends_on"}, "action")
        action_id = _text(action["id"], "action.id")
        if action_id in by_action or action["operation"] != PATTERNS[family][index]:
            raise SemanticMotionError("action id or family phase order is invalid")
        subject_ids = _ids(action["subject_ids"], "action.subject_ids")
        dependencies = _ids(action["depends_on"], "action.depends_on", allow_empty=True)
        start, _end = _window(action, duration, "action")
        if index and actions[index - 1]["id"] not in dependencies:
            raise SemanticMotionError("action must depend on the preceding semantic phase")
        for dependency in dependencies:
            # Requiring earlier phases excludes cycles, self-edges and missing IDs.
            if dependency not in by_action or by_action[dependency]["end_frame"] > start:
                raise SemanticMotionError("action dependency is cyclic, unknown or unfinished")
        for subject_id in subject_ids:
            if subject_id not in by_subject:
                raise SemanticMotionError("action references unknown subject")
            if by_subject[subject_id]["preserve"] and action["operation"] not in _OBSERVATION_OPERATIONS:
                raise SemanticMotionError("changing action targets a preserved subject")
        used_subjects.update(subject_ids)
        by_action[action_id] = action
    if used_subjects != set(by_subject):
        raise SemanticMotionError("unused subjects are not meaningful motion content")

    reading = _object(plan["read_window"], {"start_frame", "end_frame", "minimum_frames"}, "read_window")
    read_start, read_end = _window(reading, duration, "read_window")
    minimum = _integer(reading["minimum_frames"], "read_window.minimum_frames", 1)
    exit_start, exit_end = _window(_object(plan["exit_window"], {"start_frame", "end_frame"}, "exit_window"), duration, "exit_window")
    if max(action["end_frame"] for action in actions) > read_start or read_end - read_start < minimum:
        raise SemanticMotionError("terminal state has insufficient uninterrupted reading time")
    if exit_start != read_end or exit_end != duration:
        raise SemanticMotionError("exit must follow reading and finish at the shot boundary")
    return {
        "execution_status": "planning_only",
        "plan": copy.deepcopy(plan),
        "check_frames": {
            "initial": 0,
            "action_completed": {action["id"]: action["end_frame"] for action in actions},
            "read_start": read_start, "before_exit": exit_start - 1,
            "last_visible": duration - 1, "next_boundary": duration,
        },
    }


def active_action_ids(plan: dict, frame: int) -> list[str]:
    """Inspect an already checked local timeline; end frames are exclusive."""
    _integer(frame, "frame")
    return [action["id"] for action in plan["actions"]
            if action["start_frame"] <= frame < action["end_frame"]]


def plan_motion_for_job(job: state.JobState, draft: object) -> dict:
    """Read the current content approval without publishing or advancing a stage."""
    current = state.load_job(job.job_dir)
    record = content_analysis.load_approved_content_analysis(current)
    report = build_motion_plan(draft, approved_items=record["analysis"]["items"])
    return {**report, "content_analysis_sha256": record["analysis_sha256"]}

"""Bind a semantic brief to current approved content, without granting approval."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import semantic_motion
from .semantic_validator import validate_bytes

FAMILIES = ("replacement", "threshold", "delay", "hierarchy", "feedback")
TEMPLATES = {family: "hd-talking-head/semantic-state-" + family for family in FAMILIES}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate brief key")
        result[key] = value
    return result


def bind_brief(job, payload, *, node_executable, node_sha256, template_id):
    """Use the renderer's role schema and the existing approved-content planner."""
    if type(payload) is not bytes or not payload or len(payload) > 256 * 1024:
        raise ValueError("brief must be UTF-8 JSON bytes of at most 256 KiB")
    brief = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique)
    renderer = Path(__file__).with_name("semantic_state_renderer.cjs")
    before = renderer.read_bytes()
    result = validate_bytes(payload, node_executable=node_executable, node_sha256=node_sha256,
        renderer=renderer, renderer_sha256=hashlib.sha256(before).hexdigest())
    if json.loads(result) != brief or renderer.read_bytes() != before:
        raise ValueError("semantic renderer validation identity changed")
    family = brief["motion"]["family"]
    if family not in TEMPLATES or template_id != TEMPLATES[family]:
        raise ValueError("template does not match semantic family")
    report = semantic_motion.plan_motion_for_job(job, brief["motion"])
    if report.get("execution_status") != "planning_only" or report.get("plan") != brief["motion"]:
        raise ValueError("semantic motion differs from current approved content")
    return {"brief_sha256": hashlib.sha256(payload).hexdigest(),
            "node_sha256": node_sha256,
            "renderer_sha256": hashlib.sha256(before).hexdigest(),
            "template_id": template_id, "semantic_motion": report,
            "template_request": {"semantic_family": family,
                "information_units": len(brief["motion"]["subjects"]),
                "numeric_values": [], "numeric_scale": "not_applicable"}}

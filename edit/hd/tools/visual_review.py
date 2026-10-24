"""Bind host observations to actual media in the existing stage receipt.

This validates playback declarations and their scope, not human perception.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import contract_artifacts as artifacts, visual_confirmation as confirmation

POLICY_VERSION = "visual-review-v1"
_MANIFESTS = {"visual_canary": "08-visual-canary/canary-manifest.json",
              "visual_assets": "09-visual-assets/asset-manifest.json"}
_STAGES = {*_MANIFESTS, "preview"}


def _registered(job, stage, relative):
    records = [r for r in job.stages[stage]["artifacts"] if r["path"] == relative]
    if len(records) != 1:
        raise ValueError("visual review needs the current registered " + relative)
    confirmation._exact(job.job_dir, records[0])
    return dict(records[0])


def expected_observations(job, stage):
    """Return component identities and windows in the actual viewed file clock."""
    if stage not in _STAGES:
        raise ValueError("unsupported visual review stage")
    authorization = confirmation.validate_visual_authorization(job, require_realized=True)
    policy = authorization["source"].get("visual_review_policy")
    if policy is None:
        return {"status": "not_applicable", "stage": stage}
    if policy != POLICY_VERSION:
        raise ValueError("unknown visual review policy")
    plan_ref = authorization["mapping"]["final_v3"]
    plan = artifacts.read_json_artifact(confirmation._exact(job.job_dir, plan_ref))
    selected = None
    media_by_segment = {}
    offset = 0.0
    if stage == "preview":
        preview = _registered(job, stage, "11-preview/review.mp4")
        media_duration = plan["duration"]
        if any(r["path"] == "11-preview/opening-manifest.json"
               for r in job.stages[stage]["artifacts"]):
            ref = _registered(job, stage, "11-preview/opening-manifest.json")
            opening = artifacts.read_json_artifact(job.job_dir / ref["path"])
            offset = opening["body_offset_frames"] / 24
            media_duration = opening["total_frames"] / 24
            if opening["preview_sha256"] != preview["sha256"]:
                raise ValueError("visual review opening belongs to another preview")
    else:
        ref = _registered(job, stage, _MANIFESTS[stage])
        manifest = artifacts.read_json_artifact(job.job_dir / ref["path"])
        if manifest["visual_plan_sha256"] != plan_ref["sha256"]:
            raise ValueError("visual review manifest belongs to another plan")
        selected = set(manifest["segment_ids"]) if stage == "visual_canary" else None
        manifest_ids = [item["segment_id"] for item in manifest["segments"]]
        plan_ids = {item["segment_id"] for item in plan["segments"]}
        if (len(set(manifest_ids)) != len(manifest_ids)
                or set(manifest_ids) != (selected if selected is not None else plan_ids)
                or not set(manifest_ids) <= plan_ids):
            raise ValueError("visual review manifest coverage differs from the plan")
        for item in manifest["segments"]:
            path = Path(item["video_path"])
            relative = (path if path.is_absolute() else job.job_dir / path).relative_to(job.job_dir).as_posix()
            registered = _registered(job, stage, relative)
            if (registered["sha256"] != item["video_sha256"]
                    or registered["bytes"] != item["video_bytes"]):
                raise ValueError("visual review segment media differs from its manifest")
            media_by_segment[item["segment_id"]] = registered
    observations = []
    for segment in plan["segments"]:
        sid = segment["segment_id"]
        if selected is not None and sid not in selected:
            continue
        for component in segment["shot_recipe"]["components"]:
            window = component["render_window"]
            origin = segment["start"] + offset if stage == "preview" else 0
            observations.append({
                "row_id": sid + ":" + component["component_id"],
                "visual_intent": segment["visual_intent"]["statement"],
                "media_ref": preview if stage == "preview" else media_by_segment[sid],
                "media_duration": media_duration if stage == "preview" else segment["end"] - segment["start"],
                "window": [origin + window["start_frame"] / 24,
                           origin + window["end_frame"] / 24],
            })
    return {"status": "required", "policy_version": POLICY_VERSION,
            "stage": stage, "plan_ref": plan_ref, "observations": observations}


def validate_stage_review(job, stage, review):
    expected = expected_observations(job, stage)
    if expected["status"] == "not_applicable":
        return expected
    payload = review.get("visual_review")
    if (not isinstance(payload, dict) or payload.get("policy_version") != POLICY_VERSION
            or payload.get("stage") != stage or payload.get("plan_ref") != expected["plan_ref"]):
        raise ValueError("current-media visual_review is required")
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise ValueError("visual review observations are required")
    wanted = {r["row_id"]: r for r in expected["observations"]}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("row_id") not in wanted or row["row_id"] in seen:
            raise ValueError("visual review component coverage mismatch")
        seen.add(row["row_id"])
        target = wanted[row["row_id"]]
        if row.get("media_ref") != target["media_ref"]:
            raise ValueError("visual review media identity is stale")
        window = row.get("playback_window")
        if (not isinstance(window, list) or len(window) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in window)
                or window[0] < 0 or window[1] > target["media_duration"] + 1e-6
                or window[0] > target["window"][0] + 1e-6
                or window[1] < target["window"][1] - 1e-6):
            raise ValueError("visual review must declare playback of the current component window")
        if not isinstance(row.get("conclusion"), str) or not row["conclusion"].strip():
            raise ValueError("visual review needs a concrete observation")
        if any(row.get(k) is not True for k in ("size_position_clear", "unobstructed", "semantics_clear")):
            raise ValueError("visual review has unresolved size, occlusion or meaning")
    if seen != set(wanted):
        raise ValueError("visual review is missing components")
    return payload


def require_preview_review(job):
    """Repeat the gate at delivery, including consumers of raw-approve callers."""
    expected = expected_observations(job, "preview")
    if expected["status"] == "not_applicable":
        return
    for path in (job.job_dir / "manifests").glob("local-qa-preview-r*.json"):
        receipt = artifacts.read_json_artifact(path)
        if (receipt.get("job_id") != job.job_id or receipt.get("job_dir") != str(job.job_dir)
                or receipt.get("stage") != "preview" or receipt.get("reviewed_by") != "host"
                or receipt.get("passed") is not True
                or receipt.get("artifacts") != job.stages["preview"]["artifacts"]):
            continue
        validate_stage_review(job, "preview", receipt)
        return
    raise ValueError("current preview has no bound host visual review")

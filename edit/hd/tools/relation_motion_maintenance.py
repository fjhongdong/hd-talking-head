"""Approved-Job bridge for the relation motion HTML core (maintenance only)."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path
from . import semantic_motion, state

ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "relation_motion_renderer.cjs"
class RelationMotionMaintenanceError(ValueError): pass

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build_approved_relation_brief(job_dir, draft, title, source_ids, hub_id, node_executable):
    directory = Path(job_dir).resolve(strict=True)
    before = {p: p.read_bytes() for p in (directory / "workflow.json", directory / "02-content-analysis" / "content-analysis.json")}
    renderer_before = _sha(RENDERER)
    job = state.load_job(directory)
    report = semantic_motion.plan_motion_for_job(job, draft)
    if report["execution_status"] != "planning_only" or report["plan"]["family"] != "relation": raise RelationMotionMaintenanceError("relation motion is not maintenance-plannable")
    plan = report["plan"]
    subjects = {item["id"]: item for item in plan["subjects"]}
    if not isinstance(source_ids, list) or len(source_ids) not in (2, 3, 4) or any(not isinstance(x, str) or not x or len(x)>80 or any(ord(c)<32 for c in x) for x in source_ids) or len(set(source_ids)) != len(source_ids) or not isinstance(hub_id, str) or not hub_id or len(hub_id)>80 or any(ord(c)<32 for c in hub_id) or hub_id in source_ids: raise RelationMotionMaintenanceError("source_ids/hub_id are invalid")
    if set(subjects) != set(source_ids) | {hub_id}:
        raise ValueError("brief subjects do not match motion plan")
    brief = {"schema_version": 1, "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": plan["duration_frames"]}, "motion": plan, "title": title, "source_ids": source_ids, "hub_id": hub_id}
    payload = json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try: checked = subprocess.run([str(node_executable), str(RENDERER), "--validate"], input=payload, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc: raise RelationMotionMaintenanceError("Node validation failed") from exc
    if checked.returncode: raise RelationMotionMaintenanceError("Node validation failed: " + checked.stderr[:2000])
    after = {p: p.read_bytes() for p in before}
    if before != after or renderer_before != _sha(RENDERER): raise RelationMotionMaintenanceError("approved inputs or renderer changed while building brief")
    fresh = state.load_job(directory); fresh_report = semantic_motion.plan_motion_for_job(fresh, draft)
    if fresh_report != report: raise RelationMotionMaintenanceError("approved motion changed while building brief")
    final = {p: p.read_bytes() for p in before}
    if final != before or renderer_before != _sha(RENDERER): raise RelationMotionMaintenanceError("approved inputs or renderer changed while building brief")
    returned_brief = json.loads(payload); canonical = json.dumps(returned_brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"status": "maintenance_only", "brief": returned_brief, "brief_sha256": hashlib.sha256(canonical).hexdigest(), "content_analysis_sha256": report["content_analysis_sha256"], "workflow_sha256": hashlib.sha256(before[directory / "workflow.json"]).hexdigest(), "renderer_sha256": renderer_before, "job_dir": str(directory)}

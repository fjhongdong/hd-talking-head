"""Bind delivery to human plan authorization or an existing final confirmation."""

from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import os
from pathlib import Path
import sys
import tempfile

from . import contract_artifacts as artifacts
from . import state


RECEIPT_PATH = "12-delivery/approval-receipt.json"


def _publish_receipt(path: Path, receipt: dict) -> None:
    """Stage outside delivery so a hard interruption cannot poison its inventory."""
    with tempfile.TemporaryDirectory(prefix=".final-approval-", dir=path.parent.parent) as directory:
        staged = Path(directory) / path.name
        artifacts.write_json_artifact(staged, receipt)
        source_fd = state._open_stable_transaction_directory(staged.parent)
        try:
            target_fd = state._open_stable_transaction_directory(path.parent)
            try:
                library = ctypes.CDLL(None, use_errno=True)
                if sys.platform == "darwin":
                    rename, flags = getattr(library, "renameatx_np", None), 0x00000004
                elif sys.platform.startswith("linux"):
                    rename, flags = getattr(library, "renameat2", None), 0x00000001
                else:
                    rename, flags = None, 0
                if rename is None:
                    raise state.WorkflowError("exclusive receipt publication is unavailable")
                rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                   ctypes.c_char_p, ctypes.c_uint)
                rename.restype = ctypes.c_int
                if rename(source_fd, os.fsencode(staged.name), target_fd,
                          os.fsencode(path.name), flags) != 0:
                    raise OSError(ctypes.get_errno(), "exclusive receipt publication failed")
                os.fsync(target_fd)
                os.fsync(source_fd)
            finally:
                os.close(target_fd)
        finally:
            os.close(source_fd)


def _published(job: state.JobState, stage_id: str, relative: str) -> dict:
    records = [r for r in job.stages[stage_id]["artifacts"] if r["path"] == relative]
    if len(records) != 1 or records[0] != state._artifact_record(job, job.job_dir / relative):
        raise state.WorkflowError("final approval artifact is missing or changed")
    return records[0]


def _delivery_identity(job: state.JobState) -> tuple[dict, dict]:
    final = _published(job, "delivery", "12-delivery/final.mp4")
    manifest_record = _published(job, "delivery", "12-delivery/delivery-manifest.json")
    preview = _published(job, "preview", "11-preview/review.mp4")
    manifest = artifacts.read_json_artifact(job.job_dir / manifest_record["path"])
    inventory = manifest.get("artifacts")
    entry = inventory.get("final.mp4") if isinstance(inventory, dict) else None
    output = entry.get("output") if isinstance(entry, dict) else None
    transition_count = 2 if job.stages["delivery"]["status"] == "approved" else 1
    if (
        not isinstance(output, dict)
        or manifest.get("schema_version") != 2
        or manifest.get("job_id") != job.job_id
        or manifest.get("workflow_revision") != job.revision - transition_count
        or manifest.get("delivery_manifest_sha256") != artifacts.sha256_json({
            k: v for k, v in manifest.items() if k != "delivery_manifest_sha256"
        })
        or manifest.get("final_sha256") != final["sha256"]
        or output.get("sha256") != final["sha256"]
        or output.get("bytes") != final["bytes"]
        or (preview["sha256"], preview["bytes"]) != (final["sha256"], final["bytes"])
    ):
        raise state.WorkflowError("final approval does not match the reviewed delivery")
    return final, manifest_record


def _check_inventory(job: state.JobState, *, pending: bool) -> None:
    expected = {r["path"] for r in job.stages["delivery"]["artifacts"]}
    if pending:
        expected.add(RECEIPT_PATH)
    actual = set()
    for path in (job.job_dir / "12-delivery").rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise state.WorkflowError("delivery contains an unsafe entry")
        if path.is_file():
            actual.add(path.relative_to(job.job_dir).as_posix())
    if actual != expected:
        raise state.WorkflowError("delivery inventory changed after review")


def validate_approval_receipt(job: state.JobState, *, committed: bool = True) -> dict:
    """Validate current evidence; a prepared sidecar is not an approved workflow."""
    final, manifest = _delivery_identity(job)
    path = job.job_dir / RECEIPT_PATH
    record = state._artifact_record(job, path)
    receipt = artifacts.read_json_artifact(path)
    if record != state._artifact_record(job, path):
        raise state.WorkflowError("final approval receipt changed while reading")
    revision = job.revision if committed else job.revision + 1
    if receipt.get("approval_kind") == "plan_authorized":
        _validate_plan_receipt(job, receipt, committed=committed)
        if receipt.get("job_id") != job.job_id or receipt.get("delivery") != final or receipt.get("delivery_manifest") != manifest:
            raise state.WorkflowError("plan-authorized receipt identity is invalid")
        if committed:
            if job.stages["delivery"]["status"] != "approved":
                raise state.WorkflowError("plan-authorized delivery has not committed")
            _published(job, "delivery", RECEIPT_PATH)
        return receipt
    if (
        receipt.get("schema_version") != 1
        or receipt.get("approval_kind") != "formal_final"
        or receipt.get("decision") != "approved"
        or receipt.get("approved_by") != "human"
        or receipt.get("job_id") != job.job_id
        or receipt.get("workflow_revision") != revision
        or receipt.get("reviewed_revision") != revision - 1
        or not isinstance(receipt.get("user_confirmation"), str)
        or not receipt["user_confirmation"].strip()
        or not isinstance(receipt.get("approved_at"), str)
        or not receipt["approved_at"].strip()
        or receipt.get("delivery") != final
        or receipt.get("delivery_manifest") != manifest
        or not isinstance(receipt.get("reviewed_workflow_sha256"), str)
        or not state._SHA256_RE.fullmatch(receipt["reviewed_workflow_sha256"])
    ):
        raise state.WorkflowError("final approval receipt identity is invalid")
    if committed:
        if job.stages["delivery"]["status"] != "approved":
            raise state.WorkflowError("final approval has not committed")
        _published(job, "delivery", RECEIPT_PATH)
    elif (
        job.stages["delivery"]["status"] != "ready_for_review"
        or receipt["reviewed_workflow_sha256"] != job.expected_sha256
        or any(r["path"] == RECEIPT_PATH for r in job.stages["delivery"]["artifacts"])
    ):
        raise state.WorkflowError("pending final confirmation no longer matches the workflow")
    return receipt


def _visual_plan_artifact(job: state.JobState) -> tuple[dict, dict]:
    """Return the current human visual-plan approval descriptor and payload."""
    stage = job.stages.get("visual_direction")
    if not isinstance(stage, dict) or stage.get("status") != "approved":
        raise state.WorkflowError("visual direction has not been approved")
    current = stage.get("artifacts")
    if not isinstance(current, list) or not current:
        raise state.WorkflowError("visual direction artifacts are missing")
    current_records = {r.get("path"): r for r in current if isinstance(r, dict)}
    if not {"07-visual-direction/visual-plan.json", "07-visual-direction/visual-routing.md"} <= current_records.keys():
        raise state.WorkflowError("visual direction plan artifacts are incomplete")
    for record in current:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise state.WorkflowError("visual direction artifact record is invalid")
        if record != state._artifact_record(job, job.job_dir / record["path"]):
            raise state.WorkflowError("visual direction artifact changed")
    # New source-confirmed flow owns its immutable proposal and execution
    # mapping.  The shared validator checks both before delivery consumes it;
    # do not compare its receipt artifacts with the final V3 artifact list.
    mapping_records = [r for r in current if isinstance(r, dict)
                       and isinstance(r.get("path"), str)
                       and r["path"].endswith("/execution-mapping.json")]
    if mapping_records:
        try:
            from . import visual_confirmation
            result = visual_confirmation.validate_visual_authorization(job, require_realized=True)
        except Exception as exc:
            raise state.WorkflowError("source visual confirmation or realized mapping is invalid") from exc
        artifact = result.get("artifact")
        payload = result.get("payload")
        if not isinstance(artifact, dict) or not isinstance(payload, dict):
            raise state.WorkflowError("source visual confirmation descriptor is invalid")
        return artifact, payload
    candidates = []
    for path in (job.job_dir / "manifests").glob("local-qa-visual_direction-r*.json"):
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    valid = []
    for path in candidates:
        try:
            payload = artifacts.read_json_artifact(path)
        except Exception:
            continue
        try:
            filename_revision = int(path.stem.rsplit("-r", 1)[1])
        except (ValueError, IndexError):
            continue
        if (
            payload.get("job_id") != job.job_id
            or payload.get("job_dir") != str(job.job_dir)
            or payload.get("stage") != "visual_direction"
            or payload.get("passed") is not True
            or type(payload.get("revision")) is not int
            or not isinstance(payload.get("note"), str) or not payload["note"].strip()
            or not isinstance(payload.get("user_confirmation"), str)
            or not payload["user_confirmation"].strip()
            or payload.get("reviewed_by") != "human"
            or payload.get("approval_scope") != "visual_plan_and_delivery"
            or payload.get("artifacts") != current
            or payload["revision"] != filename_revision
            or not 0 <= filename_revision < job.revision
        ):
            continue
        valid.append((filename_revision, state._artifact_record(job, path), payload))
    if valid:
        _, record, payload = max(valid, key=lambda item: item[0])
        return record, payload
    raise state.WorkflowError("no valid human visual plan approval is available")


def validate_visual_plan_approval(job: state.JobState) -> dict:
    """Validate the one human approval covering the complete visual plan."""
    record, payload = _visual_plan_artifact(job)
    return {"artifact": record, "payload": payload, "path": record["path"],
            "sha256": record["sha256"], "bytes": record["bytes"]}


def approve_plan_delivery(
    job: state.JobState, *, expected_revision: int,
    delivery_sha256: str, qa_note: str,
) -> Path:
    """Commit host QA delivery after the previously approved visual plan."""
    from .qa_delivery_v2 import DeliveryV2Error, _DeliveryLock, _prepare_delivery_v2_locked

    if (job.version != 2 or type(expected_revision) is not int or expected_revision < 0
            or not isinstance(delivery_sha256, str)
            or not state._SHA256_RE.fullmatch(delivery_sha256)
            or not isinstance(qa_note, str) or not qa_note.strip()):
        raise state.WorkflowError("plan-authorized delivery requires reviewed identity and QA note")
    with _DeliveryLock(job.job_dir):
        current = state.load_job(job.job_dir)
        approved = current.stages["delivery"]["status"] == "approved"
        if (current.revision != expected_revision + int(approved)
                or current.stages["delivery"]["status"] not in {"ready_for_review", "approved"}
                or any(current.stages[s]["status"] != "approved"
                       for s in state.stage_ids_for(current) if s != "delivery") ):
            raise state.WorkflowError("delivery does not match the approved workflow revision")
        visual = validate_visual_plan_approval(current)
        final, manifest = _delivery_identity(current)
        if final["sha256"] != delivery_sha256:
            raise state.WorkflowError("host QA belongs to another delivery file")
        path = current.job_dir / RECEIPT_PATH
        _check_inventory(current, pending=not approved and path.exists())
        if path.exists() or path.is_symlink():
            receipt = validate_approval_receipt(current, committed=approved)
            if receipt.get("approval_kind") != "plan_authorized" or receipt.get("qa_note") != qa_note:
                raise state.WorkflowError("retry must preserve the original host QA")
        elif approved:
            raise state.WorkflowError("historical approval has no receipt")
        else:
            try:
                _prepare_delivery_v2_locked(current)
            except DeliveryV2Error as exc:
                raise state.WorkflowError("delivery validation failed") from exc
            receipt = {
                "schema_version": 1, "approval_kind": "plan_authorized", "decision": "approved",
                "job_id": current.job_id, "workflow_revision": current.revision + 1,
                "reviewed_revision": current.revision, "reviewed_workflow_sha256": current.expected_sha256,
                "approved_by": "host", "approved_at": datetime.now(timezone.utc).isoformat(),
                "qa_note": qa_note, "visual_approval": visual["artifact"],
                "delivery": final, "delivery_manifest": manifest,
            }
            _publish_receipt(path, receipt)
            _validate_plan_receipt(current, receipt, committed=False)
        if not approved:
            current.stages["delivery"]["artifacts"].append(state._artifact_record(current, path))
            state.approve(current, "delivery")
        state._synchronize_committed_job(job)
        validate_approval_receipt(job)
        return path


def _validate_plan_receipt(job: state.JobState, receipt: dict, *, committed: bool) -> dict:
    revision = job.revision if committed else job.revision + 1
    if (receipt.get("schema_version") != 1 or receipt.get("approval_kind") != "plan_authorized"
            or receipt.get("decision") != "approved" or receipt.get("approved_by") != "host"
            or receipt.get("job_id") != job.job_id
            or receipt.get("workflow_revision") != revision
            or receipt.get("reviewed_revision") != revision - 1
            or not isinstance(receipt.get("reviewed_workflow_sha256"), str)
            or not state._SHA256_RE.fullmatch(receipt["reviewed_workflow_sha256"])
            or not isinstance(receipt.get("approved_at"), str) or not receipt["approved_at"].strip()):
        raise state.WorkflowError("plan-authorized receipt kind is invalid")
    visual = validate_visual_plan_approval(job)
    if receipt.get("visual_approval") != visual["artifact"]:
        raise state.WorkflowError("visual plan approval identity changed")
    if not isinstance(receipt.get("qa_note"), str) or not receipt["qa_note"].strip():
        raise state.WorkflowError("host QA note is missing")
    if not committed:
        if (job.stages["delivery"]["status"] != "ready_for_review"
                or receipt.get("reviewed_workflow_sha256") != job.expected_sha256
                or any(r.get("path") == RECEIPT_PATH for r in job.stages["delivery"].get("artifacts", []))):
            raise state.WorkflowError("pending plan receipt no longer matches workflow")
    else:
        if job.stages["delivery"]["status"] != "approved":
            raise state.WorkflowError("plan-authorized delivery has not committed")
    return receipt


def approve_delivery(
    job: state.JobState, *, expected_revision: int,
    delivery_sha256: str, user_confirmation: str,
) -> Path:
    """Use only a real current-user confirmation, never a generated approval text.

    The sidecar first persists the exact intent. Registration and approval share
    the existing workflow CAS. An interruption keeps the intent for identical
    replay; it is never evidence of completion until registered and approved.
    """
    from .qa_delivery_v2 import DeliveryV2Error, _DeliveryLock, _prepare_delivery_v2_locked

    if (
        job.version != 2 or type(expected_revision) is not int or expected_revision < 0
        or not isinstance(delivery_sha256, str)
        or not state._SHA256_RE.fullmatch(delivery_sha256)
        or not isinstance(user_confirmation, str) or not user_confirmation.strip()
    ):
        raise state.WorkflowError("final delivery requires explicit confirmation and reviewed identity")
    with _DeliveryLock(job.job_dir):
        current = state.load_job(job.job_dir)
        status = current.stages["delivery"]["status"]
        approved = status == "approved"
        if (
            status not in {"ready_for_review", "approved"}
            or current.revision != expected_revision + int(approved)
            or any(current.stages[s]["status"] != "approved"
                   for s in state.stage_ids_for(current) if s != "delivery")
        ):
            raise state.WorkflowError("final confirmation belongs to another review revision")
        final, manifest = _delivery_identity(current)
        if final["sha256"] != delivery_sha256:
            raise state.WorkflowError("final confirmation belongs to another delivery file")
        path = current.job_dir / RECEIPT_PATH
        _check_inventory(current, pending=not approved and path.exists())
        if path.exists() or path.is_symlink():
            receipt = validate_approval_receipt(current, committed=approved)
            if receipt["user_confirmation"] != user_confirmation:
                raise state.WorkflowError("retry must preserve the original human confirmation")
        elif approved:
            raise state.WorkflowError("historical approval has no receipt; automatic signing is forbidden")
        else:
            try:
                _prepare_delivery_v2_locked(current)  # Validate sources and copies; no render.
            except DeliveryV2Error as exc:
                raise state.WorkflowError("final approval delivery validation failed") from exc
            receipt = {
                "schema_version": 1, "approval_kind": "formal_final", "decision": "approved",
                "job_id": current.job_id, "workflow_revision": current.revision + 1,
                "reviewed_revision": current.revision,
                "reviewed_workflow_sha256": current.expected_sha256,
                "approved_by": "human", "approved_at": datetime.now(timezone.utc).isoformat(),
                "user_confirmation": user_confirmation, "delivery": final,
                "delivery_manifest": manifest,
            }
            _publish_receipt(path, receipt)
            validate_approval_receipt(current, committed=False)
        if not approved:
            current.stages["delivery"]["artifacts"].append(state._artifact_record(current, path))
            state.approve(current, "delivery")
        state._synchronize_committed_job(job)
        validate_approval_receipt(job)
        return path

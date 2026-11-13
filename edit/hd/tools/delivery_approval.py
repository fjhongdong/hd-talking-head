"""Record delivery separately from the user's final acceptance."""
from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import os
from pathlib import Path
import shutil
import sys
import tempfile

from . import contract_artifacts as artifacts
from . import startup, state


def receipt_paths(manifest: dict) -> tuple[str, str]:
    """The registered manifest identifies one production, including identical-byte revisions."""
    digest = manifest.get("sha256")
    if not isinstance(digest, str) or not state._SHA256_RE.fullmatch(digest):
        raise state.WorkflowError("delivery manifest identity is invalid")
    root = f"manifests/delivery/{digest}"
    return root + "/delivered.json", root + "/accepted.json"


def _publish_once(staged: Path, path: Path) -> None:
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
                raise state.WorkflowError("exclusive delivery publication is unavailable")
            rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            rename.restype = ctypes.c_int
            if rename(source_fd, os.fsencode(staged.name), target_fd, os.fsencode(path.name), flags) != 0:
                raise OSError(ctypes.get_errno(), "exclusive delivery publication failed")
            os.fsync(target_fd)
            os.fsync(source_fd)
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)


def _publish_receipt(path: Path, receipt: dict) -> None:
    """Publish once; a retry must validate the existing receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".delivery-receipt-", dir=path.parent.parent) as directory:
        staged = Path(directory) / path.name
        artifacts.write_json_artifact(staged, receipt)
        _publish_once(staged, path)


def _stable_delivery(job: state.JobState, final: dict, manifest: dict) -> Path:
    root = job.job_dir / "delivered" / manifest["sha256"]
    for record, name in ((final, "final.mp4"), (manifest, "delivery-manifest.json")):
        expected = {**record, "path": str((root / name).relative_to(job.job_dir))}
        state._validate_record(job.job_dir, expected)
    return root / "final.mp4"


def _preserve_delivery(job: state.JobState, final: dict, manifest: dict) -> Path:
    root = job.job_dir / "delivered" / manifest["sha256"]
    if root.exists() or root.is_symlink():
        return _stable_delivery(job, final, manifest)
    root.parent.mkdir(parents=True, exist_ok=True)
    state._assert_directory(root.parent)
    with tempfile.TemporaryDirectory(prefix=".delivery-copy-", dir=root.parent) as directory:
        staged = Path(directory) / root.name
        staged.mkdir()
        for record, name in ((final, "final.mp4"), (manifest, "delivery-manifest.json")):
            copied = staged / name
            shutil.copyfile(job.job_dir / record["path"], copied)
            if state._digest(copied) != (record["sha256"], record["bytes"]):
                raise state.WorkflowError("delivery copy differs from its registered output")
            with copied.open("rb") as stream:
                os.fsync(stream.fileno())
        state._fsync_directory(staged)
        _publish_once(staged, root)
    return _stable_delivery(job, final, manifest)


def _published(job: state.JobState, relative: str) -> dict:
    matches = [r for r in job.stages["delivery"]["artifacts"] if r["path"] == relative]
    if len(matches) != 1 or matches[0] != state._artifact_record(job, job.job_dir / relative):
        raise state.WorkflowError("delivery artifact is missing or changed")
    return matches[0]


def _delivery_identity(job: state.JobState) -> tuple[dict, dict]:
    if any(stage["status"] != "completed" for stage in job.stages.values()):
        raise state.WorkflowError("delivery workflow has not completed")
    final = _published(job, "12-delivery/final.mp4")
    manifest_ref = _published(job, "12-delivery/delivery-manifest.json")
    manifest = artifacts.read_json_artifact(job.job_dir / manifest_ref["path"])
    video = manifest.get("artifacts", {}).get("final.mp4", {})
    output = video.get("output", {})
    if (manifest.get("job_id") != job.job_id or manifest.get("final_sha256") != final["sha256"]
            or output.get("sha256") != final["sha256"] or output.get("bytes") != final["bytes"]):
        raise state.WorkflowError("delivery manifest differs from its final output")
    if startup.is_skill_job(job):
        previews = [record for record in job.stages["preview"]["artifacts"]
                    if record["path"] == "11-preview/review.mp4"]
        if (len(previews) != 1 or video.get("source") != previews[0]
                or any(final[key] != previews[0][key] for key in ("sha256", "bytes"))):
            raise state.WorkflowError("delivery must copy the formal preview without changes")
    return final, manifest_ref


def validate_visual_plan_approval(job: state.JobState) -> dict:
    """Check the real complete-list and spending authorization."""
    from . import visual_confirmation
    authorized = visual_confirmation.validate_visual_authorization(job)
    stage = job.stages["visual_direction"]
    mappings = [record for record in stage["artifacts"]
                if record["path"].endswith("/" + visual_confirmation.MAPPING)]
    if stage["status"] != "completed" or len(mappings) != 1:
        raise state.WorkflowError("visual execution mapping is not completed")
    mapping = visual_confirmation._read(visual_confirmation._exact(job.job_dir, mappings[0]))
    if (mapping.get("source_approval") != authorized["artifact"]
            or mapping.get("proposal") != authorized["payload"]["source"]):
        raise state.WorkflowError("visual execution belongs to another authorization")
    return authorized


def validate_delivery_receipt(job: state.JobState) -> dict:
    final, manifest = _delivery_identity(job)
    path = job.job_dir / receipt_paths(manifest)[0]
    state._assert_regular(path)
    receipt = artifacts.read_json_artifact(path)
    authorization = validate_visual_plan_approval(job)
    if (receipt.get("schema_version") != 1 or receipt.get("decision") != "delivered"
            or receipt.get("job_id") != job.job_id
            or receipt.get("delivery") != final or receipt.get("delivery_manifest") != manifest
            or receipt.get("visual_authorization") != authorization["artifact"]
            or not isinstance(receipt.get("delivered_at"), str) or not receipt["delivered_at"].strip()):
        raise state.WorkflowError("delivery receipt does not match the current output")
    _stable_delivery(job, final, manifest)
    return receipt


def delivery_file(job: state.JobState) -> Path:
    receipt = validate_delivery_receipt(job)
    return job.job_dir / "delivered" / receipt["delivery_manifest"]["sha256"] / "final.mp4"


def _validate_formal_composition(job: state.JobState, final: dict) -> None:
    from . import material_usage, preview_v2, visual_confirmation

    try:
        report = artifacts.read_json_artifact(
            preview_v2._published_preview(job, "11-preview/qa-report.json"))
        preview_v2.validate_published_composition(job, report)
        if report.get("preview_sha256") != final["sha256"]:
            raise preview_v2.PreviewV2Error("preview video differs from its composition report")
    except (preview_v2.PreviewV2Error, artifacts.ContractArtifactError,
            visual_confirmation.VisualConfirmationError,
            material_usage.MaterialUsageError, OSError) as exc:
        raise state.WorkflowError(f"formal preview is invalid: {exc}") from exc


def record_delivery(job: state.JobState) -> Path:
    """Machine completion records delivered, never accepted."""
    from .qa_delivery_v2 import _DeliveryLock
    with _DeliveryLock(job.job_dir):
        current = state.load_job(job.job_dir)
        final, manifest = _delivery_identity(current)
        authorization = validate_visual_plan_approval(current)
        path = current.job_dir / receipt_paths(manifest)[0]
        if path.exists() or path.is_symlink():
            validate_delivery_receipt(current)
        else:
            if startup.is_skill_job(current):
                _validate_formal_composition(current, final)
            _preserve_delivery(current, final, manifest)
            _publish_receipt(path, {"schema_version": 1, "decision": "delivered",
                "job_id": current.job_id, "workflow_revision": current.revision,
                "delivered_at": datetime.now(timezone.utc).isoformat(),
                "delivery": final, "delivery_manifest": manifest,
                "visual_authorization": authorization["artifact"]})
        state._synchronize_committed_job(job)
        return path


def validate_acceptance(job: state.JobState) -> dict:
    delivered = validate_delivery_receipt(job)
    return _validate_acceptance_receipt(job, delivered)


def _validate_acceptance_receipt(job: state.JobState, delivered: dict) -> dict:
    path = job.job_dir / receipt_paths(delivered["delivery_manifest"])[1]
    state._assert_regular(path)
    receipt = artifacts.read_json_artifact(path)
    if (receipt.get("schema_version") != 1 or receipt.get("decision") != "accepted"
            or receipt.get("accepted_by") != "user" or receipt.get("job_id") != job.job_id
            or receipt.get("delivery") != delivered["delivery"]
            or receipt.get("delivery_manifest") != delivered["delivery_manifest"]
            or not isinstance(receipt.get("user_confirmation"), str) or not receipt["user_confirmation"].strip()
            or not isinstance(receipt.get("accepted_at"), str) or not receipt["accepted_at"].strip()):
        raise state.WorkflowError("user acceptance does not match the current delivered output")
    return receipt


def current_delivery_status(job: state.JobState) -> dict:
    """Read only the current production; past acceptance never accepts a revision."""
    if any(stage["status"] != "completed" for stage in job.stages.values()):
        return {"delivery_status": "pending"}
    manifest = _published(job, "12-delivery/delivery-manifest.json")
    delivered_path, accepted_path = receipt_paths(manifest)
    path = job.job_dir / delivered_path
    if not path.exists() and not path.is_symlink():
        return {"delivery_status": "pending"}
    delivered = validate_delivery_receipt(job)
    result = {"delivery_status": "delivered",
              "delivery_manifest_sha256": manifest["sha256"],
              "delivery_sha256": delivered["delivery"]["sha256"],
              "delivery_file": str(job.job_dir / "delivered" / manifest["sha256"] / "final.mp4")}
    acceptance = job.job_dir / accepted_path
    if acceptance.exists() or acceptance.is_symlink():
        _validate_acceptance_receipt(job, delivered)
        result["delivery_status"] = "accepted"
    return result


def approve_delivery(job: state.JobState, *, delivery_manifest_sha256: str,
                     delivery_sha256: str, user_confirmation: str) -> Path:
    """Record actual user feedback after delivery; no machine QA approval exists."""
    from .qa_delivery_v2 import _DeliveryLock
    if (not isinstance(delivery_manifest_sha256, str)
            or not state._SHA256_RE.fullmatch(delivery_manifest_sha256)
            or not isinstance(user_confirmation, str)
            or not user_confirmation.strip() or not isinstance(delivery_sha256, str)
            or not state._SHA256_RE.fullmatch(delivery_sha256)):
        raise state.WorkflowError("acceptance requires actual user feedback and the delivered identity")
    with _DeliveryLock(job.job_dir):
        current = state.load_job(job.job_dir)
        delivered = validate_delivery_receipt(current)
        if (delivered["delivery_manifest"]["sha256"] != delivery_manifest_sha256
                or delivered["delivery"]["sha256"] != delivery_sha256):
            raise state.WorkflowError("user acceptance belongs to another delivered output")
        path = current.job_dir / receipt_paths(delivered["delivery_manifest"])[1]
        if path.exists() or path.is_symlink():
            receipt = _validate_acceptance_receipt(current, delivered)
            if receipt["user_confirmation"] != user_confirmation:
                raise state.WorkflowError("retry must preserve the actual user feedback")
        else:
            _publish_receipt(path, {"schema_version": 1, "decision": "accepted", "accepted_by": "user",
                "job_id": current.job_id, "workflow_revision": current.revision,
                "accepted_at": datetime.now(timezone.utc).isoformat(), "user_confirmation": user_confirmation,
                "delivery": delivered["delivery"], "delivery_manifest": delivered["delivery_manifest"]})
        state._synchronize_committed_job(job)
        return path

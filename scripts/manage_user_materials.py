#!/usr/bin/env python3
"""Plan material changes; commit only changes that cannot invalidate approvals."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path

import initialize_video_job as initializer
from create_job_workspace import _media_type, _sha256, _write_json_atomic


class MaterialChangeError(RuntimeError):
    """A material change is unsafe, stale, or needs scoped workflow support."""


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OP_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_STAGE_DIRS = {
    "content_analysis": "02-content-analysis", "cover_direction": "03-cover-direction",
    "cover": "04-cover", "visual_direction": "07-visual-direction",
    "visual_canary": "08-visual-canary", "visual_assets": "09-visual-assets",
    "subtitles": "10-subtitles", "preview": "11-preview", "delivery": "12-delivery",
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _path(root, relative):
    try:
        return initializer._local_path(root, relative)
    except initializer.InitializeJobError as exc:
        raise MaterialChangeError(str(exc)) from exc


def _regular(path):
    try:
        info = path.lstat()
        if (path.absolute() != path.resolve() or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1):
            raise MaterialChangeError(f"not an exclusive regular file: {path}")
        return info
    except OSError as exc:
        raise MaterialChangeError(f"file unavailable: {path}") from exc


def _json(path):
    _regular(path)
    try:
        return initializer._read_record(path)
    except (OSError, ValueError, initializer.InitializeJobError) as exc:
        raise MaterialChangeError(f"invalid JSON record: {path}") from exc


def _identity(info):
    # Reading can legitimately update atime on another filesystem.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


def read_material_index(workspace, *, verify_files=True):
    """Keep annotations; validate identities and optionally imported bytes."""
    workspace = Path(workspace).absolute()
    index = _json(_path(workspace, "00-user-provided/material-index.json"))
    if (index.get("schema_version") != 1 or index.get("job_id") != workspace.name
            or type(index.get("materials")) is not list or type(index.get("assets")) is not list
            or type(index.get("material_revision", 0)) is not int
            or index.get("material_revision", 0) < 0):
        raise MaterialChangeError("material index schema is invalid")
    assets, hashes, paths = {}, set(), set()
    for asset in index["assets"]:
        if not isinstance(asset, dict):
            raise MaterialChangeError("invalid asset record")
        identifier, digest = asset.get("asset_id"), asset.get("sha256")
        relative, size = asset.get("imported_path"), asset.get("size_bytes")
        if (type(identifier) is not str or not identifier or identifier in assets
                or type(digest) is not str or not _SHA.fullmatch(digest) or digest in hashes
                or type(size) is not int or size < 0
                or asset.get("media_type") not in ("video", "images", "audio", "documents")
                or type(relative) is not str or relative in paths
                or not relative.startswith(f"00-user-provided/{asset['media_type']}/")):
            raise MaterialChangeError("invalid or duplicate asset identity")
        path = _path(workspace, relative)
        if verify_files and (_regular(path).st_size != size or _sha256(path) != digest):
            raise MaterialChangeError(f"imported asset identity changed: {relative}")
        assets[identifier] = asset
        hashes.add(digest)
        paths.add(relative)
    identifiers = set()
    for item in index["materials"]:
        if not isinstance(item, dict):
            raise MaterialChangeError("invalid material record")
        identifier = item.get("material_id")
        asset = assets.get(item.get("asset_id"))
        if (type(identifier) is not str or not re.fullmatch(r"material-[0-9]{4,}", identifier)
                or identifier in identifiers or asset is None
                or type(item.get("original_name")) is not str
                or item.get("status", "active") not in ("active", "withdrawn", "superseded")
                or any(item.get(key) != asset[key] for key in
                       ("imported_path", "sha256", "size_bytes", "media_type"))):
            raise MaterialChangeError("invalid or duplicate material identity")
        identifiers.add(identifier)
    changes = index.get("changes", [])
    if (type(changes) is not list or len(changes) != index.get("material_revision", 0)
            or any(not isinstance(change, dict) for change in changes)):
        raise MaterialChangeError("material change history is invalid")
    operation_ids = set()
    for revision, change in enumerate(changes, 1):
        operation_id = change.get("operation_id")
        if (type(operation_id) is not str or not _OP_ID.fullmatch(operation_id)
                or operation_id in operation_ids or change.get("material_revision") != revision
                or type(change.get("plan_id")) is not str or not _SHA.fullmatch(change["plan_id"])
                or change.get("material_id") not in identifiers):
            raise MaterialChangeError("material change receipt is invalid")
        operation_ids.add(operation_id)
    return index


def require_active_material(workspace, material_id, expected_sha256=None):
    """Reject withdrawn/superseded IDs even if an old rendered copy remains."""
    index = read_material_index(workspace, verify_files=False)
    matches = [item for item in index["materials"] if item["material_id"] == material_id]
    if len(matches) != 1 or matches[0].get("status", "active") != "active":
        raise MaterialChangeError("material is missing, withdrawn or superseded")
    item = matches[0]
    path = _path(Path(workspace), item["imported_path"])
    if (expected_sha256 is not None and expected_sha256 != item["sha256"]
            or _regular(path).st_size != item["size_bytes"] or _sha256(path) != item["sha256"]):
        raise MaterialChangeError("material identity changed")
    return item


def _load(workspace):
    workspace = Path(workspace).expanduser().absolute()
    if workspace.resolve() != workspace or not workspace.is_dir():
        raise MaterialChangeError("workspace must be an existing canonical directory")
    context = _json(_path(workspace, "job-context.json"))
    marker = _json(_path(workspace, "initialization.json"))
    state, identity = initializer._current_runtime(context.get("project_root"))
    if (marker.get("phase") != "ready" or marker.get("workspace") != str(workspace)
            or context.get("workspace") != str(workspace)
            or any(context.get(key) != value or marker.get(key) != value
                   for key, value in identity.items())):
        raise MaterialChangeError("workspace initialization or runtime/release identity changed")
    job_dir = workspace / "edit/hd/jobs" / state._job_id(marker["inputs"])
    if (context.get("job_dir") != str(job_dir)
            or context.get("material_index") != str(workspace / "00-user-provided/material-index.json")
            or context.get("workflow") != str(job_dir / "workflow.json")):
        raise MaterialChangeError("context paths conflict")
    job = state.load_job(job_dir)
    if job.version != 2 or job.inputs != marker["inputs"]:
        raise MaterialChangeError("primary inputs or workflow identity changed")
    return job, read_material_index(workspace)


def _references(job, target, state_module):
    """Read only current, validated usage receipts; never infer from directories."""
    from edit.hd.tools import material_usage

    references, unverified, inventory = [], [], {}
    stage_ids = state_module.stage_ids_for(job)
    order = {stage_id: index for index, stage_id in enumerate(stage_ids)}
    for stage_id in stage_ids:
        stage = job.stages[stage_id]
        records = stage.get("artifacts", [])
        if not records:
            continue
        for record in records:
            path = _path(job.job_dir, record["path"])
            inventory[record["path"]] = _sha256(path)
        try:
            receipt = material_usage.load_current_receipt(job, stage_id)
        except (material_usage.MaterialUsageError, state_module.WorkflowError):
            unverified.append(stage_id)
            continue
        for reference in receipt["references"]:
            if (
                reference["material_id"] == target["material_id"]
                and reference["material_sha256"] == target["sha256"]
            ):
                references.append({"stage": stage_id, **copy.deepcopy(reference)})
    references.sort(
        key=lambda item: (
            order[item["stage"]],
            item["consumer_id"],
            item["binding_path"],
        )
    )
    return references, unverified, inventory


def _dependents(job, state_module, stage_id):
    affected = {stage_id}
    for candidate in state_module.stage_ids_for(job):
        if candidate == stage_id:
            continue
        if any(
            dependency in affected
            for dependency in state_module.dependencies_for(job, candidate)
        ):
            affected.add(candidate)
    return affected


def _invalidation_plan(job, state_module, references):
    if not references:
        return None, [], []
    stage_ids = state_module.stage_ids_for(job)
    direct = {reference["stage"] for reference in references}
    candidates = [
        stage_id
        for stage_id in stage_ids
        if direct <= _dependents(job, state_module, stage_id)
    ]
    if not candidates:
        raise MaterialChangeError("material references have no safe invalidation root")
    earliest = max(candidates, key=stage_ids.index)
    affected = _dependents(job, state_module, earliest)
    affected_stages = [stage_id for stage_id in stage_ids if stage_id in affected]
    artifact_scope = sorted(
        {
            reference["consumer_id"]
            for reference in references
            if reference["consumer_kind"]
            in {"visual_segment", "visual_canary_segment", "visual_asset_segment"}
        }
    )
    return earliest, affected_stages, artifact_scope


def _artifact_partition(job, affected_stages):
    affected = set(affected_stages)
    reused, rebuild = [], []
    for stage_id in job.stages:
        destination = rebuild if stage_id in affected else reused
        destination.extend(
            record["path"] for record in job.stages[stage_id].get("artifacts", [])
        )
    return sorted(reused), sorted(rebuild)


def plan_material_change(workspace, operation, *, operation_id, source=None, material_id=None):
    if (operation not in ("append", "replace", "withdraw") or type(operation_id) is not str
            or not _OP_ID.fullmatch(operation_id)
            or (operation == "append") != (material_id is None)
            or (operation == "withdraw") != (source is None)):
        raise MaterialChangeError("invalid operation, ID or source arguments")
    job, index = _load(workspace)
    state_module, _identity_record = initializer._current_runtime(
        _json(_path(job.root, "job-context.json"))["project_root"]
    )
    source_record = None
    if source is not None:
        path = Path(source).expanduser().absolute()
        before = _regular(path)
        source_record = {"path": str(path), "sha256": _sha256(path), "size_bytes": before.st_size}
        if _identity(_regular(path)) != _identity(before):
            raise MaterialChangeError("source changed during planning")
    blockers, references, unverified, inventory = [], [], [], {}
    if material_id is not None:
        matches = [item for item in index["materials"] if item["material_id"] == material_id]
        if len(matches) != 1:
            raise MaterialChangeError("unknown material ID")
        target = matches[0]
        if target.get("status", "active") != "active":
            blockers.append("material_not_active")
        if any(target["sha256"] == item["sha256"] for item in job.inputs.values()):
            blockers.append("primary_input")
        references, unverified, inventory = _references(
            job, target, state_module
        )
        if unverified:
            blockers.append("material_usage_unverified")
    earliest, affected_stages, artifact_scope = _invalidation_plan(
        job, state_module, references
    )
    reused_artifacts, rebuild_artifacts = _artifact_partition(
        job, affected_stages
    )
    workflow_action = (
        "stop_before_mutation"
        if blockers
        else "revise"
        if references and operation != "append"
        else "preserve"
    )
    required_human_gates = ["confirm_material_change_plan"]
    if workflow_action == "revise":
        required_human_gates.extend(
            f"reapprove:{stage_id}" for stage_id in affected_stages
        )
    plan = {"schema_version": 2, "workspace": str(job.root), "operation": operation,
            "operation_id": operation_id, "material_id": material_id, "source": source_record,
            "index_sha256": _sha256(job.root / "00-user-provided/material-index.json"),
            "workflow_sha256": _sha256(job.job_dir / "workflow.json"),
            "workflow_revision": job.revision, "material_revision": index.get("material_revision", 0),
            "direct_references": references, "unverified_stages": unverified,
            "artifact_inventory": inventory, "affected_stages": affected_stages,
            "earliest_stage": earliest, "artifact_scope": artifact_scope,
            "reused_artifacts": reused_artifacts,
            "rebuild_artifacts": rebuild_artifacts,
            "required_human_gates": required_human_gates,
            "blockers": blockers, "workflow_action": workflow_action}
    return {**plan, "plan_hash": _digest(plan)}


@contextmanager
def _lock(workspace):
    path = _path(workspace, "00-user-provided/.materials.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise MaterialChangeError("material lock must be exclusive")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MaterialChangeError("another material change is running") from exc
        yield
    finally:
        os.close(descriptor)


def _validate_plan(plan, confirmed_plan_hash):
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != 2
        or plan.get("plan_hash")
        != _digest({k: v for k, v in plan.items() if k != "plan_hash"})
    ):
        raise MaterialChangeError("invalid plan identity")
    if confirmed_plan_hash != plan["plan_hash"]:
        raise MaterialChangeError("human confirmation does not match the plan")


def _transaction_path(workspace, operation_id):
    if type(operation_id) is not str or not _OP_ID.fullmatch(operation_id):
        raise MaterialChangeError("invalid material operation ID")
    root = _path(workspace, "00-user-provided/material-transactions")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{operation_id}.json"


def _write_transaction(path, transaction):
    _write_json_atomic(path, transaction)


def _change_for(index, operation_id):
    return next(
        (
            copy.deepcopy(change)
            for change in index.get("changes", [])
            if change.get("operation_id") == operation_id
        ),
        None,
    )


def _import_source(job, updated, source):
    asset = next(
        (asset for asset in updated["assets"] if asset["sha256"] == source["sha256"]),
        None,
    )
    if asset is not None:
        return asset
    path = Path(source["path"])
    digest, media_type = source["sha256"], _media_type(path)
    relative = f"00-user-provided/{media_type}/{digest}{path.suffix.casefold()}"
    output = _path(job.root, relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(
        f".{output.name}.{secrets.token_hex(6)}.importing"
    )
    try:
        if not output.exists():
            with path.open("rb") as src, temporary.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            if (
                _regular(temporary).st_size != source["size_bytes"]
                or _sha256(temporary) != digest
            ):
                raise MaterialChangeError("source changed during copy")
            os.link(temporary, output)
            temporary.unlink()
        if (
            _regular(output).st_size != source["size_bytes"]
            or _sha256(output) != digest
        ):
            raise MaterialChangeError("existing import identity conflicts")
    finally:
        if temporary.exists():
            temporary.unlink()
    asset = {
        "asset_id": f"asset-{digest}",
        "sha256": digest,
        "size_bytes": source["size_bytes"],
        "media_type": media_type,
        "imported_path": relative,
    }
    updated["assets"].append(asset)
    return asset


def _finish_workflow_revision(job, index, receipt, plan, state_module):
    if plan["workflow_action"] != "revise":
        receipt["workflow_revision_after"] = receipt["workflow_revision_before"]
        change = next(
            item
            for item in index["changes"]
            if item["operation_id"] == plan["operation_id"]
        )
        change.update(copy.deepcopy(receipt))
        _write_json_atomic(job.root / "00-user-provided/material-index.json", index)
        return job, index, receipt
    current = state_module.load_job(job.job_dir)
    before = receipt["workflow_revision_before"]
    scope = tuple(plan["artifact_scope"])
    already_revised = (
        current.revision == before + 1
        and current.stages[plan["earliest_stage"]]["status"] == "needs_revision"
        and current.stages[plan["earliest_stage"]].get("artifact_scope", [])
        == list(scope)
    )
    if current.revision == before:
        try:
            state_module.revise(
                current,
                plan["earliest_stage"],
                f"confirmed material {plan['operation']} {plan['material_id']} ({plan['operation_id']})",
                scope,
            )
        except BaseException:
            current = state_module.load_job(job.job_dir)
            already_revised = (
                current.revision == before + 1
                and current.stages[plan["earliest_stage"]]["status"]
                == "needs_revision"
                and current.stages[plan["earliest_stage"]].get(
                    "artifact_scope", []
                )
                == list(scope)
            )
            if not already_revised:
                raise
    elif not already_revised:
        raise MaterialChangeError("workflow changed before confirmed revision")
    receipt["workflow_revision_after"] = before + 1
    change = next(
        item
        for item in index["changes"]
        if item["operation_id"] == plan["operation_id"]
    )
    change.update(copy.deepcopy(receipt))
    _write_json_atomic(job.root / "00-user-provided/material-index.json", index)
    return current, index, receipt


def apply_material_change(workspace, plan, *, confirmed_plan_hash=None):
    """Apply one exact human-confirmed plan and resume the same operation safely."""
    _validate_plan(plan, confirmed_plan_hash)
    job, _ = _load(workspace)
    if plan.get("workspace") != str(job.root):
        raise MaterialChangeError("plan belongs to another workspace")
    with _lock(job.root):
        job, index = _load(job.root)
        context = _json(_path(job.root, "job-context.json"))
        state_module, _identity_record = initializer._current_runtime(
            context["project_root"]
        )
        transaction_path = _transaction_path(job.root, plan["operation_id"])
        transaction = _json(transaction_path) if transaction_path.exists() else None
        if transaction is not None and (
            transaction.get("schema_version") != 1
            or transaction.get("operation_id") != plan["operation_id"]
            or transaction.get("plan_hash") != plan["plan_hash"]
            or transaction.get("phase")
            not in {"prepared", "material_committed", "workflow_revised"}
        ):
            raise MaterialChangeError(
                "operation ID already belongs to another material plan"
            )
        committed = _change_for(index, plan["operation_id"])
        if committed is not None and committed.get("plan_id") != plan["plan_hash"]:
            raise MaterialChangeError("operation ID already belongs to another plan")
        if transaction is not None and transaction["phase"] == "workflow_revised":
            if committed is None:
                raise MaterialChangeError("completed material transaction is incomplete")
            return committed
        if committed is not None:
            if transaction is None:
                transaction = {
                    "schema_version": 1,
                    "operation_id": plan["operation_id"],
                    "plan_hash": plan["plan_hash"],
                    "phase": "material_committed",
                }
                _write_transaction(transaction_path, transaction)
            job, index, committed = _finish_workflow_revision(
                job, index, committed, plan, state_module
            )
            _write_transaction(
                transaction_path,
                {**transaction, "phase": "workflow_revised", "receipt": committed},
            )
            return committed
        source = plan.get("source")
        current = plan_material_change(
            job.root, plan.get("operation"), operation_id=plan.get("operation_id"),
            source=source["path"] if isinstance(source, dict) else None,
            material_id=plan.get("material_id"),
        )
        if current != plan:
            raise MaterialChangeError("stale plan; inspect current material impact again")
        if current["blockers"]:
            raise MaterialChangeError("change blocked: " + ", ".join(current["blockers"]))
        transaction = {
            "schema_version": 1,
            "operation_id": plan["operation_id"],
            "plan_hash": plan["plan_hash"],
            "phase": "prepared",
            "workflow_revision_before": job.revision,
            "index_sha256_before": plan["index_sha256"],
        }
        _write_transaction(transaction_path, transaction)
        updated = copy.deepcopy(index)
        new_id = plan["material_id"]
        if source is not None:
            asset = _import_source(job, updated, source)
            new_id = f"material-{1 + max((int(m['material_id'].split('-')[1]) for m in updated['materials']), default=0):04d}"
            updated["materials"].append({**asset, "material_id": new_id,
                                         "original_name": Path(source["path"]).name, "status": "active"})
        if plan["operation"] != "append":
            old = next(m for m in updated["materials"] if m["material_id"] == plan["material_id"])
            old["status"] = "superseded" if source else "withdrawn"
            if source:
                old["replaced_by"] = new_id
        # Hashes also detect a legacy runner or annotation writer advancing while
        # copying. Operators must keep runners paused; this is not their lock.
        if plan_material_change(job.root, plan["operation"], operation_id=plan["operation_id"],
                                source=source["path"] if source else None,
                                material_id=plan["material_id"]) != plan:
            raise MaterialChangeError("plan changed before index commit; retry from inspection")
        receipt = {"operation_id": plan["operation_id"], "plan_id": plan["plan_hash"],
                   "operation": plan["operation"], "material_id": new_id,
                   "material_revision": index.get("material_revision", 0) + 1,
                   "workflow_revision": job.revision,
                   "workflow_revision_before": job.revision,
                   "workflow_revision_after": None,
                   "workflow_action": plan["workflow_action"],
                   "earliest_stage": plan["earliest_stage"],
                   "artifact_scope": copy.deepcopy(plan["artifact_scope"])}
        updated["material_revision"] = receipt["material_revision"]
        updated.setdefault("changes", []).append(receipt)
        _write_json_atomic(job.root / "00-user-provided/material-index.json", updated)
        transaction = {**transaction, "phase": "material_committed", "receipt": receipt}
        _write_transaction(transaction_path, transaction)
        job, updated, receipt = _finish_workflow_revision(
            job, updated, receipt, plan, state_module
        )
        _write_transaction(
            transaction_path,
            {**transaction, "phase": "workflow_revised", "receipt": receipt},
        )
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("operation", choices=("append", "replace", "withdraw"))
    plan.add_argument("--operation-id", required=True)
    plan.add_argument("--source", type=Path)
    plan.add_argument("--material-id")
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--confirmed-plan-hash", required=True)
    args = parser.parse_args()
    try:
        result = (plan_material_change(args.workspace, args.operation,
                  operation_id=args.operation_id, source=args.source, material_id=args.material_id)
                  if args.command == "plan" else apply_material_change(
                      args.workspace,
                      _json(args.plan),
                      confirmed_plan_hash=args.confirmed_plan_hash,
                  ))
    except (MaterialChangeError, initializer.InitializeJobError, OSError, ValueError) as exc:
        parser.exit(2, f"material change stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

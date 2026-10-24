#!/usr/bin/env python3
"""Explicitly rebind one paused Job to a verified Skill and runtime release."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from verify_skill_release import verify_release


def migrate(
    context_path: Path,
    *,
    expected_context_sha256: str,
    expected_revision: int,
    allowed_module: str | list[str] | None,
    reason: str,
    dry_run: bool,
    project_root: Path | None = None,
    user_confirmation: str | None = None,
) -> dict:
    if not reason.strip() or context_path.is_symlink() or not context_path.is_file():
        raise ValueError("migration requires a regular Job context and a reason")
    context_path = context_path.resolve()
    original_context = json.loads(context_path.read_text(encoding="utf-8"))
    project = Path(original_context["project_root"])
    target_project = project_root.resolve() if project_root is not None else project.resolve()
    cross_root = target_project != project.resolve()
    if cross_root and (not user_confirmation or not user_confirmation.strip()):
        raise ValueError("cross-root migration requires explicit user confirmation")
    import_project = target_project if cross_root else project
    if str(import_project) not in sys.path:
        sys.path.insert(0, str(import_project))
    from edit.hd.tools import contract_artifacts, startup, state

    if contract_artifacts.sha256_file(context_path) != expected_context_sha256:
        raise ValueError("Job context changed before migration")
    context = contract_artifacts.read_json_artifact(context_path)
    job = state.load_job(Path(context["job_dir"]))
    if context_path != job.root / "job-context.json" or job.revision != expected_revision:
        raise ValueError("Job identity or workflow revision changed")
    startup.assert_project_origin(import_project)
    previous_runtime = context["runtime"]
    old_modules = previous_runtime["modules"]
    if cross_root:
        release_root = Path(__file__).resolve().parents[1]
        if release_root.parents[1] != target_project:
            raise ValueError("target project does not own this Skill release")
        current_stage = state.current_stage(job)
        if current_stage == "delivery":
            ids = list(state.stage_ids_for(job))
            if job.stages[current_stage]["status"] != "ready_for_review" or any(
                job.stages[item]["status"] != "approved" for item in ids[:-1]
            ):
                raise ValueError("cross-root migration requires a paused delivery review with approved prior stages")
        elif job.stages.get(current_stage, {}).get("status") != "needs_revision":
            raise ValueError("cross-root migration is allowed only for delivery review or needs_revision")
        target_identity = startup.runtime_identity(target_project)
        comparable = lambda value: {key: item for key, item in value.items()
                                    if key not in {"modules", "project_root"}}
        if comparable(previous_runtime) != comparable(target_identity):
            raise ValueError("target runtime Python, compositor, or contract differs from the Job")
        new_modules = target_identity.get("modules", {})
        changed_modules = sorted(key for key in set(old_modules) | set(new_modules)
                                 if old_modules.get(key) != new_modules.get(key))
        permitted = ([allowed_module] if isinstance(allowed_module, str) else allowed_module) or []
        if sorted(set(permitted)) != sorted(permitted) or changed_modules != sorted(permitted):
            raise ValueError("cross-root runtime changes must match the explicit allowed modules")
        current_runtime = target_identity
    else:
        current_runtime = startup.runtime_identity(project)
        if {key: value for key, value in previous_runtime.items() if key != "modules"} != {
            key: value for key, value in current_runtime.items() if key != "modules"
        }:
            raise ValueError("runtime contract, project, or Python changed")
        new_modules = current_runtime["modules"]
        changed_modules = sorted(key for key in set(old_modules) | set(new_modules)
                                if old_modules.get(key) != new_modules.get(key))
        permitted = ([allowed_module] if isinstance(allowed_module, str) else allowed_module) or []
        if len(set(permitted)) != len(permitted):
            raise ValueError("allowed runtime modules must be explicit and unique")
        permitted = sorted(permitted)
        if changed_modules != permitted or (changed_modules and state.current_stage(job) not in {
            stage_id for stage_id, stage in job.stages.items() if stage["status"] == "needs_revision"
        }):
            raise ValueError("runtime change is outside the paused stage or allowed module")
        release_root = Path(context["skill_release"]["root"])
    release = verify_release(release_root)
    if release["status"] != "pass":
        raise ValueError("current Skill release is invalid")
    new_release = {
        key: release[key] for key in ("root", "release_id", "manifest_sha256")
    }
    if not cross_root and context["skill_release"]["root"] != new_release["root"]:
        raise ValueError("Skill root changed")
    updated = copy.deepcopy(context)
    updated["runtime"] = current_runtime
    updated["skill_release"] = new_release
    if cross_root:
        updated["project_root"] = str(target_project)
    if updated == context:
        raise ValueError("there is no release or runtime change to migrate")
    updated_sha = contract_artifacts.sha256_json(updated)
    audit_path = job.job_dir / "manifests" / f"context-migration-r{expected_revision}-{updated_sha[:12]}.json"
    audit = {
        "reason": reason,
        "workflow_revision": expected_revision,
        "current_stage": state.current_stage(job),
        "context_before_sha256": expected_context_sha256,
        "context_after_sha256": updated_sha,
        "skill_release_before": context["skill_release"],
        "skill_release_after": new_release,
        "runtime_module_changes": {
            key: {"before": old_modules.get(key), "after": new_modules.get(key)}
            for key in changed_modules
        },
        "provider_config_changed": False,
        "workflow_changed": False,
    }
    if cross_root:
        setup_path = job.job_dir / "manifests/setup-approval.json"
        audit.update({
            "user_confirmation": user_confirmation,
            "context_before": context,
            "context_after": updated,
            "setup_approval": contract_artifacts.read_json_artifact(setup_path),
            "setup_approval_sha256": contract_artifacts.sha256_file(setup_path),
        })
    if audit_path.exists() and contract_artifacts.read_json_artifact(audit_path) != audit:
        raise ValueError("migration audit conflicts with this request")
    if not dry_run:
        if state.load_job(job.job_dir).revision != expected_revision or (
            contract_artifacts.sha256_file(context_path) != expected_context_sha256
        ):
            raise ValueError("Job changed during migration")
        if not audit_path.exists():
            contract_artifacts.write_json_artifact(audit_path, audit)
        contract_artifacts.write_json_artifact(context_path, updated)
        if contract_artifacts.sha256_file(context_path) != updated_sha:
            raise ValueError("migrated Job context does not match its audit")
    return {"status": "planned" if dry_run else "migrated", "audit": str(audit_path),
            "context_sha256": updated_sha, "changed_modules": changed_modules}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--expected-context-sha256", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--allowed-module", action="append")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--user-confirmation")
    args = parser.parse_args()
    try:
        result = migrate(
            args.job_context,
            expected_context_sha256=args.expected_context_sha256,
            expected_revision=args.expected_revision,
            allowed_module=args.allowed_module,
            reason=args.reason,
            dry_run=args.dry_run,
            project_root=args.project_root,
            user_confirmation=args.user_confirmation,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"migration stopped: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Runtime WorkflowError (and equivalent contract failures) are user-facing
        # stops; never expose an implementation traceback from this CLI.
        print(f"migration stopped: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

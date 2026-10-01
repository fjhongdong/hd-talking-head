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
) -> dict:
    if not reason.strip() or context_path.is_symlink() or not context_path.is_file():
        raise ValueError("migration requires a regular Job context and a reason")
    context_path = context_path.resolve()
    project = Path(json.loads(context_path.read_text(encoding="utf-8"))["project_root"])
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    from edit.hd.tools import contract_artifacts, startup, state

    if contract_artifacts.sha256_file(context_path) != expected_context_sha256:
        raise ValueError("Job context changed before migration")
    context = contract_artifacts.read_json_artifact(context_path)
    job = state.load_job(Path(context["job_dir"]))
    if context_path != job.root / "job-context.json" or job.revision != expected_revision:
        raise ValueError("Job identity or workflow revision changed")
    startup.assert_project_origin(project)
    current_runtime = startup.runtime_identity(project)
    previous_runtime = context["runtime"]
    if {key: value for key, value in previous_runtime.items() if key != "modules"} != {
        key: value for key, value in current_runtime.items() if key != "modules"
    }:
        raise ValueError("runtime contract, project, or Python changed")
    old_modules = previous_runtime["modules"]
    new_modules = current_runtime["modules"]
    changed_modules = sorted(
        key for key in set(old_modules) | set(new_modules)
        if old_modules.get(key) != new_modules.get(key)
    )
    permitted = ([allowed_module] if isinstance(allowed_module, str) else allowed_module) or []
    if len(set(permitted)) != len(permitted):
        raise ValueError("allowed runtime modules must be explicit and unique")
    permitted = sorted(permitted)
    if changed_modules != permitted or (
        changed_modules and state.current_stage(job) not in {
            stage_id for stage_id, stage in job.stages.items()
            if stage["status"] == "needs_revision"
        }
    ):
        raise ValueError("runtime change is outside the paused stage or allowed module")
    release_root = Path(context["skill_release"]["root"])
    release = verify_release(release_root)
    if release["status"] != "pass":
        raise ValueError("current Skill release is invalid")
    new_release = {
        key: release[key] for key in ("root", "release_id", "manifest_sha256")
    }
    if context["skill_release"]["root"] != new_release["root"]:
        raise ValueError("Skill root changed")
    updated = copy.deepcopy(context)
    updated["runtime"] = current_runtime
    updated["skill_release"] = new_release
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
    args = parser.parse_args()
    try:
        result = migrate(
            args.job_context,
            expected_context_sha256=args.expected_context_sha256,
            expected_revision=args.expected_revision,
            allowed_module=args.allowed_module,
            reason=args.reason,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"migration stopped: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

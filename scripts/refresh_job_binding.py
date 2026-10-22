#!/usr/bin/env python3
"""Refresh one paused Job's Skill binding in a single auditable command.

Skill packages change; paused Jobs keep the old release identity. The resume
contract is a fixed three-step dance (migrate context -> refresh preflight ->
re-confirm setup), each with its own hashes. This helper runs the three steps
in order with the same interpreter and reports each outcome, so a resume
after a Skill update is one command instead of three error-prone ones.

Usage:
  <python> refresh_job_binding.py --job-context <workspace>/job-context.json \
      --reason "<why the Skill/runtime changed>" \
      --user-confirmation "<this resume's real user instruction>"

Environment: set HD_WHISPER_CLI / HD_WHISPER_MODEL when the Job uses the local
reference ASR (point HD_WHISPER_CLI at the real binary — Homebrew symlinks are
rejected by the anti-tamper check).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def context_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workflow_revision(job_dir: Path) -> int:
    workflow = json.loads((job_dir / "workflow.json").read_text(encoding="utf-8"))
    return int(workflow["revision"])


def run(label: str, argv: list[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(f"{label} 失败:\n{result.stdout}\n{result.stderr}\n")
        raise SystemExit(result.returncode)
    tail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    print(f"{label}: {tail[:160]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--user-confirmation", required=True)
    args = parser.parse_args()

    context_path = args.job_context.resolve()
    context = json.loads(context_path.read_text(encoding="utf-8"))
    job_dir = Path(context["job_dir"])
    project_root = Path(context["project_root"])

    run("迁移上下文", [
        sys.executable, str(SKILL / "scripts/migrate_job_context.py"),
        "--job-context", str(context_path),
        "--expected-context-sha256", context_sha256(context_path),
        "--expected-revision", str(workflow_revision(job_dir)),
        "--reason", args.reason,
    ])
    run("刷新预检", [
        sys.executable, str(SKILL / "scripts/project_python.py"),
        "--project-root", str(project_root), "--",
        str(SKILL / "scripts/dependency_preflight.py"),
        "--manifest", str(SKILL / "references/dependency-manifest.json"),
        "--project-root", str(project_root),
        "--job-context", str(context_path),
        "--output", str(job_dir / "manifests/dependency-preflight.json"),
        "--summary-only",
    ])
    run("刷新配置批准", [
        sys.executable, str(SKILL / "scripts/project_python.py"),
        "--project-root", str(project_root), "--",
        str(SKILL / "scripts/confirm_job_setup.py"),
        "--job-context", str(context_path),
        "--user-confirmation", args.user_confirmation,
    ])
    print("Job 绑定已刷新;按合同从最早未完成阶段继续。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

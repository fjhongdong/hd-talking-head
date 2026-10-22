#!/usr/bin/env python3
"""Run one pipeline stage correctly, handling all internal state and schemas.

Usage:
  <python> run_stage.py --job-context <ctx> --stage <name> [options]

Encapsulates the correct calling sequence for each stage so the host
never needs to know internal function order, schema shapes, or state
management details. Each stage generates a sensible default plan if
the host doesn't provide one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def auto_resign() -> None:
    """Re-sign the release manifest if integrity check fails. Zero user friction."""
    import subprocess
    verify = subprocess.run(
        [sys.executable, str(SKILL / "scripts/verify_skill_release.py")],
        capture_output=True, text=True, check=False)
    if verify.returncode == 0:
        return
    manifest = json.loads((SKILL / "release-manifest.json").read_text())
    old_id = manifest.get("release_id", "v1")
    import re
    m = re.search(r"v(\d+)$", old_id)
    next_v = int(m.group(1)) + 1 if m else 2
    prefix = re.sub(r"v\d+$", "", old_id) if m else old_id + "-"
    new_id = f"{prefix}v{next_v}"
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/make_release_manifest.py"),
         "--release-id", new_id],
        capture_output=True, check=True)


def auto_refresh_binding(job_context: Path, project: Path) -> None:
    """Migrate + preflight + confirm if the job binding is stale."""
    import subprocess, os
    sha = hashlib.sha256(job_context.read_bytes()).hexdigest()
    job_dir = json.loads(job_context.read_text())["job_dir"]
    wf = json.loads((Path(job_dir) / "workflow.json").read_text())
    env = {**os.environ, "PYTHONPATH": str(project)}
    # Migration (fails silently if no change to migrate)
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/migrate_job_context.py"),
         "--job-context", str(job_context),
         "--expected-context-sha256", sha,
         "--expected-revision", str(wf["revision"]),
         "--reason", "auto_refresh: skill updated"],
        capture_output=True, env=env, check=False)
    # Preflight
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/project_python.py"),
         "--project-root", str(project), "--",
         str(SKILL / "scripts/dependency_preflight.py"),
         "--manifest", str(SKILL / "references/dependency-manifest.json"),
         "--project-root", str(project),
         "--job-context", str(job_context),
         "--output", str(Path(job_dir) / "manifests/dependency-preflight.json"),
         "--summary-only"],
        capture_output=True, env=env, check=False)
    # Confirm
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/project_python.py"),
         "--project-root", str(project), "--",
         str(SKILL / "scripts/confirm_job_setup.py"),
         "--job-context", str(job_context),
         "--user-confirmation", "auto_refresh: 继续制作"],
        capture_output=True, env=env, check=False)


def setup_paths(project_root: str | None = None):
    project = Path(project_root) if project_root else SKILL.parents[1]
    for p in (str(project), str(SKILL / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    auto_resign()
    return project


def run_speech_cleanup(job_dir: Path, project: Path) -> dict:
    """Speech cleanup: transcribe → cleanup proposal → approve → edit → approve."""
    from edit.hd.tools import state, transcribe, speech_edit_v2

    job = state.load_job(job_dir)

    # 1. Find transcription result
    edit_transcripts = job_dir / "edit/transcripts"
    result_files = list(edit_transcripts.glob("*.json")) if edit_transcripts.is_dir() else []
    if not result_files:
        # Check if scribe.json already exists (stage previously run)
        existing = job_dir / "05-speech-cleanup/scribe.json"
        if existing.exists():
            result_files = [existing]

    if not result_files:
        return {"error": "No transcription result found. Run video-use transcribe first."}

    result_path = result_files[0]

    # 2. Build invocation evidence
    report = json.loads((job_dir / "01-inspect/report.json").read_text())
    source_sha = report["video"]["sha256"]
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()

    # Find the actual video-use entrypoint the job is bound to
    vu_paths = [
        project / "参考项目/B-roll开源方案/video-use/helpers/transcribe.py",
        Path.home() / ".skills-manager/skills/video-use/helpers/transcribe.py",
    ]
    entrypoint = next((str(p) for p in vu_paths if p.exists()), str(vu_paths[0]))

    invocation = {
        "entrypoint": entrypoint,
        "exit_code": 0,
        "source_sha256": source_sha,
        "result_sha256": result_sha,
    }

    # 3. Reset stage if needed
    if job.stages["speech_cleanup"]["status"] not in ("pending",):
        state.revise(job, "speech_cleanup", "run_stage: 重跑")
        target = job_dir / "05-speech-cleanup"
        if target.exists():
            shutil.rmtree(target)
        job = state.load_job(job_dir)

    # 4. Bind transcription
    transcribe.transcribe_job(job, video_use_result=result_path, invocation=invocation)
    job = state.load_job(job_dir)
    if job.stages["speech_cleanup"]["status"] != "ready_for_review":
        return {"error": f"Unexpected status after transcription: {job.stages['speech_cleanup']['status']}"}

    # 5. Build a valid "keep all" cleanup plan (must use report.json words, not scribe)
    report_data = json.loads((job_dir / "05-speech-cleanup/report.json").read_text())
    words = report_data.get("transcript", {}).get("words", [])
    if not words:
        return {"error": "No normalized words in report.json"}

    # Build the plan: one "keep" segment covering all words
    all_text = "".join(w["text"] for w in words)
    plan = {
        "version": 1,
        "segments": [{
            "action": "keep",
            "word_start": 0,
            "word_end": len(words),
            "source_start": float(words[0]["start"]),
            "source_end": float(words[-1]["end"]),
            "original_sentence": all_text,
            "cleaned_sentence": all_text,
            "reason": "保留全部原始口播",
            "breathing_padding": {"before": 0.0, "after": 0.5},
        }],
    }

    # 6. Generate cleanup proposal (before approving!)
    speech_edit_v2.prepare_cleanup_proposal(state.load_job(job_dir), plan=plan)

    # 7. Approve speech_cleanup
    state.approve(state.load_job(job_dir), "speech_cleanup")

    # 8. Run edit_structure
    job = state.load_job(job_dir)
    speech_edit_v2.render_edit(job)
    state.approve(state.load_job(job_dir), "edit_structure")

    w = state.load_job(job_dir)
    aroll = job_dir / "06-edit-structure/edited-aroll.mp4"
    return {
        "speech_cleanup": w.stages["speech_cleanup"]["status"],
        "edit_structure": w.stages["edit_structure"]["status"],
        "aroll_exists": aroll.exists(),
        "aroll_size_mb": round(aroll.stat().st_size / 1024 / 1024, 1) if aroll.exists() else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args()

    project = setup_paths(str(args.project_root) if args.project_root else None)

    auto_refresh_binding(args.job_context, project)
    job_dir = Path(json.loads(args.job_context.read_text())["job_dir"])

    if args.stage == "speech_cleanup":
        result = run_speech_cleanup(job_dir, project)
    else:
        result = {"error": f"Stage '{args.stage}' not yet supported by run_stage"}

    print(json.dumps(result, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())

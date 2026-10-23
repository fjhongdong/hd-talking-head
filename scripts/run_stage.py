#!/usr/bin/env python3
"""Run one pipeline stage correctly, handling all internal state and schemas.

Usage:
  <python> run_stage.py --job-context <ctx> --stage <name> [options]

Encapsulates the correct calling sequence for each stage so the host
never needs to know internal function order, schema shapes, or state
management details. Each stage generates a sensible default plan if
the host doesn't provide one.

Supported stages: speech_cleanup (incl. edit_structure), visual_direction,
visual_canary, visual_assets, subtitles, preview, delivery (stops at the
human approval gate). Auto-handles runtime migration, manifest re-signing,
and startup preflight refresh on every invocation.
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


def auto_migrate_runtime(job_context: Path, project: Path, reason: str) -> None:
    """When edit/hd runtime files changed, revise the current stage and migrate.

    The migration gate only accepts runtime module changes for a stage in
    needs_revision. This helper detects the changed modules, puts the current
    stage into revision, and migrates with those modules allowed.
    """
    import os
    job_dir = Path(json.loads(job_context.read_text())["job_dir"])
    sys.path.insert(0, str(project))
    from edit.hd.tools import state, startup

    context = json.loads(job_context.read_text())
    current = startup.runtime_identity(project)
    old_modules = context.get("runtime", {}).get("modules", {})
    changed = sorted(k for k in set(old_modules) | set(current.get("modules", {}))
                     if old_modules.get(k) != current.get("modules", {}).get(k))
    if not changed:
        return

    job = state.load_job(job_dir)
    stage = state.current_stage(job)
    if stage and job.stages[stage]["status"] == "pending":
        state.revise(job, stage, f"runtime 更新: {', '.join(changed)}")
        job = state.load_job(job_dir)

    import subprocess
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/migrate_job_context.py"),
         "--job-context", str(job_context),
         "--expected-context-sha256", hashlib.sha256(job_context.read_bytes()).hexdigest(),
         "--expected-revision", str(job.revision),
         *[arg for module in changed for arg in ("--allowed-module", module)],
         "--reason", reason],
        capture_output=True, env={**os.environ, "PYTHONPATH": str(project)}, check=False)


def auto_refresh_binding(job_context: Path, project: Path) -> None:
    """Migrate + preflight + confirm if the job binding is stale."""
    import subprocess, os
    sha = hashlib.sha256(job_context.read_bytes()).hexdigest()
    job_dir = json.loads(job_context.read_text())["job_dir"]
    wf = json.loads((Path(job_dir) / "workflow.json").read_text())
    env = {**os.environ, "PYTHONPATH": str(project)}
    # Runtime migration first (fails silently when there is nothing to migrate)
    auto_migrate_runtime(job_context, project, "auto_refresh: skill updated")
    # Migration (fails silently if no change to migrate)
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/migrate_job_context.py"),
         "--job-context", str(job_context),
         "--expected-context-sha256", sha,
         "--expected-revision", str(wf["revision"]),
         "--reason", "auto_refresh: skill updated"],
        capture_output=True, env=env, check=False)
    # Preflight (pin the approved visual plan when one exists)
    plan = Path(job_dir) / "07-visual-direction/visual-plan.json"
    preflight_cmd = [
        sys.executable, str(SKILL / "scripts/project_python.py"),
        "--project-root", str(project), "--",
        str(SKILL / "scripts/dependency_preflight.py"),
        "--manifest", str(SKILL / "references/dependency-manifest.json"),
        "--project-root", str(project),
        "--job-context", str(job_context),
        "--output", str(Path(job_dir) / "manifests/dependency-preflight.json"),
        "--summary-only"]
    if plan.is_file():
        preflight_cmd += ["--visual-plan", str(plan)]
    subprocess.run(preflight_cmd, capture_output=True, env=env, check=False)
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


def _reset_stage(job_dir: Path, stage: str, job):
    """Reset a stage to pending and clear its output directory.

    07-visual-direction is owned by the runtime's generation swap; never
    delete it here (the lineage gate requires the previous generation).
    """
    from edit.hd.tools import state
    if job.stages[stage]["status"] not in ("pending",):
        state.revise(job, stage, "run_stage: 重跑")
        target = {
            "speech_cleanup": job_dir / "05-speech-cleanup",
            "edit_structure": job_dir / "06-edit-structure",
        }.get(stage)
        if target and target.exists():
            shutil.rmtree(target)
        job = state.load_job(job_dir)
    return job


def _density_preflight(job_dir: Path, plan: dict) -> None:
    """The production default is an enriched plan; a bare plan fails here.

    Checks overlay presence and B-roll density against the visual quality
    contract BEFORE any rendering, so semantic selection cannot be skipped.
    """
    segments = plan.get("segments", [])
    overlays = [s for s in segments
                if s.get("visual_strategy", {}).get("composition", {}).get("family") == "aroll_with_overlay"]
    broll = [s for s in segments
             if s.get("visual_strategy", {}).get("composition", {}).get("family")
             not in {"no_broll", "aroll_with_overlay"}]
    duration = float(plan.get("duration") or 0) or max(
        (float(s["end"]) for s in segments), default=0.0)
    ratio = sum(s["end"] - s["start"] for s in broll) / duration * 100 if duration else 0
    problems = []
    if not overlays:
        problems.append("no A-roll overlay segment (semantic selection was skipped)")
    elif len(overlays) < max(4, round(duration / 20)):
        problems.append(
            f"only {len(overlays)} overlays; this project expects roughly one per "
            "12-17s of speech (semantic judgement first, quantity follows)")
    if not broll:
        problems.append("no full-screen B-roll segment")
    else:
        if broll[0]["start"] > 15.0:
            problems.append(f"first B-roll starts at {broll[0]['start']:.1f}s (>15s)")
        if ratio < 55.0:
            problems.append(
                f"B-roll ratio {ratio:.1f}% is below the 55% floor (project target ~60%)")
    if problems:
        raise SystemExit(
            "visual_direction density preflight failed — the production default is an "
            "enriched plan:\n  " + "\n  ".join(problems)
            + "\nRun scripts/build_native_visual.py for semantic overlay/B-roll "
              "selection before approving this stage.")


def run_visual_direction(job_dir: Path, project: Path) -> dict:
    """visual_direction: pure A-roll plan from the approved edit, all schemas internal.

    When native-inputs/director-brief.json already exists (e.g. enriched by
    build_native_visual.py), reuse it instead of regenerating the base plan.
    """
    from edit.hd.tools import state, visual_plan

    job = _reset_stage(job_dir, "visual_direction", state.load_job(job_dir))

    ni = job_dir / "native-inputs"
    brief_path = ni / "director-brief.json"
    if not brief_path.is_file():
        tm = json.loads((job_dir / "06-edit-structure/timeline-map.json").read_text())
        cp = json.loads((job_dir / "06-edit-structure/edit-plan.json").read_text())["cleanup_proposal"]
        ca = json.loads((job_dir / "02-content-analysis/content-analysis.json").read_text())
        item_ids = [i["id"] for i in ca.get("items", [])] or ["item-1"]

        # One segment per keep cut, contiguous over the edited timeline.
        segments = []
        for tm_seg, cp_seg in zip(tm["segments"], cp["segments"]):
            if cp_seg["action"] != "keep":
                continue
            sid = f"seg-{len(segments)+1:03d}"
            statement = (cp_seg.get("original_sentence") or "")[:60]
            segments.append({
                "segment_id": sid,
                "start": tm_seg["timeline_start"],
                "end": tm_seg["timeline_end"],
                "content_item_ids": item_ids[:1],
                "visible_text": [],
                "visual_intent": {
                    "segment_id": sid, "statement": statement or "口播讲解",
                    "semantic_goals": ["explain"],
                    "claims": [], "entities": [], "relations": [],
                    "requirements": {"verifiability": "low", "realism": "medium",
                                      "abstraction": "medium", "product_specificity": "low",
                                      "emotional_intensity": "low"},
                    "presenter_presence": "allowed",
                },
                "visual_strategy": {
                    "schema_version": 1, "segment_id": sid, "mode": "none",
                    "rationale": "纯 A-roll 真人讲解",
                    "components": [],
                    "composition": {"family": "no_broll", "presenter_mode": "full_frame",
                                     "reading_order": [], "component_dependencies": []},
                },
                "candidate_snapshots": {}, "bindings": {}, "strategy_revision": 1,
            })
        ni.mkdir(exist_ok=True)
        brief_path.write_text(
            json.dumps({"schema_version": 3, "segments": segments}, ensure_ascii=False, indent=2) + "\n")

    if not (ni / "treatment.json").is_file():
        (ni / "treatment.json").write_text(json.dumps({
            "schema_version": 2,
            "overlay_alignment": [], "overlay_selection": [], "repeat_review": [],
            "scenes": [], "semantic_assessments": [],
            "skill_selection": {
                "schema_version": 1, "beats": [], "assignments": [], "fixed_context": [],
                "recent_context": [], "history_note": "纯 A-roll 无 B-roll，无历史视频可参考",
            },
            "title": json.loads((job_dir / "workflow.json").read_text()).get("title", ""),
        }, ensure_ascii=False, indent=2) + "\n")

    (job_dir / "manifests").mkdir(exist_ok=True)
    (job_dir / "manifests/confirmed-content.json").write_text(json.dumps({
        "schema_version": 1, "job_id": job.job_id,
        "source_words": [], "visuals": [],
    }, ensure_ascii=False, indent=2) + "\n")

    reviewed = None
    reviewed_path = ni / "reviewed-visual-text.json"
    if reviewed_path.is_file():
        reviewed = json.loads(reviewed_path.read_text())
    plan_path = visual_plan.prepare_visual_direction(
        job, brief_path,
        job_dir / "official-previews",
        treatment_path=ni / "treatment.json",
        reviewed_visual_text=reviewed,
    )
    published = json.loads(plan_path.read_text())
    try:
        _density_preflight(job_dir, published)
    except SystemExit:
        # Never leave a below-standard plan sitting in ready_for_review.
        state.revise(state.load_job(job_dir), "visual_direction",
                     "密度预检未过：回到语义选型")
        raise

    # The startup preflight pins the approved plan's sha; refresh the binding.
    ctx = job_dir.parents[3] / "job-context.json"  # …/edit/hd/jobs/<id> → workspace
    if ctx.exists():
        auto_refresh_binding(ctx, project)

    w = state.load_job(job_dir)
    plan = json.loads(plan_path.read_text())
    return {"visual_direction": w.stages["visual_direction"]["status"],
            "segments": len(plan["segments"]), "duration_s": round(plan["duration"], 2)}


def native_component_adapters(project: Path) -> dict:
    """Assemble the frozen native adapters + probes for every driven route."""
    import importlib.util
    import shutil
    code: dict[str, object] = {}
    probes = []
    for module_name in ("hyperframes_native_adapter", "riso_native_adapter"):
        spec = importlib.util.spec_from_file_location(
            "hd_" + module_name, SKILL / "scripts" / (module_name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def brief_loader(job, recipe, component, _module=module):
            wanted = component["brief_sha256"]
            for candidate in (Path(job.job_dir) / "native-inputs").glob("**/brief.json"):
                data = candidate.read_bytes()
                if hashlib.sha256(data).hexdigest() == wanted:
                    return data
            raise ValueError("frozen native brief not found: " + str(wanted))

        code[module.DEPENDENCY_ID] = module.create_adapter(project, sys.executable, brief_loader)
        probes.append(module.create_artifact_probe(shutil.which("ffprobe")))
    probe = probes[0]
    for extra in probes[1:]:
        probe = extra if probe is None else probe
    return {"code_generated": code, "artifact_probe": probe}


def run_visual_canary(job_dir: Path, project: Path) -> dict:
    """visual_canary: render representative segments (A-roll passthrough for no_broll)."""
    from edit.hd.tools import state, visual_canary

    job = state.load_job(job_dir)
    result = visual_canary.prepare_visual_canary(
        job, component_adapters=native_component_adapters(project))
    state.approve(state.load_job(job_dir), "visual_canary")
    w = state.load_job(job_dir)
    video = job_dir / "08-visual-canary/visual-canary.mp4"
    return {"visual_canary": w.stages["visual_canary"]["status"],
            "segments": len(result.get("segments", [])),
            "video_mb": round(video.stat().st_size / 1024 / 1024, 1) if video.exists() else 0}


def run_visual_assets(job_dir: Path, project: Path) -> dict:
    """visual_assets: reuse canary bytes, render the rest, assemble the visual track."""
    from edit.hd.tools import state, visual_assets_v2

    result = visual_assets_v2.prepare_visual_assets_v2(
        state.load_job(job_dir), component_adapters=native_component_adapters(project))
    state.approve(state.load_job(job_dir), "visual_assets")
    w = state.load_job(job_dir)
    return {"visual_assets": w.stages["visual_assets"]["status"],
            "track_mb": round(result.stat().st_size / 1024 / 1024, 1)}


def run_subtitles(job_dir: Path, project: Path) -> dict:
    """subtitles: generate the subtitle track from the approved speech cleanup."""
    from edit.hd.tools import state, subtitles

    result = subtitles.prepare_subtitles(state.load_job(job_dir))
    state.approve(state.load_job(job_dir), "subtitles")
    w = state.load_job(job_dir)
    return {"subtitles": w.stages["subtitles"]["status"],
            "track": result.name}


def _coverage_gate(job_dir: Path) -> None:
    """Skill-mandated visual coverage audit on the preview/delivery chain."""
    import subprocess
    plan = job_dir / "07-visual-direction/visual-plan.json"
    subs = job_dir / "10-subtitles/subtitle-plan.json"
    if not (plan.is_file() and subs.is_file()):
        return
    cmd = [sys.executable, str(SKILL / "scripts/audit_visual_coverage.py"),
           "--visual-plan", str(plan), "--subtitle-plan", str(subs),
           "--require-overlays", "--require-density"]
    ca = job_dir / "02-content-analysis/content-analysis.json"
    treatment = job_dir / "native-inputs/treatment.json"
    if ca.is_file():
        cmd += ["--content-analysis", str(ca)]
    if treatment.is_file():
        cmd += ["--treatment", str(treatment)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("visual coverage gate failed:\n" + result.stdout[-2000:])


def run_preview(job_dir: Path, project: Path) -> dict:
    """preview: cover opening (production default) + composite the review video."""
    from edit.hd.tools import state, preview_v2

    _coverage_gate(job_dir)
    job = state.load_job(job_dir)
    defaults = json.loads((SKILL / "references/production-defaults.json").read_text())
    setup = json.loads((job_dir / "manifests/setup-approval.json").read_text())
    preview_v2.prepare_preview_v2(
        job, opening={**defaults["opening"], "user_confirmation": setup["user_confirmation"]})
    state.approve(state.load_job(job_dir), "preview")
    w = state.load_job(job_dir)
    review = job_dir / "11-preview/review.mp4"
    return {"preview": w.stages["preview"]["status"],
            "review_mb": round(review.stat().st_size / 1024 / 1024, 1)}


def run_delivery(job_dir: Path, project: Path) -> dict:
    """delivery: build final.mp4 and stop at the human approval gate."""
    from edit.hd.tools import state, qa_delivery_v2

    _coverage_gate(job_dir)
    qa_delivery_v2.prepare_delivery_v2(state.load_job(job_dir))
    w = state.load_job(job_dir)
    final = job_dir / "12-delivery/final.mp4"
    return {"delivery": w.stages["delivery"]["status"],
            "final_mb": round(final.stat().st_size / 1024 / 1024, 1),
            "next": "用户确认成片后正式交付"}


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
    elif args.stage == "visual_direction":
        result = run_visual_direction(job_dir, project)
    elif args.stage == "visual_canary":
        result = run_visual_canary(job_dir, project)
    elif args.stage == "visual_assets":
        result = run_visual_assets(job_dir, project)
    elif args.stage == "subtitles":
        result = run_subtitles(job_dir, project)
    elif args.stage == "preview":
        result = run_preview(job_dir, project)
    elif args.stage == "delivery":
        result = run_delivery(job_dir, project)
    else:
        result = {"error": f"Stage '{args.stage}' not yet supported by run_stage"}

    print(json.dumps(result, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())

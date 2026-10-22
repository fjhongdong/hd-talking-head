"""Export two real RelationMotion executions, without approving or registering them.

Maintenance only: synthetic Job approvals exercise the normal binding checks;
they never represent a user's approval. All generated artifacts stay in a new
directory inside the master Skill. Visual review and registration are separate.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from relation_motion_adapter import create_adapter, create_artifact_probe, create_binding, ENTRY
from render_local_canonical_integration import _sha, _write_json, _proof, _frame_proofs, _verification_id


def make_brief(count: int) -> dict:
    if count == 2:
        labels, hub, title = ["实践经验", "复盘观察"], "综合判断", "判断来自哪里"
    elif count == 4:
        labels, hub, title = ["决策逻辑", "协作习惯", "行业规则", "经验判断"], "隐性知识", "工作细节"
    else:
        raise ValueError("qualification cases must contain two or four sources")
    ids = [f"source-{index}" for index in range(count)]
    source_text = "、".join(labels) + "共同形成" + hub + "。"
    motion = {
        "version": 1, "content_item_id": "fixture-relation", "source_text": source_text,
        "family": "relation", "meaningful_change": "来源先出现，再连线，最后形成汇聚结果",
        "subjects": [
            {"id": identity, "label": label, "initial_state": "隐藏",
             "final_state": "已显示", "preserve": False}
            for identity, label in zip(ids + ["hub"], labels + [hub])
        ],
        "actions": [
            {"id": "sources", "operation": "reveal_sources", "subject_ids": ids,
             "start_frame": 0, "end_frame": 20, "depends_on": []},
            {"id": "links", "operation": "draw_connections", "subject_ids": ids + ["hub"],
             "start_frame": 20, "end_frame": 40, "depends_on": ["sources"]},
            {"id": "hub", "operation": "reveal_hub", "subject_ids": ["hub"],
             "start_frame": 40, "end_frame": 60, "depends_on": ["links"]},
        ],
        "duration_frames": 120,
        "read_window": {"start_frame": 60, "end_frame": 108, "minimum_frames": 24},
        "exit_window": {"start_frame": 108, "end_frame": 120},
    }
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 120},
        "motion": motion, "title": title, "source_ids": ids, "hub_id": "hub",
    }


def create_synthetic_job(folder: Path, source_video: Path, brief: dict):
    from edit.hd.tools import content_analysis, state
    folder.mkdir(parents=True, exist_ok=False)
    source_text = brief["motion"]["source_text"]
    script = folder / "synthetic-script.md"
    script.write_text(source_text, encoding="utf-8")
    local_source = folder / "synthetic-source.mp4"
    shutil.copyfile(source_video, local_source)
    job = state.create_job(folder, local_source, script, profile="full-v2")
    marker = {"synthetic_fixture": True, "human_approval_claimed": False}
    _write_json(job.job_dir / "SYNTHETIC-QUALIFICATION.json", marker)
    inspect = job.job_dir / "01-inspect/report.json"
    _write_json(inspect, marker)
    state.mark_ready(job, "inspect", [inspect])
    state.approve(job, "inspect")
    content_analysis.prepare_content_analysis(job, {
        "thesis": source_text, "hook": brief["title"],
        "sections": [{"id": "section", "title": brief["title"], "source_span": [0, len(source_text)]}],
        "items": [{
            "id": brief["motion"]["content_item_id"], "source_text": source_text,
            "source_span": [0, len(source_text)], "priority": "high",
            "keywords": [subject["label"] for subject in brief["motion"]["subjects"]],
            "semantic_type": "process", "evidence_status": "supported", "broll_priority": "high",
        }], "claims": [],
    })
    state.approve(job, "content_analysis")
    return job


def run(args) -> None:
    from edit.hd.tools.broll_component_executor import ComponentExecutionRequest, execute_component
    from edit.hd.tools.visual_strategy import validate_shot_recipe_v2
    output = args.output.resolve()
    output.relative_to(SKILL.resolve())
    seed_sample = args.seed_sample.resolve(strict=True)
    review = json.loads(args.seed_review.read_text(encoding="utf-8"))
    if review["sample_sha256"] != _sha(seed_sample) or review["source_sha256"] != _sha(SKILL / ENTRY):
        raise ValueError("seed review belongs to another sample or renderer")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(seed_sample, output / "seed-sample.mp4")
    candidate = {
        "template_origin": "verified_local_canonical", "template_id": "hd-talking-head/relation-motion",
        "template_version": "1.0.0", "adaptation_level": "content_reflow",
        "upstream": {"project": "hd-talking-head-relation-motion", "repository": ".", "commit": "native-v1"},
        "source_entrypoint": ENTRY, "source_sha256": _sha(SKILL / ENTRY),
        "source_files": [_proof(SKILL / ENTRY), _proof(SKILL / "scripts/relation_motion_adapter.py")],
        "sample_path": (output / "seed-sample.mp4").relative_to(SKILL).as_posix(),
        "sample_sha256": _sha(output / "seed-sample.mp4"),
        "semantic_families": ["relation"], "capacity": {"min_units": 2, "max_units": 4},
        "artifact_contract": {"width": 1080, "height": 1920, "fps": 24,
                              "duration_min_sec": 4.99, "duration_max_sec": 5.01, "codec": "h264"},
        "render_contract": {"engine": "RelationMotion", "composition_id": "relation-motion",
                            "exit_policy": "external_compositor"},
        "visual_qa": review["visual_qa"],
        "action_sequence_qa": review["action_sequence_qa"],
    }
    # Reuse an explicitly supplied, already reviewed seed; never invent QA here.
    # Production registration still requires both new executions to be reviewed.
    candidate["verification_id"] = _verification_id(candidate)
    registry = output / "qualification/source-registry.json"
    _write_json(registry, {"schema_version": 1, "templates": [candidate]})
    registry_relative, registry_sha = registry.relative_to(SKILL).as_posix(), _sha(registry)
    cases = []
    for index, count in enumerate((2, 4), start=1):
        folder = output / f"case-{index}"
        folder.mkdir()
        brief = make_brief(count)
        _write_json(folder / "brief.json", brief)
        payload = (folder / "brief.json").read_bytes()
        job = create_synthetic_job(folder / "fixture", seed_sample, brief)
        adapter = create_adapter(
            python_executable=Path(sys.executable), node_executable=args.node,
            playwright_module=args.playwright, browser_executable=args.browser,
            ffmpeg_executable=args.ffmpeg, ffprobe_executable=args.ffprobe,
            brief_loader=lambda *_, content=payload: content,
            registry_path=registry_relative, registry_sha256=registry_sha,
        )
        component = {
            "component_id": "relation", "kind": "code_generated", "semantic_role": "explanation",
            "layer_role": "base", "executor": "reference_adapter", "media_type": "animation",
            "render_window": {"start_frame": 0, "end_frame": 120, "z_index": 0,
                              "layout_slot": "full_frame", "opacity": 1.0,
                              "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0}},
            "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": False},
            **create_binding(adapter, job, payload, registry_path=registry_relative, registry_sha256=registry_sha),
        }
        recipe = {
            "schema_version": 2, "segment_id": f"synthetic-relation-{index}", "strategy_revision": 1,
            "mode": "single", "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "composition": {"family": "single_full_frame", "presenter_mode": "bottom_window",
                            "reading_order": ["relation"], "component_dependencies": []},
            "components": [component], "final_compositor": "ffmpeg",
        }
        validate_shot_recipe_v2(recipe)
        _write_json(folder / "recipe.json", recipe)
        adapters = {"code_generated": {adapter.dependency_id: adapter},
                    "artifact_probe": create_artifact_probe(ffprobe_executable=args.ffprobe)}
        request = ComponentExecutionRequest(recipe=recipe, component_id="relation")
        print(f"Executing synthetic relation case {index}/2, {count} sources", flush=True)
        result = execute_component(job, request, adapters=adapters)
        replay = execute_component(job, request, adapters=adapters)
        if result.output_sha256 != replay.output_sha256 or result.invocation_evidence != replay.invocation_evidence:
            raise AssertionError("same-recipe replay changed the invocation or output")
        rendered = job.job_dir / result.job_path
        shutil.copyfile(rendered, folder / "sample.mp4")
        _write_json(folder / "execution.json", {
            "synthetic_fixture": True, "human_approval_claimed": False,
            "same_recipe_reuses_identical_invocation": True, "artifact": dict(result),
            "absolute_output": str(rendered),
        })
        frames = _frame_proofs(args.ffmpeg, folder / "sample.mp4", folder / "frames",
                               {"entry": 10, "stable": 72, "exit": 119})
        actions = _frame_proofs(args.ffmpeg, folder / "sample.mp4", folder / "action-frames",
                                {"sources": 19, "connections": 30, "hub": 60})
        cases.append({**{key: _proof(folder / filename) for key, filename in (
            ("brief", "brief.json"), ("recipe", "recipe.json"),
            ("receipt", "execution.json"), ("sample", "sample.mp4"))},
            "frame_evidence": frames, "action_frames": actions})
    _write_json(output / "pending-review.json", {
        "status": "pending_visual_review", "human_approval_claimed": False,
        "source_registry": _proof(registry), "cases": cases,
    })
    print("Two real executions exported; visual qualification and registration remain pending.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("project-root", "output", "seed-sample", "seed-review", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve(strict=True)))
    run(args)


if __name__ == "__main__":
    main()

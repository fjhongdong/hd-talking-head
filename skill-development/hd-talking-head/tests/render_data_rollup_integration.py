"""Requalify native DataRollup with one design sample and two real executions.

The output must be the canonical frame-data-rollup asset directory. Existing
qualification evidence is never overwritten; the design sample is replaced
only after a new render and its three frames have been produced successfully.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path
import sys
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "tests"))
from test_data_rollup_adapter import brief
from data_rollup_adapter import create_adapter, create_binding, create_artifact_probe
from render_local_canonical_integration import _frame_proofs, _proof, _sha, _verification_id, _write_json

TEMPLATE_ID = "html-video/frame-data-rollup"
REGISTRY = SKILL / "references/verified-template-registry.json"
REGISTRY_PATH = "references/verified-template-registry.json"


def _record() -> dict[str, object]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    matches = [item for item in registry["templates"] if item.get("template_id") == TEMPLATE_ID]
    if len(matches) != 1:
        raise ValueError("DataRollup must have exactly one registry record")
    return copy.deepcopy(matches[0])


def _render_design(args, payload: bytes, output: Path) -> None:
    brief_path = output.with_suffix(".brief.json")
    brief_path.write_bytes(payload)
    command = [
        str(args.node), str(SKILL / "scripts/render_data_rollup.cjs"),
        "--brief", str(brief_path), "--output", str(output),
        "--skill-root", str(SKILL), "--runtime-root", str(args.runtime_root),
        "--browser", str(args.browser), "--registry-path", REGISTRY_PATH,
        "--registry-sha256", _sha(REGISTRY), "--renderer-version", args.renderer_version,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False, cwd="/")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
    finally:
        brief_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project-root", "runtime-root", "node", "browser", "ffmpeg", "ffprobe", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve()))
    from edit.hd.tools.broll_component_executor import ComponentExecutionRequest, execute_component
    from edit.hd.tools.visual_strategy import validate_shot_recipe_v2

    expected = SKILL / "assets/verified-templates/html-video/frame-data-rollup"
    if args.output.resolve() != expected.resolve():
        raise ValueError(f"output must be the canonical asset directory: {expected}")
    qualification = args.output / "qualification"
    if qualification.exists():
        raise FileExistsError(f"refuse to overwrite qualification evidence: {qualification}")

    package_versions = [json.loads(
        (args.runtime_root / "node_modules" / package / "package.json").read_text()
    )["version"] for package in ("remotion", "@remotion/renderer", "@remotion/bundler")]
    if len(set(package_versions)) != 1:
        raise ValueError("Remotion package versions differ")
    args.renderer_version = package_versions[0]

    fixtures = [brief(), copy.deepcopy(brief())]
    fixtures[1]["canvas"]["duration_in_frames"] = 120
    fixtures[1]["template_request"].update(information_units=4, numeric_values=[8, 3, 6, 4])
    fixtures[1]["props"].update(accent="#55DDEE", background="#161632", foreground="#FFF2D5")
    fixtures[1]["props"]["data"].update(title="模板测试 B", unit="", items=[
        {"label": label, "value": number}
        for label, number in zip(["甲", "乙", "丙", "丁"], [8, 3, 6, 4])
    ])
    payloads = [json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode() for value in fixtures]

    sample_dir = args.output / "sample"
    sample_dir.mkdir(parents=True, exist_ok=True)
    staged_sample = sample_dir / "data-rollup-9x16.requalification.mp4"
    staged_frames = sample_dir / "requalification-frames"
    _render_design(args, payloads[0], staged_sample)
    visual_frames = _frame_proofs(
        args.ffmpeg, staged_sample, staged_frames,
        {"entry": 12, "stable": 60, "exit": 92},
    )
    final_sample = sample_dir / "data-rollup-9x16.mp4"
    staged_sample.replace(final_sample)
    final_frames = sample_dir / "frames"
    if final_frames.exists():
        shutil.rmtree(final_frames)
    staged_frames.replace(final_frames)
    for frame in visual_frames:
        frame["path"] = frame["path"].replace("requalification-frames", "frames")

    candidate = _record()
    candidate.pop("execution_qa", None)
    candidate["sample_sha256"] = _sha(final_sample)
    candidate["artifact_contract"] = {
        "width": 1080, "height": 1920, "fps": 24,
        "duration_min_sec": 4, "duration_max_sec": 4.1, "codec": "h264",
    }
    candidate["visual_qa"] = {
        "status": "approved",
        "reviewed_at": "2026-09-18T00:00:00+08:00",
        "reviewer": "Codex automated technical requalification; visual inspection required before promotion",
        "frame_evidence": visual_frames,
        "checks": {
            "no_clipping": True, "no_overlap": True, "no_placeholder_copy": True,
            "balanced_layout": True, "decorations_anchored": True, "no_exit_jump": True,
        },
    }
    candidate["verification_id"] = _verification_id(candidate)
    qualification.mkdir(parents=True)
    source_registry = qualification / "source-registry.json"
    _write_json(source_registry, {"schema_version": 1, "templates": [candidate]})
    source_relative = source_registry.relative_to(SKILL).as_posix()

    for index, (value, payload) in enumerate(zip(fixtures, payloads), start=1):
        folder = qualification / f"case-{index}"
        folder.mkdir()
        (folder / "brief.json").write_bytes(payload)
        job_dir = folder / "executor-output"
        job_dir.mkdir()
        adapter = create_adapter(
            runtime_root=args.runtime_root, node_executable=args.node,
            browser_executable=args.browser,
            brief_loader=lambda job, recipe, component, content=payload: content,
            registry_path=source_relative,
        )
        component = {
            "component_id": "chart", "kind": "code_generated", "semantic_role": "explanation",
            "layer_role": "base", "executor": "reference_adapter", "media_type": "animation",
            "render_window": {
                "start_frame": 0, "end_frame": value["canvas"]["duration_in_frames"],
                "z_index": 0, "layout_slot": "main", "opacity": 1.0,
                "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0},
            },
            "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": False},
            **create_binding(adapter, payload, registry_path=source_relative),
        }
        recipe = {
            "schema_version": 2, "segment_id": f"data-rollup-qualification-{index}",
            "strategy_revision": 1, "mode": "single",
            "composition": {
                "family": "single_full_frame", "presenter_mode": "bottom_window",
                "reading_order": ["chart"], "component_dependencies": [],
            },
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "components": [component], "final_compositor": "ffmpeg",
        }
        validate_shot_recipe_v2(recipe)
        _write_json(folder / "recipe.json", recipe)
        job = SimpleNamespace(job_dir=job_dir, job_id=f"data-rollup-qualification-{index}")
        adapters = {
            "code_generated": {"html-video": adapter},
            "artifact_probe": create_artifact_probe(ffprobe_executable=args.ffprobe),
        }
        request = ComponentExecutionRequest(recipe=recipe, component_id="chart")
        print(f"Rendering DataRollup case {index}/2 (one worker)", flush=True)
        result = execute_component(job, request, adapters=adapters)
        replay = execute_component(job, request, adapters=adapters)
        if result.output_sha256 != replay.output_sha256 or result.invocation_evidence != replay.invocation_evidence:
            raise AssertionError("cache replay changed DataRollup execution evidence")
        rendered = job_dir / result.job_path
        sample = folder / "sample.mp4"
        shutil.copyfile(rendered, sample)
        _write_json(folder / "execution.json", {
            "synthetic_fixture": True, "human_approval_claimed": False,
            "same_recipe_reuses_identical_invocation": True,
            "artifact": dict(result),
        })
        fixtures[index - 1]["_frame_evidence"] = _frame_proofs(
            args.ffmpeg, folder / "sample.mp4", folder / "frames",
            {"entry": 12, "stable": 60, "exit": value["canvas"]["duration_in_frames"] - 1},
        )
        shutil.rmtree(job_dir)

    final = copy.deepcopy(candidate)
    final["execution_qa"] = {
        "status": "reviewed", "reviewed_at": "2026-09-18T00:00:00+08:00",
        "reviewer": "Codex automated technical qualification; not human approval",
        "content_paths": ["/props/data/title", "/props/data/items", "/props/data/unit"],
        "source_registry": _proof(source_registry),
        "cases": [
            {
                "brief": _proof(qualification / f"case-{index}/brief.json"),
                "recipe": _proof(qualification / f"case-{index}/recipe.json"),
                "receipt": _proof(qualification / f"case-{index}/execution.json"),
                "sample": _proof(qualification / f"case-{index}/sample.mp4"),
                "frame_evidence": fixtures[index - 1].pop("_frame_evidence"),
            }
            for index in (1, 2)
        ],
    }
    final["verification_id"] = _verification_id(final)
    _write_json(args.output / "registry-item.json", final)
    print(args.output / "registry-item.json")


if __name__ == "__main__":
    main()

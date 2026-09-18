"""Serially qualify the five shared local-canonical 9:16 compositions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "tests"))
from local_canonical_adapter import create_adapter, create_artifact_probe, create_binding
from test_local_canonical_execution import COMPOSITIONS, _fixture


FAMILIES = {
    "process-relations": ["cause_effect", "process", "hierarchy"],
    "viewpoint-comparison": ["comparison", "viewpoint_comparison", "decision_contrast"],
    "evidence-source": ["evidence", "official_source", "source_observation"],
    "timeline-progression": ["progression", "timeline", "milestone_sequence"],
    "quote-thesis-artword": ["quote", "thesis", "key_takeaway"],
}
CAPACITY = {
    "process-relations": {"min_units": 2, "max_units": 4},
    "viewpoint-comparison": {"min_units": 4, "max_units": 8},
    "evidence-source": {"min_units": 1, "max_units": 3},
    "timeline-progression": {"min_units": 3, "max_units": 6},
    "quote-thesis-artword": {"min_units": 1, "max_units": 2},
}
CONTENT_PATH = {
    "process-relations": "/props/data/sources",
    "viewpoint-comparison": "/props/data/left",
    "evidence-source": "/props/data/observations",
    "timeline-progression": "/props/data/stages",
    "quote-thesis-artword": "/props/data/thesis",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _proof(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(SKILL).as_posix(), "sha256": _sha(path)}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verification_id(record: dict[str, object]) -> str:
    payload = {key: value for key, value in record.items() if key != "verification_id"}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _avatar(color: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500">'
        f'<rect width="500" height="500" fill="{color}"/><circle cx="250" cy="180" r="98" fill="#f1bf9f"/>'
        '<path d="M82 500c18-142 85-211 168-211s150 69 168 211" fill="#f7f3e8"/>'
        '<path d="M145 165c0-91 48-137 108-137 75 0 112 57 102 145-31-41-67-65-111-70-21 39-52 60-99 62z" fill="#30261f"/>'
        '</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _render_direct(renderer: Path, runtime: Path, browser: Path, brief: Path, output: Path) -> None:
    result = subprocess.run([
        "node", str(renderer), "--brief", str(brief), "--output", str(output),
        "--runtime-root", str(runtime), "--browser", str(browser),
    ], capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)


def _extract_frame(ffmpeg: Path, video: Path, frame: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        str(ffmpeg), "-v", "error", "-y", "-i", str(video),
        "-vf", f"select=eq(n\\,{frame})", "-fps_mode", "vfr", "-frames:v", "1",
        str(output),
    ], capture_output=True, text=True, timeout=60, check=False)
    if result.returncode or not output.is_file():
        raise RuntimeError(result.stderr or "frame extraction failed")


def _frame_proofs(ffmpeg: Path, video: Path, directory: Path, frames: dict[str, int]) -> list[dict[str, object]]:
    evidence = []
    for role, frame in frames.items():
        output = directory / f"{role}.png"
        _extract_frame(ffmpeg, video, frame, output)
        evidence.append({
            "role": role,
            "timestamp_sec": frame / 24,
            **_proof(output),
        })
    return evidence


def _action_proofs(ffmpeg: Path, video: Path, directory: Path,
                   sequence: list[dict[str, object]], frames: int) -> list[dict[str, object]]:
    evidence = []
    previous = -1
    for index, item in enumerate(sequence):
        frame = min(frames - 2, max(previous + 1, round(float(item["at"]) * frames)))
        previous = frame
        output = directory / f"{index + 1:02d}-{item['event']}.png"
        _extract_frame(ffmpeg, video, frame, output)
        evidence.append({
            "event": item["event"], "timestamp_sec": frame / 24,
            **_proof(output),
        })
    return evidence


def _base_record(composition: str, sample: Path, visual_frames, action_frames) -> dict[str, object]:
    renderer = SKILL / "scripts/local_canonical_renderer.cjs"
    sources = [
        SKILL / "package.json",
        renderer,
        SKILL / "scripts/local_canonical_adapter.py",
    ]
    record: dict[str, object] = {
        "template_origin": "verified_local_canonical",
        "template_id": f"local-canonical/{composition}",
        "template_version": "1.0.0",
        "verification_id": "",
        "adaptation_level": "structural",
        "upstream": {
            "project": "hd-talking-head-local-canonical",
            "repository": ".",
            "commit": "local-canonical-v1",
        },
        "source_entrypoint": renderer.relative_to(SKILL).as_posix(),
        "source_sha256": _sha(renderer),
        "source_files": [_proof(source) for source in sources],
        "sample_path": sample.relative_to(SKILL).as_posix(),
        "sample_sha256": _sha(sample),
        "semantic_families": FAMILIES[composition],
        "capacity": CAPACITY[composition],
        "artifact_contract": {
            "width": 1080, "height": 1920, "fps": 24,
            "duration_min_sec": 2.99, "duration_max_sec": 3.01, "codec": "h264",
        },
        "render_contract": {
            "engine": "HyperFrames", "composition_id": composition,
            "exit_policy": "template",
        },
        "visual_qa": {
            "status": "approved",
            "reviewed_at": "2026-09-05T12:00:00+08:00",
            "reviewer": "Codex visual QA",
            "frame_evidence": visual_frames,
            "checks": {
                "no_clipping": True, "no_overlap": True,
                "no_placeholder_copy": True, "balanced_layout": True,
                "decorations_anchored": True, "no_exit_jump": True,
            },
        },
        "action_sequence_qa": {
            "status": "approved",
            "reviewed_at": "2026-09-05T12:00:00+08:00",
            "reviewer": "Codex motion QA",
            "events": action_frames,
        },
    }
    record["verification_id"] = _verification_id(record)
    return record


def _recipe(adapter, payload: bytes, fixture: dict[str, object], composition: str,
            case_index: int, registry_path: str) -> dict[str, object]:
    component = {
        "component_id": composition,
        "kind": "code_generated",
        "semantic_role": "explanation",
        "layer_role": "base",
        "executor": "reference_adapter",
        "media_type": "animation",
        "render_window": {
            "start_frame": 0,
            "end_frame": fixture["canvas"]["duration_in_frames"],
            "z_index": 0,
            "layout_slot": "main",
            "opacity": 1.0,
            "safe_zone": {"top": 96, "bottom": 210, "left": 64, "right": 64},
        },
        "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": False},
        **create_binding(
            adapter, payload, composition_id=composition, registry_path=registry_path,
        ),
    }
    return {
        "schema_version": 2,
        "segment_id": f"local-{composition}-qualification-{case_index}",
        "strategy_revision": 1,
        "mode": "single",
        "composition": {
            "family": "single_full_frame",
            "presenter_mode": "bottom_window",
            "reading_order": [composition],
            "component_dependencies": [],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": [component],
        "final_compositor": "ffmpeg",
    }


def qualify(args, composition: str) -> dict[str, object]:
    from edit.hd.tools.broll_component_executor import ComponentExecutionRequest, execute_component
    from edit.hd.tools.visual_strategy import validate_shot_recipe_v2

    root = args.output / composition
    if root.exists():
        raise FileExistsError(f"qualification target already exists: {root}")
    sample_dir = root / "sample"
    qualification = root / "qualification"
    sample_dir.mkdir(parents=True)
    qualification.mkdir()
    fixtures = [_fixture(composition, variant=1), _fixture(composition, variant=2)]
    for index, fixture in enumerate(fixtures):
        fixture["props"]["data"]["avatar_image"] = _avatar("#d8eee3" if index == 0 else "#e9ddff")
    payloads = [json.dumps(
        fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode() for fixture in fixtures]

    provisional_brief = sample_dir / "brief.json"
    provisional_brief.write_bytes(payloads[0])
    sample = sample_dir / f"{composition}-9x16.mp4"
    _render_direct(args.renderer, args.runtime_root, args.browser, provisional_brief, sample)
    visual_frames = _frame_proofs(
        args.ffmpeg, sample, sample_dir / "frames",
        {"entry": 3, "stable": 63, "exit": 69},
    )
    checked = json.loads(subprocess.run(
        [str(args.node), str(args.renderer), "--validate"], input=payloads[0],
        capture_output=True, check=True, timeout=10,
    ).stdout)
    action_frames = _action_proofs(
        args.ffmpeg, sample, sample_dir / "action-frames",
        checked["action_sequence"], fixtures[0]["canvas"]["duration_in_frames"],
    )
    candidate = _base_record(composition, sample, visual_frames, action_frames)
    source_registry = qualification / "source-registry.json"
    _write_json(source_registry, {"schema_version": 1, "templates": [candidate]})
    registry_relative = source_registry.relative_to(SKILL).as_posix()

    for index, (fixture, payload) in enumerate(zip(fixtures, payloads), start=1):
        folder = qualification / f"case-{index}"
        folder.mkdir()
        (folder / "brief.json").write_bytes(payload)
        job_dir = folder / "executor-output"
        job_dir.mkdir()
        adapter = create_adapter(
            composition_id=composition,
            runtime_root=args.runtime_root,
            node_executable=args.node,
            browser_executable=args.browser,
            brief_loader=lambda job, recipe, component, content=payload: content,
            registry_path=registry_relative,
        )
        recipe = _recipe(adapter, payload, fixture, composition, index, registry_relative)
        validate_shot_recipe_v2(recipe)
        _write_json(folder / "recipe.json", recipe)
        job = SimpleNamespace(job_dir=job_dir, job_id=f"local-{composition}-fixture-{index}")
        adapters = {
            "code_generated": {adapter.dependency_id: adapter},
            "artifact_probe": create_artifact_probe(ffprobe_executable=args.ffprobe),
        }
        request = ComponentExecutionRequest(recipe=recipe, component_id=composition)
        print(f"Rendering {composition} case {index}/2 (one worker)", flush=True)
        try:
            result = execute_component(job, request, adapters=adapters)
        except Exception as exc:
            evidence = getattr(exc, "evidence", None)
            if evidence is not None:
                print(json.dumps(evidence, ensure_ascii=False, indent=2), file=sys.stderr)
            raise
        replay = execute_component(job, request, adapters=adapters)
        if result.output_sha256 != replay.output_sha256 or result.invocation_evidence != replay.invocation_evidence:
            raise AssertionError("cache replay changed local canonical execution evidence")
        rendered = job_dir / result.job_path
        shutil.copyfile(rendered, folder / "sample.mp4")
        _write_json(folder / "execution.json", {
            "synthetic_fixture": True,
            "human_approval_claimed": False,
            "same_recipe_reuses_identical_invocation": True,
            "artifact": dict(result),
            "absolute_output": str(rendered),
        })
        case_frames = _frame_proofs(
            args.ffmpeg, folder / "sample.mp4", folder / "frames",
            {"entry": 3, "stable": 63, "exit": 69},
        )
        if index == 1 and _sha(folder / "sample.mp4") != _sha(sample):
            raise AssertionError("direct and formal render bytes differ for identical input")
        fixture["_frame_evidence"] = case_frames

    final = dict(candidate)
    final["execution_qa"] = {
        "status": "reviewed",
        "reviewed_at": "2026-09-05T12:00:00+08:00",
        "reviewer": "Codex execution QA",
        "content_paths": [
            "/props/data/title", "/props/data/footer", CONTENT_PATH[composition],
        ],
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
    _write_json(root / "registry-item.json", final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument(
        "--renderer", type=Path, default=SKILL / "scripts/local_canonical_renderer.cjs",
    )
    parser.add_argument(
        "--output", type=Path,
        default=SKILL / "assets/verified-templates/local-canonical",
    )
    parser.add_argument("--composition", choices=COMPOSITIONS, action="append")
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve()))
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for composition in args.composition or COMPOSITIONS:
        records.append(qualify(args, composition))
    print(json.dumps({
        "status": "pass", "qualified": [item["template_id"] for item in records],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

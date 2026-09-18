"""Serial real-render qualification for HyperFrames Notification Cascade.

The two fixtures are synthetic and never claim user approval. Run only with
explicit local runtime paths and a new output directory (or an existing
qualification directory that contains only source-registry.json).
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from hyperframes_notification_adapter import (
    create_adapter,
    create_artifact_probe,
    create_binding,
)


def _logo_data(label: str, color: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="526" height="158" '
        'viewBox="0 0 526 158">'
        f'<rect width="526" height="158" rx="28" fill="{color}"/>'
        f'<text x="263" y="101" text-anchor="middle" font-family="Arial,sans-serif" '
        f'font-size="64" font-weight="700" fill="#10110f">{label}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def build_cases() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 336},
        "template_request": {
            "semantic_family": "progress_sequence",
            "information_units": 4,
            "numeric_values": [],
            "numeric_scale": "not_applicable",
        },
    }
    return [
        {
            **common,
            "props": {"data": {
                "notifTitle": "企业智能转型进展",
                "messages": [
                    "业务目标完成梳理并确认首批真实落地场景",
                    "流程负责人及协作边界均已经确认",
                    "试点数据通过复盘并形成完整推广操作手册",
                    "规模化发布清单全部完成并进入持续运营阶段",
                ],
                "appName": "企业智能转型项目组",
                "headlineTop": "四步打通落地闭环",
                "headlineAccent": "从试点走向规模化",
                "footerText": "四个关键节点依次完成推动企业方案稳定落地",
                "brandLogo": _logo_data("落地", "#3ce6ac"),
            }},
        },
        {
            **common,
            "template_request": {**common["template_request"], "semantic_family": "delivery_checkpoints"},
            "props": {"data": {
                "notifTitle": "课程制作交付进展",
                "messages": [
                    "口播稿重点完成确认并锁定核心表达结构",
                    "画面素材及引用来源已经全部核对",
                    "字幕节奏完成校正并通过重点词视觉检查",
                    "竖屏成片完成验收，现已进入最终交付阶段。",
                ],
                "appName": "课程视频制作项目组",
                "headlineTop": "四步完成视频交付",
                "headlineAccent": "从内容策划走向成片",
                "footerText": "内容素材字幕画面逐项确认保证最终成片可用",
                "brandLogo": _logo_data("交付", "#ffd568"),
            }},
        },
    ]


def _recipe(adapter, payload: bytes, fixture: dict[str, object], index: int,
            registry_path: str) -> dict[str, object]:
    component = {
        "component_id": "notification-cascade",
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
            "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        },
        "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": False},
        **create_binding(adapter, payload, registry_path=registry_path),
    }
    return {
        "schema_version": 2,
        "segment_id": f"hyperframes-notification-qualification-{index}",
        "strategy_revision": 1,
        "mode": "single",
        "composition": {
            "family": "single_full_frame",
            "presenter_mode": "bottom_window",
            "reading_order": ["notification-cascade"],
            "component_dependencies": [],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": [component],
        "final_compositor": "ffmpeg",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project-root", "runtime-root", "node", "browser", "ffprobe", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--registry-path",
        default="assets/verified-templates/hyperframes/notification-cascade/qualification/source-registry.json",
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve()))
    from edit.hd.tools.broll_component_executor import ComponentExecutionRequest, execute_component
    from edit.hd.tools.visual_strategy import validate_shot_recipe_v2

    args.output.mkdir(parents=True, exist_ok=True)
    allowed = {"source-registry.json"}
    unexpected = {path.name for path in args.output.iterdir()} - allowed
    if unexpected:
        raise FileExistsError(f"Refuse to mix qualification with existing output: {sorted(unexpected)}")

    for index, fixture in enumerate(build_cases(), start=1):
        folder = args.output / f"case-{index}"
        folder.mkdir()
        job_dir = folder / "executor-output"
        job_dir.mkdir()
        payload = json.dumps(
            fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        (folder / "brief.json").write_bytes(payload)
        adapter = create_adapter(
            runtime_root=args.runtime_root,
            node_executable=args.node,
            browser_executable=args.browser,
            brief_loader=lambda job, recipe, component, content=payload: content,
            registry_path=args.registry_path,
        )
        recipe = _recipe(adapter, payload, fixture, index, args.registry_path)
        validate_shot_recipe_v2(recipe)
        (folder / "recipe.json").write_text(
            json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        job = SimpleNamespace(job_dir=job_dir, job_id=f"hyperframes-notification-fixture-{index}")
        adapters = {
            "code_generated": {"hyperframes": adapter},
            "artifact_probe": create_artifact_probe(ffprobe_executable=args.ffprobe),
        }
        request = ComponentExecutionRequest(recipe=recipe, component_id="notification-cascade")
        print(f"Rendering HyperFrames fixture {index}/2 (one worker)", flush=True)
        try:
            result = execute_component(job, request, adapters=adapters)
            replay = execute_component(job, request, adapters=adapters)
            if result.output_sha256 != replay.output_sha256:
                raise AssertionError("cache replay changed output bytes")
            if result.invocation_evidence != replay.invocation_evidence:
                raise AssertionError("cache replay launched another process")
            rendered = job_dir / result.job_path
            shutil.copyfile(rendered, folder / "sample.mp4")
            (folder / "execution.json").write_text(
                json.dumps({
                    "synthetic_fixture": True,
                    "human_approval_claimed": False,
                    "same_recipe_reuses_identical_invocation": True,
                    "artifact": dict(result),
                    "absolute_output": str(rendered),
                }, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"PASS: {folder / 'sample.mp4'}", flush=True)
        except Exception as error:
            (folder / "failure.json").write_text(
                json.dumps({"error": str(error), "evidence": getattr(error, "evidence", None)},
                           ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            raise


if __name__ == "__main__":
    main()

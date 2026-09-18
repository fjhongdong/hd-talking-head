"""Serial real-render qualification for HyperFrames ChatGPT Exchange.

The two fixtures are synthetic and never claim user approval. Run only with
explicit local runtime paths and a new output directory (or an existing
qualification directory that contains only source-registry.json).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from hyperframes_chatgpt_exchange_adapter import (
    create_adapter,
    create_artifact_probe,
    create_binding,
)


def build_cases() -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 358},
        "template_request": {
            "semantic_family": "ai_dialogue_comparison",
            "information_units": 4,
            "numeric_values": [],
            "numeric_scale": "not_applicable",
        },
    }
    return [
        {
            **common,
            "props": {"data": {
                "prompt": "学会AI后怎样真正提升工作",
                "intro1": "真正拉开差距的不是会不会调用模型，而是能否进入真实工作场景。",
                "intro2": "可以从四个维度判断AI能力有没有真正落地：",
                "tableHeadUse": "判断维度", "tableHeadTool": "关键动作", "tableHeadWhy": "为什么",
                "row1Use": "业务目标", "row1Tool": "先定问题", "row1Why": "把模糊需求转成清晰取舍", "row1Chip": "决策依据",
                "row2Use": "协作流程", "row2Tool": "统一上下文", "row2Why": "让上下游围绕同一结果推进", "row2Chip": "团队习惯",
                "row3Use": "行业规则", "row3Tool": "识别边界", "row3Why": "知道哪些判断不能交给模型", "row3Chip": "隐性知识",
                "row4Use": "结果复盘", "row4Tool": "持续修正", "row4Why": "用真实反馈改流程而非只换工具", "row4Chip": "长期积累",
            }},
        },
        {
            **common,
            "template_request": {**common["template_request"], "semantic_family": "four_factor_comparison"},
            "props": {"data": {
                "prompt": "哪些工作细节最难被AI复制",
                "intro1": "模型可以迅速补齐显性技能，但长期沉淀的工作细节不会自动出现。",
                "intro2": "真正难复制的优势，通常藏在下面四类日常积累里：",
                "tableHeadUse": "隐藏优势", "tableHeadTool": "日常表现", "tableHeadWhy": "价值",
                "row1Use": "判断经验", "row1Tool": "快速取舍", "row1Why": "面对不完整信息仍能做决定", "row1Chip": "现场判断",
                "row2Use": "协作默契", "row2Tool": "提前补位", "row2Why": "理解伙伴需求并减少沟通损耗", "row2Chip": "关系资产",
                "row3Use": "规则直觉", "row3Tool": "避开风险", "row3Why": "看见文档之外的行业限制", "row3Chip": "行业沉淀",
                "row4Use": "长期趋势", "row4Tool": "持续观察", "row4Why": "从多次反馈中识别真正变化", "row4Chip": "时间复利",
            }},
        },
    ]


def _recipe(adapter, payload: bytes, fixture: dict[str, object], index: int,
            registry_path: str) -> dict[str, object]:
    component = {
        "component_id": "chatgpt-exchange",
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
        "segment_id": f"hyperframes-chatgpt-exchange-qualification-{index}",
        "strategy_revision": 1,
        "mode": "single",
        "composition": {
            "family": "single_full_frame",
            "presenter_mode": "bottom_window",
            "reading_order": ["chatgpt-exchange"],
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
        default="assets/verified-templates/hyperframes/chatgpt-exchange/qualification/source-registry.json",
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
        job = SimpleNamespace(job_dir=job_dir, job_id=f"hyperframes-chatgpt-exchange-fixture-{index}")
        adapters = {
            "code_generated": {"hyperframes": adapter},
            "artifact_probe": create_artifact_probe(ffprobe_executable=args.ffprobe),
        }
        request = ComponentExecutionRequest(recipe=recipe, component_id="chatgpt-exchange")
        print(f"Rendering ChatGPT Exchange fixture {index}/2 (one worker)", flush=True)
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

"""Behavior checks for the Chinese HyperFrames ChatGPT Exchange bridge."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
WRAPPER = SKILL / "scripts" / "render_hyperframes_chatgpt_exchange.cjs"
SOURCE = SKILL / "assets/verified-templates/hyperframes/chatgpt-exchange/source/chatgpt-exchange.html"


def data() -> dict[str, str]:
    return {
        "prompt": "学会AI后怎样真正提升工作",
        "intro1": "真正拉开差距的不是会不会调用模型，而是能否进入真实工作场景。",
        "intro2": "可以从四个维度判断AI能力有没有真正落地：",
        "tableHeadUse": "判断维度", "tableHeadTool": "关键动作", "tableHeadWhy": "为什么",
        "row1Use": "业务目标", "row1Tool": "先定问题", "row1Why": "把模糊需求转成清晰取舍", "row1Chip": "决策依据",
        "row2Use": "协作流程", "row2Tool": "统一上下文", "row2Why": "让上下游围绕同一结果推进", "row2Chip": "团队习惯",
        "row3Use": "行业规则", "row3Tool": "识别边界", "row3Why": "知道哪些判断不能交给模型", "row3Chip": "隐性知识",
        "row4Use": "结果复盘", "row4Tool": "持续修正", "row4Why": "用真实反馈改流程而非只换工具", "row4Chip": "长期积累",
    }


def brief() -> dict[str, object]:
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 358},
        "template_request": {
            "semantic_family": "ai_dialogue_comparison",
            "information_units": 4,
            "numeric_values": [],
            "numeric_scale": "not_applicable",
        },
        "props": {"data": data()},
    }


class HyperFramesChatGPTExchangeBridgeTests(unittest.TestCase):
    def validate(self, value: object) -> subprocess.CompletedProcess[str]:
        self.assertTrue(WRAPPER.is_file(), "missing ChatGPT Exchange bridge")
        self.assertIsNotNone(NODE)
        return subprocess.run(
            [NODE, str(WRAPPER), "--validate"], input=json.dumps(value, ensure_ascii=False),
            capture_output=True, text=True, timeout=10, cwd="/", check=False,
        )

    def test_real_content_is_returned_without_template_defaults(self) -> None:
        original = brief()
        result = self.validate(original)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), original)

    def test_rejects_invalid_contract_before_renderer_load(self) -> None:
        cases = []
        for field, replacement in (("width", 1920), ("fps", 30), ("duration_in_frames", 357)):
            value = brief()
            value["canvas"][field] = replacement
            cases.append(value)
        value = brief()
        value["template_request"]["information_units"] = 3
        cases.append(value)
        value = brief()
        value["template_request"]["semantic_family"] = "bar_chart"
        cases.append(value)
        value = brief()
        value["template_request"]["numeric_values"] = [1]
        cases.append(value)
        value = brief()
        del value["props"]["data"]["row4Why"]
        cases.append(value)
        value = brief()
        value["props"]["data"]["prompt"] = ""
        cases.append(value)
        value = brief()
        value["props"]["data"]["row1Why"] = "这段说明明显超过了已经验证的中文表格容量并且不应该通过门禁"
        cases.append(value)
        value = brief()
        value["props"]["data"]["intro1"] = "含有<标签>的危险内容不能直接进入模板"
        cases.append(value)

        for value in cases:
            with self.subTest(value=value):
                result = self.validate(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ChatGPT Exchange brief:", result.stderr)
                self.assertNotIn("Cannot find module", result.stderr)

    def test_contract_reports_the_actual_number_of_content_fields(self) -> None:
        value = brief()
        value["props"]["data"]["unexpected"] = "不能进入模板"

        result = self.validate(value)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("all 22 content fields must be explicit", result.stderr)

    def test_factory_is_importable_without_project_runtime(self) -> None:
        path = SKILL / "scripts" / "hyperframes_chatgpt_exchange_adapter.py"
        self.assertTrue(path.is_file(), "missing formal ReferenceProcessAdapter factory")
        spec = importlib.util.spec_from_file_location("hyperframes_chatgpt_exchange_adapter", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ("create_adapter", "create_binding", "create_artifact_probe"):
            self.assertTrue(callable(getattr(module, name)))

    def test_chinese_fallback_fonts_are_declared_for_strict_renderer(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        for family in ("PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei"):
            with self.subTest(family=family):
                self.assertIn(f'font-family: "{family}";', source)
                self.assertIn(f'src: local("{family}");', source)

    def test_qualification_cases_are_distinct_and_valid(self) -> None:
        sys.path.insert(0, str(SKILL / "tests"))
        try:
            from render_hyperframes_chatgpt_exchange_integration import build_cases
        finally:
            sys.path.pop(0)
        cases = build_cases()
        self.assertEqual(len(cases), 2)
        for key in cases[0]["props"]["data"]:
            self.assertNotEqual(cases[0]["props"]["data"][key], cases[1]["props"]["data"][key])
        for case in cases:
            result = self.validate(case)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

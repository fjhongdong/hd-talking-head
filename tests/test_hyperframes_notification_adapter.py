"""Behavior checks for the native HyperFrames notification bridge."""
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
WRAPPER = SKILL / "scripts" / "render_hyperframes_notification.cjs"


def brief() -> dict[str, object]:
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 336},
        "template_request": {
            "semantic_family": "progress_sequence",
            "information_units": 4,
            "numeric_values": [],
            "numeric_scale": "not_applicable",
        },
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
            "brandLogo": "data:image/svg+xml;base64,PHN2Zy8+",
        }},
    }


class HyperFramesNotificationBridgeTests(unittest.TestCase):
    def validate(self, value: object) -> subprocess.CompletedProcess[str]:
        self.assertTrue(WRAPPER.is_file(), "missing HyperFrames notification bridge")
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

    def test_rejects_content_outside_native_contract_before_renderer_load(self) -> None:
        cases = []
        for field, replacement in (("width", 1920), ("fps", 30), ("duration_in_frames", 335)):
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
        value["props"]["data"]["messages"] = value["props"]["data"]["messages"][:3]
        cases.append(value)
        value = brief()
        value["props"]["data"]["message1"] = "undeclared"
        cases.append(value)
        value = brief()
        value["props"]["data"]["notifTitle"] = ""
        cases.append(value)
        value = brief()
        value["props"]["data"]["brandLogo"] = "https://example.invalid/logo.svg"
        cases.append(value)
        value = brief()
        value["props"]["data"]["messages"][0] = "x" * 200
        cases.append(value)

        for value in cases:
            with self.subTest(value=value):
                result = self.validate(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Notification Cascade brief:", result.stderr)
                self.assertNotIn("Cannot find module", result.stderr)

    def test_factory_is_importable_without_project_runtime(self) -> None:
        path = SKILL / "scripts" / "hyperframes_notification_adapter.py"
        self.assertTrue(path.is_file(), "missing formal ReferenceProcessAdapter factory")
        spec = importlib.util.spec_from_file_location("hyperframes_notification_adapter", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ("create_adapter", "create_binding", "create_artifact_probe"):
            self.assertTrue(callable(getattr(module, name)))

    def test_qualification_cases_are_two_distinct_valid_semantic_inputs(self) -> None:
        sys.path.insert(0, str(SKILL / "tests"))
        try:
            from render_hyperframes_notification_integration import build_cases
        finally:
            sys.path.pop(0)
        cases = build_cases()
        self.assertEqual(len(cases), 2)
        self.assertNotEqual(cases[0]["props"]["data"], cases[1]["props"]["data"])
        for key in cases[0]["props"]["data"]:
            self.assertNotEqual(cases[0]["props"]["data"][key], cases[1]["props"]["data"][key])
        for case in cases:
            result = self.validate(case)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

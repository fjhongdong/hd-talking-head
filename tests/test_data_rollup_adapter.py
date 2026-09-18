"""Behavior checks for the native template bridge (no browser in unit tests)."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
WRAPPER = SKILL / "scripts/render_data_rollup.cjs"


def brief():
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 96},
        "template_request": {"semantic_family": "bar_chart", "information_units": 3,
                             "numeric_values": [2, 5, 9], "numeric_scale": "linear"},
        "props": {"data": {"title": "模板测试 A", "unit": "项", "items": [
            {"label": "流程一", "value": 2}, {"label": "流程二", "value": 5},
            {"label": "流程三", "value": 9}]},
            "accent": "#FF5A2C", "background": "#0E0E10", "foreground": "#F5F5F2"},
    }


class DataRollupBridgeTests(unittest.TestCase):
    def test_executor_stdin_entrypoint_is_actually_executed(self):
        self.assertTrue(WRAPPER.is_file())
        result = subprocess.run([NODE, "-", "--bogus"], input=WRAPPER.read_bytes(),
                                capture_output=True, timeout=10, cwd="/", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"approved data_rollup_adapter factory", result.stderr)

    def validate(self, value):
        self.assertTrue(WRAPPER.is_file(), "missing executable native DataRollup bridge")
        self.assertIsNotNone(NODE, "Node dependency must be installed before bridge tests")
        return subprocess.run(
            [NODE, str(WRAPPER), "--validate"], input=json.dumps(value),
            capture_output=True, text=True, timeout=10, cwd="/", check=False,
        )

    def test_real_props_are_returned_without_sample_defaults(self):
        original = brief()
        result = self.validate(original)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), original)

    def test_rejects_request_that_does_not_match_actual_items(self):
        value = brief()
        value["props"]["data"]["items"][1]["value"] = 7
        result = self.validate(value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("numeric_values", result.stderr)

    def test_eight_single_digit_bars_fit_without_inventing_two_digits(self):
        value = brief()
        value["props"]["data"].update(title="八柱测试", unit="", items=[
            {"label": label, "value": 9} for label in "甲乙丙丁戊己庚辛"])
        value["template_request"].update(information_units=8, numeric_values=[9] * 8)
        result = self.validate(value)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_unsupported_content_before_loading_renderer(self):
        cases = []
        for field, replacement in [("width", 1920), ("fps", 30), ("duration_in_frames", 24)]:
            value = brief()
            value["canvas"][field] = replacement
            cases.append(value)
        for numbers in ([1.5, 5, 9], [-1, 5, 9], [1, 5, 100], [True, 5, 9]):
            value = brief()
            value["template_request"]["numeric_values"] = numbers
            for item, number in zip(value["props"]["data"]["items"], numbers):
                item["value"] = number
            cases.append(value)
        value = brief()
        del value["props"]["data"]["title"]
        cases.append(value)
        value = brief()
        value["props"]["data"]["items"][0]["label"] = "不能把长文案挤到一个很窄的柱子下面"
        cases.append(value)
        value = brief()
        value["props"]["accent"] = "url(https://example.invalid/a)"
        cases.append(value)
        value = brief()
        value["template_request"]["semantic_family"] = "causal_flow"
        cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                result = self.validate(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DataRollup brief:", result.stderr)
                self.assertNotIn("Cannot find module", result.stderr)

    def test_factory_is_importable_without_importing_project_runtime(self):
        path = SKILL / "scripts/data_rollup_adapter.py"
        self.assertTrue(path.is_file(), "missing formal ReferenceProcessAdapter factory")
        spec = importlib.util.spec_from_file_location("data_rollup_adapter", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ("create_adapter", "create_binding", "create_artifact_probe"):
            self.assertTrue(callable(getattr(module, name)))

    def test_binding_and_loader_freeze_real_content_without_success_claim(self):
        path = SKILL / "scripts/data_rollup_adapter.py"
        self.assertTrue(path.is_file())
        spec = importlib.util.spec_from_file_location("data_rollup_binding_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = json.dumps(brief()).encode()
        # Package metadata only: no bundler, browser, or media result is mocked.
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            for pkg in ("remotion", "@remotion/renderer", "@remotion/bundler"):
                folder = runtime / "node_modules" / pkg
                folder.mkdir(parents=True)
                (folder / "package.json").write_text('{"version":"4.0.520"}')
            adapter = module.create_adapter(runtime_root=runtime, node_executable=NODE,
                browser_executable=NODE, brief_loader=lambda *_: payload)
            binding = module.create_binding(adapter, payload)
            self.assertEqual(binding["invocation_record"]["status"], "planned")
            self.assertIsNone(binding["invocation_record"]["exit_code"])
            self.assertEqual(binding["brief_sha256"], hashlib.sha256(payload).hexdigest())
            component = {**binding, "render_window": {"start_frame": 5, "end_frame": 101},
                         "artifact_contract": {"alpha": False}}
            recipe = {"canvas": {"width": 1080, "height": 1920, "fps": 24}}
            self.assertEqual(adapter.brief_loader(None, recipe, component), payload)
            component["render_window"]["end_frame"] = 100
            with self.assertRaisesRegex(ValueError, "render window"):
                adapter.brief_loader(None, recipe, component)
            component["render_window"]["end_frame"] = 101
            component["invocation_record"]["template_request"]["numeric_values"] = [2, 5, 8]
            with self.assertRaisesRegex(ValueError, "frozen template_request"):
                adapter.brief_loader(None, recipe, component)

    def test_qualification_registry_is_explicitly_frozen(self):
        path = SKILL / "scripts/data_rollup_adapter.py"
        spec = importlib.util.spec_from_file_location("data_rollup_qualification_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = json.dumps(brief()).encode()
        source = "assets/verified-templates/hyperframes/notification-cascade/qualification/source-registry.json"
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            for pkg in ("remotion", "@remotion/renderer", "@remotion/bundler"):
                folder = runtime / "node_modules" / pkg
                folder.mkdir(parents=True)
                (folder / "package.json").write_text('{"version":"4.0.520"}')
            adapter = module.create_adapter(runtime_root=runtime, node_executable=NODE,
                browser_executable=NODE, brief_loader=lambda *_: payload, registry_path=source)
            self.assertEqual(adapter.qualification_registry_path, source)
            self.assertEqual(adapter.qualification_registry_sha256,
                             hashlib.sha256((SKILL / source).read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, "inside the Skill"):
                module.create_adapter(runtime_root=runtime, node_executable=NODE,
                    browser_executable=NODE, brief_loader=lambda *_: payload,
                    registry_path="../outside.json")


if __name__ == "__main__":
    unittest.main()

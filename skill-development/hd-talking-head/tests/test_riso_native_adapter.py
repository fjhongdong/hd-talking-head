"""Small synthetic input/selection regression; no generation or user Job."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location("riso_native_adapter", SKILL / "scripts/riso_native_adapter.py")
riso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(riso)


def number_brief():
    return {"schema_version": 1,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-riso-test", "start": 0, "end": 5},
            "composition": {"id": "riso-test", "width": 1080, "height": 1920, "fps": 24, "frames": 120},
            "template_request": {"semantic_family": "numeric_emphasis", "information_units": 1, "numeric_values": [12], "numeric_scale": "linear"},
            "template": "number", "assets": [],
            "data": {"palette": "pal-blue", "mast": ["验证 · 非真实数据", "原生模板"], "duration": 5,
                     "number": 12, "prefix": "", "suffix": "", "comma": False, "unit": "项测试",
                     "say": "公开[内容槽]"}}


class RisoNativeAdapterTest(unittest.TestCase):
    def test_formal_recipe_guard_and_existing_artifact(self):
        from edit.hd.tools import visual_plan, visual_canary, broll_component_executor
        from edit.hd.tests.test_broll_capability_router import (
            _load_router, _visual_intent, _visual_strategy, _strategy_component, avatar_fixture)

        value = number_brief()
        payload = json.dumps(value, ensure_ascii=False).encode()
        sample = ROOT / "skill-development/test-output/cutcod-riso-20261021/minimal-native-gbnr7_er/riso-number-normalized.mp4"
        adapter = riso.create_adapter(ROOT, sys.executable, lambda *_: payload)
        binding = riso.create_binding(adapter, payload, sample)
        strategy = _visual_strategy([_strategy_component("scene", "code_generated", layout_slot="full_frame")])
        strategy["segment_id"] = value["source_binding"]["segment_id"]
        strategy["composition"]["avatar"] = avatar_fixture(frames=120)
        context = {"intent": _visual_intent(strategy["segment_id"]), "bindings": {"scene": binding},
                   "candidate_snapshots": {}, "segment_frames": 120}
        visual_plan._prevalidate_draft_bindings(strategy, context["bindings"], 1, 120)
        router = _load_router()
        recipe = router.compile_strategy(strategy, context)
        component = recipe["components"][0]
        contract = {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
        self.assertEqual(component["artifact_contract"], contract)
        self.assertEqual(component["executor"], "reference_adapter")
        self.assertEqual(component["template_id"], "eian-riso-broll/number")
        self.assertIs(broll_component_executor._validate_code_adapter(adapter, component), adapter)
        # Only the approval lookup is synthetic; the compiled recipe and guard are real.
        plan = {"edited_aroll_sha256": value["source_binding"]["aroll_sha256"], "segments": [{
            "segment_id": strategy["segment_id"], "start": 0, "end": 5, "shot_recipe": recipe}]}
        with patch.object(visual_canary, "load_approved_visual_plan", return_value=plan):
            self.assertEqual(adapter.brief_loader(None, recipe, component), payload)
            bad_component = copy.deepcopy(component)
            bad_component["artifact_contract"]["alpha"] = True
            with self.assertRaises(ValueError):
                adapter.brief_loader(None, recipe, bad_component)

        # Probe the existing real clip. This never invokes its native renderer.
        probe = riso.create_artifact_probe(riso.check_runtime(ROOT)["ffprobe"])
        media = probe.probe(sample, "video", component["artifact_contract"])
        self.assertEqual(media["frame_count"], 120)
        self.assertEqual(media["duration"], 5.0)
        with self.assertRaisesRegex(ValueError, "media contract failed"):
            probe.probe(sample.with_name("riso-number.mp4"), "video", component["artifact_contract"])
        self.assertEqual(router.riso_output_contract(strategy["components"][0],
                         {"family": "evidence_with_data_overlay"}), contract)

        for field, replacement in (("layer_role", "overlay"), ("layout_slot", "main"),
                                   ("family", "aroll_with_overlay"), ("family", "no_broll")):
            bad = copy.deepcopy(strategy)
            target = bad["composition"] if field == "family" else bad["components"][0]
            target[field] = replacement
            with self.subTest(field=field, value=replacement):
                with self.assertRaisesRegex(router.RouterError, "Riso requires"):
                    router.riso_output_contract(bad["components"][0], bad["composition"])
                with self.assertRaisesRegex(visual_plan.VisualPlanError, "Riso requires"):
                    visual_plan._prevalidate_draft_bindings(bad, context["bindings"], 1, 120)
                with self.assertRaises(ValueError):
                    router.compile_strategy(bad, context)
                bad_recipe, bad_component = copy.deepcopy(recipe), copy.deepcopy(component)
                if field == "family":
                    bad_recipe["composition"][field] = replacement
                elif field == "layout_slot":
                    bad_component["render_window"][field] = replacement
                else:
                    bad_component[field] = replacement
                with self.assertRaisesRegex(ValueError, "Riso requires"):
                    adapter.brief_loader(None, bad_recipe, bad_component)

    def test_native_slots_and_discovery(self):
        from edit.hd.tools import motion_capabilities as motion
        value = number_brief()
        riso.validate_brief(json.dumps(value))
        for key, replacement in (("number", 12.5), ("duration", 4), ("say", "<script>"), ("palette", "custom")):
            bad = copy.deepcopy(value)
            bad["data"][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                riso.validate_brief(bad)
        bad = copy.deepcopy(value)
        bad["template_request"]["numeric_values"] = [13]
        with self.assertRaisesRegex(ValueError, "contradicts"):
            riso.validate_brief(bad)
        catalog = motion.load_catalog(ROOT)
        rows = [row for row in catalog if row.get("dependency_id") == riso.DEPENDENCY_ID]
        self.assertEqual({row["source_route"] for row in rows}, set(riso.FAMILIES))
        self.assertTrue(all(row["status"] == "supported" and row["capability"]["uses"] == ["broll"] for row in rows))
        row = next(row for row in rows if row["source_route"] == "number")
        self.assertEqual(motion._native_input_check(ROOT, row, value)["status"], "pass")
        # Native public fields do not grant transparency, code or a screenshot placeholder.
        bad = copy.deepcopy(value)
        bad["composition"]["alpha"] = True
        with self.assertRaises(ValueError):
            riso.validate_brief(bad)


if __name__ == "__main__":
    unittest.main()

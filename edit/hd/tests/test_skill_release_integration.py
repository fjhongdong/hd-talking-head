"""Freeze a reviewed template through the actual visual-plan compiler."""

from __future__ import annotations

import copy
from types import SimpleNamespace
import unittest

from edit.hd.tests.test_visual_plan import valid_plan
from edit.hd.tools import visual_plan


def provenance() -> dict:
    return {
        "template_origin": "custom_fallback",
        "template_id": "explicit-custom",
        "template_version": "1",
        "verification_id": "7" * 64,
        "adaptation_level": "structural",
        "source_entrypoint": "templates/explicit-custom.html",
        "source_sha256": "8" * 64,
        "sample_sha256": "9" * 64,
        "semantic_families": ["explanation"],
        "capacity": {"min_units": 1, "max_units": 7},
    }


class SkillReleaseIntegrationTests(unittest.TestCase):
    def segment(self, binding: dict) -> dict:
        segment = copy.deepcopy(valid_plan(("code_generated",))["segments"][0])
        segment.pop("shot_recipe")
        segment["strategy_revision"] = 1
        segment["bindings"]["component-1"] = binding
        return segment

    def test_formal_compiler_preserves_already_frozen_template(self) -> None:
        from tests.test_sweety_native_adapter import SKILL, brief, sweety

        task = {**brief(), "template_id": "web-flow", "composition": {"width": 1080, "height": 1920,
                "fps": 24, "frames": 72}}
        task["source_binding"].update(segment_id="seg-001", end=3)
        task["word_anchors"][0]["end"] = 3
        adapter = SimpleNamespace(entrypoint_sha256=sweety.sha(SKILL / sweety.ENTRY), launcher="python3.12")
        binding = sweety.create_binding(adapter, sweety.artifacts.canonical_json_bytes(task))
        segment = self.segment(binding)
        segment["visual_strategy"]["components"][0]["layout_slot"] = "full_frame"
        checked = visual_plan._validate_semantic_segment(segment, draft=True)
        result = visual_plan._freeze_and_compile_segment(
            checked, candidate_freezers={}, binding_freezers={},
            strategy_compiler=visual_plan._canonical_compile_strategy,
        )
        visual_plan._validate_semantic_segment(result, draft=False)
        component = result["shot_recipe"]["components"][0]
        self.assertEqual(component["executor"], "reference_adapter")
        self.assertTrue(component["artifact_contract"]["alpha"])
        for name, value in binding.items():
            self.assertEqual(component[name], value)
            self.assertEqual(result["bindings"]["component-1"][name], value)

    def test_structural_change_cannot_keep_verified_identity(self) -> None:
        binding = valid_plan(("code_generated",))["segments"][0]["bindings"]["component-1"]
        segment = self.segment({**binding, **provenance(), "template_origin": "verified_third_party"})
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "structural"):
            visual_plan._validate_semantic_segment(segment, draft=True)


if __name__ == "__main__":
    unittest.main()

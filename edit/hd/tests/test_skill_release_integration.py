"""Freeze a reviewed template through the actual visual-plan compiler."""

from __future__ import annotations

import copy
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
    def segment(self) -> dict:
        segment = copy.deepcopy(valid_plan(("code_generated",))["segments"][0])
        segment.pop("shot_recipe")
        segment["strategy_revision"] = 1
        segment["bindings"]["component-1"].update(provenance())
        return segment

    def test_formal_compiler_preserves_already_frozen_template(self) -> None:
        segment = self.segment()
        checked = visual_plan._validate_semantic_segment(segment, draft=True)
        result = visual_plan._freeze_and_compile_segment(
            checked, candidate_freezers={}, binding_freezers={},
            strategy_compiler=visual_plan._canonical_compile_strategy,
        )
        visual_plan._validate_semantic_segment(result, draft=False)
        component = result["shot_recipe"]["components"][0]
        self.assertEqual(component["executor"], "reference_adapter")
        for name, value in provenance().items():
            self.assertEqual(component[name], value)
            self.assertEqual(result["bindings"]["component-1"][name], value)

    def test_structural_change_cannot_keep_verified_identity(self) -> None:
        segment = self.segment()
        segment["bindings"]["component-1"]["template_origin"] = "verified_third_party"
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "structural"):
            visual_plan._validate_semantic_segment(segment, draft=True)


if __name__ == "__main__":
    unittest.main()

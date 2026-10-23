"""ShotRecipe accepts semantic motion only for the native RelationMotion binding."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from edit.hd.tests.test_broll_component_executor import _code_component, _recipe
from edit.hd.tests import test_broll_capability_router as router_fixture
from edit.hd.tests.test_semantic_motion import ITEMS, draft
from edit.hd.tools import semantic_motion
from edit.hd.tools.visual_strategy import VisualStrategyError, validate_shot_recipe_v2


def relation_plan() -> dict:
    value = draft("relation")
    value["subjects"].insert(1, {
        "id": "source-2", "label": "协作流程", "initial_state": "尚未展示",
        "final_state": "已展示", "preserve": False,
    })
    value["actions"][0]["subject_ids"].append("source-2")
    value["actions"][1]["subject_ids"].insert(1, "source-2")
    return value


def report(plan: dict | None = None) -> dict:
    value = semantic_motion.build_motion_plan(
        plan or relation_plan(), approved_items=ITEMS
    )
    return {**value, "content_analysis_sha256": "a" * 64}


def component() -> dict:
    brief = b"approved relation brief"
    value = _code_component(brief)
    value.update({
        "executor": "reference_adapter",
        "dependency_id": "hd-talking-head-relation-motion",
        "entrypoint": "scripts/relation_motion_renderer_bundle.py",
        "producer_version": "1.0.0",
        "primary_renderer": "RelationMotion",
        "renderer_version": "1.0.0",
        "template_origin": "verified_local_canonical",
        "template_id": "hd-talking-head/relation-motion",
        "template_version": "1.0.0",
        "adaptation_level": "content_reflow",
        "source_entrypoint": "scripts/relation_motion_renderer_bundle.py",
        "semantic_families": ["relation"],
        "capacity": {"min_units": 2, "max_units": 4},
        "render_window": {
            "start_frame": 24, "end_frame": 144, "z_index": 0,
            "layout_slot": "main", "opacity": 1.0,
            "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
        },
        "artifact_contract": {
            "width": 1080, "height": 1920, "fps": 24, "alpha": False,
        },
    })
    value["invocation_record"] = {
        "argv": ["python", value["entrypoint"]],
        "status": "planned",
        "exit_code": None,
        "template_request": {
            "semantic_family": "relation", "information_units": 2,
            "numeric_values": [], "numeric_scale": "not_applicable",
        },
        "semantic_motion": report(),
    }
    return value


class RelationMotionShotRecipeSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = router_fixture._load_router()

    def validate(self, value: dict | None = None) -> dict:
        return validate_shot_recipe_v2(_recipe([value or component()]))

    def test_native_relation_motion_accepts_complete_planning_report(self) -> None:
        checked = self.validate()
        frozen = checked["components"][0]["invocation_record"]["semantic_motion"]
        self.assertEqual(frozen, report())

    def test_every_native_identity_field_is_required_exactly(self) -> None:
        mutations = {
            "dependency_id": "html-video",
            "template_id": "local-canonical/process-relations",
            "template_version": "0.9.0",
            "primary_renderer": "HyperFrames",
            "entrypoint": "scripts/local_canonical_renderer.cjs",
            "source_entrypoint": "scripts/local_canonical_renderer.cjs",
            "producer_version": "0.9.0",
            "renderer_version": "0.9.0",
            "template_origin": "custom_fallback",
            "executor": "approved:code_generated",
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field):
                value = component()
                value[field] = replacement
                with self.assertRaisesRegex(VisualStrategyError, "semantic_motion"):
                    self.validate(value)

    def test_report_sha_shape_duration_and_check_frames_are_cross_checked(self) -> None:
        mutations = [
            lambda r: r.pop("content_analysis_sha256"),
            lambda r: r.update(content_analysis_sha256="not-a-hash"),
            lambda r: r.update(extra=True),
            lambda r: r["check_frames"].update(before_exit=106),
            lambda r: r["plan"].update(duration_frames=119),
            lambda r: r.update(execution_status="approved"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = component()
                mutation(value["invocation_record"]["semantic_motion"])
                with self.assertRaises(VisualStrategyError):
                    self.validate(value)

    def test_other_five_planner_families_remain_rejected_for_native_renderer(self) -> None:
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            with self.subTest(family=family):
                value = component()
                plan = draft(family)
                value["invocation_record"]["semantic_motion"] = report(plan)
                value["invocation_record"]["template_request"]["semantic_family"] = family
                with self.assertRaisesRegex(VisualStrategyError, "relation"):
                    self.validate(value)

    def test_legacy_renderer_cannot_carry_even_a_valid_relation_report(self) -> None:
        value = _code_component(b"legacy")
        value["invocation_record"]["semantic_motion"] = copy.deepcopy(report())
        with self.assertRaisesRegex(VisualStrategyError, "semantic_motion"):
            self.validate(value)

    def compile(self, *, segment_frames: int = 120, value: dict | None = None):
        router = self.router
        recipe_component = value or component()
        binding = {
            key: copy.deepcopy(field)
            for key, field in recipe_component.items()
            if key not in {
                "component_id", "kind", "semantic_role", "layer_role", "executor",
                "media_type", "render_window", "artifact_contract",
            }
        }
        strategy_component = router_fixture._strategy_component("code", "code_generated")
        strategy = router_fixture._visual_strategy([strategy_component])
        context = {
            "intent": router_fixture._visual_intent(),
            "candidate_snapshots": {},
            "bindings": {"code": binding},
            "segment_frames": segment_frames,
        }
        registered = {
            **{key: copy.deepcopy(binding[key]) for key in router._TEMPLATE_PROVENANCE_FIELDS},
            "upstream": {
                "project": "hd-talking-head-relation-motion",
                "repository": ".",
                "commit": "relation-motion-v1",
            },
            "render_contract": {
                "engine": "RelationMotion",
                "composition_id": "relation-motion",
                "exit_policy": "template",
            },
        }
        with mock.patch.object(router, "_registered_template", return_value=registered):
            return router.compile_strategy(strategy, context)

    def test_compile_strategy_accepts_120_frame_native_binding(self) -> None:
        recipe = self.compile()
        compiled = recipe["components"][0]
        self.assertEqual(compiled["render_window"]["end_frame"], 120)
        self.assertEqual(compiled["executor"], "reference_adapter")
        self.assertFalse(compiled["artifact_contract"]["alpha"])

    def test_compile_strategy_rejects_actual_duration_mismatch_and_legacy_identity(self) -> None:
        with self.assertRaises(self.router.RouterError):
            self.compile(segment_frames=119)
        legacy = component()
        legacy["primary_renderer"] = "HyperFrames"
        with self.assertRaises(self.router.RouterError):
            self.compile(value=legacy)


if __name__ == "__main__":
    unittest.main()

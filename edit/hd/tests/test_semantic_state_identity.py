"""Native semantic templates must consume exactly their declared family."""
import copy
import unittest
from unittest import mock

from edit.hd.tests.test_semantic_state_renderer import brief
from edit.hd.tools import semantic_motion, visual_strategy as strategy
from edit.hd.tests import test_relation_motion_schema as relation_fixture
from edit.hd.tools.visual_plan import _load_router_module


class SemanticStateIdentityTests(unittest.TestCase):
    def test_compile_five_families_opaque_and_exact_duration(self):
        router = _load_router_module()
        fixtures = relation_fixture.router_fixture
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            component = relation_fixture.component()
            component.update(self.component(family))
            component["semantic_families"] = [family]
            component["invocation_record"].update({
                "argv": ["python", component["entrypoint"]], "status": "planned", "exit_code": None,
                "template_request": {"semantic_family": family,
                    "information_units": len(component["invocation_record"]["semantic_motion"]["plan"]["subjects"]),
                    "numeric_values": [], "numeric_scale": "not_applicable"}})
            reserved = {"component_id", "kind", "semantic_role", "layer_role", "executor",
                        "media_type", "render_window", "artifact_contract"}
            binding = {key: value for key, value in component.items() if key not in reserved}
            record = {"upstream": {"project": "hd-talking-head-semantic-state"},
                      "render_contract": {"engine": "SemanticState"}}
            visual = fixtures._visual_strategy([fixtures._strategy_component("code", "code_generated")])
            context = {"intent": fixtures._visual_intent(), "candidate_snapshots": {},
                       "bindings": {"code": binding}, "segment_frames": 120}
            # Isolate registration only; compiler and recipe authority remain real.
            with self.subTest(family=family), mock.patch.object(router, "_registered_template", return_value=record):
                compiled = router.compile_strategy(visual, context)["components"][0]
                self.assertFalse(compiled["artifact_contract"]["alpha"])
                self.assertEqual(compiled["render_window"]["end_frame"], 120)
                self.assertEqual(compiled["executor"], "reference_adapter")
                with self.assertRaisesRegex(router.RouterError, "duration"):
                    router.compile_strategy(visual, {**context, "segment_frames": 119})

    def test_router_preserves_native_duration_and_identity(self):
        router = _load_router_module()
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            component = relation_fixture.component()
            component.update(self.component(family))
            component["semantic_families"] = [family]
            component["invocation_record"].update({
                "argv": ["python", component["entrypoint"]], "status": "planned", "exit_code": None,
                "template_request": {"semantic_family": family, "information_units": 2,
                                     "numeric_values": [], "numeric_scale": "not_applicable"}})
            reserved = {"component_id", "kind", "semantic_role", "layer_role", "executor",
                        "media_type", "render_window", "artifact_contract"}
            evidence = {key: value for key, value in component.items() if key not in reserved}
            # Force the registered-template lookup to fail after structural
            # validation; successful production registration is covered by the
            # release and template-verifier suites.
            with self.subTest(family=family), mock.patch.object(
                router, "_registered_template", side_effect=router.RouterError("qualification sentinel")
            ) as lookup:
                with self.assertRaisesRegex(router.RouterError, "qualification sentinel"):
                    router.validate_invocation_evidence(evidence)
                lookup.assert_called_once()

    def component(self, family):
        plan = brief(family)["motion"]
        report = semantic_motion.build_motion_plan(plan, approved_items=[{
            "id": plan["content_item_id"], "source_text": plan["source_text"],
            "evidence_status": "supported"}])
        report["content_analysis_sha256"] = "a" * 64
        return {"kind": "code_generated", "executor": "reference_adapter",
            "dependency_id": "hd-talking-head-semantic-state",
            "template_origin": "verified_local_canonical",
            "template_id": "hd-talking-head/semantic-state-" + family,
            "template_version": "1.0.0", "producer_version": "1.0.0",
            "entrypoint": "scripts/semantic_state_renderer_bundle.py",
            "source_entrypoint": "scripts/semantic_state_renderer_bundle.py",
            "primary_renderer": "SemanticState", "renderer_version": "1.0.0",
            "render_window": {"start_frame": 0, "end_frame": 120},
            "invocation_record": {"semantic_motion": report}}

    def test_family_identity_and_exit(self):
        families = ("replacement", "threshold", "delay", "hierarchy", "feedback")
        for family in families:
            component = self.component(family)
            with self.subTest(family=family):
                self.assertEqual(strategy.native_motion_exit_window(component), (108, 120))
            for other in families:
                if other == family:
                    continue
                bad = copy.deepcopy(component)
                bad["template_id"] = "hd-talking-head/semantic-state-" + other
                with self.subTest(family=family, other=other), self.assertRaises(strategy.VisualStrategyError):
                    strategy.native_motion_exit_window(bad)

    def test_identity_and_report_mutations_rejected(self):
        component = self.component("feedback")
        for field in ("executor", "dependency_id", "template_origin", "template_id",
                      "template_version", "producer_version", "entrypoint", "source_entrypoint",
                      "primary_renderer", "renderer_version"):
            with self.subTest(field=field), self.assertRaises(strategy.VisualStrategyError):
                strategy.native_motion_exit_window({**component, field: "wrong"})
        for field, value in (("family", "unknown"), ("duration_frames", 121)):
            bad = copy.deepcopy(component)
            bad["invocation_record"]["semantic_motion"]["plan"][field] = value
            with self.subTest(field=field), self.assertRaises(strategy.VisualStrategyError):
                strategy.native_motion_exit_window(bad)

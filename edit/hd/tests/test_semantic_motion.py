"""Semantic planning is checked, but never confused with executed animation."""

import copy
import importlib
import json
import unittest

from edit.hd.tests.test_broll_component_executor import _code_component, _recipe
from edit.hd.tools.visual_strategy import VisualStrategyError, validate_shot_recipe_v2
from edit.hd.tests import test_content_analysis as content_fixture
from edit.hd.tools import content_analysis, state


ITEMS = [{"id": "item-1", "source_text": "工作细节经过整合形成新的流程", "evidence_status": "supported"}]
PATTERNS = {
    "relation": ["reveal_sources", "draw_connections", "reveal_hub"],
    "replacement": ["establish", "replace", "compare"],
    "threshold": ["establish", "cross_threshold", "raise_threshold"],
    "delay": ["establish", "wait", "realize"],
    "hierarchy": ["establish", "reveal_layers", "resolve"],
    "feedback": ["establish", "produce", "feedback_return"],
}


def draft(family="relation"):
    return {
        "version": 1, "content_item_id": "item-1", "source_text": ITEMS[0]["source_text"],
        "family": family, "meaningful_change": "来源建立后汇聚，展示整合关系",
        "subjects": [
            {"id": "source", "label": "工作细节", "initial_state": "尚未展示", "final_state": "已展示", "preserve": False},
            {"id": "hub", "label": "流程", "initial_state": "尚未形成", "final_state": "形成", "preserve": False},
        ],
        "actions": [
            {"id": "nodes", "operation": PATTERNS[family][0], "subject_ids": ["source"], "start_frame": 0, "end_frame": 12, "depends_on": []},
            {"id": "draw", "operation": PATTERNS[family][1], "subject_ids": ["source", "hub"], "start_frame": 12, "end_frame": 24, "depends_on": ["nodes"]},
            {"id": "hub", "operation": PATTERNS[family][2], "subject_ids": ["hub"], "start_frame": 24, "end_frame": 36, "depends_on": ["draw"]},
        ],
        "duration_frames": 120,
        "read_window": {"start_frame": 36, "end_frame": 108, "minimum_frames": 24},
        "exit_window": {"start_frame": 108, "end_frame": 120},
    }


class SemanticMotionTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.find_spec("edit.hd.tools.semantic_motion")
        self.assertIsNotNone(spec, "semantic motion planner is missing")
        return importlib.import_module("edit.hd.tools.semantic_motion")

    def build(self, value=None, items=None):
        return self.module().build_motion_plan(value or draft(), approved_items=ITEMS if items is None else items)

    def reject(self, value):
        module = self.module()
        with self.assertRaises(module.SemanticMotionError):
            module.build_motion_plan(value, approved_items=ITEMS)

    def test_all_six_patterns_are_planning_only_and_leave_inputs_unchanged(self):
        for family in PATTERNS:
            with self.subTest(family=family):
                value = draft(family)
                before = copy.deepcopy((value, ITEMS))
                report = self.build(value)
                self.assertEqual(report["execution_status"], "planning_only")
                self.assertEqual(report["plan"], value)
                self.assertEqual((value, ITEMS), before)
                json.dumps(report, allow_nan=False)
                report["plan"]["subjects"][0]["label"] = "changed"
                self.assertEqual((value, ITEMS), before)

    def test_original_text_unknown_id_unsupported_and_duplicate_items_are_rejected(self):
        for key, value in (("content_item_id", "unknown"), ("source_text", "伪造原文")):
            altered = draft()
            altered[key] = value
            self.reject(altered)
        module = self.module()
        for items in ([], ITEMS * 2, [{**ITEMS[0], "evidence_status": "unsupported"}]):
            with self.assertRaises(module.SemanticMotionError):
                self.build(items=items)

    def test_half_open_frame_boundaries_do_not_activate_both_actions(self):
        module = self.module()
        plan = self.build()["plan"]
        for frame, expected in ((0, ["nodes"]), (11, ["nodes"]), (12, ["draw"]),
                                (24, ["hub"]), (36, []), (119, []), (120, [])):
            self.assertEqual(module.active_action_ids(plan, frame), expected)

    def test_malformed_evidence_status_has_a_controlled_error(self):
        for status in ([], {}, None, True):
            with self.subTest(status=status):
                with self.assertRaises(self.module().SemanticMotionError):
                    self.build(items=[{**ITEMS[0], "evidence_status": status}])

    def test_check_frames_cover_initial_action_completion_read_and_exit_boundary(self):
        frames = self.build()["check_frames"]
        self.assertEqual(frames["initial"], 0)
        self.assertEqual(frames["action_completed"], {"nodes": 12, "draw": 24, "hub": 36})
        self.assertEqual(frames["read_start"], 36)
        self.assertEqual(frames["before_exit"], 107)
        self.assertEqual(frames["last_visible"], 119)
        self.assertEqual(frames["next_boundary"], 120)

    def test_order_cycle_missing_dependency_and_unknown_subject_rejected(self):
        mutations = [
            lambda p: p["actions"][0].update(depends_on=["hub"]),
            lambda p: p["actions"][1].update(depends_on=[]),
            lambda p: p["actions"][1].update(depends_on=["missing"]),
            lambda p: p["actions"][1].update(subject_ids=["missing"]),
            lambda p: p["actions"][1].update(operation="reveal_hub"),
            lambda p: p["actions"][1].update(start_frame=11),
            lambda p: p["actions"][1].update(id="nodes"),
            lambda p: p["actions"][1].update(depends_on=["nodes", "nodes"]),
        ]
        for mutate in mutations:
            value = draft()
            mutate(value)
            self.reject(value)

    def test_non_finite_boolean_fractional_negative_and_out_of_range_frames_rejected(self):
        for invalid in (True, float("nan"), float("inf"), 1.5, -1, 121):
            value = draft()
            value["actions"][1]["start_frame"] = invalid
            self.reject(value)
        for invalid in (True, 0, -2, 120.5):
            value = draft()
            value["duration_frames"] = invalid
            self.reject(value)

    def test_reading_must_follow_actions_and_exit_must_cover_end(self):
        mutations = [
            lambda p: p["read_window"].update(start_frame=35),
            lambda p: p["read_window"].update(minimum_frames=73),
            lambda p: p["read_window"].update(minimum_frames=0),
            lambda p: p["exit_window"].update(start_frame=107),
            lambda p: p["exit_window"].update(end_frame=119),
            lambda p: p["exit_window"].update(end_frame=121),
        ]
        for mutate in mutations:
            value = draft()
            mutate(value)
            self.reject(value)

    def test_preserved_subject_cannot_change_state_or_be_replaced(self):
        value = draft("replacement")
        value["subjects"][0]["preserve"] = True
        self.reject(value)
        value["subjects"][0]["final_state"] = value["subjects"][0]["initial_state"]
        self.reject(value)

    def test_preserved_context_can_be_established_and_compared(self):
        value = draft("replacement")
        value["subjects"].append({"id": "layout", "label": "布局", "initial_state": "不变", "final_state": "不变", "preserve": True})
        value["actions"][0]["subject_ids"].append("layout")
        value["actions"][2]["subject_ids"].append("layout")
        self.build(value)

    def test_unknown_fields_empty_change_and_unused_subject_fail(self):
        for mutate in (lambda p: p.update(auto_approve=True),
                       lambda p: p.update(meaningful_change=" "),
                       lambda p: p["subjects"].append({**p["subjects"][0], "id": "unused"})):
            value = draft()
            mutate(value)
            self.reject(value)

    def test_formal_recipe_cannot_silently_ignore_unimplemented_semantic_motion(self):
        component = _code_component(b"brief")
        component["invocation_record"]["semantic_motion"] = draft()
        with self.assertRaisesRegex(VisualStrategyError, "semantic_motion.*not.*supported"):
            validate_shot_recipe_v2(_recipe([component]))

    def test_job_entry_uses_current_approval_without_changing_files_or_state(self):
        fixture = content_fixture.ContentAnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        record = content_analysis.prepare_content_analysis(fixture.job, content_fixture.VALID_ANALYSIS)
        module = self.module()
        self.assertTrue(callable(getattr(module, "plan_motion_for_job", None)), "approved Job planner is missing")
        value = draft("threshold")
        value.update(content_item_id="idea-01", source_text=content_fixture.SOURCE_TEXT)
        with self.assertRaises(content_analysis.ContentAnalysisError):
            module.plan_motion_for_job(fixture.job, value)
        state.approve(fixture.job, "content_analysis")
        before = {str(p): p.read_bytes() for p in fixture.job.job_dir.rglob("*") if p.is_file()}
        report = module.plan_motion_for_job(fixture.job, value)
        self.assertEqual(report["content_analysis_sha256"], record["analysis_sha256"])
        after = {str(p): p.read_bytes() for p in fixture.job.job_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        # A stale in-memory approval must not bypass a later revision on disk.
        fresh = state.load_job(fixture.job.job_dir)
        state.revise(fresh, "content_analysis", "test revision")
        with self.assertRaises(content_analysis.ContentAnalysisError):
            module.plan_motion_for_job(fixture.job, value)


if __name__ == "__main__":
    unittest.main()

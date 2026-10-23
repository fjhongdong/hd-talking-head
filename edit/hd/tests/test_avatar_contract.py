"""Formal plan and compositor must consume the current avatar calibration."""
import importlib.util
import copy
from pathlib import Path
import unittest

from edit.hd.tools import segment_render

_spec = importlib.util.spec_from_file_location(
    "avatar_test_fixtures",
    Path(__file__).resolve().parents[3]
    / "skill-development/hd-talking-head/tests/test_avatar_profile.py",
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
avatar_fixture = _fixtures.avatar_fixture


class AvatarContractTests(unittest.TestCase):
    def test_formal_plan_accepts_current_calibration_and_rejects_missing_or_wrong_source(self):
        from edit.hd.tests.test_visual_plan import valid_plan
        from edit.hd.tools import visual_plan, contract_artifacts
        value = valid_plan()
        for key in ("visual_strategy", "shot_recipe"):
            value["segments"][0][key]["composition"]["avatar"] = avatar_fixture(frames=72)
        def rehash(plan):
            plan["visual_plan_sha256"] = contract_artifacts.sha256_json(
                {k: v for k, v in plan.items() if k != "visual_plan_sha256"}
            )
        rehash(value)
        self.assertEqual(visual_plan.validate_visual_plan(value), value)
        for missing in (True, False):
            broken = copy.deepcopy(value)
            for key in ("visual_strategy", "shot_recipe"):
                comp = broken["segments"][0][key]["composition"]
                if missing:
                    del comp["avatar"]
                else:
                    comp["avatar"]["profile"]["source_sha256"] = "f" * 64
            rehash(broken)
            with self.assertRaisesRegex(visual_plan.VisualPlanError, "avatar"):
                visual_plan.validate_visual_plan(broken)

    def test_generation_rejects_avatar_bound_to_a_different_aroll(self):
        from types import SimpleNamespace
        job = SimpleNamespace(job_id="synthetic-test")
        segment = {"start": 0, "end": 1, "shot_recipe": {"composition": {
            "presenter_mode": "bottom_window", "avatar": avatar_fixture()}}}
        arroll = segment_render._ApprovedArroll("source.mp4", "e" * 64, 100)
        with self.assertRaisesRegex(segment_render.SegmentRenderError, "avatar"):
            segment_render.generation_identity(job, segment, "f" * 64, (), arroll)

    def test_compositor_rejects_unconfigured_bottom_window(self):
        with self.assertRaisesRegex(segment_render.SegmentRenderError, "avatar"):
            segment_render.build_filter_graph(
                {"components": [], "composition": {"presenter_mode": "bottom_window"}},
                (), frames=24,
            )

    def test_compositor_uses_explicit_crop_and_placement(self):
        avatar = avatar_fixture(x=0)
        avatar["position"] = {"x": 40, "y": 1380}
        graph = segment_render.build_filter_graph(
            {"components": [], "composition": {
                "presenter_mode": "bottom_window", "avatar": avatar}}, (), frames=24,
        )
        self.assertIn("overlay=40:1380", graph)
        self.assertIn("hypot", graph)
        self.assertNotIn("960:960:60:480", graph)
        self.assertNotIn("pad=360:540", graph)


if __name__ == "__main__":
    unittest.main()

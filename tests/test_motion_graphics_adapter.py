"""Offline brief-contract regression for the motion graphics adapter."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import _env  # noqa: F401

SKILL = _env.SKILL
sys.path.insert(0, str(SKILL / "scripts"))

spec = importlib.util.spec_from_file_location(
    "motion_graphics_adapter", SKILL / "scripts/motion_graphics_adapter.py")
mga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mga)


def brief(family="lower_third"):
    data = {
        "lower_third": {"name": "李明", "role": "首席科学家", "org": "智源研究院"},
        "callout_pin": {"target_desc": "图表第三列的数据", "label": "关键增量", "direction": "up"},
        "logo_sting": {"mark_text": "AI课", "headline": "看懂AI不用慌", "cta": "关注更新"},
    }[family]
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-mg-1",
                           "start": 0.0, "end": 4.0},
        "template_request": {"semantic_family": family,
                             "information_units": 3, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"id": "mg-lower-1", "width": 1080, "height": 1920,
                        "fps": 24, "frames": 96, "alpha": True},
        "entry": {"job_path": "motion-graphics/lower-third-1.html", "sha256": "b" * 64},
        "assets": [],
        "data": data,
    }


class MotionGraphicsBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            mga.validate_brief(json.dumps(payload))

    def test_valid_lower_third(self):
        checked = mga.validate_brief(json.dumps(brief("lower_third")))
        self.assertEqual(checked["data"]["name"], "李明")

    def test_valid_callout_pin(self):
        checked = mga.validate_brief(json.dumps(brief("callout_pin")))
        self.assertEqual(checked["data"]["direction"], "up")

    def test_valid_logo_sting(self):
        checked = mga.validate_brief(json.dumps(brief("logo_sting")))
        self.assertEqual(checked["data"]["mark_text"], "AI课")

    def test_rejects_unknown_family(self):
        self.check(lambda b: b["template_request"].__setitem__("semantic_family", "keyword"),
                   "family")

    def test_rejects_bad_clock(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 50),
                   "composition clock")

    def test_rejects_alpha_false(self):
        self.check(lambda b: b["composition"].__setitem__("alpha", False),
                   "composition clock")

    def test_rejects_absolute_entry_path(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "/tmp/graphic.html"),
                   "Job-relative HTML")

    def test_rejects_non_html_entry(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "motion-graphics/graphic.js"),
                   "Job-relative HTML")

    def test_rejects_nonempty_assets(self):
        self.check(lambda b: b.__setitem__("assets", [{"media_ref": "x"}]),
                   "assets must be empty")

    def test_rejects_overlong_name(self):
        self.check(lambda b: b["data"].__setitem__("name", "超过八个字符的名字一定不行"),
                   "name")

    def test_rejects_bad_direction(self):
        payload = brief("callout_pin")
        payload["data"]["direction"] = "diagonal"
        with self.assertRaisesRegex(ValueError, "direction"):
            mga.validate_brief(json.dumps(payload))

    def test_rejects_wrong_data_slots(self):
        self.check(lambda b: b["data"].__setitem__("extra", "x"), "data slots")

    def test_runtime_probe(self):
        if not _env.EDIT_HD_AVAILABLE:
            self.skipTest("runtime unavailable")
        rt = mga.check_runtime(_env.PROJECT)
        self.assertIn("identity", rt)


if __name__ == "__main__":
    unittest.main()

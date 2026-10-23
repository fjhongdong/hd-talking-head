"""Offline brief-contract regression for the Adu native adapter; no rendering."""
import copy
import json
import unittest

import _env  # noqa: F401
import adu_native_adapter as adapter


def brief():
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-adu-1",
                           "start": 0.0, "end": 10.0},
        "template_request": {"semantic_family": "old_new_comparison",
                             "information_units": 2, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"id": "adu-1", "width": 1080, "height": 1920, "fps": 24,
                        "frames": 240},
        "title": "对比结论",
        "left": {"title": "旧方案", "items": ["手工粘贴"]},
        "right": {"title": "新方案", "items": ["自动汇总"]},
        "left_frame": 24, "right_frame": 48, "strike_frame": 72,
        "stamp": "验证",
    }


class AduNativeBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["composition"]["frames"], 240)

    def test_rejects_wrong_semantic_family(self):
        self.check(lambda b: b["template_request"].__setitem__("semantic_family", "other"),
                   "Invalid Adu native brief|template request")

    def test_rejects_bad_source_sha(self):
        self.check(lambda b: b["source_binding"].__setitem__("aroll_sha256", "z" * 64),
                   "Invalid Adu source binding")

    def test_rejects_backwards_window(self):
        self.check(lambda b: b["source_binding"].update(start=5.0, end=5.0),
                   "Invalid Adu source binding")

    def test_rejects_clock_mismatch(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 100),
                   "Invalid Adu composition clock")

    def test_rejects_frames_out_of_native_range(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 6000),
                   "Invalid Adu composition clock")

    def test_rejects_item_count_diverging_from_request(self):
        self.check(lambda b: b["left"]["items"].append("多一项"),
                   "Adu item count differs from the request")

    def test_rejects_unsorted_action_frames(self):
        self.check(lambda b: b.update(left_frame=72, strike_frame=48),
                   "Adu native actions do not fit the voice window")

    def test_rejects_strike_too_close_to_end(self):
        self.check(lambda b: b.update(strike_frame=220),
                   "Adu native actions do not fit the voice window")

    def test_rejects_overlong_side_title(self):
        self.check(lambda b: b["left"].__setitem__("title", "超过八字的上限标题"),
                   "side title")


if __name__ == "__main__":
    unittest.main()

"""Offline brief-contract regression for the Hypit native chat adapter."""
import json
import unittest

import _env  # noqa: F401
import hypit_native_adapter as adapter


def brief():
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-hypit-1",
                           "start": 0.0, "end": 5.0},
        "template_request": {"semantic_family": "plan_change_dialogue",
                             "information_units": 2, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"id": "hypit-1", "width": 1080, "height": 1920, "fps": 24,
                        "frames": 120},
        "title": "计划改变",
        "messages": [
            {"sender": "用户", "text": "把上线时间提前", "side": "left", "frame": 12},
            {"sender": "助手", "text": "好的已重新排期", "side": "right", "frame": 36},
        ],
    }


class HypitNativeBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(len(checked["messages"]), 2)

    def test_rejects_wrong_semantic_family(self):
        self.check(lambda b: b["template_request"].__setitem__(
            "semantic_family", "old_new_comparison"), "template request")

    def test_rejects_message_count_diverging_from_units(self):
        self.check(lambda b: b["messages"].pop(), "2-4 messages")

    def test_rejects_bad_message_side(self):
        self.check(lambda b: b["messages"][0].__setitem__("side", "center"),
                   "side/frame")

    def test_rejects_unsorted_arrival_frames(self):
        self.check(lambda b: b["messages"][0].__setitem__("frame", 60),
                   "do not fit the voice window")

    def test_rejects_last_arrival_too_close_to_end(self):
        self.check(lambda b: b["messages"][1].__setitem__("frame", 110),
                   "do not fit the voice window")

    def test_rejects_overlong_title(self):
        self.check(lambda b: b.__setitem__("title", "超过十四个字符的标题一定会失败"),
                   "title")

    def test_rejects_frames_out_of_native_range(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 90),
                   "composition clock")


if __name__ == "__main__":
    unittest.main()

"""Offline brief-contract regression for the Wise motion adapter."""
import json
import unittest

import _env  # noqa: F401
import wise_motion_adapter as adapter


def brief():
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-wise-1",
                           "start": 0.0, "end": 5.0},
        "template_request": {"semantic_family": "continuous_tracking",
                             "information_units": 3, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"id": "wise-1", "width": 1080, "height": 1920, "fps": 24,
                        "frames": 120},
        "theme": "light",
        "title": "追踪结论",
        "context_labels": ["阶段一", "阶段二", "阶段三"],
        "layers": [{"id": "orbit", "content": {}, "speed": 1.0, "from": 0,
                    "transparent": False,
                    "layout": {"x": 220, "y": 300, "width": 640, "height": 360}}],
    }


class WiseMotionBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["layers"][0]["speed"], 1.0)

    def test_rejects_dark_theme(self):
        self.check(lambda b: b.__setitem__("theme", "dark"), "Invalid Wise brief")

    def test_rejects_wrong_template_request_shape(self):
        self.check(lambda b: b["template_request"].__setitem__(
            "information_units", 2), "Invalid template request")

    def test_rejects_overlong_title(self):
        self.check(lambda b: b.__setitem__("title", "超过十个字符的标题要失败"),
                   "Invalid tracking title")

    def test_rejects_wrong_label_count(self):
        self.check(lambda b: b["context_labels"].pop(), "Invalid context labels")

    def test_rejects_second_layer(self):
        self.check(lambda b: b["layers"].append(copy_of_first_layer()),
                   "Use one native tracking layer")

    def test_rejects_speed_out_of_range(self):
        self.check(lambda b: b["layers"][0].__setitem__("speed", 3.0),
                   "Invalid native orbit layer")

    def test_rejects_wrong_layout_ratio(self):
        self.check(lambda b: b["layers"][0]["layout"].update(width=600, height=400),
                   "Invalid layout")

    def test_rejects_clock_mismatch(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 100),
                   "Composition clock mismatch")


def copy_of_first_layer():
    return {"id": "orbit", "content": {}, "speed": 1.0, "from": 0,
            "transparent": False,
            "layout": {"x": 220, "y": 700, "width": 640, "height": 360}}


if __name__ == "__main__":
    unittest.main()

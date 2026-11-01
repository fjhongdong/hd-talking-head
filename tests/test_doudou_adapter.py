"""Offline brief-contract regression for the Doudou adapter; no rendering."""
import json
import unittest

import _env  # noqa: F401
import doudou_adapter as adapter


def brief():
    return {
        "schema_version": 2,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-doudou-1",
                           "start": 0.0, "end": 5.0},
        "template_request": {"semantic_family": "mechanism_system",
                             "information_units": 3, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "entry": {"job_path": "doudou/scene.tsx", "sha256": "b" * 64},
        "hand": {"job_path": "doudou/hand.png", "sha256": "c" * 64,
                 "width": 512, "height": 512, "tip_x": 256.0, "tip_y": 256.0},
        "composition": {"id": "doudou-1", "width": 1080, "height": 1920, "fps": 24,
                        "frames": 120},
    }


class DoudouBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["hand"]["width"], 512)

    def test_rejects_wrong_schema(self):
        self.check(lambda b: b.__setitem__("schema_version", 1), "Invalid Doudou brief")

    def test_rejects_absolute_entry_path(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "/tmp/scene.tsx"),
                   "frozen Job-relative")

    def test_rejects_entry_without_tsx_suffix(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "doudou/scene.js"),
                   "frozen Job-relative")

    def test_rejects_quantitative_request(self):
        self.check(lambda b: b["template_request"].update(
            numeric_values=[1, 2], numeric_scale="linear"),
            "nonquantitative")

    def test_rejects_hand_tip_outside_bitmap(self):
        self.check(lambda b: b["hand"].__setitem__("tip_x", 999.0),
                   "frozen Job-relative RGBA PNG")

    def test_rejects_clock_mismatch(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 90),
                   "composition clock")


if __name__ == "__main__":
    unittest.main()

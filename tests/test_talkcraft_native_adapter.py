"""Offline brief-contract regression for the TalkCraft native adapter."""
import json
import unittest

import _env  # noqa: F401
import talkcraft_native_adapter as adapter


def brief():
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-tc-1",
                           "start": 0.0, "end": 5.0},
        "template_request": {"semantic_family": "numeric_emphasis",
                             "information_units": 1, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "entry": {"job_path": "talkcraft/card.tsx", "sha256": "b" * 64},
        "composition": {"id": "tc-1", "width": 1080, "height": 1920, "fps": 24,
                        "frames": 120},
    }


class TalkCraftNativeBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["entry"]["job_path"], "talkcraft/card.tsx")

    def test_valid_quantitative_variant_round_trips(self):
        payload = brief()
        payload["template_request"].update(numeric_values=[3.5],
                                           numeric_scale="linear")
        checked = adapter.validate_brief(json.dumps(payload))
        self.assertEqual(checked["template_request"]["numeric_scale"], "linear")

    def test_rejects_values_without_linear_scale(self):
        self.check(lambda b: b["template_request"].update(
            numeric_values=[3.5], numeric_scale="not_applicable"),
            "finite values and an explicit linear numeric scale")

    def test_rejects_log_scale(self):
        self.check(lambda b: b["template_request"].update(
            numeric_values=[3.5], numeric_scale="log"),
            "finite values and an explicit linear numeric scale")

    def test_rejects_entry_sha_mismatch_shape(self):
        self.check(lambda b: b["entry"].__setitem__("sha256", "not-hex"),
                   "frozen Job-relative adapted TSX")

    def test_rejects_escaping_entry_path(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "../card.tsx"),
                   "frozen Job-relative adapted TSX")

    def test_rejects_clock_mismatch(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 100),
                   "composition clock")


if __name__ == "__main__":
    unittest.main()

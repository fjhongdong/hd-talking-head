"""Brief and real glyph-guard regressions for Adu; no video export."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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
        "typography": {"title_px": 64, "body_px": 56},
    }


class AduNativeBriefTests(unittest.TestCase):
    def test_frozen_entry_rejects_real_glyph_collision_before_capture(self):
        project = Path(__file__).resolve().parents[3]
        native = adapter.create_adapter(project, shutil.which('node'), lambda *_: b'')
        payload = brief()
        payload['typography'] = {'title_px': 80, 'body_px': 60}
        payload['left'] = {'title': '独家秘籍', 'items': ['藏提示词']}
        payload['right'] = {'title': '制作过程', 'items': ['公开']}
        adapter.validate_brief(json.dumps(payload))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'approved-entrypoint.mjs'
            entry.write_bytes((adapter.SKILL / adapter.ENTRY).read_bytes())
            source = root / 'brief.json'
            source.write_text(json.dumps(payload))
            output = root / 'should-not-exist.mp4'
            values = {'launcher': str(native.launcher), 'entrypoint': str(entry),
                      'brief_path': str(source), 'output_path': str(output)}
            result = subprocess.run([argument.format(**values) for argument in native.argv_template],
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('overlapping glyphs', result.stdout + result.stderr)
            self.assertFalse(output.exists())

    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["composition"]["frames"], 240)
        self.assertEqual(checked["typography"], {"title_px": 64, "body_px": 56})

    def test_empty_stamp_disables_optional_native_stamp(self):
        payload = brief()
        payload["stamp"] = ""
        payload["right"]["title"] = "转向能力优先"
        self.assertEqual(adapter.validate_brief(json.dumps(payload)), payload)

    def test_optional_stamp_keeps_text_validation(self):
        for value in (None, False, 0, " ", "转向转向转", "<章>", "转\n向"):
            with self.subTest(value=value):
                self.check(lambda b: b.__setitem__("stamp", value), "Invalid Adu stamp")
        for field in ("title", "left", "right"):
            payload = brief()
            payload["stamp"] = ""
            if field == "title":
                payload[field] = ""
            else:
                payload[field]["title"] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter.validate_brief(json.dumps(payload))

    def test_portrait_typography_accepts_four_character_labels(self):
        payload = brief()
        payload["typography"] = {"title_px": 64, "body_px": 56}
        checked = adapter.validate_brief(json.dumps(payload))
        self.assertEqual(checked["typography"]["body_px"], 56)

    def test_accepts_openai_title_at_real_native_geometry_size(self):
        payload = brief()
        payload["typography"] = {"title_px": 64, "body_px": 48}
        payload["left"]["title"] = "OpenAI"
        checked = adapter.validate_brief(json.dumps(payload))
        self.assertEqual(checked["left"]["title"], "OpenAI")

    def test_portrait_typography_rejects_overlong_label(self):
        payload = brief()
        payload["typography"] = {"title_px": 64, "body_px": 56}
        payload["right"]["items"] = ["这是七个字标签"]
        with self.assertRaisesRegex(ValueError, "typography body capacity"):
            adapter.validate_brief(json.dumps(payload))

    def test_portrait_typography_rejects_multiple_rows_at_large_body_size(self):
        payload = brief()
        payload["left"]["items"] = ["一行", "二行"]
        payload["template_request"]["information_units"] = 3
        with self.assertRaisesRegex(ValueError, "body line capacity"):
            adapter.validate_brief(json.dumps(payload))

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

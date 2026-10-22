"""Offline brief-contract regression for the OpenFilm adapter; no Studio calls."""
import json
import unittest

import _env  # noqa: F401
import openfilm_motion_adapter as adapter


def brief():
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-film-1",
                           "start": 0.0, "end": 4.0},
        "template_request": {"semantic_family": "object_operation",
                             "information_units": 1, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 96,
                        "alpha": False},
        "entry": {"media_ref": "index.html", "job_path": "openfilm/index.html",
                  "scene_path": "index.html", "sha256": "b" * 64},
        "assets": [{"media_ref": "icon.png", "job_path": "openfilm/icon.png",
                    "scene_path": "assets/icon.png", "sha256": "c" * 64}],
        "upstream": {"package_version": "0.2.4", "skill_sha256": "d" * 64,
                     "manual_sha256": "e" * 64},
        "creative_handoff": {
            "transcript": "本期原声对应句", "semantic_goal": "表现装配动作",
            "required_change": "零件合为一体", "subject": "核心零件",
            "visual_pattern": "拾取并放置", "style_reason": "与相邻镜头区隔",
            "beats": [{"start_frame": 0, "end_frame": 48, "spoken_anchor": "装上",
                       "before": "散落", "action": "吸附", "after": "成体"}],
            "forbidden_outcomes": ["提前出现成果"],
        },
    }


class OpenFilmBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            adapter.validate_brief(json.dumps(payload))

    def test_valid_brief_round_trips(self):
        checked = adapter.validate_brief(json.dumps(brief()))
        self.assertEqual(checked["composition"]["alpha"], False)

    def test_rejects_alpha_composition(self):
        self.check(lambda b: b["composition"].__setitem__("alpha", True),
                   "Invalid OpenFilm composition")

    def test_rejects_numeric_values_without_scale(self):
        self.check(lambda b: b["template_request"].update(
            numeric_values=[3], numeric_scale="not_applicable"),
            "Numeric values require a scale")

    def test_rejects_entry_other_than_index_html(self):
        self.check(lambda b: b["entry"].__setitem__("scene_path", "src/scene.tsx"),
                   "entry must be index.html")

    def test_rejects_absolute_job_path(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "/tmp/scene.tsx"),
                   "Invalid OpenFilm asset path")

    def test_rejects_repeated_media_ref(self):
        self.check(lambda b: b["assets"][0].__setitem__("media_ref", "index.html"),
                   "Repeated OpenFilm media or scene path")

    def test_rejects_unordered_beats(self):
        def swap(b):
            hand = b["creative_handoff"]
            hand["beats"] = [
                {"start_frame": 48, "end_frame": 96, "spoken_anchor": "成体",
                 "before": "合拢", "action": "定格", "after": "结论"},
                {"start_frame": 0, "end_frame": 48, "spoken_anchor": "装上",
                 "before": "散落", "action": "吸附", "after": "成体"}]
        self.check(swap, "Invalid OpenFilm beat range")

    def test_rejects_wrong_upstream_version(self):
        self.check(lambda b: b["upstream"].__setitem__("package_version", "0.0.0"),
                   "Invalid OpenFilm upstream identity")

    def test_rejects_exceeding_frozen_file_limit(self):
        def add_seven(b):
            for i in range(7):
                b["assets"].append({"media_ref": f"extra{i}.png",
                                    "job_path": f"openfilm/extra{i}.png",
                                    "scene_path": f"assets/extra{i}.png",
                                    "sha256": "f" * 64})
        self.check(add_seven, "eight frozen-file limit")

    def test_rejects_clock_mismatch(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 50),
                   "Invalid OpenFilm composition")

    def test_accepts_dict_payload_too(self):
        checked = adapter.validate_brief(brief())
        self.assertEqual(checked["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()

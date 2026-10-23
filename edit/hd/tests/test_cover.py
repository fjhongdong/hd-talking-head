from __future__ import annotations

import copy
import base64
import hashlib
import importlib
import inspect
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


def _png(
    size: tuple[int, int] = (1024, 1536),
    color: tuple[int, int, int] = (236, 232, 222),
) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def _brief(face_sha256: str = "a" * 64) -> dict[str, object]:
    return {
        "version": 1,
        "generator": "gbro-cover-design",
        "title": "智能工作流",
        "subtitle": "",
        "style_id": "style-07",
        "base_generation": "scene_only_no_people_no_text",
        "face_frame": {
            "source": "current-aroll-video",
            "timestamp": 0.75,
            "sha256": face_sha256,
        },
        "rounds": {
            "style_and_title": {
                "selection": "style-07",
                "title": "智能工作流",
                "reason": "知识口播需要大面积标题留白",
            },
            "references": {
                "face_source": "current-aroll-video",
                "extras": [],
            },
            "visual_details": {
                "person_side": "left",
                "person_width_ratio": 0.30,
                "blank_width_ratio": 0.65,
                "expression": "confident",
                "background": "warm-neutral",
                "font_style": "heavy-sans",
                "font_color": "#171717",
                "safe_margin_ratio": 0.10,
            },
        },
        "base_prompt": (
            "3:4 portrait composition. Create a clean warm-neutral editorial scene "
            "background with calm depth. Reserve the left side for a local foreground "
            "composite occupying 30 percent. Preserve 10 percent safe margins. "
            "No people. No text. No letters. No words. No typography. No captions. "
            "No logos. No watermarks."
        ),
        "person_composite": {
            "source": "current-aroll-video",
            "method": "local-foreground-cutout",
            "side": "left",
            "person_width_ratio": 0.30,
        },
        "text_layer": {
            "engine": "Pillow",
            "side": "right",
            "font_style": "heavy-sans",
            "color": "#171717",
            "safe_margin_ratio": 0.10,
        },
    }


def _impact_brief(face_sha256: str = "a" * 64) -> dict[str, object]:
    brief = _brief(face_sha256)
    brief.update({
        "title": "真正淘汰你的",
        "style_id": "style-01",
        "headline": {
            "primary": "真正淘汰你的",
            "highlight": "不是AI模型",
            "conclusion": "而是旧工作流",
        },
        "base_prompt": (
            "3:4 portrait composition. Create a clean dark-ai-workflow-studio "
            "editorial scene background with calm depth. Reserve the right side for "
            "a local foreground composite occupying 55 percent. Preserve 10 percent "
            "safe margins. No people. No text. No letters. No words. No typography. "
            "No captions. No logos. No watermarks."
        ),
        "person_composite": {
            "source": "current-aroll-video",
            "method": "local-foreground-cutout",
            "side": "right",
            "person_width_ratio": 0.55,
        },
        "text_layer": {
            "engine": "Pillow",
            "side": "left",
            "font_style": "heavy-sans",
            "color": "#FFFFFF",
            "safe_margin_ratio": 0.10,
        },
    })
    brief["rounds"]["style_and_title"].update({
        "selection": "style-01",
        "title": "真正淘汰你的",
        "reason": "爆款科技封面需要深色高对比和强标题层级",
    })
    brief["rounds"]["visual_details"].update({
        "person_side": "right",
        "person_width_ratio": 0.55,
        "blank_width_ratio": 0.35,
        "expression": "confident-direct",
        "background": "dark-ai-workflow-studio",
        "font_color": "#FFFFFF",
    })
    return brief


def _ready_cover_job(root: Path, *, approve_subtitles: bool = True):
    from edit.hd.tests.test_subtitles import _canonical, _ready_job
    from edit.hd.tools import state

    job, _track = _ready_job(root)
    subtitles = job.job_dir / "06-subtitles"
    subtitles.mkdir()
    _canonical(
        subtitles / "subtitle-plan.json",
        {
            "version": 1,
            "canvas": {
                "width": 1080, "height": 1920, "fps": 24,
                "frames": 48, "duration": 2.0,
            },
        },
    )
    (subtitles / "subtitles.webm").write_bytes(b"strict-subtitle-overlay")
    (subtitles / "subtitles.srt").write_text(
        "1\n00:00:00,100 --> 00:00:01,900\n智能工作流\n", encoding="utf-8"
    )
    (subtitles / "contact-sheet.png").write_bytes(_png((320, 180)))
    state.mark_ready(job, "subtitles", sorted(subtitles.iterdir()))
    if approve_subtitles:
        state.approve(job, "subtitles")
    return job


def _provider_response() -> dict[str, object]:
    return {"data": [{"b64_json": base64.b64encode(_png()).decode("ascii")}]}


def _face_setup():
    source = _png((320, 480), (60, 90, 120))
    candidates = [{
        "timestamp": 0.75,
        "eyes_closed": False,
        "blur_score": 80.0,
        "overexposed_ratio": 0.03,
        "face_ratio": 0.20,
        "score": 10.0,
    }]
    return source, candidates


def _quality_probe(candidates):
    measurements = {
        key: value for key, value in candidates[0].items() if key != "timestamp"
    }
    return lambda _source: copy.deepcopy(measurements)


def _person_mask(source: bytes) -> bytes:
    with Image.open(io.BytesIO(source)) as image:
        mask = Image.new("L", image.size, 0)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(mask)
        draw.ellipse((image.width // 8, 0, image.width * 7 // 8, image.height), fill=255)
        stream = io.BytesIO()
        mask.save(stream, format="PNG")
        return stream.getvalue()


class CoverBriefContractTests(unittest.TestCase):
    def test_module_exposes_minimal_public_api(self) -> None:
        module = importlib.import_module("edit.hd.tools.cover")
        self.assertEqual(
            module.__all__,
            [
                "CoverError",
                "validate_cover_brief",
                "select_face_frame",
                "render_cover_base",
                "render_local_text",
                "prepare_cover",
            ],
        )

    def test_valid_style_seven_brief_preserves_three_automatic_rounds(self) -> None:
        from edit.hd.tools import cover

        checked = cover.validate_cover_brief(_brief(), expected_face_sha256="a" * 64)
        self.assertEqual(checked["generator"], "gbro-cover-design")
        self.assertEqual(checked["style_id"], "style-07")
        self.assertEqual(set(checked["rounds"]), {
            "style_and_title", "references", "visual_details",
        })
        self.assertEqual(checked["base_generation"], "scene_only_no_people_no_text")
        self.assertEqual(checked["person_composite"]["method"], "local-foreground-cutout")

    def test_reference_scene_brief_requires_exact_scene_binding(self) -> None:
        from edit.hd.tools import cover

        brief = _impact_brief()
        brief["base_generation"] = "reference_person_scene_no_text"
        brief["person_composite"]["method"] = "generated-reference-person"
        brief["reference_scene"] = {"sha256": "b" * 64, "bytes": 1234}

        checked = cover.validate_cover_brief(brief)

        self.assertEqual(checked["reference_scene"], {
            "sha256": "b" * 64,
            "bytes": 1234,
        })
        for field, value in (("sha256", "not-a-sha"), ("bytes", True), ("bytes", 0)):
            broken = copy.deepcopy(brief)
            broken["reference_scene"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(broken)

    def test_9x16_reference_scene_requires_approved_person_protection_boxes(self) -> None:
        from edit.hd.tools import cover

        brief = _impact_brief()
        brief["output_aspect_ratio"] = "9:16"
        brief["base_generation"] = "reference_person_scene_no_text"
        brief["person_composite"]["method"] = "generated-reference-person"
        brief["reference_scene"] = {"sha256": "b" * 64, "bytes": 1234}

        with self.assertRaises(cover.CoverError):
            cover.validate_cover_brief(brief)

        brief["person_protection_boxes"] = [
            [0.58, 0.29, 0.94, 0.55],
            [0.34, 0.50, 0.94, 0.95],
        ]
        checked = cover.validate_cover_brief(brief)
        self.assertEqual(
            checked["person_protection_boxes"],
            brief["person_protection_boxes"],
        )

    def test_rejects_unknown_generator_chinese_prompt_and_face_sha_mismatch(self) -> None:
        from edit.hd.tools import cover

        mutations = []
        unknown = copy.deepcopy(_brief())
        unknown["generator"] = "other"
        mutations.append(unknown)
        chinese = copy.deepcopy(_brief())
        chinese["base_prompt"] = "3:4 portrait composition. 不要生成文字"
        mutations.append(chinese)
        wrong_face = copy.deepcopy(_brief())
        wrong_face["face_frame"]["sha256"] = "b" * 64
        mutations.append(wrong_face)
        for payload in mutations:
            with self.subTest(payload=payload), self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(payload, expected_face_sha256="a" * 64)

    def test_prompt_is_strict_ascii_and_requires_each_no_people_no_text_clause(self) -> None:
        from edit.hd.tools import cover

        prompts = [
            "3:4 portrait composition. No people. No text. Café background.",
            "3:4 portrait composition. No sunlight. Typography everywhere. No people.",
            "3:4 portrait composition. No people. No text. No logos.",
            (
                "3:4 portrait composition. Generate giant typography and a person. "
                "No people. No text. No letters. No words. No typography. No captions. "
                "No logos. No watermarks."
            ),
        ]
        for prompt in prompts:
            payload = copy.deepcopy(_brief())
            payload["base_prompt"] = prompt
            with self.subTest(prompt=prompt), self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(payload)

    def test_brief_timestamp_must_match_selected_face_timestamp_exactly(self) -> None:
        from edit.hd.tools import cover

        with self.assertRaises(cover.CoverError):
            cover.validate_cover_brief(
                _brief(), expected_face_sha256="a" * 64,
                expected_face_timestamp=0.750001,
            )

    def test_title_is_four_to_eight_unicode_han_characters_only(self) -> None:
        from edit.hd.tools import cover

        for title in ("三个字", "1234", "AI工作流", "九个中文字真的超长了"):
            payload = copy.deepcopy(_brief())
            payload["title"] = title
            payload["rounds"]["style_and_title"]["title"] = title
            with self.subTest(title=title), self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(payload)
        for title in ("四字标题", "八个中文字刚刚好", "𠀀𠀁𠀂𠀃"):
            payload = copy.deepcopy(_brief())
            payload["title"] = title
            payload["rounds"]["style_and_title"]["title"] = title
            self.assertEqual(cover.validate_cover_brief(payload)["title"], title)

    def test_unsupported_font_style_is_rejected_instead_of_silently_ignored(self) -> None:
        from edit.hd.tools import cover

        payload = copy.deepcopy(_brief())
        payload["rounds"]["visual_details"]["font_style"] = "serif"
        payload["text_layer"]["font_style"] = "serif"
        with self.assertRaises(cover.CoverError):
            cover.validate_cover_brief(payload)

    def test_rejects_unknown_style_extra_keys_bool_and_invalid_style_seven_geometry(self) -> None:
        from edit.hd.tools import cover

        mutations = []
        style = copy.deepcopy(_brief())
        style["style_id"] = "style-11"
        mutations.append(style)
        extra = copy.deepcopy(_brief())
        extra["extra"] = True
        mutations.append(extra)
        boolean = copy.deepcopy(_brief())
        boolean["rounds"]["visual_details"]["person_width_ratio"] = True
        mutations.append(boolean)
        person = copy.deepcopy(_brief())
        person["rounds"]["visual_details"]["person_width_ratio"] = 0.36
        mutations.append(person)
        blank = copy.deepcopy(_brief())
        blank["rounds"]["visual_details"]["blank_width_ratio"] = 0.59
        mutations.append(blank)
        margin = copy.deepcopy(_brief())
        margin["text_layer"]["safe_margin_ratio"] = 0.09
        mutations.append(margin)
        for payload in mutations:
            with self.subTest(payload=payload), self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(payload)


class CoverFaceAndRenderTests(unittest.TestCase):
    def test_style_seven_portrait_renders_approved_copy_and_rejects_face_overlap(self):
        from edit.hd.tools import cover

        brief = _brief()
        brief["output_aspect_ratio"] = "9:16"
        brief["title"] = "真正淘汰你的"
        brief["subtitle"] = "根本不是AI模型"
        brief["person_composite"]["side"] = "right"
        brief["person_protection_boxes"] = [[0.58, 0.35, 0.95, 0.90]]
        image = cover._render_one(Image.new("RGB", (1080, 1920), "#1D2631"), brief, (1080, 1920))
        self.assertEqual(image.size, (1080, 1920))
        self.assertTrue(any(
            pixel[0] > 240 and pixel[1] > 180 and pixel[2] < 30
            for pixel in image.crop((100, 200, 900, 700)).getdata()
        ))

        brief["person_protection_boxes"] = [[0.10, 0.08, 0.95, 0.38]]
        with self.assertRaises(cover.CoverError):
            cover._render_one(Image.new("RGB", (1080, 1920), "#1D2631"), brief, (1080, 1920))

    def test_style_seven_portrait_preserves_three_tier_preview_copy(self):
        from edit.hd.tools import cover

        brief = _brief()
        brief.update({
            "output_aspect_ratio": "9:16",
            "title": "真正淘汰你的",
            "subtitle": "根本不是AI模型",
            "support_line": "认知 · 经验 · 工作流",
        })
        brief["person_composite"]["side"] = "right"
        brief["rounds"]["visual_details"]["person_side"] = "right"
        brief["text_layer"]["side"] = "left"
        brief["text_layer"]["safe_margin_ratio"] = 0.04
        brief["rounds"]["visual_details"]["safe_margin_ratio"] = 0.04
        brief["rounds"]["style_and_title"]["title"] = brief["title"]
        brief["base_prompt"] = (
            brief["base_prompt"].replace("left side", "right side")
            .replace("10 percent safe margins", "4 percent safe margins")
        )
        checked = cover.validate_cover_brief(brief)
        self.assertEqual(checked["support_line"], "认知 · 经验 · 工作流")
        checked["person_protection_boxes"] = [[0.53, 0.30, 0.99, 0.98]]
        base = Image.new("RGB", (1080, 1920), "#1D2631")
        rendered = cover._render_one(base, checked, base.size)
        yellow_band = rendered.crop((800, 265, 1030, 510))
        self.assertTrue(any(
            red > 240 and green > 180 and blue < 40
            for red, green, blue in yellow_band.getdata()
        ))
        support_area = rendered.crop((80, 490, 670, 640))
        self.assertTrue(any(
            red > 235 and green > 235 and blue > 235
            for red, green, blue in support_area.getdata()
        ))
        checked["person_protection_boxes"] = [[0.88, 0.275, 0.99, 0.90]]
        with self.assertRaises(cover.CoverError):
            cover._render_one(base, checked, base.size)

    def test_style_seven_portrait_splits_long_approved_subtitle_or_rejects_it(self):
        from edit.hd.tools import cover

        brief = _brief()
        brief.update({
            "output_aspect_ratio": "9:16",
            "title": "真正淘汰你的",
            "subtitle": "不是模型，是认知与流程",
            "person_protection_boxes": [[0.55, 0.30, 0.99, 0.98]],
        })
        brief["person_composite"]["side"] = "right"
        base = Image.new("RGB", (1080, 1920), "#1D2631")
        rendered = cover._render_one(base, brief, base.size)
        self.assertEqual(rendered.size, (1080, 1920))
        self.assertNotEqual(rendered.getpixel((180, 480)), base.getpixel((180, 480)))

        brief["subtitle"] = "不是模型是认知与流程"
        with self.assertRaises(cover.CoverError):
            cover._render_one(base, brief, base.size)

    def test_impact_headline_layout_keeps_face_clear_and_uses_warning_poster_geometry(self) -> None:
        from edit.hd.tools import cover

        layout = cover._impact_headline_layout((1080, 1440), _impact_brief())

        face_clearance = round(1440 * 0.37)
        self.assertLessEqual(layout["content_bottom"], face_clearance)
        self.assertLessEqual(layout["shade_bottom"], face_clearance)
        self.assertNotEqual(layout["highlight"]["angle"], 0)
        self.assertEqual(layout["highlight"]["radius"], 0)
        self.assertGreaterEqual(layout["highlight"]["box"][0], round(1080 * 0.10))
        self.assertLessEqual(layout["highlight"]["box"][2], round(1080 * 0.90))
        self.assertLessEqual(layout["accent"]["box"][3], face_clearance)

    def test_9x16_impact_layout_uses_two_large_highlights_and_safe_width(self) -> None:
        from edit.hd.tools import cover

        brief = _impact_brief()
        brief["output_aspect_ratio"] = "9:16"
        brief["headline"]["highlight"] = ["根本不是", "AI 模型"]
        brief["headline"]["conclusion"] = ["认知与流程", "才是差距"]
        try:
            checked = cover.validate_cover_brief(brief)
        except cover.CoverError:
            checked = None
        self.assertIsNotNone(checked, "9:16 brief should accept two approved highlight lines")

        protection_boxes = [(880, 600, 972, 1050), (700, 1050, 972, 1800)]
        layout = cover._impact_headline_layout(
            (1080, 1920), checked, person_boxes=protection_boxes,
        )
        self.assertEqual(
            [item["text"] for item in layout["highlights"]],
            ["根本不是", "AI 模型"],
        )
        self.assertGreaterEqual(layout["primary"]["font"].size, 110)
        self.assertGreaterEqual(layout["highlights"][0]["font"].size, 125)
        self.assertGreaterEqual(layout["highlights"][1]["font"].size, 135)
        self.assertGreaterEqual(layout["conclusion"]["font"].size, 78)
        self.assertEqual(
            [item["text"] for item in layout["conclusions"]],
            ["认知与流程", "才是差距"],
        )
        self.assertLessEqual(
            max(item["box"][2] for item in layout["conclusions"]),
            round(1080 * 0.58),
        )
        for item in layout["highlights"]:
            self.assertGreaterEqual(item["box"][0], 108)
            self.assertLessEqual(item["box"][2], 972)
            self.assertFalse(item["panel_shadow"])
        for box in layout["drawn_boxes"]:
            self.assertGreaterEqual(box[0], 108)
            self.assertLessEqual(box[2], 972)
            self.assertGreaterEqual(box[1], 0)
            self.assertLessEqual(box[3], 1920)
            for guard in layout["person_guards"]:
                overlaps = not (
                    box[2] <= guard[0]
                    or guard[2] <= box[0]
                    or box[3] <= guard[1]
                    or guard[3] <= box[1]
                )
                self.assertFalse(overlaps, (box, guard))
        self.assertLessEqual(layout["content_bottom"], round(1920 * 0.41))
        rendered = cover._render_impact_headline(
            Image.new("RGB", (1080, 1920), "#080C16"), checked,
            person_boxes=protection_boxes,
        )
        self.assertEqual(rendered.size, (1080, 1920))

    def test_9x16_impact_layout_accepts_single_approved_lines(self) -> None:
        from edit.hd.tools import cover

        brief = _impact_brief()
        brief["output_aspect_ratio"] = "9:16"
        checked = cover.validate_cover_brief(brief)

        protection_boxes = [(880, 600, 972, 1050), (700, 1050, 972, 1800)]
        layout = cover._impact_headline_layout(
            (1080, 1920), checked, person_boxes=protection_boxes,
        )

        self.assertEqual(
            [item["text"] for item in layout["highlights"]],
            ["不是AI模型"],
        )
        self.assertEqual(
            [item["text"] for item in layout["conclusions"]],
            ["而是旧工作流"],
        )
        self.assertEqual(
            cover._render_impact_headline(
                Image.new("RGB", (1080, 1920), "#080C16"), checked,
                person_boxes=protection_boxes,
            ).size,
            (1080, 1920),
        )

    def test_9x16_render_uses_actual_local_person_box_and_rejects_overlap(self) -> None:
        from edit.hd.tools import cover

        brief = _impact_brief()
        brief["output_aspect_ratio"] = "9:16"
        checked = cover.validate_cover_brief(brief)
        base = Image.new("RGB", (1080, 1920), "#080C16")
        tall_person = Image.new("RGBA", (320, 960), (255, 255, 255, 255))

        with self.assertRaises(cover.CoverError):
            cover._render_one(base, checked, (1080, 1920), tall_person)

        wide_person = Image.new("RGBA", (960, 320), (255, 255, 255, 255))
        self.assertEqual(
            cover._render_one(base, checked, (1080, 1920), wide_person).size,
            (1080, 1920),
        )

    def test_dict_candidate_claims_never_bypass_the_real_quality_probe(self) -> None:
        from edit.hd.tools import cover

        claimed = {"timestamp": 0.5, "eyes_closed": False, "blur_score": 900.0,
                   "overexposed_ratio": 0.0, "face_ratio": 0.2, "score": 99.0}
        measured = {"eyes_closed": True, "blur_score": 900.0,
                    "overexposed_ratio": 0.0, "face_ratio": 0.2, "score": 99.0}
        with self.assertRaises(cover.CoverError):
            cover.select_face_frame(
                Path("/tmp/aroll.mp4"), [claimed],
                frame_reader=lambda *_args: _png((320, 480)),
                quality_probe=lambda _source: measured,
            )

    def test_quality_probe_is_injected_at_detection_boundary_and_drives_selection(self) -> None:
        from edit.hd.tools import cover

        frames = {0.25: _png((320, 480), (25, 25, 25)),
                  0.50: _png((320, 480), (50, 50, 50))}
        probes = []

        def probe(source: bytes):
            probes.append(hashlib.sha256(source).hexdigest())
            if source == frames[0.25]:
                return {"eyes_closed": True, "blur_score": 90.0,
                        "overexposed_ratio": 0.0, "face_ratio": 0.2, "score": 9.0}
            return {"eyes_closed": False, "blur_score": 80.0,
                    "overexposed_ratio": 0.02, "face_ratio": 0.2, "score": 8.0}

        selected = cover.select_face_frame(
            Path("/tmp/aroll.mp4"), [0.25, 0.50],
            frame_reader=lambda _video, timestamp: frames[timestamp],
            quality_probe=probe,
        )
        self.assertEqual(selected["timestamp"], 0.50)
        self.assertEqual(len(probes), 2)

    def test_face_selection_excludes_each_quality_failure_and_chooses_best_valid(self) -> None:
        from edit.hd.tools import cover

        candidates = [
            {"timestamp": 0.1, "eyes_closed": True, "blur_score": 900.0,
             "overexposed_ratio": 0.0, "face_ratio": 0.20, "score": 99.0},
            {"timestamp": 0.2, "eyes_closed": False, "blur_score": 39.9,
             "overexposed_ratio": 0.0, "face_ratio": 0.20, "score": 90.0},
            {"timestamp": 0.3, "eyes_closed": False, "blur_score": 900.0,
             "overexposed_ratio": 0.251, "face_ratio": 0.20, "score": 80.0},
            {"timestamp": 0.4, "eyes_closed": False, "blur_score": 900.0,
             "overexposed_ratio": 0.0, "face_ratio": 0.079, "score": 70.0},
            {"timestamp": 0.5, "eyes_closed": False, "blur_score": 55.0,
             "overexposed_ratio": 0.10, "face_ratio": 0.12, "score": 1.0},
            {"timestamp": 0.6, "eyes_closed": False, "blur_score": 70.0,
             "overexposed_ratio": 0.10, "face_ratio": 0.14, "score": 2.0},
        ]
        frames = {item["timestamp"]: _png((320, 480), (50, int(item["timestamp"] * 100), 80))
                  for item in candidates}
        measured = {
            frames[item["timestamp"]]: {
                key: value for key, value in item.items() if key != "timestamp"
            }
            for item in candidates
        }
        selected = cover.select_face_frame(
            Path("/tmp/aroll.mp4"), candidates,
            frame_reader=lambda _video, timestamp: frames[timestamp],
            quality_probe=lambda source: measured[source],
        )
        self.assertEqual(selected["timestamp"], 0.6)
        self.assertEqual(selected["sha256"], hashlib.sha256(frames[0.6]).hexdigest())
        self.assertEqual(selected["source"], "current-aroll-video")

    def test_face_selection_accepts_exact_boundaries_and_rejects_no_valid_frame(self) -> None:
        from edit.hd.tools import cover

        boundary = {"timestamp": 1.0, "eyes_closed": False, "blur_score": 40.0,
                    "overexposed_ratio": 0.25, "face_ratio": 0.08, "score": 0.0}
        selected = cover.select_face_frame(
            Path("/tmp/aroll.mp4"), [boundary],
            frame_reader=lambda *_args: _png((320, 480)),
            quality_probe=lambda _source: {
                key: value for key, value in boundary.items() if key != "timestamp"
            },
        )
        self.assertEqual(selected["timestamp"], 1.0)
        for key, value in (("eyes_closed", True), ("blur_score", 39.99),
                           ("overexposed_ratio", 0.2501), ("face_ratio", 0.0799)):
            invalid = dict(boundary)
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(cover.CoverError):
                cover.select_face_frame(
                    Path("/tmp/aroll.mp4"), [invalid],
                    frame_reader=lambda *_args: _png((320, 480)),
                    quality_probe=lambda _source, item=invalid: {
                        key: value for key, value in item.items() if key != "timestamp"
                    },
                )

    def test_local_text_outputs_three_bound_sizes_with_real_chinese_pixels(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            base = root / "base.png"
            base.write_bytes(_png())
            outputs = cover.render_local_text(
                base, _brief(), root,
                delivery_size=(720, 1280),
            )
            expected = {
                "cover-3x4.png": (1080, 1440),
                "cover-9x16.png": (1080, 1920),
                "cover-delivery-raster.png": (720, 1280),
            }
            sizes = {}
            for path in outputs:
                with Image.open(path) as image:
                    sizes[path.name] = image.size
            self.assertEqual(sizes, expected)
            for path in outputs:
                with Image.open(path) as image:
                    right = image.crop((image.width // 2, 0, image.width, image.height))
                    self.assertGreater(len(set(right.convert("RGB").getdata())), 8)

    def test_local_person_cutout_uses_real_aroll_pixels_at_style_seven_width(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            base = root / "base.png"
            base.write_bytes(_png(color=(235, 235, 235)))
            person = _png((320, 480), color=(10, 80, 170))
            outputs = cover.render_local_text(
                base, _brief(hashlib.sha256(person).hexdigest()), root,
                delivery_size=(720, 1280), person_frame=person,
                person_mask_provider=_person_mask,
            )
            with Image.open(root / "cover-3x4.png") as image:
                left = image.crop((108, 144, 432, 1296)).convert("RGB")
                blue_pixels = sum(1 for red, green, blue in left.getdata()
                                  if blue > 130 and blue > red * 5)
                self.assertGreater(blue_pixels, left.width * left.height * 0.10)
                non_background = left.getbbox()
                self.assertIsNotNone(non_background)
            self.assertEqual(len(outputs), 3)

    def test_style_one_renders_dog_font_headline_and_large_person_without_box(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            base = root / "base.png"
            base.write_bytes(_png(color=(8, 12, 22)))
            person = _png((320, 480), color=(10, 80, 170))

            cover.render_local_text(
                base, _impact_brief(hashlib.sha256(person).hexdigest()), root,
                delivery_size=(720, 1280), person_frame=person,
                person_mask_provider=_person_mask,
            )

            with Image.open(root / "cover-3x4.png") as image:
                pixels = list(image.convert("RGB").getdata())
                yellow = sum(1 for red, green, blue in pixels
                             if red > 230 and green > 170 and blue < 50)
                white = sum(1 for red, green, blue in pixels
                            if red > 235 and green > 235 and blue > 235)
                blue = sum(1 for red, green, blue in pixels
                           if blue > 130 and blue > red * 5)
                background = sum(1 for pixel in pixels if pixel == (8, 12, 22))
                self.assertGreater(yellow, 5_000)
                self.assertGreater(white, 5_000)
                self.assertGreater(blue, image.width * image.height * 0.06)
                self.assertGreater(background, image.width * image.height * 0.08)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
class CoverStageTests(unittest.TestCase):
    def test_identity_streams_video_larger_than_metadata_read_limit(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "source.mov"
            size = 128 * 1024 * 1024 + 1
            with path.open("wb") as handle:
                handle.truncate(size)
            digest = hashlib.sha256()
            remaining = size
            zeroes = b"\0" * (1024 * 1024)
            while remaining:
                chunk = zeroes[:min(len(zeroes), remaining)]
                digest.update(chunk)
                remaining -= len(chunk)

            identity = cover._identity(path, {
                "path": "source.mov", "sha256": digest.hexdigest(), "bytes": size,
            })

            self.assertEqual(identity["bytes"], size)
            self.assertEqual(identity["sha256"], digest.hexdigest())

    def test_identity_never_combines_old_bytes_with_replaced_inode(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "source.bin"
            path.write_bytes(b"old-source")
            expected = {
                "path": "source.bin",
                "sha256": hashlib.sha256(b"old-source").hexdigest(),
                "bytes": len(b"old-source"),
            }
            real_fstat = cover.os.fstat
            changed = False

            def replace_after_pin(descriptor):
                nonlocal changed
                status = real_fstat(descriptor)
                if not changed and stat.S_ISREG(status.st_mode):
                    changed = True
                    replacement = path.with_suffix(".new")
                    replacement.write_bytes(b"new-source")
                    os.replace(replacement, path)
                return status

            with mock.patch.object(cover.os, "fstat", side_effect=replace_after_pin):
                with self.assertRaises(cover.CoverError):
                    cover._identity(path, expected)

    def test_stage_gate_requires_approved_subtitles_and_never_calls_provider(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory), approve_subtitles=False)
            source, candidates = _face_setup()
            calls = []
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    job,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates,
                    frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret",
                    base_url="https://openlux.invalid",
                    provider=lambda *args, **kwargs: calls.append((args, kwargs)),
                )
            self.assertEqual(calls, [])
            self.assertFalse((job.job_dir / "07-cover").exists())
            self.assertEqual(job.stages["cover"]["status"], "pending")

    def test_openlux_generation_publishes_exact_six_and_only_marks_cover_ready(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            calls = []

            def provider(prompt, **kwargs):
                calls.append((prompt, kwargs))
                return _provider_response()

            output = cover.prepare_cover(
                job,
                brief=_brief(hashlib.sha256(source).hexdigest()),
                face_candidates=candidates,
                frame_reader=lambda *_args: source,
                quality_probe=_quality_probe(candidates),
                person_mask_provider=_person_mask,
                api_key="secret",
                base_url="https://openlux.invalid",
                provider=provider,
            )
            self.assertEqual(output, job.job_dir / "07-cover" / "cover-delivery-raster.png")
            self.assertEqual(
                {path.name for path in output.parent.iterdir()},
                {
                    "cover-base.png", "cover-brief.json", "cover-3x4.png", "cover-9x16.png",
                    "cover-delivery-raster.png", "cover-report.json", "material-usage.json",
                },
            )
            self.assertEqual(len(calls), 1)
            self.assertIsNone(re.search(r"[\u3400-\u9fff]", calls[0][0]))
            self.assertEqual(calls[0][1], {
                "api_key": "secret", "base_url": "https://openlux.invalid",
            })
            self.assertEqual(job.stages["cover"]["status"], "ready_for_review")
            self.assertEqual(job.stages["preview"]["status"], "pending")
            self.assertEqual(job.stages["delivery"]["status"], "pending")
            report = json.loads((output.parent / "cover-report.json").read_text())
            self.assertEqual(report["version"], 3)
            self.assertNotIn("review_thumbnail", report)
            self.assertFalse((output.parent / "cover-thumbnail-200.png").exists())
            self.assertEqual(report["mode"], "openlux")
            self.assertEqual(report["canvas"], {"width": 1080, "height": 1920})
            self.assertEqual(report["generator"], "gbro-cover-design")
            self.assertEqual(len(report["generation_id"]), 64)
            self.assertEqual(set(report["source_bindings"]), {
                "video", "script", "visual_plan", "asset_manifest",
                "subtitle_plan", "subtitles_webm",
            })
            with Image.open(output) as image:
                self.assertEqual(image.size, (1080, 1920))

    def test_reference_scene_is_hash_bound_and_skips_second_person_composite(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            job = _ready_cover_job(root)
            source, candidates = _face_setup()
            scene_source = _png((1024, 1536), (14, 28, 46))
            scene = root / "theme-scene.png"
            scene.write_bytes(scene_source)
            brief = _impact_brief(hashlib.sha256(source).hexdigest())
            brief["base_generation"] = "reference_person_scene_no_text"
            brief["person_composite"]["method"] = "generated-reference-person"
            brief["reference_scene"] = {
                "sha256": hashlib.sha256(scene_source).hexdigest(),
                "bytes": len(scene_source),
            }
            provider = mock.Mock(side_effect=AssertionError("provider must not run"))

            output = cover.prepare_cover(
                job,
                brief=brief,
                generated_scene=scene,
                face_candidates=candidates,
                frame_reader=lambda *_args: source,
                quality_probe=_quality_probe(candidates),
                person_mask_provider=lambda _source: (_ for _ in ()).throw(
                    AssertionError("person mask must not run")
                ),
                provider=provider,
            )

            provider.assert_not_called()
            self.assertEqual(job.stages["cover"]["status"], "ready_for_review")
            self.assertEqual(job.stages["preview"]["status"], "pending")
            self.assertEqual(len(list(output.parent.iterdir())), 7)
            report = json.loads((output.parent / "cover-report.json").read_text())
            self.assertEqual(report["mode"], "reference-scene-import")
            self.assertEqual(
                report["source_bindings"]["reference_scene"]["sha256"],
                hashlib.sha256(scene_source).hexdigest(),
            )
            with Image.open(output.parent / "cover-3x4.png") as image:
                self.assertEqual(image.convert("RGB").getpixel((20, 1200)), (14, 28, 46))

    def test_provider_failure_blocks_and_second_same_job_call_is_zero_provider(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            calls = []

            def provider(*_args, **_kwargs):
                calls.append(1)
                raise RuntimeError("secret /absolute/path")

            arguments = {
                "brief": _brief(hashlib.sha256(source).hexdigest()),
                "face_candidates": candidates,
                "frame_reader": lambda *_args: source,
                "quality_probe": _quality_probe(candidates),
                "person_mask_provider": _person_mask,
                "api_key": "secret",
                "base_url": "https://openlux.invalid",
                "provider": provider,
            }
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(job, **arguments)
            self.assertEqual(calls, [1])
            self.assertEqual(job.stages["cover"]["status"], "blocked")
            self.assertEqual(job.stages["cover"]["ai_attempts"], 1)
            self.assertNotIn("secret", job.stages["cover"]["reason"])
            self.assertNotIn("/absolute", job.stages["cover"]["reason"])
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(job, **arguments)
            self.assertEqual(calls, [1])

    def test_exact_user_approved_fallback_skips_provider_and_publishes_full_generation(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            state.block(job, "cover", "image generation unavailable", 1)
            state.revise(job, "cover", 'alternative: "aroll-code-cover"')
            source, candidates = _face_setup()
            calls = []
            output = cover.prepare_cover(
                job,
                brief=_brief(hashlib.sha256(source).hexdigest()),
                face_candidates=candidates,
                frame_reader=lambda *_args: source,
                quality_probe=_quality_probe(candidates),
                person_mask_provider=_person_mask,
                api_key="secret",
                base_url="https://openlux.invalid",
                provider=lambda *_args, **_kwargs: calls.append(1),
            )
            self.assertEqual(calls, [])
            report = json.loads((output.parent / "cover-report.json").read_text())
            self.assertEqual(report["mode"], "aroll-code-cover")
            self.assertEqual(report["alternative_evidence"], {
                "reason": 'alternative: "aroll-code-cover"',
                "workflow_revision": report["workflow"]["revision"],
                "workflow_sha256": report["workflow"]["sha256"],
            })
            self.assertEqual(
                json.loads((output.parent / "cover-brief.json").read_text())["generator"],
                "gbro-cover-design",
            )
            self.assertEqual(job.stages["cover"]["status"], "ready_for_review")

    def test_fallback_evidence_is_exact_and_pending_never_silently_falls_back(self) -> None:
        from edit.hd.tools import cover, state

        reasons = [
            ' alternative: "aroll-code-cover"',
            'alternative: "AROLL-CODE-COVER"',
            'alternative: "aroll-code-cover" ',
            'alternative: "aroll-code-cover"\nextra: true',
        ]
        for reason in reasons:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job = _ready_cover_job(Path(directory))
                state.revise(job, "cover", reason)
                source, candidates = _face_setup()
                calls = []
                with self.assertRaises(cover.CoverError):
                    cover.prepare_cover(
                        job,
                        brief=_brief(hashlib.sha256(source).hexdigest()),
                        face_candidates=candidates,
                        frame_reader=lambda *_args: source,
                        quality_probe=_quality_probe(candidates),
                        person_mask_provider=_person_mask,
                        provider=lambda *_args, **_kwargs: calls.append(1),
                    )
                self.assertEqual(calls, [])
                self.assertFalse((job.job_dir / "07-cover").exists())

    def test_new_user_revision_gets_new_generation_and_fresh_complete_inodes(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            arguments = {
                "brief": _brief(hashlib.sha256(source).hexdigest()),
                "face_candidates": candidates,
                "frame_reader": lambda *_args: source,
                "quality_probe": _quality_probe(candidates),
                "person_mask_provider": _person_mask,
                "api_key": "secret",
                "base_url": "https://openlux.invalid",
                "provider": lambda *_args, **_kwargs: _provider_response(),
            }
            first = cover.prepare_cover(job, **arguments).parent
            first_report = json.loads((first / "cover-report.json").read_text())
            old = {path.name: os.stat(path) for path in first.iterdir()}
            state.approve(job, "cover")
            state.revise(job, "cover", "修订封面标题")
            second = cover.prepare_cover(job, **arguments).parent
            second_report = json.loads((second / "cover-report.json").read_text())
            self.assertNotEqual(first_report["generation_id"], second_report["generation_id"])
            self.assertEqual(set(old), {path.name for path in second.iterdir()})
            self.assertTrue(all(
                not os.path.samestat(old[path.name], os.stat(path))
                for path in second.iterdir()
            ))

    def test_same_inode_input_drift_after_provider_fails_closed_without_publication(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            script = job.root / job.inputs["script"]["path"]

            def provider(*_args, **_kwargs):
                with script.open("ab") as stream:
                    stream.write(b"drift")
                    stream.flush()
                    os.fsync(stream.fileno())
                return _provider_response()

            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    job,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates,
                    frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=provider,
                )
            self.assertFalse((job.job_dir / "07-cover").exists())
            # The public state layer refuses every mutation after an input identity
            # drift. Leaving the stage pending is the only non-forged state; the
            # workflow itself is now fail-closed until the input is restored/revised.
            self.assertEqual(job.stages["cover"]["status"], "pending")

    def test_report_binds_exact_sources_workflow_face_and_five_noncyclic_artifacts(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            output = cover.prepare_cover(
                job,
                brief=_brief(hashlib.sha256(source).hexdigest()),
                face_candidates=candidates,
                frame_reader=lambda *_args: source,
                quality_probe=_quality_probe(candidates),
                person_mask_provider=_person_mask,
                api_key="secret", base_url="https://openlux.invalid",
                provider=lambda *_args, **_kwargs: _provider_response(),
            )
            report = json.loads((output.parent / "cover-report.json").read_text())
            self.assertEqual(report["face_frame"]["sha256"], hashlib.sha256(source).hexdigest())
            self.assertEqual(report["base_generation"], "scene_only_no_people_no_text")
            self.assertEqual(report["person_composite"]["method"], "local-foreground-cutout")
            self.assertEqual(report["person_composite"]["frame_timestamp"], 0.75)
            self.assertEqual(report["person_composite"]["frame_sha256"], hashlib.sha256(source).hexdigest())
            self.assertIsNone(report["alternative_evidence"])
            self.assertEqual(report["workflow"]["revision"] + 1, job.revision)
            for name, record in report["source_bindings"].items():
                if name in {"video", "script"}:
                    path = job.root / record["path"]
                else:
                    path = job.job_dir / record["path"]
                data = path.read_bytes()
                status = os.stat(path)
                parent = os.stat(path.parent)
                self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(record["bytes"], len(data))
                self.assertEqual((record["device"], record["inode"]),
                                 (status.st_dev, status.st_ino))
                self.assertEqual((record["parent_device"], record["parent_inode"]),
                                 (parent.st_dev, parent.st_ino))
            self.assertEqual(
                {Path(record["path"]).name for record in report["artifacts"]},
                {"cover-base.png", "cover-brief.json", "cover-3x4.png", "cover-9x16.png",
                 "cover-delivery-raster.png"},
            )
            for record in report["artifacts"]:
                path = output.parent / Path(record["path"]).name
                data = path.read_bytes()
                self.assertEqual((record["sha256"], record["bytes"]),
                                 (hashlib.sha256(data).hexdigest(), len(data)))

    def test_old_generation_unknown_leaf_swap_is_never_overwritten_truncated_or_deleted(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            arguments = {
                "brief": _brief(hashlib.sha256(source).hexdigest()),
                "face_candidates": candidates,
                "frame_reader": lambda *_args: source,
                "quality_probe": _quality_probe(candidates),
                "person_mask_provider": _person_mask,
                "api_key": "secret", "base_url": "https://openlux.invalid",
                "provider": lambda *_args, **_kwargs: _provider_response(),
            }
            target = cover.prepare_cover(job, **arguments).parent
            state.approve(job, "cover")
            state.revise(job, "cover", "重新生成封面")
            swapped = target / "cover-3x4.png"
            swapped.unlink()
            swapped.write_bytes(b"external-owner-file")
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(job, **arguments)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_mark_ready_failure_rolls_back_first_and_revised_complete_generation(self) -> None:
        from edit.hd.tools import cover, state

        for revised in (False, True):
            with self.subTest(revised=revised), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job = _ready_cover_job(Path(directory))
                source, candidates = _face_setup()
                arguments = {
                    "brief": _brief(hashlib.sha256(source).hexdigest()),
                    "face_candidates": candidates,
                    "frame_reader": lambda *_args: source,
                    "quality_probe": _quality_probe(candidates),
                    "person_mask_provider": _person_mask,
                    "api_key": "secret", "base_url": "https://openlux.invalid",
                    "provider": lambda *_args, **_kwargs: _provider_response(),
                }
                old = None
                if revised:
                    target = cover.prepare_cover(job, **arguments).parent
                    old = {path.name: (os.stat(path), path.read_bytes()) for path in target.iterdir()}
                    state.approve(job, "cover")
                    state.revise(job, "cover", "验证发布回滚")
                with mock.patch.object(
                    state, "mark_ready", side_effect=state.WorkflowError("stop")
                ):
                    with self.assertRaises(cover.CoverError):
                        cover.prepare_cover(job, **arguments)
                target = job.job_dir / "07-cover"
                self.assertFalse((job.job_dir / ".07-cover.transaction.json").exists())
                if old is None:
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual({path.name for path in target.iterdir()}, set(old))
                    for path in target.iterdir():
                        self.assertTrue(os.path.samestat(old[path.name][0], os.stat(path)))
                        self.assertEqual(old[path.name][1], path.read_bytes())

    def test_unknown_target_created_during_generation_is_preserved_unmodified(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            unknown = job.job_dir / "07-cover"

            def provider(*_args, **_kwargs):
                unknown.mkdir()
                (unknown / "owner.txt").write_text("external", encoding="utf-8")
                return _provider_response()

            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    job,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates,
                    frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=provider,
                )
            self.assertEqual({path.name for path in unknown.iterdir()}, {"owner.txt"})
            self.assertEqual((unknown / "owner.txt").read_text(), "external")
            self.assertEqual(job.stages["cover"]["status"], "blocked")

    def test_keyboard_interrupt_cleans_stage_and_claim_prevents_same_generation_post(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            calls = []

            def interrupt(*_args, **_kwargs):
                calls.append(1)
                raise KeyboardInterrupt

            arguments = {
                "brief": _brief(hashlib.sha256(source).hexdigest()),
                "face_candidates": candidates,
                "frame_reader": lambda *_args: source,
                "quality_probe": _quality_probe(candidates),
                "person_mask_provider": _person_mask,
                "api_key": "secret", "base_url": "https://openlux.invalid",
                "provider": interrupt,
            }
            with self.assertRaises(KeyboardInterrupt):
                cover.prepare_cover(job, **arguments)
            self.assertFalse(any(
                path.name.startswith(".07-cover.stage-") for path in job.job_dir.iterdir()
            ))
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(job, **arguments)
            self.assertEqual(calls, [1])

    def test_provider_stage_directory_swap_never_deletes_unknown_owner_content(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            owner = b"external-owner-content"

            def provider(*_args, **_kwargs):
                stages = [
                    path for path in job.job_dir.iterdir()
                    if path.name.startswith(".07-cover.stage-")
                ]
                self.assertEqual(len(stages), 1)
                original = stages[0]
                shutil.rmtree(original)
                original.mkdir()
                (original / "owner.txt").write_bytes(owner)
                raise RuntimeError("provider failed")

            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    job,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates,
                    frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=provider,
                )
            stages = [
                path for path in job.job_dir.iterdir()
                if path.name.startswith(".07-cover.stage-")
            ]
            self.assertEqual(len(stages), 1)
            self.assertEqual((stages[0] / "owner.txt").read_bytes(), owner)

    def test_close_failure_is_sanitized_and_never_reaches_provider(self) -> None:
        from edit.hd.tools import cover

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            calls = []
            real_close = cover.os.close
            failed = False

            def fail_once(descriptor):
                nonlocal failed
                real_close(descriptor)
                if not failed:
                    failed = True
                    raise OSError("close failed /private/path")

            with mock.patch.object(cover.os, "close", side_effect=fail_once):
                with self.assertRaises(cover.CoverError):
                    cover.prepare_cover(
                        job,
                        brief=_brief(hashlib.sha256(source).hexdigest()),
                        face_candidates=candidates,
                        frame_reader=lambda *_args: source,
                        quality_probe=_quality_probe(candidates),
                        person_mask_provider=_person_mask,
                        api_key="secret", base_url="https://openlux.invalid",
                        provider=lambda *_args, **_kwargs: calls.append(1),
                    )
            self.assertEqual(calls, [])

    def test_hard_crash_publish_matrix_recovers_without_second_provider_post(self) -> None:
        from edit.hd.tools import cover, state

        for checkpoint in ("prepared", "after-install", "after-workflow"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job = _ready_cover_job(Path(directory))
                environment = dict(os.environ)
                environment["HD_COVER_CRASH_CHECKPOINT"] = checkpoint
                command = (
                    "from pathlib import Path; import hashlib; "
                    "from edit.hd.tools.state import load_job; "
                    "from edit.hd.tools.cover import prepare_cover; "
                    "from edit.hd.tests.test_cover import (_brief,_face_setup,_provider_response,"
                    "_quality_probe,_person_mask); "
                    f"j=load_job(Path({str(job.job_dir)!r})); s,c=_face_setup(); "
                    "prepare_cover(j,brief=_brief(hashlib.sha256(s).hexdigest()),"
                    "face_candidates=c,frame_reader=lambda *_:s,quality_probe=_quality_probe(c),"
                    "person_mask_provider=_person_mask,api_key='secret',"
                    "base_url='https://openlux.invalid',provider=lambda *a,**k:_provider_response())"
                )
                result = subprocess.run(["python3", "-c", command], env=environment)
                self.assertEqual(result.returncode, 86)
                recovered = state.load_job(job.job_dir)
                source, candidates = _face_setup()
                calls = []
                output = cover.prepare_cover(
                    recovered,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates,
                    frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=lambda *_args, **_kwargs: calls.append(1),
                )
                self.assertEqual(calls, [])
                self.assertTrue(output.is_file())
                self.assertEqual(recovered.stages["cover"]["status"], "ready_for_review")
                self.assertFalse((job.job_dir / ".07-cover.transaction.json").exists())

    def test_claim_phase_hard_crash_recovers_as_blocked_without_second_post(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            environment = dict(os.environ)
            environment["HD_COVER_CRASH_CHECKPOINT"] = "after-claim"
            command = (
                "from pathlib import Path; import hashlib; "
                "from edit.hd.tools.state import load_job; "
                "from edit.hd.tools.cover import prepare_cover; "
                "from edit.hd.tests.test_cover import (_brief,_face_setup,_provider_response,"
                "_quality_probe,_person_mask); "
                f"j=load_job(Path({str(job.job_dir)!r})); s,c=_face_setup(); "
                "prepare_cover(j,brief=_brief(hashlib.sha256(s).hexdigest()),"
                "face_candidates=c,frame_reader=lambda *_:s,quality_probe=_quality_probe(c),"
                "person_mask_provider=_person_mask,api_key='secret',"
                "base_url='https://openlux.invalid',provider=lambda *a,**k:_provider_response())"
            )
            result = subprocess.run(["python3", "-c", command], env=environment)
            self.assertEqual(result.returncode, 86)
            recovered = state.load_job(job.job_dir)
            source, candidates = _face_setup()
            calls = []
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    recovered,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates, frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=lambda *_args, **_kwargs: calls.append(1),
                )
            self.assertEqual(calls, [])
            self.assertEqual(recovered.stages["cover"]["status"], "blocked")

    def test_post_provider_pretransaction_crashes_block_without_second_post(self) -> None:
        from edit.hd.tools import cover, state

        for checkpoint in ("after-base", "after-local-render"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job = _ready_cover_job(Path(directory))
                environment = dict(os.environ)
                environment["HD_COVER_CRASH_CHECKPOINT"] = checkpoint
                command = (
                    "from pathlib import Path; import hashlib; "
                    "from edit.hd.tools.state import load_job; "
                    "from edit.hd.tools.cover import prepare_cover; "
                    "from edit.hd.tests.test_cover import (_brief,_face_setup,_provider_response,"
                    "_quality_probe,_person_mask); "
                    f"j=load_job(Path({str(job.job_dir)!r})); s,c=_face_setup(); "
                    "prepare_cover(j,brief=_brief(hashlib.sha256(s).hexdigest()),"
                    "face_candidates=c,frame_reader=lambda *_:s,quality_probe=_quality_probe(c),"
                    "person_mask_provider=_person_mask,api_key='secret',"
                    "base_url='https://openlux.invalid',provider=lambda *a,**k:_provider_response())"
                )
                result = subprocess.run(["python3", "-c", command], env=environment)
                self.assertEqual(result.returncode, 86)
                recovered = state.load_job(job.job_dir)
                source, candidates = _face_setup()
                calls = []
                with self.assertRaises(cover.CoverError):
                    cover.prepare_cover(
                        recovered,
                        brief=_brief(hashlib.sha256(source).hexdigest()),
                        face_candidates=candidates, frame_reader=lambda *_args: source,
                        quality_probe=_quality_probe(candidates),
                        person_mask_provider=_person_mask,
                        api_key="secret", base_url="https://openlux.invalid",
                        provider=lambda *_args, **_kwargs: calls.append(1),
                    )
                self.assertEqual(calls, [])
                self.assertEqual(recovered.stages["cover"]["status"], "blocked")

    def test_generation_claim_uses_immutable_noreplace_storage(self) -> None:
        from edit.hd.tools import cover

        source = inspect.getsource(cover._claim_generation)
        self.assertNotIn("os.replace", source)
        self.assertIn("_write_new", source)
        self.assertNotIn("_replace_ai_marker", inspect.getsource(cover.prepare_cover))

    def test_stale_crash_between_backup_and_install_restores_complete_old_generation(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            arguments = {
                "brief": _brief(hashlib.sha256(source).hexdigest()),
                "face_candidates": candidates, "frame_reader": lambda *_args: source,
                "quality_probe": _quality_probe(candidates),
                "person_mask_provider": _person_mask,
                "api_key": "secret", "base_url": "https://openlux.invalid",
                "provider": lambda *_args, **_kwargs: _provider_response(),
            }
            target = cover.prepare_cover(job, **arguments).parent
            old = {path.name: (os.stat(path), path.read_bytes()) for path in target.iterdir()}
            state.approve(job, "cover")
            state.revise(job, "cover", "生成新封面")
            environment = dict(os.environ)
            environment["HD_COVER_CRASH_CHECKPOINT"] = "after-backup"
            command = (
                "from pathlib import Path; import hashlib; "
                "from edit.hd.tools.state import load_job; from edit.hd.tools.cover import prepare_cover; "
                "from edit.hd.tests.test_cover import (_brief,_face_setup,_provider_response,"
                "_quality_probe,_person_mask); "
                f"j=load_job(Path({str(job.job_dir)!r})); s,c=_face_setup(); "
                "prepare_cover(j,brief=_brief(hashlib.sha256(s).hexdigest()),"
                "face_candidates=c,frame_reader=lambda *_:s,quality_probe=_quality_probe(c),"
                "person_mask_provider=_person_mask,api_key='secret',"
                "base_url='https://openlux.invalid',provider=lambda *a,**k:_provider_response())"
            )
            result = subprocess.run(["python3", "-c", command], env=environment)
            self.assertEqual(result.returncode, 86)
            recovered = state.load_job(job.job_dir)
            state.revise(recovered, "cover", "外部工作流修订")
            calls = []
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    recovered,
                    brief=_brief(hashlib.sha256(source).hexdigest()),
                    face_candidates=candidates, frame_reader=lambda *_args: source,
                    quality_probe=_quality_probe(candidates),
                    person_mask_provider=_person_mask,
                    api_key="secret", base_url="https://openlux.invalid",
                    provider=lambda *_args, **_kwargs: calls.append(1) or (_ for _ in ()).throw(RuntimeError()),
                )
            self.assertEqual(calls, [1])
            self.assertEqual({path.name for path in target.iterdir()}, set(old))
            for path in target.iterdir():
                self.assertTrue(os.path.samestat(old[path.name][0], os.stat(path)))
                self.assertEqual(old[path.name][1], path.read_bytes())

    def test_two_concurrent_calls_publish_one_generation_and_make_one_post(self) -> None:
        from edit.hd.tools import cover, state

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = _ready_cover_job(Path(directory))
            source, candidates = _face_setup()
            calls = []
            barrier = threading.Barrier(2)
            results = []

            def provider(*_args, **_kwargs):
                calls.append(1)
                return _provider_response()

            def run() -> None:
                local = state.load_job(job.job_dir)
                barrier.wait()
                try:
                    results.append(cover.prepare_cover(
                        local,
                        brief=_brief(hashlib.sha256(source).hexdigest()),
                        face_candidates=candidates,
                        frame_reader=lambda *_args: source,
                        quality_probe=_quality_probe(candidates),
                        person_mask_provider=_person_mask,
                        api_key="secret", base_url="https://openlux.invalid",
                        provider=provider,
                    ))
                except cover.CoverError:
                    results.append(None)

            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(calls, [1])
            self.assertEqual(sum(result is not None for result in results), 1)
            final = state.load_job(job.job_dir)
            self.assertEqual(final.stages["cover"]["status"], "ready_for_review")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from edit.hd.tests.test_content_analysis import SCRIPT, VALID_ANALYSIS
from edit.hd.tests.test_cover import _person_mask, _provider_response
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tools import content_analysis, cover, cover_direction, state


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (480, 720), (120, 90, 70)).save(stream, format="PNG")
    return stream.getvalue()


VALID_DIRECTION = {
    "output_aspect_ratio": "3:4",
    "title": "标准变了",
    "subtitle": "用进真实工作流",
    "person_reference": {
        "source": "current-aroll-video",
        "timestamp": 0.75,
    },
    "pose": "人物正面指向右侧工作流面板，露出头肩和双手",
    "expression": "坚定、直视镜头",
    "environment": "深色 AI 工作流工作室",
    "props": ["工作流面板", "任务卡片"],
    "composition": {
        "style_id": "style-01",
        "person_side": "right",
        "person_width_ratio": 0.55,
        "blank_width_ratio": 0.35,
    },
    "palette": {
        "background": "dark-ai-workflow-studio",
        "font_color": "#FFFFFF",
        "accent_color": "#FFD84D",
    },
    "typography": {"font_style": "heavy-sans"},
    "safe_zones": {"safe_margin_ratio": 0.10},
    "prompt_allow": ["人物脸部完整", "主题化环境", "工作流道具"],
    "prompt_deny": ["文字遮挡人脸", "仅有头部", "无关场景"],
}


class CoverDirectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"video")
        self.script.write_text(SCRIPT, encoding="utf-8")
        self.job = state.create_job(
            self.root, self.video, self.script, profile="full-v2"
        )
        report = self.job.job_dir / "01-inspect" / "report.json"
        report.parent.mkdir(parents=True)
        report.write_text("{}\n", encoding="utf-8")
        state.mark_ready(self.job, "inspect", [report])
        state.approve(self.job, "inspect")
        self.analysis = content_analysis.prepare_content_analysis(
            self.job, VALID_ANALYSIS
        )
        state.approve(self.job, "content_analysis")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _prepare(self):
        return cover_direction.prepare_cover_direction(
            self.job, VALID_DIRECTION, frame_reader=lambda *_args: _png()
        )

    def _punk_material(self):
        approve_fixture_setup(self.job)
        source = self.root / "00-user-provided" / "images" / "person.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(_png())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        (self.root / "00-user-provided" / "material-index.json").write_text(
            json.dumps({"schema_version": 1, "materials": [{
                "material_id": "material-0003",
                "imported_path": "00-user-provided/images/person.jpg",
                "media_type": "images", "sha256": digest,
                "size_bytes": source.stat().st_size,
            }]}) + "\n", encoding="utf-8"
        )
        direction = copy.deepcopy(VALID_DIRECTION)
        direction.update({
            "output_aspect_ratio": "9:16",
            "title": VALID_DIRECTION["title"],
            "subtitle": VALID_DIRECTION["subtitle"],
            "person_reference": {"source": "user-material", "material_id": "material-0003"},
            "composition": {
                "style_id": "interleaved-title-editorial-poster",
                "person_side": "right", "person_width_ratio": 0.60,
                "blank_width_ratio": 0.35,
            },
            "safe_zones": {"safe_margin_ratio": 0.05},
        })
        return direction

    def _punk_direction_preview(self):
        preview = self.job.job_dir / "punk-direction-preview.png"
        Image.new("RGB", (1080, 1920), "#F3EBDD").save(preview, format="PNG")
        return preview

    def test_punk_full_preview_publishes_exact_pixels_and_never_calls_provider(self):
        direction = self._punk_material()
        preview = self._punk_direction_preview()
        with mock.patch.object(
            cover_direction, "_render_direction_preview",
            side_effect=AssertionError("Punk direction must use the explicit PNG"),
        ):
            record = cover_direction.prepare_cover_direction(
                self.job, direction, direction_preview=preview
            )
        self.assertEqual(
            record["direction"]["composition"]["style_id"],
            "interleaved-title-editorial-poster",
        )
        state.approve(self.job, "cover_direction")
        approved = self.job.job_dir / "punk-assets" / "punk-cover" / "make-your-own" / "cover-source-normalized-1080x1920.png"
        approved.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1920), "#D97832").save(approved, format="PNG")
        approved_bytes = approved.read_bytes()
        output = cover.prepare_cover(
            self.job, approved_preview=approved,
            approved_preview_sha256=hashlib.sha256(approved_bytes).hexdigest(),
            approved_preview_prompt="Punk full cover prompt with exact approved Chinese title.",
            provider=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("Punk approved preview must not call provider")
            ),
        )
        self.assertEqual(output.read_bytes(), approved_bytes)
        self.assertEqual((output.parent / "cover-delivery-raster.png").read_bytes(), approved_bytes)
        report = json.loads((output.parent / "cover-report.json").read_text())
        self.assertEqual(report["mode"], "approved-full-image")
        self.assertEqual(report["generator"], "punk-cover")
        self.assertEqual(cover.review_cover(self.job)["images"]["final"]["sha256"],
                         hashlib.sha256(approved_bytes).hexdigest())

    def test_punk_direction_requires_explicit_preview_before_writing(self):
        direction = self._punk_material()
        with self.assertRaises(cover_direction.CoverDirectionError):
            cover_direction.prepare_cover_direction(self.job, direction)
        self.assertFalse((self.job.job_dir / "03-cover-direction" / "cover-direction.json").exists())

    def test_punk_full_preview_requires_nonempty_prompt_and_rejects_old_routes(self):
        direction = self._punk_material()
        preview = self._punk_direction_preview()
        record = cover_direction.prepare_cover_direction(
            self.job, direction, direction_preview=preview
        )
        state.approve(self.job, "cover_direction")
        approved = self.job.job_dir / "approved.png"
        Image.new("RGB", (1080, 1920), "#D97832").save(approved, format="PNG")
        digest = hashlib.sha256(approved.read_bytes()).hexdigest()
        for prompt in (None, "", "   "):
            with self.subTest(prompt=repr(prompt)):
                with self.assertRaises(cover.CoverError):
                    cover.prepare_cover(
                        self.job, approved_preview=approved,
                        approved_preview_sha256=digest, approved_preview_prompt=prompt,
                    )
        with self.subTest("old generated-scene route"):
            with self.assertRaises(cover.CoverError):
                cover.prepare_cover(
                    self.job, approved_preview=approved,
                    approved_preview_sha256=digest,
                    approved_preview_prompt="valid punk prompt",
                    generated_scene=approved, generated_scene_prompt="old route",
                )
        with self.subTest("old brief route"):
            old_brief = copy.deepcopy(cover._brief_from_approved_direction(
                record, approved_preview_prompt="valid Punk complete-image prompt"
            ))
            old_brief["base_generation"] = "scene_only_no_people_no_text"
            old_brief["generator"] = "gbro-cover-design"
            old_brief["person_composite"]["method"] = "local-foreground-cutout"
            old_brief["text_layer"]["engine"] = "Pillow"
            old_brief["rounds"]["visual_details"]["safe_margin_ratio"] = 0.10
            old_brief["text_layer"]["safe_margin_ratio"] = 0.10
            old_brief["base_prompt"] = cover._scene_prompt(old_brief["rounds"]["visual_details"])
            old_brief["style_id"] = "style-02"
            old_brief["rounds"]["style_and_title"]["selection"] = "style-02"
            cover.validate_cover_brief(old_brief)
            old_brief["style_id"] = "interleaved-title-editorial-poster"
            old_brief["rounds"]["style_and_title"]["selection"] = old_brief["style_id"]
            with self.assertRaises(cover.CoverError):
                cover.validate_cover_brief(old_brief)

    def test_direction_binds_analysis_and_real_aroll_reference(self) -> None:
        record = self._prepare()

        self.assertEqual(
            record["content_analysis_sha256"], self.analysis["analysis_sha256"]
        )
        reference = record["direction"]["person_reference"]
        self.assertEqual(reference["video_sha256"], self.job.inputs["video"]["sha256"])
        self.assertEqual(reference["path"], "03-cover-direction/person-reference.png")
        self.assertTrue((self.job.job_dir / reference["path"]).is_file())
        self.assertEqual(
            self.job.stages["cover_direction"]["status"], "ready_for_review"
        )

    def test_style_seven_direction_preserves_approved_support_line(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction.update({
            "output_aspect_ratio": "9:16",
            "subtitle": "根本不是AI模型",
            "support_line": "认知 · 经验 · 工作流",
        })
        direction["composition"] = {
            "style_id": "style-07",
            "person_side": "right",
            "person_width_ratio": 0.32,
            "blank_width_ratio": 0.64,
        }
        direction["safe_zones"] = {"safe_margin_ratio": 0.04}
        record = cover_direction.prepare_cover_direction(
            self.job, direction, frame_reader=lambda *_args: _png()
        )
        self.assertEqual(record["direction"]["support_line"], direction["support_line"])
        brief = cover._brief_from_approved_direction(record)
        self.assertEqual(brief["support_line"], direction["support_line"])

    def test_direction_binds_selected_user_material_reference(self) -> None:
        approve_fixture_setup(self.job)
        source = self.root / "00-user-provided" / "images" / "person.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(_png())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        index = self.root / "00-user-provided" / "material-index.json"
        index.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "materials": [
                        {
                            "material_id": "material-0003",
                            "imported_path": "00-user-provided/images/person.jpg",
                            "media_type": "images",
                            "sha256": digest,
                            "size_bytes": source.stat().st_size,
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["person_reference"] = {
            "source": "user-material",
            "material_id": "material-0003",
        }

        record = cover_direction.prepare_cover_direction(self.job, direction)

        reference = record["direction"]["person_reference"]
        self.assertEqual(reference["source"], "user-material")
        self.assertEqual(reference["material_id"], "material-0003")
        self.assertEqual(reference["material_sha256"], digest)
        self.assertEqual(reference["path"], "03-cover-direction/person-reference.png")
        self.assertTrue((self.job.job_dir / reference["path"]).is_file())
        usage = json.loads(
            (self.job.job_dir / "03-cover-direction/material-usage.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            usage["references"],
            [
                {
                    "material_id": "material-0003",
                    "material_sha256": digest,
                    "consumer_kind": "cover_reference",
                    "consumer_id": "cover-direction",
                    "binding_path": "/direction/person_reference/material_id",
                    "artifact_paths": [
                        "03-cover-direction/person-reference.png",
                        "03-cover-direction/direction-preview.png",
                    ],
                }
            ],
        )

    def test_approved_user_material_direction_imports_generated_reference_scene(self) -> None:
        approve_fixture_setup(self.job)
        source = self.root / "00-user-provided" / "images" / "person.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(_png())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        index = self.root / "00-user-provided" / "material-index.json"
        index.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "materials": [
                        {
                            "material_id": "material-0003",
                            "imported_path": "00-user-provided/images/person.jpg",
                            "media_type": "images",
                            "sha256": digest,
                            "size_bytes": source.stat().st_size,
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "16:9"
        direction["person_reference"] = {
            "source": "user-material",
            "material_id": "material-0003",
        }
        prepared = cover_direction.prepare_cover_direction(self.job, direction)
        state.approve(self.job, "cover_direction")
        scene_source = _png()
        scene = self.root / "generated-cover-scene.png"
        scene.write_bytes(scene_source)
        (self.job.job_dir / "04-cover").mkdir()
        prompt = (
            "3:4 portrait editorial cover. The reference woman tears a giant paper "
            "poster apart with both hands; her face, shoulders, arms, and hands remain "
            "fully visible. Deep navy studio, strong perspective, flying paper fragments. "
            "Avoid: any text, letters, logos, watermarks, or extra people."
        )

        output = cover.prepare_cover(
            self.job,
            generated_scene=scene,
            generated_scene_prompt=prompt,
            person_mask_provider=lambda _source: (_ for _ in ()).throw(
                AssertionError("person mask must not run")
            ),
            provider=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("provider must not run")
            ),
        )

        report = json.loads(
            (output.parent / "cover-report.json").read_text(encoding="utf-8")
        )
        reference = prepared["direction"]["person_reference"]
        self.assertEqual(report["mode"], "reference-scene-import")
        self.assertEqual(report["output_aspect_ratio"], "16:9")
        self.assertEqual(report["prompt"], prompt)
        self.assertEqual(report["face_frame"], {
            "source": "user-material",
            "material_id": "material-0003",
            "sha256": reference["sha256"],
        })
        self.assertEqual(
            report["source_bindings"]["reference_scene"]["sha256"],
            hashlib.sha256(scene_source).hexdigest(),
        )
        self.assertEqual(
            report["person_composite"]["method"],
            "generated-reference-person",
        )
        self.assertNotIn("frame_timestamp", report["person_composite"])
        self.assertEqual(self.job.stages["cover"]["status"], "ready_for_review")
        self.assertEqual(
            {path.name for path in output.parent.iterdir()},
            {
                "cover-base.png",
                "cover-brief.json",
                "cover-16x9.png",
                "cover-delivery-raster.png",
                "cover-report.json",
                "material-usage.json",
            },
        )
        with Image.open(output.parent / "cover-16x9.png") as image:
            self.assertEqual(image.size, (1920, 1080))

    def test_approved_visual_preview_is_published_without_redrawing(self) -> None:
        approve_fixture_setup(self.job)
        source = self.root / "00-user-provided" / "images" / "person.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(_png())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        index = self.root / "00-user-provided" / "material-index.json"
        index.write_text(json.dumps({
            "schema_version": 1,
            "materials": [{
                "material_id": "material-0003",
                "imported_path": "00-user-provided/images/person.jpg",
                "media_type": "images",
                "sha256": digest,
                "size_bytes": source.stat().st_size,
            }],
        }) + "\n", encoding="utf-8")
        direction = copy.deepcopy(VALID_DIRECTION)
        direction.update({
            "output_aspect_ratio": "9:16",
            "subtitle": "根本不是AI模型",
            "support_line": "认知 · 经验 · 工作流",
            "person_reference": {"source": "user-material", "material_id": "material-0003"},
            "composition": {
                "style_id": "style-07", "person_side": "right",
                "person_width_ratio": 0.32, "blank_width_ratio": 0.64,
            },
            "safe_zones": {"safe_margin_ratio": 0.04},
        })
        cover_direction.prepare_cover_direction(self.job, direction)
        state.approve(self.job, "cover_direction")
        scene = self.root / "scene-no-text.png"
        scene.write_bytes(_png())
        preview = self.root / "approved-cover-preview.png"
        with Image.new("RGB", (1080, 1920), (12, 25, 47)) as image:
            ImageDraw.Draw(image).rectangle((40, 200, 1040, 440), fill=(255, 214, 0))
            image.save(preview, format="PNG")
        approved_bytes = preview.read_bytes()
        prompt = "9:16 editorial portrait, person integrated with workflow scene. No text, no letters, no watermark."
        arguments = {
            "generated_scene": scene,
            "generated_scene_prompt": prompt,
            "person_protection_boxes": [[0.53, 0.30, 0.99, 0.98]],
            "approved_preview": preview,
            "approved_preview_sha256": hashlib.sha256(approved_bytes).hexdigest(),
            "provider": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("approved preview must not call a provider")
            ),
        }
        with self.assertRaises(cover.CoverError):
            cover.prepare_cover(
                self.job, **{**arguments, "approved_preview_sha256": "0" * 64}
            )
        output = cover.prepare_cover(self.job, **arguments)
        self.assertEqual(output.read_bytes(), approved_bytes)
        self.assertEqual((output.parent / "cover-9x16.png").read_bytes(), approved_bytes)
        report = json.loads((output.parent / "cover-report.json").read_text())
        self.assertEqual(report["mode"], "approved-preview-reuse")
        self.assertEqual(report["source_bindings"]["approved_preview"]["sha256"],
                         hashlib.sha256(approved_bytes).hexdigest())
        self.assertNotIn("review_thumbnail", report)
        self.assertFalse((output.parent / "cover-thumbnail-200.png").exists())

    def test_aroll_approved_visual_preview_keeps_exact_pixels(self) -> None:
        self._prepare()
        state.approve(self.job, "cover_direction")
        base = self.root / "scene-no-text.png"
        preview = self.root / "approved-cover-preview.png"
        Image.new("RGB", (1080, 1440), "#122235").save(base)
        Image.new("RGB", (1080, 1440), "#FFD600").save(preview)
        approved_bytes = preview.read_bytes()
        output = cover.prepare_cover(
            self.job,
            approved_preview=preview,
            approved_preview_sha256=hashlib.sha256(approved_bytes).hexdigest(),
            approved_base=base,
            person_mask_provider=lambda _source: (_ for _ in ()).throw(
                AssertionError("approved preview must not composite the person again")
            ),
            provider=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("approved preview must not call a provider")
            ),
        )
        self.assertEqual(output.read_bytes(), approved_bytes)
        self.assertEqual((output.parent / "cover-base.png").read_bytes(), base.read_bytes())
        report = json.loads((output.parent / "cover-report.json").read_text())
        self.assertEqual(report["mode"], "approved-preview-reuse")
        self.assertEqual(report["person_composite"]["method"], "approved-preview-integrated")

    def test_user_material_complete_cover_needs_no_textless_base(self) -> None:
        approve_fixture_setup(self.job)
        source = self.root / "00-user-provided/images/person.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(_png())
        index = self.root / "00-user-provided/material-index.json"
        index.write_text(json.dumps({
            "schema_version": 1,
            "materials": [{
                "material_id": "material-0003",
                "imported_path": "00-user-provided/images/person.jpg",
                "media_type": "images",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
            }],
        }) + "\n", encoding="utf-8")
        direction = copy.deepcopy(VALID_DIRECTION)
        direction.update({
            "output_aspect_ratio": "9:16",
            "subtitle": "不是模型，是认知与流程",
            "person_reference": {"source": "user-material", "material_id": "material-0003"},
            "composition": {
                "style_id": "style-07", "person_side": "right",
                "person_width_ratio": 0.32, "blank_width_ratio": 0.64,
            },
            "safe_zones": {"safe_margin_ratio": 0.05},
        })
        cover_direction.prepare_cover_direction(self.job, direction)
        state.approve(self.job, "cover_direction")
        preview = self.root / "complete-cover.png"
        Image.new("RGB", (1080, 1920), "#122235").save(preview)
        source_bytes = preview.read_bytes()
        prompt = "Punk editorial portrait with a complete Chinese headline."

        output = cover.prepare_cover(
            self.job,
            approved_preview=preview,
            approved_preview_sha256=hashlib.sha256(source_bytes).hexdigest(),
            approved_preview_prompt=prompt,
            provider=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("complete cover must not call a provider")
            ),
        )

        self.assertEqual(output.read_bytes(), source_bytes)
        self.assertEqual((output.parent / "cover-9x16.png").read_bytes(), source_bytes)
        self.assertFalse((output.parent / "cover-base.png").exists())
        report = json.loads((output.parent / "cover-report.json").read_text())
        self.assertEqual(report["mode"], "approved-full-image")
        self.assertEqual(report["prompt"], prompt)
        self.assertEqual(
            {item["path"] for item in report["artifacts"]},
            {"04-cover/cover-brief.json", "04-cover/cover-9x16.png",
             "04-cover/cover-delivery-raster.png"},
        )
        self.assertEqual(cover.review_cover(self.job)["images"]["final"]["sha256"],
                         hashlib.sha256(source_bytes).hexdigest())

    def test_direction_records_explicit_output_aspect_ratio(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "16:9"

        record = cover_direction.prepare_cover_direction(
            self.job, direction, frame_reader=lambda *_args: _png()
        )

        self.assertEqual(record["direction"]["output_aspect_ratio"], "16:9")
        review = (self.job.job_dir / "03-cover-direction" / "review.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("16:9", review)

    def test_direction_review_uses_native_9x16_visual_preview(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "9:16"
        direction["props"] = [
            "AI 模型芯片",
            "Transformer 层级块",
            "神经网络节点",
            "认知与工作流程网络",
        ]

        cover_direction.prepare_cover_direction(
            self.job, direction, frame_reader=lambda *_args: _png()
        )

        stage = self.job.job_dir / "03-cover-direction"
        preview = stage / "direction-preview.png"
        self.assertTrue(preview.is_file())
        with Image.open(preview) as image:
            self.assertEqual(image.size, (1080, 1920))
            semantics = image.info.get("cover_direction_semantics", "")
        for item in (
            "model-chip",
            "transformer-layers",
            "neural-network",
            "cognition-context-workflow",
        ):
            with self.subTest(item=item):
                self.assertIn(item, semantics)

        review = (stage / "review.html").read_text(encoding="utf-8")
        self.assertIn('src="direction-preview.png"', review)
        self.assertNotIn('src="person-reference.png"', review)
        self.assertIn("构图样板，非最终生成图", review)
        self.assertEqual(
            {Path(item["path"]).name for item in self.job.stages["cover_direction"]["artifacts"]},
            {
                "cover-direction.json",
                "direction-preview.png",
                "material-usage.json",
                "person-reference.png",
                "review.html",
            },
        )

    def test_external_direction_preview_preserves_bytes_and_identity(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        preview = self.job.job_dir / "external-preview.png"
        stream = io.BytesIO()
        Image.new("RGB", (1080, 1440), (12, 34, 56)).save(stream, format="PNG")
        original = stream.getvalue()
        preview.write_bytes(original)

        with mock.patch.object(
            cover_direction, "_render_direction_preview",
            side_effect=AssertionError("external preview must not be rendered"),
        ):
            record = cover_direction.prepare_cover_direction(
                self.job, direction,
                frame_reader=lambda *_args: _png(),
                direction_preview=preview,
            )

        self.assertEqual(
            (self.job.job_dir / "03-cover-direction" / "direction-preview.png").read_bytes(),
            original,
        )
        self.assertEqual(record["content_analysis_sha256"], self.analysis["analysis_sha256"])
        self.assertEqual(
            record["direction"]["person_reference"]["video_sha256"],
            self.job.inputs["video"]["sha256"],
        )
        self.assertEqual(
            record["direction"]["person_reference"]["path"],
            "03-cover-direction/person-reference.png",
        )

    def test_external_direction_preview_rejects_invalid_input_before_stage_write(self) -> None:
        stage = self.job.job_dir / "03-cover-direction"
        invalid = self.job.job_dir / "invalid-preview.png"
        invalid.write_bytes(_png())

        with self.assertRaisesRegex(cover_direction.CoverDirectionError, "direction preview PNG"):
            cover_direction.prepare_cover_direction(
                self.job, VALID_DIRECTION, direction_preview=invalid,
            )

        self.assertFalse(stage.exists())

        outside = self.root / "outside-preview.png"
        outside.write_bytes(_png())
        alias = self.job.job_dir / "linked-inputs"
        alias.symlink_to(self.job.job_dir, target_is_directory=True)
        for path in (outside, alias / invalid.name):
            with self.subTest(path=path), self.assertRaisesRegex(
                cover_direction.CoverDirectionError, "direction preview path",
            ):
                cover_direction.prepare_cover_direction(
                    self.job, VALID_DIRECTION, direction_preview=path,
                )
            self.assertFalse(stage.exists())

    def test_untraceable_title_is_rejected(self) -> None:
        invalid = copy.deepcopy(VALID_DIRECTION)
        invalid["title"] = "随机无关标题"

        with self.assertRaisesRegex(
            cover_direction.CoverDirectionError, "traceable"
        ):
            cover_direction.prepare_cover_direction(
                self.job, invalid, frame_reader=lambda *_args: _png()
            )

    def test_approved_record_reloads_and_detects_reference_change(self) -> None:
        first = self._prepare()
        state.approve(self.job, "cover_direction")
        loaded = cover_direction.load_approved_cover_direction(self.job)
        self.assertEqual(loaded["direction_sha256"], first["direction_sha256"])

        reference = self.job.job_dir / "03-cover-direction" / "person-reference.png"
        reference.write_bytes(b"changed")
        with self.assertRaisesRegex(
            cover_direction.CoverDirectionError, "identity changed"
        ):
            cover_direction.load_approved_cover_direction(self.job)

    def test_cover_provider_is_not_called_before_direction_approval(self) -> None:
        self._prepare()
        calls = []

        with self.assertRaisesRegex(cover.CoverError, "cover_direction"):
            cover.prepare_cover(
                self.job,
                provider=lambda *_args, **_kwargs: calls.append(1),
            )

        self.assertEqual(calls, [])

    def test_long_approved_subtitle_is_never_silently_truncated(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "9:16"
        direction["subtitle"] = "这是已经批准但超过十二个字的副标题文案"
        record = cover_direction.prepare_cover_direction(
            self.job, direction, frame_reader=lambda *_args: _png()
        )

        brief = cover._brief_from_approved_direction(
            record,
            headline_highlight_lines=[
                "这是已经批准但超过",
                "十二个字的副标题文案",
            ],
        )

        self.assertEqual(
            brief["headline"]["highlight"],
            ["这是已经批准但超过", "十二个字的副标题文案"],
        )
        self.assertEqual(
            "".join(brief["headline"]["highlight"]),
            direction["subtitle"],
        )

    def test_headline_line_overrides_fail_before_provider_for_non_impact_style(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "9:16"
        direction["composition"]["style_id"] = "style-07"
        direction["composition"]["person_width_ratio"] = 0.30
        direction["composition"]["blank_width_ratio"] = 0.65
        cover_direction.prepare_cover_direction(
            self.job, direction, frame_reader=lambda *_args: _png()
        )
        state.approve(self.job, "cover_direction")
        calls = []

        with self.assertRaises(cover.CoverError):
            cover.prepare_cover(
                self.job,
                headline_highlight_lines=["用进真实", "工作流"],
                headline_conclusion_lines=["工作流", "道具"],
                person_mask_provider=_person_mask,
                api_key="test-connection-value",
                base_url="https://openlux.invalid",
                provider=lambda *_args, **_kwargs: calls.append(1),
            )

        self.assertEqual(calls, [])

    def test_title_only_revision_reuses_persisted_base_without_provider(self) -> None:
        direction = copy.deepcopy(VALID_DIRECTION)
        direction["output_aspect_ratio"] = "9:16"
        wide_reference = io.BytesIO()
        Image.new("RGB", (720, 480), (120, 90, 70)).save(
            wide_reference, format="PNG"
        )
        cover_direction.prepare_cover_direction(
            self.job, direction,
            frame_reader=lambda *_args: wide_reference.getvalue(),
        )
        state.approve(self.job, "cover_direction")
        calls = []

        def provider(*_args, **_kwargs):
            calls.append(1)
            return _provider_response()

        first = cover.prepare_cover(
            self.job,
            headline_highlight_lines=["用进真实", "工作流"],
            headline_conclusion_lines=["工作流", "道具"],
            person_mask_provider=_person_mask,
            api_key="test-connection-value",
            base_url="https://openlux.invalid",
            provider=provider,
        )
        self.assertTrue((first.parent / "cover-base.png").is_file())
        original_final = first.read_bytes()
        original_base = (first.parent / "cover-base.png").read_bytes()
        state.approve(self.job, "cover")
        state.revise(self.job, "cover", "只调整标题分行")

        second = cover.prepare_cover(
            self.job,
            headline_highlight_lines=["用进", "真实工作流"],
            headline_conclusion_lines=["工作", "流道具"],
            person_mask_provider=_person_mask,
            api_key="test-connection-value",
            base_url="https://openlux.invalid",
            provider=provider,
        )

        self.assertEqual(calls, [1])
        report = json.loads(
            (second.parent / "cover-report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["mode"], "title-only-base-reuse")
        self.assertTrue(report["base_reused"])
        self.assertEqual((second.parent / "cover-base.png").read_bytes(), original_base)
        self.assertNotEqual(second.read_bytes(), original_final)
        self.assertFalse((second.parent / "cover-thumbnail-200.png").exists())
        from edit.hd.tools import qa_delivery_v2

        state.approve(self.job, "cover")
        sources = qa_delivery_v2._cover_sources(state.load_job(self.job.job_dir))
        self.assertEqual(sources["cover/cover-9x16.png"], second.parent / "cover-9x16.png")
        with Image.open(second) as image:
            image.load()
            self.assertEqual(image.size, (1080, 1920))

    def test_approved_direction_generates_native_full_v2_cover_once(self) -> None:
        direction = self._prepare()
        state.approve(self.job, "cover_direction")
        calls = []

        def provider(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return _provider_response()

        output = cover.prepare_cover(
            self.job,
            person_mask_provider=_person_mask,
            api_key="test-connection-value",
            base_url="https://openlux.invalid",
            provider=provider,
        )

        self.assertEqual(output.parent.name, "04-cover")
        self.assertEqual(len(calls), 1)
        report = json.loads(
            (output.parent / "cover-report.json").read_text(encoding="utf-8")
        )
        brief = json.loads(
            (output.parent / "cover-brief.json").read_text(encoding="utf-8")
        )
        self.assertEqual(brief["headline"]["conclusion"], "工作流道具")
        self.assertEqual(report["direction_sha256"], direction["direction_sha256"])
        self.assertEqual(
            report["reference_sha256"],
            direction["direction"]["person_reference"]["sha256"],
        )
        self.assertEqual(
            set(report["output_sha256"]),
            {
                "cover-base.png",
                "cover-brief.json",
                "cover-3x4.png",
                "cover-delivery-raster.png",
            },
        )
        self.assertTrue((output.parent / "material-usage.json").is_file())
        self.assertIn(
            "04-cover/material-usage.json",
            {item["path"] for item in self.job.stages["cover"]["artifacts"]},
        )
        with Image.open(output.parent / "cover-3x4.png") as image:
            self.assertEqual(image.size, (1080, 1440))
        self.assertEqual(self.job.stages["cover"]["status"], "ready_for_review")
        from edit.hd.tools import qa_delivery_v2

        workflow_before = (self.job.job_dir / "workflow.json").read_bytes()
        review = cover.review_cover(self.job)
        self.assertEqual(review["stage"], "cover")
        self.assertEqual(review["final_image"], str(output))
        self.assertNotIn("thumbnail", review)
        self.assertNotIn("thumbnail_status", review)
        self.assertEqual(set(review["images"]), {"final"})
        final_snapshot = base64.b64decode(review["images"]["final"]["base64"])
        self.assertEqual(final_snapshot, output.read_bytes())
        self.assertEqual(review["images"]["final"]["sha256"],
                         hashlib.sha256(final_snapshot).hexdigest())
        command = [sys.executable, "-m", "edit.hd.tools.cli", "review-cover",
                   "--job", str(self.job.job_dir)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), review)
        self.assertEqual((self.job.job_dir / "workflow.json").read_bytes(), workflow_before)
        with self.assertRaises(qa_delivery_v2.DeliveryV2Error):
            qa_delivery_v2._cover_sources(self.job)
        final_bytes = output.read_bytes()
        try:
            output.write_bytes(b"invalid image")
            self.assertEqual(base64.b64decode(review["images"]["final"]["base64"]),
                             final_bytes)
            failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(failed.stdout, "")
            self.assertEqual(output.read_bytes(), b"invalid image")
            self.assertEqual((self.job.job_dir / "workflow.json").read_bytes(), workflow_before)
        finally:
            output.write_bytes(final_bytes)

        # Test-only approval: consume the actual publisher output and receipt,
        # not a hand-built delivery report or mocked artifact inventory.
        state.approve(self.job, "cover")
        reloaded = state.load_job(self.job.job_dir)
        before = {path.name: path.read_bytes() for path in output.parent.iterdir()}
        sources = qa_delivery_v2._cover_sources(reloaded)
        self.assertEqual(sources["cover/cover-delivery-raster.png"], output)
        self.assertEqual(set(sources), {
            "cover/cover-3x4.png", "cover/cover-delivery-raster.png",
            "cover/cover-report.json",
        })
        self.assertEqual(report["version"], 3)
        self.assertNotIn("review_thumbnail", report)
        self.assertFalse((output.parent / "cover-thumbnail-200.png").exists())
        self.assertEqual(before, {
            path.name: path.read_bytes() for path in output.parent.iterdir()
        })
        state.revise(reloaded, "cover", "测试撤回封面审核")
        with self.assertRaises(cover.CoverError):
            cover.review_cover(self.job)  # stale in-memory ready state must not pass
        failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(failed.stdout, "")


if __name__ == "__main__":
    unittest.main()

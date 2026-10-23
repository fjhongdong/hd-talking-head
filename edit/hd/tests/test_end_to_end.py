"""End-to-end coverage for the current twelve-stage HD workflow."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw
from edit.hd.tests.test_avatar_contract import avatar_fixture

from edit.hd.tools import (
    broll_component_executor,
    cli,
    content_analysis,
    contract_artifacts,
    cover,
    cover_direction,
    edit_timeline,
    inspect_inputs,
    material_usage,
    preview,
    qa_delivery,
    state,
    subtitles,
    transcribe,
    visual_assets,
    visual_canary,
    visual_plan,
)


MEDIA_RUNTIME_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SCRIPT = "学了AI却用不好。不是能力没到，是标准变了。真正重要的是把AI用进真实工作流。"
SOURCE_TEXT = "不是能力没到，是标准变了"


def _png_bytes(
    size: tuple[int, int] = (1024, 1536),
    color: tuple[int, int, int] = (42, 78, 126),
) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def _person_mask(source: bytes) -> bytes:
    with Image.open(io.BytesIO(source)) as image:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse(
            (image.width // 8, 0, image.width * 7 // 8, image.height),
            fill=255,
        )
        stream = io.BytesIO()
        mask.save(stream, format="PNG")
        return stream.getvalue()


def _create_source_video(path: Path, *, duration: float = 3.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s=540x960:r=24:d={duration}",
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest",
            str(path),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def _analysis(script_text: str) -> dict[str, object]:
    source_text = SOURCE_TEXT if SOURCE_TEXT in script_text else script_text
    start = script_text.index(source_text)
    end = start + len(source_text)
    keyword = "标准变了" if "标准变了" in source_text else source_text
    return {
        "thesis": script_text,
        "hook": script_text,
        "sections": [{
            "id": "section-01", "title": "内容判断",
            "source_span": [0, len(script_text)],
        }],
        "items": [{
            "id": "idea-01", "source_text": source_text,
            "source_span": [start, end], "priority": "critical",
            "keywords": [keyword], "semantic_type": "thesis",
            "evidence_status": "supported", "broll_priority": "high",
        }],
        "claims": [],
    }


def _cover_direction() -> dict[str, object]:
    return {
        "output_aspect_ratio": "9:16",
        "title": "标准变了",
        "subtitle": "真实工作流",
        "person_reference": {"source": "current-aroll-video", "timestamp": 0.75},
        "pose": "人物正面指向右侧工作流面板，露出头肩和双手",
        "expression": "坚定、直视镜头",
        "environment": "深色 AI 工作流工作室",
        "props": ["工作流面板", "任务卡片"],
        "composition": {
            "style_id": "style-01", "person_side": "right",
            "person_width_ratio": 0.55, "blank_width_ratio": 0.35,
        },
        "palette": {
            "background": "dark-ai-workflow-studio",
            "font_color": "#FFFFFF", "accent_color": "#FFD84D",
        },
        "typography": {"font_style": "heavy-sans"},
        "safe_zones": {"safe_margin_ratio": 0.10},
        "prompt_allow": ["人物脸部完整", "主题化环境", "工作流道具"],
        "prompt_deny": ["文字遮挡人脸", "仅有头部", "无关场景"],
    }


def _cleanup_plan(script_text: str, duration: float) -> dict[str, object]:
    return {
        "version": 1,
        "segments": [{
            "action": "keep", "word_start": 0, "word_end": 1,
            "source_start": 0.0, "source_end": duration,
            "original_sentence": script_text, "cleaned_sentence": script_text,
            "reason": "保留完整语义段",
            "breathing_padding": {"before": 0.0, "after": 0.0},
        }],
    }


def _transcribe_from_video_use_fixture(
    job: state.JobState,
    root: Path,
    *,
    text: str,
    duration: float,
) -> None:
    entrypoint = root / "video-use/helpers/transcribe.py"
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("# fixture entrypoint\n", encoding="utf-8")
    contract_artifacts.write_json_artifact(
        job.job_dir / "manifests/dependency-preflight.json",
        {"dependencies": [{
            "id": "video-use-runtime", "status": "bound",
            "availability_level": "bound", "resolved_path": str(entrypoint.parent.parent),
        }]},
    )
    raw = root / "scribe-fixture.json"
    contract_artifacts.write_json_artifact(raw, {"words": [
        {"type": "word", "text": text, "start": 0.0, "end": duration}
    ]})
    transcribe.transcribe_job(job, video_use_result=raw, invocation={
        "entrypoint": str(entrypoint), "exit_code": 0,
        "source_sha256": job.inputs["video"]["sha256"],
        "result_sha256": contract_artifacts.sha256_file(raw),
    })
    edit_timeline.generate_cleanup_proposal(job, _cleanup_plan(text, duration))


def _approve(job: state.JobState, stage_id: str) -> None:
    persisted = state.load_job(job.job_dir)
    if persisted.stages[stage_id]["status"] != "ready_for_review":
        raise AssertionError(f"{stage_id} did not reach ready_for_review")
    state.approve(persisted, stage_id)
    state._synchronize_committed_job(job)


def _approve_placeholder(job: state.JobState, stage_id: str, relative: str) -> None:
    artifact = job.job_dir / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    contract_artifacts.write_json_artifact(artifact, {"schema_version": 1})
    state.mark_ready(job, stage_id, (artifact,))
    state.approve(job, stage_id)


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | None]]:
    snapshot: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = (
                "symlink",
                os.readlink(path).encode("utf-8", errors="surrogateescape"),
            )
        elif path.is_dir():
            snapshot[relative] = ("directory", None)
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        else:
            snapshot[relative] = ("other", None)
    return snapshot


@unittest.skipUnless(MEDIA_RUNTIME_AVAILABLE, "ffmpeg and ffprobe are required")
class TranscriptCorrectionCliEndToEndTests(unittest.TestCase):
    def _approved_job(self, root: Path) -> state.JobState:
        video = root / "source.mp4"
        script = root / "script.txt"
        _create_source_video(video, duration=2.0)
        script.write_text("这个错词需要修正", encoding="utf-8")
        job = state.create_job(root, video, script, profile="full-v2")
        inspect_inputs.inspect_job(job)
        _approve(job, "inspect")
        content_analysis.prepare_content_analysis(job, _analysis(script.read_text()))
        _approve(job, "content_analysis")
        _approve_placeholder(
            job, "cover_direction", "03-cover-direction/cover-direction.json"
        )
        _approve_placeholder(job, "cover", "04-cover/cover-report.json")
        _transcribe_from_video_use_fixture(job, root, text="错词", duration=2.0)
        _approve(job, "speech_cleanup")
        edit_timeline.render_edit(job)
        _approve(job, "edit_structure")
        return job

    @staticmethod
    def _manifest(job: object, root: Path) -> Path:
        source = next(
            record for record in job.stages["speech_cleanup"]["lineage"]
            if record["path"] == "05-speech-cleanup/word-transcript.json"
        )
        manifest = {
            "version": 1,
            "source": {key: source[key] for key in ("path", "sha256", "bytes")},
            "corrections": [{
                "word_start": 0, "word_end": 1,
                "expected_words": [{"text": "错词", "start": 0.0, "end": 2.0}],
                "replacement_texts": ["正词"],
                "reason": "按录音人工核对",
            }],
        }
        path = root / "corrections.json"
        contract_artifacts.write_json_artifact(path, manifest)
        return path

    def test_apply_cleanup_corrections_rebuilds_only_after_explicit_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._approved_job(root)
            state.revise(job, "speech_cleanup", "修正人工核对错词")
            corrections = self._manifest(job, root)
            with mock.patch.object(cli, "_emit") as emit:
                result = cli.main([
                    "apply-cleanup-corrections", "--job", str(job.job_dir),
                    "--corrections", str(corrections),
                ])
            self.assertEqual(result, 0)
            emit.assert_called_once()
            persisted = state.load_job(job.job_dir)
            self.assertEqual(
                persisted.stages["speech_cleanup"]["status"], "ready_for_review"
            )
            self.assertEqual(persisted.stages["edit_structure"]["status"], "pending")
            corrected = contract_artifacts.read_json_artifact(
                job.job_dir / "05-speech-cleanup/word-transcript.json"
            )
            self.assertEqual(corrected["words"][0]["text"], "正词")

    def test_apply_cleanup_corrections_never_revises_an_approved_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._approved_job(root)
            lineage = []
            for artifact in job.stages["speech_cleanup"]["artifacts"]:
                path = job.job_dir / artifact["path"]
                status, parent = os.lstat(path), os.lstat(path.parent)
                lineage.append({
                    **artifact,
                    "device": status.st_dev, "inode": status.st_ino,
                    "parent_device": parent.st_dev,
                    "parent_inode": parent.st_ino,
                })
            manifest_job = mock.Mock()
            manifest_job.stages = {"speech_cleanup": {"lineage": lineage}}
            corrections = self._manifest(manifest_job, root)
            with mock.patch.object(cli, "_emit") as emit:
                result = cli.main([
                    "apply-cleanup-corrections", "--job", str(job.job_dir),
                    "--corrections", str(corrections),
                ])
            self.assertEqual(result, 2)
            emit.assert_not_called()
            persisted = state.load_job(job.job_dir)
            self.assertEqual(persisted.stages["speech_cleanup"]["status"], "approved")
            self.assertEqual(persisted.stages["edit_structure"]["status"], "approved")

    def test_cleanup_lineage_requires_valid_material_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._approved_job(root)
            state.revise(job, "speech_cleanup", "修正人工核对错词")
            receipt_path = job.job_dir / "05-speech-cleanup/material-usage.json"
            receipt = contract_artifacts.read_json_artifact(receipt_path)
            receipt["job_id"] = "another-job"
            contract_artifacts.write_json_artifact(receipt_path, receipt)
            record = next(r for r in job.stages["speech_cleanup"]["lineage"]
                          if r["path"].endswith("/material-usage.json"))
            status = receipt_path.stat()
            record.update(sha256=contract_artifacts.sha256_file(receipt_path),
                          bytes=status.st_size, device=status.st_dev, inode=status.st_ino)
            with self.assertRaisesRegex(RuntimeError, "receipt identity"):
                edit_timeline._cleanup_lineage_pins(job, generation_name="05-speech-cleanup")
            job.stages["speech_cleanup"]["lineage"].remove(record)
            with self.assertRaises(edit_timeline.EditTimelineError):
                edit_timeline._cleanup_lineage_pins(job, generation_name="05-speech-cleanup")


class VisualDirectionMigrationTests(unittest.TestCase):
    def test_old_visual_plan_is_rejected_without_any_job_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            video, script = root / "source.mp4", root / "script.txt"
            video.write_bytes(b"source")
            script.write_text("现行十二阶段测试文案", encoding="utf-8")
            job = state.create_job(root, video, script, profile="full-v2")
            for stage_id, relative in (
                ("inspect", "01-inspect/report.json"),
                ("content_analysis", "02-content-analysis/content-analysis.json"),
                ("cover_direction", "03-cover-direction/cover-direction.json"),
                ("cover", "04-cover/cover-report.json"),
                ("speech_cleanup", "05-speech-cleanup/word-transcript.json"),
                ("edit_structure", "06-edit-structure/edit-plan.json"),
            ):
                _approve_placeholder(job, stage_id, relative)
            brief = root / "old-visual-plan.json"
            contract_artifacts.write_json_artifact(brief, {"version": 1, "segments": []})
            preview_root = root / "official-previews"
            preview_root.mkdir()
            before = _tree_snapshot(job.job_dir)
            freezer, compiler, writer = mock.Mock(), mock.Mock(), mock.Mock()
            with self.assertRaisesRegex(
                visual_plan.VisualPlanError, "^BROLL_SCHEMA_UNSUPPORTED$"
            ):
                visual_plan.prepare_visual_direction(
                    job, brief, preview_root,
                    candidate_freezers={"ai_generated": freezer},
                    strategy_compiler=compiler, state_writer=writer,
                )
            after = _tree_snapshot(job.job_dir)
            self.assertEqual(after, before)
            self.assertEqual(
                state.load_job(job.job_dir).stages["visual_direction"]["status"],
                "pending",
            )
            freezer.assert_not_called()
            compiler.assert_not_called()
            writer.assert_not_called()


@unittest.skipUnless(MEDIA_RUNTIME_AVAILABLE, "ffmpeg and ffprobe are required")
class FullV2EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.source_fixture = Path(cls.fixture_directory.name).resolve() / "source-3s.mp4"
        _create_source_video(cls.source_fixture, duration=3.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_directory.cleanup()

    @staticmethod
    def _visual_intent() -> dict[str, object]:
        return {
            "segment_id": "seg-001",
            "statement": "用经批准的动态画面解释标准变化。",
            "semantic_goals": ["explain"],
            "claims": [{
                "type": "concept", "value": "标准已经变化。",
                "verification_required": False,
            }],
            "entities": [], "relations": [],
            "requirements": {
                "verifiability": "medium", "realism": "medium",
                "abstraction": "medium", "product_specificity": "low",
                "emotional_intensity": "low",
            },
            "presenter_presence": "allowed",
        }

    def _visual_brief(
        self, path: Path, *, duration: float, component_sha256: str, arroll_sha256: str
    ) -> None:
        binding = {
            "provider": "xAI", "model": "grok-imagine-video",
            "endpoint_id": "video-generation",
            "prompt_sha256": hashlib.sha256(b"approved fixture prompt").hexdigest(),
            "generation_id": "fixture-generation-001", "sha256": component_sha256,
        }
        segment = {
            "segment_id": "seg-001", "start": 0.0, "end": duration,
            "content_item_ids": ["idea-01"], "visible_text": [],
            "visual_intent": self._visual_intent(),
            "visual_strategy": {
                "schema_version": 1, "segment_id": "seg-001", "mode": "single",
                "rationale": "动态画面直接解释当前语义。",
                "components": [{
                    "component_id": "component-1", "kind": "ai_generated",
                    "semantic_role": "explanation", "layer_role": "base",
                    "media_type": "image", "layout_slot": "main",
                    "brief": "生成一张可视化标准变化的竖版画面。",
                }],
                "composition": {
                    "family": "single_full_frame", "presenter_mode": "bottom_window",
                    "avatar": avatar_fixture(frames=round(duration * 24), source_sha256=arroll_sha256),
                    "reading_order": ["component-1"], "component_dependencies": [],
                },
            },
            "candidate_snapshots": {}, "bindings": {"component-1": binding},
            "strategy_revision": 1,
        }
        contract_artifacts.write_json_artifact(
            path, {"schema_version": 3, "segments": [segment]}
        )

    @staticmethod
    def _component_adapters(payload: bytes, calls: list[str]) -> dict[str, object]:
        def invoke(context: broll_component_executor.AdapterContext):
            calls.append(context.component_id)
            context.staging_path.write_bytes(payload)
            return broll_component_executor.AdapterResult(
                invocation_evidence={
                    "adapter_id": "local-ai-fixture",
                    "actual_output_job_path": context.staging_job_path,
                },
                qa={"passed": True, "checks": ["fixture_completed"]},
            )

        def probe(_path: Path, media_type: str, contract: object):
            if media_type != "image":
                raise AssertionError("the fixture emits one image")
            return {
                "media_type": "image", "container": "png", "codec": "png",
                "pixel_format": "rgba" if contract["alpha"] else "rgb24",
                "alpha": bool(contract["alpha"]), "width": 1080, "height": 1920,
                "fps": None, "frame_count": 1, "duration": None,
            }

        return {
            "ai_generated": broll_component_executor.KindAdapter(
                kind="ai_generated", approved_executor="OpenMontage:GrokVideo",
                adapter_id="local-ai-fixture", adapter_version="1.0.0",
                artifact_media_type="image", invoke=invoke, provider="xAI",
                model="grok-imagine-video", endpoint_id="video-generation",
            ),
            "artifact_probe": broll_component_executor.ArtifactProbe(
                probe_id="local-image-probe", probe_version="1.0.0", probe=probe,
            ),
        }

    def test_full_v2_builds_a_real_vertical_delivery_from_one_approved_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            video, script = root / "source.mp4", root / "script.txt"
            shutil.copyfile(self.source_fixture, video)
            script.write_text(SCRIPT, encoding="utf-8")
            job = state.create_job(root, video, script, profile="full-v2")
            approvals: list[str] = []

            inspect_inputs.inspect_job(job)
            _approve(job, "inspect")
            approvals.append("inspect")
            analysis = content_analysis.prepare_content_analysis(job, _analysis(SCRIPT))
            _approve(job, "content_analysis")
            approvals.append("content_analysis")
            direction = cover_direction.prepare_cover_direction(
                job, _cover_direction(), frame_reader=lambda *_args: _png_bytes((480, 720))
            )
            self.assertEqual(
                state.load_job(job.job_dir).stages["cover_direction"]["status"],
                "ready_for_review",
            )
            _approve(job, "cover_direction")
            approvals.append("cover_direction")

            provider_calls: list[str] = []
            cover.prepare_cover(
                job, person_mask_provider=_person_mask, api_key="fixture-key",
                base_url="https://fixture.invalid",
                provider=lambda prompt, **_kwargs: (
                    provider_calls.append(prompt)
                    or {"data": [{
                        "b64_json": base64.b64encode(_png_bytes()).decode("ascii")
                    }]}
                ),
            )
            self.assertEqual(len(provider_calls), 1)
            self.assertEqual(
                state.load_job(job.job_dir).stages["cover"]["status"],
                "ready_for_review",
            )
            _approve(job, "cover")
            approvals.append("cover")

            _transcribe_from_video_use_fixture(job, root, text=SCRIPT, duration=3.0)
            _approve(job, "speech_cleanup")
            approvals.append("speech_cleanup")
            edit_timeline.render_edit(job)
            _approve(job, "edit_structure")
            approvals.append("edit_structure")
            timeline = contract_artifacts.read_json_artifact(
                job.job_dir / "06-edit-structure/timeline-map.json"
            )
            duration = float(timeline["output_duration"])
            self.assertEqual(round(duration * 24), duration * 24)

            component_payload = _png_bytes((1080, 1920), (196, 86, 42))
            director_brief = root / "visual-direction-v3.json"
            self._visual_brief(
                director_brief, duration=duration,
                component_sha256=hashlib.sha256(component_payload).hexdigest(),
                arroll_sha256=contract_artifacts.sha256_file(
                    job.job_dir / "06-edit-structure/edited-aroll.mp4"
                ),
            )
            preview_root = root / "official-previews"
            preview_root.mkdir()
            plan_path = visual_plan.prepare_visual_direction(
                job, director_brief, preview_root
            )
            plan = contract_artifacts.read_json_artifact(plan_path)
            self.assertEqual(plan["schema_version"], 3)
            self.assertEqual(plan["segments"][0]["shot_recipe"]["schema_version"], 2)
            self.assertEqual(
                plan["content_analysis_sha256"], analysis["analysis_sha256"]
            )
            _approve(job, "visual_direction")
            approvals.append("visual_direction")

            adapter_calls: list[str] = []
            adapters = self._component_adapters(component_payload, adapter_calls)
            canary = visual_canary.prepare_visual_canary(
                job, segment_ids=("seg-001",), component_adapters=adapters
            )
            self.assertEqual(canary["segment_ids"], ["seg-001"])
            canary_segment = (
                job.job_dir / "08-visual-canary/segments/seg-001/segment.mp4"
            )
            canary_segment_bytes = canary_segment.read_bytes()
            canary_segment_sha256 = hashlib.sha256(canary_segment_bytes).hexdigest()
            self.assertEqual(len(canary["segments"]), 1)
            canary_segment_record = canary["segments"][0]
            self.assertEqual(canary_segment_record["segment_id"], "seg-001")
            self.assertEqual(
                canary_segment_record["video_bytes"], len(canary_segment_bytes)
            )
            self.assertEqual(
                canary_segment_record["video_sha256"], canary_segment_sha256
            )
            self.assertEqual(
                contract_artifacts.read_json_artifact(
                    canary_segment.parent / "segment-manifest.json"
                ),
                canary_segment_record,
            )
            _approve(job, "visual_canary")
            approvals.append("visual_canary")
            visual_track = visual_assets.prepare_visual_assets(
                job, component_adapters=adapters
            )
            formal_segment = (
                job.job_dir / "09-visual-assets/segments/seg-001/segment.mp4"
            )
            formal_segment_bytes = formal_segment.read_bytes()
            asset_manifest = contract_artifacts.read_json_artifact(
                job.job_dir / "09-visual-assets/asset-manifest.json"
            )
            self.assertEqual(adapter_calls, ["component-1"])
            self.assertEqual(formal_segment_bytes, canary_segment_bytes)
            self.assertEqual(
                hashlib.sha256(formal_segment_bytes).hexdigest(),
                canary_segment_sha256,
            )
            self.assertEqual(
                asset_manifest["reused_canary_segment_ids"], ["seg-001"]
            )
            formal_segment_record = next(
                record
                for record in asset_manifest["segments"]
                if record["segment_id"] == "seg-001"
            )
            self.assertEqual(
                formal_segment_record["video_sha256"],
                canary_segment_sha256,
            )
            self.assertEqual(
                formal_segment_record["video_bytes"], len(formal_segment_bytes)
            )
            self.assertTrue(visual_track.is_file())
            _approve(job, "visual_assets")
            approvals.append("visual_assets")

            subtitle_track = subtitles.prepare_subtitles(job)
            self.assertTrue(subtitle_track.is_file())
            _approve(job, "subtitles")
            approvals.append("subtitles")
            preview_result = preview.prepare_preview(job)
            self.assertTrue(preview_result.review.is_file())
            self.assertEqual(preview_result.qa_report["status"], "PASS")
            preview_expected = {
                "review.mp4",
                "qa-report.json",
                "source-manifest.json",
                "material-usage.json",
                *(f"keyframes/frame-{index:02d}.png" for index in range(1, 6)),
            }
            self.assertEqual(
                preview_expected,
                {
                    path.relative_to(preview_result.directory).as_posix()
                    for path in preview_result.artifacts
                },
            )
            preview_state = state.load_job(job.job_dir)
            preview_receipt = material_usage.load_current_receipt(preview_state, "preview")
            self.assertEqual(preview_receipt["job_id"], job.job_id)
            self.assertEqual(preview_receipt["stage_id"], "preview")
            self.assertIs(preview_receipt["complete_reference_declaration"], True)
            self.assertEqual(
                preview_expected,
                {
                    Path(record["path"]).relative_to("11-preview").as_posix()
                    for record in preview_state.stages["preview"]["artifacts"]
                },
            )
            qa_report_base = {
                key: value
                for key, value in preview_result.qa_report.items()
                if key != "qa_report_sha256"
            }
            self.assertEqual(
                preview_result.qa_report["qa_report_sha256"],
                contract_artifacts.sha256_json(qa_report_base),
            )
            self.assertEqual(
                {f"keyframes/frame-{index:02d}.png" for index in range(1, 6)},
                {record["path"] for record in preview_result.qa_report["evidence"]},
            )
            for record in preview_result.qa_report["evidence"]:
                self.assertEqual(
                    record["sha256"],
                    contract_artifacts.sha256_file(
                        preview_result.directory / record["path"]
                    ),
                )
            _approve(job, "preview")
            approvals.append("preview")
            expected_delivery_revision = job.revision
            expected_delivery_workflow_sha256 = job.expected_sha256
            delivery = qa_delivery.prepare_delivery(job)
            final = delivery.directory / "final.mp4"
            self.assertTrue(final.is_file())
            expected_delivery_sources = {
                "final.mp4": "11-preview/review.mp4",
                "qa/qa-report.json": "11-preview/qa-report.json",
                "source-manifest.json": "11-preview/source-manifest.json",
                "plans/content-analysis.json": (
                    "02-content-analysis/content-analysis.json"
                ),
                "plans/visual-plan.json": "07-visual-direction/visual-plan.json",
                "plans/asset-manifest.json": (
                    "09-visual-assets/asset-manifest.json"
                ),
                "plans/subtitle-plan.json": "10-subtitles/subtitle-plan.json",
                "subtitles/subtitles.srt": "10-subtitles/subtitles.srt",
                "subtitles/subtitles.webm": "10-subtitles/subtitles.webm",
                "cover/cover-9x16.png": "04-cover/cover-9x16.png",
                "cover/cover-delivery-raster.png": (
                    "04-cover/cover-delivery-raster.png"
                ),
                "cover/cover-report.json": "04-cover/cover-report.json",
            }
            manifest = delivery.manifest
            self.assertEqual(
                contract_artifacts.read_json_artifact(
                    delivery.directory / "delivery-manifest.json"
                ),
                manifest,
            )
            self.assertEqual(
                set(manifest),
                {
                    "schema_version",
                    "job_id",
                    "workflow_revision",
                    "workflow_sha256",
                    "final_sha256",
                    "canvas",
                    "background_music",
                    "artifacts",
                    "delivery_manifest_sha256",
                },
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["job_id"], job.job_id)
            self.assertEqual(
                manifest["workflow_revision"], expected_delivery_revision
            )
            self.assertEqual(
                manifest["workflow_sha256"], expected_delivery_workflow_sha256
            )
            self.assertEqual(
                manifest["canvas"], {"width": 1080, "height": 1920, "fps": 24}
            )
            self.assertIs(manifest["background_music"], False)
            self.assertEqual(
                set(manifest["artifacts"]), set(expected_delivery_sources)
            )
            delivery_expected = [
                *expected_delivery_sources,
                "delivery-manifest.json",
                "material-usage.json",
            ]
            self.assertEqual(
                sorted(delivery_expected),
                sorted(
                    path.relative_to(delivery.directory).as_posix()
                    for path in delivery.directory.rglob("*")
                    if path.is_file()
                ),
            )
            returned_artifacts = [
                path.relative_to(delivery.directory).as_posix()
                for path in delivery.artifacts
            ]
            self.assertEqual(len(returned_artifacts), len(delivery_expected))
            self.assertEqual(len(set(returned_artifacts)), len(returned_artifacts))
            self.assertEqual(
                returned_artifacts,
                delivery_expected,
            )
            delivery_state = state.load_job(job.job_dir)
            delivery_receipt = material_usage.load_current_receipt(delivery_state, "delivery")
            self.assertEqual(delivery_receipt["job_id"], job.job_id)
            self.assertEqual(delivery_receipt["stage_id"], "delivery")
            self.assertIs(delivery_receipt["complete_reference_declaration"], True)
            delivery_records = delivery_state.stages["delivery"]["artifacts"]
            delivery_record_paths = [
                Path(record["path"]).relative_to("12-delivery").as_posix()
                for record in delivery_records
            ]
            self.assertEqual(len(delivery_record_paths), len(delivery_expected))
            self.assertEqual(
                len(set(delivery_record_paths)), len(delivery_record_paths)
            )
            self.assertEqual(
                delivery_record_paths,
                delivery_expected,
            )
            for relative, source_relative in expected_delivery_sources.items():
                source = job.job_dir / source_relative
                output = delivery.directory / relative
                source_record = {
                    "path": source_relative,
                    "sha256": contract_artifacts.sha256_file(source),
                    "bytes": source.stat().st_size,
                }
                output_record = {
                    "path": relative,
                    "sha256": contract_artifacts.sha256_file(output),
                    "bytes": output.stat().st_size,
                }
                self.assertEqual(
                    manifest["artifacts"][relative],
                    {"source": source_record, "output": output_record},
                )
                self.assertEqual(source_record["sha256"], output_record["sha256"])
                self.assertEqual(source_record["bytes"], output_record["bytes"])
            manifest_base = {
                key: value
                for key, value in manifest.items()
                if key != "delivery_manifest_sha256"
            }
            self.assertEqual(
                manifest["delivery_manifest_sha256"],
                contract_artifacts.sha256_json(manifest_base),
            )
            self.assertEqual(
                manifest["final_sha256"],
                manifest["artifacts"]["final.mp4"]["output"]["sha256"],
            )
            for record in delivery_records:
                output = job.job_dir / record["path"]
                self.assertEqual(
                    record,
                    {
                        "path": record["path"],
                        "sha256": contract_artifacts.sha256_file(output),
                        "bytes": output.stat().st_size,
                    },
                )
            _approve(job, "delivery")
            approvals.append("delivery")

            persisted = state.load_job(job.job_dir)
            self.assertEqual(state.stage_ids_for(persisted), state.FULL_V2_STAGE_IDS)
            self.assertEqual(tuple(approvals), state.FULL_V2_STAGE_IDS)
            self.assertTrue(all(
                persisted.stages[stage_id]["status"] == "approved"
                for stage_id in state.FULL_V2_STAGE_IDS
            ))
            self.assertEqual(direction["direction"]["output_aspect_ratio"], "9:16")
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-count_frames", "-show_streams",
                    "-show_format", "-of", "json", str(final),
                ],
                check=True, capture_output=True, text=True, timeout=120,
            )
            media = json.loads(probe.stdout)
            videos = [s for s in media["streams"] if s["codec_type"] == "video"]
            audios = [s for s in media["streams"] if s["codec_type"] == "audio"]
            self.assertEqual((len(videos), len(audios)), (1, 1))
            self.assertEqual(
                (videos[0]["width"], videos[0]["height"], videos[0]["avg_frame_rate"]),
                (1080, 1920, "24/1"),
            )
            self.assertAlmostEqual(
                float(media["format"]["duration"]), duration, delta=1 / 24
            )


if __name__ == "__main__":
    unittest.main()

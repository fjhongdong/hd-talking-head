"""The user approves a proposal once; production binds and compiles afterwards."""
from __future__ import annotations
import copy
import sys
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env
import run_stage
from edit.hd.tests import test_visual_direction as fixture_api
from edit.hd.tools import contract_artifacts as artifacts, state, visual_confirmation as vc

class VisualConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_api.VisualDirectionSchemaV3Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.job = self.fixture.job
        self.fixture._write_brief(fixture_api.draft_segment(("external_stock",)))
        config = self.job.job_dir / "manifests/provider-config.json"
        config.parent.mkdir(exist_ok=True)
        artifacts.write_json_artifact(config, {"schema_version": 1, "providers": [],
            "max_concurrency": 1, "generation_enabled": False})
        self.treatment = self.fixture.root / "treatment.json"
        artifacts.write_json_artifact(self.treatment, {
            "semantic_lists": {"overlay": [], "broll": [{"row_id": "sem-broll-1", "start_word": 0,
                "end_word": 1, "quote": "实际剪后口播", "semantic": "资料解释", "visual_task": "展示资料",
                "components": [{"segment_id": "seg-001", "component_id": "component-1"}]}]},
            "beat_sheet": [{"start_word": 0, "end_word": 1, "quote": "实际剪后口播",
                            "decision": "broll", "visual": "资料画面承接口播",
                            "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
                            "reason": "用具体资料画面解释这句口播"}],
            "motion_queries": [{"segment_id": "seg-001", "component_id": "component-1",
                                "tags": ["approved visual explanation"]}], "overlay_selection": [],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                "fixed_context": [{"segment_id": "seg-001", "component_id": "component-1",
                                   "visual_pattern": "existing material", "source_ref": "asset-1", "skill_id": "Example Stock",
                                   "start": 0.0, "end": 3.0}],
                "recent_context": [], "history_note": "synthetic fixture"}})
        from edit.hd.tools import motion_match_cache
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        artifacts.write_json_artifact(self.treatment,
            motion_match_cache.match_once(_env.PROJECT, director, treatment))

    def prepare(self):
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                        return_value=[{"text": "实际剪后口播", "start": 0.0, "end": 3.0}]):
            return vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)

    def confirm(self):
        review = {k: copy.deepcopy(v) for k, v in run_stage._summary(self.job, "visual_direction").items()
                  if k in {"job_id", "job_dir", "stage", "revision", "artifacts"}}
        review.update(passed=True, note="synthetic host inspected the proposed content",
                      user_confirmation="synthetic approval of this exact complete list")
        return run_stage._review(self.job, "visual_direction", review)

    def test_new_proposal_requires_complete_beat_sheet(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment.pop("beat_sheet")
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "beat_sheet"):
            self.prepare()

    def test_beat_sheet_rejects_gap_or_stale_quote(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["quote"] = "过期口播"
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "quote"):
            self.prepare()

    def test_beat_sheet_accepts_actual_full_frame_strategy(self):
        director = {"segments": [{"start": 0, "end": 3,
            "visual_strategy": {"mode": "none", "components": [],
                "composition": {"family": "no_broll", "presenter_mode": "full_frame"}}}]}
        treatment = {"beat_sheet": [{"start_word": 0, "end_word": 1,
            "quote": "开场", "decision": "aroll", "visual": "真人开场称呼",
            "components": [], "reason": "保留真人视线和称呼，建立交流"}]}
        speech = [{"text": "开场", "start": 0, "end": 2.5}]
        vc._validate_beat_sheet(treatment, director, speech)
        director["segments"][0]["visual_strategy"]["mode"] = "single"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "full-frame"):
            vc._validate_beat_sheet(treatment, director, speech)

    def test_beat_sheet_allows_continuous_parallel_components(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director["segments"][0]["visual_strategy"]["components"].append(
            {"component_id": "component-2", "kind": "external_stock", "layer_role": "base"})
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"].append(
            {"segment_id": "seg-001", "component_id": "component-2"})
        treatment["beat_sheet"][0]["merge_reason"] = "两个并列画面共同承接同一段连续动作"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "实际剪后口播", "start": 0.0, "end": 3.0}])

    def test_reused_component_requires_merge_reason_on_each_beat(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "实际", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "剪后口播", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
             "merge_reason": "同一连续资料画面覆盖后半句"}]
        with self.assertRaisesRegex(vc.VisualConfirmationError, "reused"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "实际", "start": 0.0, "end": 1.0},
                                     {"text": "剪后口播", "start": 1.0, "end": 3.0}])
        treatment["beat_sheet"][0]["merge_reason"] = "同一连续资料画面覆盖前半句"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "实际", "start": 0.0, "end": 1.0},
                                 {"text": "剪后口播", "start": 1.0, "end": 3.0}])

    def test_beat_sheet_rejects_unknown_component_and_uncovered_time(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"][0]["component_id"] = "missing"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "unknown"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "实际剪后口播", "start": 0.0, "end": 3.0}])

    def test_proposal_precedes_compile_and_one_confirmation_completes_plan(self):
        proposal = self.prepare()
        self.assertFalse((self.job.job_dir / "07-visual-direction/visual-plan.json").exists())
        ready = self.confirm()
        self.assertIn("| 编号 | 时间 |", (proposal.parent / "visual-routing.md").read_text())
        numbered = vc.approved_numbered_rows(self.job)
        self.assertEqual([(row["row_id"], row["number"]) for row in numbered],
                         [("seg-001:component-1", 1)])
        self.assertEqual(ready["review_required"], "host")
        self.assertEqual(self.job.stages["visual_direction"]["status"], "ready_for_review")
        approval = vc.validate_visual_authorization(self.job)["artifact"]
        original = (self.job.job_dir / approval["path"]).read_bytes()
        result = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(result["status"], "approved")
        final = state.load_job(self.job.job_dir)
        checked = vc.validate_visual_authorization(final, require_realized=True)
        self.assertEqual(checked["artifact"], approval)
        self.assertEqual(vc.approved_numbered_rows(final), numbered)
        self.assertEqual(original, (self.job.job_dir / approval["path"]).read_bytes())
        self.assertTrue(proposal.exists())
        changed = artifacts.read_json_artifact(self.fixture.brief)
        changed["segments"][0]["visual_intent"]["statement"] = "unapproved change"
        with self.assertRaises(vc.VisualConfirmationError):
            vc.validate_realization_draft(final, changed, artifacts.read_json_artifact(self.treatment))

    def test_time_coverage_failure_returns_to_semantics_before_publication(self):
        from edit.hd.tools import motion_match_cache
        stock = fixture_api.draft_segment(("external_stock",), end=1.0)
        presenter = fixture_api.draft_segment((), segment_id="seg-002", start=1.0, end=3.0)
        director = {"schema_version": 3, "segments": [stock, presenter]}
        from edit.hd.tools import avatar_profile
        director["segments"] = avatar_profile.plan_avatar_policy(director["segments"])["segments"]
        artifacts.write_json_artifact(self.fixture.brief, director)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["fixed_context"][0]["end"] = 1.0
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "实际剪后口播", "decision": "broll", "visual": "展示资料",
             "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "继续解释", "decision": "aroll", "visual": "真人解释",
             "components": [], "reason": "真人接着解释当前资料"}]
        treatment = motion_match_cache.match_once(_env.PROJECT, director, treatment)
        artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech", return_value=[
                {"text": "实际剪后口播", "start": 0.0, "end": 1.0},
                {"text": "继续解释", "start": 1.0, "end": 3.0}]):
            with self.assertRaisesRegex(vc.VisualConfirmationError, "time coverage.*affected semantic list"):
                vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)
        self.assertFalse((self.job.job_dir / vc.DIRECTORY).exists())

    def test_selected_image_to_video_channel_reaches_realized_template(self):
        self._selected_generation_flow("local_path")

    def test_uploaded_image_and_normalized_video_reach_realized_template(self):
        self._selected_generation_flow("upload")

    def _selected_generation_flow(self, reference_mode):
        from edit.hd.tools import generation_channels as channel, generation_queue as queue, startup
        import generated_media
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                  "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                    "endpoint_id": "fixture." + purpose, "connection_status": "verified",
                    "quota_status": "available", "reference_images": True, "native_9_16": True,
                    "silent_output": True} for purpose in ("image", "video")]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1,
             "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"},
             "video": {"model_binding": {"mode": "argument", "parameter": "model"},
                       "reference_mode": reference_mode,
                       "upload": {"tool": "fixture.upload", "arguments": {"file": {"$input": "path"}},
                                  "result_path": ["data", "asset_id"]},
                       "query": {"tool": "fixture.query", "arguments": {}, "task_ids_parameter": "task_ids"}}})
        segment = fixture_api.draft_segment(("ai_generated",))
        segment["bindings"]["component-1"] = {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        self.fixture._write_brief(segment)
        arguments_path = self.job.job_dir / "channel-arguments.json"
        artifacts.write_json_artifact(arguments_path, {"prompt": "fixture request"})
        cli = subprocess.run([sys.executable, str(_env.SKILL / "scripts/run_generation.py"),
            "--project-root", str(_env.PROJECT), "--job", str(self.job.job_dir), "prepare",
            "--purpose", "image", "--request-id", "fixture-cli", "--arguments-json", str(arguments_path)],
            cwd="/tmp", check=True, capture_output=True, text=True)
        import json
        self.assertEqual(json.loads(cli.stdout)["tool"], "fixture.image")
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = [{"segment_id": "seg-001", "component_id": "component-1", "tags": ["蓝色场景"]}]
        treatment["skill_selection"]["fixed_context"][0]["skill_id"] = "fixture"
        treatment["generation_plan"] = {"steps": [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "a blue scene"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "animate blue scene", "reference": {"$step": "image", "output": 0}}, "depends_on": ["image"]}]}
        artifacts.write_json_artifact(self.treatment, treatment)
        from edit.hd.tools import motion_match_cache
        treatment = motion_match_cache.match_once(
            _env.PROJECT, artifacts.read_json_artifact(self.fixture.brief), treatment)
        artifacts.write_json_artifact(self.treatment, treatment)
        self.prepare(); self.confirm()
        image = self.job.job_dir / "source-image.png"
        from PIL import Image
        Image.new("RGB", (1080, 1920), "blue").save(image)
        video = self.job.job_dir / "source-video.mp4"
        original_video = self.job.job_dir / "provider-original-30fps.mp4"
        source = original_video if reference_mode == "upload" else video
        rate = 30 if reference_mode == "upload" else 24
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=blue:s=1080x1920:r={rate}:d=3",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        if reference_mode == "upload":
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(original_video), "-r", "24", "-an",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        original_confirmation = vc.validate_visual_authorization(self.job)["artifact"]
        # Only the independent, already-tested startup gate is a fixture. Queue,
        # authorization, actions, result copying, compiler and adapters are real.
        with mock.patch.object(queue, "_approved", return_value=(self.job.job_id, "fixture-config", config)):
            actions = vc.generation_actions(self.job)
            self.assertNotIn("model", actions[0]["arguments"])
            self.assertEqual([a["tool"] for a in actions], ["fixture.image"])
            channel.record_result(self.job.job_dir, actions[0], {"status": "completed", "artifacts": [{"type": "image", "path": str(image)}]})
            actions = vc.generation_actions(self.job)
            if reference_mode == "upload":
                upload = actions[0]
                self.assertEqual(upload["tool"], "fixture.upload")
                self.assertTrue(Path(upload["arguments"]["file"]).is_file())
                self.assertEqual(vc.generation_actions(self.job)[0]["status"], "input_upload_pending")
                # Exercise the same stage entry the host uses for upload results.
                resumed = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"generation_results": [
                    {"action": upload, "response": {"data": {"asset_id": "actual-fixture-upload-id"}}}]})
                actions = resumed["actions"]
            self.assertEqual(actions[0]["tool"], "fixture.video")
            self.assertEqual(actions[0]["arguments"]["model"], "video-model")
            if reference_mode == "upload":
                self.assertEqual(actions[0]["arguments"]["reference"], "actual-fixture-upload-id")
            else:
                self.assertTrue(Path(actions[0]["arguments"]["reference"]).is_file())
            channel.record_result(self.job, actions[0], {"status": "pending", "task_ids": ["task-real-fixture"], "poll_after_seconds": 10})
            with mock.patch.object(channel.time, "time", return_value=time.time() + 60):
                query = vc.generation_actions(self.job)[0]
            self.assertEqual(query["tool"], "fixture.query")
            output = {"type": "video", "path": str(video)}
            if reference_mode == "upload":
                output.update(source={"path": str(original_video)}, processing="convert 30fps to 24fps; retain original")
                with self.assertRaisesRegex(ValueError, "both original source"):
                    channel.record_result(self.job, query, {"status": "completed", "artifacts": [
                        {key: value for key, value in output.items() if key != "source"}]})
            channel.record_result(self.job.job_dir, query, {"status": "completed", "artifacts": [output]})
            self.assertEqual(vc.generation_actions(self.job), [])
            proposal = vc.validate_visual_authorization(self.job)["source"]
            rid = vc._request_id(proposal, proposal["generation_steps"][1])
            aroll = next(r for r in self.job.stages["edit_structure"]["artifacts"] if r["path"].endswith("edited-aroll.mp4"))
            record = generated_media.record_from_queue(self.job, rid, segment_id="seg-001", component_id="component-1",
                source_binding={"aroll_sha256": aroll["sha256"], "start": 0.0, "end": 3.0},
                qa={"passed": True, "observed_scene": "Actual solid blue scene"},
                semantic_brief={"observed_scene": "Actual solid blue scene"}, ffprobe_executable="ffprobe")
            self.assertEqual(record["model"], "video-model")
            if reference_mode == "upload":
                self.assertTrue(Path(record["generation"]["source_media"]["path"]).is_file())
                self.assertEqual(record["generation"]["source_media"]["sha256"], artifacts.sha256_file(original_video))
                self.assertTrue(record["generation"]["input_bindings"])
                self.assertEqual(record["generation"]["submitted_request"]["arguments"]["reference"], "actual-fixture-upload-id")
                self.assertEqual(vc.validate_visual_authorization(self.job)["artifact"], original_confirmation)
            record_path = self.job.job_dir / "native-inputs/completed.json"
            artifacts.write_json_artifact(record_path, record)
            with self.assertRaisesRegex(ValueError, "another approved visual row"):
                generated_media.record_from_queue(self.job, rid, segment_id="wrong-row", component_id="component-1",
                    source_binding={}, qa={}, semantic_brief={}, ffprobe_executable="ffprobe")
            segment["bindings"]["component-1"] = generated_media.prepare_binding(record)
            realized_director = self.job.job_dir / "native-inputs/realized-director.json"
            artifacts.write_json_artifact(realized_director, {"schema_version": 3, "segments": [segment]})
            ref = vc._record(self.job.job_dir, record_path)
            treatment["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": ref["path"],
                 "completed_record": {"job_path": ref["path"], "sha256": ref["sha256"], "byte_count": ref["bytes"]}}]
            realized_treatment = self.job.job_dir / "native-inputs/realized-treatment.json"
            artifacts.write_json_artifact(realized_treatment, treatment)
            from edit.hd.tools import motion_capabilities
            motion_capabilities._ai_brief_evidence(self.job.job_dir, treatment, segment, "component-1")
            result = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"realization": {
                "director_brief": str(realized_director), "treatment": str(realized_treatment), "host_qa_note": "Actual blue media checked"}})
            self.assertEqual(result["status"], "approved")
            adapters = run_stage.native_component_adapters(_env.PROJECT, state.load_job(self.job.job_dir))
            self.assertIn(("seg-001", "component-1"), adapters["ai_generated"])
            self.assertTrue(image.is_file() and video.is_file())

    def test_startup_allows_one_selected_generation_channel(self):
        from edit.hd.tools import startup
        image = {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image",
                 "connection_status": "verified", "quota_status": "available"}
        config = {"generation_enabled": True, "providers": [image]}
        self.assertEqual(startup.selected_channels(config)["image"]["endpoint_id"], "fixture.image")
        video = {**image, "purpose": "video", "model": "video-model", "endpoint_id": "fixture.video"}
        config["providers"].append(video)
        self.assertEqual(startup.selected_channels(config)["video"]["endpoint_id"], "fixture.video")

    def test_unconfirmed_proposal_cannot_start_generation(self):
        self.prepare()
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)

    def test_confirmation_requires_explicit_motion_query_tags(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = []
        director = artifacts.read_json_artifact(self.fixture.brief)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "explicit semantic retrieval tags"):
            vc._rows(director, treatment, [])

    def test_direct_material_keeps_source_separate_from_template(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["tags"], ["approved visual explanation"])
        self.assertEqual(rows[0]["source"], "asset-1")
        self.assertEqual(rows[0]["template"], "素材直用（无动效模板）")
        self.assertEqual(rows[0]["channel"], "Example Stock")

    def test_creative_scene_is_not_presented_as_a_new_fixed_template(self):
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        director = artifacts.read_json_artifact(self.fixture.brief)
        segment = director["segments"][0]
        segment["visual_strategy"]["components"][0]["kind"] = "code_generated"
        segment["bindings"]["component-1"] = {"dependency_id": "openfilm-motion-graphics",
                                               "template_id": "openfilm/motion-graphics-scene"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["assignments"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "candidate_id": "openfilm-motion-graphics:motion-graphics", "skill_id": "openfilm-motion-graphics",
            "template_id": "openfilm/motion-graphics-scene", "role": "native"}]
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertIn("无固定模板", rows[0]["template"])
        self.assertEqual(rows[0]["channel"], "openfilm-motion-graphics")
        segment["visual_strategy"]["components"][0]["kind"] = "ai_generated"
        segment["bindings"]["component-1"] = {"provider": "Lovart", "generation_id": "fixture-generation"}
        treatment["skill_selection"]["assignments"][0].update(candidate_id="gbro-collage-broll:design",
            skill_id="gbro-collage-broll", template_id="gbro-collage-broll/design", role="design")
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["channel"], "gbro-collage-broll")
        self.assertIn("无固定模板", rows[0]["template"])

    def test_channel_uses_real_source_instead_of_adapter_alias(self):
        director = {"segments": []}
        treatment = {"motion_queries": []}
        for index, dependency in enumerate(("hyperframes", "hyperframes-native-adaptation")):
            sid = f"seg-{index}"
            director["segments"].append({"segment_id": sid, "start": index, "end": index + 1,
                "visual_intent": {"statement": "顺序展开"},
                "visual_strategy": {"components": [{"component_id": "scene", "kind": "code_generated",
                                                     "layer_role": "base"}]},
                "bindings": {"scene": {"dependency_id": dependency, "template_id": f"template-{index}"}}})
            treatment["motion_queries"].append({"segment_id": sid, "component_id": "scene", "tags": ["顺序展开"]})
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        treatment["semantic_lists"] = {"overlay": [], "broll": [{
            "row_id": "shared", "start_word": 0, "end_word": 1, "quote": "x", "semantic": "顺序展开",
            "visual_task": "顺序展开", "components": [{"segment_id": f"seg-{i}", "component_id": "scene"}
                                                       for i in range(2)]}]}
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual([r["channel"] for r in rows], ["hyperframes", "hyperframes"])
        self.assertEqual([r["template"] for r in rows], ["template-0", "template-1"])

if __name__ == "__main__":
    unittest.main()

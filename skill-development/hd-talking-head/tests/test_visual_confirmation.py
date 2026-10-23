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
            "motion_queries": [], "overlay_selection": [],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                "fixed_context": [{"segment_id": "seg-001", "component_id": "component-1",
                                   "visual_pattern": "existing material", "source_ref": "asset-1", "skill_id": "stock",
                                   "start": 0.0, "end": 3.0}],
                "recent_context": [], "history_note": "synthetic fixture"}})

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

    def test_proposal_precedes_compile_and_one_confirmation_completes_plan(self):
        proposal = self.prepare()
        self.assertFalse((self.job.job_dir / "07-visual-direction/visual-plan.json").exists())
        ready = self.confirm()
        self.assertEqual(ready["review_required"], "host")
        self.assertEqual(self.job.stages["visual_direction"]["status"], "ready_for_review")
        approval = vc.validate_visual_authorization(self.job)["artifact"]
        original = (self.job.job_dir / approval["path"]).read_bytes()
        result = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(result["status"], "approved")
        final = state.load_job(self.job.job_dir)
        checked = vc.validate_visual_authorization(final, require_realized=True)
        self.assertEqual(checked["artifact"], approval)
        self.assertEqual(original, (self.job.job_dir / approval["path"]).read_bytes())
        self.assertTrue(proposal.exists())
        changed = artifacts.read_json_artifact(self.fixture.brief)
        changed["segments"][0]["visual_intent"]["statement"] = "unapproved change"
        with self.assertRaises(vc.VisualConfirmationError):
            vc.validate_realization_draft(final, changed, artifacts.read_json_artifact(self.treatment))

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
        treatment["generation_plan"] = {"steps": [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "a blue scene"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "animate blue scene", "reference": {"$step": "image", "output": 0}}, "depends_on": ["image"]}]}
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

    def test_startup_requires_both_generation_channels(self):
        from edit.hd.tools import startup
        image = {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image",
                 "connection_status": "verified", "quota_status": "available"}
        config = {"generation_enabled": True, "providers": [image]}
        with self.assertRaisesRegex(state.WorkflowError, "one image and one video"):
            startup.selected_channels(config)
        video = {**image, "purpose": "video", "model": "video-model", "endpoint_id": "fixture.video"}
        config["providers"].append(video)
        self.assertEqual(startup.selected_channels(config)["video"]["endpoint_id"], "fixture.video")

    def test_unconfirmed_proposal_cannot_start_generation(self):
        self.prepare()
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)

if __name__ == "__main__":
    unittest.main()

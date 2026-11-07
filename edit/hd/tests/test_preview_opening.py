"""Cover opening uses one offset for the actual media and exported subtitles."""

import io
import sys
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from edit.hd.tools import contract_artifacts, event_audio, preview_opening, preview_v2, state


OPTIONS = {"hold_frames": 12, "transition_frames": 6,
           "user_confirmation": "测试夹具：使用已批准封面，停留12帧，淡出6帧"}
SRT = "1\n00:00:00,042 --> 00:00:00,750\n分享观点\n\n"
SKILL = Path(__file__).resolve().parents[3] / "."


def opening_job(root):
    """Only approved fixture records; never production user approvals."""
    root = root.resolve()
    files = {
        "cover": {"04-cover/cover-delivery-raster.png": None,
                  "04-cover/cover-report.json": None},
        "subtitles": {"10-subtitles/subtitles.srt": SRT.encode()},
    }
    stages = {}
    for stage_id, sources in files.items():
        records = []
        for relative, content in sources.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".png":
                Image.new("RGB", (1080, 1920), (220, 30, 40)).save(path)
            elif content is None:
                contract_artifacts.write_json_artifact(path, {
                    "output_sha256": {"cover-delivery-raster.png":
                        contract_artifacts.sha256_file(root / "04-cover/cover-delivery-raster.png")},
                })
            else:
                path.write_bytes(content)
            records.append({"path": relative, "sha256": contract_artifacts.sha256_file(path),
                            "bytes": path.stat().st_size})
        stages[stage_id] = {"status": "completed", "artifacts": records}
    return SimpleNamespace(job_id="opening-fixture", job_dir=root, stages=stages)


class OpeningContractTests(unittest.TestCase):
    def test_offset_is_hold_only_not_hold_plus_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            plan = preview_opening.plan_opening(job, {**OPTIONS, "hold_frames": 24}, body_frames=24)
            self.assertEqual(plan["body_offset_frames"], 24)
            self.assertEqual(plan["total_frames"], 48)
            self.assertEqual(plan["body_frames"], 24)
            self.assertEqual(plan["fps"], 24)
            self.assertEqual(plan["cover"]["path"], "04-cover/cover-delivery-raster.png")

    def test_shift_preserves_copy_and_uses_identical_offset(self):
        self.assertEqual(preview_opening.shift_srt(SRT, 12),
            "1\n00:00:00,542 --> 00:00:01,250\n分享观点\n\n".encode())
        self.assertEqual(preview_opening.shift_srt("", 12), b"")

    def test_invalid_options_fail_instead_of_silent_defaults(self):
        cases = ({"hold_frames": 0}, {"hold_frames": True},
                 {"transition_frames": -1}, {"transition_frames": 24},
                 {"transition_frames": float("nan")}, {"user_confirmation": " "},
                 {"background_music": True})
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            for changes in cases:
                with self.subTest(changes=changes), self.assertRaises(preview_opening.OpeningError):
                    preview_opening.plan_opening(job, {**OPTIONS, **changes}, body_frames=24)

    def test_unapproved_or_changed_cover_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            job.stages["cover"]["status"] = "ready_for_review"
            with self.assertRaises(preview_opening.OpeningError):
                preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            job.stages["cover"]["status"] = "completed"
            (job.job_dir / "04-cover/cover-delivery-raster.png").write_bytes(b"changed")
            with self.assertRaises(preview_opening.OpeningError):
                preview_opening.plan_opening(job, OPTIONS, body_frames=24)

    def test_event_audio_uses_packaged_assets_for_independent_job(self):
        from edit.hd.tools import semantic_events
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            job.root = job.job_dir
            semantic = semantic_events.build_semantic_event_plan(
                visual_plan_sha256="a" * 64, transcript_identity="fixture-transcript",
                events=[{"event_id": "cue-01", "kind": "moment", "segment_id": "seg-001",
                    "span_id": None, "word_range": [0, 1], "start_frame": 6, "end_frame": 24,
                    "semantic_role": "emphasis", "trigger": "semantic_boundary",
                    "channels": {"visual": [], "caption": {}, "audio": ["impact-card-in"],
                                 "spatial": {}, "transition": {}}}],
            )
            packaged = Path(preview_v2.__file__).resolve().parents[1] / "integrations/talkcraft/runtime"
            audio = event_audio.build_default_plan(semantic, runtime_root=packaged,
                                                   job_id=job.job_id, total_frames=24)
            records = []
            for name, value in (("semantic-events.json", semantic), ("audio-event-plan.json", audio)):
                path = job.job_dir / "07-visual-direction" / name
                path.parent.mkdir(exist_ok=True)
                contract_artifacts.write_json_artifact(path, value)
                records.append({"path": str(path.relative_to(job.job_dir)),
                    "sha256": contract_artifacts.sha256_file(path), "bytes": path.stat().st_size})
            for explicit in (False, True):
                with self.subTest(explicit_plan=explicit):
                    job.stages["visual_direction"] = {"status": "completed",
                        "artifacts": records if explicit else records[:1]}
                    actual = preview_v2._approved_event_audio_plan(job, frames=24)
                    self.assertEqual(actual, audio)
                    self.assertTrue(Path(actual["cues"][0]["path"]).is_relative_to(packaged))

    def test_default_command_stays_body_only(self):
        command = preview_v2.build_preview_command_v2(
            Path("v.mp4"), Path("s.webm"), Path("a.mp4"), Path("out.mp4"),
            frames=24, duration=1,
        )
        self.assertEqual(command.count("-i"), 3)
        self.assertIn("2:a:0", command)
        self.assertNotIn("adelay", " ".join(command))

    def test_malformed_cover_report_is_a_domain_error(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            report = job.job_dir / "04-cover/cover-report.json"
            for invalid in (None, [], "hash"):
                contract_artifacts.write_json_artifact(report, {"output_sha256": invalid})
                record = next(r for r in job.stages["cover"]["artifacts"]
                              if r["path"].endswith("cover-report.json"))
                record.update(sha256=contract_artifacts.sha256_file(report), bytes=report.stat().st_size)
                with self.subTest(invalid=invalid), self.assertRaises(preview_opening.OpeningError):
                    preview_opening.plan_opening(job, OPTIONS, body_frames=24)


class OpeningMediaTests(unittest.TestCase):
    def test_actual_frames_audio_and_subtitle_track_share_one_offset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job = opening_job(root)
            plan = preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            body, overlay = root / "body.mp4", root / "subtitles.webm"
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=blue:s=1080x1920:r=24:d=1,"
                "drawbox=x=50:y=50:w=200:h=200:color=lime:t=fill:enable='lt(n,3)'", "-f", "lavfi", "-i",
                "sine=frequency=700:sample_rate=48000:duration=1", "-threads", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(body),
            ], check=True, capture_output=True)
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=black@0:s=1080x1920:r=24:d=1,format=rgba,"
                "drawbox=x=100:y=1400:w=800:h=100:color=yellow:t=fill:replace=1",
                "-threads", "1", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-auto-alt-ref", "0", "-deadline", "realtime", str(overlay),
            ], check=True, capture_output=True)
            output = root / "review.mp4"
            command = preview_v2.build_preview_command_v2(
                body, overlay, body, output, frames=24, duration=1,
                opening=plan, cover=job.job_dir / plan["cover"]["path"],
            )
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            media = preview_v2._validate_media(output, frames=36, duration=1.5,
                                               require_opening_contract=True)
            self.assertEqual(media["audio_streams"], 1)
            def frame(n):
                data = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(output), "-vf",
                    f"select=eq(n\\,{n})", "-frames:v", "1", "-f", "image2pipe",
                    "-c:v", "png", "-",
                ], check=True, capture_output=True).stdout
                return Image.open(io.BytesIO(data)).convert("RGB")
            first = frame(0)
            self.assertGreater(first.getpixel((500, 500))[0], 200)
            self.assertLess(first.getpixel((500, 500))[2], 60)
            stable = frame(20)
            self.assertGreater(stable.getpixel((500, 500))[2], 200)
            self.assertGreater(stable.getpixel((500, 1450))[0], 200)
            samples = np.frombuffer(subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0",
                "-ar", "48000", "-ac", "1", "-f", "f32le", "-",
            ], check=True, capture_output=True).stdout, dtype=np.float32)
            self.assertLess(np.max(np.abs(samples[:23000])), .001)
            self.assertGreater(np.sqrt(np.mean(samples[25000:47000] ** 2)), .05)
            self.assertGreater(np.sqrt(np.mean(samples[65000:71000] ** 2)), .05)
            # Zero-transition opening must retain body frame zero and its order.
            cut_plan = preview_opening.plan_opening(job, {**OPTIONS, "transition_frames": 0}, body_frames=24)
            mixed = event_audio.prepare_stage_audio(
                {"total_frames": 24, "cues": [{"path": str(body), "start_frame": 6, "volume": .2}]},
                body, root / "event-audio.m4a", body_offset_frames=12,
            )
            atlas = preview_v2._write_number_atlas(root / "numbers.png", [1])
            subprocess.run(preview_v2.build_preview_command_v2(
                body, overlay, body, output, frames=24, duration=1, opening=cut_plan,
                mixed_audio=mixed, number_overlay={"atlas": atlas, "rows": [
                    {"start_frame": 0, "end_frame": 3, "slot": 0}]},
                cover=job.job_dir / cut_plan["cover"]["path"],
            ), check=True, capture_output=True, timeout=120)
            preview_v2._validate_media(output, frames=36, duration=1.5, require_opening_contract=True)
            self.assertGreater(frame(11).getpixel((100, 100))[0], 200)  # Last cover frame.
            self.assertGreater(frame(12).getpixel((100, 100))[1], 200)  # Body frame zero.
            self.assertGreater(frame(14).getpixel((100, 100))[1], 200)  # Body frame two.
            self.assertGreater(frame(15).getpixel((100, 100))[2], 200)  # Body frame three.
            self.assertGreater(frame(12).getpixel((1025, 1860))[0], 200)  # Body badge starts at body zero.
            self.assertLess(frame(15).getpixel((1025, 1860))[0], 30)  # Badge ends with body frame two.
            mixed_samples = np.frombuffer(subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0",
                "-ar", "48000", "-ac", "1", "-f", "f32le", "-",
            ], check=True, capture_output=True).stdout, dtype=np.float32)
            self.assertLess(np.max(np.abs(mixed_samples[:23000])), .001)
            self.assertGreater(np.sqrt(np.mean(mixed_samples[25000:35000] ** 2)), .05)
            self.assertGreater(np.sqrt(np.mean(mixed_samples[65000:71000] ** 2)), .05)


class OpeningWorkflowTests(unittest.TestCase):
    def setUp(self):
        from edit.hd.tests import test_qa_delivery, test_preview_v2
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = SKILL.resolve()
        sys.path.insert(0, str(SKILL / "scripts"))
        import run_stage
        self.runner = run_stage
        fixture = test_qa_delivery.SemanticSourceDeliveryTests()
        original_write = test_preview_v2._write
        def write_fixture(path, content):
            if path.name == "subtitles.srt":
                content = SRT.encode()
            return original_write(path, content)
        original_cover = test_qa_delivery._write_cover_contract
        def write_cover(root, aspect):
            outputs, report_path, selected = original_cover(root, aspect)
            raster = root / "04-cover/cover-delivery-raster.png"
            Image.new("RGB", (1080, 1920), "red").save(raster)
            report = contract_artifacts.read_json_artifact(report_path)
            record = next(r for r in report["artifacts"] if r["path"].endswith(raster.name))
            record.update(sha256=contract_artifacts.sha256_file(raster), bytes=raster.stat().st_size)
            report["output_sha256"][raster.name] = record["sha256"]
            contract_artifacts.write_json_artifact(report_path, report)
            return outputs, report_path, selected
        with mock.patch.object(test_preview_v2, "_write", side_effect=write_fixture), \
                mock.patch.object(test_qa_delivery, "_write_cover_contract", side_effect=write_cover):
            self.job = fixture._persisted_job(self.root, attribution_required=False,
                                              cover_aspect="9:16", preview_pending=True)
        self.body_srt = SRT

    def render(self):
        real_run = subprocess.run
        def compose(command, **kwargs):
            if Path(command[0]).name != "ffmpeg":
                return real_run(command, **kwargs)
            Path(command[-1]).resolve().relative_to(self.job.job_dir)
            if Path(command[-1]).name != "review.mp4":
                return real_run(command, **kwargs)
            Path(command[-1]).write_bytes(b"cover-plus-body")
        with mock.patch.object(preview_v2.subprocess, "run", side_effect=compose), \
                mock.patch.object(preview_v2, "_validate_media", return_value={
                    "width": 1080, "height": 1920, "fps": 24, "frames": 84, "duration": 3.5,
                    "video_streams": 1, "audio_streams": 1,
                }):
            return preview_v2.prepare_preview_v2(self.job, opening=OPTIONS)

    def complete_preview(self):
        state.complete(self.job, "preview")

    def test_formal_preview_applies_default_static_opening(self):
        from edit.hd.tools import delivery_approval, visual_confirmation
        with mock.patch.object(self.runner, "_startup"), \
                mock.patch.object(delivery_approval, "validate_visual_plan_approval"), \
                mock.patch.object(visual_confirmation, "approved_body_opening", return_value=None), \
                mock.patch.object(visual_confirmation, "validate_visual_authorization", return_value={"payload": {"user_confirmation": "fixture confirmation"}}), \
                mock.patch.object(preview_v2, "prepare_preview_v2") as prepare, \
                mock.patch.object(self.runner, "_finish_stage", return_value={}):
            self.runner._execute_one_stage(self.job.job_dir, self.project, "preview")
        opening = prepare.call_args.kwargs["opening"]
        self.assertEqual(opening["hold_frames"], 12)
        self.assertEqual(opening["transition_frames"], 0)
        self.assertEqual(opening["user_confirmation"], "fixture confirmation")

    def test_preview_delivery_replay_and_exact_srt_identity(self):
        from edit.hd.tools import qa_delivery_v2
        result = self.render()
        directory = self.job.job_dir / "11-preview"
        opening = json.loads((directory / preview_opening.MANIFEST).read_text())
        self.assertEqual(opening["total_frames"], 84)
        self.assertEqual(opening["body_offset_frames"], 12)
        self.assertEqual(result.qa_report["opening_manifest_sha256"], opening["opening_manifest_sha256"])
        self.assertEqual((directory / "subtitles.srt").read_bytes(), preview_opening.shift_srt(self.body_srt, 12))
        records = self.job.stages["preview"]["artifacts"]
        self.assertIn("11-preview/opening-manifest.json", [r["path"] for r in records])
        real_run = subprocess.run
        def no_render(command, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                raise AssertionError("must not render")
            return real_run(command, **kwargs)
        with mock.patch.object(preview_v2.subprocess, "run", side_effect=no_render):
            preview_v2.prepare_preview_v2(self.job)
            preview_v2.prepare_preview_v2(self.job, opening=OPTIONS)
            with self.assertRaises(preview_v2.PreviewV2Error):
                preview_v2.prepare_preview_v2(self.job, opening={**OPTIONS, "hold_frames": 24})
        self.complete_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        artifacts = delivery.manifest["artifacts"]
        self.assertEqual(artifacts["subtitles/subtitles.srt"]["source"]["path"], "11-preview/subtitles.srt")
        self.assertIn("plans/body-subtitles.webm", artifacts)
        self.assertNotIn("subtitles/subtitles.webm", artifacts)
        self.assertIn("opening-manifest.json", artifacts)
        self.assertEqual((delivery.directory / "subtitles/subtitles.srt").read_bytes(),
                         (directory / "subtitles.srt").read_bytes())
        with mock.patch.object(qa_delivery_v2, "_copy", side_effect=AssertionError("must not copy")):
            qa_delivery_v2.prepare_delivery_v2(self.job)

    def test_changed_shifted_srt_cannot_be_replayed(self):
        self.render()
        (self.job.job_dir / "11-preview/subtitles.srt").write_text(SRT)
        with self.assertRaises(state.WorkflowError):
            preview_v2.prepare_preview_v2(self.job)

    def test_missing_opening_manifest_cannot_fall_back_to_body_only(self):
        self.render()
        (self.job.job_dir / "11-preview/opening-manifest.json").unlink()
        with self.assertRaises(state.WorkflowError):
            preview_v2.prepare_preview_v2(self.job)

    def test_interrupted_preview_publication_can_rebuild_without_partial_opening(self):
        before = (self.job.job_dir / "workflow.json").read_bytes()
        with mock.patch.object(state, "save_job", side_effect=OSError("test before commit")):
            with self.assertRaises(OSError):
                self.render()
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())
        self.assertFalse((self.job.job_dir / "11-preview/opening-manifest.json").exists())
        result = self.render()
        self.assertIn("opening_manifest_sha256", result.qa_report)
        self.assertEqual(state.load_job(self.job.job_dir).stages["preview"]["status"], "ready")

    def _deliver(self):
        from edit.hd.tools import delivery_approval, qa_delivery_v2
        self.render()
        self.complete_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        state.complete(self.job, "delivery")
        authorization = self.job.stages["visual_direction"]["artifacts"][0]
        patcher = mock.patch.object(delivery_approval, "validate_visual_plan_approval", return_value={"artifact": authorization})
        patcher.start()
        self.addCleanup(patcher.stop)
        delivery_approval.record_delivery(self.job)
        manifest = next(r for r in self.job.stages["delivery"]["artifacts"] if r["path"].endswith("/delivery-manifest.json"))
        return delivery, manifest

    def test_final_acceptance_resumes_once_and_rejects_changed_srt(self):
        from edit.hd.tools import delivery_approval
        delivery, manifest = self._deliver()
        options = dict(delivery_manifest_sha256=manifest["sha256"],
                       delivery_sha256=delivery.manifest["final_sha256"],
                       user_confirmation="测试夹具：确认本次封面成片")
        with mock.patch.object(delivery_approval, "_publish_receipt", side_effect=OSError("test interruption")):
            with self.assertRaises(OSError):
                delivery_approval.approve_delivery(self.job, **options)
        srt = delivery.directory / "subtitles/subtitles.srt"
        saved = srt.read_bytes()
        srt.write_text(SRT)
        with self.assertRaises(state.WorkflowError):
            delivery_approval.approve_delivery(self.job, **options)
        srt.write_bytes(saved)
        first = delivery_approval.approve_delivery(self.job, **options)
        self.assertEqual(delivery_approval.approve_delivery(self.job, **options), first)
        self.assertEqual(delivery_approval.current_delivery_status(self.job)["delivery_status"], "accepted")

    def test_completion_audit_checks_final_timeline(self):
        delivery, _ = self._deliver()
        spec = importlib.util.spec_from_file_location("opening_completion_audit", SKILL / "scripts/audit_job_completion.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        manifest = contract_artifacts.read_json_artifact(delivery.directory / "delivery-manifest.json")
        probe = {"duration_seconds": 3.5, "audio_streams": 1}
        self.assertTrue(audit._opening_timeline(self.job.job_dir, manifest, self.job.stages, probe))
        for changes in ({"duration_seconds": 3}, {"audio_streams": 0}):
            with self.subTest(changes=changes), self.assertRaises(audit.JobCompletionAuditError):
                audit._opening_timeline(self.job.job_dir, manifest, self.job.stages, {**probe, **changes})


if __name__ == "__main__":
    unittest.main()

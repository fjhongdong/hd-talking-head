"""Cover opening uses one offset for the actual media and exported subtitles."""

import io
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

from edit.hd.tools import contract_artifacts, preview_opening, preview_v2, state


OPTIONS = {"hold_frames": 12, "transition_frames": 6,
           "user_confirmation": "测试夹具：使用已批准封面，停留12帧，淡出6帧"}
SRT = "1\n00:00:00,042 --> 00:00:00,750\n分享观点\n\n"
SKILL = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head"


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
        stages[stage_id] = {"status": "approved", "artifacts": records}
    return SimpleNamespace(job_id="opening-fixture", job_dir=root, stages=stages)


class OpeningContractTests(unittest.TestCase):
    def test_offset_is_hold_only_not_hold_plus_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            plan = preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            self.assertEqual(plan["body_offset_frames"], 12)
            self.assertEqual(plan["total_frames"], 36)
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
            job.stages["cover"]["status"] = "approved"
            (job.job_dir / "04-cover/cover-delivery-raster.png").write_bytes(b"changed")
            with self.assertRaises(preview_opening.OpeningError):
                preview_opening.plan_opening(job, OPTIONS, body_frames=24)

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
            root = Path(temp)
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
            subprocess.run(preview_v2.build_preview_command_v2(
                body, overlay, body, output, frames=24, duration=1, opening=cut_plan,
                cover=job.job_dir / cut_plan["cover"]["path"],
            ), check=True, capture_output=True, timeout=120)
            preview_v2._validate_media(output, frames=36, duration=1.5, require_opening_contract=True)
            self.assertGreater(frame(11).getpixel((100, 100))[0], 200)  # Last cover frame.
            self.assertGreater(frame(12).getpixel((100, 100))[1], 200)  # Body frame zero.
            self.assertGreater(frame(14).getpixel((100, 100))[1], 200)  # Body frame two.
            self.assertGreater(frame(15).getpixel((100, 100))[2], 200)  # Body frame three.


class OpeningWorkflowTests(unittest.TestCase):
    def setUp(self):
        from edit.hd.tests import test_preview_v2, test_qa_delivery
        from edit.hd.tests.test_startup import approve_fixture_setup
        verifier = SKILL / "scripts/verify_skill_release.py"
        if verifier.is_file():
            verifier_hash = contract_artifacts.sha256_file(verifier)
            self.addCleanup(lambda: self.assertEqual(contract_artifacts.sha256_file(verifier), verifier_hash))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        original_cover = test_qa_delivery._write_cover_contract
        original_write = test_preview_v2._write

        def cover_fixture(root, aspect):
            outputs, report_path, selected = original_cover(root, aspect)
            raster = root / "04-cover/cover-delivery-raster.png"
            Image.new("RGB", (1080, 1920), (220, 30, 40)).save(raster)
            report = json.loads(report_path.read_text())
            record = next(r for r in report["artifacts"] if r["path"].endswith(raster.name))
            record.update(sha256=contract_artifacts.sha256_file(raster), bytes=raster.stat().st_size)
            report["output_sha256"][raster.name] = record["sha256"]
            contract_artifacts.write_json_artifact(report_path, report)
            return outputs, report_path, selected

        def write_fixture(path, payload):
            if path.name == "subtitles.srt":
                return original_write(path, SRT.encode())
            return original_write(path, payload)

        with mock.patch.object(test_qa_delivery, "_write_cover_contract", side_effect=cover_fixture), \
                mock.patch.object(test_preview_v2, "_write", side_effect=write_fixture):
            self.job = test_qa_delivery.SemanticSourceDeliveryTests()._persisted_job(
                self.root, attribution_required=False, preview_pending=True,
            )
        approve_fixture_setup(self.job)

    def render(self):
        real_run = subprocess.run
        def compose(command, **kwargs):
            if Path(command[0]).name != "ffmpeg":
                return real_run(command, **kwargs)
            Path(command[-1]).resolve().relative_to(self.job.job_dir)
            self.assertEqual(Path(command[-1]).name, "review.mp4")
            Path(command[-1]).write_bytes(b"cover-plus-body")
        def frames(video, directory, duration):
            directory.mkdir()
            paths = []
            for i in range(5):
                path = directory / f"frame-{i}.png"
                Image.new("RGB", (1080, 1920), "red").save(path)
                paths.append(path)
            return paths
        def opening_frames(video, directory, plan):
            paths = []
            for name in ("opening-first", "opening-hold-end", "opening-body-start", "opening-transition-end"):
                path = directory / f"{name}.png"
                Image.new("RGB", (1080, 1920), "red").save(path)
                paths.append(path)
            return paths
        with mock.patch.object(preview_v2.subprocess, "run", side_effect=compose), \
                mock.patch.object(preview_v2, "_validate_media", return_value={
                    "width": 1080, "height": 1920, "fps": 24, "frames": 84, "duration": 3.5,
                    "video_streams": 1, "audio_streams": 1,
                }), mock.patch.object(preview_v2, "_extract_frames", side_effect=frames), \
                mock.patch.object(preview_opening, "extract_evidence", side_effect=opening_frames, create=True):
            return preview_v2.prepare_preview_v2(self.job, opening=OPTIONS)

    def test_preview_delivery_replay_and_exact_srt_identity(self):
        from edit.hd.tools import qa_delivery_v2, state
        result = self.render()
        directory = self.job.job_dir / "11-preview"
        opening = json.loads((directory / preview_opening.MANIFEST).read_text())
        self.assertEqual(opening["total_frames"], 84)
        self.assertEqual(opening["body_offset_frames"], 12)
        self.assertEqual(result.qa_report["opening_manifest_sha256"], opening["opening_manifest_sha256"])
        self.assertEqual((directory / "subtitles.srt").read_bytes(), preview_opening.shift_srt(SRT, 12))
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
        state.approve(self.job, "preview")
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
        self.assertEqual(state.load_job(self.job.job_dir).stages["preview"]["status"], "ready_for_review")

    def test_pending_final_approval_resumes_once_and_rejects_changed_srt(self):
        from edit.hd.tools import delivery_approval, qa_delivery_v2
        self.render()
        state.approve(self.job, "preview")
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        options = dict(expected_revision=self.job.revision,
                       delivery_sha256=delivery.manifest["final_sha256"],
                       user_confirmation="测试夹具：确认本次封面成片")
        with mock.patch.object(state, "save_job", side_effect=OSError("test interruption")):
            with self.assertRaises(OSError):
                delivery_approval.approve_delivery(self.job, **options)
        before = (self.job.job_dir / "workflow.json").read_bytes()
        srt = delivery.directory / "subtitles/subtitles.srt"
        approved_bytes = srt.read_bytes()
        srt.write_text(SRT)
        with self.assertRaises(state.WorkflowError):
            delivery_approval.approve_delivery(self.job, **options)
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())
        srt.write_bytes(approved_bytes)
        delivery_approval.approve_delivery(self.job, **options)
        revision = self.job.revision
        delivery_approval.approve_delivery(self.job, **options)
        self.assertEqual(revision, self.job.revision)

    def test_completion_audit_checks_final_timeline(self):
        from edit.hd.tools import delivery_approval, qa_delivery_v2
        self.render()
        state.approve(self.job, "preview")
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        delivery_approval.approve_delivery(self.job, expected_revision=self.job.revision,
            delivery_sha256=delivery.manifest["final_sha256"],
            user_confirmation="测试夹具：审批时间轴审计")
        spec = importlib.util.spec_from_file_location("opening_completion_audit",
            SKILL / "scripts/audit_job_completion.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        probe = {"width": 1080, "height": 1920, "fps": 24, "rotation": 0,
                 "duration_seconds": 3.5, "audio_streams": 1}
        before = (self.job.job_dir / "workflow.json").read_bytes()
        with mock.patch.object(audit, "_probe_media", return_value=probe):
            result = audit.audit_job_completion(self.root)
            self.assertEqual(result["status"], "formal_complete", result)
        for changes in ({"duration_seconds": 3}, {"audio_streams": 0}):
            with self.subTest(changes=changes), mock.patch.object(
                    audit, "_probe_media", return_value={**probe, **changes}):
                result = audit.audit_job_completion(self.root)
                self.assertEqual(result["status"], "inconsistent", result)
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())


if __name__ == "__main__":
    unittest.main()

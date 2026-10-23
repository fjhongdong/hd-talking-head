"""Formal music routing and immutable workflow contracts, not listening approval."""

import copy
import inspect
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock
from PIL import Image

from edit.hd.tools import preview_v2, preview_music, preview_opening, material_usage, state, qa_delivery_v2, contract_artifacts
from edit.hd.tests import test_preview_opening, test_music_plan


class MusicRoutingTests(unittest.TestCase):
    def test_formal_runner_accepts_explicit_music(self):
        self.assertIn("music", inspect.signature(preview_v2.prepare_preview_v2).parameters)

    def test_final_clock_mix_is_mapped_once_with_and_without_opening(self):
        for opening in (None, {"body_frames": 72, "body_offset_frames": 12,
                               "total_frames": 84, "options": {"transition_frames": 6}}):
            command = preview_v2.build_preview_command_v2(
                Path("v.mp4"), Path("s.webm"), Path("a.mp4"), Path("out.mp4"),
                frames=72, duration=3, mixed_audio=Path("mix.wav"),
                opening=copy.deepcopy(opening), cover=Path("cover.png") if opening else None)
            graph = command[command.index("-filter_complex") + 1]
            self.assertNotIn("adelay", graph, "the already offset mix must not be delayed again")
            self.assertIn("4:a:0" if opening else "3:a:0", command)
            self.assertNotIn("2:a:0", command)
            self.assertEqual(command.count("-map"), 2)

    def test_music_is_a_material_consumer(self):
        self.assertIn("background_music", material_usage._CONSUMER_KINDS)


class MusicCompositionTests(unittest.TestCase):
    def test_real_cover_mix_aac_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job = test_preview_opening.opening_job(root)
            job.root = root
            _, options, index = test_music_plan.fixture(root)
            source = root / index["materials"][0]["imported_path"]
            source.unlink()  # Replace this test's identity-only placeholder with a test tone.
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=220:sample_rate=48000:duration=2", "-ac", "2", str(source)],
                check=True, capture_output=True)
            for records in (index["materials"], index["assets"]):
                records[0].update(sha256=contract_artifacts.sha256_file(source), size_bytes=source.stat().st_size)
            options["material_sha256"] = index["materials"][0]["sha256"]
            contract_artifacts.write_json_artifact(root / "00-user-provided/material-index.json", index)
            body, overlay = root / "body.mp4", root / "overlay.webm"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=1080x1920:r=24:d=3", "-f", "lavfi", "-i",
                "sine=frequency=700:sample_rate=48000:duration=3", "-threads", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ac", "2",
                "-shortest", str(body)], check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black@0:s=1080x1920:r=24:d=3,format=rgba", "-threads", "1",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                "-deadline", "realtime", str(overlay)], check=True, capture_output=True)
            opening = preview_opening.plan_opening(job, test_preview_opening.OPTIONS, body_frames=72)
            plan = preview_music.plan_music(job, options, frames=84, voice_offset_frames=12)
            stage = root / "stage"
            stage.mkdir()
            mixed = preview_music.prepare_stage_audio(job, stage, plan, body)
            output = stage / "review.mp4"
            subprocess.run(preview_v2.build_preview_command_v2(body, overlay, body, output,
                frames=72, duration=3, opening=opening,
                cover=root / opening["cover"]["path"], mixed_audio=mixed),
                check=True, capture_output=True, timeout=120)
            media = preview_v2._validate_media(output, frames=84, duration=3.5, require_opening_contract=True)
            self.assertEqual(media["audio_streams"], 1)
            manifest = preview_music.publish_metadata(job, stage, plan, body)
            self.assertGreater(manifest["metrics"]["music"]["integrated_lufs"], -60)
            self.assertFalse((stage / ".music-work").exists())
            preview_music.validate_metadata(job, stage, manifest, body)
            for metrics in (["final", "music"], {"final": {"integrated_lufs": 10 ** 1000,
                    "true_peak_dbtp": -3}, "music": manifest["metrics"]["music"]}):
                changed = {**manifest, "metrics": metrics}
                changed["music_manifest_sha256"] = contract_artifacts.sha256_json(
                    {k: v for k, v in changed.items() if k != "music_manifest_sha256"})
                with self.subTest(metrics_type=type(metrics)), self.assertRaises(preview_music.MusicError):
                    preview_music.validate_metadata(job, stage, changed, body)
            # During the cover there is no speech; actual encoded sound is music.
            audible = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output),
                "-t", "0.45", "-map", "0:a:0", "-f", "f32le", "-"],
                check=True, capture_output=True).stdout
            import numpy as np
            self.assertGreater(float(np.max(np.abs(np.frombuffer(audible, dtype=np.float32)))), .001)


class MusicWorkflowTests(unittest.TestCase):
    setUp = test_preview_opening.OpeningWorkflowTests.setUp

    def render(self):
        if not hasattr(self, "options"):
            _, self.options, _ = test_music_plan.fixture(self.job.root)
        real_run = subprocess.run

        def compose(command, **kwargs):
            if Path(command[0]).name != "ffmpeg":
                return real_run(command, **kwargs)
            path = Path(command[-1]).resolve()
            path.relative_to(self.job.job_dir)
            self.assertEqual(path.name, "review.mp4")
            self.assertIn("mix.wav", " ".join(command))
            path.write_bytes(b"test-final-mixed")

        def prepare(job, directory, plan, voice):
            # Isolate media cost here; real audio primitives have separate decode tests.
            work = directory / ".music-work"
            work.mkdir()
            (work / "mix.wav").write_bytes(b"fixture-mix")
            (directory / "music-audit.m4a").write_bytes(b"fixture-audit")
            return work / "mix.wav"

        def frames(video, directory, duration):
            directory.mkdir()
            path = directory / "frame-0.png"
            Image.new("RGB", (270, 480), "red").save(path)
            return [path]

        with mock.patch.object(preview_v2.subprocess, "run", side_effect=compose), \
                mock.patch.object(preview_v2, "_validate_media", return_value={
                    "width": 1080, "height": 1920, "fps": 24, "frames": 72, "duration": 3,
                    "video_streams": 1, "audio_streams": 1}), \
                mock.patch.object(preview_v2, "_extract_frames", side_effect=frames), \
                mock.patch.object(preview_music, "prepare_stage_audio", side_effect=prepare), \
                mock.patch.object(preview_music, "measure_audio", return_value={
                    "integrated_lufs": -25, "true_peak_dbtp": -3}):
            return preview_v2.prepare_preview_v2(self.job, music=self.options)

    def test_preview_delivery_bind_license_audit_and_reuse(self):
        result = self.render()
        self.assertTrue(result.qa_report["background_music"])
        self.assertEqual(result.qa_report["audio_mix_layers"], 2)
        receipt = material_usage.load_current_receipt(self.job, "preview")
        self.assertEqual(len(receipt["references"]), 2)
        spec = importlib.util.spec_from_file_location("music_material_change",
            Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/manage_user_materials.py")
        change = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(change)
        earliest, affected, scope = change._invalidation_plan(self.job, state,
            [{"stage": "preview", **r} for r in receipt["references"]])
        self.assertEqual((earliest, affected, scope), ("preview", ["preview", "delivery"], []))
        self.assertFalse((result.directory / ".music-work").exists())
        preview_v2.prepare_preview_v2(self.job, music=self.options)
        with self.assertRaises(preview_v2.PreviewV2Error):
            preview_v2.prepare_preview_v2(self.job, music={**self.options, "title": "changed"})
        state.approve(self.job, "preview")
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        self.assertTrue(delivery.manifest["background_music"])
        for name in preview_music.ATTACHMENTS:
            self.assertEqual((delivery.directory / name).read_bytes(), (result.directory / name).read_bytes())
        self.assertEqual(len(material_usage.load_current_receipt(self.job, "delivery")["references"]), 2)
        qa_delivery_v2.prepare_delivery_v2(self.job)
        from edit.hd.tools import delivery_approval
        delivery_approval.approve_delivery(self.job, expected_revision=self.job.revision,
            delivery_sha256=delivery.manifest["final_sha256"],
            user_confirmation="测试夹具：确认混音成片，不是生产试听批准")
        spec = importlib.util.spec_from_file_location("music_workflow_audit",
            Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/audit_job_completion.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        with mock.patch.object(audit, "_probe_media", return_value={
                "width": 1080, "height": 1920, "fps": 24, "rotation": 0,
                "duration_seconds": 3, "audio_duration_seconds": 3, "audio_streams": 1}):
            completion = audit.audit_job_completion(self.job.root)
        self.assertEqual(completion["status"], "formal_complete", completion)

    def test_missing_evidence_cannot_disable_music(self):
        result = self.render()
        (result.directory / preview_music.MANIFEST).unlink()
        with self.assertRaises(state.WorkflowError):
            preview_v2.prepare_preview_v2(self.job)

    def test_publication_failure_does_not_leave_partial_music(self):
        with mock.patch.object(state, "save_job", side_effect=OSError("test publication")):
            with self.assertRaises(OSError):
                self.render()
        self.assertFalse((self.job.job_dir / "11-preview/music-manifest.json").exists())
        self.render()


if __name__ == "__main__":
    unittest.main()

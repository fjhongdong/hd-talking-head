"""Offline reuse contract tests; synthetic receipts are not provider evidence."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lovart_existing_video_adapter as reuse
from edit.hd.tools import broll_component_executor as executor, visual_canary
from edit.hd.tests.test_broll_component_executor import _Job, _common, _recipe, _artifact_probe


def file_ref(job, name):
    data = (job.job_dir / name).read_bytes()
    return {"job_path": name, "sha256": hashlib.sha256(data).hexdigest(), "byte_count": len(data)}


def fixture(root, payload=b"synthetic native-video payload", width=1080, height=1920):
    job = _Job(root)
    prompt = "Synthetic motion fixture"
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
    digest = hashlib.sha256(payload).hexdigest()
    generation = {
        "synthetic_fixture": True, "status": "completed",
        "request": {"model": "kling/kling-video-o1", "project_id": "fixture-project", "prompt": prompt},
        "submission_response": {"model": "kling/kling-video-o1", "project_id": "fixture-project", "task_ids": ["fixture-task"]},
        "completion_response": {"status": "completed", "model": "kling/kling-video-o1", "project_id": "fixture-project",
                                "artifacts": [{"id": "fixture-artifact", "type": "video", "width": width, "height": height}]}}
    qa = {"development_only": True, "formal_job_approved": False,
          "generation": {"provider": "Lovart", "model": "kling/kling-video-o1", "project_id": "fixture-project",
                         "task_id": "fixture-task", "artifact_id": "fixture-artifact", "request_prompt_sha256": prompt_sha},
          "native_video": {"sha256": digest, "width": width, "height": height},
          "source_clock": {"cut_sha256": "a" * 64, "broll_frames_half_open": [0, 48]}}
    (job.job_dir / "native.mp4").write_bytes(payload)
    for name, value in (("generation.json", generation), ("qa.json", qa)):
        (job.job_dir / name).write_text(json.dumps(value), encoding="utf-8")
    component = _common("ai", "ai_generated", "video")
    output_size = (width, height) if (width, height) in {(720, 1280), (1080, 1920)} else (1080, 1920)
    component.update(executor=reuse.EXECUTOR, provider=reuse.PROVIDER, model="kling/kling-video-o1",
                     endpoint_id=reuse.ENDPOINT_ID, prompt_sha256=prompt_sha, generation_id="fixture-task", sha256=digest,
                     artifact_contract={"width": output_size[0], "height": output_size[1], "fps": 24, "alpha": False})
    recipe = _recipe([component])
    record = {"schema_version": 1, "job_id": job.job_id, "segment_id": "seg-001", "component_id": "ai",
              "source_binding": {"aroll_sha256": "a" * 64, "start": 0, "end": 2},
              "media": file_ref(job, "native.mp4"), "generation": file_ref(job, "generation.json"), "qa": file_ref(job, "qa.json")}
    return job, record, recipe


def execute(job, record, recipe, adapter=None, probe=None):
    segment = {"segment_id": "seg-001", "start": record["source_binding"]["start"],
               "end": record["source_binding"]["end"], "shot_recipe": recipe}
    with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": [segment]}), \
         patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": record["source_binding"]["aroll_sha256"]}):
        return executor.execute_component(job, executor.ComponentExecutionRequest(recipe, "ai"),
            adapters={"ai_generated": adapter or reuse.create_adapter(job, record), "artifact_probe": probe or _artifact_probe()})


def padded_fixture(root):
    job, record, recipe = fixture(root, height=1916)
    (job.job_dir / "padded.mp4").write_bytes(b"synthetic reviewed derivative")
    record["derived_media"] = file_ref(job, "padded.mp4")
    qa_path = job.job_dir / "qa.json"
    qa = json.loads(qa_path.read_text())
    qa["native_video"].update(frames=121, fps=24)
    qa["scene"] = {"sha256": record["derived_media"]["sha256"], "width": 1080,
                   "height": 1920, "frames": 48, "fps": 24, "provider_frames_half_open": [0, 48]}
    qa["composition"] = {"sha256": "b" * 64}
    qa["user_confirmation"] = {"preview_sha256": "b" * 64}
    qa_path.write_text(json.dumps(qa))
    record["qa"] = file_ref(job, "qa.json")
    approval = {"schema_version": 1, "status": "approved", "approval_type": "single_asset_padding_exception",
                "user_confirmation": "test fixture only", "confirmation_context": "synthetic test approval",
                "generation_id": "fixture-task", "source_sha256": record["media"]["sha256"],
                "output_sha256": record["derived_media"]["sha256"], "approved_preview_sha256": "b" * 64,
                "source_dimensions": [1080, 1916], "output_dimensions": [1080, 1920],
                "source_frame_count": 121, "output_frame_count": 48,
                "source_frames_half_open": [0, 48], "fps": 24,
                "transform": {"top": 2, "bottom": 2, "left": 0, "right": 0,
                              "color": "white", "scale": False, "crop": False},
                "applies_to_other_assets": False}
    (job.job_dir / "padding-approval.json").write_text(json.dumps(approval))
    record["normalization_approval"] = file_ref(job, "padding-approval.json")
    recipe["components"][0]["sha256"] = record["derived_media"]["sha256"]
    return job, record, recipe


class ExistingLovartTests(unittest.TestCase):
    def test_reviewed_margin_cleanup_reuses_derivative_and_rejects_scaling(self):
        with tempfile.TemporaryDirectory() as directory:
            job, record, recipe = padded_fixture(Path(directory).resolve())
            generation_path = job.job_dir / 'generation.json'
            generation = json.loads(generation_path.read_text())
            generation['completion_response']['artifacts'][0]['height'] = 1920
            generation_path.write_text(json.dumps(generation))
            record['generation'] = file_ref(job, 'generation.json')
            qa_path = job.job_dir / 'qa.json'
            qa = json.loads(qa_path.read_text())
            qa['native_video']['height'] = 1920
            qa_path.write_text(json.dumps(qa))
            record['qa'] = file_ref(job, 'qa.json')
            path = job.job_dir / 'padding-approval.json'
            approval = json.loads(path.read_text())
            approval.update(approval_type='single_asset_reviewed_margin_cleanup',
                            source_dimensions=[1080, 1920],
                            transform={'crop': [0, 0, 1080, 1800], 'pad_bottom': 120,
                                       'color': '0xf7f9f8', 'scale': False, 'sar': '1:1'})
            path.write_text(json.dumps(approval))
            record['normalization_approval'] = file_ref(job, 'padding-approval.json')
            artifact = execute(job, record, recipe)
            self.assertEqual(artifact.output_sha256, record['derived_media']['sha256'])
            self.assertTrue(artifact.invocation_evidence['adapter_record']['accepted_with_margin_cleanup'])
            self.assertEqual(artifact.invocation_evidence['adapter_record']['external_requests'], 0)
            approval['transform']['scale'] = True
            path.write_text(json.dumps(approval))
            record['normalization_approval'] = file_ref(job, 'padding-approval.json')
            with self.assertRaisesRegex(ValueError, 'exact reviewed asset'):
                reuse.create_adapter(job, record)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.job, self.record, self.recipe = fixture(Path(self.temporary.name).resolve())

    def test_exact_bytes_and_repeat_uses_published_artifact(self):
        adapter = reuse.create_adapter(self.job, self.record)
        invoke = Mock(wraps=adapter.invoke)
        adapter = replace(adapter, invoke=invoke)
        first = execute(self.job, self.record, self.recipe, adapter)
        second = execute(self.job, self.record, self.recipe, adapter)
        self.assertEqual(first, second)
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(first.kind, "ai_generated")
        self.assertEqual(first.output_sha256, self.record["media"]["sha256"])
        self.assertEqual(first.invocation_evidence["adapter_record"]["external_requests"], 0)

    def test_component_identity_changes_fail(self):
        for key, value in (("generation_id", "another-task"), ("prompt_sha256", hashlib.sha256(b"Synthetic motion fixture\n").hexdigest()),
                           ("model", "different-model"), ("sha256", "f" * 64)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                job, record, recipe = fixture(Path(directory).resolve())
                recipe["components"][0][key] = value
                with self.assertRaises(executor.BrollComponentExecutionError):
                    execute(job, record, recipe)
                self.assertFalse(list(job.job_dir.glob("08-visual-assets/components/*/*.mp4")))

    def test_completion_task_and_prompt_evidence_must_agree(self):
        for field in ("task_id", "request_prompt_sha256", "artifact_id"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                job, record, _recipe_value = fixture(Path(directory).resolve())
                path = job.job_dir / "qa.json"
                qa = json.loads(path.read_text())
                qa["generation"][field] = "wrong"
                path.write_text(json.dumps(qa))
                record["qa"] = file_ref(job, "qa.json")
                with self.assertRaises(ValueError):
                    reuse.create_adapter(job, record)

    def test_symlink_media_is_rejected_by_safe_snapshot(self):
        native = self.job.job_dir / "native.mp4"
        native.rename(self.job.job_dir / "actual.mp4")
        native.symlink_to("actual.mp4")
        with self.assertRaises(executor.BrollComponentExecutionError):
            execute(self.job, self.record, self.recipe)

    def test_incomplete_receipt_is_a_readable_rejection(self):
        path = self.job.job_dir / "generation.json"
        path.write_text('{"status":"completed"}')
        self.record["generation"] = file_ref(self.job, "generation.json")
        with self.assertRaisesRegex(ValueError, "incomplete or malformed"):
            reuse.create_adapter(self.job, self.record)

    def test_probe_version_tracks_its_code(self):
        executable = shutil.which("ffprobe")
        self.assertIsNotNone(executable, "configured media tests require ffprobe")
        first = reuse.create_artifact_probe(executable)
        actual_sha = reuse._sha
        def changed_probe_hash(path):
            return "0" * 64 if Path(path).name == "lovart_existing_video_adapter.py" else actual_sha(path)
        with patch.object(reuse, "_sha", side_effect=changed_probe_hash):
            second = reuse.create_artifact_probe(executable)
        self.assertNotEqual(first.probe_version, second.probe_version)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_real_silent_720p_source_reuses_exact_bytes_and_rejects_audio(self):
        video = self.job.job_dir / "native.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
             "-i", "color=c=blue:s=720x1280:r=24:d=2", "-frames:v", "48",
             "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video)],
            check=True, capture_output=True,
        )
        self.record["media"] = file_ref(self.job, "native.mp4")
        generation_path = self.job.job_dir / "generation.json"
        generation = json.loads(generation_path.read_text())
        generation["completion_response"]["artifacts"][0].update(width=720, height=1280)
        generation_path.write_text(json.dumps(generation))
        self.record["generation"] = file_ref(self.job, "generation.json")
        qa_path = self.job.job_dir / "qa.json"
        qa = json.loads(qa_path.read_text())
        qa["native_video"].update(sha256=self.record["media"]["sha256"], width=720, height=1280)
        qa_path.write_text(json.dumps(qa))
        self.record["qa"] = file_ref(self.job, "qa.json")
        self.recipe["components"][0]["sha256"] = self.record["media"]["sha256"]
        contract = {"width": 720, "height": 1280, "fps": 24, "alpha": False}
        self.recipe["components"][0]["artifact_contract"] = contract
        probe = reuse.create_artifact_probe(shutil.which("ffprobe"))
        artifact = execute(self.job, self.record, self.recipe, probe=probe)
        self.assertEqual(artifact.output_sha256, self.record["media"]["sha256"])
        self.assertEqual(artifact.media_probe["width"], 720)
        with_audio = self.job.job_dir / "with-audio.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(video),
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-map", "0:v:0",
             "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(with_audio)],
            check=True, capture_output=True,
        )
        with self.assertRaisesRegex(ValueError, "one silent video stream"):
            probe.probe(with_audio, "video", contract)

    def test_changed_evidence_changes_cache_identity(self):
        first = reuse.create_adapter(self.job, self.record)
        execute(self.job, self.record, self.recipe, first)
        path = self.job.job_dir / "qa.json"
        qa = json.loads(path.read_text())
        qa["user_visual_approval"] = "fixture-only"
        path.write_text(json.dumps(qa))
        record = copy.deepcopy(self.record)
        record["qa"] = file_ref(self.job, "qa.json")
        second = reuse.create_adapter(self.job, record)
        self.assertNotEqual(first.adapter_version, second.adapter_version)
        with self.assertRaises(executor.BrollComponentExecutionError):
            execute(self.job, record, self.recipe, second)

    def test_approved_derivative_preserves_native_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            job, record, recipe = padded_fixture(Path(directory).resolve())
            artifact = execute(job, record, recipe)
            evidence = artifact.invocation_evidence["adapter_record"]
            self.assertEqual(artifact.output_sha256, record["derived_media"]["sha256"])
            self.assertEqual(evidence["native_sha256"], record["media"]["sha256"])
            self.assertEqual(evidence["native_dimensions"], (1080, 1916))
            self.assertTrue(evidence["accepted_with_padding_exception"])
            self.assertEqual(evidence["external_requests"], 0)

    def test_padding_exception_is_not_a_blanket_bypass(self):
        mutations = [lambda a: a.update(approved_preview_sha256="f" * 64),
                     lambda a: a.update(source_sha256="f" * 64),
                     lambda a: a.update(output_sha256="f" * 64),
                     lambda a: a.update(user_confirmation=""),
                     lambda a: a["transform"].update(top=4),
                     lambda a: a["transform"].update(scale=True)]
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as directory:
                job, record, _recipe_value = padded_fixture(Path(directory).resolve())
                path = job.job_dir / "padding-approval.json"
                approval = json.loads(path.read_text()); mutate(approval)
                path.write_text(json.dumps(approval))
                record["normalization_approval"] = file_ref(job, "padding-approval.json")
                with self.assertRaises(ValueError):
                    reuse.create_adapter(job, record)
        for missing in ("normalization_approval", "derived_media"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                job, record, _recipe_value = padded_fixture(Path(directory).resolve())
                del record[missing]
                with self.assertRaisesRegex(ValueError, "invalid Lovart record"):
                    reuse.create_adapter(job, record)


if __name__ == "__main__":
    unittest.main()

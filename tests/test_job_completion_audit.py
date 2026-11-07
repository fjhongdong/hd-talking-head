"""Completion audit checks current delivery evidence without changing files."""
from __future__ import annotations
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
STAGES = ("inspect", "content_analysis", "cover_direction", "cover", "speech_cleanup",
          "edit_structure", "visual_direction", "visual_assets", "subtitles", "preview", "delivery")

def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class JobCompletionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve() / "job-workspace"
        self.job_dir = self.workspace / "edit/hd/jobs/job-1"
        self.delivery = self.job_dir / "12-delivery"
        self.delivery.mkdir(parents=True)
        self.final = self.delivery / "final.mp4"
        self.final.write_bytes(b"formal-final-video")
        self.revision = 37
        self._write_formal_job()

    def api(self):
        return importlib.import_module("audit_job_completion")

    def _write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _record(self, path, root=None):
        return {"path": path.relative_to(root or self.job_dir).as_posix(),
                "sha256": _sha256(path), "bytes": path.stat().st_size}

    def _write_formal_job(self):
        source = self.job_dir / "11-preview/preview.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(self.final.read_bytes())
        inputs = {}
        for name in ("video", "script"):
            path = self.workspace / (name + ".dat")
            path.write_bytes(name.encode())
            inputs[name] = self._record(path, self.workspace)
        manifest = {"schema_version": 2, "job_id": "job-1", "final_sha256": _sha256(self.final),
                    "canvas": {"width": 1080, "height": 1920, "fps": 24},
                    "artifacts": {"final.mp4": {"source": self._record(source),
                         "output": {"path": "final.mp4", "sha256": _sha256(self.final),
                                    "bytes": self.final.stat().st_size}}}}
        manifest_path = self.delivery / "delivery-manifest.json"
        self._write_json(manifest_path, manifest)
        stages = {stage: {"status": "completed", "artifacts": []} for stage in STAGES}
        stages["delivery"]["artifacts"] = [self._record(self.final), self._record(manifest_path)]
        self._write_json(self.job_dir / "workflow.json", {"version": 2, "job_id": "job-1",
                         "inputs": inputs, "revision": self.revision, "stages": stages})
        self._write_json(self.workspace / "job-context.json", {"workspace": str(self.workspace),
                         "job_dir": str(self.job_dir), "job_id": "job-1"})
        auth = self.job_dir / "03-authorization.json"
        self._write_json(auth, {"job_id": "job-1", "authorized_by": "user",
                         "authorization_scope": "visual_plan_and_generation", "user_confirmation": "确认清单"})
        manifest_record, final_record = self._record(manifest_path), self._record(self.final)
        self.receipt_root = self.job_dir / "manifests/delivery" / manifest_record["sha256"]
        self.receipt = self.receipt_root / "delivered.json"
        self.acceptance = self.receipt_root / "accepted.json"
        self._write_json(self.receipt, {"schema_version": 1, "decision": "delivered", "job_id": "job-1",
                         "delivery": final_record, "delivery_manifest": manifest_record,
                         "visual_authorization": self._record(auth), "delivered_at": "2026-11-07"})
        self._write_json(self.acceptance, {"schema_version": 1, "decision": "accepted", "accepted_by": "user",
                         "job_id": "job-1", "delivery": final_record, "delivery_manifest": manifest_record,
                         "user_confirmation": "确认成片", "accepted_at": "2026-11-07"})
        self.stable = self.job_dir / "delivered" / manifest_record["sha256"]
        self.stable.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.final, self.stable / "final.mp4")
        shutil.copyfile(manifest_path, self.stable / "delivery-manifest.json")

    def _snapshot(self):
        return {p.relative_to(self.workspace).as_posix(): (_sha256(p), p.stat().st_size)
                for p in self.workspace.rglob("*") if p.is_file()}

    def _audit(self, probe=None):
        before = self._snapshot()
        probe = probe or {"width": 1080, "height": 1920, "fps": 24.0, "rotation": 0,
                          "duration_seconds": 10.0, "audio_streams": 1}
        with mock.patch.object(self.api(), "_probe_media", return_value=probe):
            result = self.api().audit_job_completion(self.workspace)
        self.assertEqual(before, self._snapshot())
        return result

    def test_accepted_requires_current_user_evidence(self):
        result = self._audit()
        self.assertEqual("accepted", result["status"], result)
        self.assertEqual(self.revision, result["workflow_revision"])
        self.assertEqual(_sha256(self.final), result["delivery_identity"]["sha256"])
        self.assertIn("actual_user_acceptance_recorded", result["verified_claims"])
        self.assertEqual([], result["failures"])

    def test_opening_clock_and_subtitle_identity_are_checked(self):
        opening = {
            "schema_version": 1, "job_id": "job-1", "fps": 24,
            "body_frames": 24, "body_offset_frames": 12, "total_frames": 36,
            "options": {"hold_frames": 12, "transition_frames": 6,
                        "user_confirmation": "测试夹具：确认封面"},
            "preview_sha256": _sha256(self.final),
            "output_srt": {"path": "subtitles.srt", "sha256": "a" * 64, "bytes": 42},
        }
        manifest = {"job_id": "job-1", "final_sha256": _sha256(self.final), "artifacts": {
            "opening-manifest.json": {}, "plans/body-subtitles.webm": {},
            "subtitles/subtitles.srt": {
                "source": {"path": "11-preview/subtitles.srt"},
                "output": {"sha256": "a" * 64, "bytes": 42},
            },
        }}
        preview = self.job_dir / "11-preview/opening-manifest.json"
        def publish(payload):
            value = dict(payload)
            value["opening_manifest_sha256"] = hashlib.sha256((json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
            self._write_json(preview, value)
            self._write_json(self.delivery / "opening-manifest.json", value)
            return {"preview": {"artifacts": [self._record(preview)]}}
        stages = publish(opening)
        check = self.api()._opening_timeline
        self.assertTrue(check(self.job_dir, manifest, stages,
                              {"audio_streams": 1, "duration_seconds": 1.5}))
        for probe in ({"audio_streams": 0, "duration_seconds": 1.5},
                      {"audio_streams": 1, "duration_seconds": 1}):
            with self.subTest(probe=probe), self.assertRaises(self.api().JobCompletionAuditError):
                check(self.job_dir, manifest, stages, probe)
        for changes in ({"body_offset_frames": 18}, {"total_frames": 42},
                        {"options": {**opening["options"], "hold_frames": True}},
                        {"output_srt": {**opening["output_srt"], "sha256": "b" * 64}}):
            stages = publish({**opening, **changes})
            with self.subTest(changes=changes), self.assertRaises(self.api().JobCompletionAuditError):
                check(self.job_dir, manifest, stages, None)

    def test_delivered_without_acceptance(self):
        self.acceptance.unlink()
        result = self._audit()
        self.assertEqual("delivered", result["status"], result)
        self.assertIn("user_final_acceptance_pending", result["unproven_claims"])

    def test_incomplete_without_delivery_receipt(self):
        self.receipt.unlink()
        result = self._audit()
        self.assertEqual("incomplete", result["status"], result)
        self.assertIn("delivery_receipt_missing", result["unproven_claims"])

    def test_unfinished_stage_does_not_prove_delivery(self):
        path = self.job_dir / "workflow.json"
        workflow = json.loads(path.read_text())
        workflow["stages"]["subtitles"]["status"] = "ready"
        self._write_json(path, workflow)
        result = self._audit()
        self.assertEqual("incomplete", result["status"], result)
        self.assertIn("stages_not_completed:subtitles", result["unproven_claims"])

    def test_delivery_receipt_wrong_hash_is_rejected(self):
        receipt = json.loads(self.receipt.read_text())
        receipt["delivery"]["sha256"] = "0" * 64
        self._write_json(self.receipt, receipt)
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("delivery receipt differs from the completed output", result["failures"])

    def test_missing_or_changed_outputs_are_rejected(self):
        self.final.unlink()
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("workflow artifact changed: delivery", result["failures"])

    def test_stable_delivery_tampering_is_rejected(self):
        (self.stable / "final.mp4").write_bytes(b"changed")
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("stable delivered file is missing or changed", result["failures"])

    def test_acceptance_requires_real_user_confirmation(self):
        acceptance = json.loads(self.acceptance.read_text())
        acceptance["user_confirmation"] = " "
        self._write_json(self.acceptance, acceptance)
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("user acceptance differs from delivered output", result["failures"])

    def test_manifest_tampering_is_rejected(self):
        path = self.delivery / "delivery-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["extra"] = "changed"
        self._write_json(path, manifest)
        self.assertEqual("inconsistent", self._audit()["status"])

    def test_media_probe_must_match_manifest(self):
        result = self._audit({"width": 1920, "height": 1080, "fps": 24.0, "rotation": 0,
                              "duration_seconds": 10.0, "audio_streams": 1})
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("delivery media probe differs from output canvas", result["failures"])

    def test_changed_input_is_rejected(self):
        (self.workspace / "script.dat").write_bytes(b"changed")
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("workflow input changed", result["failures"])

    def test_malformed_stage_is_rejected(self):
        path = self.job_dir / "workflow.json"
        workflow = json.loads(path.read_text())
        workflow["stages"]["delivery"] = None
        self._write_json(path, workflow)
        self.assertEqual("inconsistent", self._audit()["status"])

if __name__ == "__main__":
    unittest.main()

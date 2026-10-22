"""Completion audit is four-state, evidence-bound, and strictly read-only."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

STAGES = (
    "inspect", "content_analysis", "cover_direction", "cover",
    "speech_cleanup", "edit_structure", "visual_direction", "visual_canary",
    "visual_assets", "subtitles", "preview", "delivery",
)


def _sha256(path: Path) -> str:
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

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _record(self, path: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(self.job_dir).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }

    def _write_formal_job(self) -> None:
        final_sha = _sha256(self.final)
        manifest = {
            "schema_version": 2,
            "job_id": "job-1",
            "workflow_revision": self.revision - 2,
            "final_sha256": final_sha,
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "artifacts": {
                "final.mp4": {
                    "output": {
                        "path": "final.mp4",
                        "sha256": final_sha,
                        "bytes": self.final.stat().st_size,
                    }
                }
            },
        }
        manifest_path = self.delivery / "delivery-manifest.json"
        self._write_json(manifest_path, manifest)
        stages = {
            stage_id: {
                "status": "approved",
                "reason": None,
                "artifacts": [],
                "ai_attempts": 0,
                "lineage": [],
                "artifact_scope": [],
            }
            for stage_id in STAGES
        }
        stages["delivery"]["artifacts"] = [
            self._record(self.final), self._record(manifest_path),
        ]
        workflow = {
            "version": 2,
            "job_id": "job-1",
            "inputs": {},
            "revision": self.revision,
            "stages": stages,
        }
        self._write_json(self.job_dir / "workflow.json", workflow)
        self._write_json(
            self.workspace / "job-context.json",
            {
                "schema_version": 1,
                "workspace": str(self.workspace),
                "job_dir": str(self.job_dir),
                "job_id": "job-1",
                "workflow": str(self.job_dir / "workflow.json"),
            },
        )
        self._write_json(
            self.delivery / "approval-receipt.json",
            {
                "schema_version": 1,
                "decision": "approved",
                "approval_kind": "formal_final",
                "job_id": "job-1",
                "workflow_revision": self.revision,
                "reviewed_revision": self.revision - 1,
                "reviewed_workflow_sha256": "a" * 64,
                "user_confirmation": "确认",
                "delivery_manifest": self._record(manifest_path),
                "approved_by": "human",
                "approved_at": "2026-09-05T10:00:00+08:00",
                "delivery": {
                    "path": "12-delivery/final.mp4",
                    "sha256": final_sha,
                    "bytes": self.final.stat().st_size,
                },
            },
        )

        workflow["stages"]["delivery"]["artifacts"].append(
            self._record(self.delivery / "approval-receipt.json")
        )
        self._write_json(self.job_dir / "workflow.json", workflow)

    def _snapshot(self) -> dict[str, tuple[str, int]]:
        return {
            path.relative_to(self.workspace).as_posix(): (_sha256(path), path.stat().st_size)
            for path in sorted(self.workspace.rglob("*"))
            if path.is_file()
        }

    def _audit(self):
        before = self._snapshot()
        revision = json.loads((self.job_dir / "workflow.json").read_text())["revision"]
        probe = {
            "width": 1080,
            "height": 1920,
            "fps": 24.0,
            "rotation": 0,
            "duration_seconds": 10.0,
            "audio_streams": 1,
        }
        with mock.patch.object(self.api(), "_probe_media", return_value=probe):
            result = self.api().audit_job_completion(self.workspace)
        self.assertEqual(before, self._snapshot())
        self.assertEqual(
            revision,
            json.loads((self.job_dir / "workflow.json").read_text())["revision"],
        )
        return result

    def test_formal_complete_requires_current_approved_evidence(self):
        result = self._audit()
        self.assertEqual("formal_complete", result["status"])
        self.assertEqual(self.revision, result["workflow_revision"])
        self.assertEqual(_sha256(self.final), result["delivery_identity"]["sha256"])
        self.assertIn("all_full_v2_stages_approved", result["verified_claims"])
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

    def test_legacy_external_approval_binds_exact_existing_hash(self):
        workflow_path = self.job_dir / "workflow.json"
        workflow = json.loads(workflow_path.read_text())
        workflow["stages"]["visual_assets"]["status"] = "pending"
        self._write_json(workflow_path, workflow)
        receipt_path = self.delivery / "approval-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["approval_kind"] = "legacy_external"
        receipt["workflow_revision"] = None
        self._write_json(receipt_path, receipt)
        workflow["stages"]["delivery"]["artifacts"][-1] = self._record(receipt_path)
        self._write_json(workflow_path, workflow)

        result = self._audit()
        self.assertEqual("legacy_external_approval", result["status"])
        self.assertIn("external_approval_exact_delivery_hash", result["verified_claims"])
        self.assertIn("formal_workflow_not_complete", result["unproven_claims"])
        self.assertEqual([], result["failures"])

    def test_incomplete_when_stage_or_final_approval_is_missing(self):
        workflow_path = self.job_dir / "workflow.json"
        workflow = json.loads(workflow_path.read_text())
        workflow["stages"]["subtitles"]["status"] = "ready_for_review"
        workflow["stages"]["delivery"]["artifacts"] = [
            r for r in workflow["stages"]["delivery"]["artifacts"]
            if r["path"] != "12-delivery/approval-receipt.json"
        ]
        self._write_json(workflow_path, workflow)
        (self.delivery / "approval-receipt.json").unlink()

        result = self._audit()
        self.assertEqual("incomplete", result["status"])
        self.assertIn("stages_not_approved:subtitles", result["unproven_claims"])
        self.assertIn("final_approval_missing", result["unproven_claims"])
        self.assertEqual([], result["failures"])

    def test_inconsistent_when_approved_hash_is_wrong(self):
        receipt_path = self.delivery / "approval-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["delivery"]["sha256"] = "0" * 64
        self._write_json(receipt_path, receipt)

        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("approval_delivery_sha256_mismatch", result["failures"])

    def test_inconsistent_when_approved_file_is_missing(self):
        self.final.unlink()
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("approved_delivery_missing", result["failures"])

    def test_inconsistent_when_workflow_artifact_identity_is_wrong(self):
        workflow_path = self.job_dir / "workflow.json"
        workflow = json.loads(workflow_path.read_text())
        workflow["stages"]["delivery"]["artifacts"][0]["bytes"] += 1
        self._write_json(workflow_path, workflow)
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("workflow_delivery_artifact_mismatch", result["failures"])

    def test_inconsistent_when_formal_receipt_revision_is_stale(self):
        receipt_path = self.delivery / "approval-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["workflow_revision"] -= 1
        self._write_json(receipt_path, receipt)
        result = self._audit()
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("approval_workflow_revision_mismatch", result["failures"])

    def test_inconsistent_when_media_probe_conflicts_with_manifest(self):
        before = self._snapshot()
        probe = {
            "width": 1920, "height": 1080, "fps": 24.0, "rotation": 0,
            "duration_seconds": 10.0, "audio_streams": 1,
        }
        with mock.patch.object(self.api(), "_probe_media", return_value=probe):
            result = self.api().audit_job_completion(self.workspace)
        self.assertEqual(before, self._snapshot())
        self.assertEqual("inconsistent", result["status"])
        self.assertIn("delivery_media_probe_mismatch", result["failures"])

    def test_unregistered_formal_receipt_does_not_prove_human_approval(self):
        workflow_path = self.job_dir / "workflow.json"
        workflow = json.loads(workflow_path.read_text())
        workflow["stages"]["delivery"]["artifacts"] = [
            r for r in workflow["stages"]["delivery"]["artifacts"]
            if r["path"] != "12-delivery/approval-receipt.json"
        ]
        self._write_json(workflow_path, workflow)
        self.assertEqual(self._audit()["status"], "inconsistent")

    def test_blank_user_confirmation_does_not_prove_human_approval(self):
        receipt_path = self.delivery / "approval-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["user_confirmation"] = " "
        self._write_json(receipt_path, receipt)
        self.assertEqual(self._audit()["status"], "inconsistent")

    def test_manifest_tampering_cannot_keep_formal_complete(self):
        manifest_path = self.delivery / "delivery-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["extra"] = "changed after user approval"
        self._write_json(manifest_path, manifest)
        self.assertEqual(self._audit()["status"], "inconsistent")

    def test_malformed_record_containers_return_inconsistent(self):
        for name in ("stage_artifacts", "manifest_artifacts", "canvas", "nonfinite"):
            with self.subTest(name=name):
                self._write_formal_job()
                path = (self.job_dir / "workflow.json" if name == "stage_artifacts"
                        else self.delivery / "delivery-manifest.json")
                value = json.loads(path.read_text())
                if name == "stage_artifacts":
                    value["stages"]["delivery"]["artifacts"] = None
                elif name == "manifest_artifacts":
                    value["artifacts"] = None
                elif name == "canvas":
                    value["canvas"] = None
                else:
                    value["canvas"]["fps"] = float("nan")
                self._write_json(path, value)
                self.assertEqual(self._audit()["status"], "inconsistent")

    def test_malformed_enums_and_stage_return_inconsistent(self):
        for name in ("approval_kind", "delivery_status", "delivery_stage"):
            with self.subTest(name=name):
                self._write_formal_job()
                path = (self.delivery / "approval-receipt.json" if name == "approval_kind"
                        else self.job_dir / "workflow.json")
                value = json.loads(path.read_text())
                if name == "approval_kind":
                    value["approval_kind"] = []
                elif name == "delivery_status":
                    value["stages"]["delivery"]["status"] = []
                else:
                    value["stages"]["delivery"] = None
                self._write_json(path, value)
                self.assertEqual(self._audit()["status"], "inconsistent")


if __name__ == "__main__":
    unittest.main()

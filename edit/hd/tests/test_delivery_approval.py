"""Final user confirmation must commit once and remain bound to reviewed bytes."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from edit.hd.tests import test_qa_delivery as delivery_fixtures
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tools import cli, contract_artifacts, delivery_approval, qa_delivery_v2, state


SKILL = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head"


class DeliveryApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = delivery_fixtures.SemanticSourceDeliveryTests()._persisted_job(
            self.root, attribution_required=False,
        )
        approve_fixture_setup(self.job)  # Synthetic setup, never a user approval.
        qa_delivery_v2.prepare_delivery_v2(self.job)
        self.before_revision = self.job.revision
        self.digest = contract_artifacts.sha256_file(self.job.job_dir / "12-delivery/final.mp4")

    def invoke(self, *, revision=None, digest=None, confirmation="确认", omit=False):
        args = ["approve", "--job", str(self.job.job_dir), "--stage", "delivery"]
        if not omit:
            args += [
                "--expected-revision", str(self.before_revision if revision is None else revision),
                "--delivery-sha256", self.digest if digest is None else digest,
                "--user-confirmation", confirmation,
            ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = cli.main(args)
        return result, out.getvalue(), err.getvalue()

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def audit(self, *, real_media=False):
        spec = importlib.util.spec_from_file_location(
            "approval_audit", SKILL / "scripts/audit_job_completion.py",
        )
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        before = self.snapshot()
        probe = {"width": 1080, "height": 1920, "fps": 24, "rotation": 0,
                 "duration_seconds": 1, "audio_streams": 1}
        if real_media:
            result = api.audit_job_completion(self.root)
        else:
            with mock.patch.object(api, "_probe_media", return_value=probe):
                result = api.audit_job_completion(self.root)
        self.assertEqual(before, self.snapshot())
        return result

    def test_cli_commits_receipt_and_approval_once_then_delivery_reuses(self):
        result, _, error = self.invoke()
        self.assertEqual(result, 0, error)
        current = state.load_job(self.job.job_dir)
        self.assertEqual(current.revision, self.before_revision + 1)
        self.assertEqual(current.stages["delivery"]["status"], "approved")
        receipt_path = current.job_dir / "12-delivery/approval-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["user_confirmation"], "确认")
        self.assertEqual(receipt["workflow_revision"], current.revision)
        self.assertEqual(receipt["delivery"]["sha256"], self.digest)
        self.assertIn(state._artifact_record(current, receipt_path), current.stages["delivery"]["artifacts"])
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 0)
        qa_delivery_v2.prepare_delivery_v2(current)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.audit()["status"], "formal_complete")

    def visual_approval_fixture(self):
        """Seed synthetic user plan approval into the existing delivery fixture."""
        table = self.job.job_dir / '07-visual-direction/visual-routing.md'
        table.write_text('| 时间 | 类型 | 语义 | 标签 | 模板 |\n| 0–3s | B-roll | 对比 | 对比 | fixture-template |\n')
        self.job.stages['visual_direction']['artifacts'].append(state._artifact_record(self.job, table))
        state.save_job(self.job)
        review_revision = self.job.revision - 2
        path = self.job.job_dir / f'manifests/local-qa-visual_direction-r{review_revision}.json'
        contract_artifacts.write_json_artifact(path, {
            'job_id': self.job.job_id, 'job_dir': str(self.job.job_dir),
            'stage': 'visual_direction', 'revision': review_revision,
            'artifacts': self.job.stages['visual_direction']['artifacts'],
            'passed': True, 'note': 'fixture only: full list inspected',
            'user_confirmation': 'fixture only: approve this list and deliver',
            'reviewed_by': 'human', 'approval_scope': 'visual_plan_and_delivery',
        })
        return path

    def test_plan_confirmation_then_host_qa_completes_without_final_user_confirmation(self):
        source = self.visual_approval_fixture()
        path = delivery_approval.approve_plan_delivery(self.job,
            expected_revision=self.before_revision, delivery_sha256=self.digest,
            qa_note='fixture: video, speech and subtitles checked')
        receipt = json.loads(path.read_text())
        self.assertEqual(receipt['approval_kind'], 'plan_authorized')
        self.assertEqual(receipt['approved_by'], 'host')
        self.assertNotIn('user_confirmation', receipt)
        self.assertEqual(receipt['visual_approval'], state._artifact_record(self.job, source))
        self.assertEqual(self.job.stages['delivery']['status'], 'approved')
        result = self.audit()
        self.assertEqual(result['status'], 'formal_complete', result)
        self.assertIn('plan_authorized_delivery', result['verified_claims'])
        snapshot = self.snapshot()
        delivery_approval.approve_plan_delivery(self.job,
            expected_revision=self.before_revision, delivery_sha256=self.digest,
            qa_note='fixture: video, speech and subtitles checked')
        self.assertEqual(snapshot, self.snapshot())

    def test_new_source_mapping_is_audited_from_another_directory_and_revision_is_pending(self):
        from edit.hd.tools import visual_confirmation as vc
        root = self.job.job_dir
        directory = root / "07-visual-confirmation/fixture"
        director = directory / "director.json"
        treatment = directory / "treatment.json"
        original = contract_artifacts.read_json_artifact(root / "07-visual-direction/visual-plan.json")
        contract_artifacts.write_json_artifact(director, original)
        contract_artifacts.write_json_artifact(treatment, {"motion_queries": [], "generation_plan": {}})
        inputs = {"director": vc._record(root, director), "treatment": vc._record(root, treatment)}
        proposal = {"kind": vc.SCHEMA, "job_id": self.job.job_id, "source_id": "fixture",
                    "inputs": inputs, "rows": [], "generation_steps": [],
                    "provider_config_sha256": contract_artifacts.sha256_file(root / "manifests/provider-config.json")}
        proposed = directory / "proposal.json"
        contract_artifacts.write_json_artifact(proposed, proposal)
        approval = root / f"manifests/local-qa-visual_direction-r{self.job.revision - 2}.json"
        contract_artifacts.write_json_artifact(approval, {
            "source_schema": vc.SCHEMA, "source": vc._record(root, proposed), "job_id": self.job.job_id,
            "job_dir": str(root), "stage": "visual_direction", "passed": True, "reviewed_by": "human",
            "approval_scope": "visual_plan_and_delivery", "note": "synthetic source QA",
            "user_confirmation": "synthetic exact source confirmation", "revision": self.job.revision - 2,
            "artifacts": [vc._record(root, proposed), *inputs.values()]})
        table = root / "07-visual-direction/visual-routing.md"
        table.write_text("synthetic complete list")
        self.job.stages["visual_direction"]["artifacts"].append(vc._record(root, table))
        records = list(self.job.stages["visual_direction"]["artifacts"])
        mapping = directory / vc.MAPPING
        contract_artifacts.write_json_artifact(mapping, {
            "source_approval": vc._record(root, approval), "proposal": vc._record(root, proposed),
            "final_v3": next(r for r in records if r["path"].endswith("visual-plan.json")),
            "artifacts": records, "rows": [], "generations": [], "completed_records": [], "native_inputs": [],
            "realization_inputs": inputs, "host_qa_note": "synthetic realized QA"})
        self.job.stages["visual_direction"]["artifacts"].append(vc._record(root, mapping))
        state.save_job(self.job)
        delivery_approval.approve_plan_delivery(self.job, expected_revision=self.before_revision,
            delivery_sha256=self.digest, qa_note="synthetic final QA")
        self.assertEqual(self.audit()["status"], "formal_complete")
        program = """import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('standalone_audit',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module._probe_media=lambda path: {'width':1080,'height':1920,'fps':24,'rotation':0,'duration_seconds':1,'audio_streams':1}
print(json.dumps(module.audit_job_completion(Path(sys.argv[2]))))
"""
        result = subprocess.run([sys.executable, "-c", program, str(SKILL / "scripts/audit_job_completion.py"), str(self.root)],
                                cwd="/tmp", capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "formal_complete", result.stdout)
        state.revise(self.job, "delivery", "synthetic requested revision")
        self.assertEqual(self.audit()["status"], "incomplete")
        self.assertTrue(approval.exists())

    def test_plan_delivery_rejects_missing_or_changed_plan_approval(self):
        with self.assertRaises(state.WorkflowError):
            delivery_approval.approve_plan_delivery(self.job,
                expected_revision=self.before_revision, delivery_sha256=self.digest, qa_note='fixture QA')
        source = self.visual_approval_fixture()
        payload = json.loads(source.read_text()); payload['artifacts'] = []
        contract_artifacts.write_json_artifact(source, payload)
        with self.assertRaises(state.WorkflowError):
            delivery_approval.approve_plan_delivery(self.job,
                expected_revision=self.before_revision, delivery_sha256=self.digest, qa_note='fixture QA')
        self.assertEqual(state.load_job(self.job.job_dir).stages['delivery']['status'], 'ready_for_review')

    def test_missing_confirmation_cannot_approve(self):
        before = self.snapshot()
        self.assertEqual(self.invoke(omit=True)[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_changed_review_identity_or_blank_confirmation_is_zero_write(self):
        for args in ({"revision": self.before_revision - 1}, {"digest": "0" * 64},
                     {"confirmation": " "}):
            with self.subTest(args=args):
                before = self.snapshot()
                self.assertEqual(self.invoke(**args)[0], 2)
                self.assertEqual(before, self.snapshot())

    def test_precommit_failure_is_pending_and_same_confirmation_can_resume(self):
        before_workflow = (self.job.job_dir / "workflow.json").read_bytes()
        with mock.patch.object(state, "save_job", side_effect=OSError("before commit")):
            self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before_workflow, (self.job.job_dir / "workflow.json").read_bytes())
        receipt = self.job.job_dir / "12-delivery/approval-receipt.json"
        self.assertTrue(receipt.exists())
        receipt_bytes = receipt.read_bytes()
        self.assertEqual(self.audit()["status"], "incomplete")
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(receipt_bytes, receipt.read_bytes())
        self.assertEqual(self.audit()["status"], "formal_complete")

    def test_postcommit_exception_keeps_receipt_and_retry_does_not_increment(self):
        original = state.approve
        def committed_then_interrupt(job, stage_id):
            original(job, stage_id)
            raise OSError("response interrupted after commit")
        with mock.patch.object(state, "approve", side_effect=committed_then_interrupt):
            self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(state.load_job(self.job.job_dir).revision, self.before_revision + 1)
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(state.load_job(self.job.job_dir).revision, self.before_revision + 1)

    def test_old_approved_job_is_not_retroactively_signed(self):
        state.approve(self.job, "delivery")
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_revision_retires_old_receipt_without_reusing_confirmation(self):
        self.assertEqual(self.invoke()[0], 0)
        current = state.load_job(self.job.job_dir)
        state.revise(current, "delivery", "重新审核交付")
        result = self.audit()
        self.assertEqual(result["status"], "incomplete", result)
        self.assertEqual(self.invoke()[0], 2)
        qa_delivery_v2.prepare_delivery_v2(current)
        self.assertFalse((current.job_dir / "12-delivery/approval-receipt.json").exists())
        self.assertEqual(self.audit()["status"], "incomplete")
        self.assertEqual(self.invoke()[0], 2)  # Old confirmation cannot approve the replacement.
        self.before_revision = current.revision
        self.assertEqual(self.invoke(confirmation="重新确认本次交付")[0], 0)
        self.assertEqual(self.audit()["status"], "formal_complete")

    def test_tampered_registered_receipt_cannot_be_replayed(self):
        self.assertEqual(self.invoke()[0], 0)
        receipt = self.job.job_dir / "12-delivery/approval-receipt.json"
        receipt.write_bytes(receipt.read_bytes() + b" ")
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.audit()["status"], "inconsistent")

    def test_unexpected_delivery_file_is_rejected_as_a_cli_error(self):
        (self.job.job_dir / "12-delivery/unknown.txt").write_text("unexpected")
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_pending_intent_cannot_be_replaced_with_another_confirmation(self):
        with mock.patch.object(state, "save_job", side_effect=OSError("before commit")):
            self.assertEqual(self.invoke()[0], 2)
        before = self.snapshot()
        self.assertEqual(self.invoke(confirmation="别的确认")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_unsafe_existing_receipt_is_not_overwritten(self):
        receipt = self.job.job_dir / "12-delivery/approval-receipt.json"
        outside = self.root / "outside.json"
        outside.write_text("{}")
        receipt.symlink_to(outside)
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(receipt.is_symlink())

    def test_pending_retry_rejects_new_unknown_delivery_file(self):
        with mock.patch.object(state, "save_job", side_effect=OSError("before commit")):
            self.assertEqual(self.invoke()[0], 2)
        (self.job.job_dir / "12-delivery/unknown.txt").write_text("unexpected")
        before = self.snapshot()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_special_delivery_entry_blocks_initial_and_pending_approval(self):
        special = self.job.job_dir / "12-delivery/unregistered-pipe"
        for pending in (False, True):
            with self.subTest(pending=pending):
                if pending:
                    with mock.patch.object(state, "save_job", side_effect=OSError("before commit")):
                        self.assertEqual(self.invoke()[0], 2)
                os.mkfifo(special)
                before = self.snapshot()
                try:
                    self.assertEqual(self.invoke()[0], 2)
                    self.assertEqual(before, self.snapshot())
                finally:
                    special.unlink()

    def test_missing_registered_receipt_is_inconsistent(self):
        self.assertEqual(self.invoke()[0], 0)
        (self.job.job_dir / "12-delivery/approval-receipt.json").unlink()
        self.assertEqual(self.audit()["status"], "inconsistent")

    def test_modified_non_video_delivery_artifact_is_inconsistent(self):
        self.assertEqual(self.invoke()[0], 0)
        current = state.load_job(self.job.job_dir)
        record = next(r for r in current.stages["delivery"]["artifacts"]
                      if r["path"].endswith(".srt"))
        (self.job.job_dir / record["path"]).write_text("changed subtitle")
        self.assertEqual(self.audit()["status"], "inconsistent")

    def test_hard_interruption_before_receipt_publish_can_retry(self):
        script = '''
import os
from pathlib import Path
from edit.hd.tools import state, delivery_approval, contract_artifacts
original = contract_artifacts.os.replace
def kill_before_publish(source, target):
    if "approval-receipt" in str(target):
        os._exit(91)
    original(source, target)
contract_artifacts.os.replace = kill_before_publish
delivery_approval.approve_delivery(state.load_job(Path(JOB)), expected_revision=REV,
                                  delivery_sha256=DIGEST, user_confirmation="确认")
'''
        script = f"JOB={str(self.job.job_dir)!r}\nREV={self.before_revision}\nDIGEST={self.digest!r}\n" + script
        before = (self.job.job_dir / "workflow.json").read_bytes()
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 91, result.stderr)
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(self.audit()["status"], "formal_complete")

    def test_receipt_publisher_never_overwrites_an_existing_target(self):
        from edit.hd.tools.delivery_approval import _publish_receipt
        target = self.job.job_dir / "12-delivery/approval-receipt.json"
        target.write_text("existing intent")
        before = self.snapshot()
        with self.assertRaises(OSError):
            _publish_receipt(target, {"unexpected": "replacement"})
        self.assertEqual(before, self.snapshot())

    def test_receipt_publication_without_platform_support_fails_closed(self):
        from edit.hd.tools import delivery_approval
        before = self.snapshot()
        with mock.patch.object(delivery_approval.sys, "platform", "unsupported"):
            with self.assertRaises(state.WorkflowError):
                delivery_approval._publish_receipt(
                    self.job.job_dir / "12-delivery/approval-receipt.json", {},
                )
        self.assertEqual(before, self.snapshot())

    def test_unknown_or_missing_extra_delivery_files_fail_completion_audit(self):
        self.assertEqual(self.invoke()[0], 0)
        extra = self.job.job_dir / "12-delivery/unknown.txt"
        extra.write_text("not reviewed")
        self.assertEqual(self.audit()["status"], "inconsistent")
        extra.unlink()
        current = state.load_job(self.job.job_dir)
        cover = next(r for r in current.stages["delivery"]["artifacts"]
                     if r["path"].endswith(".png"))
        (self.job.job_dir / cover["path"]).unlink()
        self.assertEqual(self.audit()["status"], "inconsistent")

    def test_real_media_delivery_cli_to_read_only_audit(self):
        clip = self.root / "fixture.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=1080x1920:r=24",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.25",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
        ], check=True, capture_output=True)
        content = clip.read_bytes()
        self.root = self.root / "real-case"
        self.root.mkdir()
        self.job = delivery_fixtures.SemanticSourceDeliveryTests()._persisted_job(
            self.root, attribution_required=False, preview_content=content,
        )
        approve_fixture_setup(self.job)
        qa_delivery_v2.prepare_delivery_v2(self.job)
        self.before_revision = self.job.revision
        self.digest = contract_artifacts.sha256_file(self.job.job_dir / "12-delivery/final.mp4")
        result = subprocess.run([
            sys.executable, "-m", "edit.hd.tools.cli", "approve", "--job", str(self.job.job_dir),
            "--stage", "delivery", "--expected-revision", str(self.before_revision),
            "--delivery-sha256", self.digest, "--user-confirmation", "确认",
        ], cwd=self.root, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
                              "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.audit(real_media=True)
        self.assertEqual(result["status"], "formal_complete", result)


if __name__ == "__main__":
    unittest.main()

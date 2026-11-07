"""Current delivery and user acceptance bind to an immutable manifest identity."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from edit.hd.tests.media_fixture import make_av_fixture
from edit.hd.tools import cli, delivery_approval as delivery, state

SKILL = Path(__file__).resolve().parents[3]


class DeliveryApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory()
        cls.media = make_av_fixture(Path(cls.media_temp.name).resolve())

    @classmethod
    def tearDownClass(cls):
        cls.media_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        video = self.root / 'source.mp4'
        video.write_bytes(self.media.read_bytes())
        script = self.root / 'script.txt'
        script.write_text('synthetic fixture speech')
        startup_patch = mock.patch('edit.hd.tools.startup.require_startup')
        startup_patch.start()
        self.addCleanup(startup_patch.stop)
        self.job = state.create_job(self.root, video, script)
        self.preview = self.job.job_dir / '11-preview/review.mp4'
        self.preview.parent.mkdir()
        self.preview.write_bytes(video.read_bytes())
        self.final = self.job.job_dir / '12-delivery/final.mp4'
        self.manifest = self.final.parent / 'delivery-manifest.json'
        self.final.parent.mkdir()
        self.final.write_bytes(self.preview.read_bytes())
        self.publish_manifest()
        for stage in state.stage_ids_for(self.job):
            paths = ([self.preview] if stage == 'preview' else
                     [self.final, self.manifest] if stage == 'delivery' else [])
            state.mark_ready(self.job, stage, paths)
            state.complete(self.job, stage)
        (self.root / 'job-context.json').write_text(json.dumps({
            'workspace': str(self.root), 'job_dir': str(self.job.job_dir), 'job_id': self.job.job_id}))
        authorization = self.job.job_dir / 'manifests/visual-authorization-r1.json'
        authorization.parent.mkdir(exist_ok=True)
        authorization.write_text(json.dumps({'job_id': self.job.job_id, 'authorized_by': 'user',
            'authorization_scope': 'visual_plan_and_generation',
            'user_confirmation': 'synthetic fixture authorization'}))
        authorization_patch = mock.patch.object(delivery, 'validate_visual_plan_approval',
            return_value={'artifact': state._artifact_record(self.job, authorization)})
        authorization_patch.start()
        self.addCleanup(authorization_patch.stop)
        self.refresh_identity()

    def publish_manifest(self):
        self.manifest.write_text(json.dumps({'schema_version': 2, 'job_id': self.job.job_id,
            'workflow_revision': self.job.revision, 'workflow_sha256': self.job.expected_sha256,
            'final_sha256': hashlib.sha256(self.final.read_bytes()).hexdigest(),
            'canvas': {'width': 1080, 'height': 1920, 'fps': 24},
            'artifacts': {'final.mp4': {'source': state._artifact_record(self.job, self.preview),
                'output': {'path': 'final.mp4', 'sha256': hashlib.sha256(self.final.read_bytes()).hexdigest(),
                           'bytes': self.final.stat().st_size}}}}))

    def refresh_identity(self):
        self.manifest_record = next(r for r in self.job.stages['delivery']['artifacts']
                                    if r['path'].endswith('/delivery-manifest.json'))
        self.manifest_digest = self.manifest_record['sha256']
        self.digest = hashlib.sha256(self.final.read_bytes()).hexdigest()
        delivered, accepted = delivery.receipt_paths(self.manifest_record)
        self.receipt = self.job.job_dir / delivered
        self.acceptance = self.job.job_dir / accepted

    def approve(self, **changes):
        args = {'delivery_manifest_sha256': self.manifest_digest, 'delivery_sha256': self.digest,
                'user_confirmation': 'synthetic user acceptance'}
        args.update(changes)
        return delivery.approve_delivery(self.job, **args)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def audit(self):
        spec = importlib.util.spec_from_file_location('delivery_audit', SKILL / 'scripts/audit_job_completion.py')
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        before = self.snapshot()
        result = api.audit_job_completion(self.root)
        self.assertEqual(before, self.snapshot())
        return result

    def test_delivery_is_not_user_acceptance_and_retry_is_idempotent(self):
        self.assertEqual(delivery.current_delivery_status(self.job)['delivery_status'], 'pending')
        delivery.record_delivery(self.job)
        self.assertFalse(self.acceptance.exists())
        self.assertEqual(delivery.current_delivery_status(self.job)['delivery_status'], 'delivered')
        self.assertEqual(self.audit()['status'], 'delivered')
        before = self.snapshot()
        delivery.record_delivery(self.job)
        self.assertEqual(before, self.snapshot())
        self.approve()
        self.assertEqual(delivery.current_delivery_status(self.job)['delivery_status'], 'accepted')
        self.assertEqual(self.audit()['status'], 'accepted')
        before = self.snapshot()
        self.approve()
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(state.WorkflowError):
            self.approve(user_confirmation='different feedback')
        self.assertEqual(before, self.snapshot())

    def test_retired_host_approval_is_rejected_without_writes(self):
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = cli.main(['approve', '--job', str(self.job.job_dir), '--stage', 'delivery'])
        self.assertEqual(result, 2)
        self.assertFalse(hasattr(delivery, 'approve_plan_delivery'))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.acceptance.exists())

    def test_wrong_identity_or_blank_confirmation_cannot_accept(self):
        delivery.record_delivery(self.job)
        before = self.snapshot()
        for changes in ({'delivery_manifest_sha256': '0' * 64}, {'delivery_sha256': '0' * 64},
                        {'user_confirmation': ' '}):
            with self.subTest(changes=changes), self.assertRaises(state.WorkflowError):
                self.approve(**changes)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.acceptance.exists())

    def test_interruption_before_and_after_receipt_publish_can_retry(self):
        delivery.record_delivery(self.job)
        with mock.patch.object(delivery, '_publish_receipt', side_effect=OSError('before publish')):
            with self.assertRaises(OSError):
                self.approve()
        self.assertFalse(self.acceptance.exists())
        publish = delivery._publish_receipt
        def publish_then_fail(path, data):
            publish(path, data)
            raise OSError('after publish')
        with mock.patch.object(delivery, '_publish_receipt', side_effect=publish_then_fail):
            with self.assertRaises(OSError):
                self.approve()
        before = self.snapshot()
        self.approve()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.audit()['status'], 'accepted')

    def test_revision_preserves_old_files_and_requires_new_acceptance(self):
        delivery.record_delivery(self.job)
        self.approve()
        old_file = Path(delivery.current_delivery_status(self.job)['delivery_file'])
        old_bytes = old_file.read_bytes()
        old_manifest = self.manifest_digest
        state.revise(self.job, 'delivery', 'synthetic revision')
        self.assertEqual(delivery.current_delivery_status(self.job)['delivery_status'], 'pending')
        self.publish_manifest()
        state.mark_ready(self.job, 'delivery', [self.final, self.manifest])
        state.complete(self.job, 'delivery')
        self.refresh_identity()
        self.assertNotEqual(old_manifest, self.manifest_digest)
        delivery.record_delivery(self.job)
        self.assertEqual(old_file.read_bytes(), old_bytes)
        self.assertEqual(self.audit()['status'], 'delivered')
        with self.assertRaises(state.WorkflowError):
            self.approve(delivery_manifest_sha256=old_manifest)
        self.assertFalse(self.acceptance.exists())
        self.approve()
        self.assertEqual(self.audit()['status'], 'accepted')

    def test_tampered_acceptance_is_rejected(self):
        delivery.record_delivery(self.job)
        self.approve()
        self.acceptance.write_bytes(self.acceptance.read_bytes().replace(b'synthetic user acceptance', b' '))
        self.assertEqual(self.audit()['status'], 'inconsistent')
        with self.assertRaises(state.WorkflowError):
            self.approve()

    def test_changed_stable_copy_is_not_reused(self):
        delivery.record_delivery(self.job)
        stable = Path(delivery.current_delivery_status(self.job)['delivery_file'])
        stable.write_bytes(b'changed')
        before = self.snapshot()
        with self.assertRaises(state.WorkflowError):
            delivery.record_delivery(self.job)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.audit()['status'], 'inconsistent')

    def test_existing_receipt_is_never_overwritten(self):
        target = self.job.job_dir / 'manifests/example/receipt.json'
        target.parent.mkdir(parents=True)
        target.write_text('existing')
        with self.assertRaises(OSError):
            delivery._publish_receipt(target, {'replacement': True})
        self.assertEqual(target.read_text(), 'existing')

    def test_unregistered_or_missing_delivery_files_fail_read_only_audit(self):
        delivery.record_delivery(self.job)
        extra = self.final.parent / 'unknown.txt'
        extra.write_text('unexpected')
        self.assertEqual(self.audit()['status'], 'inconsistent')
        extra.unlink()
        self.final.unlink()
        self.assertEqual(self.audit()['status'], 'inconsistent')

    def test_valid_receipt_cannot_be_read_through_symlink(self):
        delivery.record_delivery(self.job)
        self.approve()
        for path in (self.receipt, self.acceptance):
            with self.subTest(receipt=path.name):
                outside = self.root / path.name
                path.rename(outside)
                path.symlink_to(outside)
                before = self.snapshot()
                try:
                    with self.assertRaises(state.WorkflowError):
                        delivery.current_delivery_status(self.job)
                    with self.assertRaises(state.WorkflowError):
                        self.approve()
                    self.assertEqual(before, self.snapshot())
                    self.assertEqual(self.audit()['status'], 'inconsistent')
                finally:
                    path.unlink()
                    outside.rename(path)

    def test_receipt_publisher_requires_exclusive_platform_support(self):
        target = self.job.job_dir / 'manifests/example/receipt.json'
        target.parent.mkdir(parents=True)
        before = self.snapshot()
        with mock.patch.object(delivery.sys, 'platform', 'unsupported'):
            with self.assertRaises(state.WorkflowError):
                delivery._publish_receipt(target, {})
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()

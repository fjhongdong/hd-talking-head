"""Minimal contract tests for execute_stage (no media or provider calls)."""
from __future__ import annotations
import contextlib, copy, io, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import PROJECT, SKILL  # noqa: F401
sys.path.insert(0, str(SKILL / "scripts"))
import run_stage

class ExecuteStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake(self, status="pending", current="inspect"):
        names = ["inspect", "content_analysis", "cover_direction", "cover", "speech_cleanup", "edit_structure", "visual_direction"]
        stages = {name: {"status": "approved"} for name in names}; stages[current] = {"status": status}
        job = SimpleNamespace(job_dir=self.root, stages=stages, inputs={}, root=self.root)
        return job

    def invoke(self, job, stage, **kwargs):
        with mock.patch("edit.hd.tools.state.load_job", return_value=job), \
             mock.patch("edit.hd.tools.state.current_stage", return_value=stage), \
             mock.patch.object(run_stage, "_startup"), \
             mock.patch("edit.hd.tools.state.require_runnable"), \
             mock.patch.object(run_stage, "_summary", side_effect=lambda j, s, **kw: {"stage": s, **kw}):
            return run_stage.execute_stage(self.root, PROJECT, stage, **kwargs)

    def test_approved_reuses_without_runner(self):
        job = self.fake("approved")
        with mock.patch("edit.hd.tools.inspect_inputs.inspect_job") as runner:
            out = self.invoke(job, "inspect")
        runner.assert_not_called(); self.assertTrue(out["reused"])

    def test_ready_does_not_render_again(self):
        job = self.fake("ready_for_review")
        with mock.patch("edit.hd.tools.inspect_inputs.inspect_job") as runner:
            out = self.invoke(job, "inspect")
        runner.assert_not_called(); self.assertTrue(out["reused"])

    def test_needs_revision_runs_original_runner(self):
        job = self.fake("needs_revision")
        with mock.patch("edit.hd.tools.inspect_inputs.inspect_job") as runner:
            self.invoke(job, "inspect")
        runner.assert_called_once_with(job)

    def test_speech_passes_explicit_inputs_without_render_edit(self):
        job = self.fake(current="speech_cleanup")
        with mock.patch.object(run_stage, "run_speech_cleanup", return_value={"speech_cleanup": "ready_for_review"}) as speech, \
             mock.patch("edit.hd.tools.speech_edit_v2.render_edit") as render:
            result = self.invoke(job, "speech_cleanup", video_use_result=Path("r.json"), invocation_path=Path("i.json"), cleanup_plan=Path("p.json"))
        speech.assert_called_once_with(self.root, PROJECT, Path("r.json"), Path("i.json"), Path("p.json")); render.assert_not_called(); self.assertEqual(result["speech_cleanup"], "ready_for_review")

    def test_confirmed_content_bytes_are_preserved_by_visual_runner(self):
        confirmed = self.root / "manifests" / "confirmed-content.json"; confirmed.parent.mkdir()
        original = {"schema_version": 1, "visuals": [{"id": "approved"}]}; confirmed.write_text(json.dumps(original))
        job = self.fake(current="visual_direction")
        review = self.root / "review.json"; review.write_text('{}')
        with mock.patch("edit.hd.tools.state.load_job", return_value=job), \
             mock.patch("edit.hd.tools.visual_plan.prepare_visual_direction") as visual, \
             mock.patch.object(run_stage, "_summary", return_value={}):
            run_stage.run_visual_direction(self.root, PROJECT, Path("brief.json"), Path("treatment.json"), review)
        visual.assert_called_once()
        self.assertEqual(json.loads(confirmed.read_text()), original)

class ReviewAndDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def ready_job(self, name, video):
        from edit.hd.tools import state
        root = self.root / name; root.mkdir()
        source = root / 'source.mp4'; source.write_bytes(video)
        script = root / 'script.txt'; script.write_text('本期文案')
        job = state.create_job(root, source, script)
        candidate = job.job_dir / 'inspect.json'; candidate.write_text('{"checked": true}')
        with mock.patch('edit.hd.tools.startup.require_startup'):
            state.mark_ready(job, 'inspect', [candidate])
        return state.load_job(job.job_dir)

    def review(self, job):
        return {key: copy.deepcopy(value) for key, value in
                run_stage._summary(job, 'inspect').items()
                if key in {'job_id', 'job_dir', 'stage', 'revision', 'artifacts'}} | {
                    'passed': True, 'note': '检查过本期实际候选'}

    def test_review_is_bound_to_job_and_candidate_before_approval(self):
        from edit.hd.tools import state
        job_a = self.ready_job('a', b'video-a')
        job_b = self.ready_job('b', b'video-b')
        review = self.review(job_a)
        self.assertEqual(review['job_id'], job_a.job_id)
        for target, altered in ((job_b, review),
                                (job_a, review | {'artifacts': []}),
                                (job_a, review | {'job_dir': str(job_b.job_dir)})):
            with self.subTest(target=target.job_id, review=altered), self.assertRaises(ValueError):
                run_stage._review(target, 'inspect', altered)
        approved = run_stage._review(job_a, 'inspect', review)
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(state.load_job(job_b.job_dir).stages['inspect']['status'], 'ready_for_review')

    def test_changed_candidate_rejects_old_artifact_identity(self):
        from edit.hd.tools import state
        job = self.ready_job('a', b'video-a')
        old_review = self.review(job)
        state.revise(job, 'inspect', '更新检查结果')
        candidate = job.job_dir / 'inspect-v2.json'; candidate.write_text('{"checked": "v2"}')
        with mock.patch('edit.hd.tools.startup.require_startup'):
            state.mark_ready(job, 'inspect', [candidate])
        old_review['revision'] = job.revision
        with self.assertRaises(ValueError):
            run_stage._review(job, 'inspect', old_review)

    def test_official_image_does_not_use_video_adapter(self):
        component = {'kind': 'official_material', 'media_type': 'image'}
        plan = {'segments': [{'shot_recipe': {'components': [component]}}]}
        with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan), \
             mock.patch.object(run_stage, '_module') as loader:
            with self.assertRaisesRegex(ValueError, 'adapter-factory'):
                run_stage.native_component_adapters(PROJECT, SimpleNamespace(job_dir=self.root))
        loader.assert_not_called()

    def test_official_video_keeps_native_adapter(self):
        component = {'kind': 'official_material', 'media_type': 'video'}
        plan = {'segments': [{'shot_recipe': {'components': [component]}}]}
        factory = SimpleNamespace(create_adapter=mock.Mock(return_value='video-adapter'),
                                  create_artifact_probe=mock.Mock(return_value='probe'))
        with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan), \
             mock.patch.object(run_stage, '_module', return_value=factory):
            adapters = run_stage.native_component_adapters(PROJECT, SimpleNamespace(job_dir=self.root))
        self.assertEqual(adapters['official_material'], 'video-adapter')

    def test_explicit_image_factory_reaches_existing_runner(self):
        factory = self.root / 'image_factory.py'
        factory.write_text("def create_adapters(job, project):\n    return {'official_material': 'image-adapter'}\n")
        job = SimpleNamespace(job_dir=self.root, root=self.root,
                              stages={'visual_canary': {'status': 'pending'}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_canary'), \
             mock.patch('edit.hd.tools.state.require_runnable'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval'), \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch.object(run_stage, '_summary', return_value={}), \
             mock.patch('edit.hd.tools.visual_canary.prepare_visual_canary') as prepare:
            run_stage.execute_stage(self.root, PROJECT, adapter_factory=factory)
        prepare.assert_called_once_with(job, component_adapters={'official_material': 'image-adapter'})

    def test_completion_status_controls_exit_code(self):
        context = self.root / 'job-context.json'
        context.write_text(json.dumps({'project_root': str(PROJECT), 'job_dir': str(self.root)}))
        for status, expected in (('inconsistent', 1), ('formal_complete', 0),
                                 ('legacy_external_approval', 0), ('incomplete', 0)):
            output = io.StringIO()
            with self.subTest(status=status), \
                 mock.patch.object(sys, 'argv', ['run_stage', '--job-context', str(context)]), \
                 mock.patch.object(run_stage, 'execute_stage', return_value={'status': status}), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(run_stage.main(), expected)
            self.assertEqual(json.loads(output.getvalue())['status'], status)

    def test_visual_list_requires_user_confirmation_and_records_delivery_scope(self):
        records = []
        for name in ('visual-plan.json', 'visual-routing.md'):
            path = self.root / '07-visual-direction' / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('current plan')
            records.append({'path': str(path.relative_to(self.root)), 'sha256': 'a' * 64, 'bytes': 12})
        job = SimpleNamespace(job_id='this-job', job_dir=self.root, revision=7,
                              stages={'visual_direction': {'status': 'ready_for_review', 'artifacts': records}})
        review = {
            'job_id': job.job_id, 'job_dir': str(job.job_dir), 'revision': 7,
            'stage': 'visual_direction', 'artifacts': records, 'passed': True, 'note': '已核对完整清单'}
        with self.assertRaises(ValueError):
            run_stage._review(job, 'visual_direction', review)
        review['user_confirmation'] = '确认整张表，按表制作交付'
        with mock.patch('edit.hd.tools.state.approve') as approve, \
             mock.patch('edit.hd.tools.state.load_job', return_value=job):
            run_stage._review(job, 'visual_direction', review)
        approve.assert_called_once_with(job, 'visual_direction')
        receipt = json.loads((self.root/'manifests/local-qa-visual_direction-r7.json').read_text())
        self.assertEqual(receipt['approval_scope'], 'visual_plan_and_delivery')
        self.assertEqual(receipt['reviewed_by'], 'human')
        summary = run_stage._summary(job, 'visual_direction')
        self.assertEqual(summary['review_required'], 'user')
        self.assertEqual(summary['visual_list'], '07-visual-direction/visual-routing.md')

    def test_production_does_not_start_without_visual_list_approval(self):
        job = SimpleNamespace(stages={'visual_canary': {'status': 'pending'}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_canary'), \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval', side_effect=ValueError('missing user approval')), \
             mock.patch('edit.hd.tools.visual_canary.prepare_visual_canary') as prepare:
            with self.assertRaisesRegex(ValueError, 'missing user approval'):
                run_stage.execute_stage(self.root, PROJECT)
        prepare.assert_not_called()

    def test_delivery_uses_host_qa_without_final_user_confirmation(self):
        records = [{'path': '12-delivery/final.mp4', 'sha256': 'b'*64, 'bytes': 12}]
        job = SimpleNamespace(job_id='this-job', job_dir=self.root, revision=19,
                              stages={'delivery': {'status': 'ready_for_review', 'artifacts': records}})
        review = {'job_id': job.job_id, 'job_dir': str(self.root), 'stage': 'delivery',
                  'revision': 19, 'artifacts': records, 'passed': True, 'note': '核对成片画面、原声及字幕'}
        with mock.patch('edit.hd.tools.delivery_approval.approve_plan_delivery') as finish, \
             mock.patch('edit.hd.tools.delivery_approval.approve_delivery') as old_human_approval, \
             mock.patch('edit.hd.tools.state.load_job', return_value=job):
            run_stage._review(job, 'delivery', review)
        finish.assert_called_once_with(job, expected_revision=19, delivery_sha256='b'*64, qa_note=review['note'])
        old_human_approval.assert_not_called()
        self.assertEqual(run_stage._summary(job, 'delivery')['review_required'], 'host')

if __name__ == "__main__": unittest.main()

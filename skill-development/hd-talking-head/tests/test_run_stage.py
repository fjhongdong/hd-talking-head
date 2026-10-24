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
             mock.patch("edit.hd.tools.visual_confirmation.prepare_visual_confirmation", return_value=self.root / 'proposal.json') as visual, \
             mock.patch.object(run_stage, "prepare_visual_dependencies"), \
             mock.patch.object(run_stage, "_json", return_value={'segments': []}), \
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

    def test_material_factory_accepts_mixed_images_and_videos(self):
        components = [{'component_id': 'image', 'kind': 'official_material', 'media_type': 'image'},
                      {'component_id': 'video', 'kind': 'official_material', 'media_type': 'video'}]
        plan = {'segments': [{'segment_id': 'seg-001', 'shot_recipe': {'components': components}}]}
        with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan):
            adapters = run_stage.native_component_adapters(PROJECT, SimpleNamespace(job_dir=self.root))
        self.assertEqual(adapters['official_material'][('seg-001', 'image')].artifact_media_type, 'image')
        self.assertEqual(adapters['official_material'][('seg-001', 'video')].artifact_media_type, 'video')
        self.assertEqual(adapters['official_material'][('seg-001', 'image')].approved_executor, 'official-media')

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

    def test_visual_repair_canary_only_requests_affected_segments(self):
        job = SimpleNamespace(job_dir=self.root, root=self.root, stages={
            'visual_direction': {'status': 'approved', 'artifact_scope': ['seg-009']},
            'visual_canary': {'status': 'pending', 'artifact_scope': []}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_canary'), \
             mock.patch('edit.hd.tools.state.require_runnable'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval'), \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch.object(run_stage, '_summary', return_value={}), \
             mock.patch('edit.hd.tools.visual_canary.prepare_visual_canary') as prepare:
            run_stage.execute_stage(self.root, PROJECT, component_adapters={})
        prepare.assert_called_once_with(job, component_adapters={}, segment_ids=['seg-009'])

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

class SelectedPreparationTests(unittest.TestCase):
    def test_supported_catalog_has_default_factory_and_exact_preflight_entry(self):
        from edit.hd.tools.motion_capabilities import load_catalog
        from project_python import _load_manifest
        manifest = _load_manifest(SKILL / 'references/dependency-manifest.json')
        registered = {(item['selection']['equals'], probe['entrypoint'], probe['producer_version'])
                      for item in manifest['dependencies'] if item.get('selection', {}).get('component_kind') == 'code_generated'
                      for probe in item.get('binding_probes', [])}
        for row in load_catalog(PROJECT):
            if row['status'] != 'supported' or row['role'] == 'design':
                continue
            with self.subTest(candidate=row['candidate_id']):
                run_stage._check_default_binding(row)
                self.assertIn((row['dependency_id'], row['entrypoint'], row['producer_version']), registered)

    def test_base_preparation_excludes_optional_templates_and_checks(self):
        import project_python as pp
        manifest = pp._load_manifest(SKILL / 'references/dependency-manifest.json')
        entries, checks = pp.preparation_selection(manifest, set())
        self.assertEqual({x['id'] for x in entries}, {'talkcraft-runtime-health', 'punk-cover-project-skill', 'gbro-collage-broll-source'})
        self.assertEqual(checks, [])
        entries, checks = pp.preparation_selection(manifest, {'doudou-remotion-whiteboard'})
        self.assertIn('doudou-whiteboard-source', {x['id'] for x in entries})
        self.assertEqual([x['id'] for x in checks], ['doudou-remotion-adapter'])
        self.assertNotIn('wise-motion', {x['id'] for x in entries})
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            pp.preparation_selection(manifest, {'typo'})

    def test_draft_binding_prepares_before_table_and_failure_does_not_publish(self):
        draft = {'segments': [{'visual_strategy': {'components': [
            {'kind': 'code_generated', 'component_id': 'v'}]},
            'bindings': {'v': {'dependency_id': 'doudou-remotion-whiteboard', 'entrypoint': 'scripts/render_doudou.mjs',
                               'producer_version': '2.0.0', 'primary_renderer': 'Remotion'}}}]}
        draft['segments'][0].update(start=0, end=3)
        draft['segments'][0]['visual_strategy']['composition'] = {'presenter_mode': 'full_frame'}
        import project_python as pp
        calls = []
        job = SimpleNamespace(job_dir=PROJECT)
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch.object(run_stage, '_json', return_value=draft), \
             mock.patch.object(pp, 'prepare_environment', side_effect=lambda *args: calls.append(('prepare', args))), \
             mock.patch('edit.hd.tools.visual_confirmation.prepare_visual_confirmation', side_effect=lambda *a, **k: calls.append(('table', a)) or PROJECT / 'proposal.json'), \
             mock.patch.object(run_stage, '_summary', return_value={}):
            run_stage.run_visual_direction(PROJECT, PROJECT, Path('draft.json'), Path('treatment.json'))
        self.assertEqual([c[0] for c in calls], ['prepare', 'table'])
        self.assertEqual(calls[0][1][3], {'doudou-remotion-whiteboard'})
        self.assertEqual(calls[0][1][4][0]['entrypoint'], 'scripts/render_doudou.mjs')
        self.assertEqual(calls[0][1][4][0]['executor'], 'reference_adapter')
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch.object(run_stage, '_json', return_value=draft), \
             mock.patch.object(pp, 'prepare_environment', side_effect=RuntimeError('selected template unavailable')), \
             mock.patch('edit.hd.tools.visual_confirmation.prepare_visual_confirmation') as publish:
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                run_stage.run_visual_direction(PROJECT, PROJECT, Path('draft.json'), Path('treatment.json'))
        publish.assert_not_called()

    def test_new_native_constructor_signatures_and_launchers(self):
        for dependency, module_name, node in [('doudou-remotion-whiteboard', 'doudou_adapter', True),
                 ('lemo-opuscar', 'upstream_scene_adapter', False), ('onetake', 'upstream_scene_adapter', False)]:
            module = run_stage._module(module_name)
            factory = mock.create_autospec(module.create_adapter, return_value='bound')
            plan = {'segments': [{'shot_recipe': {'components': [{'kind': 'code_generated', 'dependency_id': dependency}]}}]}
            with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan), \
                 mock.patch.object(run_stage, '_module', return_value=SimpleNamespace(create_adapter=factory)):
                result = run_stage.native_component_adapters(PROJECT, object())
            args = factory.call_args.args
            self.assertEqual(args[1] if dependency not in {'onetake', 'lemo-opuscar'} else args[2],
                             run_stage.shutil.which('node') if node else sys.executable)
            self.assertEqual(result['code_generated'][dependency], 'bound')
        with self.assertRaisesRegex(ValueError, 'no default execution binding'):
            run_stage._check_default_binding({'dependency_id': 'motion-graphics-native'})


class MaterialExecutionSmoke(unittest.TestCase):
    def test_default_materials_execute_and_preserve_sources(self):
        import subprocess, hashlib
        from PIL import Image
        from edit.hd.tests import test_broll_component_executor as fixture
        from edit.hd.tools import broll_component_executor as executor
        with tempfile.TemporaryDirectory() as directory:
            job = fixture._Job(Path(directory).resolve())
            image = job.job_dir / 'image.jpg'; Image.new('RGB', (1080,1920), 'blue').save(image)
            video = job.job_dir / 'video.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=1080x1920:r=30:d=2',
                            '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)], check=True)
            for kind, media in [('local_material','image'),('local_material','video'),('official_material','image'),('official_material','video'),('external_stock','video')]:
                source = image if media == 'image' else video
                original = source.read_bytes()
                component = fixture._material_component(kind, relative=source.name, source_sha=hashlib.sha256(original).hexdigest(), component_id=kind+'-'+media)
                component['executor'] = {'local_material':'local-media','official_material':'official-media','external_stock':'external-stock'}[kind]
                component['media_type'] = media
                if kind == 'external_stock':
                    target = job.job_dir / component['job_path']; target.parent.mkdir(parents=True); target.write_bytes(original)
                    fixture._write_stock_license(job, component, original)
                plan = {'segments':[{'segment_id':'seg-001','shot_recipe':fixture._recipe([component])}]}
                with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan):
                    adapters = run_stage.native_component_adapters(PROJECT, job)
                artifact = executor.execute_component(job, fixture._request(component), adapters=adapters)
                self.assertEqual(artifact.status, 'success')
                self.assertEqual(artifact.media_type, media)
                self.assertEqual(source.read_bytes(), original)
                self.assertTrue((job.job_dir / artifact.job_path).is_file())


if __name__ == "__main__": unittest.main()

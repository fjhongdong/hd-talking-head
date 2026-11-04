"""Minimal contract tests for execute_stage (no media or provider calls)."""
from __future__ import annotations
import contextlib, copy, hashlib, io, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import PROJECT, SKILL  # noqa: F401
sys.path.insert(0, str(SKILL / "scripts"))
import run_stage

class CheckOnlyStageTests(unittest.TestCase):
    def test_visual_proposal_does_not_prepare_future_native_projects(self):
        from edit.hd.tools import visual_confirmation as confirmation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = SimpleNamespace(job_dir=root)
            draft = {'segments': []}
            source = root / 'proposal.json'
            with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
                 mock.patch.object(run_stage, '_json', return_value=draft), \
                 mock.patch.object(run_stage, '_summary', return_value={}), \
                 mock.patch.object(run_stage, 'prepare_visual_dependencies', side_effect=AssertionError('future project preparation')), \
                 mock.patch.object(confirmation, 'prepare_visual_confirmation', return_value=source):
                run_stage.run_visual_direction(root, PROJECT, Path('director.json'), Path('treatment.json'))

    def test_resume_returns_independent_native_work_while_generation_waits(self):
        from edit.hd.tools import visual_confirmation as confirmation, generation_queue
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = SimpleNamespace(job_dir=root, stages={'visual_direction': {'artifacts': []}})
            base = {'producer_type': 'dependency', 'dependency_id': 'barty-motion-graphics'}
            director = {'segments': [{'segment_id': 'seg-001', 'start': 0, 'end': 1, 'bindings': {
                'waiting': base, 'dependent': base, 'ready': {**base, 'brief_sha256': 'a' * 64}},
                'visual_strategy': {'composition': {'component_dependencies': [
                    {'component_id': 'dependent', 'depends_on': ['waiting']}]}, 'components': [
                    {'component_id': 'waiting', 'kind': 'code_generated'},
                    {'component_id': 'dependent', 'kind': 'code_generated'},
                    {'component_id': 'ready', 'kind': 'code_generated'}]}}]}
            treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'ready', 'brief_path': 'ready.json'}]}
            (root / 'ready.json').write_text(json.dumps({'result_record_path': 'result.json'}))
            (root / 'director.json').write_text(json.dumps(director))
            (root / 'treatment.json').write_text(json.dumps(treatment))
            step = {'id': 'image-A', 'segment_id': 'seg-001', 'component_id': 'waiting'}
            authorized = {'source': {'inputs': {'director': confirmation._record(root, root / 'director.json'),
                'treatment': confirmation._record(root, root / 'treatment.json')}, 'generation_steps': [step]},
                'artifact': {'path': 'approval.json'}, 'payload': {'source': {'path': 'proposal.json'}}}
            def native(j, d, t):
                self.assertEqual(set(d['segments'][0]['bindings']), {'ready'})
                return [{'action': 'run_native_skill', 'component_id': 'ready',
                         'next': 'Execute the original native workflow.'}]
            with mock.patch.object(confirmation, 'validate_visual_authorization', return_value=authorized), \
                 mock.patch.object(confirmation, 'validate_realization_draft'), \
                 mock.patch.object(confirmation, '_validate_authorized_native_inputs'), \
                 mock.patch.object(confirmation, 'generation_actions', return_value=[{'action': 'query', 'step_id': 'image-A'}]), \
                 mock.patch.object(confirmation, 'generation_item', return_value=('image-A', {'status': 'submitted'})), \
                 mock.patch.object(generation_queue, 'status', return_value={'items': {}}), \
                 mock.patch.object(run_stage, '_validate_prepared_native_inputs'), \
                 mock.patch.object(run_stage, 'prepare_visual_dependencies'), \
                 mock.patch.object(run_stage, 'pending_native_actions', side_effect=native), \
                 mock.patch.object(run_stage, '_summary', side_effect=lambda j, s, **kw: kw), \
                 mock.patch('edit.hd.tools.visual_plan.prepare_visual_direction') as finalize:
                result = run_stage.resume_visual_direction(job, PROJECT)
                self.assertCountEqual([a['action'] for a in result['actions']], ['query', 'run_native_skill'])
                native_action = next(a for a in result['actions'] if a['action'] == 'run_native_skill')
                self.assertEqual(native_action['proposal'], authorized['payload']['source'])
                self.assertTrue(native_action['next'].startswith('Execute the original native workflow.'))
                self.assertIn('same channel and template', native_action['next'])
                self.assertIn('proposal.inputs.treatment', native_action['next'])
                self.assertNotIn('same_template_context', native_action)
                finalize.assert_not_called()
                with mock.patch.object(confirmation, 'generation_item', return_value=('image-A', {'status': 'completed'})):
                    result = run_stage.resume_visual_direction(job, PROJECT)
                preparations = [a for a in result['actions'] if a['action'] == 'prepare_template_inputs']
                self.assertEqual([(a['segment_id'], a['component_id']) for a in preparations], [('seg-001', 'waiting')])
                self.assertEqual(preparations[0]['proposal'], native_action['proposal'])
                self.assertIn('same channel and template', preparations[0]['next'])
                self.assertIn('native template\'s style and creative freedom', preparations[0]['next'])
                finalize.assert_not_called()

    def test_scripts_only_api_reaches_job_error_from_an_unrelated_directory(self):
        import subprocess
        script = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import run_stage
try:
    run_stage.execute_stage(Path.cwd() / 'missing-job', Path(sys.argv[2]))
except ModuleNotFoundError:
    raise
except Exception as error:
    assert type(error).__name__ == 'WorkflowError', repr(error)
    print(type(error).__name__)
else:
    raise AssertionError('missing Job unexpectedly accepted')
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-c', script, str(SKILL / 'scripts'), str(PROJECT)],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'WorkflowError')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_operation_wrapper_reports_elapsed_and_clears_scope_on_error(self):
        from edit.hd.tools import startup
        calls = []
        @run_stage._operation
        def command(*, fail=False):
            calls.append(startup.current_operation())
            if fail:
                raise ValueError('fixture failure')
            return {'status': 'fixture'}
        result = command()
        self.assertEqual(result['status'], 'fixture')
        self.assertGreaterEqual(result['operation_timing']['elapsed_seconds'], 0)
        self.assertEqual(result['operation_timing']['full_release_checks'], 0)
        with self.assertRaisesRegex(ValueError, 'fixture failure') as caught:
            command(fail=True)
        self.assertTrue(any(note.startswith('operation_timing=') for note in caught.exception.__notes__))
        self.assertIsNot(calls[0], calls[1])
        self.assertIsNone(startup.current_operation())

    def test_resume_records_native_gbro_inputs_before_generation_actions(self):
        from edit.hd.tools import visual_confirmation as confirmation
        job=SimpleNamespace(job_dir=PROJECT,stages={'visual_direction':{'artifacts':[]}})
        descriptor={'path':'native-inputs/gbro.json','sha256':'a'*64,'bytes':1}
        calls=[]
        with mock.patch.object(confirmation,'validate_visual_authorization',return_value={'source': {
                'inputs': {'director': {'path': 'director.json'}, 'treatment': {'path': 'treatment.json'}}, 'generation_steps': []}}), \
             mock.patch.object(confirmation,'record_gbro_frame_preparation',side_effect=lambda *a:calls.append(('prepare',a))), \
             mock.patch.object(confirmation,'generation_actions',side_effect=lambda *a,**k:calls.append(('generate',a)) or [{'action':'prepare_template_inputs'}]), \
             mock.patch.object(confirmation,'validate_realization_draft'), \
             mock.patch.object(run_stage,'_json',return_value={'segments': []}), \
             mock.patch.object(run_stage,'_validate_prepared_native_inputs'), \
             mock.patch.object(run_stage,'prepare_visual_dependencies'), \
             mock.patch.object(run_stage,'_summary',return_value={'actions':[]}):
            run_stage.resume_visual_direction(job,PROJECT,{'gbro_frame_preparations':[descriptor]})
        self.assertEqual([kind for kind,_ in calls],['prepare','generate'])
        self.assertEqual(calls[0][1],(job,descriptor))

    def test_native_preparation_uses_completed_results_and_only_prepares_unmade_items(self):
        from test_motion_native_skill_adapter import brief
        from edit.hd.tools import visual_confirmation as confirmation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();b=brief('video-shotcraft','spotlight-hero-card')
            request=root/'native-inputs/brief.json';request.parent.mkdir();request.write_text(json.dumps(b))
            result=root/b['result_record_path'];result.parent.mkdir();result.write_text('{}')
            job=SimpleNamespace(job_dir=root,job_id=b['job_id'],stages={'visual_direction':{'artifacts':[],'lineage':[]}})
            binding={'dependency_id':b['dependency_id'],'entrypoint':'scripts/motion_native_skill_adapter.py',
                'producer_version':'2.0.0','primary_renderer':'Remotion','brief_sha256':hashlib.sha256(request.read_bytes()).hexdigest(),
                'renderer_version':'remotion-4.0.484'}
            director={'segments':[{'segment_id':'seg-001','bindings':{'native':binding},
                'visual_strategy':{'components':[{'component_id':'native','kind':'code_generated'}]}}]}
            treatment={'scenes':[{'segment_id':'seg-001','component_id':'native','brief_path':'native-inputs/brief.json'}]}
            adapter=SimpleNamespace(validate_brief=mock.Mock(return_value=b),inspect_result=mock.Mock(return_value={}),
                                    load_result=mock.Mock(return_value={}))
            router=SimpleNamespace(_executor=lambda *args:'reference_adapter')
            def module(name):return router if name=='broll_capability_router' else adapter
            with mock.patch.object(run_stage,'_module',side_effect=module), \
                 mock.patch('project_python.project_environment',return_value=({},root/'packages')), \
                 mock.patch('project_python.prepare_environment') as prepare:
                run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                adapter.inspect_result.assert_called_once();prepare.assert_not_called()
                adapter.inspect_result.side_effect=ValueError('completed media changed')
                with self.assertRaisesRegex(ValueError,'media changed'):
                    run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                prepare.assert_not_called();adapter.inspect_result.side_effect=None
                # A registered review is checked even when the current files
                # could otherwise present a self-consistent completed result.
                previous=root/'07-visual-confirmation/prior/execution-mapping.json';previous.parent.mkdir(parents=True)
                proposal={'path':'prior-proposal.json','sha256':'a'*64,'bytes':1}
                expected={'path':b['result_record_path'],'sha256':'b'*64,'bytes':2}
                previous.write_text(json.dumps({'source_approval':{},'proposal':proposal,'native_inputs':[
                    {'segment_id':'seg-001','component_id':'native','artifact':confirmation._record(root,request),
                     'result_record':expected}]}))
                stat, parent = previous.stat(), previous.parent.stat()
                lineage = {**confirmation._record(root,previous), 'device':stat.st_dev, 'inode':stat.st_ino,
                           'parent_device':parent.st_dev, 'parent_inode':parent.st_ino}
                job.stages['visual_direction']['lineage']=[lineage]
                with mock.patch.object(confirmation,'_validate_source',return_value=({'source':proposal},{})):
                    run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                adapter.load_result.assert_called_once_with(root,request.read_bytes(),expected_record=expected,
                    expected_renderer_version='remotion-4.0.484')
                prepare.assert_not_called();adapter.load_result.reset_mock()
                adapter.load_result.side_effect=ValueError('result differs from reviewed version')
                with mock.patch.object(confirmation,'_validate_source',return_value=({'source':proposal},{})):
                    with self.assertRaisesRegex(ValueError,'reviewed version'):
                        run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                adapter.load_result.assert_called_once_with(root,request.read_bytes(),expected_record=expected,
                    expected_renderer_version='remotion-4.0.484')
                prepare.assert_not_called()
                adapter.load_result.reset_mock()
                for field, value in (('sha256','0'*64),('bytes',lineage['bytes']+1)):
                    job.stages['visual_direction']['lineage']=[{**lineage,field:value}]
                    with self.subTest(changed_identity=field), self.assertRaisesRegex(ValueError,'visual evidence changed'):
                        run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                    adapter.load_result.assert_not_called();prepare.assert_not_called()
                job.stages['visual_direction']['lineage']=[];result.unlink()
                run_stage.prepare_visual_dependencies(PROJECT,director,job=job,treatment=treatment)
                self.assertEqual(prepare.call_args.args[3],{'video-shotcraft'})

    def test_pending_barty_prepares_output_after_binding_without_touching_existing_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = SimpleNamespace(job_dir=root, job_id='fixture')
            brief = {'project_directory':'native-projects/one', 'result_record_path':'native-inputs/result.json'}
            request = root/'native-inputs/brief.json'; request.parent.mkdir()
            request.write_text(json.dumps(brief)); payload=request.read_bytes()
            binding = {'dependency_id':'barty-motion-graphics', 'brief_sha256':hashlib.sha256(payload).hexdigest()}
            director = {'segments':[{'segment_id':'seg-001', 'bindings':{'native':binding},
                'visual_strategy':{'mode':'single', 'composition':{}, 'components':[{'component_id':'native'}]}}]}
            treatment = {'scenes':[{'segment_id':'seg-001','component_id':'native','brief_path':'native-inputs/brief.json'}]}
            module = SimpleNamespace(validate_brief=mock.Mock(return_value=brief), task_source=mock.Mock(return_value={}),
                native_task=mock.Mock(side_effect=lambda *a,**k:{'requirements':{},'next':'Actual native task.'}),
                inspect_result=mock.Mock())
            with mock.patch.object(run_stage,'_module',return_value=module), \
                 mock.patch('edit.hd.tools.subtitles_v2.subtitle_layout',return_value=({},'left')):
                actions=run_stage.pending_native_actions(job,director,treatment)
                output=root/'native-projects/one/out'
                self.assertTrue(output.is_dir())
                self.assertEqual(actions[0]['output_directory'],str(output))
                media=output/'retained.mp4';media.write_bytes(b'existing native media')
                run_stage.pending_native_actions(job,director,treatment)
                self.assertEqual(media.read_bytes(),b'existing native media')
                binding['brief_sha256']='0'*64
                with self.assertRaisesRegex(ValueError,'brief changed'):
                    run_stage.pending_native_actions(job,director,treatment)
                binding['brief_sha256']=hashlib.sha256(payload).hexdigest()
                # A project symlink may not create the output outside this Job.
                second=root/'native-projects/two';second.symlink_to(root/'outside',target_is_directory=True)
                brief['project_directory']='native-projects/two'
                with self.assertRaisesRegex(ValueError,'remain in this Job'):
                    run_stage.pending_native_actions(job,director,treatment)
                self.assertFalse((root/'outside').exists())

    @mock.patch('edit.hd.tools.startup.require_startup')
    def test_scribe_check_obeys_dependencies_without_running_or_writing(self, _startup):
        from edit.hd.tools import state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video = root / 'source.mp4'; video.write_bytes(b'video')
            script = root / 'script.txt'; script.write_text('原稿')
            job = state.create_job(root, video, script, profile='full-v2')

            def approve(stage):
                artifact = job.job_dir / (stage + '.txt'); artifact.write_text(stage)
                state.mark_ready(job, stage, [artifact]); state.complete(job, stage)

            context = root / 'check-context.json'
            context.write_text(json.dumps({'job_dir': str(job.job_dir), 'project_root': str(PROJECT)}))

            def check():
                before = (job.job_dir / 'workflow.json').read_bytes()
                output = io.StringIO()
                with mock.patch.object(sys, 'argv', ['run_stage.py', '--job-context', str(context),
                        '--stage', 'speech_cleanup', '--check-only']), \
                     mock.patch.object(run_stage, 'execute_stage') as execute, \
                     mock.patch.object(run_stage, '_startup') as refresh, \
                     mock.patch('subprocess.run') as process, \
                     mock.patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                     contextlib.redirect_stdout(output):
                    code = run_stage.main()
                execute.assert_not_called(); refresh.assert_not_called(); process.assert_not_called()
                self.assertEqual((job.job_dir / 'workflow.json').read_bytes(), before)
                return code, json.loads(output.getvalue())

            code, result = check()
            self.assertEqual(code, 1)
            self.assertIn('prerequisites', result['error'])
            approve('inspect')
            code, result = check()
            self.assertEqual(code, 0)
            self.assertTrue(result['runnable'])
            self.assertEqual(result['stage'], 'speech_cleanup')
            self.assertEqual(state.current_stage(state.load_job(job.job_dir)), 'content_analysis')
            with mock.patch.object(run_stage, '_startup'), \
                 mock.patch.object(run_stage, 'run_speech_cleanup', return_value={'stage': 'speech_cleanup', 'status': 'pending'}) as speech:
                result = run_stage.execute_stage(job.job_dir, PROJECT, 'speech_cleanup')
            speech.assert_called_once()
            self.assertEqual(result['stage'], 'speech_cleanup')
            with mock.patch.object(run_stage, '_startup'):
                result = run_stage.execute_stage(job.job_dir, PROJECT)
            self.assertEqual(result['stage'], 'content_analysis')

class ExecuteStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake(self, status="pending", current="inspect"):
        names = ["inspect", "content_analysis", "cover_direction", "cover", "speech_cleanup", "edit_structure", "visual_direction"]
        stages = {name: {"status": "completed"} for name in names}; stages[current] = {"status": status}
        job = SimpleNamespace(job_dir=self.root, stages=stages, inputs={}, root=self.root)
        return job

    def native_loader_fixture(self):
        from edit.hd.tools import visual_confirmation as confirmation
        approval = self.root / 'approval.json'; approval.write_text('{"approved":true}')
        evidence = {'artifact': confirmation._record(self.root, approval), 'mapping': {'native_inputs': []}}
        evidence['mapping']['source_approval'] = evidence['artifact']
        components = []
        for index in range(2):
            path = self.root / f'brief-{index}.json'; path.write_bytes(f'approved-{index}'.encode())
            record = confirmation._record(self.root, path)
            component = {'component_id': f'scene-{index}', 'kind': 'code_generated',
                         'dependency_id': 'lemo-opuscar', 'brief_sha256': record['sha256']}
            components.append(component)
            evidence['mapping']['native_inputs'].append({'segment_id': 'seg-1',
                'component_id': component['component_id'], 'artifact': record})
        mapping = self.root / 'execution-mapping.json'; mapping.write_text(json.dumps(evidence['mapping']))
        # Production mappings live below a confirmation revision directory.
        nested = self.root / 'confirmed' / mapping.name; nested.parent.mkdir(); mapping.rename(nested)
        stages = {'visual_direction': {'status': 'completed', 'artifacts': [confirmation._record(self.root, nested)]},
                  'visual_assets': {'status': 'pending'}}
        workflow = self.root / 'workflow.json'; workflow.write_text(json.dumps({'revision': 7, 'stages': stages}))
        frozen = confirmation._record(self.root, workflow)
        job = SimpleNamespace(job_dir=self.root, job_id='fixture', revision=7, stages=stages,
                              expected_sha256=frozen['sha256'], expected_bytes=frozen['bytes'])
        return job, evidence, {'segment_id': 'seg-1', 'components': components}

    def test_native_factory_checks_realization_once_for_multiple_brief_loads(self):
        from edit.hd.tools import visual_confirmation as confirmation
        job, evidence, recipe = self.native_loader_fixture()
        plan = {'segments': [{'shot_recipe': recipe}]}
        module = SimpleNamespace(create_adapter=lambda *args: args[-1])
        with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan), \
             mock.patch.object(confirmation, 'validate_visual_authorization', return_value=evidence) as validate, \
             mock.patch.object(run_stage, '_module', return_value=module):
            loader = run_stage.native_component_adapters(PROJECT, job)['code_generated']['lemo-opuscar']
            for index, component in enumerate(recipe['components']):
                self.assertEqual(loader(job, recipe, component), f'approved-{index}'.encode())
            validate.assert_called_once_with(job, require_realized=True)

    def test_native_brief_loader_rejects_changed_scope_approval_mapping_and_bytes(self):
        from edit.hd.tools import visual_confirmation as confirmation
        job, evidence, recipe = self.native_loader_fixture()
        loader = run_stage._approved_native_brief(job, evidence)
        component = recipe['components'][0]
        self.assertEqual(loader(job, recipe, component), b'approved-0')
        for altered in ({**component, 'brief_sha256': '0' * 64}, {**component, 'component_id': 'other'}):
            with self.subTest(component=altered), self.assertRaises(ValueError):
                loader(job, recipe, altered)
        for relative in ('brief-0.json', 'confirmed/execution-mapping.json', 'approval.json', 'workflow.json'):
            path = self.root / relative; original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.subTest(changed_file=relative), self.assertRaises(ValueError):
                loader(job, recipe, component)
            path.write_bytes(original)
        for mutate in (lambda j: setattr(j, 'revision', 8),
                       lambda j: j.stages['visual_assets'].update(status='completed'),
                       lambda j: j.stages['visual_direction']['artifacts'][0].update(sha256='0' * 64)):
            changed = copy.deepcopy(job); mutate(changed)
            with self.assertRaises(ValueError): loader(changed, recipe, component)
        wrong = copy.deepcopy(evidence); wrong['artifact']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'verified confirmation'):
            run_stage._approved_native_brief(job, wrong)
        duplicate = copy.deepcopy(evidence)
        duplicate['mapping']['native_inputs'].append(copy.deepcopy(duplicate['mapping']['native_inputs'][0]))
        mapping = self.root / 'confirmed/execution-mapping.json'; mapping.write_text(json.dumps(duplicate['mapping']))
        job.stages['visual_direction']['artifacts'] = [confirmation._record(self.root, mapping)]
        workflow = self.root / 'workflow.json'; workflow.write_text(json.dumps({'revision': 7, 'stages': job.stages}))
        frozen = confirmation._record(self.root, workflow)
        job.expected_sha256, job.expected_bytes = frozen['sha256'], frozen['bytes']
        duplicate_loader = run_stage._approved_native_brief(job, duplicate)
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            duplicate_loader(job, recipe, component)

    def invoke(self, job, stage, **kwargs):
        with mock.patch("edit.hd.tools.state.load_job", return_value=job), \
             mock.patch("edit.hd.tools.state.current_stage", return_value=stage), \
             mock.patch.object(run_stage, "_startup"), \
             mock.patch("edit.hd.tools.state.require_runnable"), \
             mock.patch("edit.hd.tools.state.complete", side_effect=lambda j, s: j.stages[s].update(status="completed")), \
             mock.patch.object(run_stage, "_summary", side_effect=lambda j, s, **kw: {"stage": s, **kw}):
            return run_stage.execute_stage(self.root, PROJECT, stage, **kwargs)

    def test_approved_reuses_without_runner(self):
        job = self.fake("completed")
        with mock.patch("edit.hd.tools.inspect_inputs.inspect_job") as runner:
            out = self.invoke(job, "inspect")
        runner.assert_not_called(); self.assertTrue(out["reused"])

    def test_ready_does_not_render_again(self):
        job = self.fake("ready")
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
        with mock.patch.object(run_stage, "run_speech_cleanup", return_value={"speech_cleanup": "ready"}) as speech, \
             mock.patch("edit.hd.tools.speech_edit_v2.render_edit") as render:
            result = self.invoke(job, "speech_cleanup", video_use_result=Path("r.json"), invocation_path=Path("i.json"), cleanup_plan=Path("p.json"))
        speech.assert_called_once_with(self.root, PROJECT, Path("r.json"), Path("i.json"), Path("p.json")); render.assert_not_called(); self.assertEqual(result["speech_cleanup"], "ready")

    def test_visual_revision_routes_realization_and_keeps_authorization_gate(self):
        from edit.hd.tools import visual_confirmation as confirmation
        job = self.fake("needs_revision", current="visual_direction")
        payload = {"realization": {"director_brief": "revised/director.json", "treatment": "revised/treatment.json"}}
        with mock.patch.object(run_stage, "resume_visual_direction", return_value={"continued": True}) as resume, \
             mock.patch.object(run_stage, "run_visual_direction") as prepare:
            result = self.invoke(job, "visual_direction", payload=payload)
            self.assertEqual(result.pop('operation_timing')['full_release_checks'], 0)
            self.assertEqual(result, {"continued": True})
        resume.assert_called_once_with(job, PROJECT, payload); prepare.assert_not_called()
        with mock.patch.object(confirmation, "validate_visual_authorization", side_effect=ValueError("not confirmed")), \
             mock.patch.object(confirmation, "generation_actions") as generate:
            with self.assertRaisesRegex(ValueError, "not confirmed"):
                self.invoke(job, "visual_direction", payload=payload)
        generate.assert_not_called()

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

    def test_hw_word_anchor_is_checked_before_visual_confirmation(self):
        from edit.hd.tools import contract_artifacts

        job = self.fake(current="visual_direction")
        job.stages["speech_cleanup"] = {"status": "completed", "artifacts": []}
        job.stages["edit_structure"] = {"status": "completed", "artifacts": []}
        for stage_name, relative, payload in (
                ("speech_cleanup", "05-speech-cleanup/word-transcript.json",
                 {"words": [{"text": text, "start": start, "end": start + .1}
                            for text, start in (("A", .7), ("B", 1.533333), ("C", 2.75))]}),
                ("edit_structure", "06-edit-structure/timeline-map.json",
                 {"segments": [{"source_start": 0, "source_end": 10,
                                 "timeline_start": 0}]})):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            contract_artifacts.write_json_artifact(path, payload)
            job.stages[stage_name]["artifacts"] = [{"path": relative, "bytes": path.stat().st_size,
                                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
        brief_path = self.root / "native-inputs" / "hw-brief.json"
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief = {"schema_version": 1,
                 "source_binding": {"aroll_sha256": "0" * 64, "segment_id": "seg-106", "start": 0, "end": 83 / 24},
                 "canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 83},
                 "labels": ["A", "B", "C"],
                 "template_request": {"semantic_family": "three_step_flow", "information_units": 3,
                                      "numeric_values": [], "numeric_scale": "not_applicable"},
                 "word_anchors": [{"index": 0, "text": "A"}, {"index": 1, "text": "B"},
                                  {"index": 2, "text": "C"}], "label_frames": [6, 26, 46]}
        payload = json.dumps(brief).encode(); brief_path.write_bytes(payload)
        segment = {"segment_id": "seg-106", "start": 0, "end": 10,
                   "visual_strategy": {"components": [{"component_id": "visual"}]},
                   "bindings": {"visual": {"dependency_id": "hyperframes",
                       "entrypoint": "scripts/render_hyperframes_hw_pipeline.cjs",
                       "brief_sha256": hashlib.sha256(payload).hexdigest()}}}
        director = {"segments": [segment]}
        treatment = {"scenes": [{"segment_id": "seg-106", "component_id": "visual",
                                  "brief_path": "native-inputs/hw-brief.json"}]}
        director_path = self.root / "director.json"
        treatment_path = self.root / "treatment.json"
        director_path.write_text(json.dumps(director))
        treatment_path.write_text(json.dumps(treatment))
        with self.assertRaisesRegex(ValueError, "seg-106/visual.*label reveal"):
            run_stage._validate_selected_hw_word_anchors(job, director, treatment)
        brief["label_frames"][-1] = 47
        payload = json.dumps(brief).encode(); brief_path.write_bytes(payload)
        segment["bindings"]["visual"]["brief_sha256"] = hashlib.sha256(payload).hexdigest()
        run_stage._validate_selected_hw_word_anchors(job, director, treatment)

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

    def test_review_is_bound_to_job_and_candidate_before_authorization(self):
        from edit.hd.tools import state, visual_confirmation
        job_a = self.ready_job('a', b'video-a')
        job_b = self.ready_job('b', b'video-b')
        for job in (job_a, job_b):
            job.stages['visual_direction'] = copy.deepcopy(job.stages['inspect'])
        review = {**self.review(job_a), 'stage': 'visual_direction',
                  'user_confirmation': '确认本期完整清单和费用'}
        with mock.patch.object(visual_confirmation, 'save_user_confirmation') as authorize:
            for target, altered in ((job_b, review),
                                    (job_a, review | {'artifacts': []}),
                                    (job_a, review | {'job_dir': str(job_b.job_dir)})):
                with self.subTest(target=target.job_id), self.assertRaises(ValueError):
                    run_stage._review(target, 'visual_direction', altered)
            authorize.assert_not_called()
            result = run_stage._review(job_a, 'visual_direction', review)
            authorize.assert_called_once_with(job_a, review)
        self.assertTrue(result['user_confirmed'])
        self.assertEqual(state.load_job(job_b.job_dir).stages['inspect']['status'], 'ready')

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
                              stages={'visual_direction': {'status': 'completed', 'artifact_scope': []},
                                      'visual_assets': {'status': 'pending', 'artifact_scope': []}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_assets'), \
             mock.patch('edit.hd.tools.state.require_runnable'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval') as authorize, \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch.object(run_stage, '_summary', return_value={}), \
             mock.patch('edit.hd.tools.visual_assets_v2.prepare_visual_assets_v2') as prepare:
            run_stage.execute_stage(self.root, PROJECT, adapter_factory=factory)
        authorize.assert_called_once_with(job)
        prepare.assert_called_once_with(job, component_adapters={'official_material': 'image-adapter'})

    def test_visual_repair_keeps_affected_scope_for_existing_assets_runner(self):
        job = SimpleNamespace(job_dir=self.root, root=self.root, stages={
            'visual_direction': {'status': 'completed', 'artifact_scope': ['seg-009']},
            'visual_assets': {'status': 'needs_revision', 'artifact_scope': ['seg-009']}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_assets'), \
             mock.patch('edit.hd.tools.state.require_runnable'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval'), \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch.object(run_stage, '_summary', return_value={}), \
             mock.patch('edit.hd.tools.visual_assets_v2.prepare_visual_assets_v2') as prepare:
            run_stage.execute_stage(self.root, PROJECT, component_adapters={})
        prepare.assert_called_once_with(job, component_adapters={})
        self.assertEqual(job.stages['visual_assets']['artifact_scope'], ['seg-009'])
        self.assertNotIn('visual_canary', job.stages)

    def test_completion_status_controls_exit_code(self):
        context = self.root / 'job-context.json'
        context.write_text(json.dumps({'project_root': str(PROJECT), 'job_dir': str(self.root)}))
        for status, expected in (('inconsistent', 1), ('delivered', 0),
                                 ('accepted', 0), ('incomplete', 0)):
            output = io.StringIO()
            with self.subTest(status=status), \
                 mock.patch.object(sys, 'argv', ['run_stage', '--job-context', str(context)]), \
                 mock.patch.object(run_stage, 'execute_stage', return_value={'status': status}), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(run_stage.main(), expected)
            self.assertEqual(json.loads(output.getvalue())['status'], status)

    def test_visual_list_requires_user_confirmation_and_records_generation_scope(self):
        from edit.hd.tools import visual_confirmation as confirmation
        records = []
        for name, data in (('proposal.json', {'source_id': 'current-proposal'}),
                           ('visual-routing.md', '本期完整清单')):
            path = self.root / '07-visual-confirmation/current' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data) if isinstance(data, dict) else data)
            records.append(confirmation._record(self.root, path))
        job = SimpleNamespace(job_id='this-job', job_dir=self.root, revision=7,
                              stages={'visual_direction': {'status': 'ready', 'artifacts': records}})
        review = {'job_id': job.job_id, 'job_dir': str(job.job_dir), 'revision': 7,
                  'stage': 'visual_direction', 'artifacts': copy.deepcopy(records)}
        with self.assertRaises(ValueError):
            run_stage._review(job, 'visual_direction', review)
        review['user_confirmation'] = '确认整张表和费用，按表制作交付'
        with mock.patch('edit.hd.tools.state.mark_visual_ready') as mark:
            result = run_stage._review(job, 'visual_direction', review)
        mark.assert_called_once()
        receipt = json.loads((self.root / 'manifests/visual-authorization-r7.json').read_text())
        self.assertEqual(receipt['authorization_scope'], 'visual_plan_and_generation')
        self.assertEqual(receipt['authorized_by'], 'user')
        self.assertEqual(receipt['source'], records[0])
        self.assertEqual(receipt['user_confirmation'], review['user_confirmation'])
        self.assertTrue(result['user_confirmed'])
        self.assertNotIn('review_required', result)
        self.assertEqual(result['visual_list'], records[1]['path'])

    def test_production_does_not_start_without_visual_list_approval(self):
        job = SimpleNamespace(stages={'visual_assets': {'status': 'pending'}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.current_stage', return_value='visual_assets'), \
             mock.patch.object(run_stage, '_startup'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval', side_effect=ValueError('missing user approval')), \
             mock.patch('edit.hd.tools.visual_assets_v2.prepare_visual_assets_v2') as prepare:
            with self.assertRaisesRegex(ValueError, 'missing user approval'):
                run_stage.execute_stage(self.root, PROJECT)
        prepare.assert_not_called()

    def test_preview_does_not_consume_a_stage_quality_approval(self):
        job = SimpleNamespace(job_id='preview-job', job_dir=self.root, revision=19,
                              stages={'preview': {'status': 'ready', 'artifacts': []}})
        review = {'job_id': job.job_id, 'job_dir': str(self.root), 'stage': 'preview',
                  'revision': 19, 'artifacts': [], 'user_confirmation': '已看本期预览'}
        with mock.patch('edit.hd.tools.state.complete') as complete:
            with self.assertRaisesRegex(ValueError, 'Machine stages complete automatically'):
                run_stage._review(job, 'preview', review)
            complete.assert_not_called()
        self.assertFalse((self.root / 'manifests/local-qa-preview-r19.json').exists())

    def test_delivery_records_completion_without_claiming_user_acceptance(self):
        records = [{'path': '12-delivery/final.mp4', 'sha256': 'b' * 64, 'bytes': 12}]
        job = SimpleNamespace(job_id='this-job', job_dir=self.root, revision=19,
                              stages={'delivery': {'status': 'ready', 'artifacts': records}})
        with mock.patch('edit.hd.tools.state.load_job', return_value=job), \
             mock.patch('edit.hd.tools.state.complete', side_effect=lambda j, s: j.stages[s].update(status='completed')) as complete, \
             mock.patch('edit.hd.tools.delivery_approval.record_delivery') as delivered, \
             mock.patch('edit.hd.tools.delivery_approval.approve_delivery') as accept, \
             mock.patch('edit.hd.tools.delivery_approval.current_delivery_status', return_value={'delivery_status': 'delivered'}):
            result = run_stage._finish_stage(self.root, 'delivery')
        complete.assert_called_once_with(job, 'delivery')
        delivered.assert_called_once_with(job)
        accept.assert_not_called()
        self.assertEqual(result['delivery_status'], 'delivered')
        self.assertNotIn('review_required', result)
        with self.assertRaisesRegex(ValueError, 'User confirmation'):
            run_stage._review(job, 'delivery', {'job_id': job.job_id, 'job_dir': str(self.root),
                              'stage': 'delivery', 'artifacts': records})

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

    def test_ready_execution_binding_prepares_only_its_selected_dependency(self):
        draft = {'segments': [{'segment_id': 'seg-001', 'visual_strategy': {'components': [
            {'kind': 'code_generated', 'component_id': 'v'}]},
            'bindings': {'v': {'dependency_id': 'doudou-remotion-whiteboard', 'entrypoint': 'scripts/render_doudou.mjs',
                               'producer_version': '2.0.0', 'primary_renderer': 'Remotion'}}}]}
        draft['segments'][0].update(start=0, end=3)
        draft['segments'][0]['visual_strategy']['composition'] = {'presenter_mode': 'full_frame'}
        import project_python as pp
        calls = []
        job = SimpleNamespace(job_dir=PROJECT)
        with mock.patch.object(pp, 'prepare_environment', side_effect=lambda *args: calls.append(('prepare', args))):
            run_stage.prepare_visual_dependencies(PROJECT, draft, job=job, treatment={})
        self.assertEqual([c[0] for c in calls], ['prepare'])
        self.assertEqual(calls[0][1][3], {'doudou-remotion-whiteboard'})
        self.assertEqual(calls[0][1][4][0]['entrypoint'], 'scripts/render_doudou.mjs')
        self.assertEqual(calls[0][1][4][0]['executor'], 'reference_adapter')
        with mock.patch.object(pp, 'prepare_environment', side_effect=RuntimeError('selected template unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                run_stage.prepare_visual_dependencies(PROJECT, draft, job=job, treatment={})

    def test_new_native_constructor_signatures_and_launchers(self):
        for dependency, module_name, node in [('doudou-remotion-whiteboard', 'doudou_adapter', True),
                 ('lemo-opuscar', 'upstream_scene_adapter', False), ('onetake', 'upstream_scene_adapter', False)]:
            module = run_stage._module(module_name)
            factory = mock.create_autospec(module.create_adapter, return_value='bound')
            plan = {'segments': [{'shot_recipe': {'components': [{'kind': 'code_generated', 'dependency_id': dependency}]}}]}
            with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value=plan), \
                 mock.patch('edit.hd.tools.visual_confirmation.validate_visual_authorization', return_value={}), \
                 mock.patch.object(run_stage, '_approved_native_brief', return_value=mock.Mock()), \
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


class DirectProductionCompletionTests(unittest.TestCase):
    def test_completion_audit_accepts_generated_credits_and_only_the_workspace_material_index(self):
        import audit_job_completion as audit
        from edit.hd.tools import contract_artifacts, qa_delivery_v2
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            job_dir = workspace / 'job'; job_dir.mkdir()
            def write(path, content):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
                return path
            def record(base, path):
                return {'path':str(path.relative_to(base)),
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
            video = write(workspace / 'input.mp4', b'synthetic source')
            script = write(workspace / 'script.txt', b'synthetic script')
            preview = write(job_dir / '11-preview/review.mp4', b'synthetic composition')
            source_payload = {'components':[{'attribution':{'required':True,'provider':'synthetic fixture',
                'author':'fixture author','asset_page':'https://example.invalid/fixture',
                'license':'fixture license','license_version':'1'}}]}
            source_payload['source_manifest_sha256'] = contract_artifacts.sha256_json(source_payload)
            origin = write(job_dir / '11-preview/source-manifest.json', json.dumps(source_payload).encode())
            index = write(workspace / '00-user-provided/material-index.json', b'{"materials":[]}')
            final = write(job_dir / '12-delivery/final.mp4', preview.read_bytes())
            copied_origin = write(final.parent / 'source-manifest.json', origin.read_bytes())
            copied_index = write(final.parent / 'sources/user-material-index.json', index.read_bytes())
            credits = write(final.parent / 'credits.md', qa_delivery_v2._credits_markdown(source_payload).encode())
            manifest_path = final.parent / 'delivery-manifest.json'
            inventory = {
                'final.mp4':{'source':record(job_dir,preview),'output':record(final.parent,final)},
                'source-manifest.json':{'source':record(job_dir,origin),'output':record(final.parent,copied_origin)},
                'sources/user-material-index.json':{'source':{**record(workspace,index),'path':str(index)},
                    'output':record(final.parent,copied_index)},
                'credits.md':{'generated_from':{'path':'11-preview/source-manifest.json',
                    'sha256':source_payload['source_manifest_sha256']},'output':record(final.parent,credits)},
            }
            stages = {name:{'status':'completed','artifacts':[]} for name in audit.FULL_V2_STAGES}
            stages['preview']['artifacts'] = [record(job_dir,preview),record(job_dir,origin)]
            def persist(entries):
                manifest_path.write_text(json.dumps({'job_id':'synthetic-job','final_sha256':record(job_dir,final)['sha256'],
                    'canvas':{'width':1080,'height':1920,'fps':24},'artifacts':entries}))
                stages['delivery']['artifacts'] = [record(job_dir,p) for p in
                    (final,copied_origin,copied_index,credits,manifest_path)]
                (job_dir / 'workflow.json').write_text(json.dumps({'version':2,'job_id':'synthetic-job','revision':22,
                    'inputs':{'video':record(workspace,video),'script':record(workspace,script)},'stages':stages}))
            (workspace / 'job-context.json').write_text(json.dumps({'workspace':str(workspace),
                'job_dir':str(job_dir),'job_id':'synthetic-job'}))
            probe = {'width':1080,'height':1920,'fps':24,'duration_seconds':1,'rotation':0}
            with mock.patch.object(audit,'_probe_media',return_value=probe):
                persist(inventory)
                report = audit.audit_job_completion(workspace)
                self.assertEqual(report['status'], 'incomplete', report)
                self.assertEqual(report['failures'], [])
                self.assertIn('delivery_inventory_exact', report['verified_claims'])
                for issue in ('credits_origin', 'index_hash', 'other_absolute_source'):
                    invalid = copy.deepcopy(inventory)
                    if issue == 'credits_origin':
                        invalid['credits.md']['generated_from']['sha256'] = 'b' * 64
                    elif issue == 'index_hash':
                        invalid['sources/user-material-index.json']['source']['sha256'] = 'b' * 64
                    else:
                        other = write(workspace / 'other-index.json', index.read_bytes())
                        invalid['sources/user-material-index.json']['source']['path'] = str(other)
                    with self.subTest(issue=issue):
                        persist(invalid)
                        self.assertEqual(audit.audit_job_completion(workspace)['status'], 'inconsistent')

    def test_stage_ready_completes_without_qa_and_canary_is_absent(self):
        from edit.hd.tools import state
        with tempfile.TemporaryDirectory() as directory, mock.patch('edit.hd.tools.startup.require_startup'):
            root = Path(directory).resolve()
            video, script = root / 'source.mp4', root / 'script.txt'
            video.write_bytes(b'video'); script.write_text('script')
            job = state.create_job(root, video, script)
            self.assertNotIn('visual_canary', job.stages)
            self.assertEqual(state.STAGE_STATUSES, ('pending', 'ready', 'completed', 'needs_revision', 'blocked'))
            artifact = job.job_dir / 'inspect.json'; artifact.write_text('{}')
            state.mark_ready(job, 'inspect', [artifact])
            self.assertEqual(job.stages['inspect']['status'], 'ready')
            result = run_stage._finish_stage(job.job_dir, 'inspect')
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(state.current_stage(state.load_job(job.job_dir)), 'content_analysis')
            self.assertFalse((job.job_dir / 'manifests/local-qa-inspect-r1.json').exists())

    def test_completion_rejects_changed_artifact_and_legacy_profile(self):
        from edit.hd.tools import state
        with tempfile.TemporaryDirectory() as directory, mock.patch('edit.hd.tools.startup.require_startup'):
            root = Path(directory).resolve()
            video, script = root / 'source.mp4', root / 'script.txt'
            video.write_bytes(b'video'); script.write_text('script')
            with self.assertRaises(state.WorkflowError):
                state.create_job(root, video, script, profile='legacy-v1')
            job = state.create_job(root, video, script)
            artifact = job.job_dir / 'inspect.json'; artifact.write_text('{}')
            state.mark_ready(job, 'inspect', [artifact]); artifact.write_text('{"changed":true}')
            with self.assertRaises(state.WorkflowError):
                state.complete(job, 'inspect')
            self.assertEqual(job.stages['inspect']['status'], 'ready')

    def test_runner_advances_available_stages_until_actual_input_action(self):
        from edit.hd.tools import state
        statuses = {'inspect': {'status':'pending'}, 'content_analysis': {'status':'pending'}}
        job = SimpleNamespace(stages=statuses)
        def execute(job_dir, project, stage, **options):
            if stage == 'inspect':
                statuses[stage]['status'] = 'completed'
                return {'stage':stage, 'status':'completed'}
            return {'stage':stage, 'status':'pending', 'actions':[{'action':'provide_stage_input','fields':['analysis']}]}
        def current(value):
            return next((stage for stage, record in statuses.items() if record['status'] != 'completed'), None)
        with mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(state,'current_stage',side_effect=current), \
             mock.patch.object(run_stage,'_execute_one_stage',side_effect=execute) as one:
            result = run_stage.execute_stage(Path('/unused'), PROJECT)
        self.assertEqual(one.call_count, 2)
        self.assertEqual(result['actions'][0]['fields'], ['analysis'])
        self.assertNotIn('review_required', result)
        timings = result['operation_timing']['stages']
        self.assertEqual([(item['stage'], item['status']) for item in timings],
                         [('inspect', 'completed'), ('content_analysis', 'pending')])
        self.assertTrue(all(item['elapsed_seconds'] >= 0 for item in timings))

    def test_continuous_runner_routes_stage_inputs_and_keeps_one_operation(self):
        from edit.hd.tools import state, startup
        statuses = {name: {'status':'pending'} for name in ('visual_assets', 'subtitles', 'preview', 'delivery')}
        job = SimpleNamespace(stages=statuses)
        operations, inputs = [], []
        def execute(job_dir, project, stage, **options):
            operations.append(startup.current_operation())
            inputs.append((stage, options['payload']))
            statuses[stage]['status'] = 'completed'
            return {'stage': stage, 'status':'completed', 'delivery_file':'retained-final.mp4'}
        def current(value):
            return next((name for name, record in statuses.items() if record['status'] != 'completed'), None)
        data = {'stages': {name: {'input': name} for name in statuses}}
        with mock.patch.object(state, 'load_job', return_value=job), \
             mock.patch.object(state, 'current_stage', side_effect=current), \
             mock.patch.object(run_stage, '_execute_one_stage', side_effect=execute):
            result = run_stage.execute_stage(Path('/unused'), PROJECT, payload=data)
        self.assertEqual(inputs, [(name, {'input': name}) for name in statuses])
        self.assertTrue(all(value is operations[0] for value in operations))
        self.assertEqual(result['stage'], 'delivery')
        self.assertEqual(len(result['operation_timing']['stages']), 4)
        self.assertIsNone(startup.current_operation())
        statuses['visual_assets']['status'] = 'pending'
        inputs.clear()
        with mock.patch.object(state, 'load_job', return_value=job), \
             mock.patch.object(state, 'current_stage', side_effect=current), \
             mock.patch.object(run_stage, '_execute_one_stage', side_effect=execute):
            result = run_stage.execute_stage(Path('/unused'), PROJECT, 'visual_assets', payload=data)
        self.assertEqual(inputs, [('visual_assets', {'input':'visual_assets'})])
        self.assertEqual(len(result['operation_timing']['stages']), 1)

    def test_delivery_revision_preserves_delivered_files_and_requires_current_user_acceptance(self):
        from edit.hd.tools import state, delivery_approval as delivery
        from edit.hd.tests.media_fixture import make_av_fixture
        import audit_job_completion as audit
        with tempfile.TemporaryDirectory() as directory, mock.patch('edit.hd.tools.startup.require_startup'):
            root = Path(directory).resolve()
            video = make_av_fixture(root, 'source.mp4')
            script = root / 'script.txt'; script.write_text('synthetic fixture speech')
            job = state.create_job(root, video, script)
            preview = job.job_dir / '11-preview/review.mp4'
            preview.parent.mkdir(); preview.write_bytes(video.read_bytes())
            final = job.job_dir / '12-delivery/final.mp4'
            manifest = final.parent / 'delivery-manifest.json'
            def publish_manifest():
                manifest.write_text(json.dumps({'schema_version':2,'job_id':job.job_id,
                    'workflow_revision':job.revision,'workflow_sha256':job.expected_sha256,
                    'final_sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
                    'canvas':{'width':1080,'height':1920,'fps':24},
                    'artifacts':{'final.mp4':{'source':state._artifact_record(job,preview),
                        'output':{'path':'final.mp4','sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'bytes':final.stat().st_size}}}}))
            def review():
                return {'job_id':job.job_id,'job_dir':str(job.job_dir),'stage':'delivery',
                    'revision':job.revision,'artifacts':copy.deepcopy(job.stages['delivery']['artifacts']),
                    'user_confirmation':'synthetic fixture confirmation only'}
            for stage in state.stage_ids_for(job):
                paths = []
                if stage == 'preview':
                    paths = [preview]
                elif stage == 'delivery':
                    final.parent.mkdir(); final.write_bytes(preview.read_bytes())
                    publish_manifest(); paths = [final, manifest]
                state.mark_ready(job, stage, paths); state.complete(job, stage)
            (root / 'job-context.json').write_text(json.dumps({'workspace':str(root),'job_dir':str(job.job_dir),'job_id':job.job_id}))
            authorization = job.job_dir / 'manifests/visual-authorization-r1.json'
            authorization.parent.mkdir(exist_ok=True)
            authorization.write_text(json.dumps({'job_id':job.job_id,'authorized_by':'user',
                'authorization_scope':'visual_plan_and_generation','user_confirmation':'synthetic fixture spending authorization'}))
            self.enterContext(mock.patch.object(delivery,'validate_visual_plan_approval',
                return_value={'artifact':state._artifact_record(job,authorization)}))
            receipt_path = delivery.record_delivery(job)
            first_review = review()
            first_manifest = next(r for r in job.stages['delivery']['artifacts'] if r['path'].endswith('/delivery-manifest.json'))
            first_acceptance = job.job_dir / delivery.receipt_paths(first_manifest)[1]
            self.assertFalse(first_acceptance.exists())
            first_result = run_stage._execute_one_stage(job.job_dir, PROJECT)
            first_file = Path(first_result['delivery_file'])
            first_bytes = first_file.read_bytes()
            first_manifest_bytes = first_file.with_name('delivery-manifest.json').read_bytes()
            self.assertEqual(first_result['delivery_status'], 'delivered')
            self.assertEqual(audit.audit_job_completion(root)['status'], 'delivered')
            with self.assertRaises(state.WorkflowError):
                delivery.approve_delivery(job,delivery_manifest_sha256=first_manifest['sha256'],
                    delivery_sha256=hashlib.sha256(first_bytes).hexdigest(),user_confirmation='')
            accepted = run_stage._execute_one_stage(job.job_dir, PROJECT, review=first_review)
            self.assertEqual(accepted['delivery_status'], 'accepted')
            acceptance_bytes = first_acceptance.read_bytes()
            receipt_bytes = receipt_path.read_bytes()
            job.revision += 1; state.save_job(job)
            with mock.patch.object(delivery.shutil, 'copyfile', side_effect=AssertionError('same production must not copy')):
                repeated = run_stage._execute_one_stage(job.job_dir, PROJECT, stage='delivery', review=first_review)
                delivery.record_delivery(job)
            self.assertEqual(repeated['delivery_status'], 'accepted')
            self.assertEqual(first_acceptance.read_bytes(), acceptance_bytes)
            self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
            self.assertEqual(audit.audit_job_completion(root)['status'], 'accepted')
            state.revise(job, 'delivery', 'synthetic fixture revision with identical final bytes')
            self.assertEqual(delivery.current_delivery_status(job)['delivery_status'], 'pending')
            self.assertEqual(audit.audit_job_completion(root)['status'], 'incomplete')
            publish_manifest()
            state.mark_ready(job, 'delivery', [final,manifest])
            revised = run_stage._finish_stage(job.job_dir, 'delivery')
            job = state.load_job(job.job_dir)
            new_manifest = next(r for r in job.stages['delivery']['artifacts'] if r['path'].endswith('/delivery-manifest.json'))
            self.assertNotEqual(first_manifest['sha256'], new_manifest['sha256'])
            self.assertNotEqual(revised['delivery_file'], str(first_file))
            self.assertEqual(revised['delivery_status'], 'delivered')
            self.assertEqual(Path(revised['delivery_file']).read_bytes(), first_bytes)
            self.assertEqual(first_file.read_bytes(), first_bytes)
            self.assertEqual(first_file.with_name('delivery-manifest.json').read_bytes(), first_manifest_bytes)
            self.assertEqual(audit.audit_job_completion(root)['status'], 'delivered')
            with self.assertRaises(state.WorkflowError):
                delivery.approve_delivery(job,delivery_manifest_sha256=first_manifest['sha256'],
                    delivery_sha256=hashlib.sha256(first_bytes).hexdigest(),user_confirmation=first_review['user_confirmation'])
            with self.assertRaises(ValueError):
                run_stage._execute_one_stage(job.job_dir, PROJECT, review=first_review)
            new_review = review()
            self.assertEqual(run_stage._execute_one_stage(job.job_dir, PROJECT,
                stage='delivery', review=new_review)['delivery_status'], 'accepted')
            self.assertEqual(run_stage._execute_one_stage(job.job_dir, PROJECT,
                review=new_review)['delivery_status'], 'accepted')
            report = audit.audit_job_completion(root)
            self.assertEqual(report['status'], 'accepted', report)
            self.assertEqual(report['delivery_file'], revised['delivery_file'])
            self.assertEqual(first_acceptance.read_bytes(), acceptance_bytes)

    def test_visual_authorization_records_user_words_without_qa_claim(self):
        from edit.hd.tools import state, visual_confirmation as confirmation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video, script = root / 'source.mp4', root / 'script.txt'
            video.write_bytes(b'synthetic source'); script.write_text('synthetic speech')
            job = state.create_job(root, video, script)
            root = job.job_dir
            for name in state.STAGE_IDS[:6]:
                path = root / name / 'fixture.json'; path.parent.mkdir(); path.write_text('{}')
                state.mark_ready(job, name, [path]); state.complete(job, name)
            proposal_path = root / '07-visual-confirmation/source/proposal.json'
            proposal_path.parent.mkdir(parents=True)
            config = root / 'manifests/provider-config.json'; config.parent.mkdir(exist_ok=True); config.write_text('{}')
            proposal = {'kind':confirmation.SCHEMA,'job_id':job.job_id,'source_id':'source','inputs':{},
                'provider_config_sha256':hashlib.sha256(config.read_bytes()).hexdigest()}
            proposal_path.write_text(json.dumps(proposal))
            record = confirmation._record(root, proposal_path)
            state.mark_visual_ready(job, [proposal_path])
            receipt = confirmation.save_user_confirmation(job,{'revision':job.revision,'artifacts':[record],
                'user_confirmation':'确认这份完整清单和渠道费用，按表制作'})
            self.assertNotIn('passed', receipt)
            self.assertNotIn('reviewed_by', receipt)
            self.assertEqual(receipt['authorized_by'], 'user')
            self.assertEqual(confirmation.validate_visual_authorization(job)['payload'], receipt)
            config.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'channels changed'):
                confirmation.validate_visual_authorization(job)

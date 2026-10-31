"""Native task and reviewed media contracts; no paid calls or permanent Jobs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import _env
import motion_native_skill_adapter as native


def brief(dependency='barty-motion-graphics', template='motion-broll', alpha=False):
    return {'schema_version':2,'dependency_id':dependency,'job_id':'native-test',
            'source_binding':{'aroll_sha256':'a'*64,'segment_id':'seg-001','start':0,'end':2},
            'composition':{'width':1080,'height':1920,'fps':24,'frames':48},'alpha':alpha,
            'canvas_transport':'quarter_turn_cw' if dependency=='bang-motion' else 'identity',
            'template_request':{'semantic_family':'comparison','information_units':2,'numeric_values':[],'numeric_scale':'not_applicable'},
            'template_id':template,'semantic_goal':'比较两种结果','transcript':'先看输入，再看输出。',
            'native_options':[],
            'task_source':{'semantic_row_id':'semantic-1','quote':'先看输入，再看输出。','semantic':'比较两种结果',
                           'required_change':'对照输入与输出','component_brief':'表达输入与输出之间的变化'},
            'word_anchors':[{'text':'先看输入，再看输出。','start':0,'end':2}],
            'speech':{'job_path':'voice.wav','sha256':hashlib.sha256(b'voice').hexdigest(),'byte_count':5},
            'materials':[],'authorization':{'paid_generation':False},
            'project_directory':'native-projects/native-test','result_record_path':'native-inputs/native-test/result.json'}


class NativeMotionTests(unittest.TestCase):
    def test_broll_native_alpha_requires_a_valid_hybrid_annotation(self):
        import copy
        from edit.hd.tools import motion_capabilities as motion
        from edit.hd.tests.test_visual_strategy import valid_intent, valid_strategy, strategy_component
        row = next(item for item in motion.load_catalog(_env.PROJECT)
                   if item['candidate_id'] == 'barty-motion-graphics:barty-motion-graphics/motion-broll')
        base = strategy_component('base', 'ai_generated', media_type='video')
        action = strategy_component('action', 'code_generated', layer_role='annotation',
                                    layout_slot='annotation', media_type='animation')
        segment = {'visual_intent': valid_intent(), 'visual_strategy': valid_strategy([base, action])}
        transparent = brief(alpha=True)
        check = lambda b, s, cid='action': motion._native_input_check(
            _env.PROJECT, row, b, segment=s, component_id=cid, use='broll')
        self.assertEqual(check(transparent, segment)['status'], 'pass')
        self.assertEqual(check(brief(alpha=False), segment)['status'], 'fail')
        self.assertEqual(check(transparent, segment, 'base')['status'], 'fail')
        invalid = copy.deepcopy(segment)
        invalid['visual_strategy']['composition']['component_dependencies'] = []
        self.assertEqual(check(transparent, invalid)['status'], 'fail')
        invalid = copy.deepcopy(segment)
        invalid['visual_strategy']['components'][0]['semantic_role'] = 'evidence'
        self.assertEqual(check(transparent, invalid)['status'], 'fail')
        self.assertEqual(motion._native_input_check(_env.PROJECT, row, transparent)['status'], 'fail')
        overlay_row = {**row, 'role': 'aroll_overlay'}
        self.assertEqual(motion._native_input_check(_env.PROJECT, overlay_row, transparent)['status'], 'pass')
        self.assertEqual(motion._native_input_check(_env.PROJECT, overlay_row, brief(alpha=False))['status'], 'fail')

    def test_semantic_planning_task_cannot_turn_into_completed_evidence(self):
        from edit.hd.tools import motion_capabilities
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'brief.json'
            for dependency in ('barty-motion-graphics', 'bang-motion'):
                request = brief(dependency)
                words = [{'text': request['transcript'], 'start': 0, 'end': 2}]
                segment = {'segment_id': 'seg-001', 'start': 0, 'end': 2, 'bindings': {'scene': {}}}
                row = {'candidate_id': 'selected-native', 'dependency_id': dependency,
                       'capability': {'capability_type': 'creative_skill'}}
                assessment = {'segment_id': 'seg-001', 'component_id': 'scene', 'candidate_id': row['candidate_id'],
                    'verdict': 'pass', 'reason': 'Only the approved native task, not an actual produced animation.',
                    'transcript_refs': [{'start_word': 0, 'end_word': 1, 'quote': request['transcript'],
                                         'basis': 'current_clause'}], 'content_refs': []}
                treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'scene', 'brief_path': path.name}],
                             'semantic_assessments': [assessment]}
                def write():
                    path.write_text(json.dumps(request)); digest = native.sha(path)
                    segment['bindings']['scene']['brief_sha256'] = digest
                    assessment['content_refs'] = [{'path': path.name, 'sha256': digest, 'pointer': '/' + key,
                        'value': request[key]} for key in ('transcript', 'template_id', 'native_options')]
                    assessment['content_refs'] += [{'path': path.name, 'sha256': digest,
                        'pointer': '/task_source/' + key, 'value': request['task_source'][key]} for key in ('quote', 'semantic')]
                write()
                planning = motion_capabilities._semantic_assessment(root, treatment, segment, 'scene', row,
                                                                     words, request, phase='planning')
                self.assertEqual(planning['status'], 'pass')
                self.assertEqual(planning['scope'], 'planning_inputs')
                for result in ('missing', None, {'status': 'pending'},
                               {'status': 'completed', 'scene_sources': [], 'record': {'job_path': 'result.json'}}):
                    if result != 'missing': request['native_result'] = result
                    write()
                    with self.subTest(dependency=dependency, result=result):
                        completed = motion_capabilities._semantic_assessment(root, treatment, segment, 'scene', row,
                                                                            words, request, phase='completed')
                        self.assertEqual(completed['status'], 'needs_review')
                        self.assertFalse(completed['binding_verified'])

    def test_complete_original_sources_and_native_workflow_paths(self):
        for dependency, count in [('barty-motion-graphics',4),('bang-motion',35),('mg-styles-15',15),('video-shotcraft',125)]:
            source = native.source_root(_env.PROJECT, dependency_id=dependency)
            rows = native.load_template_catalog(_env.PROJECT, dependency_id=dependency)
            self.assertEqual(len(rows),count)
            self.assertTrue(all((_env.PROJECT / row['skill_path']).is_file() for row in rows))
        for template in sorted(native.BARTY_TEMPLATES - {'motion-broll'}):
            renderer=native.embedded_renderer(native.source_root(dependency_id='barty-motion-graphics')/'skills'/template/'SKILL.md')
            self.assertTrue(renderer.startswith(b'// render.mjs:'))
            self.assertIn(b"from 'playwright'",renderer)

    def test_new_native_channels_keep_full_sources_roles_and_alpha_boundary(self):
        for dependency, template in [('mg-styles-15', 'flat-vector'), ('video-shotcraft', 'blur-slide')]:
            request = brief(dependency, template)
            native.validate_brief(json.dumps(request)); native._template(request)
            request['alpha'] = True
            with self.assertRaisesRegex(ValueError, 'transparent'):
                native.validate_brief(json.dumps(request))
        rows = native.load_template_catalog(_env.PROJECT, dependency_id='video-shotcraft')
        self.assertEqual(sum(len(row.get('styles', [])) for row in rows), 150)
        for row in rows:
            if row['native_template_group'] in {'camera', 'transition', 'rhythm'}:
                self.assertNotEqual(row['native_role'], 'scene')
            if row['native_template_group'] != 'template':
                self.assertTrue(row['native_demos'])
                self.assertTrue(all((_env.PROJECT / p).is_file() for p in row['native_demos']))
        request = brief('video-shotcraft', 'blur-slide');request['native_options'] = ['not-an-original-variant']
        with self.assertRaisesRegex(ValueError, 'variant'):
            native._template(request)

    def test_only_explicit_original_template_duration_limits_are_enforced(self):
        b=brief('video-shotcraft','ink-press')
        def clock(frames):
            b['composition']['frames']=frames;b['source_binding']['end']=frames/24
            b['word_anchors'][0]['end']=frames/24
            native.validate_brief(json.dumps(b))
        clock(144)
        with self.assertRaisesRegex(ValueError,'original template duration'):
            native._template(b)
        clock(868);native._template(b)
        b['template_id']='spotlight-hero-card';clock(144);native._template(b)

    def test_mg_capture_requires_verbatim_harness_and_exact_clock(self):
        import shutil
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();request=brief('mg-styles-15','flat-vector')
            project=root/request['project_directory'];(project/'harness').mkdir(parents=True)
            (project/'scene').mkdir();(project/'scene/index.html').write_text('<html/>')
            source=native.source_root(dependency_id='mg-styles-15')
            shutil.copyfile(source/'harness/render.mjs',project/'harness/render.mjs')
            modules=root/'modules';modules.mkdir();(project/'node_modules').symlink_to(modules,target_is_directory=True)
            runtime={'tools':{'node':'/usr/bin/node'},'node_modules':str(modules)}
            argv=['/usr/bin/node','harness/render.mjs','scene','--out','out/native.mp4',
                  '--w','1080','--h','1920','--fps','24','--duration','2.0','--workers','1','--noaudio']
            _,_,output=native._render_command(root,request,argv,runtime)
            self.assertEqual(output,project/'out/native.mp4')
            wrong=argv[:];wrong[12]='3.0'
            with self.assertRaisesRegex(ValueError,'clock'):
                native._render_command(root,request,wrong,runtime)
            (project/'harness/render.mjs').write_text('// replacement renderer')
            with self.assertRaisesRegex(ValueError,'verbatim'):
                native._render_command(root,request,argv,runtime)

    def test_shotcraft_capture_runs_the_real_cli_with_checked_browser(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();request=brief('video-shotcraft','blur-slide')
            project=root/request['project_directory'];(project/'src').mkdir(parents=True)
            (project/'src/index.ts').write_text('// authored current-task entry')
            modules=root/'modules';(modules/'@remotion/cli').mkdir(parents=True)
            cli=modules/'@remotion/cli/remotion-cli.js';cli.write_text('// pinned runtime cli fixture')
            (project/'node_modules').symlink_to(modules,target_is_directory=True)
            runtime={'tools':{'node':'/usr/bin/node'},'node_modules':str(modules),'browser':'/native/chrome'}
            argv=['/usr/bin/node',str(cli),'render','src/index.ts','NativeScene','out/native.mp4',
                  '--codec=h264','--pixel-format=yuv420p','--color-space=bt709','--image-format=png','--muted','--concurrency=1','--browser-executable=/native/chrome']
            _,script,output=native._render_command(root,request,argv,runtime)
            self.assertEqual(script,cli);self.assertEqual(output,project/'out/native.mp4')
            argv[-1]='--browser-executable=/other/chrome'
            with self.assertRaisesRegex(ValueError,'browser'):
                native._render_command(root,request,argv,runtime)

    def test_exact_clock_alpha_and_whole_board_transport(self):
        b=brief();self.assertEqual(native.validate_brief(json.dumps(b)),b)
        b['composition']['frames']=47
        with self.assertRaisesRegex(ValueError,'clock'):native.validate_brief(json.dumps(b))
        for dependency,template in [('barty-motion-graphics','explainer-default'),('bang-motion','style-cinematic-dark')]:
            with self.assertRaisesRegex(ValueError,'transparent'):native.validate_brief(json.dumps(brief(dependency,template,True)))
        b=brief('bang-motion','style-cinematic-dark');b['canvas_transport']='identity'
        with self.assertRaisesRegex(ValueError,'canvas transport'):native.validate_brief(json.dumps(b))

    def test_native_task_passes_content_without_parent_composition(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'brief.json';p.write_text(json.dumps(brief()))
            job=SimpleNamespace(job_dir=root,job_id='native-test')
            with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                action=native.native_task(job,{'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(p)},p,
                    approved_task_source=brief()['task_source'])
            self.assertEqual(action['action'],'execute_native_skill')
            self.assertEqual(action['requirements']['transcript'],brief()['transcript'])
            self.assertFalse(set(action['requirements']) & {'beats','layers','design_plan','keyframes','layout'})
            self.assertTrue(action['skill_path'].endswith('/skills/motion-broll/SKILL.md'))
            self.assertEqual(action['task_source'],brief()['task_source'])
            with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                with self.assertRaisesRegex(ValueError,'confirmed binding'):
                    native.native_task(job,{'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(p)},p,
                        approved_task_source={**brief()['task_source'],'semantic':'另一件事'})

    def test_new_native_tasks_receive_only_their_own_workflow(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);request=root/'brief.json'
            for dependency,template in [('mg-styles-15','flat-vector'),('video-shotcraft','spotlight-hero-card')]:
                b=brief(dependency,template);request.write_text(json.dumps(b))
                with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                    action=native.native_task(SimpleNamespace(job_dir=root,job_id=b['job_id']),
                        {'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(request)},request,
                        approved_task_source=b['task_source'])
                self.assertNotIn('engine/build.py',action['next'])
                self.assertNotIn('quarter_turn_cw',action['next'])
                self.assertNotIn('export-frames.mjs',action['next'])
                self.assertIn('harness/render.mjs' if dependency=='mg-styles-15' else '@remotion/cli',action['next'])

    def test_capture_requires_exact_original_embedded_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);b=brief(template='explainer-default');project=root/b['project_directory'];project.mkdir(parents=True)
            (project/'page.html').write_text('<html></html>');(project/'render.mjs').write_text('not the original renderer')
            runtime={'tools':{'node':'/usr/bin/node'},'node_modules':str(root/'modules')}
            with self.assertRaisesRegex(ValueError,'verbatim original'):
                native._render_command(root,b,['/usr/bin/node',str(project/'render.mjs'),'page.html','out/native.mp4','24'],runtime)

    def test_barty_explainer_preserves_existing_original_before_silent_output(self):
        runtime={'tools':{'node':'/usr/bin/node'},'node_modules':None,'environment':{}}
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief(template='explainer-default');project=root/b['project_directory']
            (project/'out').mkdir(parents=True);(project/'page.html').write_text('<html/>')
            original=project/'out/native.mp4';original.write_bytes(b'earlier accepted original media')
            modules=root/'modules';modules.mkdir();runtime['node_modules']=str(modules)
            (project/'node_modules').symlink_to(modules,target_is_directory=True)
            (project/'render.mjs').write_bytes(native.embedded_renderer(
                native.source_root(dependency_id=b['dependency_id'])/'skills/explainer-default/SKILL.md'))
            request=root/'brief.json';request.write_text(json.dumps(b))
            argv=['/usr/bin/node','render.mjs','page.html','out/native.mp4','24']
            with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value=runtime), \
                 mock.patch.object(native.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'Preserve existing native output'):
                    native.capture_render(root,request,argv)
            run.assert_not_called()
            self.assertEqual(original.read_bytes(),b'earlier accepted original media')
            self.assertFalse((project/'out/native_silent.mp4').exists())

    def test_pending_alpha_overlay_uses_standard_parent_subtitles_without_avatar(self):
        from types import SimpleNamespace
        import run_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();b=brief(alpha=True)
            request=root/'brief.json';request.write_text(json.dumps(b));cid='overlay'
            composition={'family':'aroll_with_overlay','presenter_mode':'full_frame'}
            director={'segments':[{'segment_id':'seg-001',
                'visual_strategy':{'mode':'none','composition':composition,
                    'components':[{'component_id':cid,'brief':b['task_source']['component_brief']}]},
                'bindings':{cid:{'dependency_id':b['dependency_id'],'brief_sha256':native.sha(request)}}}]}
            treatment={'scenes':[{'segment_id':'seg-001','component_id':cid,'brief_path':'brief.json'}],
                'semantic_lists':{'overlay':[{'row_id':'semantic-1','quote':b['task_source']['quote'],
                    'semantic':b['task_source']['semantic'],'components':[{'segment_id':'seg-001','component_id':cid}]}]},
                'skill_selection':{'overlay_beats':[{'segment_id':'seg-001','component_id':cid,'semantic_row_id':'semantic-1',
                    'required_change':b['task_source']['required_change'],'component_brief':b['task_source']['component_brief']}]}}
            with mock.patch.object(run_stage,'_module',return_value=native),mock.patch.object(native,'_inputs'), \
                 mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                actions=run_stage.pending_native_actions(SimpleNamespace(job_dir=root,job_id=b['job_id']),director,treatment)
            layout=actions[0]['requirements']['parent_subtitle_layout']
            self.assertEqual(layout['placement'],'standard')
            self.assertIsNone(layout['safe_zones']['face'])
            self.assertEqual(layout['safe_zones']['subtitle'],{'x':80,'y':1430,'width':920,'height':230})
            self.assertNotIn('avatar',composition)

    def test_native_video_inputs_are_frozen_separately_from_render_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();project=root/'native-projects/scene';(project/'assets').mkdir(parents=True)
            source=project/'assets/source.mp4';source.write_bytes(b'input footage')
            (project/'out').mkdir();(project/'out/native.mp4').write_bytes(b'rendered output')
            files=native.project_files(root,project)
            self.assertEqual([r['job_path'] for r in files],['native-projects/scene/assets/source.mp4'])
            source.write_bytes(b'changed input footage')
            with self.assertRaisesRegex(ValueError,'changed'):native.exact(root,files[0])

    def test_nested_asset_out_is_an_input_not_the_root_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();project=root/'native-projects/scene'
            (project/'assets/out').mkdir(parents=True);asset=project/'assets/out/picture.svg';asset.write_text('<svg/>')
            (project/'out').mkdir();(project/'out/render.mp4').write_bytes(b'output')
            files=native.project_files(root,project)
            self.assertEqual([r['job_path'] for r in files],['native-projects/scene/assets/out/picture.svg'])
            asset.write_text('<svg>changed</svg>')
            with self.assertRaisesRegex(ValueError,'changed'):native.exact(root,files[0])

    def test_relative_original_renderer_uses_project_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();b=brief(template='explainer-default');project=root/b['project_directory'];project.mkdir(parents=True)
            (project/'page.html').write_text('<html/>');modules=root/'modules';modules.mkdir()
            (project/'node_modules').symlink_to(modules,target_is_directory=True)
            (project/'render.mjs').write_bytes(native.embedded_renderer(native.source_root(dependency_id=b['dependency_id'])/'skills/explainer-default/SKILL.md'))
            runtime={'tools':{'node':'/usr/bin/node'},'node_modules':str(modules)}
            _,script,_=native._render_command(root,b,['/usr/bin/node','render.mjs','page.html','out/native.mp4','24'],runtime)
            self.assertEqual(script,project/'render.mjs')

    def test_native_options_keep_the_narrative_primary_and_do_not_change_task_identity(self):
        b=brief('bang-motion','explainer-continuous-action');b['native_options']=['style-paper-print']
        native.validate_brief(json.dumps(b));native._template(b)
        revision={**b,'project_directory':'native-projects/revision','result_record_path':'native-inputs/revision.json'}
        self.assertEqual(native.approved_task(b),native.approved_task(revision))
        combined=brief('bang-motion','opener-object-relay');combined['native_options']=['opener-continuous-shot','style-paper-print']
        native.validate_brief(json.dumps(combined));native._template(combined)
        b['template_id']='style-paper-print';b['native_options']=['explainer-continuous-action']
        with self.assertRaisesRegex(ValueError,'primary'):native._template(b)
        b['native_options']=['style-paper-print']
        with self.assertRaisesRegex(ValueError,'options'):native.validate_brief(json.dumps(b))

    def test_each_result_in_one_input_directory_gets_its_own_call_record(self):
        runtime={'tools':{'node':'/usr/bin/node'},'node_modules':'/unused',
                 'renderer_version':'playwright-1.64.0','runtime_identity':{},'environment':{}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();calls=[]
            for name in ('first','second'):
                b=brief();b.update(project_directory='native-projects/'+name,result_record_path='native-inputs/'+name+'.json')
                project=root/b['project_directory'];project.mkdir(parents=True)
                (project/'out').mkdir()
                (project/'page.html').write_text('<html/>');request=root/(name+'.json');request.write_text(json.dumps(b))
                script=native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'
                argv=['/usr/bin/node',str(script),'page.html','out/render.mp4','24']
                def render(*args,**kwargs):
                    (project/'out/render.mp4').write_bytes(b'fixture video')
                    return mock.Mock(returncode=0,stdout='',stderr='')
                with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value=runtime), \
                     mock.patch.object(native.subprocess,'run',side_effect=render),mock.patch.object(native,'probe',return_value=b['composition']):
                    calls.append(native.capture_render(root,request,argv))
            self.assertEqual([p.name for p in calls],['first.render-call.json','second.render-call.json'])
            self.assertTrue(all(p.is_file() for p in calls))

    def test_failed_output_inspection_retains_actual_native_call(self):
        runtime={'tools':{'node':'/usr/bin/node'},'node_modules':'/unused',
                 'renderer_version':'playwright-1.64.0','runtime_identity':{},'environment':{}}
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief();project=root/b['project_directory'];project.mkdir(parents=True)
            (project/'page.html').write_text('<html/>');request=root/'brief.json';request.write_text(json.dumps(b))
            script=native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'
            argv=['/usr/bin/node',str(script),'page.html','out/native.mp4','24']
            def render(*args,**kwargs):
                (project/'out/native.mp4').write_bytes(b'actual but rejected native output')
                return mock.Mock(returncode=0,stdout='original renderer stdout',stderr='')
            with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value=runtime), \
                 mock.patch.object(native.subprocess,'run',side_effect=render), \
                 mock.patch.object(native,'probe',side_effect=ValueError('wrong output pixel format')):
                with self.assertRaisesRegex(ValueError,'pixel format'):
                    native.capture_render(root,request,argv)
            call=json.loads((root/'native-inputs/native-test/result.render-call.json').read_bytes())
            self.assertEqual(call['stdout'],'original renderer stdout')
            self.assertEqual(call['exit_code'],0)
            self.assertEqual(call['artifact_check_error'],'wrong output pixel format')
            self.assertNotIn('media',call)

    def test_reviewed_record_and_actual_media_must_both_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/brief()['result_record_path'];p.parent.mkdir(parents=True);p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'reviewed version'):
                native.load_result(root,json.dumps(brief()),expected_record={'path':brief()['result_record_path'],'sha256':'a'*64,'bytes':2},expected_renderer_version='playwright-1.64.0')
            media=root/'media.mp4';media.write_bytes(b'reviewed video');record=native.descriptor(root,media)
            media.write_bytes(b'replaced video')
            with self.assertRaisesRegex(ValueError,'changed'):native.exact(root,record)

    def test_overlay_planning_does_not_require_a_future_result_but_final_check_does(self):
        from types import SimpleNamespace
        from edit.hd.tools import overlay_alignment, contract_artifacts as artifacts
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();b=brief(alpha=True)
            request=root/'native-inputs/brief.json';request.parent.mkdir();artifacts.write_json_artifact(request,b)
            words=root/'words.json';artifacts.write_json_artifact(words,{'words':b['word_anchors']})
            timeline=root/'timeline.json';artifacts.write_json_artifact(timeline,{'segments':[
                {'source_start':0,'source_end':2,'timeline_start':0,'timeline_end':2}]})
            binding={'dependency_id':'barty-motion-graphics','entrypoint':native.ENTRY,'producer_version':native.VERSION,
                     'template_id':'barty-motion-graphics/motion-broll','brief_sha256':native.sha(request)}
            draft={'segments':[{'segment_id':'seg-001','start':0,'end':2,'bindings':{'scene':binding},
                               'visual_strategy':{'composition':{'family':'aroll_with_overlay'}}}]}
            treatment=root/'treatment.json';artifacts.write_json_artifact(treatment,{'overlay_alignment':[
                {'segment_id':'seg-001','component_id':'scene','brief_path':'native-inputs/brief.json'}]})
            def approved(job,stage,name):
                return (words if stage=='speech_cleanup' else timeline, 'a'*64)
            with mock.patch.object(overlay_alignment,'_approved',side_effect=approved), \
                 mock.patch.object(native,'inspect_result',side_effect=FileNotFoundError('future result')) as inspect:
                result=overlay_alignment.validate_treatment(SimpleNamespace(job_dir=root),draft,treatment,phase='planning')
                self.assertEqual(result[0]['phase'],'planning');inspect.assert_not_called()
                with self.assertRaises(FileNotFoundError):
                    overlay_alignment.validate_treatment(SimpleNamespace(job_dir=root),draft,treatment)


if __name__=='__main__':unittest.main()

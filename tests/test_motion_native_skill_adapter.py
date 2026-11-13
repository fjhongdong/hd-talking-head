"""Native task and reviewed media contracts; no paid calls or permanent Jobs."""
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
import _env
import motion_native_skill_adapter as native


def brief(dependency='barty-motion-graphics', template='motion-broll', alpha=False):
    if dependency == 'cinecode' and template == 'motion-broll':
        template = 'cinematic-realistic'
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
    def setUp(self):
        # These contract fixtures have no workflow; the real identity gate is
        # exercised separately below, before any native runner or artifact I/O.
        from types import SimpleNamespace
        gate = mock.patch.object(native, '_execution_job', return_value=SimpleNamespace(job_id='native-test'))
        gate.start()
        self.addCleanup(gate.stop)
        dispatch = mock.patch('edit.hd.tools.visual_confirmation.require_native_dispatch')
        dispatch.start()
        self.addCleanup(dispatch.stop)

    def test_planned_binding_needs_current_brief_without_a_reference_sample(self):
        from types import SimpleNamespace
        for dependency in native.SOURCES:
            adapter = SimpleNamespace(dependency_id=dependency, renderer_version='test-runtime',
                entrypoint_sha256=native.sha(_env.PROJECT / native.ENTRY), launcher=Path(sys.executable))
            payload = json.dumps(brief(dependency)).encode()
            with self.subTest(dependency=dependency):
                binding = native.create_binding(adapter, payload)
                self.assertNotIn('sample_sha256', binding)
                self.assertEqual(binding['brief_sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(binding['invocation_record']['status'], 'planned')
                self.assertIsNone(binding['invocation_record']['exit_code'])

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
        for dependency, count in [('barty-motion-graphics',4),('bang-motion',35),('mg-styles-15',15),('video-shotcraft',125),('bb-video',30)]:
            source = native.source_root(_env.PROJECT, dependency_id=dependency)
            rows = native.load_template_catalog(_env.PROJECT, dependency_id=dependency)
            self.assertEqual(len(rows),count)
            self.assertTrue(all((_env.PROJECT / row['skill_path']).is_file() for row in rows))
        for template in sorted(native.BARTY_TEMPLATES - {'motion-broll'}):
            renderer=native.embedded_renderer(native.source_root(dependency_id='barty-motion-graphics')/'skills'/template/'SKILL.md')
            self.assertTrue(renderer.startswith(b'// render.mjs:'))
            self.assertIn(b"from 'playwright'",renderer)

    def test_new_native_channels_keep_full_sources_roles_and_alpha_boundary(self):
        for dependency, template in [('mg-styles-15', 'flat-vector'), ('video-shotcraft', 'blur-slide'), ('bb-video', 'whiteboard')]:
            request = brief(dependency, template)
            native.validate_brief(json.dumps(request)); native._template(request)
            request['alpha'] = True
            with self.assertRaisesRegex(ValueError, 'transparent'):
                native.validate_brief(json.dumps(request))
        rows = native.load_template_catalog(_env.PROJECT, dependency_id='video-shotcraft')
        self.assertEqual(sum(len(row.get('styles', [])) for row in rows), 150)
        for row in rows:
            if row['candidate_id'].rsplit('/',1)[-1] in {'space-camera-moves','shot-transitions','beat-cut-moves'}:
                self.assertNotEqual(row['native_role'], 'scene')
            if row['native_template_group'] != 'template':
                self.assertTrue(row['native_demos'])
                self.assertTrue(all((_env.PROJECT / p).is_file() for p in row['native_demos']))
        request = brief('video-shotcraft', 'blur-slide');request['native_options'] = ['not-an-original-variant']
        with self.assertRaisesRegex(ValueError, 'variant'):
            native._template(request)

    def test_bb_workflow_options_are_internal_and_original_narrative_budget_stays_real(self):
        b=brief('bb-video','whiteboard')
        for options in ([],['explainer'],['promo']):
            b['native_options']=options;native.validate_brief(json.dumps(b));native._template(b)
        for options in (['quick'],['explainer','promo']):
            b['native_options']=options
            with self.assertRaisesRegex(ValueError,'workflow'):
                native._template(b)
        b=brief('bb-video','parable')
        with self.assertRaisesRegex(ValueError,'duration'):
            native._template(b)
        b['composition']['frames']=360;b['source_binding']['end']=15
        native._template(b)

    def test_bb_capture_requires_real_public_entry_exact_clock_and_original_runtime(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief('bb-video','whiteboard')
            project=root/b['project_directory'];(project/'lib').mkdir(parents=True)
            (project/'index.html').write_text('<html/>')
            source=native.source_root(dependency_id='bb-video')/'skills/bb-video'
            shutil.copyfile(source/'core/runtime/core.js',project/'lib/core.js')
            shutil.copyfile(source/'explainer/runtime/whiteboard.js',project/'lib/whiteboard.js')
            runtime={'tools':{'node':'/tools/node'}}
            argv=['/tools/node',str(source/'explainer/scripts/render.mjs'),str(project),
                  '--aspect','9:16','--fps','24','--from','0','--to','2.0','--no-audio','--no-bgm',
                  '--workers','1','--out','native.mp4']
            for workflow in ('explainer','promo'):
                argv[1]=str(source/workflow/'scripts/render.mjs')
                _,script,output=native._render_command(root,b,argv,runtime)
                self.assertEqual(script,Path(argv[1]));self.assertEqual(output,project/'out/native.mp4')
            for wrong in (argv+['--force'],argv+['--draft'],argv+['--allow-font-fallback'],
                          argv[:10]+['3.0']+argv[11:],argv[:-1]+['out/native.mp4'],argv[:-1]+['../native.mp4']):
                with self.assertRaises(ValueError):native._render_command(root,b,wrong,runtime)
            copied=project/'render.mjs';shutil.copyfile(Path(argv[1]),copied)
            with self.assertRaisesRegex(ValueError,'pinned public'):
                native._render_command(root,b,[argv[0],str(copied),*argv[2:]],runtime)
            (project/'lib/whiteboard.js').write_text('// modified original runtime')
            with self.assertRaisesRegex(ValueError,'runtime changed'):
                native._render_command(root,b,argv,runtime)

    def test_bb_capture_publish_and_reuse_bind_real_command_without_npm_or_historical_tools(self):
        import motion_native_runtime as runtime_module
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief('bb-video','whiteboard')
            project=root/b['project_directory'];(project/'lib').mkdir(parents=True)
            (project/'index.html').write_text('<html>actual current-task scene</html>')
            source=native.source_root(dependency_id='bb-video')/'skills/bb-video'
            shutil.copyfile(source/'core/runtime/core.js',project/'lib/core.js')
            request=root/'brief.json';request.write_text(json.dumps(b))
            tools={key:'/historical/missing/'+key for key in ('node','ffmpeg','ffprobe')}
            renderer=runtime_module.renderer_version('bb-video')
            identity={'schema_version':1,'dependency_id':'bb-video','renderer_version':renderer,
                'source_sha256':native.sha(_env.PROJECT/'references/bb-video-native-source.json'),
                'tools':{key:{'path':value,'version':'v26.10.0' if key=='node' else key+' version 8'} for key,value in tools.items()},
                'browser':{'path':'/historical/missing/chrome','version':'Chrome 140'}}
            runtime={'tools':tools,'renderer_version':renderer,'runtime_identity':identity,
                     'environment':{'CHROME_PATH':identity['browser']['path']}}
            argv=[tools['node'],str(source/'explainer/scripts/render.mjs'),str(project),
                  '--aspect','9:16','--fps','24','--from','0','--to','2.0','--no-audio','--no-bgm',
                  '--workers','1','--out','native.mp4']
            def execute(command,**kwargs):
                self.assertEqual(command,argv)
                self.assertEqual(kwargs['env']['CHROME_PATH'],identity['browser']['path'])
                (project/'out/native.mp4').write_bytes(b'real recorded native output fixture')
                return subprocess.CompletedProcess(command,0,'native lint and font checks\nactual renderer output','')
            with mock.patch.object(native,'_inputs'),mock.patch.object(runtime_module,'check',return_value=runtime), \
                 mock.patch.object(native,'_run_native_process',side_effect=execute) as process, \
                 mock.patch.object(native,'probe',return_value=b['composition']):
                callpath=native.capture_render(root,request,argv)
                call=json.loads(callpath.read_bytes())
                self.assertNotIn('node_modules',call['execution_runtime'])
                self.assertEqual(call['native_script_sha256'],native.sha(Path(argv[1])))
                self.assertEqual(call['status'],'completed');self.assertEqual(process.call_count,1)
                result=native.publish_completed(root,request,callpath)
                self.assertEqual(native.inspect_result(root,request.read_bytes())['media'],call['media'])
                self.assertEqual(json.loads(result.read_bytes())['status'],'completed')
                self.assertNotIn('qa_note', json.loads(result.read_bytes()))
                (project/'index.html').write_text('later changed scene')
                with self.assertRaisesRegex(ValueError,'changed'):
                    native.inspect_result(root,request.read_bytes())

    def test_cinecode_capture_preserves_original_recipe_local_inputs_and_silent_clock(self):
        from cinecode_browser_assets import LOCK_SHA256
        import motion_native_runtime as runtime_module
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            b = brief('cinecode', 'glass-product')
            project = root / b['project_directory']
            project.mkdir(parents=True)
            scene = project / 'film.html'
            scene.write_text('<html>actual glass-product scene<script src="active.mjs"></script></html>')
            active = project / 'active.mjs'
            active.write_text('// loaded in the authored scene')
            unused = project / 'unused.mjs'
            unused.write_text('// unused in the authored scene')
            (project / 'plate.mp4').write_bytes(b'0123456789')
            (project.parent / 'unapproved.txt').write_text('must stay out of capture')
            request = root / 'brief.json'
            request.write_text(json.dumps(b))
            tools = {key: '/historical/missing/' + key for key in ('node', 'ffmpeg', 'ffprobe')}
            renderer = runtime_module.renderer_version('cinecode')
            identity = {'schema_version': 1, 'dependency_id': 'cinecode', 'renderer_version': renderer,
                        'source_sha256': native.sha(_env.PROJECT / 'references/cinecode-native-source.json'),
                        'browser_assets_sha256': LOCK_SHA256,
                        'tools': {key: {'path': value, 'version': 'v26.10.0' if key == 'node' else key + ' version 8'}
                                  for key, value in tools.items()},
                        'browser': {'path': '/historical/missing/chrome', 'version': 'Chrome 140'}}
            runtime = {'tools': tools, 'renderer_version': renderer, 'runtime_identity': identity,
                       'environment': {'CHROME_PATH': identity['browser']['path']}}
            capture = native.source_root(dependency_id='cinecode') / 'scripts/capture.mjs'
            argv = [tools['node'], str(capture), '--url', 'film.html', '--params', 'w=1080&h=1920',
                    '--flags', native.CINECODE_BROWSER_FLAGS, '--video', 'out/native.mp4']

            def execute(command, **kwargs):
                origin = command[3].rsplit('/', 1)[0]
                with urlopen(Request(command[3], headers={'Sec-Fetch-Dest': 'document'}), timeout=5) as response:
                    self.assertEqual(response.read(), scene.read_bytes())
                    self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
                with urlopen(Request(origin + '/active.mjs', headers={'Sec-Fetch-Dest': 'script'}), timeout=5) as response:
                    self.assertEqual(response.read(), active.read_bytes())
                clip = Request(origin + '/plate.mp4', headers={'Range': 'bytes=2-4', 'Sec-Fetch-Dest': 'video'})
                with urlopen(clip, timeout=5) as response:
                    self.assertEqual((response.status, response.read()), (206, b'234'))
                with self.assertRaises(HTTPError) as denied:
                    urlopen(origin + '/../unapproved.txt', timeout=5)
                self.assertEqual(denied.exception.code, 404)
                (project / 'out/native.mp4').write_bytes(b'recorded fixture output')
                return subprocess.CompletedProcess(command, 0, '[capture] page: 1080x1920, 48 frames @ 24 fps\n', '')

            pixels = b'\x11\x22\x33\x77\x88\x99' * (270 * 480 // 2)
            with mock.patch.object(native, '_inputs'), mock.patch.object(runtime_module, 'check', return_value=runtime), \
                 mock.patch.object(native, '_run_native_process', side_effect=execute) as process, \
                 mock.patch('cinecode_capture_evidence.review_frames', return_value=[pixels] * 5), \
                 mock.patch.object(native, 'probe', return_value=b['composition']):
                with self.assertRaisesRegex(ValueError, 'picture-only'):
                    native.capture_render(root, request, [*argv, '--audio', 'out/native.wav'])
                call_path = native.capture_render(root, request, argv)
                call = json.loads(call_path.read_bytes())
                self.assertEqual(call['argv'], argv)
                self.assertEqual(call['local_http']['argv'], process.call_args.args[0])
                self.assertIn('vendor/cinecode/styles/glass-product.md',
                              {ref['source_path'] for ref in call['native_sources']})
                self.assertEqual([ref['job_path'] for ref in native.loaded_project_files(root, b, call)], [
                    b['project_directory'] + '/' + name for name in ('active.mjs', 'film.html', 'plate.mp4')])
                self.assertEqual([row['index'] for row in call['review_frames']], [0, 12, 24, 35, 47])
                usage = [{'card_id': b['template_id'], 'variant': None, 'purpose': 'show the moving mechanism',
                          'implementation_refs': [native.descriptor(root, scene), native.descriptor(root, active)]}]
                with self.assertRaisesRegex(ValueError, 'approved original template'):
                    native.publish_completed(root, request, call_path,
                                             native_usage=[{**usage[0], 'card_id': 'cinematic-realistic'}])
                with self.assertRaisesRegex(ValueError, 'captured HTML entry'):
                    native.publish_completed(root, request, call_path, native_usage=[
                        {**usage[0], 'implementation_refs': [native.descriptor(root, active)]}])
                with self.assertRaisesRegex(ValueError, 'loaded authored scripts'):
                    native.publish_completed(root, request, call_path, native_usage=[
                        {**usage[0], 'implementation_refs': [native.descriptor(root, scene), native.descriptor(root, unused)]}])
                native.publish_completed(root, request, call_path, native_usage=usage)
                self.assertEqual(native.inspect_result(root, request.read_bytes())['native_usage'], usage)
                with mock.patch('cinecode_capture_evidence.review_frames', return_value=[bytes(len(pixels))] * 5):
                    with self.assertRaisesRegex(ValueError, 'only blank'):
                        native._verify_call(root, b, request.read_bytes(), call)
                call['stdout'] = '[capture] page: 1080x1920, 49 frames @ 24 fps\n'
                with self.assertRaisesRegex(ValueError, 'READY clock'):
                    native._verify_call(root, b, request.read_bytes(), call)

    def test_cinecode_variety_captions_select_the_original_video_photo_or_drawn_branch(self):
        b = brief('cinecode', 'variety-captions')
        with self.assertRaisesRegex(ValueError, 'material branch'):
            native.validate_brief(json.dumps(b))
        b['cinecode_material_branch'] = 'drawn'
        self.assertEqual(native.validate_brief(json.dumps(b))['cinecode_material_branch'], 'drawn')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            self.assertEqual(native._cinecode_caption_material(root, b), set())
            b['cinecode_material_branch'] = 'video'
            with self.assertRaisesRegex(ValueError, 'requires approved materials'):
                native.validate_brief(json.dumps(b))
            input_file = root / 'approved.mp4'
            input_file.write_bytes(b'material fixture')
            descriptor = native.descriptor(root, input_file)
            b['materials'] = [descriptor]
            frame = {'codec_type': 'video', 'width': 10, 'height': 10}
            video = {'streams': [frame], 'format': {'format_name': 'mov,mp4', 'duration': '2.000000'}}
            photo = {'streams': [frame], 'format': {'format_name': 'jpeg_pipe'}}
            with mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, json.dumps(photo), '')):
                with self.assertRaisesRegex(ValueError, 'actual approved video'):
                    native._cinecode_caption_material(root, b)
            for branch, stream, destination in [('video', video, 'video'), ('photo', photo, 'image')]:
                with self.subTest(branch=branch):
                    b['cinecode_material_branch'] = branch
                    with mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess(
                            [], 0, json.dumps(stream), '')):
                        matching = native._cinecode_caption_material(root, b)
                    with self.assertRaisesRegex(ValueError, 'load a local copy'):
                        native._verify_cinecode_caption_material(b, [{'file': descriptor, 'destinations': ['empty']}], matching)
                    native._verify_cinecode_caption_material(b, [{'file': descriptor, 'destinations': [destination]}], matching)

    def test_only_explicit_original_action_budgets_are_enforced(self):
        b=brief('video-shotcraft','ink-press')
        def clock(frames):
            b['composition']['frames']=frames;b['source_binding']['end']=frames/24
            b['word_anchors'][0]['end']=frames/24
            native.validate_brief(json.dumps(b))
        clock(144)
        native._template(b)  # The full-template demo duration is not a hard minimum.
        for template, below, enough in [('spotlight-hero-card',95,96),('basic-3d-scene',163,164)]:
            b['template_id']=template;clock(below)
            with self.assertRaisesRegex(ValueError,'duration|budget'):
                native._template(b)
            clock(enough);native._template(b)
        b['template_id']='chart-live-moves';clock(24)
        with self.assertRaisesRegex(ValueError,'duration|budget'):
            native._template(b)
        clock(29);native._template(b)

    def test_shotcraft_primary_requires_a_narrative_variant_and_keeps_internal_components(self):
        rows=native.load_template_catalog(dependency_id='video-shotcraft')
        self.assertEqual(len(rows),125)
        cards={row['candidate_id'].rsplit('/',1)[-1]:row for row in rows}
        self.assertEqual(cards['basic-3d-scene']['native_role'],'scene')
        self.assertEqual(cards['basic-3d-scene']['uses'],['broll','component'])
        self.assertEqual(cards['collab-cursor-moves']['uses'],['component'])
        b=brief('video-shotcraft','glow-flyline-moves')
        for options in ([],['glow-orb-ambient']):
            b['native_options']=options
            with self.assertRaisesRegex(ValueError,'narrative variant'):
                native._template(b)
        for options in (['flyline-arc'],['orb-flyline-relay'],['glow-orb-ambient','flyline-arc']):
            b['native_options']=options
            native._template(b)
        b=brief('video-shotcraft','collab-cursor-moves');b['native_options']=['cast-ensemble']
        with self.assertRaisesRegex(ValueError,'cannot be the primary'):
            native._template(b)
        # A real frozen main scene can still use collaboration cursors internally.
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);source=root/'Scene.tsx';source.write_text('// current main content and collaboration layer')
            ref=native.descriptor(root,source)
            main=brief('video-shotcraft','glow-flyline-moves');main['native_options']=['flyline-arc']
            usage=[{'card_id':card,'variant':variant,'purpose':'本期真实画布中的主叙事或协作氛围层',
                    'implementation_refs':[ref]} for card,variant in
                   [('glow-flyline-moves','flyline-arc'),('collab-cursor-moves','cast-ensemble')]]
            native._validate_native_usage(root,main,{'project_files':[ref]},usage)

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
                  '--codec=h264','--pixel-format=yuv420p','--color-space=bt709','--image-format=png','--muted','--concurrency=1','--browser-executable=/native/chrome','--bundle-cache=false']
            _,script,output=native._render_command(root,request,argv,runtime)
            self.assertEqual(script,cli);self.assertEqual(output,project/'out/native.mp4')
            with self.assertRaisesRegex(ValueError,'pinned Remotion'):
                native._render_command(root,request,argv[:-1],runtime)
            argv[12]='--browser-executable=/other/chrome'
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

    def test_scheduled_native_task_defers_browser_and_blender_checks(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); request = root / 'brief.json'
            for dependency, template in [('barty-motion-graphics', 'motion-broll'), ('mg-styles-15', '3d-render')]:
                payload = brief(dependency, template); request.write_text(json.dumps(payload))
                with mock.patch.object(native, '_inputs'), \
                     mock.patch('motion_native_runtime.check', side_effect=AssertionError('browser probe')), \
                     mock.patch('motion_native_runtime.check_template_dependencies', side_effect=AssertionError('Blender probe')):
                    action = native.native_task(SimpleNamespace(job_dir=root, job_id=payload['job_id']),
                        {'segment_id': 'seg-001'}, {'component_id': 'scene', 'brief_sha256': native.sha(request)},
                        request, approved_task_source=payload['task_source'], defer_runtime=True)
                self.assertEqual(action['runtime']['status'], 'pending')
                self.assertIn('--check', action['runtime']['check_argv'])
                self.assertEqual(action['native_preparation_runtime']['prepare_argv'][-1], template)
                self.assertEqual(action['task_source'], payload['task_source'])

    def test_new_native_tasks_receive_only_their_own_workflow(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);request=root/'brief.json'
            for dependency,template in [('mg-styles-15','flat-vector'),('video-shotcraft','spotlight-hero-card'),('bb-video','whiteboard')]:
                b=brief(dependency,template)
                if dependency == 'video-shotcraft':
                    b['composition']['frames']=96;b['source_binding']['end']=4;b['word_anchors'][0]['end']=4
                request.write_text(json.dumps(b))
                with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                    action=native.native_task(SimpleNamespace(job_dir=root,job_id=b['job_id']),
                        {'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(request)},request,
                        approved_task_source=b['task_source'])
                self.assertNotIn('engine/build.py',action['next'])
                self.assertNotIn('quarter_turn_cw',action['next'])
                self.assertNotIn('export-frames.mjs',action['next'])
                self.assertIn({'mg-styles-15':'harness/render.mjs','video-shotcraft':'@remotion/cli',
                               'bb-video':'explainer/scripts/render.mjs'}[dependency],action['next'])
                if dependency == 'video-shotcraft':
                    self.assertEqual(len(action['native_catalog']),125)
                    self.assertIn('complementary cards',action['next'])

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
                     mock.patch.object(native,'_run_native_process',side_effect=render),mock.patch.object(native,'probe',return_value=b['composition']):
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
                 mock.patch.object(native,'_run_native_process',side_effect=render), \
                 mock.patch.object(native,'probe',side_effect=ValueError('wrong output pixel format')):
                with self.assertRaisesRegex(ValueError,'pixel format'):
                    native.capture_render(root,request,argv)
            call=json.loads((root/'native-inputs/native-test/result.render-call.json').read_bytes())
            self.assertEqual(call['stdout'],'original renderer stdout')
            self.assertEqual(call['exit_code'],0)
            self.assertEqual(call['artifact_check_error'],'wrong output pixel format')
            self.assertNotIn('media',call)

    def test_start_failure_timeout_and_source_change_retain_the_started_call(self):
        runtime={'tools':{'node':'/usr/bin/node'},'node_modules':'/unused',
                 'renderer_version':'playwright-1.64.0','runtime_identity':{},'environment':{}}
        for failure in ('start', 'timeout', 'source', 'cache'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as name:
                root=Path(name).resolve();b=brief();project=root/b['project_directory'];project.mkdir(parents=True)
                html=project/'page.html';html.write_text('<html/>')
                request=root/'brief.json';request.write_text(json.dumps(b))
                script=native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'
                record=root/'native-inputs/native-test/result.render-call.json'
                def render(*args,**kwargs):
                    self.assertEqual(json.loads(record.read_bytes())['status'],'running')
                    if failure=='start': raise OSError('cannot start native renderer')
                    if failure=='timeout':
                        raise subprocess.TimeoutExpired(args[0],1200,output=b'partial stdout',stderr=b'partial stderr')
                    if failure=='source':
                        html.write_text('<html>changed during native execution</html>')
                    else:
                        cache=project/'.cache/webpack/probe.pack';cache.parent.mkdir(parents=True)
                        cache.write_bytes(b'generated build cache')
                    return subprocess.CompletedProcess(args[0],0,'render stdout','render stderr')
                with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value=runtime), \
                     mock.patch.object(native,'_run_native_process',side_effect=render) as execute:
                    with self.assertRaises((OSError,subprocess.TimeoutExpired,ValueError)):
                        native.capture_render(root,request,['/usr/bin/node',str(script),'page.html','out/native.mp4','24'])
                self.assertEqual(execute.call_count,1)
                saved=json.loads(record.read_bytes());self.assertEqual(saved['status'],'failed')
                self.assertIn('error_type',saved);self.assertNotIn('media',saved)
                if failure=='timeout':
                    self.assertEqual(saved['stdout'],'partial stdout');self.assertEqual(saved['stderr'],'partial stderr')
                if failure=='source':
                    self.assertEqual(saved['source_changes']['changed'][0]['after']['job_path'],
                                     'native-projects/native-test/page.html')
                if failure=='cache':
                    self.assertEqual(saved['source_changes']['added'][0]['job_path'],
                                     'native-projects/native-test/.cache/webpack/probe.pack')
                    self.assertIn('project_files_after',saved)

    def test_timeout_stops_native_parent_and_detached_child_without_retry(self):
        command = [sys.executable, '-c',
            "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
            "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            "print('child='+str(p.pid),flush=True);time.sleep(30)"]
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            native._run_native_process(command,timeout=.5)
        self.assertIn('child=',raised.exception.stdout)
        pid=raised.exception.stdout.strip().split('child=')[1]
        status=subprocess.run(['ps','-p',pid,'-o','stat='],capture_output=True,text=True)
        self.assertTrue(status.returncode or status.stdout.strip().startswith('Z'),status.stdout)

    def test_3d_preparation_freezes_real_declared_assets_and_rejects_other_source_changes(self):
        from PIL import Image
        for scenario in ('complete','undeclared','missing'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as name:
                root=Path(name).resolve();b=brief('mg-styles-15','3d-render')
                b['composition']['frames']=2;b['source_binding']['end']=2/24;b['word_anchors'][0]['end']=2/24
                project=root/b['project_directory'];(project/'blender').mkdir(parents=True)
                (project/'scene').mkdir();(project/'harness').mkdir();(project/'assets').mkdir()
                source=project/'blender/scene.py';source.write_text('# actual current task Blender scene')
                (project/'scene/index.html').write_text('<img src="/assets/frames/0000.png">')
                shutil.copyfile(native.source_root(dependency_id='mg-styles-15')/'harness/render.mjs',project/'harness/render.mjs')
                modules=root/'modules';modules.mkdir();(project/'node_modules').symlink_to(modules,target_is_directory=True)
                runtime={'tools':{'node':'/tools/node'},'node_modules':str(modules),'renderer_version':'puppeteer-core-25.12.0',
                         'runtime_identity':{},'environment':{}}
                blender={'status':'ready','blender':'/missing/historical/blender','version':[5,1,2],
                         'cycles':True,'executable_sha256':'b'*64}
                outputs=[project/'assets/scene.blend',project/'assets/0000.png',project/'assets/0001.png']
                preparation={'argv':[blender['blender'],'--background','--factory-startup','--python','blender/scene.py'],
                    'inputs':[source.relative_to(root).as_posix()],
                    'outputs':[item.relative_to(root).as_posix() for item in outputs]}
                request=root/'brief.json';request.write_text(json.dumps(b))
                argv=['/tools/node','harness/render.mjs','scene','--out','out/native.mp4','--w','1080','--h','1920',
                      '--fps','24','--duration',str(2/24),'--workers','1','--noaudio']
                def execute(command,**kwargs):
                    if command[0]==blender['blender']:
                        outputs[0].write_bytes(b'actual generated blend scene')
                        for output in outputs[1:]:Image.new('RGB',(1080,1920),'pink').save(output)
                        if scenario=='undeclared':(project/'unexpected.py').write_text('# changed native inputs')
                    else:(project/'out/native.mp4').write_bytes(b'actual native final output')
                    return subprocess.CompletedProcess(command,0,'native real execution stdout','')
                with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value=runtime), \
                     mock.patch('motion_native_runtime.check_template_dependencies',return_value=blender), \
                     mock.patch.object(native,'_run_native_process',side_effect=execute) as process, \
                     mock.patch.object(native,'probe',return_value=b['composition']):
                    if scenario=='complete':
                        call=native.capture_render(root,request,argv,native_preparations=[preparation])
                        record=json.loads(call.read_bytes());self.assertEqual(process.call_count,2)
                        self.assertEqual(record['native_preparations'][0]['status'],'completed')
                        native._verify_native_preparations(root,b,record)  # The old Blender path does not exist.
                        outputs[1].write_bytes(b'later replacement')
                        with self.assertRaisesRegex(ValueError,'changed'):
                            native._verify_native_preparations(root,b,record)
                    else:
                        with self.assertRaisesRegex(ValueError,'undeclared|actual recorded Blender'):
                            native.capture_render(root,request,argv,native_preparations=None if scenario=='missing' else [preparation])
                        record=json.loads((root/b['result_record_path']).with_suffix('.render-call.json').read_bytes())
                        self.assertEqual(record['status'],'failed');self.assertNotIn('media',record)
                        self.assertEqual(process.call_count,1 if scenario=='undeclared' else 0)

    def test_frozen_3d_inputs_verify_in_an_isolated_python_without_pillow(self):
        import struct
        import zlib
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief('mg-styles-15','3d-render');b['composition']['frames']=1
            project=root/b['project_directory'];(project/'blender').mkdir(parents=True);(project/'assets').mkdir()
            source=project/'blender/scene.py';source.write_text('# frozen current-task Blender script')
            authored=native.project_files(root,project)
            blend=project/'assets/scene.blend';blend.write_bytes(b'frozen generated scene')
            frame=project/'assets/0000.png'
            def chunk(kind,data):
                return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
            pixels=(b'\x00'+b'\xcc\xba\xda'*1080)*1920
            frame.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1080,1920,8,2,0,0,0))
                +chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))
            outputs=[native.descriptor(root,item) for item in (blend,frame)]
            record={'authored_project_files':authored,'project_files':native.project_files(root,project),
                'native_preparations':[{'status':'completed','exit_code':0,
                    'argv':['/missing/historical/blender','--background','--python','blender/scene.py'],
                    'runtime_identity':{'blender':'/missing/historical/blender','version':[5,1,2],
                        'cycles':True,'executable_sha256':'b'*64},
                    'inputs':[native.descriptor(root,source)],'outputs':outputs,
                    'expected_outputs':[item['job_path'] for item in outputs]}]}
            request=root/'brief.json';request.write_text(json.dumps(b))
            call=root/'call.json';call.write_text(json.dumps(record))
            program=("import sys,json,importlib.util;from pathlib import Path;"
                "sys.path[:0]=sys.argv[1:3];assert importlib.util.find_spec('PIL') is None;"
                "import motion_native_skill_adapter as n;r=Path(sys.argv[3]);"
                "n._verify_native_preparations(r,json.loads((r/'brief.json').read_bytes()),"
                "json.loads((r/'call.json').read_bytes()));print('verified without Pillow')")
            result=subprocess.run([sys.executable,'-I','-S','-c',program,str(_env.PROJECT),str(_env.SKILL/'scripts'),str(root)],
                capture_output=True,text=True,timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('verified without Pillow',result.stdout)

    def test_shotcraft_reuse_keeps_frozen_sources_without_the_old_runtime(self):
        import motion_native_runtime as runtime_module
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief('video-shotcraft','spotlight-hero-card')
            b['composition']['frames']=96;b['source_binding']['end']=4;b['word_anchors'][0]['end']=4
            project=root/b['project_directory'];(project/'src').mkdir(parents=True)
            (project/'src/index.ts').write_text('// current task composition')
            (project/'node_modules').symlink_to('/historical/missing/runtime',target_is_directory=True)
            output=project/'out/native.mp4';output.parent.mkdir();output.write_bytes(b'reviewed video')
            tools={'node':'/historical/node','ffmpeg':'/historical/ffmpeg','ffprobe':'/historical/ffprobe'}
            versions={'node':'v22.12.0','ffmpeg':'ffmpeg old recorded version','ffprobe':'ffprobe old recorded version'}
            runtime={'tools':tools,'node_modules':'/historical/missing/runtime','renderer_version':'remotion-4.0.484'}
            identity={'schema_version':1,'dependency_id':'video-shotcraft','renderer_version':runtime['renderer_version'],
                'lock_sha256':native.sha(runtime_module.locked_files(_env.PROJECT,'video-shotcraft')['package-lock.json']),
                'tools':{key:{'path':value,'version':versions[key]} for key,value in tools.items()},
                'browser':{'path':'/historical/missing/chrome','version':'recorded Chrome version'}}
            argv=[tools['node'],runtime['node_modules']+'/@remotion/cli/remotion-cli.js','render','src/index.ts',
                'NativeScene','out/native.mp4','--codec=h264','--pixel-format=yuv420p','--color-space=bt709',
                '--image-format=png','--muted','--concurrency=1','--browser-executable='+identity['browser']['path']]
            payload=json.dumps(b).encode()
            call={'exit_code':0,'dependency_id':b['dependency_id'],'request_sha256':hashlib.sha256(payload).hexdigest(),
                'upstream_commit':native.SOURCES[b['dependency_id']][1],'native_script_sha256':'b'*64,
                'argv':argv,'renderer_version':runtime['renderer_version'],'runtime_identity':identity,
                'execution_runtime':runtime,'media':native.descriptor(root,output),
                'project_files':native.project_files(root,project)}
            with mock.patch('motion_native_runtime.check',return_value={}) as check, \
                 mock.patch.object(native,'probe',return_value=b['composition']):
                native._verify_call(root,b,payload,call)
                check.assert_called_once_with(_env.PROJECT,dependency_id='video-shotcraft',mode='reuse')
                call['status']='failed'
                with self.assertRaisesRegex(ValueError,'does not match'):
                    native._verify_call(root,b,payload,call)
                call['status']='completed'
                (project/'src/index.ts').write_text('// changed source')
                with self.assertRaisesRegex(ValueError,'changed'):
                    native._verify_call(root,b,payload,call)

    def test_shotcraft_publication_freezes_actual_native_components_and_required_primary(self):
        rows=native.load_template_catalog(dependency_id='video-shotcraft')
        main=next(row for row in rows if row['candidate_id'].endswith('/spotlight-hero-card'))
        component=next(row for row in rows if row['native_template_group']=='camera')
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();b=brief('video-shotcraft','spotlight-hero-card')
            b['composition']['frames']=720;b['source_binding']['end']=30
            b['native_options']=[main['styles'][0]['key']]
            project=root/b['project_directory'];(project/'src').mkdir(parents=True)
            source=project/'src/Scene.tsx';source.write_text('// actual current-task implementation')
            call={'project_files':native.project_files(root,project),'renderer_version':'remotion-4.0.484',
                  'media':{'job_path':'native-projects/native-test/out/native.mp4','sha256':'c'*64,'byte_count':1}}
            callpath=root/'render-call.json';callpath.write_text(json.dumps(call))
            request=root/'brief.json';request.write_text(json.dumps(b))
            usage=[{'card_id':row['candidate_id'].rsplit('/',1)[-1],'variant':row['styles'][0]['key'],
                    'purpose':'本期原生制作中的实际主镜头或辅助运镜','implementation_refs':[native.descriptor(root,source)]}
                   for row in (main,component)]
            with mock.patch.object(native,'_inputs'),mock.patch.object(native,'_verify_call'):
                with self.assertRaisesRegex(ValueError,'actual native'):
                    native.publish_completed(root,request,callpath)
                result=native.publish_completed(root,request,callpath,native_usage=usage)
                saved=json.loads(result.read_bytes());self.assertEqual(saved['schema_version'],3)
                self.assertEqual(saved['native_usage'],usage)
                self.assertEqual(native.inspect_result(root,request.read_bytes())['native_usage'],usage)
                with self.assertRaisesRegex(ValueError,'primary'):
                    native._validate_native_usage(root,b,call,usage[1:])
                invalid=[{**usage[0],'variant':'invented-variant'}]
                with self.assertRaisesRegex(ValueError,'original card'):
                    native._validate_native_usage(root,b,call,invalid)
                source.write_text('// later replacement')
                with self.assertRaisesRegex(ValueError,'changed'):
                    native.inspect_result(root,request.read_bytes())

    def test_reviewed_record_and_actual_media_must_both_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/brief()['result_record_path'];p.parent.mkdir(parents=True);p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'frozen version'):
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


class NativeExecutionIdentityTests(unittest.TestCase):
    def test_all_four_factories_keep_the_absolute_python_alias(self):
        import talkcraft_skill_adapter as talkcraft
        import lemo_wake_adapter as wake
        import upstream_scene_adapter as upstream
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); bin_dir = root / 'bin'; bin_dir.mkdir()
            alias = bin_dir / 'python'; alias.symlink_to(Path(sys.executable).resolve())
            parent_alias = root / 'linked-bin'; parent_alias.symlink_to(bin_dir, target_is_directory=True)
            supplied = parent_alias / 'python'
            with mock.patch.object(native, 'source_root'), \
                 mock.patch('motion_native_runtime.check', return_value={}), \
                 mock.patch.object(talkcraft, 'source_root'), \
                 mock.patch('prepare_talkcraft_native.check', return_value={'renderer_version': 'fixture'}), \
                 mock.patch.object(wake, 'source_root'), \
                 mock.patch.object(upstream, 'check_runtime', return_value={'commit': upstream.SOURCES['onetake'][0]}):
                adapters = [native.create_adapter(_env.PROJECT, supplied, lambda *_: b'{}', dependency_id='bb-video', renderer_version='fixture'),
                            talkcraft.create_adapter(_env.PROJECT, supplied, lambda *_: b'{}'),
                            wake.create_adapter(_env.PROJECT, supplied, lambda *_: b'{}'),
                            upstream.create_adapter(_env.PROJECT, 'onetake', supplied, lambda *_: b'{}')]
            for adapter in adapters:
                with self.subTest(adapter=adapter.adapter_id):
                    self.assertEqual(adapter.launcher, alias)
                    self.assertNotEqual(adapter.launcher, alias.resolve())
                    self.assertEqual(adapter.launcher_sha256, native.sha(alias.resolve()))

    def test_api_and_cli_reject_wrong_parent_python_before_native_or_file_work(self):
        from edit.hd.tools import startup, state
        import talkcraft_skill_adapter as talkcraft
        import lemo_wake_adapter as wake
        import upstream_scene_adapter as upstream
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video = root / 'source.mp4'; video.write_bytes(b'video')
            script = root / 'script.txt'; script.write_text('script')
            job = state.create_job(root, video, script, profile='full-v2')
            runtime = startup.runtime_identity(_env.PROJECT)
            runtime['python']['version'] = '0.0.0'
            context = {'workspace': str(root), 'job_dir': str(job.job_dir), 'job_id': job.job_id,
                       'project_root': str(_env.PROJECT), 'runtime': runtime}
            (root / 'job-context.json').write_text(json.dumps(context))
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob('*'))
            with mock.patch.object(native, '_inputs') as inputs, \
                 mock.patch.object(native, '_run_native_process') as render, \
                 mock.patch.object(native.artifacts, 'write_json_artifact') as write:
                for operation in (
                    lambda: native.capture_render(job.job_dir, root / 'missing.json', []),
                    lambda: native.publish_completed(job.job_dir, root / 'missing.json', root / 'missing-call.json'),
                    lambda: talkcraft.capture_render(job.job_dir, root / 'missing.json', []),
                    lambda: talkcraft.publish_completed(job.job_dir, root / 'missing.json', root / 'missing-call.json'),
                    lambda: wake.initialize_project(job.job_dir, root / 'missing.json', slug='fixture'),
                    lambda: wake.capture_call(job.job_dir, root / 'missing.json', 'render', [], root),
                    lambda: wake.publish_completed(job.job_dir, root / 'missing.json', root, root / 'missing.mp4', root / 'qa.json', []),
                    lambda: wake.prepare_revision(job.job_dir, root / 'missing.json', reason='fixture'),
                    lambda: upstream.run_native({}, root, {}, job_dir=job.job_dir),
                ):
                    with self.assertRaisesRegex(state.WorkflowError, 'runtime changed'):
                        operation()
                inputs.assert_not_called(); render.assert_not_called(); write.assert_not_called()
            for action in ('--capture-render', '--publish'):
                result = subprocess.run([sys.executable, str(_env.PROJECT / native.ENTRY),
                    '--dependency-id', 'bb-video', '--job-dir', str(job.job_dir), action,
                    '--brief', str(root / 'missing.json'), '--argv-json', '[]'], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('runtime changed', result.stderr)
            for module, actions in ((talkcraft, ('--capture-render', '--publish')),
                                    (wake, ('--initialize', '--publish')),
                                    (upstream, ('--output',))):
                for action in actions:
                    arguments = [action, str(root / 'missing-output.mp4')] if action == '--output' else [action]
                    result = subprocess.run([sys.executable, str(_env.PROJECT / module.ENTRY),
                        '--job-dir', str(job.job_dir), '--brief', str(root / 'missing.json'), *arguments,
                        *(['--argv-json', '[]'] if action == '--capture-render' else [])], capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('runtime changed', result.stderr)
            self.assertEqual(sorted(path.relative_to(root).as_posix() for path in root.rglob('*')), before)

    def test_missing_job_and_other_job_brief_cannot_render_or_publish(self):
        from edit.hd.tools import state
        from types import SimpleNamespace
        with self.assertRaisesRegex(state.WorkflowError, 'requires a Job'):
            native.capture_render(None, None, [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); request = root / 'brief.json'
            request.write_text(json.dumps(brief()))
            with mock.patch.object(native, '_execution_job', return_value=SimpleNamespace(job_id='other-job')), \
                 mock.patch.object(native, '_inputs') as inputs:
                for operation in (
                    lambda: native.capture_render(root, request, []),
                    lambda: native.publish_completed(root, request, root / 'missing-call'),
                ):
                    with self.assertRaisesRegex(ValueError, 'another Job'):
                        operation()
                inputs.assert_not_called()


if __name__=='__main__':unittest.main()

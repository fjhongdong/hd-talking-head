"""Wake native result -> formal executor, opening clock and semantic evidence."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from _env import PROJECT, SKILL
sys.path.insert(0, str(SKILL / 'scripts'))
import lemo_wake_adapter as wake
import run_stage
import broll_capability_router as router
from edit.hd.tools import broll_skill_selection, motion_capabilities, wake_opening, visual_plan, visual_strategy
from edit.hd.tests.test_visual_strategy import valid_intent, valid_strategy, strategy_component
from edit.hd.tests import test_broll_component_executor as fixture
from edit.hd.tools import broll_component_executor as executor
from edit.hd.tools import state, content_analysis, contract_artifacts as artifacts, visual_confirmation as confirmation, motion_match_cache
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tests.test_visual_direction import draft_segment

SAMPLE = SKILL / 'assets/wake-native-v2-smoke'

class WakeNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        shutil.copyfile(SAMPLE/'inputs/source.mp4',self.root/'source.mp4')
        shutil.copyfile(SAMPLE/'inputs/script.md',self.root/'script.md')
        self.job=state.create_job(self.root,self.root/'source.mp4',self.root/'script.md',profile='full-v2')
        shutil.copytree(SAMPLE,self.job.job_dir,dirs_exist_ok=True)
        self.payload=(self.job.job_dir/'native-inputs/brief.json').read_bytes()
        self.brief=wake.validate_brief(self.payload)
        self.assertEqual(self.job.job_id,self.brief['job_id'])
        script=(self.root/'script.md').read_text()
        def approve(stage,items):
            paths=[]
            for rel,data in items:
                f=self.job.job_dir/rel;f.parent.mkdir(parents=True,exist_ok=True)
                if data is not None:f.write_bytes(data)
                paths.append(f)
            state.mark_ready(self.job,stage,paths);state.approve(self.job,stage)
        approve('inspect',[('01-inspect/report.json',b'{"development_fixture":true}')])
        analysis={'thesis':script,'hook':'先按语义','sections':[{'id':'s1','title':'语义与模板','source_span':[0,len(script)]}],
            'items':[{'id':'idea-01','source_text':script,'source_span':[0,len(script)],'priority':'critical','keywords':['语义','模板'],
                      'semantic_type':'contrast','evidence_status':'supported','broll_priority':'high'}],'claims':[]}
        content_analysis.prepare_content_analysis(self.job,analysis);state.approve(self.job,'content_analysis')
        approve('cover_direction',[('03-cover-direction/cover-direction.json',b'{"development_fixture":true}')])
        approve('cover',[('04-cover/cover-report.json',b'{"development_fixture":true}'),('04-cover/cover-delivery-raster.png',None)])
        approve('speech_cleanup',[('05-speech-cleanup/word-transcript.json',json.dumps({'version':1,'words':[{'text':script,'start':0,'end':6}]}).encode())])
        approve('edit_structure',[('06-edit-structure/edit-plan.json',json.dumps({'canvas':{'width':1080,'height':1920,'fps':24}}).encode()),
            ('06-edit-structure/timeline-map.json',json.dumps({'output_duration':6,'segments':[{'source_start':0,'source_end':6,'timeline_start':0,'timeline_end':6}]}).encode()),
            ('06-edit-structure/edited-aroll.mp4',None)])

    def setup_component(self):
        adapter = wake.create_adapter(PROJECT, sys.executable, lambda *_: self.payload)
        binding = wake.create_binding(adapter, self.payload, SAMPLE / 'native-sample.mp4')
        c = fixture._code_component(self.payload, dependency_id='lemo-wake')
        c.update(binding)
        c['executor']='reference_adapter'
        c['render_window']['end_frame'] = 144
        c['artifact_contract']['alpha'] = False
        recipe = fixture._recipe([c]);recipe['segment_id'] = 'seg-001'
        recipe['composition']['presenter_mode'] = 'hidden'
        segment = {'segment_id': 'seg-001', 'start': 0, 'end': 6, 'shot_recipe': recipe}
        return adapter, c, recipe, segment

    def flow_draft(self):
        adapter=wake.create_adapter(PROJECT,sys.executable,lambda *_:self.payload)
        segment=draft_segment(('code_generated',),segment_id='seg-001',end=6)
        segment['visual_intent']['presenter_presence']='hidden'
        segment['visual_intent']['statement']=(self.root/'script.md').read_text()
        segment['visual_strategy']['composition']['presenter_mode']='hidden'
        segment['visual_strategy']['composition'].pop('avatar',None)
        segment['visual_strategy']['components'][0]['media_type']='animation'
        cid='component-1'
        segment['bindings'][cid]=wake.create_binding(adapter,self.payload,SAMPLE/'native-sample.mp4')
        director={'schema_version':3,'segments':[segment]}
        script=(self.root/'script.md').read_text()
        design={'composition':'原图整屏三行关系','typography':'保持原图中文完整','finish':'暖白纸面橙色轨迹','focus':'三行语义依次连接模板'}
        skills={r['skill_id'] for r in broll_skill_selection.discover_candidates(PROJECT)}
        selection={'schema_version':1,'opening':{'segment_id':'seg-001','component_id':cid,'candidate_id':'lemo-wake:wake'},
            'beats':[{'segment_id':'seg-001','component_id':cid,'semantic_row_id':'opening-semantic','start':0,'end':6,
                'transcript':script,'semantic_goal':'按语义选择模板','required_change':'原图关系依次运动连接',
                'intent_statement':segment['visual_intent']['statement'],'component_brief':segment['visual_strategy']['components'][0]['brief'],
                'binding_snapshot':copy.deepcopy(segment['bindings'][cid]),
                'skill_reviews':{skill:{'fit':'preferred' if skill=='lemo-wake' else 'unsuitable','reason':'该开场项按已确定首镜政策执行'} for skill in skills},
                'single_source_review':{'decision':'keep','reason':'已批准封面首镜固定使用完整原生Wake'},
                'candidates':[{'candidate_id':'lemo-wake:wake','fit':'preferred','reason':'按固定首镜政策演示原图关系','visual_pattern':'source_image_actor','design_plan':design}]}],
            'overlay_beats':[],'history_note':'独立开发样本，无历史视频','fixed_context':[],'recent_context':[]}
        treatment={'numbering_scope_id':'wake-v2-development','scenes':[{'segment_id':'seg-001','component_id':cid,'brief_path':'native-inputs/brief.json'}],
            'semantic_lists':{'overlay':[],'broll':[{'row_id':'opening-semantic','start_word':0,'end_word':1,'quote':script,'semantic':'按语义选择模板','visual_task':'批准封面整屏入场并展示三种对应关系','components':[{'segment_id':'seg-001','component_id':cid}]}]},
            'beat_sheet':[{'start_word':0,'end_word':1,'quote':script,'decision':'broll','visual':'三行关系依次连接','components':[{'segment_id':'seg-001','component_id':cid}],'reason':'开场语义由已批准封面原生动作演示'}],
            'motion_queries':[{'segment_id':'seg-001','component_id':cid,'tags':['展示已批准封面']}],
            'skill_selection':selection,'overlay_selection':[],'generation_plan':{'steps':[]},
            'semantic_assessments':[{'segment_id':'seg-001','component_id':cid,'candidate_id':'lemo-wake:wake','verdict':'pass','reason':'原图三行与口播语义对应，完整可读',
                'transcript_refs':[{'start_word':0,'end_word':1,'quote':script,'basis':'current_clause'}],
                'content_refs':[{'path':self.brief['image']['job_path'],'sha256':self.brief['image']['sha256'],'image':True}]}]}
        treatment=motion_match_cache.match_once(PROJECT,director,treatment)
        treatment['skill_selection']=broll_skill_selection.assign_skills(PROJECT,treatment['skill_selection'],job_dir=self.job.job_dir)
        native=wake.inspect_result(self.job.job_dir,self.payload)
        for item in native['project_files']:
            if item['job_path'].endswith(('/index.html','/DIRECTOR.md')):
                treatment['semantic_assessments'][0]['content_refs'].append({'path':item['job_path'],'sha256':item['sha256'],
                    'quote':(self.job.job_dir/item['job_path']).read_text().splitlines()[0]})
        treatment['semantic_assessments'][0]['content_refs'].append({'path':self.brief['result_record_path'],
            'sha256':wake.sha(self.job.job_dir/self.brief['result_record_path']),'pointer':'/status','value':'completed'})
        entry=next(f for f in native['project_files'] if f['job_path'].endswith('/index.html'))
        text=(self.job.job_dir/entry['job_path']).read_text();start=text.index('本地')
        treatment['motion_readability']=[{'segment_id':'seg-001','component_id':cid,'targets':[{'target_id':'wake-local-label',
            'content_ref':{'path':entry['job_path'],'sha256':entry['sha256'],'pointer':f'text:{start}:{start+2}','value':'本地'},
            'span':[0,2],'role':'title','region':{'x':384,'y':1138,'width':240,'height':136},'windows':[{'start':0,'end':6}]}]}]
        return director,treatment

    def test_native_result_reaches_public_executor_without_rerendering(self):
        director,treatment=self.flow_draft()
        approve_fixture_setup(self.job)
        artifacts.write_json_artifact(self.job.job_dir/'manifests/confirmed-content.json',{
            'schema_version':1,'job_id':self.job.job_id,
            'source_words':[{'index':0,'text':(self.root/'script.md').read_text()}],
            'visuals':[{'component_id':'component-1','composition_family':'single_full_frame','visible_text':[],
                'binding':director['segments'][0]['bindings']['component-1']}]})
        dpath=self.job.job_dir/'director.json';tpath=self.job.job_dir/'treatment.json'
        artifacts.write_json_artifact(dpath,director);artifacts.write_json_artifact(tpath,treatment)
        source=run_stage.run_visual_direction(self.job.job_dir,PROJECT,dpath,tpath)
        self.job=state.load_job(self.job.job_dir)
        review={k:copy.deepcopy(v) for k,v in run_stage._summary(self.job,'visual_direction').items()
                if k in {'job_id','job_dir','stage','revision','artifacts'}}
        review.update(passed=True,note='开发测试：核对该完整清单',user_confirmation='开发fixture授权，只用于代码验证')
        run_stage._review(self.job,'visual_direction',review)
        self.job=state.load_job(self.job.job_dir)
        result=wake.inspect_result(self.job.job_dir,self.payload)
        artifacts.write_json_artifact(tpath,treatment)
        run_stage.resume_visual_direction(self.job,PROJECT,{'realization':{'director_brief':'director.json','treatment':'treatment.json','host_qa_note':'开发测试已检查本次原生动画首中尾，文字完整、动作匹配'}})
        self.job=state.load_job(self.job.job_dir)
        adapters=run_stage.native_component_adapters(PROJECT,self.job)
        from edit.hd.tools import visual_canary
        plan=visual_canary.load_approved_visual_plan(self.job)
        from edit.hd.tools import material_usage
        receipt=material_usage.load_current_receipt(self.job,'visual_direction')
        self.assertEqual(receipt['references'],[])
        self.assertEqual(receipt['job_id'],self.job.job_id)
        recipe=plan['segments'][0]['shot_recipe'];component=recipe['components'][0]
        self.assertEqual(component['executor'],'reference_adapter');self.assertFalse(component['artifact_contract']['alpha'])
        artifact=executor.execute_component(self.job,executor.ComponentExecutionRequest(recipe=recipe,component_id='component-1'),
            adapters={**adapters,'artifact_probe':wake.create_artifact_probe(ffprobe_executable=shutil.which('ffprobe'))})
        self.assertEqual(artifact.status,'success')
        self.assertEqual(artifact.output_sha256,wake.sha(SAMPLE/'native-sample.mp4'))
        self.assertEqual(wake.probe(self.job.job_dir/artifact.job_path)['frames'],144)
        from edit.hd.tools import segment_render
        arroll=self.job.job_dir/'06-edit-structure/edited-aroll.mp4'
        rendered=segment_render.render_segment_video(self.job,plan['segments'][0],(artifact,),
            output_dir=self.job.job_dir/'development-render',
            visual_plan_sha256=wake.sha(self.job.job_dir/'07-visual-direction/visual-plan.json'),
            arroll_source=arroll,arroll_sha256=wake.sha(arroll),arroll_bytes=arroll.stat().st_size)
        self.assertEqual(rendered.frames,144)
        self.assertEqual(rendered.composition['presenter_mode'],'hidden')
        self.assertTrue((self.job.job_dir/rendered.video_path).is_file())
        expected=confirmation.native_result_descriptor(self.job,'seg-001','component-1',hashlib.sha256(self.payload).hexdigest())
        result_path=self.job.job_dir/expected['path']
        current=json.loads(result_path.read_bytes());current['unreviewed_note']='changed after review'
        result_path.write_text(json.dumps(current))
        with self.assertRaisesRegex(ValueError,'reviewed version'):
            wake.load_result(self.job.job_dir,self.payload,expected_record=expected)


    def draft(self):
        adapter, c, recipe, segment = self.setup_component()
        strategy=valid_strategy([strategy_component(component_id=c['component_id'], kind='code_generated')], segment_id='seg-001')
        strategy['composition']['presenter_mode']='hidden'
        intent=valid_intent(segment_id='seg-001',presenter_presence='hidden')
        visual_strategy.validate_visual_strategy(intent,strategy)
        segment.update(visual_intent=intent, visual_strategy=strategy,
            bindings={c['component_id']: wake.create_binding(adapter, self.payload, SAMPLE / 'native-sample.mp4')})
        treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': c['component_id'],
                               'brief_path': 'native-inputs/brief.json'}],
                     'skill_selection': {'opening': {'segment_id': 'seg-001',
                         'component_id': c['component_id'], 'candidate_id': 'lemo-wake:wake'}}}
        return {'segments': [segment]}, treatment

    def test_pending_native_handoff_and_completed_reuse(self):
        director, treatment = self.draft()
        self.assertEqual(run_stage.pending_native_actions(self.job, director, treatment), [])
        (self.job.job_dir / self.brief['result_record_path']).unlink()
        with mock.patch('edit.hd.tools.motion_capabilities._approved_speech',return_value=[{'text':'先按语义','start':0,'end':6}]):
            action, = run_stage.pending_native_actions(self.job, director, treatment)
        self.assertEqual(action['action'], 'execute_native_skill')
        self.assertTrue(Path(action['skill_path']).is_file())
        self.assertEqual(action['requirements']['frames'], 144)
        self.assertTrue(action['requirements']['silent'])
        self.assertEqual(action['requirements']['parent_subtitle_layout']['safe_zones']['subtitle'],
                         {'x':80,'y':1430,'width':920,'height':230})
        self.assertEqual(action['requirements']['transcript'],'先按语义')
        self.assertNotIn('complete_source_first_frame', action['requirements'])
        self.assertTrue(action['requirements']['single_pass'])

    def test_revision_preserves_completed_work_and_dispatches_only_new_request(self):
        director, treatment = self.draft()
        old_brief = self.job.job_dir / 'native-inputs/brief.json'
        old_result = self.job.job_dir / self.brief['result_record_path']
        completed = wake.inspect_result(self.job.job_dir, self.payload)
        preserved = {item['job_path']: (self.job.job_dir / item['job_path']).read_bytes()
                     for item in completed['project_files']}
        preserved.update({str(p.relative_to(self.job.job_dir)): p.read_bytes()
                          for p in (old_brief, old_result, self.job.job_dir / completed['media']['job_path'])})
        result = wake.prepare_revision(self.job.job_dir, old_brief, reason='开场整幅不动，需要原生重新规划完整运动')
        self.assertEqual(result['action'], 'rebind_native_revision')
        self.assertNotIn('skill_path', result)
        self.assertEqual(state.load_job(self.job.job_dir).stages['visual_direction']['status'], 'needs_revision')
        new_brief = self.job.job_dir / result['brief_path']
        revised = wake.validate_brief(new_brief.read_bytes())
        self.assertEqual(revised['revision']['previous_media'], completed['media'])
        self.assertNotEqual(revised['result_record_path'], self.brief['result_record_path'])
        self.assertFalse((self.job.job_dir / revised['result_record_path']).exists())
        self.assertFalse((self.job.job_dir / result['project_parent']).exists())
        self.assertEqual(run_stage.pending_native_actions(self.job, director, treatment), [])
        treatment['scenes'][0]['brief_path'] = result['brief_path']
        binding = director['segments'][0]['bindings']['code']
        binding['brief_sha256'] = result['brief_sha256']
        with mock.patch('edit.hd.tools.motion_capabilities._approved_speech', return_value=[{'text':'先按语义','start':0,'end':6}]):
            action, = run_stage.pending_native_actions(self.job, director, treatment)
        self.assertEqual(action['result_record_path'], result['result_record_path'])
        self.assertEqual(action['project_parent'], result['project_parent'])
        self.assertEqual(action['revision_context']['reason'], revised['revision']['reason'])
        old_src = (self.job.job_dir / next(item['job_path'] for item in completed['project_files']
                                          if item['job_path'].endswith('/index.html'))).parent
        native_root = wake.source_root()
        native_render = str(native_root / 'skills/wake/scripts/render.mjs')
        with mock.patch.object(wake, 'source_root', return_value=native_root), \
             mock.patch.object(wake.subprocess, 'run') as call:
            with self.assertRaisesRegex(ValueError, 'new native project'):
                wake.capture_call(self.job.job_dir, new_brief, 'render',
                                  ['node', native_render, str(old_src), 'frames'], old_src)
            call.assert_not_called()
        new_result = self.job.job_dir / result['result_record_path']
        new_result.write_bytes(old_result.read_bytes())
        with self.assertRaisesRegex(ValueError, 'approved request or clock'):
            run_stage.pending_native_actions(self.job, director, treatment)
        for relative, data in preserved.items():
            self.assertEqual((self.job.job_dir / relative).read_bytes(), data)

    def test_revision_failure_does_not_advance_state_or_report_success(self):
        old_brief = self.job.job_dir / 'native-inputs/brief.json'
        previous_revision = self.job.revision
        with mock.patch.object(wake.artifacts, 'write_json_artifact', side_effect=OSError('write failed')), \
             mock.patch.object(state, 'revise') as revise:
            with self.assertRaisesRegex(OSError, 'write failed'):
                wake.prepare_revision(self.job.job_dir, old_brief, reason='调整完整运动')
            revise.assert_not_called()
        self.assertEqual(state.load_job(self.job.job_dir).revision, previous_revision)
        with mock.patch.object(state, 'revise', side_effect=state.WorkflowError('revision failed')):
            with self.assertRaisesRegex(state.WorkflowError, 'revision failed'):
                wake.prepare_revision(self.job.job_dir, old_brief, reason='调整完整运动')
        self.assertEqual(state.load_job(self.job.job_dir).revision, previous_revision)

    def test_approved_cover_and_first_clock_are_mandatory(self):
        director, treatment = self.draft()
        cover = self.job.job_dir / '04-cover/cover-delivery-raster.png'
        cover.parent.mkdir(exist_ok=True)
        b = copy.deepcopy(self.brief);b['image'] = wake.descriptor(self.job.job_dir, cover)
        raw = json.dumps(b).encode();brief_path=self.job.job_dir/'native-inputs/brief.json';brief_path.write_bytes(raw)
        binding=director['segments'][0]['bindings']['code'];binding['brief_sha256']=hashlib.sha256(raw).hexdigest()
        self.job.stages={'cover': {'status':'approved','artifacts':[{'path':str(cover.relative_to(self.job.job_dir)),
            'sha256':wake.sha(cover),'bytes':cover.stat().st_size}]}}
        self.assertEqual(wake_opening.validate(self.job,director,treatment)['candidate_id'],'lemo-wake:wake')
        for mutate in (lambda d: d['segments'][0].update(start=.5),
                       lambda d: d['segments'][0]['visual_strategy']['composition'].update(avatar={}),
                       lambda d: d['segments'][0]['visual_strategy']['composition'].update(presenter_mode='bottom_window')):
            changed=copy.deepcopy(director);mutate(changed)
            with self.assertRaises(ValueError):wake_opening.validate(self.job,changed,treatment)
        self.job.stages['cover']['status']='pending'
        with self.assertRaises(visual_plan.VisualPlanError):wake_opening.validate(self.job,director,treatment)
        (self.job.root/'job-context.json').write_text('{}')
        with self.assertRaises(ValueError):wake_opening.validate(self.job,director,{'skill_selection':{}})

    def test_semantic_evidence_requires_actual_image_then_actual_project(self):
        director,treatment=self.draft();segment=director['segments'][0]
        row={'candidate_id':'lemo-wake:wake','dependency_id':'lemo-wake','capability':{'capability_type':'creative_skill'}}
        image={'path':'04-cover/cover-delivery-raster.png','sha256':self.brief['image']['sha256'],'image':True}
        assessment={'segment_id':'seg-001','component_id':'code','candidate_id':'lemo-wake:wake',
            'verdict':'pass','reason':'图中三种语义逐行连接，对应口播。',
            'transcript_refs':[{'start_word':0,'end_word':1,'quote':'先按语义','basis':'current_clause'}], 'content_refs':[image]}
        treatment['semantic_assessments']=[assessment]
        speech=[{'text':'先按语义','start':0,'end':6}]
        def check(b):return motion_capabilities._semantic_assessment(self.job.job_dir,treatment,segment,'code',row,speech,b)
        self.assertEqual(check(self.brief)['status'],'pass')
        assessment['content_refs']=[]
        self.assertNotEqual(check(self.brief)['status'],'pass')
        assessment['content_refs']=[image]
        enriched=motion_capabilities._bound_brief(self.job.job_dir,treatment,segment,'code')
        self.assertIn('native_result',enriched)
        self.assertNotEqual(check(enriched)['status'],'pass')
        for d in (enriched['native_result']['entry'],enriched['native_result']['director']):
            assessment['content_refs'].append({'path':d['job_path'],'sha256':d['sha256'],
                'quote':(self.job.job_dir/d['job_path']).read_text().splitlines()[0]})
        d=enriched['native_result']['record']
        assessment['content_refs'].append({'path':d['job_path'],'sha256':d['sha256'],'pointer':'/status','value':'completed'})
        self.assertEqual(check(enriched)['status'],'pass')

    def test_wrong_native_output_or_clock_is_rejected(self):
        self.assertEqual(wake.inspect_result(self.job.job_dir,self.payload)['status'],'completed')
        result=self.job.job_dir/self.brief['result_record_path'];r=json.loads(result.read_bytes());r['media_probe']['frames']=143
        result.write_text(json.dumps(r))
        with self.assertRaises(ValueError):wake.inspect_result(self.job.job_dir,self.payload)
        b=copy.deepcopy(self.brief);b['composition']['frames']=143
        with self.assertRaises(ValueError):wake.validate_brief(json.dumps(b))

    def test_reviewed_result_and_normalized_source_cannot_be_replaced(self):
        result_path=self.job.job_dir/self.brief['result_record_path']
        reviewed=wake.sha(result_path)
        treatment={'semantic_assessments':[{'segment_id':'seg-001','component_id':'code',
            'candidate_id':'lemo-wake:wake','verdict':'pass','content_refs':[{
                'path':self.brief['result_record_path'],'sha256':reviewed,'pointer':'/status','value':'completed'}]}]}
        frozen=confirmation._freeze_reviewed_native_result(self.job.job_dir,treatment,'seg-001','code',self.payload,'lemo-wake')
        self.assertEqual(frozen['sha256'],reviewed)
        data=result_path.read_bytes();result_path.write_bytes(data+b'\n')
        with self.assertRaisesRegex(ValueError,'host reviewed'):
            confirmation._freeze_reviewed_native_result(self.job.job_dir,treatment,'seg-001','code',self.payload,'lemo-wake')
        result_path.write_bytes(data)
        native=wake.inspect_result(self.job.job_dir,self.payload)
        source=next(f for f in native['project_files'] if '/assets/source.' in f['job_path'])
        (self.job.job_dir/source['job_path']).write_bytes(b'changed normalized source')
        with self.assertRaises(ValueError):wake.inspect_result(self.job.job_dir,self.payload)

    def test_selected_inputs_and_runtime_directory_are_checked_before_confirmation(self):
        director,treatment=self.draft()
        wake.validate_selected_inputs(self.job,director,treatment)
        environment=wake.runtime_environment()
        self.assertEqual(environment['LEMO_WAKE_MODELS'],str(PROJECT/'skill-development/runtime/lemo-wake/models'))
        (self.job.job_dir/self.brief['image']['job_path']).unlink()
        with self.assertRaises(FileNotFoundError):wake.validate_selected_inputs(self.job,director,treatment)
        b=copy.deepcopy(self.brief);b['source_binding']['segment_id']='seg-opening'
        with self.assertRaisesRegex(ValueError,'source clock'):wake.validate_brief(json.dumps(b))

    def test_preview_stage_passes_no_prefix_and_rejects_override(self):
        _,_,recipe,segment=self.setup_component()
        self.job.stages={'preview':{'status':'pending'}}
        with mock.patch('edit.hd.tools.state.load_job',return_value=self.job), \
             mock.patch('edit.hd.tools.state.current_stage',return_value='preview'), \
             mock.patch.object(run_stage,'_startup'), \
             mock.patch.object(run_stage,'_coverage_gate',return_value={}), \
             mock.patch.object(run_stage,'_summary',return_value={}), \
             mock.patch('edit.hd.tools.state.require_runnable'), \
             mock.patch('edit.hd.tools.delivery_approval.validate_visual_plan_approval'), \
             mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan',return_value={'segments':[segment]}), \
             mock.patch('edit.hd.tools.preview_v2.prepare_preview_v2') as preview:
            run_stage.execute_stage(self.job.job_dir,PROJECT,'preview')
            preview.assert_called_once_with(self.job,opening=None,music=None)
            with self.assertRaisesRegex(ValueError,'static opening prefix'):
                run_stage.execute_stage(self.job.job_dir,PROJECT,'preview',payload={'opening':{'hold_frames':6}})

    def test_selected_preflight_uses_original_runtime_and_exact_bridge(self):
        from dependency_preflight import _load_manifest, _check_binding_probe
        from project_python import preparation_selection
        manifest=_load_manifest(SKILL/'references/dependency-manifest.json')
        entries,checks=preparation_selection(manifest,{'lemo-wake'})
        self.assertIn('lemo-wake-source',{r['id'] for r in entries})
        item=next(r for r in checks if r['id']=='lemo-wake')
        result=_check_binding_probe(item,{'dependency_id':'lemo-wake','entrypoint':wake.ENTRY,
            'producer_version':wake.VERSION,'executor':'reference_adapter','primary_renderer':'HTMLCanvas'},
            project_root=PROJECT,reference_root=SKILL,dependency_root=SKILL)
        self.assertEqual(result['status'],'bound',result)

    def test_complete_upstream_snapshot_works_without_nested_git(self):
        from ensure_visual_broll_skills import _validate_repo, SOURCES
        packaged=self.root/'portable';packaged.mkdir()
        index=PROJECT/'source-repositories/index.json'
        entry=next(r for r in json.loads(index.read_text())['repositories'] if r['path']=='skill-development/vendor/lemo-wake')
        target=packaged/entry['path']
        for name in entry['files']:
            output=target/name;output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(PROJECT/entry['path']/name,output)
        (packaged/'source-repositories').mkdir();shutil.copyfile(index,packaged/'source-repositories/index.json')
        _validate_repo(target,SOURCES['lemo-wake'])
        self.assertEqual(wake.source_root(packaged),target)
        (target/'skills/wake/SKILL.md').write_text('changed')
        with self.assertRaises(ValueError):wake.source_root(packaged)

    def test_catalog_has_one_complete_wake_template(self):
        candidates=broll_skill_selection.discover_candidates(PROJECT)
        rows=[r for r in candidates if r['dependency_id']=='lemo-wake']
        self.assertEqual([(r['candidate_id'],r['template_id']) for r in rows], [('lemo-wake:wake','lemo-wake/wake')])

if __name__=='__main__':unittest.main()

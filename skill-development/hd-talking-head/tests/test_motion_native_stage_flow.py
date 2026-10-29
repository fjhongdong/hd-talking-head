"""Opt-in native motion stage smoke with isolated approval fixtures.

HD_MOTION_NATIVE_STAGE_SMOKE=1 python3.12 -m unittest test_motion_native_stage_flow

This is a code-flow fixture, not user approval, speech transcription, listening,
or creative acceptance. Media rendering uses the real pinned native scripts.
Its retained Jobs and media live outside the distributable Skill package.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _env
import motion_native_skill_adapter as native
from test_motion_native_skill_adapter import brief as native_brief
import test_wake_native as wake_fixture
SAMPLE = wake_fixture.SAMPLE
from edit.hd.tests.test_visual_direction import draft_segment
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tools import state, contract_artifacts as artifacts
from edit.hd.tools import broll_skill_selection, motion_match_cache, motion_capabilities
from edit.hd.tools import visual_canary, visual_confirmation as confirmation
from edit.hd.tools import broll_component_executor as executor
import run_stage

SAMPLES = Path(os.environ.get('HD_MOTION_NATIVE_SAMPLE_ROOT',
    str(_env.PROJECT.parent.parent / 'motion-integration-samples/20261029-barty-bang'))).resolve()


@unittest.skipUnless(os.environ.get('HD_MOTION_NATIVE_STAGE_SMOKE') == '1',
                     'Opt-in real browser/native rendering smoke')
class MotionNativeStageFlowTests(unittest.TestCase):
    def setUp(self):
        SAMPLES.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='stage-smoke-', dir=SAMPLES))
        # Reuse the known approved-input fixture without relocating or modifying
        # its original assets. Keep this new isolated Job for failure inspection.
        with mock.patch('test_wake_native.tempfile.TemporaryDirectory',
                        return_value=SimpleNamespace(name=str(root), cleanup=lambda: None)):
            wake_fixture.WakeNativeTests.setUp(self)
        print('\nNative motion fixture:', self.root, flush=True)

    def _edited_fixture(self):
        root = self.job.job_dir
        source = root / '06-edit-structure/edited-aroll.mp4'
        concat = root / 'fixture-concat.txt'
        concat.write_text("file '" + str(source) + "'\nfile '" + str(source) + "'\n")
        replacement = root / 'edited-fixture.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-v','error','-n','-f','concat','-safe','0','-i',str(concat),
            '-vf','trim=end_frame=168,setpts=PTS-STARTPTS','-af','atrim=end=7,asetpts=PTS-STARTPTS',
            '-c:v','libx264','-preset','ultrafast','-crf','30','-pix_fmt','yuv420p',
            '-c:a','aac','-video_track_timescale','24',str(replacement)],check=True,capture_output=True)
        replacement.replace(source)
        script = (self.root / 'script.md').read_text()
        artifacts.write_json_artifact(root / '06-edit-structure/timeline-map.json',
            {'output_duration':7,'segments':[{'source_start':0,'source_end':7,'timeline_start':0,'timeline_end':7}]})
        artifacts.write_json_artifact(root / '05-speech-cleanup/word-transcript.json',
            {'version':1,'words':[
                {'text':script,'start':0,'end':3},{'text':script,'start':3,'end':7}]})
        workflow = json.loads((root / 'workflow.json').read_bytes())
        for stage in ('speech_cleanup','edit_structure'):
            for item in workflow['stages'][stage]['artifacts']:
                file = root / item['path']; item.update(sha256=native.sha(file),bytes=file.stat().st_size)
        artifacts.write_json_artifact(root / 'workflow.json', workflow)
        self.job = state.load_job(root)
        return script, source

    def _draft(self, script, arroll):
        root = self.job.job_dir
        director = {'schema_version':3,'segments':[]}
        treatment = {'numbering_scope_id':'motion-native-isolated-stage-fixture',
            'scenes':[],'semantic_lists':{'overlay':[],'broll':[]},'beat_sheet':[],
            'motion_queries':[],'semantic_assessments':[],'motion_readability':[],
            'overlay_selection':[],'generation_plan':{'steps':[]},
            'skill_selection':{'schema_version':1,'beats':[],'overlay_beats':[],
                'history_note':'隔离测试，不判断真实创意质量','fixed_context':[],'recent_context':[]}}
        skills = {row['skill_id'] for row in broll_skill_selection.discover_candidates(_env.PROJECT)}
        targets = [('barty-motion-graphics','motion-broll',0,3,['过程']),
                   ('bang-motion','explainer-continuous-action',3,7,['过程'])]
        for index,(dependency,template,start,end,tags) in enumerate(targets,1):
            sid=f'seg-{index:03d}';cid=f'component-{index}';rowid=f'native-semantic-{index}'
            segment=draft_segment(('code_generated',),segment_id=sid,start=start,end=end)
            component=segment['visual_strategy']['components'][0]
            component.update(component_id=cid,media_type='animation')
            segment['visual_intent'].update(presenter_presence='hidden',statement=script)
            composition=segment['visual_strategy']['composition']
            composition.update(presenter_mode='hidden',reading_order=[cid]);composition.pop('avatar',None)
            segment['candidate_snapshots']={};segment['bindings']={}
            b=native_brief(dependency,template);b.update(job_id=self.job.job_id,transcript=script,
                semantic_goal='隔离fixture验证原生过程说明',
                composition={'width':1080,'height':1920,'fps':24,'frames':round((end-start)*24)},
                word_anchors=[{'text':script,'start':0,'end':end-start}],
                project_directory='native-projects/'+sid,result_record_path='native-inputs/'+sid+'/result.json')
            b['source_binding']={'aroll_sha256':native.sha(arroll),'segment_id':sid,'start':start,'end':end}
            voice=root/('voice-'+sid+'.wav')
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-n','-ss',str(start),'-i',str(arroll),
                            '-t',str(end-start),'-vn','-ac','1','-ar','16000',str(voice)],check=True,capture_output=True)
            b['speech']=native.descriptor(root,voice)
            request=root/('native-inputs/'+sid+'/brief.json');request.parent.mkdir(parents=True)
            artifacts.write_json_artifact(request,b);payload=request.read_bytes()
            adapter=native.create_adapter(_env.PROJECT,sys.executable,lambda *_:payload,dependency_id=dependency)
            binding=native.create_binding(adapter,payload,SAMPLE/'native-sample.mp4');segment['bindings'][cid]=binding
            director['segments'].append(segment)
            refs=[{'segment_id':sid,'component_id':cid}]
            treatment['scenes'].append({'segment_id':sid,'component_id':cid,'brief_path':request.relative_to(root).as_posix()})
            treatment['semantic_lists']['broll'].append({'row_id':rowid,'start_word':index-1,'end_word':index,
                'quote':script,'semantic':b['semantic_goal'],'visual_task':'用原生过程说明工程验证执行链','components':refs})
            treatment['beat_sheet'].append({'start_word':index-1,'end_word':index,'quote':script,'decision':'broll',
                'visual':'隔离fixture原生过程说明','components':refs,'reason':'只验证接口与状态流程'})
            treatment['motion_queries'].append({'segment_id':sid,'component_id':cid,'tags':tags})
            treatment['semantic_assessments'].append({'segment_id':sid,'component_id':cid,
                'candidate_id':dependency+':'+dependency+'/'+template,'verdict':'pass','reason':'隔离fixture前提，不代表实际内容评价',
                'transcript_refs':[{'start_word':index-1,'end_word':index,'quote':script,'basis':'current_clause'}],
                'content_refs':[{'path':request.relative_to(root).as_posix(),'sha256':native.sha(request),
                                 'pointer':'/'+key,'value':b[key]} for key in ('transcript','semantic_goal','template_id')]})
            treatment['motion_readability'].append({'segment_id':sid,'component_id':cid,'targets':[],
                'no_critical_text_reason':'隔离状态fixture；此处不冒充真实创作文字视觉验收'})
            treatment['skill_selection']['beats'].append({'segment_id':sid,'component_id':cid,'semantic_row_id':rowid,
                'start':start,'end':end,'transcript':script,'semantic_goal':b['semantic_goal'],
                'required_change':'用原生过程说明工程验证执行链','intent_statement':script,'component_brief':component['brief'],
                'binding_snapshot':copy.deepcopy(binding),
                'skill_reviews':{skill:{'fit':'equivalent','reason':'隔离fixture候选前提，不据此评价实际质量'} for skill in skills},
                'candidates':[]})
        treatment=motion_match_cache.match_once(_env.PROJECT,director,treatment)
        cached=motion_match_cache.validate_matches(_env.PROJECT,director,treatment)
        design={'composition':'隔离fixture原生整屏过程','typography':'沿用原生示例中文',
                'finish':'沿用原生示例色彩材质','focus':'验证当前过程工程执行到媒体'}
        for beat in treatment['skill_selection']['beats']:
            key=(beat['segment_id'],beat['component_id'])
            wanted=next(r['candidate_id'] for r in treatment['semantic_assessments']
                        if (r['segment_id'],r['component_id'])==key)
            beat['candidates']=[{'candidate_id':item['candidate']['candidate_id'],
                'fit':'preferred' if item['candidate']['candidate_id']==wanted else 'equivalent',
                'reason':'隔离fixture选择真实准备的原生工程','visual_pattern':'native-'+beat['segment_id'],
                'design_plan':design} for item in cached[key]['matches']]
        treatment['skill_selection']=broll_skill_selection.assign_skills(_env.PROJECT,treatment['skill_selection'],job_dir=root)
        self.assertEqual([a['skill_id'] for a in treatment['skill_selection']['assignments']],
                         ['barty-motion-graphics','bang-motion'])
        return director,treatment

    def _render(self, action):
        root=self.job.job_dir;request=Path(action['brief_path']);b=native.validate_brief(request.read_bytes())
        directory=Path(action['project_directory']);directory.mkdir(parents=True)
        runtime=action['runtime'];(directory/'node_modules').symlink_to(runtime['node_modules'],target_is_directory=True)
        if b['dependency_id']=='barty-motion-graphics':
            source=SAMPLES/'barty-source';(directory/'dist').mkdir()
            shutil.copyfile(source/'dist/opaque.html',directory/'dist/opaque.html')
            shutil.copytree(source/'assets',directory/'assets')
            html=directory/'dist/opaque.html';output=directory/'out/native.mp4';output.parent.mkdir()
            argv=[runtime['tools']['node'],str(native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'),str(html),str(output),'24']
        else:
            shutil.copytree(SAMPLES/'bang-source',directory,dirs_exist_ok=True)
            shutil.copyfile(native.source_root(dependency_id=b['dependency_id'])/'scripts/export-frames.mjs',directory/'export-frames.mjs')
            html=directory/'index.html';output=directory/'out/native.mp4'
            argv=[runtime['tools']['node'],str(directory/'export-frames.mjs'),str(html),str(output)]
        call=native.capture_render(root,request,argv)
        native.publish_completed(root,request,call,qa_note='隔离fixture仅核对原生执行和真实媒体规格；不冒充听音或创意验收。')
        return native.inspect_result(root,request.read_bytes())

    def test_barty_and_bang_from_complete_list_to_native_executor(self):
        script,arroll=self._edited_fixture();director,treatment=self._draft(script,arroll)
        root=self.job.job_dir;approve_fixture_setup(self.job)
        artifacts.write_json_artifact(root/'manifests/confirmed-content.json',{'schema_version':1,'job_id':self.job.job_id,
            'source_words':[{'index':0,'text':script}],
            'visuals':[{'component_id':cid,'composition_family':'single_full_frame','visible_text':[],'binding':binding}
                       for seg in director['segments'] for cid,binding in seg['bindings'].items()]})
        dpath=root/'director.json';tpath=root/'treatment.json'
        artifacts.write_json_artifact(dpath,director);artifacts.write_json_artifact(tpath,treatment)
        run_stage.run_visual_direction(root,_env.PROJECT,dpath,tpath)
        self.job=state.load_job(root)
        review={k:copy.deepcopy(v) for k,v in run_stage._summary(self.job,'visual_direction').items()
                if k in {'job_id','job_dir','stage','revision','artifacts'}}
        review.update(passed=True,note='显式隔离fixture批准，仅验证流程，不是实际用户确认',
                      user_confirmation='显式隔离fixture授权，不得用于正式用户视频')
        run_stage._review(self.job,'visual_direction',review);self.job=state.load_job(root)
        pending=run_stage.resume_visual_direction(self.job,_env.PROJECT,{})
        self.assertEqual([a['dependency_id'] for a in pending['actions']],['barty-motion-graphics','bang-motion'])
        self.assertTrue(all(a['action']=='execute_native_skill' for a in pending['actions']))
        for action in pending['actions']:
            result=self._render(action)
            assessment=next(a for a in treatment['semantic_assessments']
                            if (a['segment_id'],a['component_id'])==(action['segment_id'],action['component_id']))
            call=json.loads(native.exact(root,result['render_call']).read_bytes())
            assessment['content_refs']=[{'path':f['job_path'],'sha256':f['sha256'],
                'quote':(root/f['job_path']).read_text().splitlines()[0]}
                for f in call['project_files'] if Path(f['job_path']).suffix=='.html']
            record=root/action['result_record_path']
            assessment['content_refs'].append({'path':action['result_record_path'],'sha256':native.sha(record),
                'pointer':'/status','value':'completed'})
        artifacts.write_json_artifact(tpath,treatment)
        run_stage.resume_visual_direction(self.job,_env.PROJECT,{'realization':{'director_brief':'director.json',
            'treatment':'treatment.json','host_qa_note':'隔离fixture原生渲染完成，检查来源、内容引用和结果冻结，不冒充正式视觉验收'}})
        self.job=state.load_job(root);confirmation.validate_visual_authorization(self.job,require_realized=True)
        plan=visual_canary.load_approved_visual_plan(self.job);adapters=run_stage.native_component_adapters(_env.PROJECT,self.job)
        outcomes=[]
        for segment in plan['segments']:
            recipe=segment['shot_recipe'];component=recipe['components'][0]
            result=executor.execute_component(self.job,executor.ComponentExecutionRequest(recipe=recipe,component_id=component['component_id']),
                adapters={**adapters,'artifact_probe':native.create_artifact_probe(ffprobe_executable=shutil.which('ffprobe'))})
            self.assertEqual(result.status,'success')
            b=next(s for s in treatment['scenes'] if s['segment_id']==segment['segment_id'])
            expected=native.inspect_result(root,(root/b['brief_path']).read_bytes())
            self.assertEqual(result.output_sha256,expected['media']['sha256'])
            outcomes.append({'dependency_id':component['dependency_id'],'status':result.status,'job_path':result.job_path,
                             'sha256':result.output_sha256})
        artifacts.write_json_artifact(self.root/'stage-smoke-result.json',{'development_fixture':True,'outcomes':outcomes})
        print('Native stage smoke completed:',self.root/'stage-smoke-result.json',flush=True)


if __name__=='__main__':unittest.main()

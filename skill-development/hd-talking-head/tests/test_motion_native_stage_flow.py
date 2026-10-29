"""Opt-in native motion stage smoke with isolated approval fixtures.

HD_MOTION_NATIVE_STAGE_SMOKE=1 HD_MOTION_NATIVE_SAMPLE_ROOT=<external-case-root> \
    python3.12 -m unittest test_motion_native_stage_flow

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
import unittest

import _env
import motion_native_skill_adapter as native
from test_motion_native_skill_adapter import brief as native_brief
from edit.hd.tests.test_visual_direction import draft_segment
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tools import state, contract_artifacts as artifacts
from edit.hd.tools import broll_skill_selection, motion_match_cache
from edit.hd.tools import visual_canary, visual_confirmation as confirmation
from edit.hd.tools import broll_component_executor as executor
import run_stage

@unittest.skipUnless(os.environ.get('HD_MOTION_NATIVE_STAGE_SMOKE') == '1',
                     'Opt-in real browser/native rendering smoke')
class MotionNativeStageFlowTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('HD_MOTION_NATIVE_SAMPLE_ROOT'):
            raise ValueError('Set HD_MOTION_NATIVE_SAMPLE_ROOT to the external native sample directory')
        self.samples=Path(os.environ['HD_MOTION_NATIVE_SAMPLE_ROOT']).resolve(strict=True)
        if self.samples.is_relative_to(_env.PROJECT):
            raise ValueError('Native sample inputs and outputs must stay outside the Skill package')
        case_root=self.samples/'source-case'
        self.case=json.loads((case_root/'case.json').read_bytes())
        self.root=Path(tempfile.mkdtemp(prefix='stage-smoke-',dir=self.samples)).resolve()
        shutil.copyfile(case_root/'source.mp4',self.root/'source.mp4')
        shutil.copyfile(case_root/'script.md',self.root/'script.md')
        self.job=state.create_job(self.root,self.root/'source.mp4',self.root/'script.md',profile='full-v2')
        approve_fixture_setup(self.job)
        print('\nNative motion fixture:', self.root, flush=True)

    def _edited_fixture(self):
        root = self.job.job_dir
        duration=self.case['duration_frames']/24
        script=(self.root/'script.md').read_text().strip()
        def approve(stage,items):
            paths=[]
            for relative,value in items:
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
                if isinstance(value,Path):shutil.copyfile(value,path)
                else:artifacts.write_json_artifact(path,value)
                paths.append(path)
            state.mark_ready(self.job,stage,paths);state.approve(self.job,stage)
        approve('inspect',[('01-inspect/report.json',{'development_fixture':True,'source':'real lecturer clip'})])
        from edit.hd.tools import content_analysis
        content_analysis.prepare_content_analysis(self.job,{'thesis':script,'hook':'门店日常工作',
            'sections':[{'id':'s1','title':'工作与疲劳','source_span':[0,len(script)]}],
            'items':[{'id':'idea-01','source_text':script,'source_span':[0,len(script)],'priority':'critical',
                'keywords':['补货','理架','收银','肯熬','手快','不出错'],'semantic_type':'contrast',
                'evidence_status':'supported','broll_priority':'high'}],'claims':[]})
        state.approve(self.job,'content_analysis')
        approve('cover_direction',[('03-cover-direction/cover-direction.json',{'development_fixture':True})])
        approve('cover',[('04-cover/cover-report.json',{'development_fixture':True}),
            ('04-cover/cover-delivery-raster.png',_env.SKILL/'assets/wake-native-v2-smoke/04-cover/cover-delivery-raster.png')])
        approve('speech_cleanup',[('05-speech-cleanup/word-transcript.json',{'version':1,'words':self.case['words']})])
        source=root/'06-edit-structure/edited-aroll.mp4'
        approve('edit_structure',[('06-edit-structure/edit-plan.json',{'canvas':{'width':1080,'height':1920,'fps':24}}),
            ('06-edit-structure/timeline-map.json',{'output_duration':duration,'segments':[
                {'source_start':0,'source_end':duration,'timeline_start':0,'timeline_end':duration}]}),
            ('06-edit-structure/edited-aroll.mp4',self.root/'source.mp4')])
        self.job = state.load_job(root)
        return script, source

    def _draft(self, script, arroll):
        root = self.job.job_dir
        director = {'schema_version':3,'segments':[]}
        treatment = {'numbering_scope_id':'motion-native-isolated-stage-fixture',
            'scenes':[],'semantic_lists':{'overlay':[],'broll':[]},'beat_sheet':[],
            'motion_queries':[],'semantic_assessments':[],'motion_readability':[],
            'overlay_selection':[],'overlay_alignment':[],'generation_plan':{'steps':[]},
            'skill_selection':{'schema_version':1,'beats':[],'overlay_beats':[],
                'history_note':'隔离测试，不判断真实创意质量','fixed_context':[],'recent_context':[]}}
        skills = {row['skill_id'] for row in broll_skill_selection.discover_candidates(_env.PROJECT)}
        for index,case in enumerate(self.case['segments'],1):
            dependency,template=case['dependency_id'],case['template_id']
            start,end=case['start_frame']/24,case['end_frame']/24
            sid=case['segment_id'];cid=f'component-{index}';rowid=f'native-semantic-{index}'
            indices=[i for i,w in enumerate(self.case['words']) if start <= (w['start']+w['end'])/2 < end]
            first,last=min(indices),max(indices)+1;quote=case['quote']
            self.assertEqual(quote,''.join(w['text'] for w in self.case['words'][first:last]))
            overlay = dependency == 'barty-motion-graphics'
            segment=draft_segment(('code_generated',),segment_id=sid,start=start,end=end)
            component=segment['visual_strategy']['components'][0]
            component.update(component_id=cid,media_type='animation')
            segment['visual_intent'].update(presenter_presence='hidden',statement=case['semantic'])
            composition=segment['visual_strategy']['composition']
            composition.update(presenter_mode='hidden',reading_order=[cid]);composition.pop('avatar',None)
            if overlay:
                segment['visual_intent']['presenter_presence']='required'
                segment['visual_strategy']['mode']='none'
                composition.update(family='aroll_with_overlay',presenter_mode='full_frame')
                component.update(layer_role='annotation',layout_slot='main_overlay')
            else:
                component['layout_slot']='full_frame'
            segment['candidate_snapshots']={};segment['bindings']={}
            b=native_brief(dependency,template,overlay);b.update(job_id=self.job.job_id,transcript=quote,
                semantic_goal=case['semantic'],
                composition={'width':1080,'height':1920,'fps':24,'frames':round((end-start)*24)},
                word_anchors=[{'text':w['text'],'start':max(0,w['start']-start),'end':min(end,w['end'])-start}
                              for w in self.case['words'][first:last]],
                project_directory='native-projects/'+sid,result_record_path='native-inputs/'+sid+'-result.json')
            b['task_source']={'semantic_row_id':rowid,'quote':quote,'semantic':b['semantic_goal'],
                'required_change':case['required_change'],'component_brief':component['brief']}
            b['native_options']=case['native_options']
            b['source_binding']={'aroll_sha256':native.sha(arroll),'segment_id':sid,'start':start,'end':end}
            voice=root/('voice-'+sid+'.wav')
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-n','-ss',str(start),'-i',str(arroll),
                            '-t',str(end-start),'-vn','-ac','1','-ar','16000',str(voice)],check=True,capture_output=True)
            b['speech']=native.descriptor(root,voice)
            request=root/('native-inputs/'+sid+'/brief.json');request.parent.mkdir(parents=True)
            artifacts.write_json_artifact(request,b);payload=request.read_bytes()
            adapter=native.create_adapter(_env.PROJECT,sys.executable,lambda *_:payload,dependency_id=dependency)
            binding=native.create_binding(adapter,payload,arroll);segment['bindings'][cid]=binding
            director['segments'].append(segment)
            refs=[{'segment_id':sid,'component_id':cid}]
            treatment['scenes'].append({'segment_id':sid,'component_id':cid,'brief_path':request.relative_to(root).as_posix()})
            treatment['semantic_lists']['overlay' if overlay else 'broll'].append({'row_id':rowid,'start_word':first,'end_word':last,
                'quote':quote,'semantic':b['semantic_goal'],'visual_task':case['required_change'],'components':refs})
            treatment['beat_sheet'].append({'start_word':first,'end_word':last,'quote':quote,'decision':'overlay' if overlay else 'broll',
                'visual':case['required_change'],'components':refs,'reason':'独立开发样片的明确语义任务'})
            treatment['motion_queries'].append({'segment_id':sid,'component_id':cid,'tags':['并列','过程'] if overlay else ['疲劳','过程']})
            treatment['semantic_assessments'].append({'segment_id':sid,'component_id':cid,
                'candidate_id':('overlay:' if overlay else dependency+':')+dependency+'/'+template,'verdict':'pass','reason':'隔离fixture前提，不代表实际内容评价',
                'transcript_refs':[{'start_word':first,'end_word':last,'quote':quote,'basis':'current_clause'}],
                'content_refs':[{'path':request.relative_to(root).as_posix(),'sha256':native.sha(request),
                                 'pointer':'/'+key,'value':b[key]} for key in ('transcript','template_id','native_options')]
                    +[{'path':request.relative_to(root).as_posix(),'sha256':native.sha(request),
                       'pointer':'/task_source/'+key,'value':b['task_source'][key]} for key in ('quote','semantic')]})
            treatment['motion_readability'].append({'segment_id':sid,'component_id':cid,'targets':[], 'pending_native':True})
            if overlay:
                treatment['overlay_alignment'].append({'segment_id':sid,'component_id':cid,'brief_path':request.relative_to(root).as_posix()})
                treatment['overlay_selection'].append({'segment_id':sid,'component_id':cid,'native_route':dependency+'/'+template,
                    'intent_relation':'parallel','visible_action':'one_shape_morph','visual_structure':'parallel_jobs',
                    'selection_reason':'在原声词锚逐项呈现并列工作，避免画成先后流程'})
            treatment['skill_selection']['overlay_beats' if overlay else 'beats'].append({'segment_id':sid,'component_id':cid,'semantic_row_id':rowid,
                'start':start,'end':end,'transcript':quote,'semantic_goal':b['semantic_goal'],
                'required_change':b['task_source']['required_change'],'intent_statement':case['semantic'],'component_brief':component['brief'],
                'binding_snapshot':copy.deepcopy(binding),
                'skill_reviews':{skill:{'fit':'equivalent','reason':'隔离fixture候选前提，不据此评价实际质量'} for skill in skills},
                'candidates':[]})
        treatment=motion_match_cache.match_once(_env.PROJECT,director,treatment)
        cached=motion_match_cache.validate_matches(_env.PROJECT,director,treatment)
        design={'composition':'隔离fixture原生整屏过程','typography':'沿用原生示例中文',
                'finish':'沿用原生示例色彩材质','focus':'验证当前过程工程执行到媒体'}
        for beat in [*treatment['skill_selection']['beats'],*treatment['skill_selection']['overlay_beats']]:
            key=(beat['segment_id'],beat['component_id'])
            wanted=next(r['candidate_id'] for r in treatment['semantic_assessments']
                        if (r['segment_id'],r['component_id'])==key)
            beat['candidates']=[{'candidate_id':item['candidate']['candidate_id'],
                'fit':'preferred' if item['candidate']['candidate_id']==wanted else 'equivalent',
                'reason':'隔离fixture选择真实准备的原生工程','visual_pattern':'native-'+beat['segment_id'],
                'design_plan':design} for item in cached[key]['matches']]
        treatment['skill_selection']=broll_skill_selection.assign_skills(_env.PROJECT,treatment['skill_selection'],job_dir=root)
        self.assertEqual([a['skill_id'] for a in treatment['skill_selection']['assignments']],['bang-motion'])
        self.assertEqual([a['skill_id'] for a in treatment['skill_selection']['overlay_assignments']],['barty-motion-graphics'])
        return director,treatment

    def _render(self, action):
        root=self.job.job_dir;request=Path(action['brief_path']);b=native.validate_brief(request.read_bytes())
        case=next(c for c in self.case['segments'] if c['segment_id']==action['segment_id'])
        source=self.samples/'source-case'/case['source_project']
        if not source.is_dir():raise ValueError('Prepare the complete native authored project first: '+str(source))
        directory=Path(action['project_directory']);shutil.copytree(source,directory)
        runtime=action['runtime'];(directory/'node_modules').symlink_to(runtime['node_modules'],target_is_directory=True)
        if b['dependency_id']=='barty-motion-graphics':
            builder=native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/build.py'
            fragment=case['fragment_html'];html=directory/case['entry_html']
            subprocess.run([sys.executable,str(builder),str(html.parent),fragment],cwd=directory,check=True,capture_output=True)
            output=directory/'out/native.mov';output.parent.mkdir()
            argv=[runtime['tools']['node'],str(native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'),str(html),str(output),'24']
        else:
            shutil.copyfile(native.source_root(dependency_id=b['dependency_id'])/'scripts/export-frames.mjs',directory/'export-frames.mjs')
            argv=[runtime['tools']['node'],'export-frames.mjs',case['entry_html'],'out/native.mp4']
        call=native.capture_render(root,request,argv)
        native.publish_completed(root,request,call,qa_note='开发Smoke完成原生工程与媒体回传；最终像素、透明叠加和创意质量仍由宿主检查，不能冒充正式用户交付。')
        return native.inspect_result(root,request.read_bytes())

    def test_barty_and_bang_from_complete_list_to_native_executor(self):
        script,arroll=self._edited_fixture();director,treatment=self._draft(script,arroll)
        root=self.job.job_dir
        artifacts.write_json_artifact(root/'manifests/confirmed-content.json',{'schema_version':1,'job_id':self.job.job_id,
            'source_words':[{'index':i,'text':word['text']} for i,word in enumerate(self.case['words'])],
            'visuals':[{'component_id':cid,'composition_family':seg['visual_strategy']['composition']['family'],'visible_text':[],
                       'binding':{key:binding[key] for key in ('dependency_id','template_id','source_sha256')}}
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
                'quote':'M.scene({' if result['alpha'] else 'window.OPENER'}
                for f in call['project_files'] if Path(f['job_path']).suffix=='.html']
            record=root/action['result_record_path']
            assessment['content_refs'].append({'path':action['result_record_path'],'sha256':native.sha(record),
                'pointer':'/status','value':'completed'})
            case=next(c for c in self.case['segments'] if c['segment_id']==action['segment_id'])
            source=next(f for f in call['project_files'] if f['job_path'].endswith('/'+case['entry_html']))
            source_text=(root/source['job_path']).read_text()
            targets=[]
            for index,target in enumerate(case['text_targets']):
                text=target['text']
                offset=source_text.index('>'+text+'<')+1
                targets.append({'target_id':action['segment_id']+'-'+str(index),
                    'content_ref':{'path':source['job_path'],'sha256':source['sha256'],'pointer':f'text:{offset}:{offset+len(text)}','value':text},
                    'span':[0,len(text)],'role':target['role'],'region':target['region'],'windows':target['windows']})
            readability=next(r for r in treatment['motion_readability'] if r['segment_id']==action['segment_id'])
            readability.clear();readability.update(segment_id=action['segment_id'],component_id=action['component_id'],targets=targets)
            next(s for s in director['segments'] if s['segment_id']==action['segment_id'])['visible_text']=[target['text'] for target in case['text_targets']]
        artifacts.write_json_artifact(dpath,director)
        artifacts.write_json_artifact(tpath,treatment)
        from edit.hd.tools import content_analysis
        analysis=content_analysis.load_approved_content_analysis(self.job)
        artifacts.write_json_artifact(root/'reviewed-visual-text.json',{'content_analysis_sha256':analysis['analysis_sha256'],
            'entries':[{'segment_id':segment['segment_id'],'text':text,'source_ref':'item:idea-01',
                        'source_quote':script,'reason':'原生从当前真实原话提炼的画面文字，不增加事实、数字或后文结果'}
                       for segment in director['segments'] for text in segment['visible_text']]})
        run_stage.resume_visual_direction(self.job,_env.PROJECT,{'realization':{'director_brief':'director.json',
            'treatment':'treatment.json','reviewed_visual_text':'reviewed-visual-text.json',
            'host_qa_note':'独立开发样片原生渲染完成，实际源码、文字清单与结果审核冻结；最终画面由宿主再检查，不冒充用户正式交付'}})
        self.job=state.load_job(root);confirmation.validate_visual_authorization(self.job,require_realized=True)
        plan=visual_canary.load_approved_visual_plan(self.job);adapters=run_stage.native_component_adapters(_env.PROJECT,self.job)
        outcomes=[];rendered=[]
        from edit.hd.tools import segment_render, subtitles_v2, talkcraft_subtitles, preview_v2
        for segment in plan['segments']:
            recipe=segment['shot_recipe'];component=recipe['components'][0]
            if component['dependency_id']=='bang-motion':
                self.assertEqual(component['render_window']['layout_slot'],'full_frame')
            result=executor.execute_component(self.job,executor.ComponentExecutionRequest(recipe=recipe,component_id=component['component_id']),
                adapters={**adapters,'artifact_probe':native.create_artifact_probe(ffprobe_executable=shutil.which('ffprobe'))})
            self.assertEqual(result.status,'success')
            b=next(s for s in treatment['scenes'] if s['segment_id']==segment['segment_id'])
            expected=native.inspect_result(root,(root/b['brief_path']).read_bytes())
            self.assertEqual(result.output_sha256,expected['media']['sha256'])
            renderer=segment_render.render_arroll_segment if recipe['mode']=='none' else segment_render.render_segment_video
            rendered.append(renderer(self.job,segment,artifacts=(result,),output_dir=root/'smoke-segments',
                visual_plan_sha256=plan['visual_plan_sha256'],arroll_source=arroll,arroll_sha256=native.sha(arroll),arroll_bytes=arroll.stat().st_size))
            outcomes.append({'dependency_id':component['dependency_id'],'status':result.status,'job_path':result.job_path,
                             'sha256':result.output_sha256})
        outputs=root/'smoke-preview';outputs.mkdir()
        visual=outputs/'visual.mp4';segment_render.assemble_visual_track(rendered,visual)
        numbered=confirmation.approved_numbered_rows(self.job)
        component_records=outputs/'component-results.json';artifacts.write_json_artifact(component_records,{'outcomes':outcomes})
        paths={'word_transcript':root/'05-speech-cleanup/word-transcript.json','timeline_map':root/'06-edit-structure/timeline-map.json',
            'edited_aroll':arroll,'visual_plan':root/'07-visual-direction/visual-plan.json','asset_manifest':component_records,'visual_track':visual}
        cues=[]
        render_plan=subtitles_v2.build_render_plan(records={name:confirmation._record(root,path) for name,path in paths.items()},
            words=self.case['words'],timeline=json.loads(paths['timeline_map'].read_bytes()),visual_plan=plan,
            keyword_index={'idea-01':('补货','理架','收银','肯熬','手快','不出错')},renderer_cues=cues)
        subtitle_input=talkcraft_subtitles.renderer_input(render_plan,cues)
        artifacts.write_json_artifact(outputs/'subtitle-plan.json',render_plan)
        subtitles=outputs/'subtitles.webm'
        with subtitles.open('w+b') as stream:talkcraft_subtitles.render(subtitle_input,stream.fileno())
        atlas=preview_v2._write_number_atlas(outputs/'number-badges.png',[r['number'] for r in numbered])
        schedule=[{**r,'start_frame':round(r['start']*24),'end_frame':round(r['end']*24)} for r in numbered]
        preview=outputs/'native-stage-smoke-preview.mp4'
        command=preview_v2.build_preview_command_v2(visual,subtitles,arroll,preview,frames=self.case['duration_frames'],
            duration=self.case['duration_frames']/24,number_overlay={'rows':schedule,'atlas':atlas})
        subprocess.run(command,check=True,capture_output=True)
        artifacts.write_json_artifact(self.root/'stage-smoke-result.json',{'development_fixture':True,'outcomes':outcomes,
            'preview':str(preview),'numbered_rows':numbered})
        print('Native stage smoke completed:',self.root/'stage-smoke-result.json',flush=True)


if __name__=='__main__':unittest.main()

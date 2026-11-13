"""Opt-in local native production smoke ending in delivered, pending acceptance.

HD_MOTION_NATIVE_STAGE_SMOKE=1 HD_MOTION_NATIVE_SAMPLE_ROOT=<external-case-root> \
    python3.12 -m unittest test_motion_native_stage_flow

Existing local inputs and a fixed production plan are reused with explicit provenance.
This does not validate new speech transcription, image generation, listening, or creative acceptance. Media rendering uses the real pinned native scripts.
Its retained Jobs and media live outside the distributable Skill package.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import _env
import motion_native_skill_adapter as native
from test_motion_native_skill_adapter import brief as native_brief
from edit.hd.tests.test_visual_direction import draft_segment
from edit.hd.tools import state, contract_artifacts as artifacts
from edit.hd.tools import broll_skill_selection, motion_match_cache
from edit.hd.tools import visual_confirmation as confirmation
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
        if self.case.get('exercise_explicit_routes'):
            original_constraint=motion_match_cache._constraint_refs
            def validate_constraint(review, *args, **kwargs):
                # This fixture exercises specific approved routes after matching. A
                # fixture preference supplies no evidence of a competing route's limits.
                if review.get('reason') != '隔离技术样片要求使用为本镜准备的指定原生配方':
                    return original_constraint(review,*args,**kwargs)
            self.enterContext(patch.object(motion_match_cache,'_constraint_refs',validate_constraint))
        from initialize_video_job import initialize_video_job
        from edit.hd.tools import startup
        import dependency_preflight
        runs = self.samples / 'runs'
        runs.mkdir(exist_ok=True)
        self.job, _context = initialize_video_job(runs, 'direct-delivery-local-smoke',
            case_root / 'source.mp4', case_root / 'script.md',
            user_files=[case_root / 'existing-cover/cover-9x16.png'], project_root=_env.PROJECT)
        self.root = self.job.root
        manifests = self.job.job_dir / 'manifests'
        config = manifests / 'provider-config.json'
        artifacts.write_json_artifact(config, {'schema_version': 1, 'providers': [],
            'max_concurrency': 1, 'generation_enabled': False})
        report = dependency_preflight.build_report(_env.PROJECT / 'references/dependency-manifest.json',
            _env.PROJECT, _env.PROJECT / 'vendor', dependency_preflight._default_skill_roots(),
            job_context_path=self.root / 'job-context.json')
        artifacts.write_json_artifact(manifests / 'dependency-preflight.json', report)
        startup.confirm_setup(self.job, config,
            user_confirmation='本次已授权独立免费本地制作链验证；不上传ASR，不生成新图片视频，不继承旧人工验收。')
        print('\nNative motion fixture:', self.root, flush=True)

    def _edited_fixture(self):
        root = self.job.job_dir
        duration=self.case['duration_frames']/24
        script=(self.samples/'source-case/script.md').read_text().strip()
        keywords=self.case.get('keywords',['补货','理架','收银','肯熬','手快','不出错'])
        def complete(stage,items):
            paths=[]
            for relative,value in items:
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
                if isinstance(value,Path):shutil.copyfile(value,path)
                else:artifacts.write_json_artifact(path,value)
                paths.append(path)
            state.mark_ready(self.job,stage,paths);state.complete(self.job,stage)
        complete('inspect',[('01-inspect/report.json',{'fixture_scope':'reuse_existing_local_inputs_before_production_plan'})])
        from edit.hd.tools import content_analysis
        content_analysis.prepare_content_analysis(self.job,{'thesis':script,'hook':script,
            'sections':[{'id':'s1','title':'真实口播样片','source_span':[0,len(script)]}],
            'items':[{'id':'idea-01','source_text':script,'source_span':[0,len(script)],'priority':'critical',
                'keywords':keywords,'semantic_type':'contrast',
                'evidence_status':'supported','broll_priority':'high'}],'claims':[]})
        state.complete(self.job,'content_analysis')
        complete('cover_direction',[('03-cover-direction/cover-direction.json',self.samples/'source-case/existing-cover-direction.json')])
        cover = self.samples/'source-case/existing-cover'
        complete('cover',[(f'04-cover/{name}', cover/name) for name in
            ('cover-report.json','cover-brief.json','cover-9x16.png','cover-delivery-raster.png')])
        complete('speech_cleanup',[
            ('05-speech-cleanup/word-transcript.json',{'version':1,'words':self.case['words']}),
            ('05-speech-cleanup/diff-summary.json',{'version':1,'original_script':script,
                'cleaned_script':script,'deleted_words':[],'deleted_word_count':0})])
        source=root/'06-edit-structure/edited-aroll.mp4'
        complete('edit_structure',[('06-edit-structure/edit-plan.json',{'canvas':{'width':1080,'height':1920,'fps':24}}),
            ('06-edit-structure/timeline-map.json',{'version':1,'source_duration':duration,'output_duration':duration,
                'has_deletion':False,'audio_policy':'existing-local-clip-audio-clock',
                'render_adapter':'native-ffmpeg-no-cut','segments':[
                {'source_start':0,'source_end':duration,'timeline_start':0,'timeline_end':duration}]}),
            ('06-edit-structure/edited-aroll.mp4',self.job.root/self.job.inputs['video']['path'])])
        self.job = state.load_job(root)
        return script, source

    def _draft(self, script, arroll):
        root = self.job.job_dir
        director = {'schema_version':3,'segments':[]}
        treatment = {'numbering_scope_id':'motion-native-isolated-stage-fixture',
            'scenes':[],'semantic_lists':{'overlay':[],'broll':[]},'beat_sheet':[],
            'motion_queries':[],
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
                if 'avatar' in case:
                    composition.update(presenter_mode='bottom_window',avatar=copy.deepcopy(case['avatar']))
                    composition['avatar']['profile']['source_sha256']=native.sha(arroll)
                    segment['visual_intent']['presenter_presence']='required'
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
            declaration=copy.deepcopy(case.get('cinecode_input'))
            if declaration is not None:
                b['cinecode_material_branch']=declaration['branch']
                material_path=declaration.pop('material_path',None)
                if material_path is not None:
                    original=self.samples/'source-case'/case['source_project']/material_path
                    approved=root/'fixture-materials'/sid/original.name
                    approved.parent.mkdir(parents=True)
                    shutil.copyfile(original,approved)
                    material=native.descriptor(root,approved)
                    declaration['material']=material
                    b['materials']=[material]
                case['prepared_cinecode_input']=declaration
            if dependency in {'mg-styles-15','video-shotcraft','bb-video','cinecode'}:
                b['template_request'].update(semantic_family='process',information_units=2)
            b['source_binding']={'aroll_sha256':native.sha(arroll),'segment_id':sid,'start':start,'end':end}
            voice=root/('voice-'+sid+'.wav')
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-n','-ss',str(start),'-i',str(arroll),
                            '-t',str(end-start),'-vn','-ac','1','-ar','16000',str(voice)],check=True,capture_output=True)
            b['speech']=native.descriptor(root,voice)
            request=root/('native-inputs/'+sid+'/brief.json');request.parent.mkdir(parents=True)
            artifacts.write_json_artifact(request,b);payload=request.read_bytes()
            adapter=native.create_adapter(_env.PROJECT,sys.executable,lambda *_:payload,dependency_id=dependency)
            binding=native.create_binding(adapter,payload);segment['bindings'][cid]=binding
            director['segments'].append(segment)
            refs=[{'segment_id':sid,'component_id':cid}]
            treatment['scenes'].append({'segment_id':sid,'component_id':cid,'brief_path':request.relative_to(root).as_posix()})
            treatment['semantic_lists']['overlay' if overlay else 'broll'].append({'row_id':rowid,'start_word':first,'end_word':last,
                'quote':quote,'semantic':b['semantic_goal'],'visual_task':case['required_change'],'components':refs})
            treatment['beat_sheet'].append({'start_word':first,'end_word':last,'quote':quote,'decision':'overlay' if overlay else 'broll',
                'visual':case['required_change'],'components':refs,'reason':'独立开发样片的明确语义任务'})
            treatment['motion_queries'].append({'segment_id':sid,'component_id':cid,
                'tags':case.get('query_tags',['并列','过程'] if overlay else ['疲劳','过程'])})
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
        from edit.hd.tests.test_motion_match_cache import bind_review_fixture
        design={'composition':'隔离fixture原生整屏过程','typography':'沿用原生示例中文',
                'finish':'沿用原生示例色彩材质','focus':'验证当前过程工程执行到媒体'}
        for beat in [*treatment['skill_selection']['beats'],*treatment['skill_selection']['overlay_beats']]:
            key=(beat['segment_id'],beat['component_id'])
            selected=next(case for case in self.case['segments'] if case['segment_id']==key[0])
            dependency=selected['dependency_id']
            wanted=('overlay:' if dependency=='barty-motion-graphics' else dependency+':')+dependency+'/'+selected['template_id']
            isolated = self.case.get('stop_at_preview')
            if isolated:
                beat['single_source_review'] = {'decision': 'keep', 'reason': '本测试验证指定原生配方的实际调用。'}
            beat['candidates']=[{'candidate_id':item['candidate']['candidate_id'],
                'fit':('preferred' if item['candidate']['candidate_id']==wanted else
                       'unsuitable' if isolated else 'equivalent'),
                'reason':'隔离技术样片要求使用为本镜准备的指定原生配方', 'visual_pattern':'native-'+beat['segment_id'],
                'design_plan':design,
                **({'rejection_basis': 'semantic', 'constraint_refs': {'requirement': 'semantic', 'capability': 'summary'}}
                   if isolated and item['candidate']['candidate_id'] != wanted else {}),
                **({'cinecode_input':selected['prepared_cinecode_input']}
                   if item['candidate']['candidate_id'] == wanted and 'prepared_cinecode_input' in selected else {})}
                for item in cached[key]['matches']]
        bind_review_fixture(treatment, cached)
        treatment['skill_selection']=broll_skill_selection.assign_skills(
            _env.PROJECT,treatment['skill_selection'],job_dir=root,director=director,treatment=treatment)
        self.assertEqual([a['skill_id'] for a in treatment['skill_selection']['assignments']],
            [c['dependency_id'] for c in self.case['segments'] if c['dependency_id']!='barty-motion-graphics'])
        self.assertEqual([a['skill_id'] for a in treatment['skill_selection']['overlay_assignments']],
            [c['dependency_id'] for c in self.case['segments'] if c['dependency_id']=='barty-motion-graphics'])
        return director,treatment

    def _render(self, action):
        root=self.job.job_dir;request=Path(action['brief_path']);b=native.validate_brief(request.read_bytes())
        case=next(c for c in self.case['segments'] if c['segment_id']==action['segment_id'])
        source=self.samples/'source-case'/case['source_project']
        if not source.is_dir():raise ValueError('Prepare the complete native authored project first: '+str(source))
        directory=Path(action['project_directory']);shutil.copytree(source,directory)
        runtime=action['runtime']
        if runtime['status']=='pending':
            runtime=json.loads(subprocess.check_output(runtime['check_argv'], text=True))
        if 'node_modules' in runtime:
            (directory/'node_modules').symlink_to(runtime['node_modules'],target_is_directory=True)
        if b['dependency_id']=='barty-motion-graphics':
            builder=native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/build.py'
            fragment=case['fragment_html'];html=directory/case['entry_html']
            subprocess.run([sys.executable,str(builder),str(html.parent),fragment],cwd=directory,check=True,capture_output=True)
            output=directory/'out/native.mov';output.parent.mkdir()
            argv=[runtime['tools']['node'],str(native.source_root(dependency_id=b['dependency_id'])/'skills/motion-broll/engine/render.js'),str(html),str(output),'24']
        elif b['dependency_id']=='bang-motion':
            shutil.copyfile(native.source_root(dependency_id=b['dependency_id'])/'scripts/export-frames.mjs',directory/'export-frames.mjs')
            argv=[runtime['tools']['node'],'export-frames.mjs',case['entry_html'],'out/native.mp4']
        elif b['dependency_id']=='mg-styles-15':
            (directory/'harness').mkdir(exist_ok=True)
            shutil.copyfile(native.source_root(dependency_id=b['dependency_id'])/'harness/render.mjs',directory/'harness/render.mjs')
            argv=[runtime['tools']['node'],'harness/render.mjs','scene','--out','out/native.mp4',
                  '--w','1080','--h','1920','--fps','24','--duration',str(b['composition']['frames']/24),
                  '--workers','1','--noaudio']
        elif b['dependency_id']=='cinecode':
            argv=[runtime['tools']['node'],*action['capture_argv'][1:]]
            argv[3]=case['entry_html']
        elif b['dependency_id']=='video-shotcraft':
            argv=[runtime['tools']['node'],str(Path(runtime['node_modules'])/'@remotion/cli/remotion-cli.js'),
                  'render','src/index.ts','NativeScene','out/native.mp4','--codec=h264','--pixel-format=yuv420p',
                  '--color-space=bt709','--image-format=png','--muted','--concurrency=1',
                  '--browser-executable='+runtime['browser'],'--bundle-cache=false']
        elif b['dependency_id']=='bb-video':
            workflow=case.get('native_workflow', 'promo')
            argv=[runtime['tools']['node'],str(native.source_root(dependency_id='bb-video')/
                  'skills/bb-video'/workflow/'scripts/render.mjs'),str(directory),
                  '--aspect','9:16','--fps','24','--from','0','--to',str(b['composition']['frames']/24),
                  '--no-audio','--no-bgm','--workers','1','--out','native.mp4']
        else:
            raise ValueError('Unsupported native smoke dependency')
        preparations=None
        if b['dependency_id']=='mg-styles-15' and b['template_id']=='3d-render':
            preparations=[{'argv':[action['native_preparation_runtime']['blender'],
                '--background','--factory-startup','--python','blender/scene.py'],
                'inputs':[(Path(b['project_directory'])/name).as_posix()
                          for name in case['native_preparation_inputs']],
                'outputs':[(Path(b['project_directory'])/name).as_posix()
                           for name in case['native_preparation_outputs']]}]
        call=native.capture_render(root,request,argv,native_preparations=preparations)
        options={}
        if b['dependency_id'] in {'video-shotcraft', 'cinecode'}:
            options['native_usage']=[{**usage,'implementation_refs':[
                native.descriptor(root,directory/relative) for relative in usage['implementation_paths']]}
                for usage in case['native_usage']]
            for usage in options['native_usage']:
                usage.pop('implementation_paths')
        native.publish_completed(root,request,call,**options)
        return native.inspect_result(root,request.read_bytes())

    def test_native_motion_from_complete_list_to_native_executor(self):
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
        review.update(user_confirmation='本次已授权按固定计划执行独立免费本地制作链验证；不继承旧验收，不做付费调用。')
        run_stage._review(self.job,'visual_direction',review);self.job=state.load_job(root)
        approved=confirmation.validate_visual_authorization(self.job)['source']
        director=artifacts.read_json_artifact(confirmation._exact(root,approved['inputs']['director']))
        treatment=artifacts.read_json_artifact(confirmation._exact(root,approved['inputs']['treatment']))
        pending=run_stage.resume_visual_direction(self.job,_env.PROJECT,{})
        self.assertEqual([a['dependency_id'] for a in pending['actions']],
                         [c['dependency_id'] for c in self.case['segments']])
        self.assertTrue(all(a['action']=='execute_native_skill' for a in pending['actions']))
        native_results=[self._render(action) for action in pending['actions']]
        run_stage.resume_visual_direction(self.job,_env.PROJECT,{'realization':{
            'director_brief':'director.json','treatment':'treatment.json'}})
        self.job=state.load_job(root)
        self.assertEqual(self.job.stages['visual_direction']['status'], 'completed')
        confirmation.validate_visual_authorization(self.job, require_realized=True)
        numbered = confirmation.approved_numbered_rows(self.job)
        self.assertTrue(numbered)
        self.assertEqual([row['number'] for row in numbered], list(range(1, len(numbered) + 1)))
        if self.case.get('stop_at_preview'):
            for stage in ('visual_assets', 'subtitles', 'preview'):
                result = run_stage.execute_stage(root, _env.PROJECT, stage)
                self.assertEqual(result['status'], 'completed', result)
            preview = next(root / item['path'] for item in result['artifacts'] if item['path'].endswith('.mp4'))
            metadata = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error',
                '-show_streams', '-of', 'json', str(preview)], text=True))
            self.assertEqual({stream['codec_type'] for stream in metadata['streams']}, {'video', 'audio'})
            artifacts.write_json_artifact(self.root/'stage-smoke-result.json', {
                'scope':'explicitly chosen native routes through the parent preview',
                'input_provenance':self.case['input_provenance'], 'native_results':native_results,
                'preview':str(preview), 'numbered_rows':numbered, 'manual_acceptance_performed':False})
            print('Native stage smoke completed:',self.root/'stage-smoke-result.json',flush=True)
            return
        delivered = run_stage.execute_stage(root, _env.PROJECT)
        self.assertEqual(delivered['status'], 'completed', delivered)
        self.assertTrue(all(stage['status'] == 'completed'
            for stage in state.load_job(root).stages.values()))
        self.assertEqual(delivered['delivery_status'], 'delivered')
        from edit.hd.tools import delivery_approval
        manifest = next(row for row in state.load_job(root).stages['delivery']['artifacts']
                        if row['path'] == '12-delivery/delivery-manifest.json')
        receipt, acceptance = delivery_approval.receipt_paths(manifest)
        record = artifacts.read_json_artifact(root / receipt)
        self.assertEqual(record['decision'], 'delivered')
        final = Path(delivered['delivery_file'])
        metadata = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error',
            '-show_streams', '-show_format', '-of', 'json', str(final)], text=True))
        self.assertTrue(any(stream['codec_type'] == 'video' for stream in metadata['streams']))
        self.assertTrue(any(stream['codec_type'] == 'audio' for stream in metadata['streams']))
        self.assertFalse((root / acceptance).exists())
        self.assertFalse(list((root / '08-visual-canary').glob('**/*.*')))
        artifacts.write_json_artifact(self.root/'stage-smoke-result.json', {
            'scope':'fixed local production plan to native render, subtitles, composition, delivery',
            'input_provenance':self.case['input_provenance'], 'native_results':native_results, 'final':str(final),
            'delivery_status':'delivered','acceptance_status':'pending', 'numbered_rows':numbered,
            'new_asr_calls':0,'new_generated_media_calls':0,'manual_acceptance_performed':False})
        print('Native stage smoke completed:',self.root/'stage-smoke-result.json',flush=True)


if __name__=='__main__':unittest.main()

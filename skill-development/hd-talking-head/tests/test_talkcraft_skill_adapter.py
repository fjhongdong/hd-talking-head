"""Contracts for the complete native Skill boundary; no render or paid calls."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import wave
from unittest import mock

import _env
import talkcraft_skill_adapter as native


def brief():
    return {'schema_version':1,'job_id':'native-test','source_binding':{'aroll_sha256':'a'*64,'segment_id':'seg-001','start':0,'end':2},
            'composition':{'width':1080,'height':1920,'fps':24,'frames':48},
            'template_request':{'semantic_family':'source_convergence','information_units':3,'numeric_values':[],'numeric_scale':'not_applicable'},
            'card_id':'source-converge','semantic_goal':'真实资料汇聚','transcript':'合同年报项目材料',
            'word_anchors':[{'text':'合同年报项目材料','start':0,'end':2}],
            'speech':{'job_path':'voice.wav','sha256':hashlib.sha256(b'voice').hexdigest(),'byte_count':5},
            'materials':[],'authorization':{'paid_generation':False},
            'project_directory':'native-projects/native-test','result_record_path':'native-inputs/native-test/result.json'}


class TalkCraftSkillTests(unittest.TestCase):
    def test_complete_original_source_and_all_recipe_roles(self):
        root=native.source_root(_env.PROJECT)
        self.assertTrue((root/'scripts/render_shots.mjs').is_file())
        rows=native.load_card_catalog(_env.PROJECT)
        self.assertEqual(len(rows),108)
        self.assertEqual(sum(row['native_role']=='scene' for row in rows),51)
        self.assertEqual({row['native_role'] for row in rows},{'scene','overlay','annotation','transition','camera'})
        self.assertTrue(all('/upstream/template/cards/' in row['source'] for row in rows))

    def test_native_task_passes_inputs_and_output_spec_without_parent_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with wave.open(str(root/'voice.wav'),'wb') as audio:
                audio.setparams((1,2,16000,0,'NONE','not compressed'));audio.writeframes(b'\0'*64000)
            source_video=root/'aroll.mp4';source_video.write_bytes(b'approved source identity fixture')
            payload=brief();payload['source_binding'].update(start=14.25,end=16.25,aroll_sha256=native.sha(source_video));payload['speech']=native.descriptor(root,root/'voice.wav')
            p=root/'brief.json';p.write_text(json.dumps(payload))
            job=SimpleNamespace(job_dir=root,job_id='native-test')
            action=native.native_task(job,{'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(p)},p)
            self.assertEqual(action['action'],'execute_native_skill')
            self.assertTrue(action['requirements']['silent'])
            self.assertEqual(action['speech_window'],{'start':0,'end':2})
            self.assertEqual(action['source_binding']['start'],14.25)
            director={'segments':[{'segment_id':'seg-001','start':14.25,'end':16.25,'bindings':{'scene':{
                'dependency_id':'video-talkcraft','template_id':'video-talkcraft/source-converge','brief_sha256':native.sha(p)}}}]}
            treatment={'scenes':[{'segment_id':'seg-001','component_id':'scene','brief_path':'brief.json'}]}
            with mock.patch('edit.hd.tools.visual_plan._approved_artifact',return_value=source_video):
                native.validate_selected_inputs(job,director,treatment)
                director['segments'][0]['start']=14
                with self.assertRaisesRegex(ValueError,'approved source'):
                    native.validate_selected_inputs(job,director,treatment)
            self.assertEqual(action['requirements']['word_anchors'],brief()['word_anchors'])
            self.assertFalse(set(action['requirements']) & {'design_plan','beats','composition','creative_handoff','complete_source_first_frame'})
            changed=brief();changed['design_plan']={}
            with self.assertRaisesRegex(ValueError,'native task brief'):
                native.validate_brief(json.dumps(changed))

    def test_clock_and_recipe_identity_are_checked_without_arbitrary_duration_ceiling(self):
        payload=brief();payload['composition']['frames']=47
        with self.assertRaisesRegex(ValueError,'clock'):
            native.validate_brief(json.dumps(payload))
        payload=brief();payload['card_id']='../not-a-recipe'
        with self.assertRaisesRegex(ValueError,'recipe identity'):
            native.validate_brief(json.dumps(payload))
        payload=brief();payload['source_binding']['end']=90;payload['composition']['frames']=2160
        self.assertEqual(native.validate_brief(json.dumps(payload))['composition']['frames'],2160)

    def test_production_load_requires_exact_reviewed_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'native-inputs/native-test/result.json';p.parent.mkdir(parents=True);p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'descriptor'):
                native.load_result(root,json.dumps(brief()),expected_record={'path':'wrong.json','sha256':'a'*64,'bytes':2},expected_renderer_version='4.0.519')
            with self.assertRaisesRegex(ValueError,'reviewed version'):
                native.load_result(root,json.dumps(brief()),expected_record={'path':brief()['result_record_path'],'sha256':'a'*64,'bytes':2},expected_renderer_version='4.0.519')

    def test_original_locked_runtime_is_ready_outside_native_source(self):
        from prepare_talkcraft_native import check
        runtime=check(_env.PROJECT)
        self.assertEqual(runtime['renderer_version'],'4.0.519')
        self.assertTrue(Path(runtime['runtime_root']).is_relative_to(_env.PROJECT/'skill-development/runtime'))
        self.assertNotIn('/integrations/talkcraft/runtime',runtime['node_modules'])

    def test_manifest_probe_matches_exact_registered_protocol(self):
        import dependency_preflight
        manifest = json.loads((_env.SKILL / 'references/dependency-manifest.json').read_bytes())
        item = next(row for row in manifest['dependencies'] if row['id'] == 'video-talkcraft')
        selected = {'dependency_id': 'video-talkcraft', 'entrypoint': native.ENTRY,
                    'producer_version': native.VERSION, 'executor': 'reference_adapter', 'primary_renderer': 'Remotion'}
        result = dependency_preflight._check_binding_probe(item, selected, project_root=_env.PROJECT,
                    reference_root=_env.PROJECT, dependency_root=_env.SKILL)
        self.assertEqual(result['status'], 'bound', result)

    def test_capture_rejects_cached_segments_and_foreign_segment_directory_before_launch(self):
        from prepare_talkcraft_native import check
        runtime = check(_env.PROJECT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = brief()
            request = root / 'brief.json'; request.write_text(json.dumps(payload))
            project = root / payload['project_directory']; (project / 'remotion/out/segments').mkdir(parents=True)
            (project / 'remotion/out/segments/old.mp4').write_bytes(b'old cached render')
            (project / 'remotion/node_modules').symlink_to(runtime['node_modules'], target_is_directory=True)
            argv = [runtime['tools']['node'], str(native.source_root() / native.NATIVE_RENDER), '--concat', 'out/new.mp4']
            with mock.patch.object(native, '_inputs'), mock.patch('prepare_talkcraft_native.check', return_value=runtime), mock.patch.object(native.subprocess, 'run') as launch:
                with self.assertRaisesRegex(ValueError, 'requires --all'):
                    native.capture_render(root, request, argv)
                with self.assertRaisesRegex(ValueError, 'current native project'):
                    native.capture_render(root, request, argv + ['--all', '--seg-dir', str(root / 'old-segments')])
                launch.assert_not_called()

    def test_frozen_producer_version_cannot_be_relabelled_by_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/brief()['result_record_path'];p.parent.mkdir(parents=True);p.write_bytes(b'{}')
            expected={'path':brief()['result_record_path'],'sha256':native.sha(p),'bytes':2}
            with mock.patch.object(native,'inspect_result',return_value={'renderer_version':'4.0.520'}):
                with self.assertRaisesRegex(ValueError,'frozen component'):
                    native.load_result(root,json.dumps(brief()),expected_record=expected,expected_renderer_version='4.0.519')


if __name__=='__main__':unittest.main()


class TalkCraftStageFlowTests(unittest.TestCase):
    """Real two-stage gates with existing native media; native rendering is not repeated."""
    def setUp(self):
        from test_wake_native import WakeNativeTests
        WakeNativeTests.setUp(self)

    def flow_draft(self):
        from test_wake_native import WakeNativeTests
        return WakeNativeTests.flow_draft(self)

    def test_confirm_then_create_then_accept_actual_scene(self):
        import copy
        import shutil
        import subprocess
        import sys
        import run_stage
        import lemo_wake_adapter as wake
        from edit.hd.tools import state, contract_artifacts as artifacts, motion_capabilities as motion
        from edit.hd.tools import motion_match_cache, broll_skill_selection, visual_confirmation as confirmation
        from edit.hd.tools import broll_component_executor as executor, visual_canary, visual_plan
        from edit.hd.tests.test_startup import approve_fixture_setup
        from test_wake_native import SAMPLE
        root = self.job.job_dir
        # Extend only the temporary approved input by stream-copying existing fixture media.
        concat = root / 'fixture-inputs.txt'
        source = SAMPLE / '06-edit-structure/edited-aroll.mp4'
        concat.write_text("file '" + str(source) + "'\nfile '" + str(source) + "'\n")
        edited = root / '06-edit-structure/edited-aroll.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-f', 'concat', '-safe', '0',
                        '-i', str(concat), '-c', 'copy', str(edited)], check=True, capture_output=True)
        artifacts.write_json_artifact(root / '06-edit-structure/timeline-map.json', {'output_duration': 12, 'segments': [
            {'source_start': 0, 'source_end': 12, 'timeline_start': 0, 'timeline_end': 12}]})
        script = (self.root / 'script.md').read_text()
        artifacts.write_json_artifact(root / '05-speech-cleanup/word-transcript.json', {'version':1,'words':[
            {'text':script,'start':0,'end':6},{'text':script,'start':6,'end':12}]})
        workflow = json.loads((root / 'workflow.json').read_bytes())
        for stage in ('speech_cleanup','edit_structure'):
            for item in workflow['stages'][stage]['artifacts']:
                file = root / item['path']; item.update(sha256=native.sha(file), bytes=file.stat().st_size)
        artifacts.write_json_artifact(root / 'workflow.json', workflow)
        self.job = state.load_job(root)
        # Rebind copied Wake fixture command records to this temporary edited input.
        self.brief['source_binding']['aroll_sha256'] = native.sha(edited)
        artifacts.write_json_artifact(root / 'native-inputs/brief.json', self.brief)
        self.payload = (root / 'native-inputs/brief.json').read_bytes()
        wake_result = json.loads((root / self.brief['result_record_path']).read_bytes())
        wake_result['request_sha256'] = hashlib.sha256(self.payload).hexdigest()
        for desc in wake_result['calls']:
            call_path = root / desc['job_path']; call = json.loads(call_path.read_bytes())
            call['request_sha256'] = wake_result['request_sha256']; artifacts.write_json_artifact(call_path, call)
            desc.update(native.descriptor(root, call_path))
        artifacts.write_json_artifact(root / self.brief['result_record_path'], wake_result)
        director, treatment = self.flow_draft()
        script = (self.root / 'script.md').read_text()
        payload = brief(); payload.update(job_id=self.job.job_id, transcript=script,
            semantic_goal='资料汇聚', composition={'width':1080,'height':1920,'fps':24,'frames':144},
            word_anchors=[{'text':script,'start':0,'end':6}])
        payload['source_binding'].update(aroll_sha256=native.sha(edited),segment_id='seg-002',start=6,end=12)
        voice = root / 'voice.wav'
        with wave.open(str(voice), 'wb') as audio:
            audio.setparams((1,2,16000,0,'NONE','not compressed')); audio.writeframes(b'\0'*192000)
        payload['speech'] = native.descriptor(root, voice)
        request = root / 'native-inputs/talkcraft-brief.json'; artifacts.write_json_artifact(request, payload)
        raw = request.read_bytes()
        adapter = native.create_adapter(_env.PROJECT, sys.executable, lambda *_: raw)
        binding = native.create_binding(adapter, raw, SAMPLE / 'native-sample.mp4')
        segment = copy.deepcopy(director['segments'][0]); segment.update(segment_id='seg-002',start=6,end=12)
        segment['visual_strategy']['segment_id']='seg-002'
        segment['visual_intent']['segment_id']='seg-002'
        segment['visual_strategy']['components'][0]['component_id']='component-2'
        segment['visual_strategy']['composition']['reading_order']=['component-2']
        segment['bindings']={'component-2':binding}; director['segments'].append(segment)
        treatment['scenes'].append({'segment_id':'seg-002','component_id':'component-2','brief_path':'native-inputs/talkcraft-brief.json'})
        row = copy.deepcopy(treatment['semantic_lists']['broll'][0]); row.update(row_id='native-semantic',start_word=1,end_word=2,semantic='资料汇聚',visual_task='资料原生汇聚场景',components=[{'segment_id':'seg-002','component_id':'component-2'}])
        treatment['semantic_lists']['broll'].append(row)
        beat = copy.deepcopy(treatment['beat_sheet'][0]); beat.update(start_word=1,end_word=2,components=row['components'])
        treatment['beat_sheet'].append(beat)
        treatment['motion_queries'].append({'segment_id':'seg-002','component_id':'component-2','tags':['汇聚']})
        assessment={'segment_id':'seg-002','component_id':'component-2','candidate_id':'video-talkcraft:source-converge','verdict':'pass','reason':'本段原声和资料汇聚目标对应',
            'transcript_refs':[{'start_word':1,'end_word':2,'quote':script,'basis':'current_clause'}],
            'content_refs':[{'path':'native-inputs/talkcraft-brief.json','sha256':native.sha(request),'pointer':'/'+key,'value':payload[key]} for key in ('transcript','semantic_goal','card_id')]}
        treatment['semantic_assessments'].append(assessment)
        treatment=motion_match_cache.match_once(_env.PROJECT,director,treatment)
        cached=motion_match_cache.validate_matches(_env.PROJECT,director,treatment)[('seg-002','component-2')]
        review=copy.deepcopy(treatment['skill_selection']['beats'][0]); review.update(segment_id='seg-002',component_id='component-2',semantic_row_id='native-semantic',start=6,end=12,semantic_goal='资料汇聚',required_change='资料原生汇聚场景',binding_snapshot=binding)
        for v in review['skill_reviews'].values():v.update(fit='equivalent',reason='临时流程fixture评审')
        design=review['candidates'][0]['design_plan']
        review['candidates']=[{'candidate_id':m['candidate']['candidate_id'],'fit':'preferred' if m['candidate']['candidate_id']=='video-talkcraft:source-converge' else 'equivalent',
            'reason':'临时流程fixture语义评审','visual_pattern':'source-convergence','design_plan':design} for m in cached['matches']]
        treatment['skill_selection']['beats'].append(review)
        treatment['skill_selection']=broll_skill_selection.assign_skills(_env.PROJECT,treatment['skill_selection'],job_dir=root)
        selected=treatment['skill_selection']['assignments'][-1]
        self.assertEqual(selected['candidate_id'],'video-talkcraft:source-converge')
        treatment['motion_readability'].append({'segment_id':'seg-002','component_id':'component-2','targets':[],
            'no_critical_text_reason':'本fixture只验证阶段门，不进行原生创作文字的视觉验收'})
        approve_fixture_setup(self.job)
        artifacts.write_json_artifact(root/'manifests/confirmed-content.json',{'schema_version':1,'job_id':self.job.job_id,'source_words':[{'index':0,'text':script}],
            'visuals':[{'component_id':'component-1','composition_family':'single_full_frame','visible_text':[],'binding':director['segments'][0]['bindings']['component-1']}]})
        dpath=root/'director.json'; tpath=root/'treatment.json'
        artifacts.write_json_artifact(dpath,director);artifacts.write_json_artifact(tpath,treatment)
        run_stage.run_visual_direction(root,_env.PROJECT,dpath,tpath)
        self.job=state.load_job(root)
        review={k:copy.deepcopy(v) for k,v in run_stage._summary(self.job,'visual_direction').items() if k in {'job_id','job_dir','stage','revision','artifacts'}}
        review.update(passed=True,note='隔离fixture完整清单确认',user_confirmation='隔离fixture批准，只测试阶段门')
        run_stage._review(self.job,'visual_direction',review);self.job=state.load_job(root)
        pending=run_stage.resume_visual_direction(self.job,_env.PROJECT,{})
        self.assertEqual([a['dependency_id'] for a in pending['actions']],['video-talkcraft'])
        self.assertEqual(pending['actions'][0]['speech_window'],{'start':0,'end':6})
        # Simulate native completion with existing media and original recipe source; do not render.
        project=root/payload['project_directory'];(project/'remotion/src/cards').mkdir(parents=True)
        shutil.copyfile(native.source_root()/'template/cards/source-converge.tsx',project/'remotion/src/cards/source-converge.tsx')
        (project/'SHOTBOOK.md').write_text('# 资料汇聚\n'+script)
        (project/'remotion/src/entry.tsx').write_text('export {SourceConverge as default} from "./cards/source-converge";')
        output=project/'remotion/out/native.mp4';output.parent.mkdir();shutil.copyfile(SAMPLE/'native-sample.mp4',output)
        record=root/payload['result_record_path'];record.parent.mkdir(parents=True)
        from prepare_talkcraft_native import check
        runtime=check(_env.PROJECT);package=record.parent/'renderer-package.json'
        shutil.copyfile(Path(runtime['node_modules'])/'@remotion/renderer/package.json',package)
        call_path=record.parent/'render-call.json'
        call={'schema_version':1,'request_sha256':native.sha(request),'upstream_commit':native.UPSTREAM_COMMIT,'native_script_sha256':native.sha(native.source_root()/native.NATIVE_RENDER),
            'argv':[runtime['tools']['node'],str(native.source_root()/native.NATIVE_RENDER),'--all','--concat','out/native.mp4'],
            'working_directory':payload['project_directory']+'/remotion','project_files':native.project_files(root,project),'output':output.relative_to(root).as_posix(),
            'renderer_version':runtime['renderer_version'],'renderer_package':native.descriptor(root,package),'exit_code':0,'stdout':'isolated completion fixture, existing media','stderr':''}
        artifacts.write_json_artifact(call_path,call)
        native.publish_completed(root,request,call_path,qa_note='隔离阶段fixture，复用既有媒体，不执行原生渲染')
        with self.assertRaisesRegex(visual_plan.VisualPlanError,'motion semantic/native input check'):
            visual_plan._skill_selection_for_publication(self.job,director,tpath)
        completed=motion._bound_brief(root,treatment,segment,'component-2')['native_result']
        assessment['content_refs']=[]
        for item in [completed['shotbook'],*completed['scene_sources']]:
            assessment['content_refs'].append({'path':item['job_path'],'sha256':item['sha256'],'quote':(root/item['job_path']).read_text().splitlines()[0]})
        assessment['content_refs'].append({'path':payload['result_record_path'],'sha256':native.sha(record),'pointer':'/status','value':'completed'})
        # match_once returns a deep copy; update the current assessment object.
        treatment['semantic_assessments'][-1]=assessment
        artifacts.write_json_artifact(tpath,treatment)
        self.assertEqual(visual_plan._skill_selection_for_publication(self.job,director,tpath)['motion_review']['status'],'pass')
        run_stage.resume_visual_direction(self.job,_env.PROJECT,{'realization':{'director_brief':'director.json','treatment':'treatment.json','host_qa_note':'隔离fixture完成后真实工程引用核对'}})
        self.job=state.load_job(root);confirmation.validate_visual_authorization(self.job,require_realized=True)
        plan=visual_canary.load_approved_visual_plan(self.job);recipe=plan['segments'][1]['shot_recipe']
        result=executor.execute_component(self.job,executor.ComponentExecutionRequest(recipe=recipe,component_id='component-2'),adapters=run_stage.native_component_adapters(_env.PROJECT,self.job))
        self.assertEqual(result.status,'success');self.assertEqual(result.output_sha256,native.sha(output))

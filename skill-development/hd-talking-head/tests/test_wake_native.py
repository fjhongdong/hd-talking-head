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

SAMPLE = SKILL / 'assets/wake-native-smoke'

class WakeNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = fixture._Job(self.root)
        shutil.copytree(SAMPLE, self.job.job_dir, dirs_exist_ok=True)
        self.job.job_id = 'wake-native-smoke'
        self.payload = (self.job.job_dir / 'native-inputs/brief-v3.json').read_bytes()
        self.brief = wake.validate_brief(self.payload)

    def setup_component(self):
        adapter = wake.create_adapter(PROJECT, sys.executable, lambda *_: self.payload)
        binding = wake.create_binding(adapter, self.payload, SAMPLE / 'native-smoke-v3.mp4')
        c = fixture._code_component(self.payload, dependency_id='lemo-wake')
        c.update(binding)
        c['executor']='reference_adapter'
        c['render_window']['end_frame'] = 144
        c['artifact_contract']['alpha'] = False
        recipe = fixture._recipe([c]);recipe['segment_id'] = 'seg-opening'
        recipe['composition']['presenter_mode'] = 'hidden'
        segment = {'segment_id': 'seg-opening', 'start': 0, 'end': 6, 'shot_recipe': recipe}
        return adapter, c, recipe, segment

    def test_native_result_reaches_public_executor_without_rerendering(self):
        adapter, c, recipe, segment = self.setup_component()
        router.validate_template_binding(c)
        request = executor.ComponentExecutionRequest(recipe=recipe, component_id=c['component_id'])
        with mock.patch('edit.hd.tools.visual_canary.load_approved_visual_plan', return_value={'segments': [segment]}), \
             mock.patch('edit.hd.tools.visual_canary.approved_aroll_record', return_value={'sha256': self.brief['source_binding']['aroll_sha256']}):
            artifact = executor.execute_component(self.job, request, adapters={
                'code_generated': {'lemo-wake': adapter},
                'artifact_probe': wake.create_artifact_probe(ffprobe_executable=shutil.which('ffprobe'))})
        self.assertEqual(artifact.status, 'success')
        self.assertEqual(artifact.output_sha256, wake.sha(SAMPLE / 'native-smoke-v3.mp4'))
        self.assertEqual(wake.probe(self.job.job_dir / artifact.job_path)['frames'], 144)

    def draft(self):
        adapter, c, recipe, segment = self.setup_component()
        strategy=valid_strategy([strategy_component(component_id=c['component_id'], kind='code_generated')], segment_id='seg-opening')
        strategy['composition']['presenter_mode']='hidden'
        intent=valid_intent(segment_id='seg-opening',presenter_presence='hidden')
        visual_strategy.validate_visual_strategy(intent,strategy)
        segment.update(visual_intent=intent, visual_strategy=strategy,
            bindings={c['component_id']: wake.create_binding(adapter, self.payload, SAMPLE / 'native-smoke-v3.mp4')})
        treatment = {'scenes': [{'segment_id': 'seg-opening', 'component_id': c['component_id'],
                               'brief_path': 'native-inputs/brief-v3.json'}],
                     'skill_selection': {'opening': {'segment_id': 'seg-opening',
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
        self.assertEqual(action['requirements']['transcript'],'先按语义')

    def test_approved_cover_and_first_clock_are_mandatory(self):
        director, treatment = self.draft()
        cover = self.job.job_dir / '04-cover/cover-delivery-raster.png'
        cover.parent.mkdir();shutil.copyfile(self.job.job_dir / 'source.png', cover)
        b = copy.deepcopy(self.brief);b['image'] = wake.descriptor(self.job.job_dir, cover)
        raw = json.dumps(b).encode();brief_path=self.job.job_dir/'native-inputs/brief-v3.json';brief_path.write_bytes(raw)
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
        image={'path':'source.png','sha256':self.brief['image']['sha256'],'image':True}
        assessment={'segment_id':'seg-opening','component_id':'code','candidate_id':'lemo-wake:wake',
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
        self.assertEqual(wake.load_result(self.job.job_dir,self.payload)['status'],'completed')
        result=self.job.job_dir/self.brief['result_record_path'];r=json.loads(result.read_bytes());r['media_probe']['frames']=143
        result.write_text(json.dumps(r))
        with self.assertRaises(ValueError):wake.load_result(self.job.job_dir,self.payload)
        b=copy.deepcopy(self.brief);b['composition']['frames']=143
        with self.assertRaises(ValueError):wake.validate_brief(json.dumps(b))

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

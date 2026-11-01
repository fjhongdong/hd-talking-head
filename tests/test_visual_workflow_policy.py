"""Regression coverage for grouping, persistent numbers, and current-media QA."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import PROJECT, SKILL
sys.path.insert(0, str(SKILL / 'scripts'))
import run_stage
from test_avatar_profile import avatar_fixture
from edit.hd.tools import avatar_profile as ap, contract_artifacts as ca
from edit.hd.tools import preview_v2 as preview, visual_confirmation as vc, visual_review as vr


def segment(sid, start, end, avatar=False, overlay=False):
    comp = {'presenter_mode': 'bottom_window' if avatar else 'full_frame'}
    if avatar:
        comp['avatar'] = avatar_fixture(frames=round((end-start)*24))
    return {'segment_id': sid, 'start': start, 'end': end,
            'visual_strategy': {'composition': comp, 'components': [{}] if overlay else []}}


class PlanningAndNumberTests(unittest.TestCase):
    def test_default_groups_are_complete_and_omission_is_rejected(self):
        source = [segment('a',0,2), segment('b',2,3,True),
                  segment('c',3,4,True), segment('d',4,6)]
        planned = ap.plan_avatar_policy(source)['segments']
        first, last = [s['visual_strategy']['composition']['avatar'] for s in planned[1:3]]
        self.assertIn('entrance',first); self.assertTrue(first['continuation'])
        self.assertNotIn('entrance',last); self.assertIn('exit',last)
        self.assertNotIn('continuation',last)
        ap.validate_avatar_plan_policy(planned)
        self.assertNotIn('entrance',source[1]['visual_strategy']['composition']['avatar'])
        del first['entrance']
        with self.assertRaises(ValueError): ap.validate_avatar_plan_policy(planned)
        boundary = ap.plan_avatar_policy([segment('only',0,1,True)])['segments']
        self.assertFalse(any(k in boundary[0]['visual_strategy']['composition']['avatar']
                             for k in ('entrance','exit','continuation')))
        with self.assertRaises(ValueError):
            ap.plan_avatar_policy([segment('a',0,2),segment('tiny',2,2.5,True),segment('c',2.5,4)])

    def test_short_gap_stops_before_dependencies_and_freezing(self):
        draft = {'segments':[segment('left',0,1,True),segment('gap',1,1.5),segment('right',1.5,2.5,True)]}
        action = ap.plan_avatar_policy(draft['segments'])['actions'][0]
        self.assertEqual((action['left_segment_id'],action['target_start'],action['target_end']),('left',0,1.5))
        self.assertEqual(action['absorbed_segment_ids'],['gap'])
        with self.assertRaises(ValueError): ap.validate_avatar_plan_policy(draft['segments'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'draft.json').write_text(json.dumps(draft))
            job=SimpleNamespace(job_dir=root)
            with mock.patch('edit.hd.tools.state.load_job',return_value=job), \
                 mock.patch.object(run_stage,'_summary',side_effect=lambda j,s,**kw:kw), \
                 mock.patch.object(run_stage,'prepare_visual_dependencies') as dependencies, \
                 mock.patch.object(vc,'prepare_visual_confirmation') as freeze:
                result=run_stage.run_visual_direction(root,PROJECT,Path('draft.json'),Path('treatment.json'))
            self.assertIs(result['prepared'],False)
            dependencies.assert_not_called();freeze.assert_not_called()
            self.assertFalse((root/'07-visual-confirmation').exists())
        protected=copy.deepcopy(draft['segments']);protected[1]['visual_strategy']['components']=[{}]
        protected[2]=segment('right',1.5,3.5,True)
        self.assertFalse(ap.plan_avatar_policy(protected)['actions'])
        complete=[segment('left',0,1,True),segment('cut1',1,1.25),segment('cut2',1.25,2.25),segment('right',2.25,4.25,True)]
        self.assertFalse(ap.plan_avatar_policy(complete)['actions'])

    def test_approved_numbering_survives_delete_and_reorder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifests').mkdir();job=SimpleNamespace(job_dir=root,job_id='job',revision=10)
            p=root/'proposal.json';ca.write_json_artifact(p,{'kind':vc.SCHEMA,'job_id':'job','job_dir':str(root),
                'numbering_scope_id':'current-scope',
                'rows':[{'row_id':'b'}],'numbering':{'a':1,'b':2,'retired':3}})
            ref={'path':'proposal.json','sha256':ca.sha256_file(p),'bytes':p.stat().st_size}
            receipt={'source_schema':vc.SCHEMA,'job_id':'job','job_dir':str(root),'stage':'visual_direction',
                     'passed':True,'reviewed_by':'human','approval_scope':'visual_plan_and_delivery','revision':9,'source':ref}
            ca.write_json_artifact(root/'manifests/local-qa-visual_direction-r9.json',receipt)
            mapping=vc._prior_numbering(job,'current-scope')
            self.assertEqual([r['number'] for r in vc.number_visual_rows([{'row_id':'new'},{'row_id':'b'}],mapping)],[4,2])
            p.write_text('{}')
            with self.assertRaises(ValueError):vc._prior_numbering(job,'current-scope')
        with self.assertRaises(ValueError):vc.number_visual_rows([{'row_id':'a'}],{'a':1,'b':1})

    def test_badge_slots_follow_identity_and_half_open_time(self):
        rows=[{'row_id':'late','number':3,'start':1,'end':2},
              {'row_id':'early','number':1,'start':0,'end':1},
              {'row_id':'other','number':4,'start':0,'end':2}]
        slots=preview._number_badge_slots(rows)
        self.assertEqual(slots['early'],slots['late'])
        self.assertNotEqual(slots['early'],slots['other'])
        with self.assertRaises(preview.PreviewV2Error):
            preview._number_badge_slots([{'row_id':str(i),'number':i+1,'start':0,'end':1} for i in range(4)])
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            sparse=Path(tmp)/'sparse.png'; single=Path(tmp)/'single.png'
            preview._write_number_atlas(sparse,[1,3]);preview._write_number_atlas(single,[3])
            with Image.open(sparse) as a,Image.open(single) as b:
                self.assertEqual(a.crop((0,44,64,88)).tobytes(),b.tobytes())


class CurrentMediaReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.job=SimpleNamespace(job_dir=self.root,job_id='job',stages={})
        self.plan={'duration':4,'segments':[{'segment_id':'s','start':2,'end':4,
            'visual_intent':{'statement':'对应负责人和待办'},'shot_recipe':{'components':[
                {'component_id':'a','render_window':{'start_frame':0,'end_frame':24}},
                {'component_id':'b','render_window':{'start_frame':24,'end_frame':48}}]}}]}
        self.plan['visual_plan_sha256']=ca.sha256_json(self.plan)
        self.plan_ref=self.write('plan.json',self.plan)
        self.auth={'source':{'rows':[{'row_id':'s:a'},{'row_id':'s:b'}],
                             'visual_review_policy':vr.POLICY_VERSION},'mapping':{'final_v3':self.plan_ref}}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(vc,'validate_visual_authorization',side_effect=lambda *a,**kw:self.auth).start()
        for stage,folder,name in [('visual_canary','08-visual-canary','canary-manifest.json'),
                                  ('visual_assets','09-visual-assets','asset-manifest.json')]:
            media=self.write(folder+'/segments/s/segment.mp4',b'synthetic media identity')
            manifest={'visual_plan_sha256':self.plan['visual_plan_sha256'],'segment_ids':['s'],
                      'segments':[{'segment_id':'s','video_path':str(self.root/media['path']),
                                   'video_sha256':media['sha256'],'video_bytes':media['bytes']}]}
            m=self.write(folder+'/'+name,manifest)
            self.job.stages[stage]={'artifacts':[media,m]}
        media=self.write('11-preview/review.mp4',b'synthetic preview identity')
        opening=self.write('11-preview/opening-manifest.json',{'body_offset_frames':6,'total_frames':102,
                                                             'preview_sha256':media['sha256']})
        self.job.stages['preview']={'artifacts':[media,opening]}

    def write(self,path,value):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(value) if isinstance(value,bytes) else p.write_text(json.dumps(value))
        return {'path':path,'sha256':ca.sha256_file(p),'bytes':p.stat().st_size}

    def review(self,stage):
        expected=vr.expected_observations(self.job,stage)
        return {'visual_review':{'policy_version':expected['policy_version'],'stage':stage,'plan_ref':expected['plan_ref'],
            'observations':[{'row_id':r['row_id'],'media_ref':r['media_ref'],'playback_window':r['window'],
                'conclusion':'synthetic fixture observation, not a watched production video',
                'design_review': {'verdict': 'pass',
                    'composition': 'Synthetic subject and label share a clear focal area.',
                    'typography': 'Synthetic primary label is distinct from secondary text.',
                    'finish': 'Synthetic flat surfaces and fine lines use one visual language.',
                    'focus': 'Synthetic state change stays on the current object.'},
                'size_position_clear':True,'unobstructed':True,'semantics_clear':True}
                for r in expected['observations']]}}

    def test_new_policy_requires_design_observations_and_refuses_unfinished_design(self):
        for stage in ('visual_canary','visual_assets','preview'):
            for field in ('composition','typography','finish','focus'):
                bad=self.review(stage)
                del bad['visual_review']['observations'][0]['design_review'][field]
                with self.subTest(stage=stage,missing=field), self.assertRaisesRegex(ValueError,'design review'):
                    vr.validate_stage_review(self.job,stage,bad)
            for verdict in ('revise','reselect'):
                bad=self.review(stage)
                bad['visual_review']['observations'][0]['design_review']['verdict']=verdict
                with self.subTest(stage=stage,verdict=verdict), self.assertRaisesRegex(ValueError,'design review'):
                    vr.validate_stage_review(self.job,stage,bad)
            vr.validate_stage_review(self.job,stage,self.review(stage))

    def test_frozen_v1_review_remains_read_only_and_cannot_downgrade_new_policy(self):
        old=self.review('preview')
        old['visual_review']['policy_version']='visual-review-v1'
        for row in old['visual_review']['observations']:
            row.pop('design_review')
        with self.assertRaises(ValueError):
            vr.validate_stage_review(self.job,'preview',old)
        self.auth['source']['visual_review_policy']='visual-review-v1'
        with self.assertRaisesRegex(ValueError,'read-only'):
            vr.validate_stage_review(self.job,'preview',old)
        self.job.stages['preview']['status']='approved'
        self.assertEqual(vr.validate_stage_review(self.job,'preview',old),old['visual_review'])

    def test_real_manifest_shape_and_current_component_clocks(self):
        for stage in ('visual_canary','visual_assets','preview'):
            expected=vr.expected_observations(self.job,stage)
            self.assertEqual([r['row_id'] for r in expected['observations']],['s:a','s:b'])
            self.assertEqual(expected['observations'][0]['window'],[2.25,3.25] if stage=='preview' else [0,1])
            vr.validate_stage_review(self.job,stage,self.review(stage))
        bad=self.review('preview');bad['visual_review']['observations'].pop()
        with self.assertRaises(ValueError):vr.validate_stage_review(self.job,'preview',bad)
        bad=self.review('preview');bad['visual_review']['observations'][0]['playback_window']=[2.25,2.5]
        with self.assertRaises(ValueError):vr.validate_stage_review(self.job,'preview',bad)
        bad=self.review('preview');bad['visual_review']['observations'][0]['playback_window']=[True,float('inf')]
        with self.assertRaises(ValueError):vr.validate_stage_review(self.job,'preview',bad)

    def test_delivery_consumer_needs_current_receipt_and_old_policy_is_untouched(self):
        with self.assertRaises(ValueError):vr.require_preview_review(self.job)
        from edit.hd.tools import qa_delivery_v2
        with mock.patch('edit.hd.tools.motion_readability.require_preview_review'), \
             mock.patch.object(qa_delivery_v2,'_recover_delivery_publication') as publish:
            with self.assertRaises(ValueError):qa_delivery_v2._prepare_delivery_v2_locked(self.job)
            publish.assert_not_called()
        receipt=self.review('preview')|{'job_id':'job','job_dir':str(self.root),'stage':'preview',
            'reviewed_by':'host','passed':True,'artifacts':self.job.stages['preview']['artifacts']}
        self.write('manifests/local-qa-preview-r10.json',receipt)
        vr.require_preview_review(self.job)
        old=self.review('preview')
        new=self.write('11-preview/review.mp4',b'changed synthetic media')
        self.job.stages['preview']['artifacts'][0]=new
        with self.assertRaises(ValueError):vr.validate_stage_review(self.job,'preview',old)
        self.auth['source'].pop('visual_review_policy')
        self.assertEqual(vr.expected_observations(self.job,'preview')['status'],'not_applicable')
        vr.require_preview_review(self.job)

"""The user approves a proposal once; production binds and compiles afterwards."""
from __future__ import annotations
import copy
import sys
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env
import run_stage
from edit.hd.tests import test_visual_direction as fixture_api
from edit.hd.tools import avatar_profile, contract_artifacts as artifacts, state, visual_confirmation as vc

class VisualConfirmationTests(unittest.TestCase):
    def test_first_native_speech_matches_real_approved_clip(self):
        root = self.job.job_dir
        source, clip, forged = root / 'approved-source.mp4', root / 'clip.wav', root / 'forged.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=16x16:r=24:d=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:v', 'libx264',
                        '-c:a', 'aac', '-shortest', str(source)], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-ss', '0.25', '-t', '1.5',
                        '-vn', '-ac', '1', '-ar', '16000', str(clip)], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=1.5',
                        '-ac', '1', '-ar', '16000', str(forged)], check=True)
        segment = {'segment_id': 'seg-001', 'start': .25, 'end': 1.75}
        beat = {**segment, 'component_id': 'native', 'transcript': '已批准口播'}
        original = {'skill_selection': {'beats': [beat]}}
        brief = {'transcript': beat['transcript'], 'speech': {'job_path': clip.name,
            'sha256': artifacts.sha256_file(clip), 'byte_count': clip.stat().st_size},
            'source_binding': {**segment, 'aroll_sha256': artifacts.sha256_file(source)},
            'word_anchors': [{'text': beat['transcript'], 'start': 0, 'end': 1.5}]}
        words = [{'text': beat['transcript'], 'start': .25, 'end': 1.75}]
        with mock.patch('edit.hd.tools.visual_plan._approved_artifact', return_value=source), \
             mock.patch('edit.hd.tools.motion_capabilities._approved_speech', return_value=words):
            vc._validate_fresh_native_parent_inputs(root, {}, original, segment, 'native', brief)
            # 41 video frames have a fractional sample count at 16k; use the parent's exact extraction argv.
            partial_segment = {'segment_id': 'seg-001', 'start': 3 / 24, 'end': 44 / 24}
            partial = root / 'fractional-frame-clip.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-ss', str(partial_segment['start']),
                '-t', str(partial_segment['end'] - partial_segment['start']), '-vn', '-ac', '1',
                '-ar', '16000', '-c:a', 'pcm_s16le', str(partial)], check=True)
            fractional = copy.deepcopy(brief)
            fractional['source_binding'] = {**partial_segment, 'aroll_sha256': artifacts.sha256_file(source)}
            fractional['speech'] = {'job_path': partial.name, 'sha256': artifacts.sha256_file(partial),
                                    'byte_count': partial.stat().st_size}
            fractional['word_anchors'] = [{'text': beat['transcript'], 'start': 0,
                                          'end': partial_segment['end'] - partial_segment['start']}]
            with mock.patch('edit.hd.tools.motion_capabilities._approved_speech',
                    return_value=[{'text': beat['transcript'], 'start': partial_segment['start'],
                                   'end': partial_segment['end']}]):
                vc._validate_fresh_native_parent_inputs(root, {}, original, partial_segment, 'native', fractional)
            import wave
            with wave.open(str(clip), 'rb') as stream:
                params, samples = stream.getparams(), stream.readframes(stream.getnframes())
            with wave.open(str(clip), 'wb') as stream:
                stream.setparams(params)
                stream.writeframes(samples + b'\x01\x00' * 640)
            brief['speech'].update(sha256=artifacts.sha256_file(clip), byte_count=clip.stat().st_size)
            with self.assertRaisesRegex(ValueError, 'authorized native input: speech'):
                vc._validate_fresh_native_parent_inputs(root, {}, original, segment, 'native', brief)
            brief['speech'] = {'job_path': forged.name, 'sha256': artifacts.sha256_file(forged),
                               'byte_count': forged.stat().st_size}
            with self.assertRaisesRegex(ValueError, 'authorized native input: speech'):
                vc._validate_fresh_native_parent_inputs(root, {}, original, segment, 'native', brief)
            brief['word_anchors'][0]['text'] = '伪造词锚'
            with self.assertRaisesRegex(ValueError, 'authorized native input: word_anchors'):
                vc._validate_fresh_native_parent_inputs(root, {}, original, segment, 'native', brief)

    def test_fresh_local_words_allow_only_microsecond_rounding(self):
        words = [{'text': '词', 'start': .2, 'end': .3}]
        segment = {'segment_id': 'seg-001', 'start': .1, 'end': .4}
        brief = {'word_anchors': [{'text': '词', 'start': .1, 'end': .2}]}
        with mock.patch('edit.hd.tools.motion_capabilities._approved_speech', return_value=words):
            vc._validate_fresh_native_parent_inputs(self.job.job_dir, {}, {}, segment, 'native', brief)
            brief['word_anchors'][0]['end'] += .001
            with self.assertRaisesRegex(ValueError, 'word_anchors'):
                vc._validate_fresh_native_parent_inputs(self.job.job_dir, {}, {}, segment, 'native', brief)

    def test_first_talkcraft_realization_keeps_approved_semantic_goal(self):
        from test_talkcraft_skill_adapter import brief as native_brief
        from edit.hd.tools import motion_capabilities
        root = self.job.job_dir
        source = root / '06-edit-structure/edited-aroll.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=16x16:r=24:d=3',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'libx264',
                        '-c:a', 'aac', '-shortest', str(source)], check=True)
        workflow = artifacts.read_json_artifact(root / 'workflow.json')
        for record in workflow['stages']['edit_structure']['artifacts']:
            if record['path'] == '06-edit-structure/edited-aroll.mp4':
                record.update(sha256=artifacts.sha256_file(source), bytes=source.stat().st_size)
        artifacts.write_json_artifact(root / 'workflow.json', workflow)
        self.job = state.load_job(root)
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(('code_generated',))])['segments'][0]
        candidate_id = 'video-talkcraft:source-converge'
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT) if r['candidate_id'] == candidate_id)
        segment['bindings']['component-1'] = {'producer_type': 'dependency', **{k: candidate[k] for k in
            ('dependency_id', 'entrypoint', 'producer_version', 'template_id')}}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment['motion_queries'][0]['tags'] = ['数据', '汇聚', '资料', '蓝色场景']
        treatment = self._review_creator(segment, treatment, candidate_id)
        treatment['skill_selection']['beats'][0].pop('binding_snapshot')
        treatment['skill_selection']['beats'][0]['semantic_goal'] = '资料解释：展示多来源汇聚过程'
        segment.pop('bindings')
        self.fixture._write_brief(segment)
        artifacts.write_json_artifact(self.treatment, treatment)
        proposal = artifacts.read_json_artifact(self.prepare())
        director = artifacts.read_json_artifact(root / proposal['inputs']['director']['path'])
        self.confirm()
        self.assertEqual(run_stage.resume_visual_direction(self.job, _env.PROJECT)['actions'][0]['action'], 'prepare_template_inputs')
        clip = root / 'canonical.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-ss', '0', '-t', '3',
                        '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(clip)], check=True)
        brief = native_brief()
        brief.update(job_id=self.job.job_id, transcript='Approved source evidence', semantic_goal='未经批准的相反含义',
            composition={'width': 1080, 'height': 1920, 'fps': 24, 'frames': 72},
            word_anchors=[{'text': 'Approved source evidence', 'start': 0, 'end': 3}],
            speech={'job_path': clip.name, 'sha256': artifacts.sha256_file(clip), 'byte_count': clip.stat().st_size},
            source_binding={'aroll_sha256': artifacts.sha256_file(source), 'segment_id': 'seg-001', 'start': 0., 'end': 3.})
        path = root / 'native-brief.json'
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'brief_path': path.name}]
        def resume():
            artifacts.write_json_artifact(path, brief)
            director['segments'][0]['bindings']['component-1']['brief_sha256'] = artifacts.sha256_file(path)
            artifacts.write_json_artifact(root / 'actual-director.json', director)
            artifacts.write_json_artifact(root / 'actual-treatment.json', treatment)
            return run_stage.resume_visual_direction(self.job, _env.PROJECT, {'realization': {
                'director_brief': 'actual-director.json', 'treatment': 'actual-treatment.json'}})
        result = resume()
        self.assertIn('semantic_goal', result['errors'][0]['error'])
        self.assertFalse(result['actions'])
        brief['semantic_goal'] = treatment['skill_selection']['beats'][0]['semantic_goal']
        self.assertNotEqual(brief['semantic_goal'], treatment['semantic_lists']['broll'][0]['semantic'])
        self.assertEqual(resume()['actions'][0]['action'], 'execute_native_skill')

    def test_openfilm_parent_sources_and_authored_media_keep_distinct_roles(self):
        from test_openfilm_motion_adapter import brief as native_brief
        from edit.hd.tools import motion_capabilities
        from PIL import Image
        root = self.job.job_dir
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT)
                         if r.get('dependency_id') == 'openfilm-motion-graphics')
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(('code_generated',))])['segments'][0]
        segment['bindings']['component-1'] = {'producer_type': 'dependency', **{k: candidate[k] for k in
            ('dependency_id', 'entrypoint', 'producer_version', 'template_id')}}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment['skill_selection']['beats'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
            'transcript': 'Approved source evidence'}]
        brief = native_brief()
        brief['source_binding'].update(aroll_sha256=artifacts.sha256_file(root/'06-edit-structure/edited-aroll.mp4'),
                                       segment_id='seg-001', end=3.)
        brief['composition']['frames'] = 72
        brief['creative_handoff'].update(transcript='Approved source evidence', semantic_goal='资料解释')
        entry = root / 'native-scene.html'; entry.write_text('<html><body>canvas drawing</body></html>')
        image = root / 'native-drawing.png'; Image.new('RGB', (8, 8), 'red').save(image)
        brief['entry'].update(job_path=entry.name, sha256=artifacts.sha256_file(entry))
        brief['assets'][0].update(job_path=image.name, sha256=artifacts.sha256_file(image))
        scene = {'segment_id': 'seg-001', 'component_id': 'component-1'}
        def check(proposal=None):
            vc._validate_fresh_native_parent_inputs(root, proposal or {}, treatment, segment, 'component-1', brief, scene=scene)
        with self.assertRaisesRegex(ValueError, 'same-target source'):
            check()
        scene['native_asset_origins'] = [{'job_path': image.name, 'sha256': artifacts.sha256_file(image),
            'kind': 'authored', 'evidence': vc._record(root, entry)}]
        check()
        queue_path = root / 'manifests/generation-queue.json'
        other = {'generation_steps': [{'id': 'other-image', 'segment_id': 'seg-002', 'component_id': 'component-1'}]}
        queued = {'items': {'other-image': {'status': 'pending', 'completion_response': {
            'artifacts': [vc._record(root, image)]}}}}
        artifacts.write_json_artifact(queue_path, queued)
        check(other)  # Another unfinished task does not block this authored image.
        queued['items']['other-image']['status'] = 'completed'
        artifacts.write_json_artifact(queue_path, queued)
        with self.assertRaisesRegex(ValueError, 'authorized native input: materials'):
            check(other)  # Its completed image cannot be relabeled as this task's authored asset.
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                'source': vc._record(root, image)}]
        check(other)  # An explicit same-target authorization permits the same content hash.
        treatment['scenes'] = []
        queue_path.unlink()
        brief['creative_handoff']['semantic_goal'] = '相反含义'
        with self.assertRaisesRegex(ValueError, 'semantic_goal'):
            check()
        brief['creative_handoff']['semantic_goal'] = '资料解释'
        foreign = {'segment_id': 'seg-002', 'component_id': 'component-1', 'source': vc._record(root, image)}
        treatment['scenes'] = [foreign]
        # A foreign parent image cannot become authored by copying or relabeling it.
        with self.assertRaisesRegex(ValueError, 'materials'):
            check()
        treatment['scenes'] = []
        scene['native_asset_origins'][0].pop('evidence')
        with self.assertRaisesRegex(ValueError, 'engineering source'):
            check()

    def test_fresh_hw_input_retains_original_indexed_word_anchors(self):
        import shutil
        import hyperframes_hw_pipeline_adapter as native
        from edit.hd.tools import motion_capabilities
        root = self.job.job_dir
        words = [{'text': text, 'start': .45 + i, 'end': .7 + i} for i, text in enumerate(('甲', '乙', '丙'))]
        transcript = root / '05-speech-cleanup/word-transcript.json'
        artifacts.write_json_artifact(transcript, {'version': 1, 'words': words})
        workflow = artifacts.read_json_artifact(root / 'workflow.json')
        workflow['stages']['speech_cleanup']['artifacts'] = [vc._record(root, transcript)]
        artifacts.write_json_artifact(root / 'workflow.json', workflow)
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT) if r['candidate_id'] == 'overlay:hw-pipeline')
        segment = {'segment_id': 'seg-001', 'start': 0, 'end': 5, 'bindings': {'native': {
            k: candidate[k] for k in ('dependency_id', 'entrypoint', 'template_id')}}}
        brief = {'schema_version': 1, 'canvas': {'width': 1080, 'height': 1920, 'fps': 24, 'frames': 120},
            'labels': ['甲', '乙', '丙'], 'label_frames': [0, 24, 48],
            'word_anchors': [{'index': i, 'text': w['text']} for i, w in enumerate(words)],
            'template_request': {'semantic_family': 'three_step_flow', 'information_units': 3,
                'numeric_values': [], 'numeric_scale': 'not_applicable'},
            'source_binding': {'aroll_sha256': artifacts.sha256_file(root/'06-edit-structure/edited-aroll.mp4'),
                'segment_id': 'seg-001', 'start': 0, 'end': 5}}
        native._checked_brief(Path(shutil.which('node')), artifacts.canonical_json_bytes(brief))
        vc._validate_fresh_native_parent_inputs(root, {}, {}, segment, 'native', brief)
        brief['word_anchors'][0]['text'] = '伪造词'
        with self.assertRaisesRegex(ValueError, 'approved transcript'):
            vc._validate_fresh_native_parent_inputs(root, {}, {}, segment, 'native', brief)

    def test_native_plan_authorizes_without_future_brief_and_rejects_broken_real_input(self):
        from edit.hd.tools import motion_capabilities
        segment = avatar_profile.plan_avatar_policy([
            fixture_api.draft_segment(('code_generated',))])['segments'][0]
        candidate_id = 'barty-motion-graphics:barty-motion-graphics/motion-broll'
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT)
                         if r['candidate_id'] == candidate_id)
        segment['bindings']['component-1'] = {'producer_type': 'dependency', **{
            k: candidate[k] for k in ('dependency_id', 'entrypoint', 'producer_version', 'template_id')}}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment['motion_queries'][0]['tags'] = ['输入', '输出', '对比', '解释', '蓝色场景']
        treatment = self._review_creator(segment, treatment, candidate_id)
        treatment['skill_selection']['beats'][0].pop('binding_snapshot')
        segment.pop('bindings')
        self.fixture._write_brief(segment)
        artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch.object(run_stage, 'prepare_visual_dependencies', side_effect=AssertionError('future engineering')):
            proposal_path = self.prepare()
        proposal = artifacts.read_json_artifact(proposal_path)
        director = artifacts.read_json_artifact(self.job.job_dir / proposal['inputs']['director']['path'])
        binding = director['segments'][0]['bindings']['component-1']
        self.assertEqual(binding['template_id'], candidate['template_id'])
        self.assertNotIn('brief_sha256', binding)
        self.assertFalse((self.job.job_dir / 'native-projects').exists())
        self.confirm()
        with mock.patch.object(run_stage, 'prepare_visual_dependencies', side_effect=AssertionError('future engineering')):
            result = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        action, = result['actions']
        self.assertEqual((action['action'], action['segment_id'], action['component_id']),
                         ('prepare_template_inputs', 'seg-001', 'component-1'))
        broken = self.job.job_dir / 'broken.json'
        artifacts.write_json_artifact(broken, {})
        binding['brief_sha256'] = artifacts.sha256_file(broken)
        actual = self.job.job_dir / 'realized.json'
        artifacts.write_json_artifact(actual, director)
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'brief_path': broken.name}]
        realized_treatment = self.job.job_dir / 'realized-treatment.json'
        artifacts.write_json_artifact(realized_treatment, treatment)
        result = run_stage.resume_visual_direction(self.job, _env.PROJECT, {'realization': {
            'director_brief': actual.name, 'treatment': realized_treatment.name}})
        self.assertEqual(result['actions'], [])
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('Invalid native motion task brief', result['errors'][0]['error'])

    def test_existing_doudou_brief_keeps_native_schema_gate(self):
        from edit.hd.tools import motion_capabilities
        segment = avatar_profile.plan_avatar_policy([
            fixture_api.draft_segment(('code_generated',))])['segments'][0]
        candidate_id = 'doudou-remotion-whiteboard:doudou-reviewed-scene'
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT)
                         if r['candidate_id'] == candidate_id)
        binding = {'producer_type': 'dependency', **{k: candidate[k] for k in
            ('dependency_id', 'entrypoint', 'producer_version', 'template_id')}}
        path = self.job.job_dir / 'broken-doudou.json'; artifacts.write_json_artifact(path, {})
        binding['brief_sha256'] = artifacts.sha256_file(path)
        segment['bindings']['component-1'] = binding
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment['motion_queries'][0]['tags'] = ['手绘', '白板', '流程', '步骤']
        treatment = self._review_creator(segment, treatment, candidate_id)
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'brief_path': path.name}]
        self.fixture._write_brief(segment); artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(ValueError, 'Invalid Doudou brief'):
            self.prepare()

    def test_deferred_wake_binds_only_authorized_completed_image(self):
        from types import SimpleNamespace
        import hashlib
        import json
        from edit.hd.tools import generation_queue
        from PIL import Image
        root = self.job.job_dir
        original = root / 'wake-original.png'; Image.new('RGB', (16, 16), 'orange').save(original)
        edited = root / 'wake-edited.png'; edited.write_bytes(b'edited')
        aroll = root / '06-edit-structure/edited-aroll.mp4'; aroll.parent.mkdir(exist_ok=True); aroll.write_bytes(b'aroll')
        original_ref = vc._record(root, original); edited_ref = vc._record(root, edited); aroll_ref = vc._record(root, aroll)
        key = ('seg-001', 'component-1')
        base = {'producer_type':'dependency', 'dependency_id':'lemo-wake', 'entrypoint':'scripts/lemo_wake_adapter.py',
                'producer_version':'2.0.0', 'template_id':'lemo-wake/wake', 'primary_renderer':'HTMLCanvas'}
        segment = {'segment_id':key[0], 'start':0, 'end':1, 'visual_strategy':{'components':[{'component_id':key[1]}]},
                   'bindings':{key[1]:base}}
        frozen = {'segments':[segment]}
        beat = {'segment_id':key[0], 'component_id':key[1], 'binding_snapshot':base, 'semantic_goal':'approved beat'}
        treatment = {'scenes':[{'segment_id':key[0], 'component_id':key[1]}],
                     'semantic_lists':{'overlay':[], 'broll':[{'row_id':'wake-row', 'semantic':'approved beat',
                         'components':[{'segment_id':key[0], 'component_id':key[1]}]}]},
                     'skill_selection':{'assignments':[{'segment_id':key[0], 'component_id':key[1],
                       'candidate_id':'lemo-wake:wake'}], 'beats':[beat]}}
        brief = {'schema_version':1, 'job_id':self.job.job_id,
                 'source_binding':{'aroll_sha256':aroll_ref['sha256'], 'segment_id':key[0], 'start':0, 'end':1},
                 'image':{'job_path':edited_ref['path'],'sha256':edited_ref['sha256'],'byte_count':edited_ref['bytes']},
                 'purpose':'body', 'composition':{'width':1080,'height':1920,'fps':24,'frames':24},
                 'semantic_goal':'approved beat', 'template_request':{'semantic_family':'image-led',
                 'information_units':1,'numeric_values':[],'numeric_scale':'not_applicable'},
                 'result_record_path':'native-inputs/wake-result.json'}
        path = root / 'native-inputs/wake-brief.json'; path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(brief), encoding='utf-8')
        digest = artifacts.sha256_file(path)
        source_sha = artifacts.sha256_file(_env.PROJECT / 'scripts/lemo_wake_adapter.py')
        module = vc._native_result_adapter('lemo-wake')
        bound = {**base, 'renderer_version':module.UPSTREAM_COMMIT, 'template_version':'2.0.0',
                 'template_origin':'custom_fallback','adaptation_level':'structural','source_entrypoint':base['entrypoint'],
                 'source_sha256':source_sha,'brief_sha256':digest,
                 'verification_id':hashlib.sha256((source_sha+digest).encode()).hexdigest(),
                 'semantic_families':['image-led'],'capacity':{'min_units':1,'max_units':1},
                 'invocation_record':{'argv':['python',base['entrypoint']],'status':'planned','exit_code':None,
                                      'template_request':brief['template_request']}}
        director = copy.deepcopy(frozen); director['segments'][0]['bindings'][key[1]] = bound
        actual = copy.deepcopy(treatment); actual['scenes'][0]['brief_path']='native-inputs/wake-brief.json'
        actual['skill_selection']['beats'][0]['binding_snapshot']=bound
        step = {'id':'image-step','segment_id':key[0],'component_id':key[1],'purpose':'image'}
        proposal = {'generation_steps':[step]}
        request = {'id':'edit','purpose':'image','tool':'image.tool','arguments':{'referenced_image_paths':[str(original)]},
                   'input_files':[original_ref]}
        plan = {'from_id':'original','request':request,'issue':'cropped','count':1}
        review = root / 'wake-review.json'
        artifacts.write_json_artifact(review, {'from_id':'original', 'preview':original_ref,
            'status':'needs_revision', 'method':'host image inspection', 'observations':['cropped']})
        plan['followup_evidence'] = {'image':original_ref, 'review':vc._record(root, review)}
        identity = {'provider':'fixture'}
        origin = {'status':'completed','request':{'id':'original','tool':'image.tool'},'authorization':{'source':'approved'},
                  'channel_identity':identity,'config_sha256':'config','completion_response':{
                  'artifacts':[{'type':'image','path':str(original),'sha256':original_ref['sha256'],'bytes':original_ref['bytes']}]}}
        item = {'request':request,'status':'completed','retry_of':'original','plan_request_id':'original',
                'image_edit_plan':plan,'user_confirmation':'one approved edit','channel_identity':identity,'config_sha256':'config',
                'approved_plan_sha256':artifacts.sha256_json(plan),'completion_response':{'artifacts':[
                    {'type':'image','path':str(edited),'sha256':edited_ref['sha256'],'bytes':edited_ref['bytes']}]}}
        job = SimpleNamespace(job_dir=root, job_id=self.job.job_id, stages={'edit_structure':{'status':'completed','artifacts':[aroll_ref]}})
        receipt = {'source': {'path': 'old-proposal.json'}, 'revision': 1}
        authorized = {'artifact': {'path': 'old-receipt.json'}, 'payload': receipt, 'source': proposal}
        with mock.patch.object(vc,'planned_generation_targets',return_value={key}), \
             mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(vc,'validate_visual_authorization',return_value={'source':{'newer':True}}) as latest, \
             mock.patch.object(vc,'_validate_source',return_value=(receipt,proposal)) as validate_source, \
             mock.patch.object(generation_queue,'status',return_value={'items':{'original':origin, 'edit':item}}), \
             mock.patch.object(vc,'generation_item',return_value=('edit',item)), \
             mock.patch.object(vc,'validate_generation_request',return_value={'step':step}):
            normalized, normalized_treatment = vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual, source_authorization=authorized)
            self.assertEqual(normalized,frozen)
            self.assertEqual(normalized_treatment,treatment)
            latest.assert_not_called()
            validate_source.assert_called_once_with(root, authorized['artifact'], job_id=job.job_id)
            vc._validate_fresh_native_parent_inputs(root, proposal, treatment, segment, key[1], brief,
                                                    scene=actual['scenes'][0])
            for semantic_rows in ([], treatment['semantic_lists']['broll'] * 2):
                ambiguous = copy.deepcopy(treatment)
                ambiguous['semantic_lists']['broll'] = semantic_rows
                with self.subTest(rows=len(semantic_rows)), self.assertRaisesRegex(ValueError, 'one confirmed semantic row'):
                    vc._normalize_prepared_wake(root, proposal, frozen, ambiguous, director, actual,
                                               source_authorization=authorized)
                with self.subTest(fresh_rows=len(semantic_rows)), self.assertRaisesRegex(ValueError, 'one confirmed semantic row'):
                    vc._validate_fresh_native_parent_inputs(root, proposal, ambiguous, segment, key[1], brief)
            with self.assertRaisesRegex(ValueError, 'authorized native input: semantic_goal'):
                vc._validate_fresh_native_parent_inputs(root, proposal, treatment, segment, key[1],
                                                       {**brief, 'semantic_goal':'unapproved meaning'})
            wrong = {**brief, 'image': {'job_path': original_ref['path'], 'sha256': original_ref['sha256'],
                                      'byte_count': original_ref['bytes']}}
            with self.assertRaisesRegex(ValueError, 'authorized native input: image'):
                vc._validate_fresh_native_parent_inputs(root, proposal, treatment, segment, key[1], wrong,
                                                        scene=actual['scenes'][0])
            cover = root / '04-cover/cover-delivery-raster.png'
            cover.write_bytes(original.read_bytes())
            job.stages['cover'] = {'status': 'completed', 'artifacts': [vc._record(root, cover)]}
            opening_treatment = copy.deepcopy(treatment)
            opening_treatment['skill_selection']['opening'] = {'segment_id': key[0], 'component_id': key[1],
                                                               'candidate_id': 'lemo-wake:wake'}
            cover_brief = {**brief, 'purpose': 'opening', 'image': {
                'job_path': '04-cover/cover-delivery-raster.png', 'sha256': artifacts.sha256_file(cover),
                'byte_count': cover.stat().st_size}}
            vc._validate_fresh_native_parent_inputs(root, {}, opening_treatment, segment, key[1], cover_brief)
            cover_brief['image'] = brief['image']
            with self.assertRaisesRegex(ValueError, 'authorized native input: image'):
                vc._validate_fresh_native_parent_inputs(root, {}, opening_treatment, segment, key[1], cover_brief)
            for scenes in ([], None):
                deferred = copy.deepcopy(treatment)
                if scenes is None:
                    deferred.pop('scenes')
                else:
                    deferred['scenes'] = scenes
                _, normalized = vc._normalize_prepared_wake(root,proposal,frozen,deferred,director,actual,
                                                           source_authorization=authorized)
                self.assertEqual(normalized,deferred)
                self.assertIn('brief_path',actual['scenes'][0])
            for scenes in ([treatment['scenes'][0]] * 2,
                           [{**treatment['scenes'][0], 'brief_path': 'already-prepared.json'}]):
                with self.subTest(old_scenes=scenes), self.assertRaisesRegex(ValueError,'original deferred scene'):
                    vc._normalize_prepared_wake(root,proposal,frozen,{**treatment,'scenes':scenes},director,actual,
                                               source_authorization=authorized)
            for field, value in [('source', {'newer':True}), ('payload', {'revision':2})]:
                with self.subTest(authority=field), self.assertRaisesRegex(ValueError, 'verified source approval'):
                    vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual,
                                               source_authorization={**authorized, field:value})
            with mock.patch.object(vc,'_validate_source',side_effect=ValueError('wrong source identity')):
                with self.assertRaisesRegex(ValueError, 'wrong source identity'):
                    vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual,
                                               source_authorization=authorized)
            for field, value in [('status','pending'),('user_confirmation',''),('approved_plan_sha256','0'*64)]:
                with self.subTest(field=field):
                    changed = {**item,field:value}
                    with mock.patch.object(vc,'generation_item',return_value=('edit',changed)), \
                         mock.patch.object(generation_queue,'status',return_value={'items':{'original':origin,'edit':changed}}):
                        with self.assertRaises(ValueError):
                            vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual, source_authorization=authorized)
            changed = copy.deepcopy(actual); changed['skill_selection']['beats'][0]['semantic_goal'] = 'different'
            with self.assertRaisesRegex(ValueError,'semantic beat'):
                vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,changed, source_authorization=authorized)
            for field, value, message in [('semantic_goal','different','semantic goal'),
                    ('source_binding',{**brief['source_binding'],'end':2},'source clock')]:
                modified = {**brief,field:value}
                if field == 'source_binding': modified['composition'] = {**brief['composition'], 'frames':48}
                path.write_text(json.dumps(modified),encoding='utf-8')
                changed_director = copy.deepcopy(director)
                changed_director['segments'][0]['bindings'][key[1]]['brief_sha256'] = artifacts.sha256_file(path)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError,message):
                    vc._normalize_prepared_wake(root,proposal,frozen,treatment,changed_director,actual, source_authorization=authorized)
            path.write_text(json.dumps(brief),encoding='utf-8')
            edited.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'completed image'):
                vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual, source_authorization=authorized)

    def test_realization_rejects_deferred_paper_without_crop_provenance_before_publish(self):
        from edit.hd.tools import generation_queue
        root = self.job.job_dir
        key = ('seg-001', 'component-1')
        binding = {'dependency_id': 'paper-collage-hyperframes'}
        frozen = {'segments': [{'segment_id': key[0], 'bindings': {key[1]: binding},
                   'visual_strategy': {'components': [{'component_id': key[1]}]}}]}
        old_treatment = {'scenes': [{'segment_id': key[0], 'component_id': key[1]}]}
        source_director, source_treatment = root / 'paper-plan.json', root / 'paper-plan-treatment.json'
        artifacts.write_json_artifact(source_director, frozen)
        artifacts.write_json_artifact(source_treatment, old_treatment)
        proposal = {'inputs': {'director': vc._record(root, source_director),
                              'treatment': vc._record(root, source_treatment)}}
        director, treatment = copy.deepcopy(frozen), copy.deepcopy(old_treatment)
        director['segments'][0]['bindings'][key[1]] = {**binding, 'brief_sha256': 'a' * 64}
        treatment['scenes'][0]['brief_path'] = 'paper-actual-brief.json'
        with mock.patch.object(vc, '_validate_parent_camera_framing'), \
             mock.patch.object(vc, 'planned_generation_targets', return_value={key}), \
             mock.patch.object(state, 'load_job', return_value=self.job), \
             mock.patch.object(generation_queue, 'status', return_value={}), \
             self.assertRaisesRegex(ValueError, 'bound brief and explicit crop provenance'):
            vc._normalize_prepared_paper(root, proposal, frozen, old_treatment, director, treatment)



    def test_routing_distribution_separates_logical_counts_channels_and_repeats(self):
        rows = [
            {"row_id": "a:1", "semantic_row_id": "logical-a", "segment_id": "a", "component_id": "1",
             "type": "B-roll", "start": 0, "end": 2, "number": 1},
            {"row_id": "a:2", "semantic_row_id": "logical-a", "segment_id": "a", "component_id": "2",
             "type": "B-roll", "start": 2, "end": 3, "number": 1, "channel": "Paper"},
            {"row_id": "b:1", "semantic_row_id": "logical-b", "segment_id": "b", "component_id": "1",
             "type": "B-roll", "start": 3, "end": 4, "number": 2, "channel": "Paper",
             "visual_pattern": "说明", "selection_reason": "保持动作连续"},
            {"row_id": "c:1", "semantic_row_id": "logical-c", "segment_id": "c", "component_id": "1",
             "type": "贴片", "start": 4, "end": 5, "number": 3, "channel": "Overlay"},
        ]
        rows[0]["channel"] = "Lovart"
        summary, repeats = vc._routing_distribution(rows, {"skill_selection": {}})
        self.assertEqual(summary["B-roll"]["logical_count"], 2)
        self.assertEqual(summary["B-roll"]["channels"]["Lovart"]["count"], 1)
        self.assertEqual(summary["B-roll"]["channels"]["Paper"]["duration"], 2.0)
        self.assertEqual(summary["贴片"]["logical_count"], 1)
        self.assertTrue(any(item[0] == 1 and item[1] == 2 for item in repeats))

    def test_routing_distribution_unions_overlaps_and_skips_same_logical_repeat(self):
        rows = [
            {"row_id": "a:1", "semantic_row_id": "same", "segment_id": "a", "component_id": "1", "type": "B-roll", "start": 0, "end": 3, "number": 1, "channel": "Paper"},
            {"row_id": "a:2", "semantic_row_id": "same", "segment_id": "a", "component_id": "2", "type": "B-roll", "start": 2, "end": 4, "number": 1, "channel": "Paper"},
            {"row_id": "b:1", "semantic_row_id": "next", "segment_id": "b", "component_id": "1", "type": "B-roll", "start": 4, "end": 5, "number": 2, "channel": "Paper", "visual_pattern": "同动作", "template": "other-template"},
        ]
        rows[1]['visual_pattern'] = '同动作'
        summary, repeats = vc._routing_distribution(rows, {"skill_selection": {}})
        self.assertEqual(summary["B-roll"]["logical_count"], 2)
        self.assertEqual(summary["B-roll"]["channels"]["Paper"]["duration"], 5.0)
        self.assertEqual(len(repeats), 1)
        self.assertIn("同构图/动作", repeats[0][2])

    def test_routing_uses_actual_incoming_and_outgoing_physical_channels(self):
        def row(sid, logical, begin, end, number, channel):
            return {'row_id':sid+':v','semantic_row_id':logical,'segment_id':sid,'component_id':'v',
                    'type':'B-roll','start':begin,'end':end,'number':number,'channel':channel}
        rows=[row('a','one',0,2,1,'Lovart'),row('b','one',2,3,1,'Paper'),
              row('c','two',3,4,2,'Paper'),row('d','two',4,5,2,'OpenFilm'),
              row('e','three',4.5,6,3,'OpenFilm')]
        summary,repeats=vc._routing_distribution(rows,{'skill_selection':{}})
        self.assertEqual(summary['B-roll']['channels']['OpenFilm']['duration'],2)
        self.assertEqual([(r[0],r[1]) for r in repeats],[(1,2),(2,3)])
        self.assertIn('同渠道：Paper',repeats[0][2])
        self.assertIn('同屏重叠',repeats[1][2])

    def setUp(self):
        self.fixture = fixture_api.VisualDirectionSchemaV3Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.job = self.fixture.job
        self.fixture._write_brief(*avatar_profile.plan_avatar_policy(
            [fixture_api.draft_segment(("external_stock",))])["segments"])
        config = self.job.job_dir / "manifests/provider-config.json"
        config.parent.mkdir(exist_ok=True)
        artifacts.write_json_artifact(config, {"schema_version": 1, "providers": [],
            "max_concurrency": 1, "generation_enabled": False})
        self.treatment = self.fixture.root / "treatment.json"
        artifacts.write_json_artifact(self.treatment, {
            "numbering_scope_id": "scope-test",
            "semantic_lists": {"overlay": [], "broll": [{"row_id": "sem-broll-1", "start_word": 0,
                "end_word": 1, "quote": "Approved source evidence", "semantic": "资料解释", "visual_task": "展示资料",
                "components": [{"segment_id": "seg-001", "component_id": "component-1"}]}]},
            "beat_sheet": [{"start_word": 0, "end_word": 1, "quote": "Approved source evidence",
                            "decision": "broll", "visual": "资料画面承接口播",
                            "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
                            "reason": "用具体资料画面解释这句口播"}],
            "motion_queries": [{"segment_id": "seg-001", "component_id": "component-1",
                                "tags": ["approved visual explanation"]}], "overlay_selection": [],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                "fixed_context": [{"segment_id": "seg-001", "component_id": "component-1",
                                   "visual_pattern": "existing material", "source_ref": "asset-1", "skill_id": "Example Stock",
                                   "start": 0.0, "end": 3.0}],
                "recent_context": [], "history_note": "synthetic fixture"}})
        from edit.hd.tools import motion_match_cache
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        artifacts.write_json_artifact(self.treatment,
            motion_match_cache.match_once(_env.PROJECT, director, treatment))

    def prepare(self):
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                        return_value=[{"text": "Approved source evidence", "start": 0.0, "end": 3.0}]):
            return vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)

    def confirm(self):
        review = {k: copy.deepcopy(v) for k, v in run_stage._summary(self.job, "visual_direction").items()
                  if k in {"job_id", "job_dir", "stage", "revision", "artifacts"}}
        review.update(passed=True, note="synthetic host inspected the proposed content",
                      user_confirmation="synthetic approval of this exact complete list")
        return run_stage._review(self.job, "visual_direction", review)

    def test_new_proposal_requires_complete_beat_sheet(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment.pop("beat_sheet")
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "beat_sheet"):
            self.prepare()

    def test_new_proposal_requires_explicit_numbering_scope(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment.pop("numbering_scope_id")
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "numbering_scope_id"):
            self.prepare()

    def test_new_proposal_rejects_non_renderable_internal_segment_id(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director["segments"][0]["segment_id"] = "seg-../followup"
        artifacts.write_json_artifact(self.fixture.brief, director)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not renderable"):
            self.prepare()
        self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))

    def test_numbering_scope_starts_new_universe(self):
        def approve(revision, scope, numbering):
            root = self.job.job_dir / "07-visual-confirmation" / f"history-{revision}"
            root.mkdir(parents=True, exist_ok=True)
            proposal_path = root / "proposal.json"
            proposal = {"job_id": self.job.job_id, "job_dir": str(self.job.job_dir),
                        "kind": vc.SCHEMA, "numbering_scope_id": scope,
                        "rows": [{"row_id": key, "semantic_row_id": key}
                                 for key in numbering], "numbering": numbering}
            artifacts.write_json_artifact(proposal_path, proposal)
            source = vc._record(self.job.job_dir, proposal_path)
            receipt = {"source_schema": vc.SCHEMA, "job_id": self.job.job_id,
                       "job_dir": str(self.job.job_dir), "stage": "visual_direction",
                       "passed": True, "authorized_by": "user",
                       "authorization_scope": "visual_plan_and_generation", "revision": revision,
                       "source": source}
            artifacts.write_json_artifact(self.job.job_dir / "manifests" /
                                          f"visual-authorization-r{revision}.json", receipt)

        # Same scope inherits the sparse mapping, including a deleted number.
        approve(1, "scope-target", {"semantic-keep": 3, "semantic-deleted": 7})
        self.assertEqual(vc._prior_numbering(self.job, "scope-target"),
                         {"semantic-keep": 3, "semantic-deleted": 7})
        numbered = vc.number_visual_rows(
            [{"row_id": "physical-new", "semantic_row_id": "semantic-new"}],
            vc._prior_numbering(self.job, "scope-target"))
        self.assertEqual(numbered[0]["number"], 8)

        # A different scope is a new numbering universe, so the old 20 is ignored.
        approve(2, "scope-other", {"semantic-old": 20})
        self.assertEqual(vc._prior_numbering(self.job, "scope-new"), {})
        self.assertEqual(vc.number_visual_rows(
            [{"row_id": "physical-first", "semantic_row_id": "semantic-first"}],
            vc._prior_numbering(self.job, "scope-new"))[0]["number"], 1)

        # Historical scope-less approvals remain readable but never seed a new scope.
        approve(3, None, {"semantic-legacy": 99})
        self.assertEqual(vc._prior_numbering(self.job, "scope-new"), {})

    def test_missing_draft_version_blocks_before_proposal_or_generation(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director.pop("schema_version")
        artifacts.write_json_artifact(self.fixture.brief, director)
        with self.assertRaisesRegex(Exception, "BROLL_SCHEMA_UNSUPPORTED"):
            self.prepare()
        self.assertFalse((self.job.job_dir / vc.DIRECTORY).exists())

    def test_native_timing_failure_blocks_proposal_before_generation(self):
        before = copy.deepcopy(self.job.stages["visual_direction"])
        with mock.patch("edit.hd.tools.motion_capabilities.check_planning_only", return_value={
                'status': 'fail', 'failures': ['native clock differs'], 'not_verified': []}):
            with self.assertRaisesRegex(ValueError, "native clock differs"):
                self.prepare()
        self.assertEqual(self.job.stages["visual_direction"], before)
        self.assertFalse(list((self.job.job_dir / "07-visual-confirmation").glob("*/proposal.json")))

    def test_beat_sheet_rejects_gap_or_stale_quote(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["quote"] = "过期口播"
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "quote"):
            self.prepare()

    def test_beat_sheet_accepts_actual_full_frame_strategy(self):
        director = {"segments": [{"start": 0, "end": 3,
            "visual_strategy": {"mode": "none", "components": [],
                "composition": {"family": "no_broll", "presenter_mode": "full_frame"}}}]}
        treatment = {"beat_sheet": [{"start_word": 0, "end_word": 1,
            "quote": "开场", "decision": "aroll", "visual": "真人开场称呼",
            "components": [], "reason": "保留真人视线和称呼，建立交流"}]}
        speech = [{"text": "开场", "start": 0, "end": 2.5}]
        vc._validate_beat_sheet(treatment, director, speech)
        director["segments"][0]["visual_strategy"]["mode"] = "single"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "full-frame"):
            vc._validate_beat_sheet(treatment, director, speech)

    def test_beat_sheet_allows_continuous_parallel_components(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director["segments"][0]["visual_strategy"]["components"].append(
            {"component_id": "component-2", "kind": "external_stock", "layer_role": "base"})
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"].append(
            {"segment_id": "seg-001", "component_id": "component-2"})
        treatment["beat_sheet"][0]["merge_reason"] = "两个并列画面共同承接同一段连续动作"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "Approved source evidence", "start": 0.0, "end": 3.0}])

    def test_reused_component_requires_merge_reason_on_each_beat(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "实际", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "剪后口播", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
             "merge_reason": "同一连续资料画面覆盖后半句"}]
        with self.assertRaisesRegex(vc.VisualConfirmationError, "reused"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "实际", "start": 0.0, "end": 1.0},
                                     {"text": "剪后口播", "start": 1.0, "end": 3.0}])
        treatment["beat_sheet"][0]["merge_reason"] = "同一连续资料画面覆盖前半句"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "实际", "start": 0.0, "end": 1.0},
                                 {"text": "剪后口播", "start": 1.0, "end": 3.0}])

    def test_beat_sheet_rejects_unknown_component_and_uncovered_time(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"][0]["component_id"] = "missing"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "unknown"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "Approved source evidence", "start": 0.0, "end": 3.0}])

    def test_proposal_precedes_compile_and_one_confirmation_completes_plan(self):
        proposal = self.prepare()
        self.assertFalse((self.job.job_dir / "07-visual-direction/visual-plan.json").exists())
        ready = self.confirm()
        self.assertIn("| 编号 | 时间 |", (proposal.parent / "visual-routing.md").read_text())
        numbered = vc.approved_numbered_rows(self.job)
        self.assertEqual([(row["row_id"], row["number"]) for row in numbered],
                         [("seg-001:component-1", 1)])
        self.assertNotIn("review_required", ready)
        self.assertEqual(self.job.stages["visual_direction"]["status"], "ready")
        approval = vc.validate_visual_authorization(self.job)["artifact"]
        original = (self.job.job_dir / approval["path"]).read_bytes()
        (self.job.root / '00-user-provided').mkdir()
        result = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(result["status"], "completed")
        final = state.load_job(self.job.job_dir)
        checked = vc.validate_visual_authorization(final, require_realized=True)
        self.assertEqual(checked["artifact"], approval)
        self.assertEqual(vc.approved_numbered_rows(final), numbered)
        self.assertEqual(original, (self.job.job_dir / approval["path"]).read_bytes())
        self.assertTrue(proposal.exists())
        changed = artifacts.read_json_artifact(self.fixture.brief)
        changed["segments"][0]["visual_intent"]["statement"] = "unapproved change"
        with self.assertRaises(vc.VisualConfirmationError):
            vc.validate_realization_draft(final, changed, artifacts.read_json_artifact(self.treatment))

    def test_managed_publication_carries_exact_proposal_and_authorization_into_mapping(self):
        from edit.hd.tools import visual_plan
        proposal_path = self.prepare()
        self.confirm()
        authorized = vc.validate_visual_authorization(self.job)
        original_proposal = copy.deepcopy(authorized['payload']['source'])
        original_authorization = copy.deepcopy(authorized['artifact'])
        # Exercise the managed publication branch without external generation or rendering.
        (self.job.root / '00-user-provided').mkdir()
        director = self.job.job_dir / authorized['source']['inputs']['director']['path']
        treatment = self.job.job_dir / authorized['source']['inputs']['treatment']['path']
        with mock.patch('edit.hd.tools.motion_capabilities._approved_speech',
                        return_value=[{'text':'Approved source evidence','start':0.0,'end':3.0}]):
            visual_plan.prepare_visual_direction(self.job, director, self.fixture.asset_root,
                                                 treatment_path=treatment)
        compiled = state.load_job(self.job.job_dir)
        for reference in (original_proposal, original_authorization):
            self.assertIn(reference, compiled.stages['visual_direction']['artifacts'])
        self.assertEqual(vc.validate_visual_authorization(compiled)['artifact'], original_authorization)
        vc.write_realization_mapping(compiled, director_path=director, treatment_path=treatment)
        state.complete(compiled, 'visual_direction')
        final = state.load_job(compiled.job_dir)
        checked = vc.validate_visual_authorization(final, require_realized=True)
        self.assertEqual(checked['artifact'], original_authorization)
        self.assertEqual(checked['payload']['source'], original_proposal)
        self.assertTrue(proposal_path.exists())
        for reference in (original_proposal, original_authorization):
            self.assertIn(reference, final.stages['visual_direction']['artifacts'])

    def test_time_coverage_failure_returns_to_semantics_before_publication(self):
        from edit.hd.tools import motion_match_cache
        stock = fixture_api.draft_segment(("external_stock",), end=1.0)
        presenter = fixture_api.draft_segment((), segment_id="seg-002", start=1.0, end=3.0)
        director = {"schema_version": 3, "segments": [stock, presenter]}
        from edit.hd.tools import avatar_profile
        director["segments"] = avatar_profile.plan_avatar_policy(director["segments"])["segments"]
        artifacts.write_json_artifact(self.fixture.brief, director)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["fixed_context"][0]["end"] = 1.0
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "Approved source evidence", "decision": "broll", "visual": "展示资料",
             "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "继续解释", "decision": "aroll", "visual": "真人解释",
             "components": [], "reason": "真人接着解释当前资料"}]
        treatment = motion_match_cache.match_once(_env.PROJECT, director, treatment)
        artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech", return_value=[
                {"text": "Approved source evidence", "start": 0.0, "end": 1.0},
                {"text": "继续解释", "start": 1.0, "end": 3.0}]):
            with self.assertRaisesRegex(vc.VisualConfirmationError, "time coverage.*affected semantic list"):
                vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)
        self.assertFalse((self.job.job_dir / vc.DIRECTORY).exists())

    def test_selected_image_to_video_channel_reaches_realized_template(self):
        self._selected_generation_flow("local_path")

    def test_lovart_project_is_checked_before_freeze_with_future_image(self):
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                  "providers": [
                      {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image"},
                      {"purpose": "video", "provider": "Lovart", "model": "kling/kling-video-o1", "endpoint_id": "mcp__lovart__generate_video"}]}
        for provider in config["providers"]:
            provider.update(connection_status="verified", quota_status="available", reference_images=True,
                            native_9_16=True, silent_output=True)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json", {
            "schema_version": 1, "image": {"model_binding": {"mode": "fixed"}},
            "video": {"model_binding": {"mode": "argument", "parameter": "model"}}})
        treatment = artifacts.read_json_artifact(self.treatment)
        future = {"$step": "image", "output": 0}
        steps = [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "fixture image"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "fixture video", "first_frame": future}, "depends_on": ["image"]}]
        treatment["generation_plan"] = {"steps": steps}
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(ValueError, "real project_id"):
            self.prepare()
        self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))
        steps[1]["arguments"]["project_id"] = "synthetic-project"
        artifacts.write_json_artifact(self.treatment, treatment)
        proposal = artifacts.read_json_artifact(self.prepare())
        self.assertEqual(proposal["generation_steps"][1]["arguments"]["first_frame"], future)
        self.assertFalse((self.job.job_dir / "generated-media").exists())

    def test_uploaded_image_and_normalized_video_reach_realized_template(self):
        self._selected_generation_flow("upload")

    def _review_creator(self, segment, treatment, candidate_id):
        """Synthetic creative judgement; matching and assignment remain real."""
        from edit.hd.tools import motion_match_cache, motion_capabilities, broll_skill_selection
        director = {"schema_version": 3, "segments": [segment]}
        treatment["skill_selection"]["fixed_context"] = []
        treatment = motion_match_cache.match_once(_env.PROJECT, director, treatment)
        catalog = {r["candidate_id"]: r for r in motion_capabilities.load_catalog(_env.PROJECT)}
        row = treatment["semantic_lists"]["broll"][0]
        candidates = []
        for match in treatment["motion_matches"][row["row_id"]]["matches"]:
            cid = match["candidate_id"]
            candidates.append({"candidate_id": cid, "fit": "preferred" if cid == candidate_id else "equivalent",
                "capability_sha256": motion_match_cache.candidate_review_identity(catalog[cid]),
                "reason": "Synthetic candidate review for the phase-boundary fixture",
                "visual_pattern": "blue-scene", "design_plan": dict.fromkeys(
                    ("composition", "typography", "finish", "focus"), "Synthetic blue scene design")})
        eligible = {catalog[c["candidate_id"]]["skill_id"] for c in candidates}
        beat = {"segment_id": segment["segment_id"], "component_id": "component-1",
            "semantic_row_id": row["row_id"], "start": segment["start"], "end": segment["end"],
            "semantic_sha256": treatment["motion_matches"][row["row_id"]]["semantic_sha256"],
            "transcript": row["quote"], "semantic_goal": row["semantic"], "required_change": row["visual_task"],
            "intent_statement": segment["visual_intent"]["statement"],
            "component_brief": segment["visual_strategy"]["components"][0]["brief"],
            "binding_snapshot": copy.deepcopy(segment["bindings"]["component-1"]), "candidates": candidates,
            "skill_reviews": {sid: {"fit": "equivalent" if sid in eligible else "unsuitable",
                "reason": "Synthetic full-pool judgement for this fixture"}
                for sid in {r["skill_id"] for r in broll_skill_selection.discover_candidates(_env.PROJECT)}}}
        treatment["skill_selection"]["beats"] = [beat]
        treatment["skill_selection"] = broll_skill_selection.assign_skills(_env.PROJECT, treatment["skill_selection"])
        self.assertEqual(treatment["skill_selection"]["assignments"][0]["candidate_id"], candidate_id)
        return treatment

    def test_design_final_video_requires_its_own_image_input(self):
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 1,
            "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                "endpoint_id": "fixture." + purpose, "connection_status": "verified",
                "quota_status": "available", "reference_images": True, "native_9_16": True,
                "silent_output": True} for purpose in ("image", "video")]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1, **{purpose: {"model_binding": {"mode": "fixed"},
                "reference_mode": "local_path"} for purpose in ("image", "video")}})
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(("ai_generated",))])["segments"][0]
        segment["bindings"]["component-1"] = {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"][0]["tags"] = ["蓝色场景"]
        treatment = self._review_creator(segment, treatment,
            "muyang-flat-animation:muyang-flat-animation/design")
        director = {"schema_version": 3, "segments": [segment]}
        def step(sid, purpose, arguments, depends_on=()):
            return {"id": sid, "purpose": purpose, "segment_id": "seg-001", "component_id": "component-1",
                    "arguments": arguments, "depends_on": list(depends_on)}
        image = step("image", "image", {"prompt": "a blue scene"})
        earlier = step("earlier-video", "video", {"reference": {"$step": "image"}}, ["image"])
        frozen = self.job.job_dir / "frozen.png"
        frozen.write_bytes(b"synthetic frozen image input")
        frozen_ref = vc._record(self.job.job_dir, frozen)
        for case in ("unrelated_local_image", "ordering_only", "video_ancestor"):
            first = copy.deepcopy(earlier)
            final = step("final-video", "video", {"prompt": "text-only final"}, ["earlier-video"])
            if case == "unrelated_local_image":
                first = step("earlier-video", "video", {"reference": str(frozen)})
                first["input_files"] = [frozen_ref]
            elif case == "video_ancestor":
                final["arguments"]["reference"] = {"$step": "earlier-video"}
            treatment["generation_plan"] = {"steps": [image, first, final]}
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "needs its image input"):
                vc.planned_generation_targets(_env.PROJECT, director, treatment, job_dir=self.job.job_dir)
        for final in (step("video", "video", {"reference": {"$step": "image"}}, ["image"]),
                      {**step("video", "video", {"reference": str(frozen)}), "input_files": [frozen_ref]}):
            treatment["generation_plan"] = {"steps": [image, final]}
            self.assertEqual(vc.planned_generation_targets(_env.PROJECT, director, treatment,
                job_dir=self.job.job_dir), {("seg-001", "component-1")})

    def test_native_paper_future_image_is_confirmed_before_authoring(self):
        from edit.hd.tools import motion_capabilities
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 1,
            "providers": [{"purpose": "image", "provider": "fixture", "model": "image-model",
                "endpoint_id": "fixture.image", "connection_status": "verified", "quota_status": "available",
                "reference_images": True, "native_9_16": True, "silent_output": True}]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1, "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"}})
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(("code_generated",))])["segments"][0]
        cid = "paper-collage-hyperframes:paper-collage-ad/hyperframes"
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT) if r["candidate_id"] == cid)
        segment["bindings"]["component-1"] = {**{k: candidate[k] for k in
            ("dependency_id", "entrypoint", "producer_version", "template_id")},
            "producer_type": "dependency", "primary_renderer": "HyperFrames"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"][0]["tags"] = ["蓝色场景"]
        treatment["generation_plan"] = {"steps": [{"id": "paper-image", "purpose": "image",
            "segment_id": "seg-001", "component_id": "component-1", "arguments": {"prompt": "blue paper assets"}}]}
        treatment["motion_readability"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "targets": [], "no_critical_text_reason": "Synthetic scene has no critical text"}]
        treatment = self._review_creator(segment, treatment, cid)
        self.fixture._write_brief(segment)
        artifacts.write_json_artifact(self.treatment, treatment)
        director = {"schema_version": 3, "segments": [segment]}
        deferred = copy.deepcopy(treatment)
        deferred['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                           'pending_generation': True}]
        from edit.hd.tools import motion_readability
        with mock.patch.object(motion_readability, '_managed', return_value=True):
            motion_readability.validate_direction_contract(self.job, director, deferred, phase='planning')
            with self.assertRaisesRegex(ValueError, 'uncreated approved generation'):
                motion_readability.validate_direction_contract(self.job, director, deferred, phase='completed')
        for case in ("missing_step", "wrong_target", "wrong_route", "invented_image", "unfrozen_reference", "fixed_action"):
            invalid = copy.deepcopy(treatment)
            changed = copy.deepcopy(director)
            if case == "missing_step": invalid["generation_plan"]["steps"] = []
            elif case == "wrong_target": invalid["generation_plan"]["steps"][0]["component_id"] = "missing"
            elif case == "wrong_route": changed["segments"][0]["bindings"]["component-1"]["template_id"] = "wrong"
            elif case == "invented_image": invalid["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": "missing.png"}]
            elif case == "unfrozen_reference": invalid["generation_plan"]["steps"][0]["arguments"]["referenced_image_paths"] = ["/missing.png"]
            else: invalid["skill_selection"]["assignments"][0]["candidate_id"] = "eian-riso-broll:focus"
            with self.subTest(case=case):
                if case == "missing_step":
                    self.assertEqual(vc.planned_generation_targets(_env.PROJECT, changed, invalid, job_dir=self.job.job_dir), set())
                    with self.assertRaisesRegex(ValueError, "missing its scene brief"):
                        run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, changed, invalid)
                else:
                    with self.assertRaises(ValueError):
                        vc.planned_generation_targets(_env.PROJECT, changed, invalid, job_dir=self.job.job_dir)
        unconfigured = copy.deepcopy(config)
        unconfigured["generation_enabled"] = False
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", unconfigured)
        with self.assertRaisesRegex(ValueError, "selected channel"):
            vc.planned_generation_targets(_env.PROJECT, director, treatment, job_dir=self.job.job_dir)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        damaged = copy.deepcopy(director)
        damaged["segments"][0]["bindings"]["component-1"]["brief_sha256"] = "b" * 64
        damaged_treatment = copy.deepcopy(treatment)
        path = self.job.job_dir / "damaged-native.json"
        path.write_text("{}")
        damaged_treatment["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": path.name}]
        self.assertEqual(vc.planned_generation_targets(_env.PROJECT, damaged, damaged_treatment, job_dir=self.job.job_dir), set())
        with self.assertRaisesRegex(ValueError, "brief differs"):
            run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, damaged, damaged_treatment)
        unrelated = copy.deepcopy(director)
        neighbor = copy.deepcopy(segment)
        neighbor["segment_id"] = "seg-002"
        unrelated["segments"].append(neighbor)
        with self.assertRaisesRegex(ValueError, "missing its scene brief"):
            run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, unrelated, treatment,
                planned={("seg-001", "component-1")})
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                return_value=[{"text": "Approved source evidence", "start": 0.0, "end": 3.0}]), \
             mock.patch.object(run_stage, "prepare_visual_dependencies"):
            result = run_stage.run_visual_direction(self.job.job_dir, _env.PROJECT,
                self.fixture.brief, self.treatment)
        self.job = state.load_job(self.job.job_dir)
        self.assertIn("confirmation_source", result)
        self.assertFalse((self.job.job_dir / "generated-media").exists())
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)
        self.confirm()
        from edit.hd.tools import generation_channels, generation_queue
        from PIL import Image
        import paper_hyperframes_adapter as paper
        image = self.job.job_dir / "actual-paper.png"
        Image.new("RGB", (128, 128), "blue").save(image)
        with mock.patch.object(generation_queue, "_approved", return_value=(self.job.job_id, "fixture-config", config)):
            action = vc.generation_actions(self.job)[0]
            generation_channels.record_result(self.job.job_dir, action, {'status':'failed',
                'error':{'code':'moderation_blocked'}})
            predecessor = copy.deepcopy(generation_queue.status(self.job.job_dir)['items'][action['request_id']])
            corrected = copy.deepcopy(predecessor['request'])
            corrected['id'] = 'corrected-paper-image'
            corrected['arguments']['prompt'] = 'blue paper assets, fully clothed adult actors'
            retry = generation_queue.prepare_retry(self.job.job_dir, action['request_id'], corrected)
            generation_queue.retry(self.job.job_dir, retry['plan'], '允许这两次图片调用，继续', retry['plan_sha256'])
            action = vc.generation_actions(self.job)[0]
            self.assertEqual(action['request_id'], corrected['id'])
            generation_channels.record_result(self.job.job_dir, action, {"status": "completed", "artifacts": [{"type": "image", "path": str(image)}]})
            self.assertEqual(generation_queue.status(self.job.job_dir)['items'][predecessor['request']['id']], predecessor)
            pending = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(pending["actions"][0]["action"], "prepare_template_inputs")
        output = pending["actions"][0]["completed_generations"][0]["completion_response"]["artifacts"][0]
        local = Path(output["path"])
        local = local if local.is_absolute() else self.job.job_dir / local
        action = paper.authoring_context(_env.PROJECT, output_directory=self.job.job_dir / "paper-authoring",
            source_binding={"aroll_sha256": artifacts.sha256_file(self.job.job_dir / "06-edit-structure/edited-aroll.mp4"),
                "segment_id": "seg-001", "start": 0.0, "end": 3.0},
            composition={"width":1080,"height":1920,"fps":24,"frames":72,"alpha":False},
            template_request={"semantic_family":"explanation","information_units":1,"numeric_values":[],"numeric_scale":"not_applicable"},
            transcript="Approved source evidence", semantic_goal="资料解释", assets=[local], speech=None, word_anchors=[],
            authorization={"paid_generation":False}, parent_subtitle_layout=None)
        self.assertEqual(action["requirements"]["assets"], [{"path": str(local.resolve()), "sha256": artifacts.sha256_file(local)}])
        pending = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"realization": {
                "director_brief": str(self.fixture.brief), "treatment": str(self.treatment),
                "host_qa_note": "Image exists; native scene is deliberately not prepared"}})
        self.assertEqual(pending['actions'][0]['action'], 'prepare_template_inputs')
        self.assertEqual(pending['actions'][0]['component_id'], 'component-1')

    def test_generated_image_consumption_belongs_to_its_native_component(self):
        from PIL import Image
        root = self.job.job_dir
        image = root / "actual-generated.png"
        Image.new("RGB", (64, 64), "blue").save(image)
        digest = artifacts.sha256_file(image)
        brief = root / "native-inputs/actual-native-brief.json"
        artifacts.write_json_artifact(brief, {"assets": [{"job_path": image.name, "sha256": digest}]})
        director = {"segments": [{"segment_id": "seg-001", "bindings": {"component-1": {}}},
                                 {"segment_id": "seg-002", "bindings": {"component-1": {}}}]}
        native = {"segment_id": "seg-002", "component_id": "component-1", "artifact": vc._record(root, brief)}
        hashes = vc._realized_media_hashes(root, director, [], [native])
        self.assertNotIn(digest, hashes[("seg-001", "component-1")])
        self.assertIn(digest, hashes[("seg-002", "component-1")])
        native["segment_id"] = "seg-001"
        self.assertIn(digest, vc._realized_media_hashes(root, director, [], [native])[("seg-001", "component-1")])
        brief.write_text("{}")
        with self.assertRaisesRegex(vc.VisualConfirmationError, "evidence changed"):
            vc._realized_media_hashes(root, director, [], [native])

    def _selected_generation_flow(self, reference_mode):
        from edit.hd.tools import generation_channels as channel, generation_queue as queue, startup
        import generated_media
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                  "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                    "endpoint_id": "fixture." + purpose, "connection_status": "verified",
                    "quota_status": "available", "reference_images": True, "native_9_16": True,
                    "silent_output": True} for purpose in ("image", "video")]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1,
             "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"},
             "video": {"model_binding": {"mode": "argument", "parameter": "model"},
                       "reference_mode": reference_mode,
                       "upload": {"tool": "fixture.upload", "arguments": {"file": {"$input": "path"}},
                                  "result_path": ["data", "asset_id"]},
                       "query": {"tool": "fixture.query", "arguments": {}, "task_ids_parameter": "task_ids"}}})
        segment = fixture_api.draft_segment(("ai_generated",))
        segment["bindings"]["component-1"] = {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        segment = avatar_profile.plan_avatar_policy([segment])["segments"][0]
        self.fixture._write_brief(segment)
        arguments_path = self.job.job_dir / "channel-arguments.json"
        artifacts.write_json_artifact(arguments_path, {"prompt": "fixture request"})
        cli = subprocess.run([sys.executable, str(_env.SKILL / "scripts/run_generation.py"),
            "--project-root", str(_env.PROJECT), "--job", str(self.job.job_dir), "prepare",
            "--purpose", "image", "--request-id", "fixture-cli", "--arguments-json", str(arguments_path)],
            cwd="/tmp", check=True, capture_output=True, text=True)
        import json
        self.assertEqual(json.loads(cli.stdout)["tool"], "fixture.image")
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = [{"segment_id": "seg-001", "component_id": "component-1", "tags": ["蓝色场景"]}]
        treatment["skill_selection"]["fixed_context"][0]["skill_id"] = "fixture"
        treatment["generation_plan"] = {"steps": [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "a blue scene"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "animate blue scene", "reference": {"$step": "image", "output": 0}}, "depends_on": ["image"]}]}
        artifacts.write_json_artifact(self.treatment, treatment)
        treatment = self._review_creator(segment, treatment,
            "muyang-flat-animation:muyang-flat-animation/design")
        artifacts.write_json_artifact(self.treatment, treatment)
        if reference_mode == "upload":
            missing_snapshot = copy.deepcopy(treatment)
            missing_snapshot["skill_selection"]["overlay_beats"] = [
                {"segment_id": "seg-001", "component_id": "component-1"}]
            artifacts.write_json_artifact(self.treatment, missing_snapshot)
            with self.assertRaisesRegex(vc.VisualConfirmationError, "review beat target is unknown or duplicated"):
                self.prepare()
            artifacts.write_json_artifact(self.treatment, treatment)
            planned = artifacts.read_json_artifact(self.fixture.brief)
            planned["segments"][0]["bindings"]["component-1"]["generation_id"] = "video"
            artifacts.write_json_artifact(self.fixture.brief, planned)
            invalid_identity = copy.deepcopy(treatment)
            invalid_identity["skill_selection"]["beats"][0]["binding_snapshot"] = copy.deepcopy(
                planned["segments"][0]["bindings"]["component-1"])
            artifacts.write_json_artifact(self.treatment, invalid_identity)
            with self.assertRaisesRegex(vc.VisualConfirmationError, "omit completed generation identity"):
                self.prepare()
            self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))
            del planned["segments"][0]["bindings"]["component-1"]["generation_id"]
            artifacts.write_json_artifact(self.fixture.brief, planned)
            artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                return_value=[{"text": "Approved source evidence", "start": 0.0, "end": 3.0}]):
            run_stage.run_visual_direction(self.job.job_dir, _env.PROJECT, self.fixture.brief, self.treatment)
        self.job = state.load_job(self.job.job_dir)
        self.confirm()
        image = self.job.job_dir / "source-image.png"
        from PIL import Image
        Image.new("RGB", (1080, 1920), "blue").save(image)
        video = self.job.job_dir / "source-video.mp4"
        original_video = self.job.job_dir / "provider-original-30fps.mp4"
        source = original_video if reference_mode == "upload" else video
        rate = 30 if reference_mode == "upload" else 24
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=blue:s=1080x1920:r={rate}:d=3",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        if reference_mode == "upload":
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(original_video), "-r", "24", "-an",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        original_confirmation = vc.validate_visual_authorization(self.job)["artifact"]
        # Only the independent, already-tested startup gate is a fixture. Queue,
        # authorization, actions, result copying, compiler and adapters are real.
        with mock.patch.object(queue, "_approved", return_value=(self.job.job_id, "fixture-config", config)):
            actions = vc.generation_actions(self.job)
            self.assertNotIn("model", actions[0]["arguments"])
            self.assertEqual([a["tool"] for a in actions], ["fixture.image"])
            channel.record_result(self.job.job_dir, actions[0], {"status": "completed", "artifacts": [{"type": "image", "path": str(image)}]})
            actions = vc.generation_actions(self.job)
            if reference_mode == "upload":
                upload = actions[0]
                self.assertEqual(upload["tool"], "fixture.upload")
                self.assertTrue(Path(upload["arguments"]["file"]).is_file())
                # A technical proposal revision must reuse the already-authorized
                # request and pending upload without rewriting the old receipt.
                before = queue.status(self.job.job_dir)
                old_auth = copy.deepcopy(before["items"][upload["request_id"]]["authorization"])
                previous_source = vc.validate_visual_authorization(self.job)["source"]["source_id"]
                state.revise(self.job, "visual_direction", "same content, technical preparation revised")
                revised = artifacts.read_json_artifact(self.treatment)
                revised["planning_notes"] = ["technical preparation checked; same generation content"]
                revised["numbering_scope_id"] = "scope-renumbered-plan"
                treatment["numbering_scope_id"] = revised["numbering_scope_id"]
                artifacts.write_json_artifact(self.treatment, revised)
                self.prepare(); self.confirm()
                current = vc.validate_visual_authorization(self.job)
                self.assertNotEqual(current["source"]["source_id"], previous_source)
                self.assertEqual(current["source"]["numbering_scope_id"], "scope-renumbered-plan")
                original_confirmation = current["artifact"]
                resumed_actions = vc.generation_actions(self.job)
                self.assertEqual(resumed_actions[0]["status"], "input_upload_pending")
                self.assertEqual(resumed_actions[0]["request_id"], upload["request_id"])
                after = queue.status(self.job.job_dir)
                self.assertEqual(set(after["items"]), set(before["items"]))
                self.assertEqual(after["items"][upload["request_id"]]["authorization"],
                    {'source': current['artifact'], 'steps': old_auth['steps']})
                step = current["source"]["generation_steps"][1]
                request = vc.resolve_generation_request(self.job, current["source"], step)
                self.assertEqual(request["id"], upload["request_id"])
                changed = copy.deepcopy(request)
                changed["arguments"]["prompt"] = "different request"
                self.assertIsNone(vc._equivalent_request_id(after, changed, step["id"], self.job))
                # Exercise the same stage entry the host uses for upload results.
                resumed = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"generation_results": [
                    {"action": upload, "response": {"data": {"asset_id": "actual-fixture-upload-id"}}}]})
                actions = resumed["actions"]
            self.assertEqual(actions[0]["tool"], "fixture.video")
            self.assertEqual(actions[0]["arguments"]["model"], "video-model")
            if reference_mode == "upload":
                self.assertEqual(actions[0]["arguments"]["reference"], "actual-fixture-upload-id")
            else:
                self.assertTrue(Path(actions[0]["arguments"]["reference"]).is_file())
            channel.record_result(self.job, actions[0], {"status": "pending", "task_ids": ["task-real-fixture"], "poll_after_seconds": 10})
            with mock.patch.object(channel.time, "time", return_value=time.time() + 60):
                query = vc.generation_actions(self.job)[0]
            self.assertEqual(query["tool"], "fixture.query")
            output = {"type": "video", "path": str(video)}
            if reference_mode == "upload":
                output.update(source={"path": str(original_video)}, processing="convert 30fps to 24fps; retain original")
                with self.assertRaisesRegex(ValueError, "both original source"):
                    channel.record_result(self.job, query, {"status": "completed", "artifacts": [
                        {key: value for key, value in output.items() if key != "source"}]})
            channel.record_result(self.job.job_dir, query, {"status": "completed", "artifacts": [output]})
            self.assertEqual(vc.generation_actions(self.job), [])
            proposal = vc.validate_visual_authorization(self.job)["source"]
            rid, _ = vc.generation_item(queue.status(self.job.job_dir), proposal, proposal["generation_steps"][1])
            aroll = next(r for r in self.job.stages["edit_structure"]["artifacts"] if r["path"].endswith("edited-aroll.mp4"))
            record = generated_media.record_from_queue(self.job, rid, segment_id="seg-001", component_id="component-1",
                source_binding={"aroll_sha256": aroll["sha256"], "start": 0.0, "end": 3.0},
                semantic_brief={"observed_scene": "Actual solid blue scene"}, ffprobe_executable="ffprobe")
            self.assertEqual(record["model"], "video-model")
            if reference_mode == "upload":
                self.assertTrue(Path(record["generation"]["source_media"]["path"]).is_file())
                self.assertEqual(record["generation"]["source_media"]["sha256"], artifacts.sha256_file(original_video))
                self.assertTrue(record["generation"]["input_bindings"])
                self.assertEqual(record["generation"]["submitted_request"]["arguments"]["reference"], "actual-fixture-upload-id")
                self.assertEqual(vc.validate_visual_authorization(self.job)["artifact"], original_confirmation)
            record_path = self.job.job_dir / "native-inputs/completed.json"
            artifacts.write_json_artifact(record_path, record)
            with self.assertRaisesRegex(ValueError, "another approved visual row"):
                generated_media.record_from_queue(self.job, rid, segment_id="wrong-row", component_id="component-1",
                    source_binding={}, semantic_brief={}, ffprobe_executable="ffprobe")
            segment["bindings"]["component-1"] = generated_media.prepare_binding(record)
            treatment["skill_selection"]["beats"][0]["binding_snapshot"] = copy.deepcopy(segment["bindings"]["component-1"])
            realized_director = self.job.job_dir / "native-inputs/realized-director.json"
            artifacts.write_json_artifact(realized_director, {"schema_version": 3, "segments": [segment]})
            ref = vc._record(self.job.job_dir, record_path)
            treatment["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": ref["path"],
                 "completed_record": {"job_path": ref["path"], "sha256": ref["sha256"], "byte_count": ref["bytes"]}}]
            realized_treatment = self.job.job_dir / "native-inputs/realized-treatment.json"
            artifacts.write_json_artifact(realized_treatment, treatment)
            from edit.hd.tools import motion_capabilities
            motion_capabilities._ai_brief_evidence(self.job.job_dir, treatment, segment, "component-1")
            (self.job.root / '00-user-provided').mkdir()
            result = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"realization": {
                "director_brief": str(realized_director), "treatment": str(realized_treatment)}})
            self.assertEqual(result["status"], "completed")
            adapters = run_stage.native_component_adapters(_env.PROJECT, state.load_job(self.job.job_dir))
            self.assertIn(("seg-001", "component-1"), adapters["ai_generated"])
            self.assertTrue(image.is_file() and video.is_file())

    def test_startup_allows_one_selected_generation_channel(self):
        from edit.hd.tools import startup
        image = {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image",
                 "connection_status": "verified", "quota_status": "available"}
        config = {"generation_enabled": True, "providers": [image]}
        self.assertEqual(startup.selected_channels(config)["image"]["endpoint_id"], "fixture.image")
        video = {**image, "purpose": "video", "model": "video-model", "endpoint_id": "fixture.video"}
        config["providers"].append(video)
        self.assertEqual(startup.selected_channels(config)["video"]["endpoint_id"], "fixture.video")

    def test_unconfirmed_proposal_cannot_start_generation(self):
        self.prepare()
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)

    def test_confirmation_requires_explicit_motion_query_tags(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = []
        director = artifacts.read_json_artifact(self.fixture.brief)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "explicit semantic retrieval tags"):
            vc._rows(director, treatment, [])

    def test_direct_material_keeps_source_separate_from_template(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["tags"], ["approved visual explanation"])
        self.assertEqual(rows[0]["source"], "asset-1")
        self.assertEqual(rows[0]["template"], "素材直用（无动效模板）")
        self.assertEqual(rows[0]["channel"], "Example Stock")

    def test_native_creation_uses_the_registered_template_in_the_list(self):
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        director = artifacts.read_json_artifact(self.fixture.brief)
        segment = director["segments"][0]
        segment["visual_strategy"]["components"][0]["kind"] = "code_generated"
        segment["bindings"]["component-1"] = {"dependency_id": "openfilm-motion-graphics",
                                               "template_id": "openfilm/motion-graphics-scene"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["assignments"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "candidate_id": "openfilm-motion-graphics:motion-graphics", "skill_id": "openfilm-motion-graphics",
            "template_id": "openfilm/motion-graphics-scene", "role": "native"}]
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["template"], "openfilm/motion-graphics-scene")
        self.assertEqual(rows[0]["channel"], "openfilm-motion-graphics")
        segment["visual_strategy"]["components"][0]["kind"] = "ai_generated"
        segment["bindings"]["component-1"] = {"provider": "Lovart", "generation_id": "fixture-generation"}
        treatment["skill_selection"]["assignments"][0].update(candidate_id="gbro-collage-broll:design",
            skill_id="gbro-collage-broll", template_id="gbro-collage-broll/design", role="design")
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["channel"], "gbro-collage-broll")
        self.assertEqual(rows[0]["template"], "gbro-collage-broll/design")
        self.assertEqual(rows[0]["generation_channel"], "Lovart")
        treatment["generation_plan"] = {"steps": [{"id":"image", "purpose":"image",
            "segment_id":segment["segment_id"], "component_id":"component-1", "arguments":{}},
            {"id":"video", "purpose":"video", "segment_id":segment["segment_id"],
             "component_id":"component-1", "arguments":{}, "depends_on":["image"]}]}
        rows = vc._rows(director, treatment, [],
            validate_semantic_lists(treatment, director)["component_rows"], {
                "image":{"provider":"Builtin", "model":"image-model"},
                "video":{"provider":"Lovart", "model":"Kling O1"}})
        self.assertEqual(rows[0]["channel"], "gbro-collage-broll")
        self.assertEqual(rows[0]["generation_channel"], "图片：Builtin / image-model；视频：Lovart / Kling O1")
        self.assertEqual(rows[0]["template"], "gbro-collage-broll/design")

    def test_channel_uses_real_source_instead_of_adapter_alias(self):
        director = {"segments": []}
        treatment = {"motion_queries": []}
        for index, dependency in enumerate(("hyperframes", "hyperframes-native-adaptation")):
            sid = f"seg-{index}"
            director["segments"].append({"segment_id": sid, "start": index, "end": index + 1,
                "visual_intent": {"statement": "顺序展开"},
                "visual_strategy": {"components": [{"component_id": "scene", "kind": "code_generated",
                                                     "layer_role": "base"}]},
                "bindings": {"scene": {"dependency_id": dependency, "template_id": f"template-{index}"}}})
            treatment["motion_queries"].append({"segment_id": sid, "component_id": "scene", "tags": ["顺序展开"]})
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        treatment["semantic_lists"] = {"overlay": [], "broll": [{
            "row_id": "shared", "start_word": 0, "end_word": 1, "quote": "x", "semantic": "顺序展开",
            "visual_task": "顺序展开", "components": [{"segment_id": f"seg-{i}", "component_id": "scene"}
                                                       for i in range(2)]}]}
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual([r["channel"] for r in rows], ["hyperframes", "hyperframes"])
        self.assertEqual([r["template"] for r in rows], ["template-0", "template-1"])

class PaperSourceReuseTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from types import SimpleNamespace
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.job = SimpleNamespace(job_dir=root, job_id='paper-source-fixture')
        artifacts.write_json_artifact(root/'workflow.json', {'job_id':self.job.job_id,'revision':10,
            'stages':{'visual_direction':{'lineage':[]}}})

    def test_paper_crop_consumption_requires_approved_source_and_exact_bound_pixels(self):
        from PIL import Image
        root = self.job.job_dir
        source, cropped, provenance, entry = (root / name for name in ('paper-source.png', 'paper-crop.png', 'paper-provenance.json', 'paper-scene.html'))
        image = Image.new('RGBA', (8, 8), (10, 20, 30, 128))
        image.putpixel((3, 3), (200, 2, 4, 255))
        image.save(source)
        image.crop((2, 2, 6, 6)).save(cropped)
        original = vc._record(root, source)
        output_sha = artifacts.sha256_file(cropped)
        entry.write_text('<html><body><img src="paper-crop.png"></body></html>', encoding='utf-8')
        brief = {'entry': {'job_path': entry.name, 'sha256': artifacts.sha256_file(entry)},
                 'assets': [{'job_path': cropped.name, 'scene_path': cropped.name, 'sha256': output_sha}]}
        proof = {'source_images': {'cutouts': {'path': source.name, 'sha256': original['sha256']}},
                 'crops': [{'source': source.name, 'source_sha256': original['sha256'],
                            'crop': [2, 2, 6, 6], 'output': cropped.name, 'output_sha256': output_sha}]}
        def check(data, assets=None, approved=None):
            artifacts.write_json_artifact(provenance, data)
            return vc._paper_crop_sources(root, assets or brief, vc._record(root, provenance),
                                          approved if approved is not None else [original])
        self.assertEqual(check(proof), {original['sha256']})
        with self.assertRaisesRegex(ValueError, 'approved generated image'):
            check(proof, approved=[])
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(proof, assets={**brief, 'assets': []})
        not_used = copy.deepcopy(brief); not_used['assets'][0]['scene_path'] = 'not-used.png'
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(proof, assets=not_used)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['crop'] = [1, 1, 5, 5]
        with self.assertRaisesRegex(ValueError, 'pixels differ'):
            check(wrong)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['crop'] = [0, 0, 9, 9]
        with self.assertRaisesRegex(ValueError, 'bounds exceed'):
            check(wrong)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['output_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(wrong)

        # Reuse proves the frozen current input against its original approval.
        check(proof)
        brief_path = root / 'paper-brief.json'; artifacts.write_json_artifact(brief_path, brief)
        native = {'segment_id':'seg-001', 'component_id':'scene', 'artifact':vc._record(root, brief_path),
                  'asset_provenance':vc._record(root, provenance)}
        binding = {'dependency_id':'paper-collage-hyperframes', 'brief_sha256':native['artifact']['sha256']}
        director = {'segments':[{'segment_id':'seg-001', 'bindings':{'scene':binding}}]}
        director_path = root / 'paper-director.json'; artifacts.write_json_artifact(director_path, director)
        receipt = {'path':'previous-receipt.json', 'sha256':'a'*64, 'bytes':1}
        treatment = {'skill_selection':{'revision_locks':{'previous_receipt':receipt}},
                     'scenes':[{'segment_id':'seg-001', 'component_id':'scene', 'brief_path':brief_path.name,
                         'asset_provenance':{'job_path':native['asset_provenance']['path'],
                            'sha256':native['asset_provenance']['sha256'],
                            'byte_count':native['asset_provenance']['bytes']}}]}
        treatment_path = root / 'paper-treatment.json'; artifacts.write_json_artifact(treatment_path, treatment)
        proposal = {'inputs':{'treatment':vc._record(root, treatment_path),
                              'director':vc._record(root,director_path)}, 'generation_steps':[]}
        from edit.hd.tools import generation_queue
        old_final = root / 'old-canonical.json'; artifacts.write_json_artifact(old_final,{'old':True})
        artifacts.write_json_artifact(old_final,{'current':True})
        source_ref = {'path':'old-proposal.json','sha256':'b'*64,'bytes':1}
        step = {'id':'paper-image', 'segment_id':'seg-001', 'component_id':'scene', 'purpose':'image'}
        origin_treatment = root/'origin-treatment.json'
        artifacts.write_json_artifact(origin_treatment, {'scenes':[{'segment_id':'seg-001','component_id':'scene'}]})
        old_source = {'source_id':'paper-origin','rows':[], 'generation_steps':[step],
                      'inputs':{'director':vc._record(root,director_path),'treatment':vc._record(root,origin_treatment)}}
        request = {'id':vc._request_id(old_source,step)}
        item = {'status':'completed','request':request,'authorization':{'source':receipt},
                'completion_response':{'artifacts':[{'type':'image',**original}]}}
        queue = {'items':{request['id']:item}}
        workflow = artifacts.read_json_artifact(root / 'workflow.json')
        workflow['stages']['visual_direction']['lineage'] = []
        artifacts.write_json_artifact(root / 'workflow.json', workflow)
        old_receipt = {'source':source_ref,'revision':1}
        def consume(actual_native=native, actual_treatment=treatment):
            return vc._realized_media_hashes(root,director,[],[actual_native],[],proposal,actual_treatment)
        with mock.patch.object(vc,'validate_realization_evidence',side_effect=AssertionError('old canonical must not be read')), \
             mock.patch.object(vc,'_validate_source',return_value=(old_receipt,old_source)) as verify, \
             mock.patch.object(state,'load_job',return_value=self.job), \
             mock.patch.object(generation_queue,'status',return_value=queue), \
             mock.patch.object(vc,'validate_generation_request',return_value={'step':step}):
            self.assertIn(original['sha256'],consume()[('seg-001','scene')])
            verify.assert_called_once_with(root,receipt,job_id=workflow['job_id'])
            self.assertEqual(proposal['generation_steps'],[])
            with mock.patch.object(vc,'_validate_source',side_effect=ValueError('wrong original authority')):
                with self.assertRaisesRegex(ValueError,'wrong original authority'):consume()
            changed_item = {**item,'authorization':{'source':{'path':'other-receipt.json'}}}
            with mock.patch.object(generation_queue,'status',return_value={'items':{request['id']:changed_item}}):
                with self.assertRaisesRegex(ValueError,'queue approval differs'):consume()
            alternate = root / 'other-provenance.json'; artifacts.write_json_artifact(alternate,proof)
            changed = {**native,'asset_provenance':vc._record(root,alternate)}
            altered = copy.deepcopy(treatment)
            altered['scenes'][0]['asset_provenance']['job_path'] = alternate.name
            with self.assertRaisesRegex(ValueError,'frozen component'):consume(changed,altered)
            wrong = copy.deepcopy(old_source); wrong['generation_steps'][0]['component_id']='another'
            with mock.patch.object(vc,'_validate_source',return_value=(old_receipt,wrong)):
                with self.assertRaisesRegex(ValueError,'component inputs|image source'):consume()
            self.assertIn(original['sha256'],consume()[('seg-001','scene')])


    def test_paper_sources_follow_explicit_approval_chain_per_image(self):
        from edit.hd.tools import generation_queue
        root = self.job.job_dir
        def ref(path, digest='a'):
            return {'path':path,'sha256':digest*64,'bytes':1}
        receipts = {name:ref(name+'.receipt') for name in ('A','B','C')}
        binding = {'dependency_id':'paper-collage-hyperframes','template_id':'paper/design','brief_sha256':'a'*64}
        director = {'segments':[{'segment_id':'seg-001','bindings':{'scene':binding}}]}
        scene = {'segment_id':'seg-001','component_id':'scene','brief_path':'brief',
                 'asset_provenance':{'job_path':'provenance','sha256':'a'*64,'byte_count':1}}
        native = {'segment_id':'seg-001','component_id':'scene','artifact':ref('brief'),'asset_provenance':ref('provenance')}
        def treatment(previous):
            return {'skill_selection':{'revision_locks':{'previous_receipt':previous}},'scenes':[scene]}
        images = {'a':ref('a.png'), 'b':ref('b.png','b'), 'oldb':ref('old-b.png','d')}
        values = {'workflow.json':{'job_id':self.job.job_id,'revision':10},'director':director,
                  'current':treatment(receipts['C']),'A':{'scenes':[{'segment_id':'seg-001','component_id':'scene'}]},
                  'B':treatment(receipts['A']),'C':treatment(receipts['B']),
                  'provenance':{'source_images':{'a':{'path':'a.png','sha256':'a'*64}}}}
        step = lambda name:{'id':name,'segment_id':'seg-001','component_id':'scene','purpose':'image'}
        sources = {name:{'source_id':name,'inputs':{'director':ref('director'),'treatment':ref(name)},
                         'generation_steps':[step('a')] if name=='A' else []} for name in ('A','B','C')}
        def item(name, image):
            rid=vc._request_id(sources[name],step(image))
            return rid,{'request':{'id':rid},'authorization':{'source':receipts[name]},'status':'completed',
                        'completion_response':{'artifacts':[{'type':'image',**images[image]}]}}
        rid,original=item('A','a');queue={'items':{rid:original}}
        sources['A']['generation_steps'].append(step('oldb'))
        old_b_id,old_b=item('A','oldb');queue['items'][old_b_id]=old_b
        def source(_, descriptor, **kwargs):
            name=descriptor['path'][0]
            return {'revision':{'A':1,'B':2,'C':3}[name]},sources[name]
        def approved(_, authorization, request, **kwargs):
            self.assertNotEqual(request['id'],old_b_id,'an unused replaced image must not be revalidated')
            name=authorization['source']['path'][0]
            return {'step':next(s for s in sources[name]['generation_steps'] if vc._request_id(sources[name],s)==request['id'])}
        with mock.patch.object(vc,'_exact',side_effect=lambda r,x:r/x['path']), \
             mock.patch.object(vc,'_path',side_effect=lambda r,p:r/p), \
             mock.patch.object(vc,'_read',side_effect=lambda p:values[Path(p).name]), \
             mock.patch.object(vc,'_record',side_effect=lambda r,p:images.get(Path(p).stem,ref(Path(p).name))), \
             mock.patch.object(vc,'_validate_source',side_effect=source), \
             mock.patch.object(state,'load_job',return_value=self.job), \
             mock.patch.object(generation_queue,'status',return_value=queue), \
             mock.patch.object(vc,'validate_generation_request',side_effect=approved):
            proposal={'inputs':{'director':ref('director'),'treatment':ref('current')},'generation_steps':[]}
            consume=lambda:vc._reused_paper_media(root,proposal,director,values['current'],native)
            self.assertEqual(consume(),[images['a']])
            # B replaces only b; a still comes from A, across zero-generation C.
            values['provenance']['source_images']['b']={'path':'b.png','sha256':'b'*64}
            sources['B']['generation_steps']=[step('b')];new_id,new_item=item('B','b');queue['items'][new_id]=new_item
            self.assertEqual({m['path'] for m in consume()},{'a.png','b.png'})
            # A currently used edited image must validate its explicit successor.
            new_item['completion_response']['artifacts']=[{'type':'image',**ref('b-initial.png','e')}]
            queue['items']['edited-b']={'retry_of':new_id,'plan_request_id':new_id,'status':'completed',
                'request':{'id':'edited-b'},'completion_response':{'artifacts':[{'type':'image',**images['b']}]}}
            with mock.patch.object(generation_queue,'_validate_image_successor') as check_successor:
                self.assertEqual({m['path'] for m in consume()},{'a.png','b.png'})
                check_successor.assert_called_once()
            queue['items'].pop('edited-b');new_item['completion_response']['artifacts']=[{'type':'image',**images['b']}]
            values['B']['skill_selection']['revision_locks']['previous_receipt']=receipts['C']
            with self.assertRaisesRegex(ValueError,'approval chain'):consume()
            values['B']['skill_selection']['revision_locks']['previous_receipt']=receipts['A']
            wrong=copy.deepcopy(director);wrong['segments'][0]['segment_id']='different'
            values['wrong-director']=wrong;sources['A']['inputs']['director']=ref('wrong-director')
            with self.assertRaisesRegex(ValueError,'component'):consume()
            sources['A']['inputs']['director']=ref('director')
            successor={'retry_of':rid,'plan_request_id':rid,'status':'completed','request':{'id':'retry'},
                       'completion_response':{'artifacts':[{'type':'image',**ref('unused.png','d')}]}}
            queue['items']['retry']=successor
            with mock.patch.object(generation_queue,'_validate_image_successor') as check_successor:
                self.assertEqual({m['path'] for m in consume()},{'a.png','b.png'})
                check_successor.assert_not_called()  # The later result is not used.
            queue['items'].pop('retry')
            original['authorization']['source']=receipts['B']
            with self.assertRaisesRegex(ValueError,'queue approval'):consume()



class NativeSupplementBoundaryTests(unittest.TestCase):
    def setUp(self):
        import tempfile, json, hashlib
        from test_motion_native_skill_adapter import brief
        import motion_native_skill_adapter as native
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.native=native
        base=fixture_api.draft_segment(('ai_generated',),end=2)
        base['visual_strategy']['components'][0].update(media_type='video',layout_slot='full_frame')
        sid=base['segment_id'];cid=base['visual_strategy']['components'][0]['component_id'];aid='advice'
        self.sid,self.cid,self.aid=sid,cid,aid
        request=brief();self.request=request
        source_task={'semantic_row_id':'task','quote':request['transcript'],'semantic':request['semantic_goal'],
                     'required_change':request['task_source']['required_change'],
                     'component_brief':base['visual_strategy']['components'][0]['brief']}
        request['task_source']=source_task
        base['bindings']={cid:{'provider':'Lovart','model':'approved-model','endpoint_id':'approved-video'}}
        self.old={'schema_version':3,'segments':[base]}
        row={'row_id':'task','quote':request['transcript'],'semantic':request['semantic_goal'],
             'components':[{'segment_id':sid,'component_id':cid}]}
        beat={'segment_id':sid,'component_id':cid,'semantic_row_id':'task','transcript':request['transcript'],
              'required_change':source_task['required_change'],'component_brief':source_task['component_brief']}
        self.old_t={'semantic_lists':{'broll':[row],'overlay':[]},'scenes':[],
                    'skill_selection':{'beats':[beat],'assignments':[]},'motion_readability':[],
                    'motion_queries':[],'beat_sheet':[{'components':[{'segment_id':sid,'component_id':cid}]}]}
        self.director=copy.deepcopy(self.old);self.treatment=copy.deepcopy(self.old_t)
        new=self.director['segments'][0];strategy=new['visual_strategy'];strategy['mode']='hybrid'
        action={**strategy['components'][0],'component_id':aid,'kind':'code_generated',
                'layer_role':'annotation','layout_slot':'annotation','media_type':'animation'}
        strategy['components'].append(action)
        strategy['composition'].update(family='evidence_with_data_overlay',reading_order=[cid,aid],
            component_dependencies=[{'component_id':aid,'depends_on':[cid]}])
        media=self.root/'base.mp4';media.write_bytes(b'actual registered provider bytes')
        ref=native.descriptor(self.root,media)
        self.record={'schema_version':3,'job_id':request['job_id'],'status':'completed','segment_id':sid,'component_id':cid,
            'source_binding':{k:request['source_binding'][k] for k in ('aroll_sha256','start','end')},
            'media':{**ref,'media_type':'video'},'source_dimensions':{'width':1080,'height':1920},
            'composition_base':{'action_component_id':aid,'source_qa':{'passed':False,'observed_scene':'Missing advice'}},
            'qa':{'passed':True,'scope':'composition_base','observed_scene':'Usable task base only'},
            'generation':{'approved_request_id':'request','approved_request':{'id':'request'},
                          'approved_plan':{'source':{'fixture':'existing receipt'},'steps':{'request':'video-step'}}}}
        request['materials']=[ref]
        request['alpha']=True
        self.path=self.root/'native-inputs/alpha-brief.json';self.path.parent.mkdir()
        artifacts.write_json_artifact(self.path,request)
        new['bindings'][aid]={'dependency_id':'barty-motion-graphics',
            'brief_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}
        new['bindings'][cid].update(execution_mode='reuse_completed_generated_media',sha256=ref['sha256'])
        record_path=self.root/'base-record.json';artifacts.write_json_artifact(record_path,self.record)
        self.treatment['scenes']=[{'segment_id':sid,'component_id':cid,'completed_record':native.descriptor(self.root,record_path)},
            {'segment_id':sid,'component_id':aid,'brief_path':'native-inputs/alpha-brief.json'}]
        self.treatment['semantic_lists']['broll'][0]['components'].append({'segment_id':sid,'component_id':aid})
        self.treatment['beat_sheet'][0]['components'].append({'segment_id':sid,'component_id':aid})
        self.treatment['beat_sheet'][0]['merge_reason']='Native advice belongs to the same original task'
        self.treatment['skill_selection']['beats'].append({**beat,'component_id':aid})
        self.treatment['motion_readability']=[{'segment_id':sid,'component_id':aid,'targets':[],'pending_native':True}]
        self.treatment['native_supplements']=[{'segment_id':sid,'base_component_id':cid,'action_component_id':aid,
                                            'reason':'Actual source misses the approved advice action'}]
        d=self.root/'original-director.json';t=self.root/'original-treatment.json'
        artifacts.write_json_artifact(d,self.old);artifacts.write_json_artifact(t,self.old_t)
        self.proposal={'inputs':{'director':vc._record(self.root,d),'treatment':vc._record(self.root,t)},
                      'generation_steps':[{'id':'video-step','segment_id':sid,'component_id':cid,'purpose':'video'}]}

    def validate(self,director=None,treatment=None):
        from edit.hd.tools import motion_capabilities
        with mock.patch.object(vc,'_native_result_adapter',return_value=self.native), \
             mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(self.record,{})), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)):
            submitted, inputs = director or self.director, treatment or self.treatment
            normalized, compared = vc._normalize_native_supplements(
                self.root, self.proposal, self.old, self.old_t, submitted, inputs)
            normalized = vc._normalize_verified_technical_revisions(
                self.old, self.old_t, submitted, inputs, normalized)
            vc._validate_draft_against_source(self.root, self.proposal, normalized, compared)

    def test_pending_supplement_retains_original_plan_and_rejects_source_task_or_clock_drift(self):
        from edit.hd.tools import visual_strategy
        segment=self.director['segments'][0]
        visual_strategy.validate_visual_strategy(segment['visual_intent'],segment['visual_strategy'])
        self.validate()
        for field in ('time','meaning','avatar','base','paid','queue','unrelated'):
            d,t=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
            if field=='time':d['segments'][0]['end']=3
            if field=='meaning':t['semantic_lists']['broll'][0]['semantic']='another meaning'
            if field=='avatar':d['segments'][0]['visual_strategy']['composition']['presenter_mode']='hidden'
            if field=='base':d['segments'][0]['visual_strategy']['components'][0]['brief']='another task'
            if field=='paid':t['generation_plan']={'steps':[{'new':'paid request'}]}
            if field=='queue':
                self.record['generation']['approved_plan']['steps']['request']='wrong-step'
            if field=='unrelated':d['segments'].append(copy.deepcopy(d['segments'][0]))
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(d,t)
            self.record['generation']['approved_plan']['steps']['request']='video-step'
        self.assertEqual(self.old['segments'][0]['visual_strategy']['mode'],'single')
        self.assertEqual(self.director['segments'][0]['visual_strategy']['mode'],'hybrid')
        self.assertEqual(self.old['segments'][0]['strategy_revision'],self.director['segments'][0]['strategy_revision'])
        changed=copy.deepcopy(self.director);changed['segments'][0]['strategy_revision']+=1
        with self.assertRaisesRegex(ValueError,'technical strategy revision needs'):
            self.validate(director=changed)

    def test_completed_supplement_requires_real_native_result_alignment_and_text(self):
        result=self.root.joinpath(self.request['result_record_path']);result.parent.mkdir(parents=True,exist_ok=True)
        result.write_text('{}')
        with self.assertRaisesRegex(ValueError,'alignment'):
            self.validate()
        self.root.joinpath(self.request['result_record_path']).unlink()
        changed=copy.deepcopy(self.treatment)
        changed['motion_readability'][0].pop('pending_native')
        with self.assertRaisesRegex(ValueError,'unfinished'):
            self.validate(treatment=changed)

    def test_completed_supplement_reuses_hybrid_checks_and_exact_rendered_text(self):
        source=self.root/'source.html';source.write_text('<p>建议</p>')
        call=self.root/'call.json';artifacts.write_json_artifact(call,{'project_files':[self.native.descriptor(self.root,source)]})
        alpha=self.root/'alpha.mov';alpha.write_bytes(b'isolated native output fixture')
        result={'status':'completed','media':self.native.descriptor(self.root,alpha),
                'render_call':self.native.descriptor(self.root,call)}
        result_path=self.root/self.request['result_record_path'];result_path.parent.mkdir(parents=True)
        artifacts.write_json_artifact(result_path,result)
        binding=self.director['segments'][0]['bindings'][self.aid]
        binding['invocation_record']={'canvas_alignment':{'mode':'identity','base_component_id':self.cid,
            'base_sha256':self.record['media']['sha256'],'layer_sha256':result['media']['sha256']}}
        self.director['segments'][0]['visible_text']=['建议']
        target={'target_id':'advice','content_ref':{'path':'source.html','sha256':self.native.sha(source),
                'pointer':'text:3:5','value':'建议'},'span':[0,2],'role':'title',
                'region':{'x':100,'y':200,'width':400,'height':100},'windows':[{'start':.5,'end':1.5}]}
        self.treatment['motion_readability'][0]={'segment_id':self.sid,'component_id':self.aid,'targets':[target]}
        self.treatment['semantic_assessments']=[{'segment_id':self.sid,'component_id':self.aid,
            'candidate_id':'barty-motion-graphics:barty-motion-graphics/motion-broll','verdict':'pass',
            'content_refs':[{'path':self.request['result_record_path'],'sha256':self.native.sha(result_path),
                             'pointer':'/status','value':'completed'}]}]
        with mock.patch.object(self.native,'inspect_result',return_value=result):
            self.validate()
            changed=copy.deepcopy(self.director)
            changed['segments'][0]['bindings'][self.aid]['invocation_record']['canvas_alignment']['layer_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'action media differs'):self.validate(director=changed)
            changed=copy.deepcopy(self.treatment)
            changed['motion_readability'][0]['targets'][0]['content_ref']['sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'actual rendered native source'):self.validate(treatment=changed)

    def test_camera_realization_requires_the_same_original_proposal_and_queue_pixels(self):
        import generated_media
        from edit.hd.tools import parent_camera_framing as camera, motion_capabilities
        from types import SimpleNamespace
        record=copy.deepcopy(self.record);record.pop('composition_base')
        record['qa']['scope']='framing_source';record['generation']['request_id']='request'
        data={'schema_version':1,'segment_id':self.sid,'component_id':self.cid,
              'source_binding':record['source_binding'],'source_media':record['media'],
              'normalized_media':record['media'],'source_frames':[0,48],
              'path':[{'frame':n,'x':0,'y':0,'width':1080,'height':1920} for n in range(48)],
              'reason':'Focus the original checked calendar without replacing its content'}
        path=self.root/'camera.json';artifacts.write_json_artifact(path,data)
        ref=self.native.descriptor(self.root,path)
        record['camera_source']={'framing':ref}
        director=copy.deepcopy(self.old);treatment=copy.deepcopy(self.old_t)
        director['segments'][0]['bindings'][self.cid].update(execution_mode='reuse_completed_generated_media',
            sha256=record['media']['sha256'],**{camera.FIELD:ref})
        job=SimpleNamespace(job_dir=self.root,job_id=record['job_id'])
        with mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(record,{})), \
             mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(generated_media,'_queue_media',return_value=record['media']), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)):
            vc._validate_parent_camera_framing(self.root,self.proposal,self.old,director,treatment)
            with mock.patch.object(vc,'_validate_source',return_value=({},{'another':'proposal'})):
                with self.assertRaisesRegex(ValueError,'another approved visual proposal'):
                    vc._validate_parent_camera_framing(self.root,self.proposal,self.old,director,treatment)
            with mock.patch.object(generated_media,'_queue_media',return_value={**record['media'],'sha256':'e'*64}):
                with self.assertRaisesRegex(ValueError,'original generation'):
                    vc._validate_parent_camera_framing(self.root,self.proposal,self.old,director,treatment)

    def test_selector_supplement_scope_reuses_actual_realization_proof_and_source_locks(self):
        from edit.hd.tools import broll_skill_selection as selection, motion_capabilities
        from types import SimpleNamespace
        job=SimpleNamespace(job_dir=self.root,job_id=self.request['job_id'])
        with mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(vc,'validate_visual_authorization',return_value={'source':self.proposal}), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)), \
             mock.patch.object(vc,'_native_result_adapter',return_value=self.native), \
             mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(self.record,{})):
            keys,locks=selection._verified_supplement_routes(self.root,self.director,self.treatment)
            self.assertEqual(keys,{(self.sid,self.aid)})
            self.assertEqual(locks[(self.sid,self.aid)],'barty-motion-graphics:barty-motion-graphics/motion-broll')
            altered=copy.deepcopy(self.director)
            altered['segments'][0]['bindings'][self.cid]['provider']='another source'
            with self.assertRaisesRegex(ValueError,'approved source'):
                selection._verified_supplement_routes(self.root,altered,self.treatment)
            self.record['schema_version']=2
            with self.assertRaisesRegex(ValueError,'original completed video'):
                selection._verified_supplement_routes(self.root,self.director,self.treatment)


class MotionRealizationBoundaryTests(unittest.TestCase):
    """A native result may reveal text, without changing its approved task."""
    def test_prepared_paper_layout_revision_uses_registered_actual_origin(self):
        import tempfile, hashlib
        from types import SimpleNamespace
        from edit.hd.tools import motion_capabilities, generation_queue, motion_readability
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();key=('seg-001','component-1')
            def write(name,value):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                if isinstance(value,bytes):path.write_bytes(value)
                else:artifacts.write_json_artifact(path,value)
                return vc._record(root,path)
            aroll=write('06-edit-structure/edited-aroll.mp4',b'approved source clock')
            image=write('paper.png',b'unchanged approved paper bitmap')
            provenance=write('crop.json',{})
            base={'producer_type':'dependency','dependency_id':'paper-collage-hyperframes',
                  'entrypoint':'scripts/paper_hyperframes_adapter.py','producer_version':'2.0.0',
                  'template_id':'paper-collage-ad-hyperframes-portrait-adaptation','primary_renderer':'HyperFrames'}
            source_sha=artifacts.sha256_file(_env.PROJECT/base['entrypoint'])
            html='<style>.label{top:100px;animation:fade 3s}</style><div class="label">任务示意</div><img src="paper.png"><script>window.clock=3;</script>'
            def prepare(name,markup,*,end=3,asset=None):
                entry=write(name+'/index.html',markup.encode())
                brief={'schema_version':2,'source_binding':{'aroll_sha256':aroll['sha256'],'segment_id':key[0],'start':0,'end':end},
                    'template_request':{'semantic_family':'explanation','information_units':1,'numeric_values':[],'numeric_scale':'not_applicable'},
                    'entry':{'media_ref':'entry','job_path':entry['path'],'sha256':entry['sha256'],'scene_path':'index.html'},
                    'assets':[{'media_ref':'paper','job_path':(asset or image)['path'],'sha256':(asset or image)['sha256'],'scene_path':'paper.png'}],
                    'composition':{'width':1080,'height':1920,'fps':24,'frames':round(end*24),'alpha':False},
                    'upstream_route':'paper-collage-ad/hyperframes','source_pins':{'route':'paper-collage-ad/hyperframes',
                        'sha256':artifacts.sha256_file(_env.PROJECT/'vendor/paper-collage-ad-codex/references/hyperframes-route.md')},
                    'word_anchors':[{'text':'原话','start':0,'end':1}]}
                ref=write(name+'/brief.json',brief)
                binding={**base,'brief_sha256':ref['sha256'],'source_entrypoint':base['entrypoint'],
                    'source_sha256':source_sha,'renderer_version':'fixture-runtime','template_version':'2.0.0',
                    'template_origin':'custom_fallback','adaptation_level':'structural',
                    'verification_id':hashlib.sha256((source_sha+entry['sha256']).encode()).hexdigest(),
                    'semantic_families':['explanation'],'capacity':{'min_units':1,'max_units':1},
                    'invocation_record':{'argv':[sys.executable,base['entrypoint']],'status':'planned','exit_code':None,
                                         'template_request':brief['template_request']}}
                at=markup.index('任务示意')
                reading={'segment_id':key[0],'component_id':key[1],'targets':[{'target_id':'title','role':'title',
                    'span':[0,4],'content_ref':{'path':entry['path'],'sha256':entry['sha256'],
                        'pointer':f'text:{at}:{at+4}','value':'任务示意'},
                    'region':{'x':100,'y':120,'width':400,'height':80},'windows':[{'start':.5,'end':2.5}]}]}
                return ref['path'],binding,reading
            old_path,old_binding,old_read=prepare('old',html)
            new_path,new_binding,new_read=prepare('new',html.replace('top:100px','top:120px'))
            segment=fixture_api.draft_segment(('code_generated',));segment['bindings']={key[1]:base}
            frozen={'schema_version':3,'segments':[segment]}
            frozen_t={'scenes':[{'segment_id':key[0],'component_id':key[1]}],
                      'skill_selection':{'beats':[{'segment_id':key[0],'component_id':key[1],'binding_snapshot':base}]}}
            def actual(path,binding,reading,revision):
                d=copy.deepcopy(frozen);d['segments'][0].update(bindings={key[1]:binding},strategy_revision=revision)
                t=copy.deepcopy(frozen_t);t['scenes'][0].update(brief_path=path,
                    asset_provenance={'job_path':provenance['path'],'sha256':provenance['sha256'],'byte_count':provenance['bytes']})
                t['skill_selection']['beats'][0]['binding_snapshot']=binding
                t['motion_readability']=[reading]
                return d,t
            previous,previous_t=actual(old_path,old_binding,old_read,3)
            director,treatment=actual(new_path,new_binding,new_read,4)
            config=write('manifests/provider-config.json',{})
            step={'id':'paper-image','segment_id':key[0],'component_id':key[1],'purpose':'image'}
            proposal={'job_id':'job','kind':vc.SCHEMA,'provider_config_sha256':config['sha256'],
                      'inputs':{'director':write('frozen.json',frozen),'treatment':write('frozen-treatment.json',frozen_t)},
                      'generation_steps':[step]}
            pref=write('proposal.json',proposal);write('workflow.json',{'job_id':'job'})
            approval=write('receipt.json',{'source_schema':vc.SCHEMA,'job_id':'job','job_dir':str(root),
                'stage':'visual_direction','passed':True,'authorized_by':'user','authorization_scope':'visual_plan_and_generation',
                'revision':1,'note':'fixture','user_confirmation':'approved','artifacts':[pref],'source':pref})
            origin=write('old/execution-mapping.json',{'proposal':pref,'source_approval':approval,
                'realization_inputs':{'director':write('old/director.json',previous),'treatment':write('old/treatment.json',previous_t)}})
            treatment['scenes'][0].update(native_revision_from=origin,native_revision_reason='Move the existing label clear of its paper pattern.')
            item={'status':'completed','authorization':{},'request':{},'completion_response':{'artifacts':[
                {'path':str(root/image['path']),'sha256':image['sha256'],'bytes':image['bytes']}]}}
            item['authorization']={'source':approval}
            job=SimpleNamespace(stages={'edit_structure':{'status':'completed','artifacts':[aroll]},
                                       'visual_direction':{'artifacts':[],'lineage':[origin]}})
            def check(d,t):return vc._normalize_prepared_paper(root,proposal,frozen,frozen_t,d,t)
            with mock.patch.object(state,'load_job',return_value=job), \
                 mock.patch.object(vc,'planned_generation_targets',return_value={key}), \
                 mock.patch.object(generation_queue,'status',return_value={'items':{'image':item}}), \
                 mock.patch.object(vc,'generation_item',return_value=('image',item)), \
                 mock.patch.object(vc,'validate_generation_request',return_value={'step':step}), \
                 mock.patch.object(motion_capabilities,'load_catalog',return_value=[base]), \
                 mock.patch.object(motion_capabilities,'_native_input_check',return_value={'status':'pass'}), \
                 mock.patch.object(vc,'_paper_crop_sources',return_value={image['sha256']}), \
                 mock.patch.object(motion_readability,'validate_targets'):
                compared,_=check(director,treatment)
                self.assertEqual(compared['segments'][0]['strategy_revision'],frozen['segments'][0]['strategy_revision'])
                for scenes in ([{'segment_id':key[0],'component_id':key[1]}], [], None):
                    deferred = copy.deepcopy(frozen_t)
                    if scenes is None:
                        deferred.pop('scenes')
                    else:
                        deferred['scenes'] = scenes
                    _, normalized = vc._normalize_prepared_paper(root,proposal,frozen,deferred,previous,previous_t)
                    self.assertEqual(normalized.get('scenes'),deferred.get('scenes'))
                    self.assertIn('brief_path',previous_t['scenes'][0])
                for scenes in (frozen_t['scenes'] * 2,
                               [{**frozen_t['scenes'][0], 'brief_path':'already-prepared.json'}]):
                    with self.subTest(old_scenes=scenes), self.assertRaisesRegex(ValueError,'bound brief'):
                        vc._normalize_prepared_paper(root,proposal,frozen,{**frozen_t,'scenes':scenes},previous,previous_t)
                self.assertEqual(director['segments'][0]['strategy_revision'],4)
                self.assertIn('native_revision_from',treatment['scenes'][0])
                for defect in ('script','asset','clock','text','window','origin','revision'):
                    d,t=copy.deepcopy(director),copy.deepcopy(treatment)
                    if defect in {'script','asset','clock'}:
                        path,binding,reading=prepare(defect,html.replace('top:100px','top:120px').replace(
                            'window.clock=3','window.clock=4') if defect=='script' else html.replace('top:100px','top:120px'),
                            end=4 if defect=='clock' else 3,asset=write('other.png',b'other bitmap') if defect=='asset' else None)
                        d['segments'][0]['bindings'][key[1]]=binding;t['scenes'][0]['brief_path']=path
                        t['skill_selection']['beats'][0]['binding_snapshot']=binding;t['motion_readability']=[reading]
                    elif defect=='text':t['motion_readability'][0]['targets'][0]['content_ref']['value']='换个词语'
                    elif defect=='window':t['motion_readability'][0]['targets'][0]['windows']=[{'start':1,'end':2}]
                    elif defect=='origin':t['scenes'][0]['native_revision_from']={**origin,'path':'unregistered/execution-mapping.json'}
                    else:d['segments'][0]['strategy_revision']=5
                    with self.subTest(defect=defect),self.assertRaises(ValueError):check(d,t)

    def test_hyperframes_repair_verifies_registered_origin_envelope_and_actual_text(self):
        import hashlib, json, tempfile
        from types import SimpleNamespace
        import hyperframes_native_adapter as native
        from edit.hd.tools import overlay_alignment
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def write(name, value):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value, bytes): path.write_bytes(value)
                else: artifacts.write_json_artifact(path, value)
                return vc._record(root, path)
            source = _env.PROJECT / 'vendor/hyperframes/registry/components/before-after-wipe/before-after-wipe.html'
            source_sha = artifacts.sha256_file(_env.SKILL / native.ENTRY)
            adapter = SimpleNamespace(entrypoint_sha256=source_sha, launcher=Path(sys.executable))
            def prepare(name, split, exit):
                props = {'label_a':'陌生号','label_b':'贷款','rest_split':split,'wipe_at':1,'exit':exit}
                width = 960 if name == 'old' else 520
                html = ('<html><head><script>window.hostReady=true;</script><style>.layout{width:' + str(width) +
                        'px;height:300px}</style></head><body><div class="layout" style="left:60px" data-composition-id="before-after-wipe" data-composition-src="native.html" data-start="0" data-duration="4" data-variable-values=\'' + json.dumps(props, ensure_ascii=False) + '\'></div></body></html>')
                entry = write(name + '/index.html', html.encode())
                clock = overlay_alignment.bind_native_clock(source.read_bytes(), 'hyperframes/before-after-wipe', 4)
                slots = {'before':'<svg><circle cx="5" cy="5" r="4"/></svg>',
                         'after':'<svg><rect x="1" y="1" width="8" height="8"/></svg>'}
                mounted = write(name + '/native.html', overlay_alignment.bind_native_slots(clock, slots))
                def asset(ref, record, scene):
                    return {'media_ref':ref,'job_path':record['path'],'sha256':record['sha256'],'scene_path':scene}
                brief = {'schema_version':2,'source_binding':{'aroll_sha256':'a'*64,'segment_id':'seg-001','start':0,'end':4},
                    'template_request':{'semantic_family':'state_comparison','information_units':2,'numeric_values':[],'numeric_scale':'not_applicable'},
                    'entry':asset('entry', entry, 'index.html'),'assets':[asset('native', mounted, 'native.html')],
                    'composition':{'width':1080,'height':1920,'fps':24,'frames':96,'alpha':True},
                    'upstream_route':'hyperframes/before-after-wipe',
                    'source_pins':{'route':'hyperframes/before-after-wipe','sha256':artifacts.sha256_file(source)}}
                ref = write(name + '/brief.json', brief)
                payload = (root/ref['path']).read_bytes()
                return brief, ref['path'], native.create_binding(adapter, payload)
            old, old_path, binding = prepare('old', 65, 'fade')
            new, new_path, revised = prepare('new', 100, 'none')
            segment = {'segment_id':'seg-001','start':0,'end':4,'strategy_revision':1,
                'visible_text':['陌生号','贷款'],'visual_intent':{'statement':'接听后揭示来电身份'},
                'visual_strategy':{'components':[{'component_id':'scene','kind':'code_generated'}]},'bindings':{'scene':binding}}
            frozen = {'segments':[segment, {'segment_id':'seg-002','start':4,'end':5,'strategy_revision':1,
                'visual_strategy':{'components':[]},'bindings':{}}]}
            def targets(brief):
                text = (root/brief['entry']['job_path']).read_text()
                result = []
                for i, word in enumerate(segment['visible_text']):
                    at = text.index(word)
                    result.append({'target_id':'label-'+str(i),'role':'title','span':[0,len(word)],
                        'content_ref':{'path':brief['entry']['job_path'],'sha256':brief['entry']['sha256'],
                            'pointer':f'text:{at}:{at+len(word)}','value':word},
                        'region':{'x':100,'y':100,'width':400,'height':100},'windows':[{'start':.5+i*2,'end':1.5+i*2}]})
                return result
            treatment = {'scenes':[{'segment_id':'seg-001','component_id':'scene','brief_path':old_path}],
                'skill_selection':{'overlay_beats':[{'segment_id':'seg-001','component_id':'scene','binding_snapshot':binding,'transcript':'原话'}]},
                'motion_readability':[{'segment_id':'seg-001','component_id':'scene','targets':targets(old)}],
                'overlay_alignment':[{'segment_id':'seg-001','component_id':'scene','brief_path':old_path,'events':['same source words']}],
                'semantic_assessments':[{'segment_id':'seg-001','component_id':'scene','candidate_id':'overlay:before-after-wipe',
                    'transcript_refs':['same source words'],'content_refs':[],'verdict':'pass','reason':'approved'}]}
            dref, tref = write('director.json', frozen), write('treatment.json', treatment)
            config = write('manifests/provider-config.json', {})
            write('workflow.json', {'job_id':'job'})
            proposal = {'job_id':'job','kind':vc.SCHEMA,'inputs':{'director':dref,'treatment':tref},'provider_config_sha256':config['sha256']}
            pref = write('proposal.json', proposal)
            approval = write('receipt.json', {'source_schema':vc.SCHEMA,'job_id':'job','job_dir':str(root),
                'stage':'visual_direction','passed':True,'authorized_by':'user','authorization_scope':'visual_plan_and_generation',
                'revision':1,'note':'fixture','user_confirmation':'approved','artifacts':[pref],'source':pref})
            origin = write('prior/execution-mapping.json', {'proposal':pref,'source_approval':approval,
                'realization_inputs':{'director':dref,'treatment':tref}})
            director, actual = copy.deepcopy(frozen), copy.deepcopy(treatment)
            director['segments'][0].update(strategy_revision=2,bindings={'scene':revised})
            actual['scenes'][0].update(brief_path=new_path,native_revision_from=origin,native_revision_reason='真实终态与留白问题')
            actual['overlay_alignment'][0]['brief_path']=new_path
            actual['skill_selection']['overlay_beats'][0]['binding_snapshot']=copy.deepcopy(revised)
            actual['motion_readability'][0]['targets']=targets(new)
            job = SimpleNamespace(stages={'visual_direction':{'artifacts':[origin],'lineage':[]}})
            def check(director, actual):
                normalized, compared = vc._normalize_hyperframes_revisions(root, frozen, treatment, director, actual)
                vc._validate_draft_against_source(root, proposal, normalized, compared)
            with mock.patch.object(state,'load_job',return_value=job):
                check(director,actual)
                self.assertEqual(director['segments'][0]['strategy_revision'],2)
                self.assertEqual(actual['scenes'][0]['brief_path'],new_path)
                with mock.patch.object(vc.shutil, 'which', return_value=None):
                    vc._normalize_hyperframes_revisions(root, frozen, treatment, frozen, treatment)
                    with self.assertRaisesRegex(ValueError, 'prepared HyperFrames runtime'):
                        check(director, actual)
                html = (root / new['entry']['job_path']).read_text()
                changed_hosts = {
                    'new_script': html.replace('</head>', '<script>window.addedMotion=true;</script></head>'),
                    'changed_script': html.replace('hostReady=true', 'hostReady=false'),
                    'event': html.replace('<body>', '<body onload="startMotion()">'),
                    'animation': html.replace('</style>', '.layout{animation:blink 1s}</style>'),
                    'transition': html.replace('left:60px', 'left:60px;transition:all 1s'),
                    'keyframes': html.replace('</style>', '@keyframes blink{to{opacity:0}}</style>'),
                    'nested_animation': html.replace('</style>', '@media(min-width:1px){.layout{animation-name:blink}}</style>'),
                    'escaped_animation': html.replace('</style>', r'.layout{anim\61tion:blink 1s}</style>'),
                }
                for label, changed_html in changed_hosts.items():
                    changed, altered = copy.deepcopy(director), copy.deepcopy(actual)
                    brief = copy.deepcopy(new)
                    entry_ref = write(label + '/index.html', changed_html.encode())
                    brief['entry'].update(job_path=entry_ref['path'], sha256=entry_ref['sha256'])
                    ref = write(label + '/brief.json', brief)
                    changed_binding = native.create_binding(adapter, (root / ref['path']).read_bytes())
                    changed['segments'][0]['bindings']['scene'] = changed_binding
                    altered['scenes'][0]['brief_path'] = ref['path']
                    altered['overlay_alignment'][0]['brief_path'] = ref['path']
                    altered['skill_selection']['overlay_beats'][0]['binding_snapshot'] = copy.deepcopy(changed_binding)
                    altered['motion_readability'][0]['targets'] = targets(brief)
                    with self.subTest(host_change=label), self.assertRaisesRegex(ValueError, 'parent'):
                        check(changed, altered)
                for mutation in ('source','template','timing','origin','revision','text','window','other_row','word_anchor'):
                    changed, altered = copy.deepcopy(director), copy.deepcopy(actual)
                    if mutation in {'source','timing'}:
                        brief=copy.deepcopy(new)
                        if mutation=='source':brief['source_binding']['aroll_sha256']='b'*64
                        else:brief['source_binding']['end']=4.5;brief['composition']['frames']=108
                        ref=write(mutation+'/brief.json',brief)
                        changed['segments'][0]['bindings']['scene']=native.create_binding(adapter,(root/ref['path']).read_bytes())
                        altered['scenes'][0]['brief_path']=ref['path']
                        altered['overlay_alignment'][0]['brief_path']=ref['path']
                        altered['skill_selection']['overlay_beats'][0]['binding_snapshot']=copy.deepcopy(changed['segments'][0]['bindings']['scene'])
                    elif mutation=='template':changed['segments'][0]['bindings']['scene']['template_id']='another-template'
                    elif mutation=='origin':altered['scenes'][0]['native_revision_from']={**origin,'path':'unregistered/execution-mapping.json'}
                    elif mutation=='revision':changed['segments'][0]['strategy_revision']=3
                    elif mutation=='text':altered['motion_readability'][0]['targets'][0]['content_ref']['value']='另一词'
                    elif mutation=='window':altered['motion_readability'][0]['targets'][0]['windows']=[{'start':3.8,'end':4}]
                    elif mutation=='other_row':changed['segments'][1]['end']=6
                    else:altered['overlay_alignment'][0]['events']=['different source words']
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        check(changed,altered)
                with self.assertRaisesRegex(ValueError,'verified implementation'):
                    vc._normalize_verified_technical_revisions(frozen,treatment,director,actual,director)

    def test_native_repair_binds_registered_prior_mapping_and_next_real_revision(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = {'segments': [{'segment_id': 'seg-001', 'strategy_revision': 1, 'bindings': {
                'native': {'dependency_id': 'bang-motion', 'brief_sha256': 'a' * 64}}}]}
            def write(name, value):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                artifacts.write_json_artifact(path, value)
                return vc._record(root, path)
            director = write('director.json', old)
            treatment = write('treatment.json', {'scenes': [
                {'segment_id': 'seg-001', 'component_id': 'native'}]})
            config = write('manifests/provider-config.json', {})
            write('workflow.json', {'job_id': 'job'})
            proposal = write('proposal.json', {'job_id': 'job', 'kind': vc.SCHEMA,
                'provider_config_sha256': config['sha256'], 'inputs': {'director': director}})
            approval = write('receipt.json', {'source_schema': vc.SCHEMA, 'job_id': 'job',
                'job_dir': str(root), 'stage': 'visual_direction', 'passed': True,
                'authorized_by': 'user', 'authorization_scope': 'visual_plan_and_generation',
                'revision': 1, 'note': 'fixture', 'user_confirmation': 'approved', 'artifacts': [proposal], 'source': proposal})
            previous = write('prior/execution-mapping.json', {'proposal': proposal, 'source_approval': approval,
                'realization_inputs': {'director': director, 'treatment': treatment}})
            scene = {'native_revision_from': previous, 'native_revision_reason': '实际光标遮字，修原生自有输入'}
            current = copy.deepcopy(old['segments'][0]); current['strategy_revision'] = 2
            current['bindings']['native']['brief_sha256'] = 'b' * 64
            job = SimpleNamespace(stages={'visual_direction': {'artifacts': [previous], 'lineage': []}})
            with mock.patch.object(state, 'load_job', return_value=job):
                vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), current, scene)
                vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), old['segments'][0], scene)
                for mutation in ('skip_revision', 'same_input', 'meaning', 'unregistered'):
                    changed = copy.deepcopy(current)
                    if mutation == 'skip_revision': changed['strategy_revision'] = 3
                    elif mutation == 'same_input': changed['bindings']['native']['brief_sha256'] = 'a' * 64
                    elif mutation == 'meaning': changed['visual_intent'] = {'statement': '另一件事'}
                    else: job.stages['visual_direction']['artifacts'] = []
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), changed, scene)

    def test_technical_revision_requires_scoped_verified_implementation_change(self):
        base = {'segments': [{'segment_id': 'seg-1', 'strategy_revision': 1, 'bindings': {
            'action': {'dependency_id': 'barty-motion-graphics', 'invocation_record': {}}}}]}
        actual = copy.deepcopy(base); actual['segments'][0]['strategy_revision'] = 2
        with self.assertRaisesRegex(ValueError, 'verified implementation'):
            vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)
        actual['segments'][0]['bindings']['action']['invocation_record']['canvas_alignment'] = {'mode': 'identity'}
        normalized = vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)
        self.assertEqual(normalized['segments'][0]['strategy_revision'], 1)
        self.assertEqual(actual['segments'][0]['strategy_revision'], 2)
        actual['segments'][0]['strategy_revision'] = 0
        with self.assertRaisesRegex(ValueError, 'must increase'):
            vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)

    def test_lemo_number_size_change_does_not_allow_other_source_edits(self):
        old = "before; paint(String(step),px,py+10,30,color,'center','Font');after"
        new = "before; paint(String(step),px,py+12,36,color,'center','Font');after"
        self.assertEqual(vc._lemo_number_change(old, new), (30, 36))
        for changed in (new.replace('after', 'different'), new.replace('color', 'other'),
                        new.replace('py+12', 'py+90'), new.replace(',36,', ',20,')):
            with self.assertRaises(ValueError):
                vc._lemo_number_change(old, changed)
        old = "label('周报',377,964,64);window.TEXTS=t=>[{id:'report',text:'周报',x0:377,y0:900,x1:520,y1:975}];drawHand(t);"
        new = old.replace("'周报',377,", "'周报',397,").replace('x0:377','x0:397').replace('x1:520','x1:540')
        self.assertEqual(vc._lemo_text_position_change(old,new),'周报')
        for changed in (new.replace('drawHand(t)','drawHand(t+1)'),new.replace(',64)',',62)'),
                        new.replace("text:'周报'","text:'月报'"),new.replace('x1:540','x1:539'),
                        new.replace("id:'report'","id:'other'")):
            with self.subTest(source=changed),self.assertRaises(ValueError):
                vc._lemo_text_position_change(old,changed)

    def test_lemo_second_typography_revision_preserves_only_comparison_evidence(self):
        import hashlib,json,importlib.util
        from types import SimpleNamespace
        root=self.root
        def write(name,value):
            path=root/name
            if isinstance(value,str):path.write_text(value)
            else:artifacts.write_json_artifact(path,value)
            return vc._record(root,path)
        source="label('周报',100,250,64);window.TEXTS=t=>[{id:'report',text:'周报',x0:100,y0:200,x1:200,y1:260}];"
        revised=source.replace("'周报',100,","'周报',120,").replace('x0:100','x0:120').replace('x1:200','x1:220')
        handoff={k:'fixture' for k in ('transcript','semantic_goal','required_change','subject','visual_pattern')}
        handoff['design_plan']={'typography':'unchanged'}
        arroll=write('aroll', 'fixture arroll')
        briefs=[]
        for name,text in [('old',source),('new',revised)]:
            scene=write(name+'.mjs',text);work=write(name+'-workflow.json',{'design_plan':handoff['design_plan']})
            files=[{'media_ref':key,'scene_path':local,'job_path':ref['path'],'sha256':ref['sha256']}
                   for key,local,ref in [('scene','scene.mjs',scene),('workflow','workflow.json',work)]]
            data={'files':files,'workflow_media_ref':'workflow','creative_handoff':handoff,
                  'composition':{'frames':24},'source_binding':{'aroll_sha256':arroll['sha256']}}
            briefs.append((data,write(name+'-brief.json',data)))
        old,new=briefs[0][0],briefs[1][0]
        script=_env.PROJECT/'scripts/upstream_scene_adapter.py';source_sha=artifacts.sha256_file(script)
        binding={'dependency_id':'lemo-opuscar','brief_sha256':briefs[0][1]['sha256'],'verification_id':'old',
                 'source_sha256':source_sha,'renderer_version':'fixture',
                 'invocation_record':{'argv':['python',str(script)],'status':'planned','exit_code':None,
                    'template_request':{},'style_slug':'fixture','production_evidence':{'fixture':True},'creative_handoff':handoff}}
        after={**binding,'brief_sha256':briefs[1][1]['sha256']}
        after['verification_id']=hashlib.sha256((source_sha+'fixture'+after['brief_sha256']).encode()).hexdigest()
        segment=fixture_api.draft_segment(('code_generated',),end=1)
        cid='component-1';segment['bindings']={cid:binding};director={'segments':[segment]}
        current=copy.deepcopy(director);current['segments'][0]['bindings'][cid]=after
        files={'sample':write('sample', 'fixture not a media render')}
        manifest=write('manifest.json',{'brief_sha256':after['brief_sha256'],'media':[
            {'media_ref':f['media_ref'],'sha256':f['sha256'],'byte_length':(root/f['job_path']).stat().st_size} for f in new['files']]})
        result={'status':'rendered','frames':24,'dependency_id':'lemo-opuscar','upstream_commit':'fixture',
                'native_entry_sha256':artifacts.sha256_file(_env.PROJECT/'vendor/lemo-opuscar/core/render/video.mjs'),
                'production_evidence':{'fixture':True}}
        call=write('call.json',{'argv':['python',str(script),'--brief',str(root/briefs[1][1]['path']),
            '--media-manifest',str(root/manifest['path']),'--output',str(root/files['sample']['path'])],
            'exit_code':0,'stdout':json.dumps(result)})
        evidence={'sample':files['sample'],'call':call,'manifest':manifest}
        prior=copy.deepcopy(evidence)
        def reading(name,text):
            at=text.index('周报');ref=vc._record(root,root/(name+'.mjs'))
            return {'segment_id':'seg-001','component_id':cid,'targets':[{'target_id':'report','role':'body',
                'span':[0,2],'region':{'x':90,'y':190,'width':180,'height':100},'windows':[{'start':.1,'end':.9}],
                'content_ref':{'path':ref['path'],'sha256':ref['sha256'],'pointer':f'text:{at}:{at+2}','value':'周报'}}]}
        frozen={'scenes':[{'segment_id':'seg-001','component_id':cid,'brief_path':briefs[0][1]['path'],
                          'native_typography_revision':prior}],'motion_readability':[reading('old',source)]}
        actual=copy.deepcopy(frozen);actual['scenes'][0].update(brief_path=briefs[1][1]['path'],native_typography_revision=evidence)
        actual['motion_readability']=[reading('new',revised)]
        adapter=SimpleNamespace(validate_brief=json.loads,SOURCES={'lemo-opuscar':('fixture','core/render/video.mjs')},
                                workflow_reference=lambda _: {'fixture':True})
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _:None))
        probe=json.dumps({'streams':[{'codec_type':'video','avg_frame_rate':'24/1','width':1080,'height':1920,'nb_read_frames':'24'}]})
        with mock.patch.object(importlib.util,'spec_from_file_location',return_value=spec), \
             mock.patch.object(importlib.util,'module_from_spec',return_value=adapter), \
             mock.patch.object(vc.subprocess,'check_output',return_value=probe):
            normalized,compared=vc._normalize_lemo_typography(root,director,frozen,current,actual)
            self.assertEqual(normalized,director)
            self.assertEqual(compared,{**frozen,'motion_readability':actual['motion_readability']})
            self.assertEqual(actual['scenes'][0]['native_typography_revision'],evidence)
            (root/call['path']).write_text('tampered E2')
            with self.assertRaisesRegex(ValueError,'confirmed visual evidence changed'):
                vc._normalize_lemo_typography(root,director,frozen,current,actual)

    def test_lemo_revision_still_requires_unchanged_actual_sample_and_call(self):
        sample = self.root / 'lemo-sample.mp4'
        sample.write_bytes((_env.PROJECT / 'assets/lemo-native-smoke/sample.mp4').read_bytes())
        evidence_file = self.root / 'lemo-evidence.json'
        artifacts.write_json_artifact(evidence_file, {})
        evidence = {key: vc._record(self.root, evidence_file) for key in ('call', 'manifest')}
        evidence.update(sample=vc._record(self.root, sample))
        before = {'dependency_id': 'lemo-opuscar', 'brief_sha256': 'a' * 64}
        after = {**before, 'brief_sha256': 'b' * 64}
        frozen = {'segments': [{'segment_id': 'seg-001', 'bindings': {'scene': before}}]}
        director = {'segments': [{'segment_id': 'seg-001', 'bindings': {'scene': after}}]}
        original = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'scene',
                               'brief_path': 'lemo-evidence.json'}]}
        current = copy.deepcopy(original)
        current['scenes'][0]['native_typography_revision'] = evidence
        for path in (sample, evidence_file):
            saved = path.read_bytes()
            path.write_bytes(saved + b'changed')
            with self.subTest(evidence=path.name), self.assertRaisesRegex(
                    vc.VisualConfirmationError, 'confirmed visual evidence changed: ' + path.name):
                vc._normalize_lemo_typography(self.root, frozen, original, director, current)
            path.write_bytes(saved)

    def test_native_source_facts_do_not_require_host_pixel_approval(self):
        before = {'authorization': {'paid_generation': False},
                  'transcript': '实际原话', 'source_facts': {'count': 2},
                  'template_request': {'numeric_values': [2], 'numeric_scale': 'linear'}}
        with mock.patch.object(vc.subprocess, 'check_output', side_effect=AssertionError('no host pixel QA')):
            vc._validate_native_parent_fields(before, copy.deepcopy(before))
            for field in ('transcript', 'source_facts', 'template_request'):
                changed = copy.deepcopy(before)
                if field == 'transcript': changed[field] = '另一原话'
                elif field == 'source_facts': changed[field]['count'] = 3
                else: changed[field]['numeric_values'] = [3]
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'authorized native input'):
                    vc._validate_native_parent_fields(before, changed)

    def test_transparency_does_not_change_the_actual_component_use(self):
        brief = {'template_id': 'motion-broll', 'alpha': True}
        component = {'component_id': 'scene', 'layer_role': 'annotation'}
        segment = {'visual_strategy': {'composition': {'family': 'broll_with_avatar'}, 'components': [component]}}
        candidate = vc.native_candidate_id('barty-motion-graphics', brief, segment, 'scene')
        self.assertEqual(candidate, 'barty-motion-graphics:barty-motion-graphics/motion-broll')
        segment['visual_strategy']['composition']['family'] = 'aroll_with_overlay'
        self.assertEqual(vc.native_candidate_id('barty-motion-graphics', brief, segment, 'scene'),
                         'overlay:barty-motion-graphics/motion-broll')
        with self.assertRaises(vc.VisualConfirmationError):
            vc.native_candidate_id('barty-motion-graphics', brief, segment, 'wrong')

    def setUp(self):
        import tempfile
        from test_motion_native_skill_adapter import brief
        import motion_native_skill_adapter as native
        self.native = native
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        segment = fixture_api.draft_segment(('code_generated',), end=2)
        cid = 'component-1'
        self.director = {'schema_version': 3, 'segments': [segment]}
        request = brief()
        request['task_source']['component_brief'] = segment['visual_strategy']['components'][0]['brief']
        self.treatment = {'numbering_scope_id': 'native-test', 'scenes': [],
            'semantic_lists': {'overlay': [], 'broll': [{'row_id': 'semantic-1', 'quote': request['transcript'],
                'semantic': request['semantic_goal'], 'visual_task': '可替换的参考构图',
                'components': [{'segment_id': 'seg-001', 'component_id': cid}]}]},
            'skill_selection': {'beats': [{'segment_id': 'seg-001', 'component_id': cid, 'semantic_row_id': 'semantic-1',
                'required_change': request['task_source']['required_change'], 'transcript': request['transcript'],
                'component_brief': segment['visual_strategy']['components'][0]['brief']}], 'overlay_beats': []},
            'semantic_assessments': [{'segment_id': 'seg-001', 'component_id': cid,
                'candidate_id': 'barty-motion-graphics:barty-motion-graphics/motion-broll', 'verdict': 'pass',
                'reason': '批准语义', 'transcript_refs': [], 'content_refs': []}],
            'motion_readability': [{'segment_id': 'seg-001', 'component_id': cid, 'targets': [], 'pending_native': True}]}
        path = self.root / 'native-inputs/approved.json'; artifacts.write_json_artifact(path, request)
        digest = native.sha(path)
        binding = {'dependency_id': 'barty-motion-graphics', 'template_id': 'barty-motion-graphics/motion-broll',
                   'source_sha256': 'a' * 64, 'brief_sha256': digest,
                   'verification_id': __import__('hashlib').sha256(('a' * 64 + digest).encode()).hexdigest()}
        segment['bindings'] = {cid: binding}
        self.treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(binding)
        self.treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': cid, 'brief_path': 'native-inputs/approved.json'}]
        dpath = self.root / 'approved-director.json'; tpath = self.root / 'approved-treatment.json'
        artifacts.write_json_artifact(dpath, self.director); artifacts.write_json_artifact(tpath, self.treatment)
        self.proposal = {'inputs': {'director': vc._record(self.root, dpath), 'treatment': vc._record(self.root, tpath)}}
        source = self.root / 'native-projects/native-test/index.html'
        source.parent.mkdir(parents=True); source.write_text('<html>输入</html>')
        call = self.root / 'native-inputs/call.json'
        artifacts.write_json_artifact(call, {'project_files': [native.descriptor(self.root, source)]})
        self.result = {'render_call': native.descriptor(self.root, call)}
        ref = {'path': source.relative_to(self.root).as_posix(), 'sha256': native.sha(source),
               'pointer': 'text:6:8', 'value': '输入'}
        self.target = {'target_id': 'native-input', 'content_ref': ref, 'span': [0, 2], 'role': 'title',
                       'region': {'x': 100, 'y': 200, 'width': 600, 'height': 100},
                       'windows': [{'start': .5, 'end': 1.5}]}

    def realized(self):
        director, treatment = copy.deepcopy(self.director), copy.deepcopy(self.treatment)
        director['segments'][0]['visible_text'] = ['输入']
        treatment['motion_readability'][0] = {'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [copy.deepcopy(self.target)]}
        return director, treatment

    def validate(self, director, treatment):
        with mock.patch.object(vc, '_native_result_adapter', return_value=self.native), \
             mock.patch.object(self.native, 'inspect_result', return_value=self.result):
            normalized, compared = vc._validate_motion_realization(
                self.root, self.director, self.treatment, director, treatment)
            vc._validate_draft_against_source(self.root, self.proposal, normalized, compared)

    def test_unchanged_native_without_parent_text_retains_its_binding_checks(self):
        treatment = copy.deepcopy(self.treatment)
        treatment['motion_readability'] = []
        with mock.patch.object(vc, '_native_result_adapter', return_value=self.native):
            normalized = vc._validate_motion_realization(
                self.root, self.director, treatment, self.director, treatment)
            self.assertEqual(normalized, (self.director, treatment))
            changed = copy.deepcopy(self.director)
            changed['segments'][0]['bindings']['component-1']['verification_id'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'approved template or source'):
                vc._validate_motion_realization(
                    self.root, self.director, treatment, changed, treatment)

    def test_native_revision_without_optional_assessments_keeps_identity_checks(self):
        treatment = copy.deepcopy(self.treatment)
        treatment.pop('semantic_assessments')
        treatment['motion_readability'] = []
        assessed = {**treatment, 'semantic_assessments': self.treatment['semantic_assessments']}
        with mock.patch.object(vc, '_native_result_adapter', return_value=self.native):
            self.assertEqual(vc._validate_motion_realization(
                self.root, self.director, treatment, self.director, treatment),
                (self.director, treatment))
            for before, after in ((assessed, treatment), (treatment, assessed)):
                with self.assertRaisesRegex(ValueError, 'semantic assessment identity'):
                    vc._validate_motion_realization(
                        self.root, self.director, before, self.director, after)
            altered = copy.deepcopy(assessed)
            altered['semantic_assessments'][0]['candidate_id'] = 'another-template'
            with self.assertRaisesRegex(ValueError, 'semantic assessment identity'):
                vc._validate_motion_realization(
                    self.root, self.director, assessed, self.director, altered)

    def test_realization_preserves_native_permissions_audio_words_and_original_materials(self):
        original_path = self.root / 'native-inputs/approved.json'
        original = artifacts.read_json_artifact(original_path)
        from PIL import Image
        material = self.root / 'original.png'; Image.new('RGB', (8, 8), 'blue').save(material)
        source = {'job_path': material.name, 'sha256': artifacts.sha256_file(material),
                  'byte_count': material.stat().st_size}
        original['materials'] = [source]
        original['assets'] = [{**source, 'media_ref': 'shot', 'scene_path': 'assets/shots/shot.png'}]
        artifacts.write_json_artifact(original_path, original)
        binding = self.director['segments'][0]['bindings']['component-1']
        binding['brief_sha256'] = artifacts.sha256_file(original_path)
        self.treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(binding)
        for name, value in (('director', self.director), ('treatment', self.treatment)):
            path = self.root / ('approved-' + name + '.json')
            artifacts.write_json_artifact(path, value)
            self.proposal['inputs'][name] = vc._record(self.root, path)

        def realized(request):
            path = self.root / 'native-inputs/revised.json'
            artifacts.write_json_artifact(path, request)
            director, treatment = copy.deepcopy(self.director), copy.deepcopy(self.treatment)
            bound = director['segments'][0]['bindings']['component-1']
            bound['brief_sha256'] = artifacts.sha256_file(path)
            treatment['scenes'][0]['brief_path'] = str(path.relative_to(self.root))
            treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(bound)
            return director, treatment

        for field in ('authorization', 'speech', 'word_anchors', 'source_binding',
                      'task_source', 'materials', 'template_request', 'assets', 'asset_slot'):
            request = copy.deepcopy(original)
            if field == 'authorization': request[field]['paid_generation'] = True
            elif field == 'speech': request[field]['job_path'] = 'other-audio.wav'
            elif field == 'word_anchors': request[field][0]['text'] = '未确认文字'
            elif field == 'source_binding': request[field]['aroll_sha256'] = 'f' * 64
            elif field == 'task_source': request[field]['quote'] = '未确认原话'
            elif field == 'materials': request[field] = []
            elif field == 'assets':
                request[field][0].update(job_path='another-screenshot.png', sha256='e' * 64)
            elif field == 'asset_slot':
                request['assets'].append({**request['assets'][0], 'media_ref': 'unused', 'scene_path': 'unused.png'})
                request['assets'][0].update(job_path='another-screenshot.png', sha256='e' * 64)
            else: request[field]['numeric_values'] = [999]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'authorized native input'):
                vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
        request = copy.deepcopy(original)
        request.update(project_directory='native-projects/revised', result_record_path='native-inputs/result-v2.json',
                       native_options=['complementary-native-option'])
        vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
        generated = self.root / 'generated.png'; generated.write_bytes(b'approved generated input')
        output = vc._record(self.root, generated)
        request['materials'].append({'job_path': output['path'], 'sha256': output['sha256'],
                                     'byte_count': output['bytes']})
        with self.assertRaisesRegex(ValueError, 'authorized native input: materials'):
            vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
        self.proposal.update(job_id=original['job_id'], generation_steps=[{
            'id': 'approved-image', 'segment_id': 'seg-001', 'component_id': 'component-1'}])
        with mock.patch.object(vc, '_completed_generations', return_value=[{
                'step_id': 'approved-image', 'media': [output]}]) as completed:
            vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
            self.assertEqual(completed.call_count, 1)
            request['assets'][0].update(job_path=output['path'], sha256=output['sha256'])
            vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
            self.proposal['generation_steps'][0]['component_id'] = 'another-component'
            with self.assertRaisesRegex(ValueError, 'authorized native input: materials'):
                vc._validate_draft_against_source(self.root, self.proposal, *realized(request))
        self.proposal['generation_steps'] = []
        self.director['segments'][0]['bindings']['component-1']['dependency_id'] = 'paper-collage-hyperframes'
        path = self.root / 'approved-director.json'; artifacts.write_json_artifact(path, self.director)
        self.proposal['inputs']['director'] = vc._record(self.root, path)
        cropped = self.root / 'cropped.png'
        with Image.open(material) as image: image.crop((1, 1, 7, 7)).save(cropped)
        request = copy.deepcopy(original)
        request['assets'][0].update(job_path=cropped.name, sha256=artifacts.sha256_file(cropped))
        entry = self.root / 'new-scene.html'; entry.write_text('<img src="assets/shots/shot.png">')
        request['entry'] = {'job_path': entry.name, 'sha256': artifacts.sha256_file(entry)}
        provenance = self.root / 'crop-provenance.json'
        artifacts.write_json_artifact(provenance, {'source_images': {'original': {
            'path': source['job_path'], 'sha256': source['sha256']}}, 'crops': [{
            'source': source['job_path'], 'source_sha256': source['sha256'], 'crop': [1, 1, 7, 7],
            'output': cropped.name, 'output_sha256': artifacts.sha256_file(cropped)}]})
        director, treatment = realized(request)
        ref = vc._record(self.root, provenance)
        treatment['scenes'][0]['asset_provenance'] = {'job_path': ref['path'], 'sha256': ref['sha256'], 'byte_count': ref['bytes']}
        vc._validate_draft_against_source(self.root, self.proposal, director, treatment)
        cropped.write_bytes(b'unrelated screenshot')
        with self.assertRaisesRegex(ValueError, 'asset changed|output changed'):
            vc._validate_draft_against_source(self.root, self.proposal, director, treatment)

    def test_foreign_damaged_brief_does_not_block_approved_own_material(self):
        from PIL import Image
        image = self.root / 'approved-own.png'
        Image.new('RGB', (8, 8), 'blue').save(image)
        request_path = self.root / 'native-inputs/approved.json'
        request = artifacts.read_json_artifact(request_path)
        request['materials'] = [{'job_path': image.name, 'sha256': artifacts.sha256_file(image),
                                 'byte_count': image.stat().st_size}]
        artifacts.write_json_artifact(request_path, request)
        own = self.director['segments'][0]
        own['bindings']['component-1']['brief_sha256'] = artifacts.sha256_file(request_path)
        foreign = copy.deepcopy(own)
        foreign.update(segment_id='seg-002', start=2, end=4)
        foreign_path = self.root / 'native-inputs/foreign.json'
        foreign_request = copy.deepcopy(request)
        foreign_request['source_binding'].update(segment_id='seg-002', start=2, end=4)
        artifacts.write_json_artifact(foreign_path, foreign_request)
        foreign['bindings']['component-1']['brief_sha256'] = artifacts.sha256_file(foreign_path)
        self.director['segments'].append(foreign)
        self.treatment['scenes'].append({'segment_id': 'seg-002', 'component_id': 'component-1',
                                        'brief_path': 'native-inputs/foreign.json'})
        for name, value in (('director', self.director), ('treatment', self.treatment)):
            path = self.root / ('approved-' + name + '.json')
            artifacts.write_json_artifact(path, value)
            self.proposal['inputs'][name] = vc._record(self.root, path)
        for damaged in (None, b'{broken', b'{"foreign":"changed"}'):
            with self.subTest(damaged=damaged):
                if damaged is None:
                    foreign_path.unlink()
                else:
                    foreign_path.write_bytes(damaged)
                vc._validate_authorized_native_inputs(self.root, self.proposal, self.director,
                    self.treatment, self.director, self.treatment, targets={('seg-001', 'component-1')})
                with self.assertRaises((ValueError, OSError)):
                    vc._validate_authorized_native_inputs(self.root, self.proposal, self.director,
                        self.treatment, self.director, self.treatment, targets={('seg-002', 'component-1')})

    def test_local_native_options_can_change_without_changing_parent_inputs(self):
        before = artifacts.read_json_artifact(self.root / 'native-inputs/approved.json')
        before.update(dependency_id='bang-motion', template_id='opener', canvas_transport='quarter_turn_cw')
        after = {**before, 'native_options': ['counter'], 'task_source': {
            **before['task_source'], 'required_change': '原生选择新的布局与动作',
            'component_brief': '原生工作流的可替换表现参考'}}
        first = self.root / 'native-inputs/bang-before.json'
        second = self.root / 'native-inputs/bang-after.json'
        artifacts.write_json_artifact(first, before); artifacts.write_json_artifact(second, after)
        director, treatment = copy.deepcopy(self.director), copy.deepcopy(self.treatment)
        treatment.pop('semantic_assessments'); treatment['motion_readability'] = []
        bound = director['segments'][0]['bindings']['component-1']
        bound.update(dependency_id='bang-motion', template_id='bang-motion/opener', brief_sha256=self.native.sha(first))
        bound['verification_id'] = __import__('hashlib').sha256((bound['source_sha256'] + bound['brief_sha256']).encode()).hexdigest()
        treatment['scenes'][0]['brief_path'] = str(first.relative_to(self.root))
        treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(bound)
        actual, revised = copy.deepcopy(director), copy.deepcopy(treatment)
        changed = actual['segments'][0]['bindings']['component-1']
        changed['brief_sha256'] = self.native.sha(second)
        changed['verification_id'] = __import__('hashlib').sha256((changed['source_sha256'] + changed['brief_sha256']).encode()).hexdigest()
        revised['scenes'][0]['brief_path'] = str(second.relative_to(self.root))
        revised['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(changed)
        with mock.patch.object(vc, '_native_result_adapter', return_value=self.native):
            self.assertEqual(vc._validate_motion_realization(self.root, director, treatment, actual, revised),
                             (director, treatment))

    def test_actual_native_text_can_be_added_but_semantics_time_and_numbering_cannot_change(self):
        director, treatment = self.realized(); self.validate(director, treatment)
        for change in ('semantic', 'time', 'template', 'numbering'):
            changed, altered = copy.deepcopy(director), copy.deepcopy(treatment)
            if change == 'semantic': altered['semantic_lists']['broll'][0]['semantic'] = '另一种意思'
            if change == 'time': changed['segments'][0]['end'] = 3
            if change == 'template': changed['segments'][0]['bindings']['component-1']['template_id'] = 'another-template'
            if change == 'numbering': altered['numbering_scope_id'] = 'another-scope'
            with self.subTest(change=change), self.assertRaises(ValueError): self.validate(changed, altered)

    def test_execution_revision_preserves_task_and_needs_current_binding_snapshot(self):
        director, treatment = self.realized()
        old = self.native.validate_brief((self.root / 'native-inputs/approved.json').read_bytes())
        revision = {**old, 'project_directory': 'native-projects/revision-2', 'result_record_path': 'native-inputs/revision-2.json'}
        path = self.root / 'native-inputs/revision-2-brief.json'; artifacts.write_json_artifact(path, revision)
        binding = director['segments'][0]['bindings']['component-1']; binding['brief_sha256'] = self.native.sha(path)
        binding['verification_id'] = __import__('hashlib').sha256((binding['source_sha256'] + binding['brief_sha256']).encode()).hexdigest()
        treatment['scenes'][0]['brief_path'] = 'native-inputs/revision-2-brief.json'
        with self.assertRaisesRegex(ValueError, 'failure reason'): self.validate(director, treatment)
        treatment['scenes'][0]['native_revision_reason'] = '首次实看发现文字遮挡，仅修订该项原生排版'
        with self.assertRaisesRegex(ValueError, 'snapshot'): self.validate(director, treatment)
        treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(binding)
        self.validate(director, treatment)
        revision['authorization'] = {'paid_generation': True}; artifacts.write_json_artifact(path, revision)
        binding['brief_sha256'] = self.native.sha(path)
        with self.assertRaisesRegex(ValueError, 'approved semantic task'): self.validate(director, treatment)

    def test_readability_rejects_foreign_source_and_preserves_user_confirmed_text(self):
        director, treatment = self.realized()
        treatment['motion_readability'][0]['targets'][0]['content_ref']['path'] = 'foreign.html'
        with self.assertRaisesRegex(ValueError, 'actual rendered project'): self.validate(director, treatment)
        director, treatment = self.realized()
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'segment_id': 'seg-002', 'component_id': 'component-1',
                         'visible_text': ['其他镜头指定']}]})
        self.validate(director, treatment)
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'segment_id': 'seg-001', 'component_id': 'component-1',
                         'visible_text': ['用户指定']}]})
        with self.assertRaisesRegex(ValueError, 'retain confirmed text'): self.validate(director, treatment)
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'component_id': 'component-1', 'visible_text': ['用户指定']}]})
        with self.assertRaisesRegex(ValueError, 'retain confirmed text'): self.validate(director, treatment)

    def test_sequential_native_revisions_preserve_earlier_completed_references(self):
        second=copy.deepcopy(self.director['segments'][0]);second['segment_id']='seg-002'
        second['start']=2;second['end']=4;self.director['segments'].append(second)
        request=self.native.validate_brief((self.root/'native-inputs/approved.json').read_bytes())
        request['source_binding'].update(segment_id='seg-002',start=2,end=4)
        request['task_source']['semantic_row_id']='semantic-2'
        request.update(project_directory='native-projects/second',result_record_path='native-inputs/second.json')
        path=self.root/'native-inputs/second-brief.json';artifacts.write_json_artifact(path,request)
        binding=second['bindings']['component-1'];binding['brief_sha256']=self.native.sha(path)
        binding['verification_id']=__import__('hashlib').sha256((binding['source_sha256']+binding['brief_sha256']).encode()).hexdigest()
        row=copy.deepcopy(self.treatment['semantic_lists']['broll'][0]);row['row_id']='semantic-2'
        row['components'][0]['segment_id']='seg-002';self.treatment['semantic_lists']['broll'].append(row)
        beat=copy.deepcopy(self.treatment['skill_selection']['beats'][0]);beat.update(segment_id='seg-002',semantic_row_id='semantic-2',binding_snapshot=copy.deepcopy(binding))
        self.treatment['skill_selection']['beats'].append(beat)
        for field in ('scenes','semantic_assessments','motion_readability'):
            item=copy.deepcopy(self.treatment[field][0]);item['segment_id']='seg-002'
            if field=='scenes':item['brief_path']='native-inputs/second-brief.json'
            self.treatment[field].append(item)
        for name,value in [('director',self.director),('treatment',self.treatment)]:
            path=self.root/('approved-'+name+'.json');artifacts.write_json_artifact(path,value)
            self.proposal['inputs'][name]=vc._record(self.root,path)
        director,treatment=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
        first_revision=None
        for index,scene in enumerate(treatment['scenes']):
            revision=self.native.validate_brief((self.root/scene['brief_path']).read_bytes())
            revision.update(project_directory=f'native-projects/revision-{index}',result_record_path=f'native-inputs/revision-{index}.json')
            path=self.root/f'native-inputs/revision-{index}-brief.json';artifacts.write_json_artifact(path,revision)
            scene.update(brief_path=path.relative_to(self.root).as_posix(),native_revision_reason='当前画面需修订')
            binding=director['segments'][index]['bindings']['component-1'];binding['brief_sha256']=self.native.sha(path)
            binding['verification_id']=__import__('hashlib').sha256((binding['source_sha256']+binding['brief_sha256']).encode()).hexdigest()
            treatment['skill_selection']['beats'][index]['binding_snapshot']=copy.deepcopy(binding)
            self.validate(director,treatment)
            if index==0:first_revision=copy.deepcopy(director['segments'][0])
            else:self.assertEqual(director['segments'][0],first_revision)

    def test_pending_native_text_is_only_a_planning_state(self):
        from edit.hd.tools import motion_readability
        segment = self.director['segments'][0]
        segments = [{**segment, 'shot_recipe': {'components': segment['visual_strategy']['components']}}]
        records = self.treatment['motion_readability']
        self.assertEqual(motion_readability.validate_targets(segments, records, [],
            pending_components={('seg-001', 'component-1')})[0]['status'], 'pending_native')
        with self.assertRaisesRegex(ValueError, 'only allowed'):
            motion_readability.validate_targets(segments, records, [])

    def test_generated_text_completion_preserves_approval_and_requires_actual_sources(self):
        frozen = copy.deepcopy(self.director)
        segment = frozen['segments'][0]
        segment['visible_text'] = ['输入']
        segment['bindings'] = {'component-1': {'dependency_id': 'paper-collage-ad', 'template_id': 'paper'}}
        old = copy.deepcopy(self.treatment)
        old['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                     'pending_generation': True}]
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {'prompt': 'approved paper'}, 'depends_on': []}
        old['generation_plan'] = {'steps': [step], 'cost_note': 'one approved image'}
        for name, data in [('director', frozen), ('treatment', old)]:
            path = self.root / ('approved-' + name + '.json'); artifacts.write_json_artifact(path, data)
            self.proposal['inputs'][name] = vc._record(self.root, path)
        self.proposal['generation_steps'] = [step]
        director, treatment = copy.deepcopy(frozen), copy.deepcopy(old)
        payload = {'source_binding': {'segment_id': 'seg-001', 'start': segment['start'], 'end': segment['end']},
                   'entry': {'job_path': self.target['content_ref']['path'], 'sha256': self.target['content_ref']['sha256']}}
        path = self.root / 'actual-brief.json'; artifacts.write_json_artifact(path, payload)
        director['segments'][0]['bindings']['component-1']['brief_sha256'] = artifacts.sha256_file(path)
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'brief_path': path.name}]
        treatment['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                            'targets': [copy.deepcopy(self.target)]}]
        output = self.root / 'generated-output.bin'; output.write_bytes(b'fixture completed output')
        evidence = [{'step_id': 'image', 'media': [vc._record(self.root, output)]}]
        def validate(director, treatment, evidence=evidence, eligible={('seg-001', 'component-1')}):
            with mock.patch.object(vc, 'planned_generation_targets', return_value=eligible):
                normalized = copy.deepcopy(director)
                compared = vc._validate_generated_readability(self.root, self.proposal, frozen, old,
                    normalized, treatment, evidence, production_director=director, production_treatment=treatment)
                vc._validate_draft_against_source(self.root, self.proposal, normalized, compared)
        validate(director, treatment)
        for change in ('no_completion', 'not_eligible', 'wording', 'step_count', 'channel', 'cost',
                       'time', 'template', 'semantic', 'foreign_source', 'pending'):
            changed, altered = copy.deepcopy(director), copy.deepcopy(treatment)
            if change == 'no_completion':
                with self.assertRaisesRegex(ValueError, 'completed generation'): validate(changed, altered, [])
                continue
            if change == 'not_eligible':
                with self.assertRaisesRegex(ValueError, 'uncreated approved'): validate(changed, altered, eligible=set())
                continue
            if change == 'wording': changed['segments'][0]['visible_text'] = ['新文案']
            elif change == 'step_count': altered['generation_plan']['steps'].append({**step, 'id': 'extra'})
            elif change == 'channel': altered['generation_plan']['steps'][0]['arguments']['model'] = 'unapproved'
            elif change == 'cost': altered['generation_plan']['cost_note'] = 'two paid images'
            elif change == 'time': changed['segments'][0]['end'] += 1
            elif change == 'template': changed['segments'][0]['bindings']['component-1']['template_id'] = 'other'
            elif change == 'semantic': altered['semantic_lists']['broll'][0]['semantic'] = 'new fact'
            elif change == 'pending': altered['motion_readability'][0]['pending_generation'] = True
            else: altered['motion_readability'][0]['targets'][0]['content_ref']['path'] = 'foreign.html'
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)):
                validate(changed, altered)

    def test_approved_visible_text_cannot_be_removed_even_with_an_existing_target(self):
        self.director['segments'][0]['visible_text']=['输入']
        self.treatment['motion_readability'][0]={'segment_id':'seg-001','component_id':'component-1','targets':[self.target]}
        for name,value in [('director',self.director),('treatment',self.treatment)]:
            path=self.root/('approved-'+name+'.json');artifacts.write_json_artifact(path,value)
            self.proposal['inputs'][name]=vc._record(self.root,path)
        director,treatment=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
        director['segments'][0]['visible_text']=[]
        treatment['motion_readability'][0]={'segment_id':'seg-001','component_id':'component-1','targets':[],
                                          'no_critical_text_reason':'不能以无字理由删除已批准文字'}
        with self.assertRaisesRegex(ValueError,'retain confirmed text'):self.validate(director,treatment)

    def test_generated_image_text_requires_scoped_real_image_and_human_review(self):
        from PIL import Image
        from edit.hd.tools import motion_capabilities
        image = self.root / 'actual-image.png'
        Image.new('RGB', (10, 10), 'white').save(image)
        image_ref = vc._record(self.root, image)
        brief = '报销单缺附件时停下，人的手补入附件。'
        component = {'component_id': 'component-1', 'kind': 'code_generated', 'brief': brief}
        original = {'segment_id': 'seg-001', 'start': 0, 'end': 2, 'visible_text': [],
                    'visual_strategy': {'components': [component]},
                    'bindings': {'component-1': {'brief_sha256': 'a' * 64}}}
        frozen = {'segments': [original]}
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {}, 'depends_on': []}
        old = {'motion_readability': [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                      'pending_generation': True, 'targets': []}],
               'generation_plan': {'steps': [step]}}
        target = {'target_id': 'actual-image-title', 'content_ref': {
            'path': image_ref['path'], 'sha256': image_ref['sha256'], 'pointer': 'image-text', 'value': '费用报销单'},
            'span': [0, 5], 'role': 'body', 'region': {'x': 10, 'y': 10, 'width': 300, 'height': 80},
            'windows': [{'start': 0, 'end': 1}]}
        review = {'segment_id': 'seg-001', 'component_id': 'component-1', 'text': '费用报销单',
                  'source_quote': brief, 'source_image': image_ref, 'verdict': 'pass',
                  'reason': '宿主审阅：费用报销单是原确认报销单对象的标题。'}
        director = copy.deepcopy(frozen); director['segments'][0]['visible_text'] = ['费用报销单']
        treatment = copy.deepcopy(old); treatment['motion_readability'][0] = {
            'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [target]}
        treatment['reviewed_generated_text'] = [review]
        evidence = [{'step_id': 'image', 'media': [image_ref]}]
        def validate(d, t, *, comparison_director=None, comparison_treatment=None):
            with mock.patch.object(vc, 'planned_generation_targets', return_value={('seg-001', 'component-1')}), \
                 mock.patch.object(motion_capabilities, '_bound_brief', return_value={}) as bound, \
                 mock.patch.object(motion_capabilities, '_brief_relative', return_value='brief.json'):
                result = vc._validate_generated_readability(self.root, {'generation_steps': [step]},
                    frozen, old, comparison_director or d, comparison_treatment or t, evidence,
                    production_director=d, production_treatment=t)
                bound.assert_called_once_with(self.root, t, d['segments'][0], 'component-1')
                return result
        validate(copy.deepcopy(director), copy.deepcopy(treatment))
        # Deferred native routes lose their real bindings only in the comparison copy.
        comparison = copy.deepcopy(director)
        comparison['segments'][0]['bindings']['component-1'].pop('brief_sha256')
        validate(copy.deepcopy(director), copy.deepcopy(treatment), comparison_director=comparison)
        for mutation in ('missing_review', 'wrong_quote', 'wrong_image', 'unreviewed_new_fact', 'rejected_review'):
            d, t = copy.deepcopy(director), copy.deepcopy(treatment)
            if mutation == 'missing_review': t['reviewed_generated_text'] = []
            elif mutation == 'wrong_quote': t['reviewed_generated_text'][0]['source_quote'] = '无来源的另一项任务'
            elif mutation == 'wrong_image': t['reviewed_generated_text'][0]['source_image']['sha256'] = 'b' * 64
            elif mutation == 'rejected_review': t['reviewed_generated_text'][0]['verdict'] = 'fail'
            else: d['segments'][0]['visible_text'].append('报销已完成')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): validate(d, t)

    def test_deferred_generation_can_bind_real_parent_static_labels_without_replanning(self):
        from edit.hd.tests.test_segment_render_components import ParentStaticLabelTests
        from edit.hd.tools import motion_capabilities
        segment, label, png = ParentStaticLabelTests().fixture(self.root)
        segment.update(segment_id='seg-001', end=2)
        segment['bindings']['component-1'] = segment['bindings'].pop('visual-1')
        binding = segment['bindings']['component-1']
        manifest_path = self.root / binding['parent_static_labels']['job_path']
        manifest = artifacts.read_json_artifact(manifest_path)
        manifest.update(segment_id='seg-001', component_id='component-1')
        artifacts.write_json_artifact(manifest_path, manifest)
        binding['parent_static_labels'].update(sha256=artifacts.sha256_file(manifest_path),
                                               byte_count=manifest_path.stat().st_size)
        frozen = copy.deepcopy(self.director)
        frozen['segments'][0]['visible_text'] = ['聊天']
        frozen['segments'][0]['visual_strategy']['components'][0]['kind'] = 'ai_generated'
        frozen['segments'][0]['bindings'] = {'component-1': {'provider': 'fixture', 'model': 'fixture', 'endpoint_id': 'fixture'}}
        old = copy.deepcopy(self.treatment)
        old['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'pending_generation': True}]
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {'prompt': 'approved scene with parent labels'}, 'depends_on': []}
        old['generation_plan'] = {'steps': [step], 'cost_note': 'one image'}
        self.proposal['generation_steps'] = [step]
        for name, value in [('director', frozen), ('treatment', old)]:
            path = self.root / ('approved-' + name + '.json'); artifacts.write_json_artifact(path, value)
            self.proposal['inputs'][name] = vc._record(self.root, path)
        director, treatment = copy.deepcopy(frozen), copy.deepcopy(old)
        director['segments'][0]['bindings']['component-1'].update(binding)
        target = {'target_id': 'parent-chat-label', 'content_ref': label['content_ref'], 'span': [0, 2], 'role': 'body',
                  'region': {'x': 120, 'y': 180, 'width': 240, 'height': 96}, 'windows': [{'start': .25, 'end': .75}]}
        treatment['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [target]}]
        evidence = [{'step_id': 'image', 'media': [vc._record(self.root, png)]}]
        with mock.patch.object(vc, 'planned_generation_targets', return_value={('seg-001', 'component-1')}), \
             mock.patch.object(motion_capabilities, '_ai_brief_evidence',
                               return_value=({'observed_scene': 'fixture'}, {'job_path': 'completed.json', 'sha256': 'a' * 64})):
            vc._validate_draft_against_source(self.root, self.proposal, director, treatment)
            # Exercise the final persisted mapping consumer, not just its draft gate.
            director['segments'][0]['bindings']['component-1']['sha256'] = artifacts.sha256_file(png)
            config = self.root / 'manifests/provider-config.json'; artifacts.write_json_artifact(config, {})
            self.proposal.update(job_id='job', kind=vc.SCHEMA, rows=[], provider_config_sha256=artifacts.sha256_file(config))
            proposal_path = self.root / 'proposal.json'; artifacts.write_json_artifact(proposal_path, self.proposal)
            receipt = {'source_schema': vc.SCHEMA, 'job_id': 'job', 'job_dir': str(self.root),
                'stage': 'visual_direction', 'passed': True, 'authorized_by': 'user', 'revision': 1,
                'authorization_scope': 'visual_plan_and_generation', 'note': 'synthetic test',
                'user_confirmation': 'fixture approval', 'artifacts': [vc._record(self.root, proposal_path)],
                'source': vc._record(self.root, proposal_path)}
            receipt_path = self.root / 'receipt.json'; artifacts.write_json_artifact(receipt_path, receipt)
            receipt_ref = vc._record(self.root, receipt_path)
            realized = {}
            for name, value in [('director', director), ('treatment', treatment)]:
                path = self.root / ('realized-' + name + '.json'); artifacts.write_json_artifact(path, value)
                realized[name] = vc._record(self.root, path)
            final = copy.deepcopy(director)
            compiled = {k: v for k, v in director['segments'][0]['bindings']['component-1'].items()
                        if k not in {'execution_mode', 'media_type', 'source_dimensions', 'parent_static_labels'}}
            final['segments'][0]['shot_recipe'] = {'components': [{'component_id': 'component-1', **compiled}]}
            final_path = self.root / 'final.json'
            def consume():
                artifacts.write_json_artifact(final_path, final)
                final_ref = vc._record(self.root, final_path)
                mapping = {'source_approval': receipt_ref, 'proposal': receipt['source'], 'host_qa_note': 'fixture',
                    'artifacts': [final_ref], 'final_v3': final_ref, 'rows': [], 'realization_inputs': realized,
                    'generations': [{**evidence[0], 'request_id': 'fixture-image', 'request': {'input_files': []}}]}
                path = self.root / '07-visual-direction' / vc.MAPPING; artifacts.write_json_artifact(path, mapping)
                stages = {'visual_direction': {'artifacts': [final_ref, vc._record(self.root, path)]}}
                return vc.validate_realization_evidence(self.root, stages, 2, receipt_ref, job_id='job')
            self.assertIn('mapping', consume())
            final['segments'][0]['shot_recipe']['components'][0]['provider'] = 'unapproved-provider'
            with self.assertRaisesRegex(ValueError, 'compiled template differs'):
                consume()
            director['segments'][0]['start'] += .25
            with self.assertRaisesRegex(ValueError, 'authorized segment timing'):
                vc._validate_draft_against_source(self.root, self.proposal, director, treatment)

    def test_frozen_realization_cannot_be_overwritten_before_stage_revision(self):
        from types import SimpleNamespace
        job=SimpleNamespace(stages={'visual_direction':{'status':'completed','artifacts':[]}})
        with self.assertRaisesRegex(ValueError,'frozen'):
            vc.write_realization_mapping(job, director_path=None, treatment_path=None)

    def test_realization_mappings_are_immutable_and_unique_per_revision(self):
        old = self.root / '07-visual-confirmation' / 'r26-approved' / vc.MAPPING
        artifacts.write_json_artifact(old, {'original': True})
        old_bytes = old.read_bytes()
        first = vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        again = vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        later = vc._write_unique_mapping(self.root, 35, {'approval': 'same', 'plan': 'second'})
        self.assertEqual(first, again)
        self.assertNotEqual(first, later)
        self.assertEqual(old.read_bytes(), old_bytes)
        first.write_bytes(b'not the approved mapping')
        with self.assertRaisesRegex(ValueError, 'differs'):
            vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        self.assertEqual(first.read_bytes(), b'not the approved mapping')

    def test_realization_writer_retains_old_mapping_and_source_approval(self):
        from edit.hd.tools import state
        from types import SimpleNamespace
        old = self.root / '07-visual-confirmation' / 'r26-approved' / vc.MAPPING
        artifacts.write_json_artifact(old, {'original': True}); old_bytes = old.read_bytes()
        plan = self.root / '07-visual-direction' / 'visual-plan.json'
        artifacts.write_json_artifact(plan, {'segments': []})
        director = self.root / 'director.json'; treatment = self.root / 'treatment.json'
        artifacts.write_json_artifact(director, {'segments': []})
        artifacts.write_json_artifact(treatment, {'scenes': []})
        approval = {'path': 'manifests/user-confirmation.json', 'sha256': 'a' * 64, 'bytes': 1}
        source = {'path': '07-visual-confirmation/r26-approved/proposal.json', 'sha256': 'b' * 64, 'bytes': 1}
        job = SimpleNamespace(job_dir=self.root, revision=35, stages={'visual_direction': {
            'status': 'ready', 'artifacts': [vc._record(self.root, plan)]}})
        with mock.patch.object(vc, 'validate_visual_authorization', return_value={
                'artifact': approval, 'payload': {'source': source}, 'source': {'rows': []}}), \
             mock.patch.object(vc, '_completed_generations', return_value=[]), \
             mock.patch.object(state, 'mark_visual_ready') as ready:
            path = vc.write_realization_mapping(job, director_path=director, treatment_path=treatment)
        self.assertNotEqual(path, old)
        self.assertEqual(old.read_bytes(), old_bytes)
        mapping = vc._read(path)
        self.assertEqual(mapping['source_approval'], approval)
        self.assertEqual(mapping['proposal'], source)
        self.assertEqual(mapping['final_v3'], vc._record(self.root, plan))
        ready.assert_called_once()


class OfficialPortraitCropTests(unittest.TestCase):
    def test_supplement_keeps_one_original_routing_number(self):
        from edit.hd.tools import visual_plan
        segment = {'segment_id': 'seg-001', 'start': 0, 'end': 2,
            'visual_intent': {'statement': '原任务'}, 'visual_strategy': {'mode': 'hybrid', 'components': [
                {'component_id': 'base', 'kind': 'ai_generated', 'layer_role': 'base'},
                {'component_id': 'action', 'kind': 'code_generated', 'layer_role': 'annotation'}]},
            'bindings': {'base': {'template_id': 'original/design'}, 'action': {'template_id': 'barty/motion-broll'}}}
        selection = {'native_supplements': [{'segment_id': 'seg-001',
            'base_component_id': 'base', 'action_component_id': 'action'}]}
        text = visual_plan._review_text({'segments': [segment]}, skill_selection=selection,
                                       numbering={'seg-001:base': 2})
        self.assertEqual(text.count('| 2 |'), 1)
        self.assertIn('original/design + barty/motion-broll（同项补足层）', text)
        self.assertNotIn('| 3 |', text)

    def test_approved_task_example_cannot_add_numbers_or_claim_evidence(self):
        from edit.hd.tools import visual_plan
        from edit.hd.tests.test_visual_plan import visual_intent
        quote = '整理日程：中性邮件示例包含项目沟通，周五15:00；不作为实测或事实证据。'
        component = {'component_id': 'native', 'kind': 'code_generated',
                     'semantic_role': 'explanation', 'brief': quote}
        segment = {'segment_id': 'seg-001', 'visible_text': ['整理日程', '周五 15:00'],
                   'visual_intent': visual_intent(),
                   'visual_strategy': {'components': [component]}}
        analysis = {'analysis_sha256': 'a' * 64, 'analysis': {'thesis': '整理日程', 'items': []}}
        record = {'content_analysis_sha256': 'a' * 64, 'entries': [{
            'segment_id': 'seg-001', 'text': '周五 15:00', 'source_ref': 'component:native',
            'source_quote': quote, 'reason': '沿已确认示例保留同一时间，不声称真实执行。'}]}
        visual_plan._validate_reviewed_visual_text(record, analysis_record=analysis, segments=[segment])
        for change in ('number', 'evidence', 'evidence_goal', 'fact', 'real_ui'):
            actual, review = copy.deepcopy(segment), copy.deepcopy(record)
            if change == 'number':
                actual['visible_text'][1] = review['entries'][0]['text'] = '周五 16:00'
            elif change == 'evidence': actual['visual_strategy']['components'][0]['semantic_role'] = 'evidence'
            elif change == 'evidence_goal': actual['visual_intent']['semantic_goals'] = ['evidence']
            elif change == 'fact': actual['visual_intent']['claims'][0]['type'] = 'fact'
            else: actual['visual_intent']['entities'] = [{'type': 'real_product_ui'}]
            with self.subTest(change=change), self.assertRaises(visual_plan.VisualPlanError):
                visual_plan._validate_reviewed_visual_text(review, analysis_record=analysis, segments=[actual])

    def test_same_source_crop_renders_exact_portrait_without_changing_native_gate(self):
        import tempfile
        import shutil
        from types import SimpleNamespace
        from PIL import Image
        from edit.hd.tools import broll_component_executor, material_adapter, visual_strategy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'official.png'
            original = Image.new('RGB', (320, 160), 'blue')
            original.paste('red', (0, 0, 90, 160)); original.save(source)
            digest = artifacts.sha256_file(source)
            binding = {'source_id': 'official', 'sha256': digest, 'snapshot_path': 'official.png',
                'portrait_crop': {'source_sha256': digest, 'source_width': 320, 'source_height': 160,
                                  'x': 0, 'y': 0, 'width': 90, 'height': 160}}
            candidate = {'asset_id': 'official', 'kind': 'official_material', 'quality_score': 1,
                'semantic_match_score': 1, 'hard_gates': {'native_vertical': False,
                'semantic_match': True, 'quality_readability': True, 'factual_reliability': True}}
            with self.assertRaises(ValueError):
                visual_strategy.stable_same_kind_candidates([candidate], 'official_material')
            ranked = visual_strategy.stable_same_kind_candidates([candidate], 'official_material', framing_binding=binding)
            self.assertFalse(ranked[0]['hard_gates']['native_vertical'])
            component = {**binding, 'artifact_contract': {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': False}}
            output = root / 'portrait.png'
            context = SimpleNamespace(source_path=source, source_sha256=digest,
                                      component=broll_component_executor._freeze(component), staging_path=output)
            adapter = material_adapter.create_adapter('official_material', 'image', shutil.which('ffmpeg'), shutil.which('ffprobe'))
            result = adapter.invoke(context)
            broll_component_executor._validate_adapter_result(result, 'BROLL_COMPOSITE_FAILED',
                                                               job_dir=root, request_only_values=())
            with Image.open(output) as actual:
                self.assertEqual(actual.size, (1080, 1920))
                self.assertEqual(actual.tobytes(), original.crop((0, 0, 90, 160)).resize((1080, 1920), Image.Resampling.LANCZOS).tobytes())
            self.assertEqual(artifacts.sha256_file(source), digest)
            self.assertEqual(result.invocation_evidence['portrait_crop'], binding['portrait_crop'])
            for change in ('outside', 'source', 'quality'):
                bad_binding, bad_candidate = copy.deepcopy(binding), copy.deepcopy(candidate)
                if change == 'outside': bad_binding['portrait_crop']['x'] = 300
                elif change == 'source': bad_binding['portrait_crop']['source_sha256'] = 'b' * 64
                else: bad_candidate['hard_gates']['quality_readability'] = False
                with self.subTest(change=change), self.assertRaises(ValueError):
                    visual_strategy.stable_same_kind_candidates([bad_candidate], 'official_material', framing_binding=bad_binding)
            old_binding = {k: v for k, v in binding.items() if k != 'portrait_crop'}
            segment = {'segment_id': 'seg-001', 'visual_strategy': {'components': [
                {'component_id': 'image', 'kind': 'official_material', 'media_type': 'image'}]}, 'bindings': {'image': old_binding}}
            frozen = {'segments': [segment]}; director = copy.deepcopy(frozen)
            director['segments'][0]['bindings']['image'] = binding
            before = {'motion_readability': [{'segment_id': 'seg-001', 'component_id': 'image', 'targets': [
                {'target_id': 'model', 'content_ref': {'value': 'model'}, 'region': {'x': 0, 'y': 0, 'width': 100, 'height': 100}}]}]}
            after = copy.deepcopy(before); after['motion_readability'][0]['targets'][0]['region']['width'] = 200
            self.assertEqual(vc._normalize_official_crop_text(root, frozen, before, director, after, after), before)
            after['motion_readability'][0]['targets'][0]['content_ref']['value'] = 'different model'
            with self.assertRaises(ValueError):
                vc._normalize_official_crop_text(root, frozen, before, director, after, after)


class OpenfilmTypographyTests(unittest.TestCase):
    def test_only_existing_css_font_sizes_can_increase(self):
        from edit.hd.tools import visual_confirmation as vc
        source = '<style>.label{font-size:36px}.row{font-size:37px}</style><p>原字</p><script>frame(1)</script>'
        revised = source.replace('36px','42px').replace('37px','44px')
        vc._validate_css_font_growth(source,revised)
        for invalid in (source, source.replace('36px','32px'), revised.replace('原字','新字'),
                        revised.replace('frame(1)','frame(2)'), revised.replace('44px','144px'),
                        revised.replace('.row{','.row{display:none;')):
            with self.subTest(invalid=invalid), self.assertRaises(vc.VisualConfirmationError):
                vc._validate_css_font_growth(source,invalid)


class GbroFramePreparationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from types import SimpleNamespace
        from edit.hd.tools import generation_queue, generation_channels, parent_static_labels
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); (self.root / 'manifests').mkdir()
        self.job = SimpleNamespace(job_dir=self.root, job_id='synthetic')
        self.queue = generation_queue
        self.image = {'id':'image', 'purpose':'image', 'segment_id':'seg-016', 'component_id':'scene',
                      'arguments':{'prompt':'approved still'}, 'depends_on':[], 'input_files':[]}
        self.video = {'id':'video', 'purpose':'video', 'segment_id':'seg-016', 'component_id':'scene',
            'arguments':{'prompt':'Original action timing 1.125 then 1.84..2.30; label from first frame.',
                         'first_frame':{'$step':'image', 'output':0}, 'model':'approved-model',
                         'project_id':'approved-project', 'duration':5, 'params':{'mode':'pro'}},
            'depends_on':['image'], 'input_files':[]}
        def write(name, value):
            path = self.root / name
            if isinstance(value, bytes): path.write_bytes(value)
            else: artifacts.write_json_artifact(path, value)
            return vc._record(self.root, path)
        segment = {'segment_id':'seg-016', 'visible_text':['任务示意'],
                   'bindings':{'scene':{}}, 'visual_strategy':{'components':[{'component_id':'scene'}]}}
        self.proposal = {'source_id':'synthetic-source', 'generation_steps':[self.image, self.video],
            'inputs':{'director':write('director.json', {'segments':[segment]}),
                      'treatment':write('treatment.json', {'skill_selection':{'assignments':[
                          {'segment_id':'seg-016', 'component_id':'scene', 'skill_id':'gbro-collage-broll',
                           'template_id':'gbro-collage-broll/design'}]}})}}
        self.source = write('source.png', b'preserved completed generated still')
        self.record = {'source_id':self.proposal['source_id'], 'step_id':'video', 'source_image':self.source,
            **{key:write(key+'.png', key.encode()) for key in ('blank_frame','first_frame','last_frame')},
            'parent_static_labels':{'job_path':'labels.json','sha256':'a'*64,'byte_count':1},
            'native_skill':vc._record(_env.PROJECT, _env.PROJECT / 'vendor/gbro-collage-broll/SKILL.md'),
            'calls':[{'argv':['ffmpeg','actual-native-preparation'], 'exit_code':0}]}
        self.descriptor = write('preparation.json', self.record)
        self.authorized = {'source':self.proposal, 'artifact':{'path':'approved.json','sha256':'b'*64,'bytes':1}}
        patch = mock.patch.object(vc, 'validate_visual_authorization', return_value=self.authorized)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(parent_static_labels, 'load', return_value=[{'content_ref':{'value':'任务示意'}}])
        self.labels = patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(parent_static_labels, '_file', return_value=self.root/'labels.json')
        patch.start(); self.addCleanup(patch.stop)
        (self.root/'labels.json').write_bytes(b'label manifest')
        def prepare(job, purpose, arguments, *, request_id, input_files):
            return {'id':request_id, 'purpose':purpose, 'tool':'fixture.'+purpose,
                    'arguments':arguments, 'input_files':input_files}
        patch = mock.patch.object(generation_channels, 'prepare_request', side_effect=prepare)
        patch.start(); self.addCleanup(patch.stop)
        image_request = prepare(self.job, 'image', self.image['arguments'],
                                request_id=vc._request_id(self.proposal,self.image), input_files=[])
        self.saved = {'schema_version':1, 'job_dir':str(self.root), 'job_id':'synthetic',
                     'max_concurrency':1,'paused':False,'items':{image_request['id']:{'request':image_request,
                         'fingerprint':generation_queue._fingerprint(image_request), 'status':'completed',
                         'completion_response':{'artifacts':[{'type':'image','path':str(self.root/'source.png'),
                                                               'sha256':self.source['sha256'],'bytes':self.source['bytes']}]}}}}
        self.save_queue()

    def save_queue(self):
        artifacts.write_json_artifact(self.root/'manifests/generation-queue.json', self.saved)

    def test_stops_for_native_inputs_then_preserves_prompt_and_resolves_both_frames(self):
        before = copy.deepcopy(self.proposal)
        with mock.patch.object(self.queue, 'add_authorized') as add:
            actions = vc.generation_actions(self.job)
        add.assert_not_called()
        self.assertEqual([(a['action'],a['step_id']) for a in actions], [('prepare_template_inputs','video')])
        self.assertIsNone(vc.generation_item(self.queue.status(self.root), self.proposal, self.video, self.job)[1])
        with self.assertRaisesRegex(ValueError,'not prepared'):
            vc._build_generation_request(self.job,self.proposal,self.video)
        vc.record_gbro_frame_preparation(self.job,self.descriptor)
        vc.record_gbro_frame_preparation(self.job,self.descriptor)
        request = vc._build_generation_request(self.job,self.proposal,self.video)
        self.assertEqual(request['arguments'], {**self.video['arguments'],
            'first_frame':str(self.root/'first_frame.png'), 'last_frame':str(self.root/'last_frame.png')})
        self.assertIn(self.source,request['input_files'])
        self.assertIn(self.descriptor,request['input_files'])
        self.assertEqual(self.proposal,before)
        self.assertEqual(self.queue.status(self.root)['items'],self.saved['items'])

    def test_stage_returns_gbro_preparation_before_future_request_exists(self):
        from types import SimpleNamespace
        director = self.root / 'director.json'
        payload = artifacts.read_json_artifact(director)
        payload['segments'][0]['visual_strategy']['components'][0]['kind'] = 'ai_generated'
        artifacts.write_json_artifact(director, payload)
        self.proposal['inputs']['director'] = vc._record(self.root, director)
        job = SimpleNamespace(job_dir=self.root, job_id='synthetic', revision=0,
            stages={'visual_direction': {'artifacts': [], 'status': 'ready'}})
        with mock.patch.object(run_stage, 'prepare_visual_dependencies', side_effect=AssertionError('premature join')):
            response = run_stage.resume_visual_direction(job, _env.PROJECT)
        self.assertEqual([(a['action'], a.get('step_id')) for a in response['actions']],
                         [('prepare_template_inputs', 'video')])
        self.assertEqual(response['errors'], [])
        self.assertEqual(self.queue.status(self.root)['items'], self.saved['items'])

    def test_preparation_rejects_queued_videos_and_cannot_be_replaced(self):
        rid = vc._request_id(self.proposal,self.video)
        request = {'id':rid,'purpose':'video','tool':'fixture.video',
                   'arguments':self.video['arguments'],'input_files':[]}
        for status in ('ready','submitting','pending','unknown','completed','failed'):
            self.saved['items'][rid] = {'status':status,'request':request,'fingerprint':self.queue._fingerprint(request)}
            self.save_queue()
            with self.subTest(status=status), self.assertRaisesRegex(ValueError,'already queued or submitted'):
                vc.record_gbro_frame_preparation(self.job,self.descriptor)
        del self.saved['items'][rid]; self.save_queue()
        vc.record_gbro_frame_preparation(self.job,self.descriptor)
        altered = self.root/'other-preparation.json'
        artifacts.write_json_artifact(altered,{**self.record,'calls':[{'argv':['ffmpeg','another-preparation'],'exit_code':0}]})
        with self.assertRaisesRegex(ValueError,'immutable'):
            vc.record_gbro_frame_preparation(self.job,vc._record(self.root,altered))
        (self.root/'first_frame.png').write_bytes(b'changed prepared frame')
        with self.assertRaisesRegex(ValueError,'evidence changed'):
            vc._build_generation_request(self.job,self.proposal,self.video)

    def test_without_approved_text_uses_the_original_empty_paper_first_frame(self):
        director = self.root/'director.json'
        data = artifacts.read_json_artifact(director)
        data['segments'][0]['visible_text'] = []
        artifacts.write_json_artifact(director,data)
        self.proposal['inputs']['director'] = vc._record(self.root,director)
        self.record['parent_static_labels'] = None
        self.record['first_frame'] = self.record['blank_frame']
        artifacts.write_json_artifact(self.root/'preparation.json',self.record)
        descriptor = vc._record(self.root,self.root/'preparation.json')
        vc.record_gbro_frame_preparation(self.job,descriptor)
        request = vc._build_generation_request(self.job,self.proposal,self.video)
        self.assertEqual(request['arguments']['first_frame'],str(self.root/'blank_frame.png'))
        self.assertEqual(request['arguments']['prompt'],self.video['arguments']['prompt'])
        self.labels.assert_not_called()

    def test_unsent_tail_revision_preserves_history_and_reuses_only_completed_first_frame(self):
        from edit.hd.tools import generation_inputs, generation_channels
        vc.record_gbro_frame_preparation(self.job, self.descriptor)
        original_index = vc._gbro_preparation_path(self.job, self.proposal, self.video).read_bytes()
        request = vc._build_generation_request(self.job, self.proposal, self.video)
        rid = request['id']
        original_item = {'request': request, 'fingerprint': self.queue._fingerprint(request),
            'status': 'ready', 'config_sha256': 'config', 'channel_identity': {'model': 'approved'},
            'approved_plan_sha256': artifacts.sha256_json({'requests': [request]}),
            'authorization': {'source': self.authorized['artifact'], 'steps': {rid: 'video'}}}
        self.saved['items'][rid] = copy.deepcopy(original_item)
        self.save_queue()
        artifacts.write_json_artifact(self.root/'manifests/generation-channels.json', {'video': {
            'reference_mode': 'upload', 'upload': {'tool': 'fixture.upload',
            'arguments': {'file': {'$input': 'path'}}, 'result_path': ['url']}}})
        first = generation_inputs.next_action(self.root, request)
        generation_inputs.record_result(self.root, request, first, {'url': 'https://fixture/first'})
        binding = generation_inputs._binding(self.root, 'video')
        old_upload_path, _ = generation_inputs._state(self.root, request, binding)
        old_upload_bytes = old_upload_path.read_bytes()
        tail = self.root/'clean-tail.png'; tail.write_bytes(b'different cleaned native tail fixture')
        after = {**self.record, 'last_frame': vc._record(self.root, tail),
                 'calls': [{'argv': ['ffmpeg', 'actual-native-tail-correction'], 'exit_code': 0}]}
        prepared = self.root/'corrected-preparation.json'; artifacts.write_json_artifact(prepared, after)
        descriptor = vc._record(self.root, prepared)
        expected = artifacts.sha256_json(request)
        def identity(root, current, config):
            self.queue._inputs(root, current)
            return {'model': 'approved'}
        with mock.patch.object(state, 'load_job', return_value=self.job), mock.patch.object(self.queue, '_approved', return_value=('synthetic', 'config', {'max_concurrency': 1})),              mock.patch.object(self.queue, '_request', side_effect=identity),              mock.patch.object(vc, '_validate_source', return_value=({}, self.proposal)):
            for status in ('submitting', 'pending', 'unknown', 'completed', 'failed', 'moderated'):
                self.saved['items'][rid] = {**copy.deepcopy(original_item), 'status': status}
                self.save_queue()
                with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'never claimed or submitted'):
                    vc.revise_unsent_gbro_frames(self.job, rid, descriptor, expected)
            self.saved['items'][rid] = {**copy.deepcopy(original_item), 'claimed_at': 1}
            self.save_queue()
            with self.assertRaisesRegex(ValueError, 'never claimed or submitted'):
                vc.revise_unsent_gbro_frames(self.job, rid, descriptor, expected)
            self.saved['items'][rid] = copy.deepcopy(original_item); self.save_queue()
            vc.revise_unsent_gbro_frames(self.job, rid, descriptor, expected)
            saved = self.queue.status(self.root)['items'][rid]
            current = saved['request']
            self.assertEqual(current, vc._build_generation_request(self.job, self.proposal, self.video))
            self.assertEqual(vc.generation_item(self.queue.status(self.root), self.proposal, self.video, self.job)[0], rid)
            self.assertEqual(saved['input_revision_history'][0]['request'], request)
            self.assertEqual(saved['input_revision_history'][0]['preparation'], self.descriptor)
            self.assertEqual(old_upload_path.read_bytes(), old_upload_bytes)
            self.assertEqual(vc._gbro_preparation_path(self.job, self.proposal, self.video).read_bytes(), original_index)
            self.assertEqual(artifacts.read_json_artifact(self.root/'preparation.json'), self.record)
            self.assertEqual(current['arguments'], {**request['arguments'], 'last_frame': str(tail)})
            with self.assertRaisesRegex(ValueError, 'differs from its approved step'):
                vc.validate_generation_request(self.job, original_item['authorization'], request)
            with self.assertRaisesRegex(ValueError, 'request changed'):
                vc.revise_unsent_gbro_frames(self.job, rid, descriptor, expected)
            action = generation_channels.next_action(self.job, rid)
            self.assertEqual(action['arguments']['file'], str(tail))
            generation_inputs.record_result(self.root, current, action, {'url': 'https://fixture/clean-tail'})
            generated = self.queue.claim(self.root, rid)
            self.assertEqual(generated['arguments']['first_frame'], 'https://fixture/first')
            self.assertEqual(generated['arguments']['last_frame'], 'https://fixture/clean-tail')
            self.assertEqual(len([x for x in self.queue.status(self.root)['items'].values()
                                  if x['request']['purpose'] == 'video']), 1)

    def test_rejects_wrong_source_labels_route_and_unfinished_dependency(self):
        for defect in ('source_id','source_image','same_frame','failed_call','prompt','label','route','pending'):
            record = copy.deepcopy(self.record); proposal = copy.deepcopy(self.proposal)
            queue = copy.deepcopy(self.saved)
            if defect=='source_id': record['source_id']='other'
            elif defect=='source_image': record['source_image']=record['first_frame']
            elif defect=='same_frame': record['first_frame']=record['last_frame']
            elif defect=='failed_call': record['calls'][0]['exit_code']=1
            elif defect=='prompt': record['prompt']='unapproved rewritten prompt'
            elif defect=='label': record['parent_static_labels']=None
            elif defect=='route':
                field='treatment'
                path=self.root/('other-'+field+'.json'); data=artifacts.read_json_artifact(self.root/(field+'.json'))
                data['skill_selection']['assignments'][0]['skill_id']='another-skill'
                artifacts.write_json_artifact(path,data); proposal['inputs'][field]=vc._record(self.root,path)
            else: next(iter(queue['items'].values()))['status']='pending'
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                vc._validate_gbro_frames(self.job,proposal,self.video,record,queue)


if __name__ == "__main__":
    unittest.main()

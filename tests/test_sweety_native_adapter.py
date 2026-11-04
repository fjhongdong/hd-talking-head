"""Sweety dispatch and immutable native-result consumption; no generation calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import sweety_native_adapter as sweety


def brief():
    # Contract-only fixture, not a real semantic approval or media qualification.
    return {'schema_version':2,'dependency_id':sweety.DEPENDENCY_ID,'job_id':'contract-only',
        'source_binding':{'aroll_sha256':'a'*64,'segment_id':'seg-contract','start':0,'end':5},
        'composition':{'width':1080,'height':1920,'fps':24,'frames':120},'alpha':True,
        'canvas_transport':'identity','template_request':{'semantic_family':'section_heading',
        'information_units':1,'numeric_values':[],'numeric_scale':'not_applicable'},
        'template_id':'web-kinetic-title','semantic_goal':'说明测试边界','transcript':'只验证交接，不生成内容。',
        'word_anchors':[{'text':'只验证交接','start':0,'end':5}],
        'speech':{'job_path':'inputs/speech.wav','sha256':'a'*64,'byte_count':1},'materials':[],
        'authorization':{'new_tts':False,'new_image_generation':False},
        'project_directory':'native-projects/contract','result_record_path':'native-inputs/contract.json',
        'task_source':{'semantic_row_id':'row-contract','quote':'只验证交接，不生成内容。',
            'semantic':'说明测试边界','required_change':'验证结果消费','component_brief':'保留原生结果'},
        'native_options':[]}


class SweetyNativeTest(unittest.TestCase):
    def test_selected_task_rejects_changed_word_clock_or_parent_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();b=brief();arroll=root/'approved-aroll.mp4';arroll.write_bytes(b'approved clock fixture')
            b['source_binding']['aroll_sha256']=sweety.sha(arroll)
            f=root/'native-inputs/brief.json';f.parent.mkdir();sweety.artifacts.write_json_artifact(f,b)
            binding={'dependency_id':sweety.DEPENDENCY_ID,'template_id':sweety.DEPENDENCY_ID+'/'+b['template_id'],
                     'brief_sha256':sweety.sha(f)}
            component={'component_id':'scene','brief':b['task_source']['component_brief']}
            director={'segments':[{'segment_id':'seg-contract','start':0,'end':5,
                                  'bindings':{'scene':binding},'visual_strategy':{'components':[component]}}]}
            row={'row_id':'row-contract','quote':b['task_source']['quote'],'semantic':b['semantic_goal'],
                 'components':[{'segment_id':'seg-contract','component_id':'scene'}]}
            beat={'segment_id':'seg-contract','component_id':'scene','semantic_row_id':'row-contract',
                  'component_brief':component['brief'],'required_change':b['task_source']['required_change'],
                  'transcript':b['transcript']}
            treatment={'semantic_lists':{'broll':[row]},'skill_selection':{'beats':[beat]},
                       'scenes':[{'segment_id':'seg-contract','component_id':'scene','brief_path':'native-inputs/brief.json'}]}
            job=SimpleNamespace(job_dir=root,job_id=b['job_id'])
            with patch('edit.hd.tools.visual_plan._approved_artifact',return_value=arroll), \
                 patch('edit.hd.tools.motion_capabilities._approved_speech',return_value=b['word_anchors']), \
                 patch.object(sweety,'_inputs') as checked:
                sweety.validate_selected_inputs(job,director,treatment)
                checked.assert_called_once()
                for mutate in (lambda x:x['word_anchors'][0].update(end=4.9),
                               lambda x:x.update(job_id='another-job'),
                               lambda x:x['task_source'].update(semantic='changed meaning')):
                    changed=copy.deepcopy(b);mutate(changed);sweety.artifacts.write_json_artifact(f,changed)
                    binding['brief_sha256']=sweety.sha(f)
                    with self.assertRaises(ValueError):sweety.validate_selected_inputs(job,director,treatment)
                # Other channels are not required to supply a Sweety task.
                sweety.validate_selected_inputs(job,director,{},dependency_id='anidoodle')
            self.assertEqual(sweety.parent_input_facts(b)['word_anchors'],b['word_anchors'])

    def test_parent_16k_pcm_is_normalized_without_gain_or_retiming(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();directory=root/'native-projects/test';audio=directory/'inputs/narration';audio.mkdir(parents=True)
            original=audio/'parent-source.wav';target=audio/'master.wav'
            with wave.open(str(original),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'))
                stream.writeframes(b'\x10\x00'*32000)
            b=brief();b['composition']['frames']=48;b['speech']=sweety.descriptor(root,original)
            b['word_anchors']=[{'text':'contract fixture','start':0,'end':1.6}]
            import subprocess
            ffmpeg=sweety.check_runtime(mode='reuse')['tools']['ffmpeg']
            command=sweety._narration_command(ffmpeg,original,target,None)
            subprocess.run(command,check=True,capture_output=True)
            record={'raw_source':b['speech'],'raw_sha256':b['speech']['sha256'],'raw_copy':b['speech'],
                    'processed_sha256':sweety.sha(target),'word_anchors_sha256':sweety.artifacts.sha256_json(b['word_anchors']),
                    'tail_fade':None,'filter':'aresample=48000','argv':command}
            sweety.artifacts.write_json_artifact(audio/'parent-import.json',record)
            sweety.artifacts.write_json_artifact(directory/'job.json',{'narration':{'source':'inputs/narration/master.wav'}})
            sweety.verify_narration_import(root,b,directory)
            self.assertEqual(sweety.sha(original),b['speech']['sha256'])
            with wave.open(str(target)) as stream:
                self.assertEqual((stream.getframerate(),stream.getnframes()),(48000,96000))
            self.assertEqual(sweety._pcm(original),sweety._pcm(target))
            # A real encoded audio stream is rejected by the same probe used
            # in capture and completed-result inspection, even at the right canvas.
            video=root/'with-audio.mp4'
            subprocess.run([ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i',
                'color=c=white:s=1080x1920:r=24','-i',str(target),'-frames:v','1',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(video)],
                check=True,capture_output=True)
            with self.assertRaisesRegex(ValueError,'silent'):
                sweety._silent_probe(video,{'width':1080,'height':1920,'fps':24,'frames':1},False)

    def test_tail_preparation_rejects_spoken_samples_and_duration_changes(self):
        with self.assertRaises(ValueError):sweety.tail_fade_interval(2,1.95)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);directory=root/'native-projects/test';audio=directory/'inputs/narration';audio.mkdir(parents=True)
            def wav(name,frames):
                with wave.open(str(audio/name),'wb') as stream:
                    stream.setparams((1,2,48000,0,'NONE','not compressed'));stream.writeframes(b'\x10\x00'*frames)
            wav('parent-source-tail.wav',96000);wav('master-tail.wav',96000)
            b=brief();b['composition']['frames']=48;b['word_anchors']=[{'text':'contract fixture','start':0,'end':1.6}]
            b['speech']=sweety.descriptor(root,audio/'parent-source-tail.wav')
            sweety.artifacts.write_json_artifact(directory/'job.json',{'narration':{'source':'inputs/narration/master-tail.wav'}})
            record={'raw_source':b['speech'],'raw_sha256':b['speech']['sha256'],'raw_copy':b['speech'],
                    'processed_sha256':sweety.sha(audio/'master-tail.wav'),
                    'word_anchors_sha256':sweety.artifacts.sha256_json(b['word_anchors']),
                    'tail_fade':{'start':1.5,'end':1.88,'quiet_tail_seconds':.12},'filter':'not used'}
            record_path=audio/'parent-import-tail.json';sweety.artifacts.write_json_artifact(record_path,record)
            with self.assertRaisesRegex(ValueError,'final word'):
                sweety.verify_narration_import(root,b,directory)
            wav('master-tail.wav',95000);record['processed_sha256']=sweety.sha(audio/'master-tail.wav')
            sweety.artifacts.write_json_artifact(record_path,record)
            with self.assertRaisesRegex(ValueError,'duration'):
                sweety.verify_narration_import(root,b,directory)

    def test_original_catalog_and_clock(self):
        rows=sweety.load_template_catalog(SKILL)
        self.assertEqual(len(rows),41)
        styles=[r for r in rows if r['native_template_group']=='style']
        self.assertEqual(len(styles),21)
        self.assertEqual(sum(r['drawing_mode']=='draw' for r in styles),6)
        self.assertEqual(sum(r['requires_reveal_acceptance'] for r in styles),15)
        self.assertNotIn('custom',{r['native_option_id'] for r in rows})
        b=brief();sweety.validate_brief(b)
        for transform in (lambda x:x.update(template_id='web-custom'),
                          lambda x:x.update(alpha=False),
                          lambda x:x['composition'].update(frames=119)):
            changed=copy.deepcopy(b);transform(changed)
            with self.assertRaises(ValueError):sweety.validate_brief(changed)
        changed=copy.deepcopy(b);changed.update(template_id='style-17',alpha=False)
        self.assertEqual(sweety._template(sweety.validate_brief(changed))['native_option_id'],'17')

    def test_visual_inputs_bind_renderer_dependencies_and_reject_external_frames(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d).resolve();root=base/'job';directory=root/'native-projects/style'
            def file(name):
                p=directory/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode());return p
            for name in ('work/narration.wav','outputs/cover.png','work/assets/art.png','work/assets/art.npz',
                         'work/assets/art-line.png','work/assets/art-paint.png','work/assets/art-shade.png',
                         'work/assets/art-sketch.png','work/watermark-plan.json','work/assets/unrelated-cache.png'):
                file(name)
            frames=file('work/web-motion/clip/00000.png').parent;file('work/web-motion/clip/00001.png')
            hand=file('inputs/hand.png');mark=file('inputs/watermark.png');background=file('inputs/background.png')
            font=file('inputs/counter.ttf')
            timeline={'assets':{'art':{'type':'counter','counter':{'font':{'path':str(font)}}}},
                      'hand':{'source':str(hand)},'watermark':{'source':str(mark)},
                      'pages':[{'background':str(background),'overlays':[{'frames':str(frames),'count':2}]}]}
            target=directory/'work/timeline.json';sweety.artifacts.write_json_artifact(target,timeline)
            frozen=sweety._visual_inputs(root,directory);names={r['job_path'] for r in frozen}
            for suffix in ('inputs/hand.png','inputs/watermark.png','inputs/background.png','inputs/counter.ttf',
                           'work/watermark-plan.json','work/assets/art-sketch.png','work/web-motion/clip/00001.png'):
                self.assertIn('native-projects/style/'+suffix,names)
            self.assertNotIn('native-projects/style/work/assets/unrelated-cache.png',names)
            (frames/'00000.png').write_bytes(b'changed frame')
            self.assertNotEqual(sweety._visual_inputs(root,directory),frozen)
            outside=base/'another-job/frames';outside.mkdir(parents=True)
            for index in range(2):(outside/f'{index:05d}.png').write_bytes(b'outside Job')
            timeline['pages'][0]['overlays'][0]['frames']=str(outside)
            sweety.artifacts.write_json_artifact(target,timeline)
            with self.assertRaisesRegex(ValueError,'current Job'):
                sweety._visual_inputs(root,directory)
            # A symlink inside the Job must not hide the same external cache.
            (directory/'linked-frames').symlink_to(outside,target_is_directory=True)
            timeline['pages'][0]['overlays'][0]['frames']=str(directory/'linked-frames')
            sweety.artifacts.write_json_artifact(target,timeline)
            with self.assertRaisesRegex(ValueError,'current Job'):
                sweety._visual_inputs(root,directory)
            timeline['pages'][0]['overlays'][0]['frames']=str(frames)
            sweety.artifacts.write_json_artifact(target,timeline)
            vendor=sweety.source_root();official=vendor/'README.md';original_sha=sweety.sha(official)
            for output,destination in ((directory/'out',vendor),
                    (directory/'out/visual.mp4',official),
                    (directory/'work/review/page-00.jpg',official),
                    (directory/'work/watermark-plan.json',official)):
                output.parent.mkdir(parents=True,exist_ok=True)
                saved=output.read_bytes() if output.is_file() else None
                if output.exists():output.unlink()
                output.symlink_to(destination,target_is_directory=destination.is_dir())
                try:
                    with self.assertRaisesRegex(ValueError,'native output'):
                        sweety._visual_inputs(root,directory)
                finally:
                    output.unlink()
                    if saved is not None:output.write_bytes(saved)
            self.assertEqual(sweety.sha(official),original_sha)

    def test_completed_result_consumption_checks_both_frozen_files(self):
        payload=json.dumps(brief(),ensure_ascii=False).encode();request_sha=hashlib.sha256(payload).hexdigest()
        media=b'format-only consumer bytes; not a native rendered sample'
        record={'status':'completed','dependency_id':sweety.DEPENDENCY_ID,'template_id':'web-kinetic-title',
                'request_sha256':request_sha,'media':{'job_path':'native-projects/contract/out/visual.mov',
                    'sha256':hashlib.sha256(media).hexdigest(),'byte_count':len(media)}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);records=[];handles=[]
            for name,data in [('native-inputs/contract.json',json.dumps(record).encode()),(record['media']['job_path'],media)]:
                item=root/str(len(records));item.write_bytes(data);handle=item.open('rb');handles.append(handle)
                records.append({'media_ref':'sweety-'+hashlib.sha256(name.encode()).hexdigest()[:32],
                    'fd':handle.fileno(),'sha256':hashlib.sha256(data).hexdigest(),'byte_length':len(data)})
            try:
                manifest={'brief_sha256':request_sha,'media':records}
                sweety.consume_result(payload,manifest,root/'copied.mov')
                self.assertEqual((root/'copied.mov').read_bytes(),media)
                for handle in handles:handle.seek(0)
                with (root/'descriptor.mov').open('xb') as output:
                    sweety.consume_result(payload,manifest,f'/dev/fd/{output.fileno()}')
                self.assertEqual((root/'descriptor.mov').read_bytes(),media)
                changed=copy.deepcopy(manifest);changed['media'][1]['sha256']='b'*64
                for handle in handles:handle.seek(0)
                with self.assertRaises(ValueError):sweety.consume_result(payload,changed,root/'rejected.mov')
                self.assertFalse((root/'rejected.mov').exists())
            finally:
                for handle in handles:handle.close()


if __name__=='__main__':unittest.main()

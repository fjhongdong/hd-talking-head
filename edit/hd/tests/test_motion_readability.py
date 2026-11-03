import unittest, copy, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from edit.hd.tools import motion_readability as m
from edit.hd.tools.motion_readability import validate_targets, sample_times, assess_target, validate_resolutions

class MotionReadabilityTest(unittest.TestCase):
    def setUp(self):
        self.ref={"path":"x.json","sha256":"x","pointer":"/text","value":"小字"}
        self.seg=[{"segment_id":"s","start":0,"end":2,"shot_recipe":{"components":[{"component_id":"c","kind":"material"}]}}]
        self.target={"target_id":"t","content_ref":self.ref,"span":[0,2],"role":"body","region":{"x":100,"y":100,"width":400,"height":100},"windows":[{"start":0,"end":2}]}
    def test_literal_source_reference_is_bound_without_fabricating_json_text(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / "scene.tsx"
            source = '<text>版本号</text>'; path.write_text(source)
            ref = {"path":"scene.tsx","sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                   "pointer":"text:6:9","value":"版本号"}
            target = {**self.target,"content_ref":ref,"span":[0,3]}
            validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[target]}],[],root=root)
            target["content_ref"]={**ref,"pointer":"text:0:3"}
            with self.assertRaises(ValueError):
                validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[target]}],[],root=root)

    def test_pending_generation_requires_its_exact_planning_target(self):
        row = {'segment_id': 's', 'component_id': 'c', 'pending_generation': True}
        self.assertEqual(validate_targets(self.seg, [row], [],
            pending_generation_components={('s', 'c')})[0]['status'], 'pending_generation')
        for changes in ({}, {'pending_generation': False}, {'targets': [self.target]},
                        {'no_critical_text_reason': '不能假装无字'}, {'pending_native': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_targets(self.seg, [{**row, **changes}], [],
                    pending_generation_components=() if not changes else {('s', 'c')})

    def test_direction_reading_window_excludes_avatar_transition_frames(self):
        import hashlib, json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "job-context.json").write_text("{}")
            source = root / "x.json"; source.write_text(json.dumps({"text":"小字"}))
            ref = {**self.ref, "sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
            job = SimpleNamespace(root=root, job_dir=root)
            director = {"segments":[{"segment_id":"s", "start":17.041666666666668,
                "end":25.75, "visual_strategy":{"components":[{"component_id":"c"}],
                "composition":{"presenter_mode":"bottom_window", "avatar":{
                    "entrance":{"kind":"aroll_to_avatar", "frames":12},
                    "exit":{"kind":"avatar_to_aroll", "frames":8}}}}}]}
            target = {**self.target, "content_ref":ref,
                      "windows":[{"start":7.25, "end":208/24}]}
            treatment = {"motion_readability":[{"segment_id":"s", "component_id":"c", "targets":[target]}]}
            with self.assertRaisesRegex(ValueError, "avatar transition"):
                m.validate_direction_contract(job, director, treatment)
            target["windows"][0]["end"] = 201/24
            m.validate_direction_contract(job, director, treatment)
            target["windows"] = [{"start":0, "end":1.75}]
            with self.assertRaisesRegex(ValueError, "avatar transition"):
                m.validate_direction_contract(job, director, treatment)

    def test_times_and_small_vs_large(self):
        out=validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[self.target]}],[])
        self.assertGreaterEqual(len(sample_times(out[0])),3)
        small=[{"time":x,"frame_sha256":"h","frame_path":"p","width":1080,"height":1920,"observations":[{"text":"小字","confidence":.9,"bbox":[110,110,100,20]}]} for x in sample_times(out[0])]
        self.assertEqual(assess_target(out[0],small)["status"],"fail")
        for s in small: s["observations"][0]["bbox"][3]=40
        self.assertEqual(assess_target(out[0],small)["status"],"sampled_pass")
    def test_one_bad_frame_and_review(self):
        out=validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[self.target]}],[])[0]
        ss=[{"time":x,"frame_sha256":str(i),"frame_path":"p","width":1080,"height":1920,"observations":[{"text":"小字","confidence":.9,"bbox":[110,110,100,40 if i else 20]}]} for i,x in enumerate(sample_times(out))]
        self.assertEqual(assess_target(out,ss)["status"],"fail")
    def test_symbol_inflated_line_cannot_prove_target_glyph_height(self):
        target = {**self.target, "text": "小字", "segment_id": "s", "component_id": "c"}
        for text in ("→ 小字", "• 小字"):
            samples = [{"time": t, "frame_sha256": "h", "frame_path": "p", "width": 1080,
                        "height": 1920, "observations": [{"text": text, "confidence": .99,
                        "bbox": [110, 110, 100, 45]}]} for t in sample_times(target)]
            result = assess_target(target, samples)
            self.assertEqual(result["status"], "needs_review")
            self.assertTrue(all(s["reason"] == "aggregate_non_target_text" for s in result["samples"]))
    def test_duplicate_ids_and_missing_ocr_review(self):
        with self.assertRaises(ValueError): validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[self.target,self.target]}],[])
        out=validate_targets(self.seg,[{"segment_id":"s","component_id":"c","targets":[self.target]}],[])[0]
        ss=[{"time":x,"frame_sha256":"h","frame_path":"p","width":1080,"height":1920,"observations":[]} for x in sample_times(out)]
        self.assertEqual(assess_target(out,ss)["status"],"needs_review")

    def test_missing_targets_and_empty_windows_are_not_passes(self):
        with self.assertRaises(ValueError): validate_targets(self.seg, [], [])
        target = copy.deepcopy(self.target); target["windows"] = []
        with self.assertRaises(ValueError):
            validate_targets(self.seg, [{"segment_id":"s","component_id":"c","targets":[target]}], [])

    def test_large_subtitle_cannot_replace_small_motion_text(self):
        target = {**self.target, "text":"小字", "segment_id":"s", "component_id":"c",
                  "region":{"x":0,"y":0,"width":1080,"height":1800}}
        samples = [{"time":t,"frame_sha256":"a"*64,"frame_path":"p","width":1080,"height":1920,
                    "excluded_regions":[[0,1400,1080,400]], "observations":[
                        {"text":"小字","confidence":.9,"bbox":[110,110,100,20]},
                        {"text":"小字","confidence":1,"bbox":[110,1500,400,80]}]}
                   for t in sample_times(target)]
        self.assertEqual(assess_target(target,samples)["status"],"fail")
        for sample in samples: sample["observations"].pop(0)
        self.assertEqual(assess_target(target,samples)["status"],"needs_review")

    def test_uncertain_frame_needs_measured_specific_review(self):
        target = {**self.target,"text":"小字","segment_id":"s","component_id":"c"}
        samples = [{"time":t,"frame_sha256":"a"*64,"frame_path":"p","width":1080,"height":1920,
                    "observations":[{"text":"小字","confidence":.2,"bbox":[110,110,100,40]}]}
                   for t in sample_times(target)]
        report = {"targets":[assess_target(target,samples)]}
        with self.assertRaises(ValueError): validate_resolutions(report,[])
        resolutions = [{"target_id":"t","time":t,"frame_sha256":"a"*64,"bbox":[110,110,100,40],
                        "text":"小字","reason":"原尺寸已核对完整清晰，识别置信度偏低",
                        "unclipped":True,"unobstructed":True,"contrast_clear":True,"window_reviewed":True}
                       for t in sample_times(target)]
        validate_resolutions(report,resolutions)
        altered=copy.deepcopy(resolutions); altered[0]["frame_sha256"]="b"*64
        with self.assertRaises(ValueError): validate_resolutions(report,altered)
        for sample in samples: sample["observations"][0].update(confidence=.9,bbox=[110,110,100,20])
        with self.assertRaises(ValueError): validate_resolutions({"targets":[assess_target(target,samples)]},resolutions)

    def test_delivery_consumer_rejects_bypassed_or_stale_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/"job-context.json").write_text("{}")
            (root/"manifests").mkdir()
            job=SimpleNamespace(root=root,job_dir=root,job_id="job",stages={"preview":{"artifacts":[{"sha256":"current"}]}})
            report={"binding":{"media":"new"},"targets":[{"status":"needs_review","target_id":"t","samples":[{"time":0,"status":"needs_review"}]}]}
            receipt={"job_id":"job","job_dir":str(root),"stage":"preview","reviewed_by":"host","passed":True,
                     "artifacts":job.stages["preview"]["artifacts"],"motion_readability":{"binding":{"media":"old"},"targets":[]}}
            import json
            (root/"manifests/local-qa-preview-r1.json").write_text(json.dumps(receipt))
            with mock.patch.object(m,"inspect_job",return_value=report):
                with self.assertRaises(ValueError): m.require_preview_review(job)

    def test_user_preview_still_requires_current_readability_and_visual_evidence(self):
        import json
        from edit.hd.tools import visual_review
        from edit.hd.tests.test_visual_review import VisualReviewPlanIdentityTests
        expected, review = VisualReviewPlanIdentityTests().user_preview()
        target = {'target_id': 't', 'segment_id': 's', 'component_id': 'c',
                  'text': '小字', 'status': 'needs_review',
                  'region': self.target['region'], 'minimum_required_height_px': 36,
                  'samples': [{'time': 0, 'status': 'needs_review', 'frame_sha256': 'a' * 64}]}
        report = {'binding': {'media': 'current'}, 'targets': [target]}
        resolution = {'target_id': 't', 'time': 0, 'frame_sha256': 'a' * 64,
                      'text': '小字', 'bbox': [110, 110, 100, 40],
                      'reason': '当前原尺寸帧内文字完整且清楚', 'unclipped': True,
                      'unobstructed': True, 'contrast_clear': True, 'window_reviewed': True}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'manifests').mkdir()
            import hashlib
            from PIL import Image
            frame = root / 'frame.png'; Image.new('RGB', (1080, 1920), 'white').save(frame)
            digest = hashlib.sha256(frame.read_bytes()).hexdigest()
            target['samples'][0].update(frame_path=str(frame), frame_sha256=digest)
            resolution['frame_sha256'] = digest
            records = [expected['observations'][0]['media_ref']]
            job = SimpleNamespace(job_dir=root, job_id='job',
                                  stages={'preview': {'status': 'approved', 'artifacts': records}})
            receipt = {**review, 'job_id': 'job', 'job_dir': str(root), 'stage': 'preview',
                       'passed': True, 'artifacts': records, 'motion_readability': report,
                       'motion_readability_resolutions': [resolution]}
            receipt['motion_readability_observations'] = [
                {**row, 'verdict': 'pass', 'conclusion': '当前实际帧中文字完整，未被手或指针遮挡。'}
                for row in m.observation_requirements(report)]
            path = root / 'manifests/local-qa-preview-r1.json'
            with mock.patch.object(m, '_managed', return_value=True), \
                 mock.patch.object(m, 'inspect_job', return_value=report), \
                 mock.patch.object(visual_review, 'expected_observations', return_value=expected):
                path.write_text(json.dumps(receipt)); m.require_preview_review(job)
                for changes in ({'audio_listened': False}, {'motion_readability_resolutions': []},
                                {'motion_readability': {'binding': {'media': 'stale'}, 'targets': []}}):
                    path.write_text(json.dumps({**receipt, **changes}))
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        m.require_preview_review(job)

class MotionTextObservationTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.frame = self.root / 'frame.png'
        Image.new('RGB', (1080, 1920), 'white').save(self.frame)
        self.digest = hashlib.sha256(self.frame.read_bytes()).hexdigest()
        self.sample = {'time': 0.5, 'status': 'pass', 'frame_path': str(self.frame),
                       'frame_sha256': self.digest, 'bbox': [110, 110, 100, 40], 'height': 40}
        self.report = {'targets': [{'target_id': 'text', 'segment_id': 's', 'component_id': 'c',
            'text': '周报', 'status': 'sampled_pass', 'samples': [self.sample]}]}
        self.observation = {'row_id': 's:c', 'sample_refs': [
            {'target_id': 'text', 'time': 0.5, 'frame_sha256': self.digest}],
            'verdict': 'pass', 'conclusion': '已实看当前字形，手指、光标和头像均未遮挡。'}

    def test_ocr_pass_and_pending_audio_do_not_replace_text_observation(self):
        with mock.patch.object(m, 'inspect_job', return_value=self.report):
            for review in ({}, {'user_final_review': {'status': 'pending',
                'full_playback_reviewed': False, 'audio_listened': False}}):
                with self.subTest(review=review), self.assertRaisesRegex(ValueError, 'observation'):
                    m.validate_stage_review(SimpleNamespace(), 'preview', review)

    def test_current_static_observation_keeps_full_audio_review_pending(self):
        review = {'motion_readability_observations': [self.observation],
                  'user_final_review': {'status': 'pending', 'full_playback_reviewed': False,
                                        'audio_listened': False}}
        before = copy.deepcopy(review)
        with mock.patch.object(m, 'inspect_job', return_value=self.report):
            self.assertEqual(m.validate_stage_review(SimpleNamespace(), 'preview', review), self.report)
        self.assertEqual(review, before)
        for change in (
            {'verdict': 'revise', 'conclusion': 'OCR识别成功，但手指挡住了周字。'},
            {'sample_refs': []}, {'row_id': 'other:c'}, {'conclusion': ''},
            {'sample_refs': self.observation['sample_refs'] * 2},
            {'sample_refs': [{**self.observation['sample_refs'][0], 'frame_sha256': 'b' * 64}]},
            {'sample_refs': [*self.observation['sample_refs'],
                             {**self.observation['sample_refs'][0], 'time': 0.75}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.validate_observations(self.report, [{**self.observation, **change}])

    def test_observation_verifies_actual_frame_and_no_text_needs_no_observation(self):
        m.validate_observations({'targets': [{'status': 'not_applicable'}]}, [])
        missing = copy.deepcopy(self.report); missing['targets'][0]['samples'][0].pop('frame_path')
        with self.assertRaisesRegex(ValueError, 'sample frame'):
            m.validate_observations(missing, [self.observation])
        data = self.frame.read_bytes(); self.frame.write_bytes(data + b'changed')
        with self.assertRaisesRegex(ValueError, 'frame changed'):
            m.validate_observations(self.report, [self.observation])
        import hashlib
        truncated = data[:50]; self.frame.write_bytes(truncated)
        digest = hashlib.sha256(truncated).hexdigest()
        self.sample['frame_sha256'] = digest
        self.observation['sample_refs'][0]['frame_sha256'] = digest
        with self.assertRaisesRegex(ValueError, 'frame is unavailable'):
            m.validate_observations(self.report, [self.observation])

    def test_delivery_does_not_bypass_all_ocr_passing_targets(self):
        import json
        (self.root / 'manifests').mkdir()
        records = [{'path': '11-preview/review.mp4', 'sha256': 'current', 'bytes': 1}]
        job = SimpleNamespace(root=self.root, job_dir=self.root, job_id='job',
                              stages={'preview': {'artifacts': records}})
        receipt = {'job_id': 'job', 'job_dir': str(self.root), 'stage': 'preview',
                   'reviewed_by': 'host', 'passed': True, 'artifacts': records,
                   'motion_readability': self.report, 'motion_readability_resolutions': []}
        path = self.root / 'manifests/local-qa-preview-r1.json'
        with mock.patch.object(m, '_managed', return_value=True), \
             mock.patch.object(m, 'inspect_job', return_value=self.report):
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'observation'):
                m.require_preview_review(job)
            receipt['motion_readability_observations'] = [self.observation]
            path.write_text(json.dumps(receipt)); m.require_preview_review(job)


class BatchedReadingFramesTests(unittest.TestCase):
    def test_real_batch_matches_input_seek_pixels_and_frame_numbers(self):
        import shutil,subprocess
        from PIL import Image,ImageDraw,ImageFont
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for number in range(12):
                image=Image.new('RGB',(1080,1920),(number*18,70,40))
                ImageDraw.Draw(image).text((30,30),str(number),fill='white',font=ImageFont.load_default(size=96))
                image.save(root/f'input-{number:02d}.png')
            video=root/'preview.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-framerate','24','-i',str(root/'input-%02d.png'),
                '-c:v','libx264','-preset','ultrafast','-threads','1','-pix_fmt','yuv420p',str(video)],
                check=True,capture_output=True)
            separate=root/'segment.mp4';shutil.copyfile(video,separate)
            # A shared preview has several segment bases and a cover offset.
            times=[0,.01,.02,1/24,.041667,.0625,.125,.126,11/24,.125+.041667,.25+.01,.25+.01]
            requests=[(video,t,root/f'preview-segment-{i}.png') for i,t in enumerate(times)]
            requests += [(separate,t,root/f'segment-tail-{i}.png') for i,t in enumerate((.4,.40001,11/24))]
            expected=[0,1,1,1,1,2,3,4,11,4,7,7,10,10,11]
            originals=[]
            for i,(source,seconds,_) in enumerate(requests):
                path=root/f'legacy-{i}.png'
                subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-ss',str(seconds),'-i',str(source),
                    '-frames:v','1',str(path)],check=True,capture_output=True)
                originals.append(path)
            run=subprocess.run
            with mock.patch.object(subprocess,'run',wraps=run) as actual_calls:
                m._extract_frames_batched(requests,sample_step_seconds=.125)
                self.assertEqual(sum(call.args[0][0]=='ffmpeg' for call in actual_calls.call_args_list),3)
                self.assertEqual(sum(call.args[0][0]=='ffprobe' for call in actual_calls.call_args_list),2)
                preview=[call.args[0] for call in actual_calls.call_args_list
                         if call.args[0][0]=='ffmpeg' and str(video.resolve()) in call.args[0]]
                self.assertEqual(len(preview),2)
                self.assertAlmostEqual(float(preview[1][preview[1].index('-ss')+1]),11/24)
                self.assertAlmostEqual(float(preview[1][preview[1].index('-t')+1]),1/24)
                tail=next(call.args[0] for call in actual_calls.call_args_list
                          if call.args[0][0]=='ffmpeg' and str(separate.resolve()) in call.args[0])
                self.assertAlmostEqual(float(tail[tail.index('-ss')+1]),10/24)
                self.assertAlmostEqual(float(tail[tail.index('-t')+1]),2/24)
                self.assertEqual(tail[tail.index('-frames:v')+1],'2')
            for (_,_,path),original,number in zip(requests,originals,expected):
                with self.subTest(path=path.name),Image.open(path) as batch,Image.open(original) as legacy:
                    self.assertEqual(batch.format,'PNG');self.assertEqual(batch.size,(1080,1920))
                    self.assertEqual(batch.convert('RGB').tobytes(),legacy.convert('RGB').tobytes())
                    self.assertEqual(round(batch.getpixel((1000,1900))[0]/18),number)
            self.assertEqual(requests[10][2].read_bytes(),requests[11][2].read_bytes())

    def test_report_keeps_sampling_and_cached_elapsed_without_reexecuting(self):
        import hashlib,json
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'11-preview').mkdir()
            (root/'11-preview/opening-manifest.json').write_text(json.dumps({'body_offset_frames':3,'fps':24}))
            (root/'words.json').write_text(json.dumps({'text':'小字'}))
            ref={'path':'words.json','sha256':hashlib.sha256((root/'words.json').read_bytes()).hexdigest(),
                 'pointer':'/text','value':'小字'}
            segments=[{'segment_id':sid,'start':start,'end':start+.5,
                       'shot_recipe':{'components':[{'component_id':'c','kind':'material'}]}}
                      for sid,start in [('a',0),('b',.5)]]
            target={'target_id':'t','content_ref':ref,'span':[0,2],'role':'body',
                    'region':{'x':100,'y':100,'width':400,'height':100},'windows':[{'start':0,'end':.5}]}
            treatment={'motion_readability':[{'segment_id':sid,'component_id':'c',
                'targets':[{**target,'target_id':sid}]} for sid in ('a','b')]}
            job=SimpleNamespace(job_dir=root,stages={'preview':{'artifacts':[]}})
            def extract(requests, **kwargs):
                for _,_,destination in requests:Image.new('RGB',(1080,1920),'white').save(destination)
            def ocr(paths):
                return {str(p.resolve()):{'width':1080,'height':1920,'observations':[]} for p in paths}
            with mock.patch.object(m,'_current_inputs',side_effect=lambda _:
                    ({'segments':segments},treatment,{'source':'fixture'})), \
                 mock.patch.object(m,'_published',side_effect=lambda _,stage,name:root/name), \
                 mock.patch.object(m,'_extract_frames_batched',side_effect=extract) as extraction, \
                 mock.patch.object(m,'_ocr',side_effect=ocr) as recognition:
                report=m.inspect_job(job,'preview')
                self.assertEqual(report['status'],'needs_review')
                self.assertEqual([len(t['samples']) for t in report['targets']],[len(sample_times(target))]*2)
                self.assertEqual(extraction.call_args.args[0][0][1],3/24)
                self.assertTrue(all(v>=0 for v in report['timing_seconds'].values()))
                self.assertEqual(m.inspect_job(job,'preview'),report)
                extraction.assert_called_once();recognition.assert_called_once()
                sample=report['targets'][0]['samples'][0]
                Path(sample['frame_path']).write_bytes(b'truncated PNG')
                m.inspect_job(job,'preview')
                self.assertEqual(extraction.call_count,2);self.assertEqual(recognition.call_count,2)


if __name__ == '__main__': unittest.main()

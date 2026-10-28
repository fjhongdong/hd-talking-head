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

if __name__ == '__main__': unittest.main()

"""Native task and reviewed media contracts; no paid calls or permanent Jobs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import _env
import motion_native_skill_adapter as native


def brief(dependency='barty-motion-graphics', template='motion-broll', alpha=False):
    return {'schema_version':1,'dependency_id':dependency,'job_id':'native-test',
            'source_binding':{'aroll_sha256':'a'*64,'segment_id':'seg-001','start':0,'end':2},
            'composition':{'width':1080,'height':1920,'fps':24,'frames':48},'alpha':alpha,
            'canvas_transport':'quarter_turn_cw' if dependency=='bang-motion' else 'identity',
            'template_request':{'semantic_family':'comparison','information_units':2,'numeric_values':[],'numeric_scale':'not_applicable'},
            'template_id':template,'semantic_goal':'比较两种结果','transcript':'先看输入，再看输出。',
            'word_anchors':[{'text':'先看输入，再看输出。','start':0,'end':2}],
            'speech':{'job_path':'voice.wav','sha256':hashlib.sha256(b'voice').hexdigest(),'byte_count':5},
            'materials':[],'authorization':{'paid_generation':False},
            'project_directory':'native-projects/native-test','result_record_path':'native-inputs/native-test/result.json'}


class NativeMotionTests(unittest.TestCase):
    def test_complete_original_sources_and_native_workflow_paths(self):
        for dependency, count in [('barty-motion-graphics',4),('bang-motion',35)]:
            source = native.source_root(_env.PROJECT, dependency_id=dependency)
            rows = native.load_template_catalog(_env.PROJECT, dependency_id=dependency)
            self.assertEqual(len(rows),count)
            self.assertTrue(all((_env.PROJECT / row['skill_path']).is_file() for row in rows))
        for template in sorted(native.BARTY_TEMPLATES - {'motion-broll'}):
            renderer=native.embedded_renderer(native.source_root(dependency_id='barty-motion-graphics')/'skills'/template/'SKILL.md')
            self.assertTrue(renderer.startswith(b'// render.mjs:'))
            self.assertIn(b"from 'playwright'",renderer)

    def test_exact_clock_alpha_and_whole_board_transport(self):
        b=brief();self.assertEqual(native.validate_brief(json.dumps(b)),b)
        b['composition']['frames']=47
        with self.assertRaisesRegex(ValueError,'clock'):native.validate_brief(json.dumps(b))
        for dependency,template in [('barty-motion-graphics','explainer-default'),('bang-motion','style-cinematic-dark')]:
            with self.assertRaisesRegex(ValueError,'transparent'):native.validate_brief(json.dumps(brief(dependency,template,True)))
        b=brief('bang-motion','style-cinematic-dark');b['canvas_transport']='identity'
        with self.assertRaisesRegex(ValueError,'canvas transport'):native.validate_brief(json.dumps(b))

    def test_native_task_passes_content_without_parent_composition(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'brief.json';p.write_text(json.dumps(brief()))
            job=SimpleNamespace(job_dir=root,job_id='native-test')
            with mock.patch.object(native,'_inputs'),mock.patch('motion_native_runtime.check',return_value={'status':'ready'}):
                action=native.native_task(job,{'segment_id':'seg-001'},{'component_id':'scene','brief_sha256':native.sha(p)},p)
            self.assertEqual(action['action'],'execute_native_skill')
            self.assertEqual(action['requirements']['transcript'],brief()['transcript'])
            self.assertFalse(set(action['requirements']) & {'beats','layers','design_plan','keyframes','layout'})
            self.assertTrue(action['skill_path'].endswith('/skills/motion-broll/SKILL.md'))

    def test_capture_requires_exact_original_embedded_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);b=brief(template='explainer-default');project=root/b['project_directory'];project.mkdir(parents=True)
            (project/'page.html').write_text('<html></html>');(project/'render.mjs').write_text('not the original renderer')
            runtime={'tools':{'node':'/usr/bin/node'},'node_modules':str(root/'modules')}
            with self.assertRaisesRegex(ValueError,'verbatim original'):
                native._render_command(root,b,['/usr/bin/node',str(project/'render.mjs'),'page.html','out/native.mp4','24'],runtime)

    def test_native_video_inputs_are_frozen_separately_from_render_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();project=root/'native-projects/scene';(project/'assets').mkdir(parents=True)
            source=project/'assets/source.mp4';source.write_bytes(b'input footage')
            (project/'out').mkdir();(project/'out/native.mp4').write_bytes(b'rendered output')
            files=native.project_files(root,project)
            self.assertEqual([r['job_path'] for r in files],['native-projects/scene/assets/source.mp4'])
            source.write_bytes(b'changed input footage')
            with self.assertRaisesRegex(ValueError,'changed'):native.exact(root,files[0])

    def test_reviewed_record_and_actual_media_must_both_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/brief()['result_record_path'];p.parent.mkdir(parents=True);p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'reviewed version'):
                native.load_result(root,json.dumps(brief()),expected_record={'path':brief()['result_record_path'],'sha256':'a'*64,'bytes':2},expected_renderer_version='playwright-1.64.0')
            media=root/'media.mp4';media.write_bytes(b'reviewed video');record=native.descriptor(root,media)
            media.write_bytes(b'replaced video')
            with self.assertRaisesRegex(ValueError,'changed'):native.exact(root,record)

    def test_overlay_planning_does_not_require_a_future_result_but_final_check_does(self):
        from types import SimpleNamespace
        from edit.hd.tools import overlay_alignment, contract_artifacts as artifacts
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();b=brief(alpha=True)
            request=root/'native-inputs/brief.json';request.parent.mkdir();artifacts.write_json_artifact(request,b)
            words=root/'words.json';artifacts.write_json_artifact(words,{'words':b['word_anchors']})
            timeline=root/'timeline.json';artifacts.write_json_artifact(timeline,{'segments':[
                {'source_start':0,'source_end':2,'timeline_start':0,'timeline_end':2}]})
            binding={'dependency_id':'barty-motion-graphics','entrypoint':native.ENTRY,'producer_version':native.VERSION,
                     'template_id':'barty-motion-graphics/motion-broll','brief_sha256':native.sha(request)}
            draft={'segments':[{'segment_id':'seg-001','start':0,'end':2,'bindings':{'scene':binding},
                               'visual_strategy':{'composition':{'family':'aroll_with_overlay'}}}]}
            treatment=root/'treatment.json';artifacts.write_json_artifact(treatment,{'overlay_alignment':[
                {'segment_id':'seg-001','component_id':'scene','brief_path':'native-inputs/brief.json'}]})
            def approved(job,stage,name):
                return (words if stage=='speech_cleanup' else timeline, 'a'*64)
            with mock.patch.object(overlay_alignment,'_approved',side_effect=approved), \
                 mock.patch.object(native,'inspect_result',side_effect=FileNotFoundError('future result')) as inspect:
                result=overlay_alignment.validate_treatment(SimpleNamespace(job_dir=root),draft,treatment,phase='planning')
                self.assertEqual(result[0]['phase'],'planning');inspect.assert_not_called()
                with self.assertRaises(FileNotFoundError):
                    overlay_alignment.validate_treatment(SimpleNamespace(job_dir=root),draft,treatment)


if __name__=='__main__':unittest.main()

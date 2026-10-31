from __future__ import annotations

import hashlib
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import _env  # noqa: F401

from edit.hd.tools import broll_component_executor as executor
import broll_capability_router as router
import generated_media
from edit.hd.tests.test_broll_capability_router import (
    _compile_context,
    _strategy_component,
    _visual_strategy,
)
from edit.hd.tests.test_broll_component_executor import _Job
from lovart_existing_video_adapter import create_artifact_probe
from edit.hd.tools import visual_canary


class GeneratedMediaPublicSmoke(unittest.TestCase):
    def _camera_fixture(self, root):
        from edit.hd.tests.test_visual_direction import draft_segment
        from edit.hd.tools import contract_artifacts as a
        media=root/'source.mp4';media.write_bytes(b'original source fixture')
        record=self._complete_record(root,media.name,media.read_bytes())
        segment=draft_segment(('ai_generated',),segment_id='seg',start=0,end=2)
        component=segment['visual_strategy']['components'][0]
        component.update(component_id='ai',media_type='video',layout_slot='full_frame')
        segment['visual_strategy']['composition']['reading_order']=['ai']
        original=copy.deepcopy(record['media'])
        data={'schema_version':1,'segment_id':'seg','component_id':'ai','source_binding':record['source_binding'],
            'source_media':original,'normalized_media':original,'source_frames':[0,48],
            'path':[{'frame':n,'x':0,'y':0,'width':1080,'height':1920} for n in range(48)],
            'reason':'Keep the existing calendar as the focus without changing its pixels'}
        path=root/'framing.json';a.write_json_artifact(path,data)
        descriptor={'job_path':path.name,'sha256':a.sha256_file(path),'byte_count':path.stat().st_size}
        record['qa']['scope']='framing_source'
        record['camera_source']={'source_qa':{'passed':False,'observed_scene':'Original focus remains on the mouth'},'framing':descriptor}
        record['generation']['request_id']='generation'
        segment['bindings']={'ai':generated_media.prepare_binding(record)}
        return segment,record,data,original

    def test_camera_scope_preserves_provider_identity_and_rejects_missing_parent_framing(self):
        from edit.hd.tools import parent_camera_framing as camera
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();segment,record,data,original=self._camera_fixture(root)
            job=SimpleNamespace(job_dir=root,job_id='job')
            with patch.object(generated_media,'_queue_media',return_value=original), \
                 patch.object(generated_media,'_validate_base_queue_identity'):
                generated_media.validate_record(record,job)
                generated_media.validate_camera_source(job,record,segment)
                self.assertEqual(camera.load(root,segment,'ai'),data)
                binding=segment['bindings']['ai']
                self.assertEqual(binding['sha256'],record['media']['sha256'])
                self.assertEqual(binding['generation_id'],'generation')
                del segment['bindings']['ai'][camera.FIELD]
                with self.assertRaisesRegex(ValueError,'mandatory parent framing'):
                    generated_media.validate_camera_source(job,record,segment)
            record['qa'].pop('scope')
            with self.assertRaisesRegex(ValueError,'separately bound parent framing'):
                generated_media.prepare_binding(record)

    def test_camera_rectangles_cannot_change_clock_fill_outside_source_or_distort(self):
        from edit.hd.tools import parent_camera_framing as camera
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();segment,record,data,_=self._camera_fixture(root)
            for change in ('clock','order','outside','shape','nan'):
                wrong=copy.deepcopy(data)
                if change=='clock':wrong['source_frames']=[1,49]
                if change=='order':wrong['path'][0]['frame']=1
                if change=='outside':wrong['path'][0]['x']=1
                if change=='shape':wrong['path'][0]['height']=1800
                if change=='nan':wrong['path'][0]['width']=float('nan')
                with self.subTest(change=change),self.assertRaises(ValueError):
                    camera.validate_manifest(wrong,segment,'ai',media_sha256=record['media']['sha256'])
            graph=camera.filter_chain(data)
            self.assertIn(':d=1:s=1080x1920:fps=24',graph)
            self.assertNotIn('pad',graph);self.assertNotIn('tpad',graph)
            (root/'source.mp4').write_bytes(b'changed source')
            with self.assertRaises(ValueError):camera.load(root,segment,'ai')

    def test_camera_expression_renders_longer_than_libavutil_linear_nesting_limit(self):
        from edit.hd.tools import parent_camera_framing as camera
        data = {'path': [{'x': 0, 'y': 0, 'width': 1080 - frame, 'height': (1080 - frame) * 16 / 9}
                         for frame in range(104)]}
        graph = camera.filter_chain(data).replace('s=1080x1920', 's=16x16')
        result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-f', 'lavfi',
                                 '-i', 'color=s=16x16:r=24', '-vf', graph, '-frames:v', '104',
                                 '-f', 'framehash', '-'], capture_output=True, check=True)
        frames = [line for line in result.stdout.decode().splitlines() if not line.startswith('#')]
        self.assertEqual(len(frames), 104)

    def test_compiler_consumes_camera_descriptor_without_replacing_media_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();segment,record,_,_=self._camera_fixture(root)
            component=_strategy_component('ai','ai_generated',layout_slot='full_frame');component['media_type']='video'
            recipe=router.compile_strategy(_visual_strategy([component],segment_id='seg-router'),
                _compile_context([component],segment_frames=48,binding_overrides={'ai':segment['bindings']['ai']}))
            self.assertNotIn('parent_camera_framing',recipe['components'][0])
            self.assertEqual(recipe['components'][0]['sha256'],record['media']['sha256'])
            self.assertEqual(recipe['components'][0]['generation_id'],'generation')

    def test_symlink_cannot_bind_media_outside_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / 'job'
            job_dir.mkdir()
            external = root / 'outside.mp4'
            external.write_bytes(b'outside content')
            (job_dir / 'link.mp4').symlink_to(external)
            record = self._complete_record(job_dir, 'link.mp4', external.read_bytes())
            with self.assertRaisesRegex(ValueError, 'path or bytes'):
                generated_media.create_adapter(SimpleNamespace(job_dir=job_dir, job_id='job'), record)

    def _complete_record(self, job_dir, name, data):
        record = self._binding_record()
        record.update(schema_version=1, job_id='job', segment_id='seg', component_id='ai',
                      generation={}, qa={'passed': True, 'observed_scene': 'observed'})
        record['media'].update(job_path=name, sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data))
        return record

    def test_media_source_window_must_match_current_approved_aroll(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'media.mp4'
            source.write_bytes(b'known local media')
            job = SimpleNamespace(job_dir=root, job_id='job')
            record = self._complete_record(root, source.name, source.read_bytes())
            adapter = generated_media.create_adapter(job, record)
            component = {'kind': 'ai_generated', **generated_media.prepare_binding(record)}
            recipe = {'components': [component]}
            context = SimpleNamespace(job_id='job', segment_id='seg', component_id='ai',
                component=component, recipe=recipe, staging_path=root / 'output.mp4')
            segment = {'segment_id': 'seg', 'start': 0, 'end': 2, 'shot_recipe': recipe}
            with patch.object(visual_canary, 'load_approved_visual_plan', return_value={'segments': [segment]}), \
                 patch.object(visual_canary, 'approved_aroll_record', return_value={'sha256': 'd' * 64}):
                with self.assertRaisesRegex(ValueError, 'source window mismatch'):
                    adapter.invoke(context)
            self.assertFalse(context.staging_path.exists())

    def _binding_record(self):
        return {
            "status": "completed", "provider": "fixture", "model": "model",
            "endpoint_id": "endpoint", "generation_id": "generation",
            "prompt_sha256": "a" * 64,
            "media": {"sha256": "b" * 64, "media_type": "video"},
            "semantic_brief": {"observed_scene": "observed"},
            "source_binding": {"aroll_sha256": "c" * 64, "start": 0, "end": 2},
            "source_dimensions": {"width": 1080, "height": 1920},
        }

    def test_prepare_binding_rejects_missing_observed_scene(self):
        record = self._binding_record()
        del record["semantic_brief"]["observed_scene"]
        with self.assertRaisesRegex(ValueError, "observed scene"):
            generated_media.prepare_binding(record)

    def test_prepare_binding_rejects_extra_source_binding_field(self):
        record = self._binding_record()
        record["source_binding"]["segment_id"] = "seg"
        with self.assertRaisesRegex(ValueError, "source binding"):
            generated_media.prepare_binding(record)

    def test_prepare_binding_rejects_invalid_source_clock(self):
        record = self._binding_record()
        record["source_binding"]["end"] = 0
        with self.assertRaisesRegex(ValueError, "clock"):
            generated_media.prepare_binding(record)

    def test_prepare_binding_accepts_observed_scene_and_source_binding(self):
        binding = generated_media.prepare_binding(self._binding_record())
        self.assertEqual(binding["source_dimensions"], {"width": 1080, "height": 1920})

    def test_compiler_retains_media_identity_with_parent_static_labels(self):
        binding = generated_media.prepare_binding(self._binding_record())
        binding['parent_static_labels'] = {'job_path': 'labels.json', 'sha256': 'd' * 64, 'byte_count': 100}
        component = _strategy_component('ai', 'ai_generated', layout_slot='full_frame')
        component['media_type'] = 'video'
        recipe = router.compile_strategy(_visual_strategy([component], segment_id='seg-router'),
            _compile_context([component], segment_frames=48, binding_overrides={'ai': binding}))
        self.assertNotIn('parent_static_labels', recipe['components'][0])
        self.assertEqual(recipe['components'][0]['sha256'], self._binding_record()['media']['sha256'])
        self.assertEqual(recipe['components'][0]['executor'], 'generated_media')

    def test_validate_record_preserves_approved_request_reference(self):
        from edit.hd.tools import visual_confirmation as vc, broll_skill_selection as selection
        from edit.hd.tools import contract_artifacts as a
        import copy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'manifests').mkdir()
            job = SimpleNamespace(job_id='job', job_dir=root)
            provider = {"purpose":"video", "provider":"fixture", "model":"model",
                "endpoint_id":"endpoint", "connection_status":"verified", "quota_status":"available",
                "reference_images":True, "native_9_16":True, "silent_output":True}
            config = root / 'manifests/provider-config.json'
            a.write_json_artifact(config, {"schema_version":1,"generation_enabled":True,
                "max_concurrency":1,"providers":[provider]})
            a.write_json_artifact(root / 'manifests/generation-channels.json',
                {"video":{"model_binding":{"mode":"fixed"}}})
            a.write_json_artifact(root / 'workflow.json', {"job_id":"job"})
            spec = root / 'TREATMENT.md'; spec.write_text('Original creative workflow.')
            step = {"id":"video", "purpose":"video", "segment_id":"seg", "component_id":"ai",
                "arguments":{"prompt":"assemble paper objects"}, "input_files":[vc._record(root,spec)]}
            assignment = {"segment_id":"seg", "component_id":"ai", "skill_id":"gbro-collage-broll",
                "template_id":"gbro-collage-broll/design", "candidate_id":"gbro-collage-broll:design"}
            treatment = root / 'treatment.json'
            a.write_json_artifact(treatment, {"skill_selection":{"assignments":[assignment]}})
            director = root / 'director.json'; a.write_json_artifact(director,{})
            proposal = {"job_id":"job", "kind":vc.SCHEMA, "source_id":"fixture",
                "inputs":{"treatment":vc._record(root,treatment),"director":vc._record(root,director)},
                "provider_config_sha256":a.sha256_file(config), "generation_steps":[step]}
            proposal_path = root / 'proposal.json'; a.write_json_artifact(proposal_path,proposal)
            receipt = {"source_schema":vc.SCHEMA,"job_id":"job","job_dir":str(root),
                "stage":"visual_direction","passed":True,"reviewed_by":"human",
                "approval_scope":"visual_plan_and_delivery","note":"synthetic local test",
                "user_confirmation":"fixture only", "artifacts":[],"source":vc._record(root,proposal_path)}
            receipt_path = root / 'receipt.json'; a.write_json_artifact(receipt_path,receipt)
            request = vc._build_generation_request(job,proposal,step)
            authorization = {"source":vc._record(root,receipt_path), "steps":{request['id']:'video'}}
            record = self._complete_record(root,'generated.mp4',b'fixture bytes')
            (root / 'generated.mp4').write_bytes(b'fixture bytes')
            record['generation'] = {"approved_plan":authorization,"approved_request":request,
                "approved_request_id":request['id'],"submitted_request":request}
            record['prompt_sha256'] = a.sha256_json(request['arguments'])
            checked = generated_media.validate_record(record,job)
            self.assertEqual(checked['generation']['approved_request_id'],request['id'])
            identity = selection.approved_creative_identity(job,record['generation'],segment_id='seg',component_id='ai')
            self.assertEqual(identity['skill_id'],'gbro-collage-broll')
            record_path = root / 'completed.json'; a.write_json_artifact(record_path,record)
            fixed = {**identity, 'segment_id':'seg','component_id':'ai', 'completed_record':{'job_path':record_path.name,
                'sha256':a.sha256_file(record_path),'byte_count':record_path.stat().st_size}}
            self.assertEqual(selection.fixed_identity(fixed,job_dir=root),identity)
            wrong = {**fixed,'component_id':'other'}
            with self.assertRaisesRegex(ValueError,'another visual item'):
                selection.fixed_identity(wrong,job_dir=root)
            fixed.update(segment_id='seg',component_id='ai',start=0,end=2)
            binding = generated_media.prepare_binding(record)
            draft = {'segments':[{'segment_id':'seg','start':0,'end':2,
                'visual_strategy':{'components':[{'component_id':'ai','kind':'ai_generated'}]},
                'bindings':{'ai':binding}}]}
            selection.validate_fixed_materials(draft,{'fixed_context':[fixed]},job_dir=root)
            binding['provider']='another-service'
            with self.assertRaisesRegex(ValueError,'completed result'):
                selection.validate_fixed_materials(draft,{'fixed_context':[fixed]},job_dir=root)
            binding['provider']='fixture'
            (root/'generated.mp4').write_bytes(b'changed result')
            with self.assertRaisesRegex(ValueError,'media changed'):
                selection.fixed_identity(fixed,job_dir=root)
            (root/'generated.mp4').write_bytes(b'fixture bytes')
            altered = copy.deepcopy(record); altered['component_id']='other'
            with self.assertRaisesRegex(ValueError,'another approved visual'):
                generated_media.validate_record(altered,job)
            altered = copy.deepcopy(record); altered['generation']['approved_request']['arguments']['prompt']='another theme'
            with self.assertRaisesRegex(ValueError,'approved step'):
                generated_media.validate_record(altered,job)
            spec.write_text('Different workflow.')
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                generated_media.validate_record(record,job)
            spec.write_text('Original creative workflow.')
            a.write_json_artifact(treatment,{'skill_selection':{'assignments':[]}})
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                generated_media.validate_record(record,job)

    def test_validate_record_rejects_invalid_approved_request_reference(self):
        record = self._binding_record()
        record.update(schema_version=1, job_id='job', segment_id='seg', component_id='ai',
                      generation={"approved_request_id": "", "approved_plan": {}, "approved_request": {}},
                      qa={"passed": True, "observed_scene": "observed"})
        record["media"].update(job_path="generated.mp4", byte_count=1)
        with self.assertRaisesRegex(ValueError, "approved request identity"):
            generated_media.validate_record(record, SimpleNamespace(job_id='job'))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_actual_media_record_compiles_and_runs_public_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = _Job(root)
            media_path = job.job_dir / "generated.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
                 "-i", "color=c=blue:s=1080x1920:r=24:d=2", "-frames:v", "48", "-an",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(media_path)],
                check=True, capture_output=True,
            )
            media_sha = hashlib.sha256(media_path.read_bytes()).hexdigest()
            prompt_sha = hashlib.sha256(b"a blue vertical explanatory scene").hexdigest()
            record = {
                "schema_version": 1, "status": "completed", "job_id": job.job_id,
                "segment_id": "seg-router", "component_id": "ai",
                "provider": "fixture-provider", "model": "fixture-video",
                "endpoint_id": "fixture-video-endpoint", "generation_id": "generation-001",
                "prompt_sha256": prompt_sha,
                "media": {"job_path": "generated.mp4", "sha256": media_sha,
                          "byte_count": media_path.stat().st_size, "media_type": "video"},
                "generation": {"request_id": "generation-001", "task_ids": ["task-001"]},
                "qa": {"passed": True, "observed_scene": "solid blue vertical scene"},
                "semantic_brief": {"observed_scene": "solid blue vertical scene"},
                "source_binding": {"aroll_sha256": "a" * 64, "start": 0, "end": 2},
                "source_dimensions": {"width": 1080, "height": 1920},
            }
            binding = generated_media.prepare_binding(record)
            self.assertEqual(binding["source_dimensions"], {"width": 1080, "height": 1920})

            component = _strategy_component("ai", "ai_generated", layout_slot="full_frame")
            component["media_type"] = "video"
            strategy = _visual_strategy([component], segment_id="seg-router")
            context = _compile_context([component], segment_frames=48, binding_overrides={"ai": binding})
            recipe = router.compile_strategy(strategy, context)
            self.assertEqual(recipe["components"][0]["executor"], "generated_media")

            adapters = generated_media.create_job_adapter(job, [record])
            probe = create_artifact_probe(shutil.which("ffprobe"))
            segment = {"segment_id": "seg-router", "start": 0, "end": 2, "shot_recipe": recipe}
            with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": [segment]}), \
                 patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": "a" * 64}):
                artifact = executor.execute_component(
                    job, executor.ComponentExecutionRequest(recipe, "ai"),
                    adapters={"ai_generated": adapters, "artifact_probe": probe},
                )
            self.assertEqual(artifact.output_sha256, media_sha)
            self.assertEqual(artifact.media_probe["width"], 1080)
            self.assertEqual(artifact.media_probe["height"], 1920)
            self.assertEqual(artifact.invocation_evidence["adapter_record"]["external_requests"], 0)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class CompositionBaseReuseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.job = _Job(self.root)
        self.manifests = self.job.job_dir / 'manifests'
        self.manifests.mkdir()
        (self.manifests / 'generation-channels.json').write_text(json.dumps({'video': {'reference_mode': 'local_path'}}))
        self.source_binding = {'aroll_sha256': 'a' * 64, 'start': 0, 'end': 1}

    def source(self, height):
        from edit.hd.tools import generation_queue
        path = self.job.job_dir / 'original.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi',
            '-i', f'testsrc2=s=1080x{height}:r=24:d=1', '-an', '-vf', 'setsar=0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-bsf:v', 'h264_metadata=sample_aspect_ratio=0/1', '-n', str(path)], check=True, capture_output=True)
        request = {'id': 'generated', 'purpose': 'video', 'arguments': {'prompt': 'synthetic test only'}, 'input_files': []}
        item = {'status': 'completed', 'request': request, 'submitted_request': request,
            'fingerprint': generation_queue._fingerprint(request), 'task_ids': ['actual-fixture-task'],
            'channel_identity': {'provider': 'fixture', 'model': 'model', 'endpoint_id': 'endpoint'},
            'completion_response': {'status': 'completed', 'artifacts': [{'type': 'video', 'path': str(path),
                'sha256': generated_media._sha(path), 'bytes': path.stat().st_size}]}}
        queue = {'schema_version': 1, 'job_dir': str(self.job.job_dir), 'items': {'generated': item}}
        self.queue_path = self.manifests / 'generation-queue.json'
        self.queue_path.write_text(json.dumps(queue))
        self.queue_bytes = self.queue_path.read_bytes()
        self.assertIsNone(generated_media._base_probe(path, 'ffprobe')['sar'])
        return path

    def normalized_record(self):
        normalization = generated_media.normalize_composition_base(self.job, 'generated',
            output_path='normalized.mp4', ffprobe_executable='ffprobe', ffmpeg_executable='ffmpeg')
        record = generated_media.record_from_queue(self.job, 'generated', segment_id='seg-001', component_id='ai',
            source_binding=self.source_binding,
            qa={'scope': 'composition_base', 'passed': True, 'observed_scene': 'Usable illustrative background only.'},
            semantic_brief={'observed_scene': 'Original action failed; background only; separate native action required.'},
            composition_base={'source_qa': {'passed': False, 'observed_scene': 'The required original action is incomplete.'},
                              'action_component_id': 'action'}, normalization=normalization,
            ffprobe_executable='ffprobe', ffmpeg_executable='ffmpeg')
        return record

    def recipe(self, record):
        from edit.hd.tests.test_broll_component_executor import _code_component
        from edit.hd.tests import test_segment_render_components as media_fixture
        base = media_fixture._component('ai', 'ai_generated', record['media']['sha256'],
            window=media_fixture._window(start=0, end=24, z_index=0, slot='full_frame'), alpha=False)
        base['media_type'] = 'video'
        binding = generated_media.prepare_binding(record)
        base.update({k: v for k, v in binding.items() if k not in {'execution_mode', 'source_dimensions'}})
        base['executor'] = generated_media.EXECUTOR
        action = _code_component(b'actual fixture dependency input', component_id='action')
        action['layer_role'] = 'annotation'
        action['render_window'] = media_fixture._window(start=0, end=24, z_index=10, slot='annotation')
        recipe = media_fixture._recipe([base, action])
        recipe['composition']['presenter_mode'] = 'hidden'
        recipe['composition'].pop('avatar')
        return recipe

    def test_scoped_base_normalizes_only_tiny_rounding_or_missing_sar(self):
        for height in (1916, 1920):
            with self.subTest(height=height):
                # Each case has independent immutable queue and source files.
                original = self.source(height)
                before = original.read_bytes()
                record = self.normalized_record()
                transform = record['normalization']['transform']
                self.assertEqual(transform['codec'], 'libx264' if height == 1916 else 'copy')
                self.assertEqual(record['source_dimensions'], {'width': 1080, 'height': 1920})
                self.assertFalse(record['composition_base']['source_qa']['passed'])
                self.assertEqual(original.read_bytes(), before)
                self.assertEqual(self.queue_path.read_bytes(), self.queue_bytes)
                for altered_height in (1900, 1930):
                    with self.assertRaisesRegex(ValueError, 'rounding'):
                        generated_media._base_transform({'width': 1080, 'height': altered_height})
                # Prepare the second independent case without retaining temporary test outputs.
                if height == 1916:
                    (self.job.job_dir / 'normalized.mp4').unlink()
                    original.unlink()

    def test_scoped_base_rejects_standalone_evidence_wrong_dependency_and_changed_pixels(self):
        self.source(1916)
        record = self.normalized_record()
        recipe = self.recipe(record)
        generated_media.validate_composition_base(record, recipe)
        for change in ('standalone', 'evidence', 'dependency', 'opaque', 'source_qa'):
            altered, bound = copy.deepcopy(recipe), copy.deepcopy(record)
            if change == 'standalone':
                altered.update(mode='single', components=altered['components'][:1])
                altered['composition'].update(family='single_full_frame', reading_order=['ai'], component_dependencies=[])
            elif change == 'evidence': altered['components'][0]['semantic_role'] = 'evidence'
            elif change == 'dependency': altered['composition']['component_dependencies'] = []
            elif change == 'opaque': altered['components'][1]['artifact_contract']['alpha'] = False
            else: bound['composition_base']['source_qa']['passed'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                generated_media.validate_composition_base(bound, altered)
        wrong = copy.deepcopy(record['normalization'])
        wrong['frame_md5_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pixels or timestamps'):
            generated_media._verify_base_normalization(self.job, wrong, 'ffprobe', 'ffmpeg')
        wrong = copy.deepcopy(record)
        wrong['model'] = 'a different generation model'
        with self.assertRaisesRegex(ValueError, 'generation identity'):
            generated_media.validate_record(wrong, self.job)
        altered_path = self.job.job_dir / 'altered-pixels.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.job.job_dir / 'normalized.mp4'),
            '-vf', 'drawbox=x=100:y=100:w=20:h=20:color=red:t=fill', '-c:v', 'libx264', '-qp', '0',
            '-pix_fmt', 'yuv420p', '-an', '-n', str(altered_path)], check=True, capture_output=True)
        wrong = copy.deepcopy(record['normalization'])
        wrong['output'].update(job_path=altered_path.name, sha256=generated_media._sha(altered_path),
                               byte_count=altered_path.stat().st_size)
        wrong['output_probe'] = generated_media._base_probe(altered_path, 'ffprobe')
        wrong['command'][-1] = str(altered_path)
        with self.assertRaisesRegex(ValueError, 'pixels or timestamps'):
            generated_media._verify_base_normalization(self.job, wrong, 'ffprobe', 'ffmpeg')
        (self.job.job_dir / 'original.mp4').write_bytes(b'changed provider output')
        with self.assertRaisesRegex(ValueError, 'path or bytes'):
            generated_media.validate_record(record, self.job)

    def test_scoped_base_runs_actual_component_and_composition_without_external_calls(self):
        from PIL import Image, ImageDraw
        from edit.hd.tests import test_segment_render_components as media_fixture
        from edit.hd.tests.test_broll_component_executor import ComponentExecutorDispatchTests, _artifact_probe
        from edit.hd.tools import segment_render
        self.source(1916)
        record = self.normalized_record()
        recipe = self.recipe(record)
        segment = media_fixture._segment(recipe)
        source = self.job.job_dir / 'aroll.mp4'
        shutil.copyfile(self.job.job_dir / 'normalized.mp4', source)
        # This is an explicitly synthetic native-process fixture, not production choreography.
        overlay = self.job.job_dir / 'overlay.png'
        picture = Image.new('RGBA', (1080, 1920))
        ImageDraw.Draw(picture).rectangle((100, 200, 400, 400), fill=(255, 0, 0, 255))
        picture.save(overlay)
        fixture = ComponentExecutorDispatchTests()
        fixture.root = self.root
        native = fixture._working_code_adapter(b'actual fixture dependency input', overlay.read_bytes())
        from dataclasses import replace
        native = replace(native, artifact_media_type='image')
        adapter = generated_media.create_adapter(self.job, record)
        with patch.object(visual_canary, 'load_approved_visual_plan', return_value={'segments': [segment]}), \
             patch.object(visual_canary, 'approved_aroll_record', return_value={'sha256': 'a' * 64}):
            base = executor.execute_component(self.job, executor.ComponentExecutionRequest(recipe, 'ai'),
                adapters={'ai_generated': adapter, 'artifact_probe': create_artifact_probe(shutil.which('ffprobe'))})
            action = executor.execute_component(self.job, executor.ComponentExecutionRequest(recipe, 'action'),
                adapters={'code_generated': {'html-video': native}, 'artifact_probe': _artifact_probe()})
        rendered = segment_render.render_segment_video(self.job, segment, (base, action),
            output_dir=self.job.job_dir / 'composition', visual_plan_sha256='b' * 64,
            arroll_source=source, arroll_sha256=generated_media._sha(source), arroll_bytes=source.stat().st_size)
        self.assertEqual(rendered.frames, 24)
        self.assertEqual(base.output_sha256, record['media']['sha256'])
        self.assertEqual(base.invocation_evidence['adapter_record']['external_requests'], 0)
        self.assertFalse(base.invocation_evidence['adapter_record']['composition_base']['source_qa']['passed'])
        self.assertEqual(self.queue_path.read_bytes(), self.queue_bytes)
        still = subprocess.run(['ffmpeg', '-v', 'error', '-i', rendered.video_path,
            '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
        import io
        with Image.open(io.BytesIO(still)) as final:
            red, green, blue = final.convert('RGB').getpixel((250, 300))
            self.assertGreater(red, 200)
            self.assertLess(green + blue, 40)


if __name__ == "__main__":
    unittest.main()

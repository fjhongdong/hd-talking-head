from __future__ import annotations

import hashlib
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


if __name__ == "__main__":
    unittest.main()

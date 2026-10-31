from __future__ import annotations

import copy
import contextlib
import io
import json
import multiprocessing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import contract_artifacts as artifacts, generation_queue as queue


def _claim_worker(job, request_id, config, start, results):
    # Only the already-tested startup gate is a fixture; file locking is real.
    with mock.patch.object(queue, "_approved", return_value=("synthetic", "config", config)):
        start.wait()
        results.put(queue.claim(job, request_id, 10))


def _retry_worker(job, plan, config, approval, start, results):
    with mock.patch.object(queue, "_approved", return_value=("synthetic", "config", config)):
        start.wait()
        result = queue.retry(job, plan, approval, artifacts.sha256_json(plan))
        results.put({"retry": result, "claim": queue.claim(job, result["id"], 10)})


class GenerationQueueTests(unittest.TestCase):
    def _generated_upload(self, *, metadata_bytes=3_200_000, padding="", noise=False):
        from PIL import Image, PngImagePlugin
        import random
        source = self.job / "generated.png"
        image = (Image.frombytes("RGB", (1100, 1100), random.Random(7).randbytes(1100 * 1100 * 3))
                 if noise else Image.new("RGB", (32, 32), "#4a718c"))
        info = PngImagePlugin.PngInfo()
        info.add_text("Description", "x" * metadata_bytes)
        image.save(source, pnginfo=info, compress_level=0)
        ref = {"path": source.name, "sha256": artifacts.sha256_file(source), "bytes": source.stat().st_size}
        bindings = artifacts.read_json_artifact(self.job / "manifests/generation-channels.json")
        bindings["video"].update(reference_mode="upload", upload={
            "tool": "mcp__lovart__upload_asset", "result_path": ["url"],
            "arguments": {"data_base64": {"$input": "base64"}, "filename": {"$input": "filename"},
                          "project_id": "synthetic-project", "padding": padding}})
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", bindings)
        request = self.request("upload-video", "video")
        request["arguments"]["first_frame"] = str(source)
        request["input_files"] = [ref]
        self.add(self.request("source-image"), request)
        claim = queue.claim(self.job, "source-image")
        queue.record(self.job, "source-image", claim["claim_token"], {"status": "completed", "artifacts": [
            {"type": "image", "path": str(source), "sha256": ref["sha256"], "bytes": ref["bytes"]}]})
        return source, request, bindings["video"], ref

    def test_lovart_upload_preflights_full_json_and_keeps_png_pixels(self):
        import base64
        from PIL import Image
        from edit.hd.tools import generation_inputs as inputs
        source, request, binding, ref = self._generated_upload(metadata_bytes=2_900_000, padding="p" * 330_000)
        original = source.read_bytes()
        self.assertLess(len(base64.b64encode(original)), 4 * 1024 * 1024)
        action = inputs.next_action(self.job, request)
        self.assertLess(len(json.dumps(action["arguments"], ensure_ascii=True).encode()) + 64 * 1024, 4 * 1024 * 1024)
        path, saved = inputs._state(self.job, request, binding)
        transport = saved["uploads"][artifacts.sha256_json(ref)]["transport"]
        copy_path = self.job / transport["path"]
        self.assertEqual(base64.b64decode(action["arguments"]["data_base64"]), copy_path.read_bytes())
        with Image.open(source) as a, Image.open(copy_path) as b:
            self.assertEqual((a.mode, a.size, a.tobytes()), (b.mode, b.size, b.tobytes()))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(transport["source_sha256"], ref["sha256"])

    def test_public_upload_413_record_preserves_action_and_recovers_once(self):
        import base64
        from edit.hd.tools import generation_inputs as inputs, generation_channels as channels
        source, request, binding, ref = self._generated_upload()
        original_request = copy.deepcopy(request)
        # A concrete action issued before the preflight fix, as in the captured incident.
        action = {"action": "upload", "purpose": "video", "request_id": request["id"],
                  "binding_id": artifacts.sha256_json(ref), "claim_token": "synthetic-original",
                  "tool": "mcp__lovart__upload_asset", "arguments": {
                      "data_base64": base64.b64encode(source.read_bytes()).decode(),
                      "filename": source.name, "project_id": "synthetic-project", "padding": ""}}
        path, saved = inputs._state(self.job, request, binding)
        saved["uploads"][action["binding_id"]] = {"source": ref, "action": action}
        artifacts.write_json_artifact(path, saved)
        response = {"isError": True, "content": [{"type": "text", "text":
            "tool call error: unexpected server response: HTTP 413: request body exceeds 4194304 bytes"}]}
        result = channels.record_result(SimpleNamespace(job_dir=self.job), action, response)
        self.assertEqual(result["status"], "input_upload_rejected_413")
        retry = inputs.next_action(self.job, request)
        self.assertNotEqual(retry["arguments"], action["arguments"])
        history = artifacts.read_json_artifact(path)["uploads"][action["binding_id"]]["rejected_uploads"]
        self.assertEqual(history, [{"action": action, "response": response}])
        self.assertEqual(inputs.next_action(self.job, request)["status"], "input_upload_pending")
        with self.assertRaisesRegex(ValueError, "remote media reference"):
            channels.record_result(SimpleNamespace(job_dir=self.job), retry,
                {"isError": True, "content": [{"type": "text", "text": "HTTP 500 unknown result"}]})
        self.assertEqual(inputs.next_action(self.job, request)["status"], "input_upload_pending")
        channels.record_result(SimpleNamespace(job_dir=self.job), retry, {"url": "https://example.test/actual.png"})
        self.assertEqual(inputs.resolve_request(self.job, request)["arguments"]["first_frame"], "https://example.test/actual.png")
        self.assertEqual(queue.status(self.job)["items"][request["id"]]["request"], original_request)

    def test_lovart_upload_stops_when_lossless_png_cannot_fit(self):
        from edit.hd.tools import generation_inputs as inputs
        source, request, binding, ref = self._generated_upload(metadata_bytes=0, noise=True)
        original = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "lossless.*limit"):
            inputs.next_action(self.job, request)
        self.assertEqual(source.read_bytes(), original)
        _, saved = inputs._state(self.job, request, binding)
        self.assertFalse(saved["uploads"])

    def test_reference_upload_encodes_frozen_bytes_for_lovart(self):
        import base64
        from edit.hd.tools import generation_inputs
        source = self.job / "reference.png"
        source.write_bytes(b"actual frozen image bytes")
        bindings = artifacts.read_json_artifact(self.job / "manifests/generation-channels.json")
        bindings["video"].update(reference_mode="upload", upload={
            "tool": "mcp__lovart__upload_asset",
            "arguments": {"data_base64": {"$input": "base64"},
                          "filename": {"$input": "filename"}},
            "result_path": ["url"],
        })
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", bindings)
        request = self.request("reference-upload", "video")
        request["arguments"]["ref_images"] = [str(source)]
        request["input_files"] = [{"path": source.name, "sha256": artifacts.sha256_file(source),
                                   "bytes": source.stat().st_size}]
        action = generation_inputs.next_action(self.job, request)
        self.assertEqual(base64.b64decode(action["arguments"]["data_base64"]), source.read_bytes())
        self.assertEqual(action["arguments"]["filename"], source.name)
        self.assertEqual(action["arguments"]["project_id"], request["arguments"]["project_id"])
        self.assertEqual(generation_inputs.next_action(self.job, request)["status"], "input_upload_pending")
        wrong_action = copy.deepcopy(action)
        wrong_action["arguments"]["project_id"] = "another-project"
        with self.assertRaisesRegex(ValueError, "original action"):
            generation_inputs.record_result(self.job, request, wrong_action, {"url": "https://example.test/reference.png"})
        generation_inputs.record_result(self.job, request, action, {"url": "https://example.test/reference.png"})
        self.assertEqual(generation_inputs.resolve_request(self.job, request)["arguments"]["ref_images"],
                         ["https://example.test/reference.png"])
        source.write_bytes(b"changed reference")
        with self.assertRaisesRegex(ValueError, "reference changed"):
            generation_inputs.resolve_request(self.job, request)

    def test_lovart_upload_rejects_conflicting_config_and_old_wrong_project_receipt(self):
        from edit.hd.tools import generation_inputs as inputs
        source, request, binding, ref = self._generated_upload(metadata_bytes=0)
        bindings = artifacts.read_json_artifact(self.job / "manifests/generation-channels.json")
        bindings["video"]["upload"]["arguments"]["project_id"] = "another-project"
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", bindings)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            inputs.next_action(self.job, request)
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", {**bindings, "video": binding})
        path, saved = inputs._state(self.job, request, binding)
        key = artifacts.sha256_json(ref)
        saved["uploads"][key] = {"source": ref, "action": {"arguments": {}}, "reference": "https://example.test/old.png"}
        artifacts.write_json_artifact(path, saved)
        with self.assertRaisesRegex(ValueError, "recorded Lovart upload project_id"):
            inputs.resolve_request(self.job, request)

    def test_lovart_query_uses_approved_project_with_explicit_binding(self):
        from edit.hd.tools import generation_channels as channels
        request = self.request("query-video", "video")
        self.add(request)
        claimed = queue.claim(self.job, request["id"], 10)
        queue.record(self.job, request["id"], claimed["claim_token"],
                     {"status": "pending", "task_ids": ["synthetic-task"]})
        path = self.job / "manifests/generation-channels.json"
        bindings = artifacts.read_json_artifact(path)
        bindings["video"]["query"] = {"tool": "mcp__lovart__get_task_status", "arguments": {},
                                      "task_ids_parameter": "task_ids"}
        artifacts.write_json_artifact(path, bindings)
        with mock.patch.object(channels.time, "time", return_value=10**12):
            action = channels.next_action(SimpleNamespace(job_dir=self.job), request["id"])
        self.assertEqual(action["arguments"], {"project_id": "synthetic-project", "task_ids": ["synthetic-task"]})
        self.assertEqual(artifacts.read_json_artifact(path), bindings)
        bindings["video"]["query"]["arguments"]["project_id"] = "different-project"
        artifacts.write_json_artifact(path, bindings)
        with mock.patch.object(channels.time, "time", return_value=10**12):
            with self.assertRaisesRegex(ValueError, "project_id conflicts"):
                channels.next_action(SimpleNamespace(job_dir=self.job), request["id"])

    def test_completed_visual_image_edit_is_unique_and_uses_original_bytes(self):
        from edit.hd.tools import visual_confirmation as visual
        original = self.request("image")
        self.add(original)
        claim = queue.claim(self.job, "image")
        source = self.job / "original.png"
        source.write_bytes(b"original image")
        ref = {"path": source.name, "sha256": artifacts.sha256_file(source), "bytes": source.stat().st_size}
        queue.record(self.job, "image", claim["claim_token"], {"status": "completed", "conclusion": "subject cropped", "artifacts": [
            {"type": "image", "path": str(source), "sha256": ref["sha256"], "bytes": ref["bytes"]}]})
        before = copy.deepcopy(queue.status(self.job)["items"]["image"])
        request = self.request("edit-image")
        request["arguments"]["referenced_image_paths"] = [str(source)]
        request["input_files"] = [ref]
        plan = {"from_id": "image", "request": request, "issue": "subject cropped", "count": 1}
        digest = artifacts.sha256_json(plan)
        with mock.patch.object(queue.state, "load_job", return_value=SimpleNamespace(job_dir=self.job)), \
             mock.patch.object(visual, "validate_generation_request") as validate:
            with self.assertRaisesRegex(queue.GenerationQueueError, "explicit permission"):
                queue.edit_completed_image(self.job, plan, "", digest)
            bad = copy.deepcopy(plan)
            bad["request"]["arguments"]["referenced_image_paths"] = [str(self.job / "other.png")]
            with self.assertRaisesRegex(queue.GenerationQueueError, "exact original"):
                queue.edit_completed_image(self.job, bad, "one edit", artifacts.sha256_json(bad))
            first = queue.edit_completed_image(self.job, plan, "one edit", digest)
            self.assertFalse(first["idempotent"])
            self.assertTrue(queue.edit_completed_image(self.job, plan, "one edit", digest)["idempotent"])
            with self.assertRaisesRegex(queue.GenerationQueueError, "different successor"):
                queue.edit_completed_image(self.job, plan, "another approval", digest)
            self.assertTrue(validate.called)
        items = queue.status(self.job)["items"]
        self.assertEqual(items["image"], before)
        self.assertEqual(items["edit-image"]["retry_of"], "image")
        self.assertEqual(items["edit-image"]["image_edit_plan"], plan)
        with mock.patch.object(visual, "_request_id", return_value="image"):
            rid, item = visual.generation_item({"items": items}, {}, {})
        self.assertEqual((rid, item["status"]), ("edit-image", "ready"))
        edited = self.job / "edited.png"
        edited.write_bytes(b"edited image")
        claimed = queue.claim(self.job, "edit-image")
        queue.record(self.job, "edit-image", claimed["claim_token"], {"status": "completed", "artifacts": [
            {"type": "image", "path": str(edited), "sha256": artifacts.sha256_file(edited), "bytes": edited.stat().st_size}]})
        with mock.patch.object(visual, "_request_id", return_value="image"):
            rid, item = visual.generation_item({"items": queue.status(self.job)["items"]}, {}, {})
        self.assertEqual((rid, item["status"]), ("edit-image", "completed"))
        self.assertEqual(queue.status(self.job)["items"]["image"], before)

    def test_followup_paper_sample_evidence_binds_actual_source_and_review(self):
        from PIL import Image
        from edit.hd.tools import visual_confirmation as visual, segment_render
        root = self.job
        def write(name, value):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            artifacts.write_json_artifact(path, value)
            return visual._record(root, path)
        source = root / 'source.png'
        Image.new('RGB', (20, 20), 'white').save(source)
        original = visual._record(root, source)
        crop = root / 'crop.png'
        with Image.open(source) as im: im.crop((0, 0, 10, 10)).save(crop)
        crop_ref = visual._record(root, crop)
        entry = root / 'index.html'
        entry.write_text('<img src="crop.png">', encoding='utf-8')
        entry_ref = visual._record(root, entry)
        arroll = root / '06-edit-structure/edited-aroll.mp4'
        arroll.parent.mkdir(parents=True)
        arroll.write_bytes(b'approved audio clock')
        arroll_ref = visual._record(root, arroll)
        preview = root / 'preview.mp4'
        preview.write_bytes(b'captured sample')
        preview_ref = visual._record(root, preview)
        director = write('director.json', {'segments': [{'segment_id': 'seg-009', 'start': 0, 'end': 2,
                           'bindings': {'visual': {'dependency_id': 'paper-collage-hyperframes'}}}]})
        brief = {'source_binding': {'aroll_sha256': arroll_ref['sha256'], 'segment_id': 'seg-009', 'start': 0, 'end': 2},
                 'upstream_route': 'paper-collage-ad/hyperframes',
                 'composition': {'width': 1080, 'height': 1920, 'fps': 24, 'frames': 48, 'alpha': False},
                 'entry': {'job_path': 'index.html', 'media_ref': 'entry', 'sha256': entry_ref['sha256']},
                 'assets': [{'job_path': 'crop.png', 'scene_path': 'crop.png', 'media_ref': 'crop', 'sha256': crop_ref['sha256']}]}
        proof = {'brief': write('brief.json', brief), 'preview': preview_ref}
        proof['crop_provenance'] = write('crop.json', {'source_images': {'source': {'path': 'source.png', 'sha256': original['sha256']}},
            'crops': [{'source': 'source.png', 'source_sha256': original['sha256'], 'crop': [0, 0, 10, 10], 'output': 'crop.png', 'output_sha256': crop_ref['sha256']}]})
        proof['media_manifest'] = write('media.json', {'schema_version': 'reference-process-media/v1', 'brief_sha256': proof['brief']['sha256'],
            'media': [{'media_ref': 'entry', 'sha256': entry_ref['sha256'], 'byte_length': entry_ref['bytes']},
                      {'media_ref': 'crop', 'sha256': crop_ref['sha256'], 'byte_length': crop_ref['bytes']}]})
        proof['render_evidence'] = write('render.json', {'exit_code': 0, 'external_requests': 0, 'upstream_route': brief['upstream_route'],
                                                           'frames': 48, 'output_sha256': preview_ref['sha256']})
        proof['review'] = write('review.json', {'status': 'needs_revision', 'preview': preview_ref,
            'observations': ['纸纹网格不自然'], 'method': '实看关键帧', 'inspected_times_seconds': [0.5]})
        plan = {'issue': '纸纹网格不自然', 'followup_evidence': proof}
        unapproved = {'from_id': 'image', 'request': self.request('edit-image'), 'count': 1, **plan}
        with self.assertRaisesRegex(queue.GenerationQueueError, 'explicit permission'):
            queue.edit_completed_image(root, unapproved, '', artifacts.sha256_json(unapproved))
        parent = {'authorization': {'source': {}}, 'completion_response': {'artifacts': [
            {'type': 'image', 'path': str(source), 'sha256': original['sha256'], 'bytes': original['bytes']}]}}
        job = SimpleNamespace(job_dir=root, job_id='synthetic', stages={'edit_structure': {'status': 'approved', 'artifacts': [arroll_ref]}})
        approved = {'step': {'segment_id': 'seg-009', 'component_id': 'visual', 'purpose': 'image'}}
        with mock.patch.object(visual, '_validate_source', return_value=(None, {'inputs': {'director': director}})), \
             mock.patch.object(segment_render, '_default_probe', return_value={}), \
             mock.patch.object(segment_render, '_probe_matches', return_value=True):
            queue._validate_followup_image_evidence(job, parent, plan, approved)
            for change in ('missing', 'path', 'issue', 'source'):
                bad = copy.deepcopy(plan)
                if change == 'missing': del bad['followup_evidence']['crop_provenance']
                if change == 'path': bad['followup_evidence']['preview']['path'] = 'index.html'
                if change == 'issue': bad['issue'] = '未经记录的问题'
                if change == 'source':
                    forged = {'source_images': {'source': {'path': 'source.png', 'sha256': original['sha256']}}, 'crops': []}
                    bad['followup_evidence']['crop_provenance'] = write('forged.json', forged)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    queue._validate_followup_image_evidence(job, parent, bad, approved)
            preview.write_bytes(b'tampered sample')
            with self.assertRaises(ValueError):
                queue._validate_followup_image_evidence(job, parent, plan, approved)

    def test_followup_edit_claim_reuses_locked_queue_and_keeps_unique_original(self):
        from edit.hd.tools import visual_confirmation as visual, generation_channels
        original = self.request('image')
        self.add(original)
        first = queue.claim(self.job, 'image')
        source = self.job / 'original.png'
        source.write_bytes(b'original image')
        ref = visual._record(self.job, source)
        queue.record(self.job, 'image', first['claim_token'], {'status': 'completed', 'artifacts': [
            {'type': 'image', 'path': str(source), 'sha256': ref['sha256'], 'bytes': ref['bytes']}]})
        queue_path = self.job / 'manifests/generation-queue.json'
        saved = artifacts.read_json_artifact(queue_path)
        saved['items']['image']['authorization'] = {'source': {}, 'steps': {'image': 'step'}}
        artifacts.write_json_artifact(queue_path, saved)
        job = SimpleNamespace(job_dir=self.job, job_id='synthetic')
        step = {'id': 'step', 'purpose': 'image', 'arguments': original['arguments'], 'input_files': []}
        proposal = {'generation_steps': [step]}
        request = self.request('edit-image')
        request['arguments']['referenced_image_paths'] = [str(source)]
        request['input_files'] = [ref]
        plan = {'from_id': 'image', 'request': request, 'issue': 'sample issue', 'count': 1, 'followup_evidence': {}}
        digest = artifacts.sha256_json(plan)
        with mock.patch.object(queue.state, 'load_job', return_value=job), \
             mock.patch.object(visual, '_validate_source', return_value=(None, proposal)), \
             mock.patch.object(visual, '_request_id', return_value='image'), \
             mock.patch.object(generation_channels, 'prepare_request', return_value=original), \
             mock.patch.object(queue, '_validate_followup_image_evidence'):
            parent_before = copy.deepcopy(queue.status(self.job)['items']['image'])
            result = queue.edit_completed_image(self.job, plan, '允许编辑 1 次并继续', digest)
            self.assertFalse(result['idempotent'])
            self.assertTrue(queue.edit_completed_image(self.job, plan, '允许编辑 1 次并继续', digest)['idempotent'])
            # A nested status() would deadlock on the real flock. Fail immediately instead.
            with mock.patch.object(queue, 'status', side_effect=AssertionError('nested queue lock')):
                action = queue.claim(self.job, 'edit-image')
            self.assertEqual(action['action'], 'generate')
            self.assertEqual(action['tool'], request['tool'])
            self.assertEqual(action['arguments'], request['arguments'])
            self.assertEqual(queue.claim(self.job, 'edit-image')['status'], 'submitting')
            items = queue.status(self.job)['items']
            self.assertEqual(items['image'], parent_before)
            self.assertEqual([key for key, value in items.items() if value.get('retry_of') == 'image'], ['edit-image'])

    def test_replace_only_proven_unsent_projectless_action_and_keep_evidence(self):
        from edit.hd.tools import generation_inputs as inputs, generation_channels as channels
        source, request, binding, ref = self._generated_upload(metadata_bytes=0)
        binding["upload"]["arguments"].pop("project_id")
        bindings = artifacts.read_json_artifact(self.job / "manifests/generation-channels.json")
        bindings["video"] = binding
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", bindings)
        old = inputs.next_action(self.job, request)
        del old["arguments"]["project_id"]
        path, state = inputs._state(self.job, request, binding)
        state["uploads"][old["binding_id"]]["action"] = copy.deepcopy(old)
        artifacts.write_json_artifact(path, state)
        job = SimpleNamespace(job_dir=self.job)
        unknown = {"status": "unknown", "evidence": "no response"}
        proven = {"status": "not_sent", "evidence": "host invocation log shows no tool call"}
        with self.assertRaisesRegex(ValueError, "not sent"):
            channels.replace_unsent_upload(job, old, unknown)
        self.assertEqual(artifacts.read_json_artifact(path), state)
        new = channels.replace_unsent_upload(job, old, proven)
        self.assertEqual(new["arguments"]["project_id"], request["arguments"]["project_id"])
        self.assertNotEqual(new["claim_token"], old["claim_token"])
        saved = artifacts.read_json_artifact(path)["uploads"][old["binding_id"]]
        self.assertEqual(saved["superseded_uploads"], [{"action": old, "evidence": proven}])
        self.assertEqual(inputs.next_action(self.job, request)["status"], "input_upload_pending")
        with self.assertRaisesRegex(ValueError, "original action"):
            channels.record_result(job, old, {"url": "https://example.test/old.png"})
        with self.assertRaisesRegex(ValueError, "original pending"):
            channels.replace_unsent_upload(job, old, proven)
        channels.record_result(job, new, {"url": "https://example.test/new.png"})
        self.assertEqual(inputs.resolve_request(self.job, request)["arguments"]["first_frame"], "https://example.test/new.png")

    def test_completed_artifact_download_identifies_our_client_without_browser_spoofing(self):
        import urllib.request
        from edit.hd.tools import generation_channels as channels
        request = self.request('download-video', 'video'); self.add(request)
        claim = queue.claim(self.job, request['id'], 10)
        action = {'action': 'submit', 'purpose': 'video', 'request_id': request['id'],
                  'claim_token': claim['claim_token']}
        url = 'https://a.lovart.ai/artifacts/generator/fixture.mp4'
        def fetch(actual, *, timeout):
            self.assertIsInstance(actual, urllib.request.Request)
            self.assertEqual(actual.full_url, url)
            self.assertEqual(actual.get_header('User-agent'), 'HD-Talking-Head/1.0 (authorized artifact retrieval)')
            self.assertIsNone(actual.get_header('Cookie'))
            self.assertIsNone(actual.get_header('Authorization'))
            self.assertEqual(timeout, 120)
            return io.BytesIO(b'synthetic provider media bytes')
        with mock.patch.object(channels.urllib.request, 'urlopen', side_effect=fetch) as download:
            result = channels.record_result(SimpleNamespace(job_dir=self.job), action,
                {'status': 'completed', 'artifacts': [{'type': 'video', 'url': url}]})
        self.assertEqual(download.call_count, 1)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(Path(result['artifacts'][0]['path']).read_bytes(), b'synthetic provider media bytes')
        self.assertEqual(queue.status(self.job)['items'][request['id']]['request'], request)

    def test_artifact_access_denial_preserves_pending_generation_without_retry(self):
        import urllib.error
        from edit.hd.tools import generation_channels as channels
        request = self.request('denied-video', 'video'); self.add(request)
        claim = queue.claim(self.job, request['id'], 10)
        queue.record(self.job, request['id'], claim['claim_token'], {'status': 'pending', 'task_ids': ['provider-task']})
        before = queue.status(self.job)['items'][request['id']]
        action = {'action': 'query', 'purpose': 'video', 'request_id': request['id'],
                  'claim_token': claim['claim_token'], 'task_ids': ['provider-task']}
        url = 'https://a.lovart.ai/artifacts/generator/denied.mp4'
        denied = urllib.error.HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(b'Access denied'))
        with mock.patch.object(channels.urllib.request, 'urlopen', side_effect=denied) as download:
            with self.assertRaises(urllib.error.HTTPError):
                channels.record_result(SimpleNamespace(job_dir=self.job), action,
                    {'status': 'completed', 'artifacts': [{'type': 'video', 'url': url}]})
        self.assertEqual(download.call_count, 1)
        self.assertEqual(queue.status(self.job)['items'][request['id']], before)
        self.assertFalse((self.job / 'generated-media' / request['id'] / '0.mp4').exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name).resolve()
        (self.job / "manifests").mkdir()
        self.config = {"max_concurrency": 2, "generation_enabled": True, "providers": [
            {"purpose": "image", "provider": "builtin", "endpoint_id": "image_gen.imagegen", "model": "builtin",
             "connection_status": "verified", "quota_status": "available"},
            {"purpose": "video", "provider": "Lovart", "endpoint_id": "mcp__lovart__generate_video", "model": "kling/kling-video-o1",
             "connection_status": "verified", "quota_status": "available"},
        ]}
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", {
            "schema_version": 1,
            "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"},
            "video": {"model_binding": {"mode": "argument", "parameter": "model"}, "reference_mode": "local_path"},
        })
        self.gate = mock.patch.object(queue, "_approved", return_value=("synthetic", "config", self.config))
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def request(self, rid, purpose="image"):
        args = {"prompt": "synthetic input " + rid}
        if purpose == "video":
            args.update(model="kling/kling-video-o1", project_id="synthetic-project", duration=5)
        return {"id": rid, "purpose": purpose, "tool": next(p["endpoint_id"] for p in self.config["providers"] if p["purpose"] == purpose),
                "arguments": args, "input_files": []}

    def add(self, *requests):
        plan = {"requests": list(requests)}
        return queue.add(self.job, plan, "synthetic permission, not user approval", artifacts.sha256_json(plan))

    def complete(self, rid, token, purpose="image", queried=None):
        return queue.record(self.job, rid, token, {"status": "completed", "project_id": "synthetic-project"} |
                            ({"artifacts": [{"type": purpose, "url": "https://example.invalid/synthetic"}]}), queried)

    def test_real_processes_share_two_slots_then_refill(self):
        requests = [self.request("r" + str(i), "video" if i % 2 else "image") for i in range(4)]
        self.add(*requests)
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_claim_worker, args=(self.job, r["id"], self.config, start, results)) for r in requests]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        answers = [results.get(timeout=2) for _ in processes]
        generated = [x for x in answers if x["action"] == "generate"]
        self.assertEqual(len(generated), 2)
        self.assertEqual(sum(x["status"] in queue.ACTIVE for x in queue.status(self.job)["items"].values()), 2)
        first = generated[0]
        item = queue.status(self.job)["items"][first["id"]]
        response = {"status": "completed", "artifacts": [{"type": item["request"]["purpose"], "url": "https://example.invalid/synthetic"}]}
        queue.record(self.job, first["id"], first["claim_token"], response)
        waiting = next(x["id"] for x in answers if x["action"] == "wait")
        self.assertEqual(queue.claim(self.job, waiting, 10)["action"], "generate")
        self.assertEqual(queue.claim(self.job, first["id"], 10)["action"], "blocked")

    def test_mixed_slots_pending_completion_poll_gate_and_recovery(self):
        self.add(self.request("image"), self.request("video", "video"), self.request("third"))
        image = queue.claim(self.job, "image")
        video = queue.claim(self.job, "video", 10)
        self.assertEqual(queue.claim(self.job, "third")["action"], "wait")
        response = {"status": "pending", "task_ids": ["synthetic-task"], "project_id": "synthetic-project", "poll_after_seconds": 10}
        queue.record(self.job, "video", video["claim_token"], response)
        self.assertTrue(queue.record(self.job, "video", video["claim_token"], response)["idempotent"])
        due = queue.status(self.job)["items"]["video"]["next_poll_at"]
        self.assertEqual(queue.poll(self.job, due - 1)["action"], "wait")
        group = queue.poll(self.job, due + 1)["groups"][0]
        self.assertEqual(group["task_ids"], ["synthetic-task"])
        self.assertEqual(queue.poll(self.job, due + 1)["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            self.complete("video", video["claim_token"], "video", ["wrong-task"])
        # Config drift blocks new generation, never collection of an existing result.
        with mock.patch.object(queue, "_approved", side_effect=queue.GenerationQueueError("changed")):
            self.complete("video", video["claim_token"], "video", ["synthetic-task"])
        completed = queue.status(self.job)["items"]["video"]
        self.assertEqual(completed["submission_response"], response)
        self.assertEqual(completed["completion_response"]["status"], "completed")
        self.assertEqual(queue.claim(self.job, "third")["action"], "generate")
        queue.record(self.job, "image", image["claim_token"], {"status": "unknown"})
        inspected = subprocess.run([sys.executable, "-m", "edit.hd.tools.generation_queue", "--job", str(self.job), "status"],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(inspected.stdout)["items"]["image"]["status"], "unknown")
        self.assertEqual(queue.claim(self.job, "image")["action"], "blocked")

    def test_id_content_and_cross_id_fingerprint_are_immutable(self):
        req = self.request("one")
        self.add(req)
        self.add(req)
        changed = copy.deepcopy(req)
        changed["arguments"]["prompt"] = "changed"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(changed)
        changed = {**req, "id": "another"}
        with self.assertRaises(queue.GenerationQueueError):
            self.add(changed)

    def test_model_binding_rejects_wrong_argument_and_fixed_model(self):
        self.config["providers"][1]["provider"] = "Generic"
        self.config["providers"][1]["endpoint_id"] = "generic.video"
        video = self.request("video", "video")
        video["arguments"]["model"] = "model-B"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(video)
        image = self.request("fixed")
        image["arguments"]["model"] = "unexpected"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(image)
        correct = self.request("correct", "video")
        self.add(correct)
        self.assertEqual(queue.status(self.job)["items"]["correct"]["channel_identity"]["model"], "kling/kling-video-o1")
        missing = self.request("missing", "video")
        del missing["arguments"]["model"]
        with self.assertRaises(queue.GenerationQueueError):
            self.add(missing)

    def test_independent_cli_transmits_video_account_limit(self):
        import importlib.util
        entry = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/run_generation.py"
        spec = importlib.util.spec_from_file_location("run_generation_cli_test", entry)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        self.add(self.request("cli-video", "video"))
        argv = [str(entry), "--project-root", str(entry.parents[3]), "--job", str(self.job),
                "next", "--request-id", "cli-video", "--account-limit", "1"]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(queue.state, "load_job", return_value=SimpleNamespace(job_dir=self.job)), \
             contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["action"], "submit")
        self.assertEqual(result["arguments"]["model"], "kling/kling-video-o1")

    def test_input_drift_limit_failure_and_config_one(self):
        image = self.job / "reference.png"
        image.write_bytes(b"synthetic")
        req = self.request("one")
        req["arguments"]["referenced_image_paths"] = [str(image)]
        req["input_files"] = [{"path": image.name, "bytes": image.stat().st_size, "sha256": artifacts.sha256_file(image)}]
        self.add(req)
        image.write_bytes(b"changed")
        with self.assertRaises(queue.GenerationQueueError):
            queue.claim(self.job, "one")
        self.config["max_concurrency"] = 1
        self.add(self.request("video", "video"), self.request("two"))
        v = queue.claim(self.job, "video", 10)
        self.assertEqual(queue.claim(self.job, "two")["action"], "wait")
        queue.record(self.job, "video", v["claim_token"], {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        self.assertEqual(queue.claim(self.job, "two")["action"], "wait")
        self.assertEqual(queue.claim(self.job, "video", 10)["action"], "blocked")

    def test_startup_receives_loaded_job_not_a_path(self):
        loaded = mock.Mock(job_id="synthetic", root=self.job)
        (self.job / "job-context.json").write_text("{}")
        config_path = self.job / "provider-config.json"
        config_path.write_text(json.dumps(self.config))
        config_digest = artifacts.sha256_file(config_path)
        (self.job / "manifests/setup-approval.json").write_text(json.dumps({"provider_config_sha256": config_digest}))
        self.gate.stop()
        with mock.patch.object(queue.state, "load_job", return_value=loaded), \
             mock.patch.object(queue.startup, "require_startup") as gate, \
             mock.patch.object(queue.startup, "_config", return_value=(config_path, config_digest)):
            self.assertEqual(queue._approved(self.job)[0], "synthetic")
            gate.assert_called_once_with(loaded)
        self.gate.start()

    def test_completion_cannot_clear_rate_limit_without_permission(self):
        self.add(self.request("video", "video"), self.request("image"), self.request("next"))
        video = queue.claim(self.job, "video", 10)
        image = queue.claim(self.job, "image")
        queue.record(self.job, "video", video["claim_token"], {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        queue.record(self.job, "image", image["claim_token"], {"status": "completed", "artifacts": [{"type": "image", "url": "https://example.invalid/synthetic"}]})
        self.assertEqual(queue.claim(self.job, "next")["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            queue.resume(self.job, "")
        queue.resume(self.job, "synthetic explicit resume permission")
        self.assertEqual(queue.claim(self.job, "next")["action"], "generate")
        self.assertEqual(queue.claim(self.job, "video", 10)["action"], "blocked")


    def test_frozen_retry_preserves_predecessor_and_requires_a_new_decision(self):
        reference = self.job / "reference.png"
        reference.write_bytes(b"synthetic reference")
        req = self.request("video", "video")
        req["input_files"] = [{"path": reference.name, "bytes": reference.stat().st_size,
                               "sha256": artifacts.sha256_file(reference)}]
        self.add(req)
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"],
                     {"status": "pending", "task_ids": ["original-task"]})
        failed = {"status": "failed", "task_ids": ["original-task"], "error": {"code": "FAILED"}}
        queue.record(self.job, "video", original["claim_token"], failed, ["original-task"])
        predecessor = copy.deepcopy(queue.status(self.job)["items"]["video"])
        prepared = queue.prepare_retry(self.job, "video")
        plan, digest = prepared["plan"], prepared["plan_sha256"]
        self.assertEqual(prepared["request"], req)
        self.assertEqual(plan["failure_response_sha256"], artifacts.sha256_json(failed))
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, plan, "", digest)
        changed = {**plan, "count": 2}
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, changed, "synthetic retry decision", artifacts.sha256_json(changed))
        changed = {**plan, "from_id": "another"}
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, changed, "synthetic retry decision", digest)
        reference.write_bytes(b"changed reference")
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, plan, "synthetic retry decision", digest)
        reference.write_bytes(b"synthetic reference")
        with mock.patch.object(queue, "_approved", return_value=("synthetic", "changed config", self.config)):
            with self.assertRaises(queue.GenerationQueueError):
                queue.retry(self.job, plan, "synthetic retry decision", digest)
        child = queue.retry(self.job, plan, "synthetic retry decision", digest)
        self.assertFalse(child["idempotent"])
        self.assertEqual(child["plan_request_id"], "video")
        child_item = copy.deepcopy(queue.status(self.job)["items"][child["id"]])
        self.add(req, child_item["request"])
        self.assertEqual(queue.status(self.job)["items"][child["id"]], child_item)
        with self.assertRaises(queue.GenerationQueueError):
            self.add({**req, "id": "duplicate"})
        claimed = queue.claim(self.job, child["id"], 10)
        self.assertEqual(claimed["arguments"], original["arguments"])
        self.assertNotEqual(claimed["claim_token"], original["claim_token"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, child["id"], original["claim_token"], failed)
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, "video", original["claim_token"], {"status": "completed"})
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, child["id"], claimed["claim_token"],
                         {"status": "pending", "task_ids": ["original-task"]})
        queue.record(self.job, child["id"], claimed["claim_token"],
                     {"status": "failed", "error": {"code": "FAILED_AGAIN"}})
        # Replaying permission cannot silently retarget the newest failure.
        replay = queue.retry(self.job, plan, "synthetic replay", digest)
        self.assertEqual(replay["id"], child["id"])
        self.assertTrue(replay["idempotent"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "video")
        next_plan = queue.prepare_retry(self.job, child["id"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, next_plan["plan"], "", next_plan["plan_sha256"])
        grandchild = queue.retry(self.job, next_plan["plan"], "synthetic separate new decision", next_plan["plan_sha256"])
        self.assertEqual(grandchild["retry_of"], child["id"])
        self.assertEqual(grandchild["plan_request_id"], "video")
        self.assertEqual(queue.status(self.job)["items"]["video"], predecessor)

    def test_concurrent_retry_decisions_create_and_claim_only_one_successor(self):
        self.add(self.request("video", "video"))
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"], {"status": "failed", "error": {"code": "FAILED"}})
        plan = queue.prepare_retry(self.job, "video")["plan"]
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_retry_worker,
                                 args=(self.job, plan, self.config, "synthetic decision " + str(i), start, results))
                     for i in range(2)]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        answers = [results.get(timeout=2) for _ in processes]
        self.assertEqual(len({x["retry"]["id"] for x in answers}), 1)
        self.assertEqual(sum(not x["retry"]["idempotent"] for x in answers), 1)
        self.assertEqual(sum(x["claim"]["action"] == "generate" for x in answers), 1)
        child = answers[0]["retry"]["id"]
        self.assertEqual(len(queue.status(self.job)["items"]), 2)
        claimed = next(x["claim"] for x in answers if x["claim"]["action"] == "generate")
        queue.record(self.job, child, claimed["claim_token"], {"status": "pending", "task_ids": ["retry-task"]})
        self.complete(child, claimed["claim_token"], "video", ["retry-task"])
        rows = queue.status(self.job)["items"]
        self.assertEqual(rows["video"]["status"], "failed")
        self.assertEqual(rows[child]["completion_response"]["status"], "completed")
        self.assertEqual(rows[child]["task_ids"], ["retry-task"])

    def test_paused_retry_and_not_found_keep_admission_closed(self):
        self.add(self.request("video", "video"), self.request("image"), self.request("next"))
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"],
                     {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        prepared = queue.prepare_retry(self.job, "video")
        child = queue.retry(self.job, prepared["plan"], "synthetic explicit resume and retry permission", prepared["plan_sha256"])
        self.assertTrue(queue.status(self.job)["paused"])
        self.assertEqual(queue.claim(self.job, child["id"], 10)["action"], "wait")
        queue.resume(self.job, "synthetic explicit resume and retry permission")
        claimed = queue.claim(self.job, child["id"], 10)
        image = queue.claim(self.job, "image")
        queue.record(self.job, "image", image["claim_token"], {"status": "unknown"})
        queue.record(self.job, child["id"], claimed["claim_token"],
                     {"status": "pending", "task_ids": ["missing-task"]})
        missing = {"status": "not_found", "task_ids": ["missing-task"]}
        self.assertEqual(queue.record(self.job, child["id"], claimed["claim_token"], missing, ["missing-task"])["status"], "unknown")
        item = queue.status(self.job)["items"][child["id"]]
        self.assertEqual(item["response"], missing)
        self.assertEqual(queue.poll(self.job, item["next_poll_at"] + 1000)["action"], "wait")
        self.assertEqual(queue.claim(self.job, "next")["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, child["id"])
        self.complete(child["id"], claimed["claim_token"], "video", ["missing-task"])
        self.assertEqual(queue.claim(self.job, "next")["action"], "generate")
        self.assertEqual(queue.status(self.job)["items"]["video"]["status"], "failed")

    def test_ambiguous_failure_and_nonfailed_states_cannot_be_retried(self):
        self.add(self.request("multi", "video"), self.request("partial", "video"),
                 self.request("moderated", "video"), self.request("completed", "video"))
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        multi = queue.claim(self.job, "multi", 10)
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        queue.record(self.job, "multi", multi["claim_token"], {"status": "pending", "task_ids": ["one", "two"]})
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        queue.record(self.job, "multi", multi["claim_token"], {"status": "failed", "task_ids": ["one", "two"]}, ["one", "two"])
        self.assertEqual(queue.status(self.job)["items"]["multi"]["status"], "unknown")
        self.assertEqual(queue.poll(self.job, queue.status(self.job)["items"]["multi"]["next_poll_at"] + 1)["action"], "wait")
        partial = queue.claim(self.job, "partial", 10)
        queue.record(self.job, "partial", partial["claim_token"],
                     {"status": "failed", "artifacts": [{"type": "video", "url": "https://example.invalid/partial"}]})
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "partial")
        self.complete("multi", multi["claim_token"], "video", ["one", "two"])
        for rid in ("moderated", "completed"):
            claimed = queue.claim(self.job, rid, 10)
            if rid == "completed":
                self.complete(rid, claimed["claim_token"], "video")
            else:
                queue.record(self.job, rid, claimed["claim_token"], {"status": "moderated"})
            with self.assertRaises(queue.GenerationQueueError):
                queue.prepare_retry(self.job, rid)


if __name__ == "__main__":
    unittest.main()

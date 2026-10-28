"""Current native Skill adapter contracts, replacing the retired derived-card bridge.

The FD/hash/symlink protections remain unchanged; native request and reviewed
result identities replace the former derived registry/qualification protocol.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from edit.hd.tests.test_broll_component_executor import _Job, _code_component, _recipe
from edit.hd.tools import broll_component_executor as executor, visual_canary, visual_confirmation

ROOT = Path(__file__).parents[3].resolve()
ADAPTER_PATH = ROOT / "skill-development/hd-talking-head/scripts/talkcraft_skill_adapter.py"


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location("hd_talkcraft_skill_adapter", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def brief():
    return {"schema_version":1,"job_id":"job-001",
        "source_binding":{"aroll_sha256":"a"*64,"segment_id":"seg-001","start":0,"end":2},
        "composition":{"width":1080,"height":1920,"fps":24,"frames":48},
        "template_request":{"semantic_family":"source_convergence","information_units":3,"numeric_values":[],"numeric_scale":"not_applicable"},
        "card_id":"source-converge","semantic_goal":"真实资料汇聚","transcript":"合同年报项目材料",
        "word_anchors":[{"text":"合同年报项目材料","start":0,"end":2}],
        "speech":{"job_path":"voice.wav","sha256":hashlib.sha256(b"voice").hexdigest(),"byte_count":5},
        "materials":[],"authorization":{"paid_generation":False},
        "project_directory":"native-projects/native-test","result_record_path":"native-inputs/native-test/result.json"}


class TalkCraftAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.directory=Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def _adapter(self):
        module=_load_adapter_module()
        return module.create_adapter(ROOT,sys.executable,lambda *_:json.dumps(brief()).encode())

    def test_factory_binds_native_entrypoint_and_reviewed_result_stdin_protocol(self):
        adapter=self._adapter()
        self.assertEqual(adapter.dependency_id,"video-talkcraft")
        self.assertEqual(adapter.entrypoint,"scripts/talkcraft_skill_adapter.py")
        self.assertIsNone(adapter.qualification_registry_path)
        self.assertEqual(adapter.renderer_version,"4.0.519")
        self.assertEqual(adapter.argv_template[:2],("{launcher}","{entrypoint}"))
        self.assertIn("--skill-root",adapter.argv_template)
        self.assertIn("--media-manifest",adapter.argv_template)
        self.assertIn("{media_manifest_fd}",adapter.argv_template)
        self.assertTrue(callable(adapter.media_loader))

    def test_reference_media_is_hash_bound_and_frozen_before_process(self) -> None:
        job = _Job(self.directory)
        media = job.job_dir / "presenter.webm"
        original = b"alpha-presenter-v1"
        media.write_bytes(original)
        adapter = replace(
            self._adapter(),
            media_loader=lambda *_args: (
                executor.ReferenceProcessMedia(
                    media_ref="media-0",
                    job_path="presenter.webm",
                    sha256=hashlib.sha256(original).hexdigest(),
                ),
            ),
        )
        nonce = self.directory / "nonce"
        nonce.mkdir()
        nonce_fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY)
        pinned = executor._job_context(job)
        manifest_fd = None
        media_fds = ()
        try:
            manifest_fd, media_fds = executor._freeze_reference_media(
                adapter=adapter,
                job=job,
                pinned_job=pinned,
                recipe={},
                component={},
                brief=b'{"brief":true}',
                nonce_fd=nonce_fd,
            )
            media.write_bytes(b"changed-after-freeze")
            os.lseek(media_fds[0], 0, os.SEEK_SET)
            self.assertEqual(os.read(media_fds[0], 1024), original)
            os.lseek(manifest_fd, 0, os.SEEK_SET)
            manifest = json.loads(os.read(manifest_fd, 65536))
            self.assertEqual(manifest["schema_version"], "reference-process-media/v1")
            self.assertEqual(manifest["media"][0]["fd"], media_fds[0])
            self.assertEqual(manifest["media"][0]["byte_length"], len(original))
        finally:
            if manifest_fd is not None:
                os.close(manifest_fd)
            for descriptor in media_fds:
                os.close(descriptor)
            pinned.close()
            os.close(nonce_fd)

    def test_reference_media_rejects_hash_mismatch_and_symlink(self) -> None:
        job = _Job(self.directory)
        target = job.job_dir / "target.webm"
        target.write_bytes(b"actual")
        linked = job.job_dir / "linked.webm"
        linked.symlink_to(target)
        pinned = executor._job_context(job)
        try:
            for index, (job_path, digest) in enumerate((
                ("target.webm", "0" * 64),
                ("linked.webm", hashlib.sha256(target.read_bytes()).hexdigest()),
            )):
                nonce = self.directory / f"nonce-{index}"
                nonce.mkdir()
                nonce_fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY)
                adapter = replace(
                    self._adapter(),
                    media_loader=lambda *_args, p=job_path, d=digest: (
                        executor.ReferenceProcessMedia(
                            media_ref="media-0", job_path=p, sha256=d
                        ),
                    ),
                )
                try:
                    with self.assertRaises(executor.BrollComponentExecutionError):
                        executor._freeze_reference_media(
                            adapter=adapter,
                            job=job,
                            pinned_job=pinned,
                            recipe={},
                            component={},
                            brief=b'{"brief":true}',
                            nonce_fd=nonce_fd,
                        )
                finally:
                    os.close(nonce_fd)
        finally:
            pinned.close()

    def test_factory_rejects_symlinked_project_root(self):
        module=_load_adapter_module()
        linked=self.directory/"linked-project"
        linked.symlink_to(ROOT,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,"canonical and nonsymlinked"):
            module.create_adapter(linked,sys.executable,lambda *_:b"{}")

    def test_result_path_is_rejected_before_any_out_of_root_read(self):
        module=_load_adapter_module()
        for invalid in ("/tmp/result.json","../result.json"):
            payload=brief();payload["result_record_path"]=invalid
            with patch.object(Path,"read_bytes",side_effect=AssertionError("must not read")):
                with self.assertRaises(ValueError):
                    module.load_result(self.directory,json.dumps(payload),
                        expected_record={"path":invalid,"sha256":"a"*64,"bytes":2},
                        expected_renderer_version="4.0.519")

    def test_pending_native_result_is_rejected_before_component_process(self):
        module=_load_adapter_module()
        payload=json.dumps(brief()).encode()
        adapter=module.create_adapter(ROOT,sys.executable,lambda *_:payload)
        reference=self.directory/"reference.mp4";reference.write_bytes(b"reference identity fixture")
        component=_code_component(payload,dependency_id="video-talkcraft")
        component.update(module.create_binding(adapter,payload,reference))
        component["executor"]="reference_adapter";component["artifact_contract"]["alpha"]=False
        recipe=_recipe([component]);segment={"segment_id":"seg-001","start":0,"end":2,"shot_recipe":recipe}
        process=Mock(side_effect=AssertionError("component process must not start"))
        policy=Mock()
        with patch("edit.hd.tools.visual_plan._load_router_module",return_value=policy), \
             patch.object(visual_canary,"load_approved_visual_plan",return_value={"segments":[segment]}), \
             patch.object(visual_canary,"approved_aroll_record",return_value={"sha256":"a"*64}), \
             patch.object(module,"_inputs"), \
             patch.object(visual_confirmation,"native_result_descriptor",return_value={"path":brief()["result_record_path"],"sha256":"a"*64,"bytes":2}), \
             patch.object(executor.subprocess,"Popen",process):
            with self.assertRaises(executor.BrollComponentExecutionError):
                executor.execute_component(_Job(self.directory),
                    executor.ComponentExecutionRequest(recipe=recipe,component_id="code"),
                    adapters={"code_generated":{"video-talkcraft":adapter},
                              "artifact_probe":executor.ArtifactProbe("unused","1",lambda *_:{})})
        process.assert_not_called()

    def test_original_recipe_binds_to_one_native_runtime_adapter(self):
        module=_load_adapter_module();adapter=self._adapter();payload=json.dumps(brief()).encode()
        reference=self.directory/"reference.mp4";reference.write_bytes(b"reference identity fixture")
        binding=module.create_binding(adapter,payload,reference)
        self.assertEqual(binding["template_id"],"video-talkcraft/source-converge")
        self.assertEqual(binding["source_entrypoint"],"scripts/talkcraft_skill_adapter.py")
        self.assertEqual(binding["source_sha256"],module.sha(ADAPTER_PATH))
        component=_code_component(payload,dependency_id="video-talkcraft");component.update(binding)
        component["executor"]="reference_adapter";component["artifact_contract"]["alpha"]=False
        policy=Mock()
        with patch("edit.hd.tools.visual_plan._load_router_module",return_value=policy):
            self.assertIs(executor._validate_code_adapter(adapter,component),adapter)
        policy.validate_template_binding.assert_called_once_with(component)


if __name__=="__main__":unittest.main()

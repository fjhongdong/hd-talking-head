from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from edit.hd.tests.test_render_span import v4_plan
from edit.hd.tests.test_talkcraft_contract import brief
from edit.hd.tests.test_broll_component_executor import _Job
from edit.hd.tools import broll_component_executor as executor
from edit.hd.tools import talkcraft_contract


ROOT = Path(__file__).parents[3].resolve()
ADAPTER_PATH = ROOT / "skill-development/hd-talking-head/scripts/talkcraft_adapter.py"


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location("hd_talkcraft_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("TalkCraft adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TalkCraftAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.paths = {}
        self.hashes = {}
        for name in ("node", "playwright", "browser", "ffmpeg", "ffprobe"):
            path = self.directory / name
            path.write_bytes(name.encode("ascii"))
            path.chmod(0o700)
            self.paths[name] = path
            self.hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.contracts = {
            name: {
                "kind": "file_snapshot", "path": str(self.paths[name]),
                "sha256": self.hashes[name], "version": "test",
                "library_discovery": "mach_o_static_v1", "libraries": [],
            }
            for name in ("node", "ffmpeg", "ffprobe")
        }
        for name in ("playwright", "browser"):
            self.contracts[name] = {
                "kind": "directory_tree", "path": str(self.paths[name]),
                "version": "test",
                "roots": [{"path": str(self.directory), "sha256": "a" * 64}],
            }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _adapter(self):
        module = _load_adapter_module()
        payload = json.dumps(brief(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        with patch("edit.hd.tools.runtime_contracts.verify_contracts", side_effect=lambda value: value):
            return module.create_adapter(
                project_root=ROOT,
                tools=self.paths,
                tool_hashes=self.hashes,
                brief_loader=lambda *_args: payload,
                runtime_contracts=self.contracts,
            )

    def test_factory_binds_entrypoint_registry_closure_and_stdin_protocol(self) -> None:
        adapter = self._adapter()
        self.assertEqual(adapter.dependency_id, talkcraft_contract.DEPENDENCY_ID)
        self.assertEqual(adapter.entrypoint, "edit/hd/integrations/talkcraft/runtime/render.mjs")
        self.assertEqual(adapter.qualification_registry_path,
                         "edit/hd/integrations/talkcraft/runtime/card-registry.json")
        self.assertEqual(adapter.argv_template[:3],
                         ("{launcher}", "--input-type=module", "{entrypoint}"))
        self.assertIn("--runtime-contracts", adapter.argv_template)
        self.assertIn("--media-manifest", adapter.argv_template)
        self.assertIn("{media_manifest_fd}", adapter.argv_template)
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

    def test_factory_rejects_symlinked_project_root(self) -> None:
        module = _load_adapter_module()
        linked = self.directory / "linked-project"
        linked.symlink_to(ROOT, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "canonical and nonsymlinked"):
            module.create_adapter(
                project_root=linked,
                tools=self.paths,
                tool_hashes=self.hashes,
                brief_loader=lambda *_args: b"{}",
                runtime_contracts=self.contracts,
            )

    def test_registry_path_is_rejected_before_any_out_of_root_read(self) -> None:
        base = self._adapter()
        card_id = talkcraft_contract.load_card_registry()["cards"][0]["card_id"]
        component = v4_plan(card_id)["segments"][0]["shot_recipe"]["components"][0]
        component.update(
            entrypoint=base.entrypoint,
            producer_version=base.producer_version,
            primary_renderer=base.primary_renderer,
            renderer_version=base.renderer_version,
        )
        for invalid in ("/tmp/registry.json", "../registry.json"):
            adapter = replace(base, qualification_registry_path=invalid)
            with (
                patch("edit.hd.tools.visual_plan._load_router_module", return_value=Mock()),
                patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")),
                self.assertRaises(executor.BrollComponentExecutionError),
            ):
                executor._validate_code_adapter(adapter, component)

    def test_pending_card_is_rejected_before_policy_or_process(self) -> None:
        adapter = self._adapter()
        card_id = talkcraft_contract.load_card_registry()["cards"][0]["card_id"]
        recipe = v4_plan(card_id)["segments"][0]["shot_recipe"]
        component = recipe["components"][0]
        component.update(
            entrypoint=adapter.entrypoint,
            producer_version=adapter.producer_version,
            primary_renderer=adapter.primary_renderer,
            renderer_version=adapter.renderer_version,
        )
        policy = Mock()
        process = Mock(side_effect=AssertionError("renderer must not start"))
        request = executor.ComponentExecutionRequest(
            recipe=recipe, component_id=component["component_id"]
        )
        with (
            patch.object(executor, "_bound_runtime_contract", return_value=self.contracts),
            patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy),
            patch.object(executor.subprocess, "Popen", process),
            self.assertRaises(executor.BrollComponentExecutionError) as caught,
        ):
            executor.execute_component(
                _Job(self.directory),
                request,
                adapters={
                    "code_generated": {talkcraft_contract.DEPENDENCY_ID: adapter},
                    "artifact_probe": executor.ArtifactProbe(
                        probe_id="unused", probe_version="1", probe=lambda *_args: {}
                    ),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
        policy.validate_template_binding.assert_not_called()
        process.assert_not_called()

    def test_qualified_card_binds_card_module_to_runtime_adapter(self) -> None:
        adapter = self._adapter()
        registry = talkcraft_contract.load_card_registry()
        card = next(
            item for item in registry["cards"]
            if item["card_id"] == "parallel-items-with-host"
        )
        production = card["production"]
        component = v4_plan(card["card_id"])["segments"][0]["shot_recipe"]["components"][0]
        component.update(
            executor=adapter.approved_executor,
            entrypoint=production["derived_entrypoint"],
            source_entrypoint=production["derived_entrypoint"],
            source_sha256=production["implementation_sha256"],
            producer_version=production["adapter_version"],
            verification_id=production["qualification_id"],
            primary_renderer=adapter.primary_renderer,
            renderer_version=adapter.renderer_version,
        )
        policy = Mock()
        with (
            patch.object(executor, "_bound_runtime_contract", return_value=self.contracts),
            patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy),
        ):
            self.assertIs(executor._validate_code_adapter(adapter, component), adapter)
        policy.validate_template_binding.assert_called_once_with(component)


if __name__ == "__main__":
    unittest.main()

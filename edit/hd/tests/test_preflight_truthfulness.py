"""Preflight must test the chosen interpreter and not overstate discovery."""

import importlib.util
import json
import os
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from edit.hd.tests.test_job_workspace import ROOT


def preflight():
    path = ROOT / "skill-development/hd-talking-head/scripts/dependency_preflight.py"
    spec = importlib.util.spec_from_file_location("truthful_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TruthfulPreflightTests(unittest.TestCase):
    def test_asr_process_failure_is_missing_capability_not_invalid_input(self):
        module = preflight()
        identity = {"job_context": {"workspace": "/unused", "job_id": "fixture"}}
        for error in (OSError("cannot spawn"), subprocess.TimeoutExpired(["probe"], 120)):
            with self.subTest(error=type(error).__name__), mock.patch.object(module.subprocess, "run", side_effect=error):
                result = module._check_reference_asr(ROOT, identity)
                self.assertEqual(result["status"], "smoke_failed")

    def test_selected_reference_asr_requires_real_probe_not_module_import(self):
        from edit.hd.tools import state, startup
        module = preflight()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video, script = root / "source.mp4", root / "script.md"
            video.write_bytes(b"synthetic input")
            script.write_text("script")
            job = state.create_job(root, video, script, profile="full-v2")
            context = {"project_root": str(ROOT), "workspace": str(root), "job_id": job.job_id,
                       "job_dir": str(job.job_dir), "runtime": startup.runtime_identity(ROOT)}
            context_path = root / "job-context.json"
            context_path.write_text(json.dumps(context))
            manifest = root / "references/dependency-manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({"schema_version": 3, "dependencies": [{
                "id": "reference-asr", "kind": "project_path", "required": False,
                "target": "edit/hd/tools/reference_asr.py", "api": ["probe_configured_runtime"],
                "required_level": "callable", "config_selection": "reference_asr", "stage": "job-start"}]}))
            config = job.job_dir / "manifests/provider-config.json"
            config.parent.mkdir(exist_ok=True)
            base = {"schema_version": 1, "providers": [], "generation_enabled": False, "max_concurrency": 1}
            selected = {"provider": "whisper.cpp", "model": "ggml-test", "execution": "local",
                        "upload_policy": "forbidden"}
            with mock.patch.dict(os.environ, {"HD_WHISPER_CLI": str(root / "missing"),
                                               "HD_WHISPER_MODEL": str(root / "ggml-test.bin")}):
                config.write_text(json.dumps({**base, "schema_version": 2, "reference_asr": selected}))
                report = module.build_report(manifest, ROOT, root, [], job_context_path=context_path)
                result = report["dependencies"][0]
                self.assertTrue(result["required"])
                self.assertFalse(result["callable"])
                self.assertEqual(report["summary"]["required_missing"], 1)
                config.write_text(json.dumps(base))
                report = module.build_report(manifest, ROOT, root, [], job_context_path=context_path)
                self.assertFalse(report["dependencies"][0]["required"])
                self.assertEqual(report["summary"]["required_missing"], 0)
                executable = root / "missing"
                executable.write_text('#!/bin/sh\n[ "$#" -eq 1 ] && [ "$1" = "--help" ]\n')
                executable.chmod(0o700)
                (root / "ggml-test.bin").write_bytes(b"synthetic model")
                config.write_text(json.dumps({**base, "schema_version": 2, "reference_asr": selected}))
                before = (job.job_dir / "workflow.json").read_bytes()
                report = module.build_report(manifest, ROOT, root, [], job_context_path=context_path)
                result = report["dependencies"][0]
                self.assertTrue(result["required"])
                self.assertTrue(result["callable"])
                self.assertFalse(result["reference_asr_probe"]["model_load_verified"])
                self.assertEqual(result["reference_asr_probe"]["provider_config_sha256"],
                                 hashlib.sha256(config.read_bytes()).hexdigest())
                self.assertEqual(report["summary"]["required_missing"], 0)
                self.assertEqual((job.job_dir / "workflow.json").read_bytes(), before)
                context["skill_release"] = {"root": str(root)}
                saved_report = job.job_dir / "manifests/dependency-preflight.json"
                saved_report.write_text(json.dumps(report))
                startup._report(job, context, report["provider_config_sha256"])
                for mutation in ("missing", "optional", "model", "hash", "file"):
                    altered = json.loads(json.dumps(report))
                    item = altered["dependencies"][0]
                    if mutation == "missing":
                        altered["dependencies"] = []
                    elif mutation == "optional":
                        item["required"] = False
                    elif mutation == "model":
                        item["reference_asr_probe"]["model"] = "ggml-other"
                    elif mutation == "hash":
                        item["reference_asr_probe"]["provider_config_sha256"] = "0" * 64
                    else:
                        item["reference_asr_probe"]["model_file"]["bytes"] = True
                    saved_report.write_text(json.dumps(altered))
                    with self.subTest(mutation=mutation), self.assertRaisesRegex(state.WorkflowError, "reference ASR"):
                        startup._report(job, context, report["provider_config_sha256"])


    def test_python_runtime_is_the_running_interpreter_not_path_python(self):
        module = preflight()
        with mock.patch.object(module.shutil, "which", return_value="/missing/path-python"):
            result = module._check_command({
                "id": "python-runtime", "target": "python3", "version_args": ["--version"],
            })
        self.assertEqual(result["resolved_path"], sys.executable)
        self.assertEqual(result["status"], "available")

    def test_false_connection_values_are_not_connections(self):
        module = preflight()
        for value in ("false", "0", "no", "off", "", "   "):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"HD_TEST_CONNECTED": value}, clear=True):
                result = module._check_environment_any({"id": "test", "target": ["HD_TEST_CONNECTED"]})
                self.assertNotEqual(result["status"], "connected")
                self.assertFalse(result.get("configured", False))

    def test_key_presence_is_configuration_not_authenticated_connection(self):
        module = preflight()
        with mock.patch.dict(os.environ, {"TEST_API_KEY": "sensitive-test-value"}, clear=True):
            result = module._check_environment_any({"id": "test", "target": ["TEST_API_KEY"]})
        self.assertEqual(result["status"], "configured")
        self.assertFalse(result.get("connected", False))
        self.assertNotIn("sensitive-test-value", json.dumps(result))

    def test_document_entrypoint_without_smoke_is_not_callable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "SKILL.md").write_text("instructions")
            result = preflight()._check_entrypoints({"id": "test", "entrypoints": ["SKILL.md"]}, root)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["entrypoints"][0]["status"], "discovered")

    def test_import_failure_blocks_a_required_runner(self):
        self.check_runner("import nonexistent_hd_test_dependency\ndef run(): pass\n", "smoke_failed")

    def test_non_callable_api_blocks_a_required_runner(self):
        self.check_runner("run = 'not a callable'\n", "smoke_failed")

    def test_real_callable_runner_passes_isolated_import(self):
        self.check_runner("def run(): return 42\n", "callable")

    def test_probe_preserves_packages_available_to_the_running_interpreter(self):
        from PIL import Image
        self.assertTrue(callable(Image.new))
        self.check_runner("from PIL import Image\ndef run(): return Image.new('RGB', (1, 1))\n", "callable")

    def test_cached_validators_cannot_come_from_another_project(self):
        module = preflight()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.PreflightError, "origin|project"):
                module._contract_validators(Path(directory).resolve())

    def test_cached_adapter_cannot_come_from_another_project(self):
        module = preflight()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.PreflightError, "origin|project"):
                module._project_binding_identity(Path(directory).resolve(), "html-video")

    def test_binding_function_does_not_make_unexecuted_entrypoint_callable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "reference").mkdir()
            (root / "reference/SKILL.md").write_text("instructions")
            (root / "runner.py").write_text("def run(): pass\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 3, "dependencies": [{
                "id": "reference", "kind": "reference_path", "target": "reference",
                "required": True, "required_level": "bound", "entrypoints": ["SKILL.md"],
                "bindings": [{"stage": "inspect", "target": "runner.py", "api": ["run"]}],
            }]}))
            report = preflight().build_report(manifest, root, root, [])
            self.assertEqual(report["summary"]["required_missing"], 1)
            self.assertFalse(report["dependencies"][0]["callable"])

    def check_runner(self, code, expected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "runner.py").write_text(code)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 3, "dependencies": [{
                "id": "runner", "kind": "project_path", "required": True,
                "target": "runner.py", "api": ["run"], "required_level": "callable",
            }]}))
            result = preflight().build_report(manifest, root, root, [])
            self.assertEqual(result["dependencies"][0]["status"], expected)
            self.assertEqual(result["summary"]["required_missing"], 0 if expected == "callable" else 1)


class LocalOfficialVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.clip = self.root / "official.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:r=10:d=0.2",
                        "-an", "-threads", "1", str(self.clip)], check=True, capture_output=True)
        self.binding = {"component_kind": "official_material", "media_type": "video",
                        "source_id": "official", "publisher": "Official publisher",
                        "source_url": "https://example.org/talk", "snapshot_path": "official.mp4",
                        "sha256": hashlib.sha256(self.clip.read_bytes()).hexdigest()}
        self.module = preflight()

    def check(self):
        self.assertTrue(callable(getattr(self.module, "_verify_local_official_video", None)),
                        "local official video verification is missing")
        return self.module._verify_local_official_video(self.binding, self.root)

    def test_local_official_video_is_verified_without_downloader(self):
        with mock.patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            self.assertTrue(self.check())

    def test_missing_local_video_still_needs_acquisition(self):
        self.clip.unlink()
        self.assertFalse(self.check())

    def test_changed_local_video_stops_instead_of_selecting_a_replacement(self):
        self.binding["sha256"] = "0" * 64
        self.assertTrue(callable(getattr(self.module, "_verify_local_official_video", None)))
        with self.assertRaisesRegex(self.module.PreflightError, "changed"):
            self.check()

    def test_video_header_without_decodable_media_is_not_valid(self):
        self.clip.write_bytes(b"not a video")
        self.binding["sha256"] = hashlib.sha256(self.clip.read_bytes()).hexdigest()
        self.assertTrue(callable(getattr(self.module, "_verify_local_official_video", None)))
        with self.assertRaisesRegex(self.module.PreflightError, "media"):
            self.check()

    def test_verified_local_video_does_not_select_acquisition(self):
        binding = {**self.binding, "local_media_verified": True}
        item = {"id": "official-video-acquisition", "selection": {
            "component_kind": "official_material", "binding_field": "media_type",
            "equals": "video", "required_level": "callable",
        }}
        self.assertIsNone(self.module._selected_recipe_binding(item, [binding]))

    def test_bound_job_report_skips_acquisition_only_while_local_video_is_valid(self):
        from edit.hd.tests.test_job_workspace import _load_initializer_module
        fixture_path = ROOT / "skill-development/hd-talking-head/tests/test_dependency_preflight.py"
        spec = importlib.util.spec_from_file_location("plan_fixture", fixture_path)
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        script = self.root / "script.md"
        script.write_text("测试官方视频复用", encoding="utf-8")
        job, _ = _load_initializer_module().initialize_video_job(
            self.root / "jobs", "预检复用测试", self.clip, script, project_root=ROOT)
        (job.job_dir / "manifests/provider-config.json").write_text(json.dumps({
            "schema_version": 1, "providers": [], "max_concurrency": 1, "generation_enabled": False,
        }))
        local = job.job_dir / "official.mp4"
        local.write_bytes(self.clip.read_bytes())
        binding = fixture._official_binding("official.mp4")
        binding["sha256"] = hashlib.sha256(local.read_bytes()).hexdigest()
        plan_path = job.job_dir / "07-visual-direction/visual-plan.json"
        plan_path.write_text(json.dumps(fixture._complete_visual_plan((binding,))))
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 3, "dependencies": [{
            "id": "official-video-acquisition", "kind": "availability_any", "required": False,
            "target": [{"id": "absent", "kind": "python_module", "target": "hd_test_nonexistent_downloader"}], "selection": {
                "component_kind": "official_material", "binding_field": "media_type",
                "equals": "video", "required_level": "callable",
            },
        }]}))
        def report():
            return self.module.build_report(manifest, ROOT, self.root, [], plan_path,
                                            job.root / "job-context.json")
        available = report()
        self.assertEqual(available["summary"]["required_missing"], 0)
        self.assertFalse(available["dependencies"][0]["selected"])
        self.assertEqual(available["local_official_media"][0]["sha256"], binding["sha256"])
        local.unlink()
        missing = report()
        self.assertEqual(missing["summary"]["required_missing"], 1)
        self.assertTrue(missing["dependencies"][0]["selected"])


if __name__ == "__main__":
    unittest.main()

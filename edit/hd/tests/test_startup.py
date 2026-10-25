"""Regression tests for the Skill-managed Job startup boundary."""

from __future__ import annotations

import json
import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from edit.hd.tools import state
from edit.hd.tests.test_job_workspace import ROOT, _load_initializer_module


def approve_fixture_setup(job):
    """Unit fixture only: stage tests use a synthetic dependency report.

    Real initialization/preflight/CLI integration is tested separately below.
    Never call this helper for a user Job or a provider request.
    """
    from edit.hd.tools import startup
    skill = ROOT / "skill-development/hd-talking-head"
    release_path = skill / "release-manifest.json"
    context = {
        "workspace": str(job.root), "job_dir": str(job.job_dir), "job_id": job.job_id,
        "project_root": str(ROOT), "runtime": startup.runtime_identity(ROOT),
        "skill_release": {"root": str(skill), "release_id": json.loads(release_path.read_text())["release_id"],
                          "manifest_sha256": hashlib.sha256(release_path.read_bytes()).hexdigest()},
    }
    (job.root / "job-context.json").write_text(json.dumps(context))
    manifests = job.job_dir / "manifests"
    manifests.mkdir(exist_ok=True)
    config = manifests / "provider-config.json"
    config.write_text(json.dumps({"schema_version": 1, "providers": [], "max_concurrency": 1,
                                  "generation_enabled": False}))
    manifest = skill / "references/dependency-manifest.json"
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "project_root": str(ROOT), "runtime": context["runtime"],
              "manifest_path": str(manifest), "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "job_context": {"job_id": job.job_id, "workspace": str(job.root)},
              "provider_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
              "summary": {"status": "ready", "required_missing": 0},
              "dependencies": [{"id": x["id"], "required": True, "status": "bound",
                                "callable": True, "connected": True, "bound": True}
                               for x in json.loads(manifest.read_text())["dependencies"] if x.get("required")]}
    plan = job.job_dir / "07-visual-direction/visual-plan.json"
    if plan.is_file() and job.stages["visual_direction"]["status"] == "approved":
        report["visual_plan"] = {"path": str(plan),
                                 "sha256": hashlib.sha256(plan.read_bytes()).hexdigest()}
    (manifests / "dependency-preflight.json").write_text(json.dumps(report))
    startup.confirm_setup(job, config, user_confirmation="隔离单元测试夹具，不是用户审批")


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"input-fixture")
        self.script.write_text("口播测试", encoding="utf-8")
        self.initializer = _load_initializer_module()

    def create(self):
        return self.initializer.initialize_video_job(
            self.root / "jobs", "启动检查", self.video, self.script,
            project_root=ROOT,
        )

    def test_managed_job_cannot_inspect_without_preflight(self):
        job, _ = self.create()
        with self.assertRaisesRegex(state.WorkflowError, "startup|preflight"):
            state.require_runnable(job, "inspect")

    def test_missing_context_cannot_silently_become_unmanaged(self):
        job, context = self.create()
        (Path(context["workspace"]) / "job-context.json").unlink()
        with self.assertRaisesRegex(state.WorkflowError, "startup|context"):
            state.require_runnable(job, "inspect")

    def test_initializer_records_actual_runtime_and_python(self):
        _, context = self.create()
        self.assertIn("runtime", context)
        runtime = context["runtime"]
        self.assertEqual(runtime["project_root"], str(ROOT))
        self.assertEqual(runtime["python"]["executable"], sys.executable)
        self.assertIn("edit/hd/tools/state.py", runtime["modules"])
        self.assertIn("compositor_contract", runtime)

    def test_cached_other_project_is_rejected_before_copying_inputs(self):
        other = self.root / "other-project"
        tools_dir = other / "edit/hd/tools"
        tools_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "edit/hd/tools/state.py", tools_dir / "state.py")
        with self.assertRaisesRegex(self.initializer.InitializeJobError, "cached|origin|project"):
            self.initializer.initialize_video_job(
                self.root / "jobs", "不能混用", self.video, self.script,
                project_root=other,
            )
        self.assertFalse((self.root / "jobs").exists())

    def test_ready_looking_unbound_report_does_not_authorize_inspect(self):
        job, _ = self.create()
        report = job.job_dir / "manifests/dependency-preflight.json"
        report.write_text(json.dumps({"summary": {"required_missing": 0, "status": "ready"}}))
        with self.assertRaisesRegex(state.WorkflowError, "startup|confirm|preflight"):
            state.require_runnable(job, "inspect")

    def prepared(self, *, max_concurrency=1):
        job, context = self.create()
        self.assertIn("runtime", context)
        config = job.job_dir / "manifests/provider-config.json"
        config.write_text(json.dumps({
            "schema_version": 1, "providers": [], "max_concurrency": max_concurrency,
            "generation_enabled": False,
        }))
        manifest = Path(context["skill_release"]["root"]) / "references/dependency-manifest.json"
        report = {
            "schema_version": 3,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "manifest_path": str(manifest),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "project_root": str(ROOT), "runtime": context["runtime"],
            "job_context": {"job_id": job.job_id, "workspace": str(job.root)},
            "provider_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "visual_plan": None,
            "summary": {"status": "ready", "required_missing": 0},
            "dependencies": [{
                "id": item["id"], "required": True, "status": "bound",
                "callable": True, "bound": True, "connected": True,
            } for item in json.loads(manifest.read_text())["dependencies"] if item.get("required")],
        }
        report_path = job.job_dir / "manifests/dependency-preflight.json"
        report_path.write_text(json.dumps(report))
        return job, context, config, report_path

    def startup(self):
        self.assertTrue((ROOT / "edit/hd/tools/startup.py").is_file(), "startup gate is missing")
        return importlib.import_module("edit.hd.tools.startup")

    def test_same_job_confirmation_is_idempotent(self):
        startup = self.startup()
        job, _, config, _ = self.prepared()
        with self.assertRaisesRegex(state.WorkflowError, "confirm"):
            state.require_runnable(job, "inspect")
        path = startup.confirm_setup(job, config, user_confirmation="确认本次本地配置")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.assertEqual(startup.confirm_setup(job, config, user_confirmation="确认"), path)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        state.require_runnable(state.load_job(job.job_dir), "inspect")

    def test_missing_talkcraft_health_report_blocks_setup(self):
        startup = self.startup()
        job, _, config, report_path = self.prepared()
        report = json.loads(report_path.read_text())
        report["dependencies"] = [
            item for item in report["dependencies"]
            if item["id"] != "talkcraft-runtime-health"
        ]
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(state.WorkflowError, "preflight dependency result is missing"):
            startup.confirm_setup(job, config, user_confirmation="确认")

    def test_selected_generation_channels_require_executable_bindings(self):
        startup = self.startup()
        for purposes in (("image",), ("video",), ("image", "video")):
            with self.subTest(purposes=purposes):
                job, _, config, report_path = self.prepared()
                config.write_text(json.dumps({"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                    "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                        "endpoint_id": "fixture." + purpose, "connection_status": "verified", "quota_status": "available",
                        "reference_images": True, "native_9_16": True, "silent_output": True}
                        for purpose in purposes]}))
                report = json.loads(report_path.read_text())
                report["provider_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
                report_path.write_text(json.dumps(report))
                bindings = config.parent / "generation-channels.json"
                if bindings.exists():
                    bindings.unlink()
                with self.assertRaisesRegex(state.WorkflowError, "confirm model and reference"):
                    startup.confirm_setup(job, config, user_confirmation="synthetic selected channels")
                data = {"schema_version": 1, **{purpose: {"model_binding": {"mode": "fixed"},
                    "reference_mode": "local_path"} for purpose in purposes}}
                invalid = json.loads(json.dumps(data))
                invalid[purposes[0]]["model_binding"] = {}
                bindings.write_text(json.dumps(invalid))
                with self.assertRaises(state.WorkflowError):
                    startup.confirm_setup(job, config, user_confirmation="synthetic selected channels")
                bindings.write_text(json.dumps(data))
                receipt = startup.confirm_setup(job, config, user_confirmation="synthetic selected channels")
                approval = json.loads(receipt.read_text())
                self.assertEqual(set(approval["channels"]), set(purposes))
                self.assertEqual(approval["generation_channels_sha256"], hashlib.sha256(bindings.read_bytes()).hexdigest())
                state.require_runnable(job, "inspect")

    def test_selected_generation_channels_allow_one_explicit_purpose(self):
        startup = self.startup()
        provider = {"purpose": "image", "provider": "fixture", "model": "image-model",
                    "endpoint_id": "fixture.image", "connection_status": "verified",
                    "quota_status": "available", "reference_images": True,
                    "native_9_16": True, "silent_output": True}
        config = {"schema_version": 1, "generation_enabled": True,
                  "max_concurrency": 1, "providers": [provider]}
        self.assertEqual(startup.selected_channels(config), {
            "image": {"provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image"}
        })

        provider["purpose"] = "video"
        provider["model"] = "video-model"
        provider["endpoint_id"] = "fixture.video"
        config["providers"] = [provider]
        self.assertEqual(startup.selected_channels(config), {
            "video": {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        })

    def test_generation_request_for_unconfigured_purpose_is_blocked(self):
        startup = self.startup()
        job, _, config, report_path = self.prepared()
        provider = {"purpose": "image", "provider": "fixture", "model": "image-model",
                    "endpoint_id": "fixture.image", "connection_status": "verified",
                    "quota_status": "available", "reference_images": True,
                    "native_9_16": True, "silent_output": True}
        config.write_text(json.dumps({"schema_version": 1, "generation_enabled": True,
                                      "max_concurrency": 1, "providers": [provider]}))
        report = json.loads(report_path.read_text())
        report["provider_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
        report_path.write_text(json.dumps(report))
        from edit.hd.tools import generation_channels
        with self.assertRaisesRegex(state.WorkflowError, "no verified video"):
            generation_channels.selected_channel(job, "video")

    def test_selected_generation_channels_require_a_configured_purpose(self):
        startup = self.startup()
        config = {"schema_version": 1, "generation_enabled": True,
                  "max_concurrency": 1, "providers": []}
        with self.assertRaisesRegex(state.WorkflowError, "at least one"):
            startup.selected_channels(config)

    def test_stale_preflight_stops_even_after_confirmation(self):
        startup = self.startup()
        job, _, config, report_path = self.prepared()
        startup.confirm_setup(job, config, user_confirmation="确认")
        report = json.loads(report_path.read_text())
        report["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(state.WorkflowError, "preflight.*stale"):
            state.require_runnable(job, "inspect")

    def test_foreign_job_report_is_rejected(self):
        startup = self.startup()
        job, _, config, report_path = self.prepared()
        report = json.loads(report_path.read_text())
        report["job_context"]["workspace"] = str(self.root / "different-job")
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(state.WorkflowError, "preflight.*Job"):
            startup.confirm_setup(job, config, user_confirmation="确认")

    def test_config_change_requires_new_confirmation_and_preflight(self):
        startup = self.startup()
        job, _, config, _ = self.prepared()
        startup.confirm_setup(job, config, user_confirmation="确认")
        changed = json.loads(config.read_text())
        changed["max_concurrency"] = 2
        config.write_text(json.dumps(changed))
        with self.assertRaisesRegex(state.WorkflowError, "config"):
            state.require_runnable(job, "inspect")

    def test_max_generation_concurrency_two_is_valid(self):
        startup = self.startup()
        job, _, config, _ = self.prepared(max_concurrency=2)
        self.assertEqual(startup._config(job), (config, startup.artifacts.sha256_file(config)))

    def test_invalid_generation_concurrency_is_rejected(self):
        startup = self.startup()
        for value in (True, False, 0, -1, 3):
            with self.subTest(value=value):
                job, _, config, _ = self.prepared()
                changed = json.loads(config.read_text())
                changed["max_concurrency"] = value
                config.write_text(json.dumps(changed))
                with self.assertRaisesRegex(state.WorkflowError, "provider config fields"):
                    startup._config(job)

    def test_report_cannot_omit_a_required_runner(self):
        startup = self.startup()
        job, _, config, report_path = self.prepared()
        report = json.loads(report_path.read_text())
        report["dependencies"] = []
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(state.WorkflowError, "preflight.*dependenc"):
            startup.confirm_setup(job, config, user_confirmation="确认")

    def test_empty_confirmation_is_not_an_approval(self):
        startup = self.startup()
        job, _, config, _ = self.prepared()
        with self.assertRaisesRegex(state.WorkflowError, "confirmation"):
            startup.confirm_setup(job, config, user_confirmation=" ")

    def test_runtime_change_stops_before_stage_execution(self):
        startup = self.startup()
        job, context, config, _ = self.prepared()
        startup.confirm_setup(job, config, user_confirmation="确认")
        context["runtime"]["compositor_contract"] = "different-renderer"
        (job.root / "job-context.json").write_text(json.dumps(context))
        with self.assertRaisesRegex(state.WorkflowError, "runtime changed"):
            state.require_runnable(job, "inspect")

    def test_skill_version_change_requires_explicit_migration(self):
        startup = self.startup()
        job, context, config, _ = self.prepared()
        startup.confirm_setup(job, config, user_confirmation="确认")
        context["skill_release"]["manifest_sha256"] = "0" * 64
        (job.root / "job-context.json").write_text(json.dumps(context))
        with self.assertRaisesRegex(state.WorkflowError, "release changed"):
            state.require_runnable(job, "inspect")

    def test_confirmation_cli_works_from_another_directory(self):
        cli = ROOT / "skill-development/hd-talking-head/scripts/confirm_job_setup.py"
        self.assertTrue(cli.is_file(), "portable configuration confirmation CLI is missing")
        job, _, _, _ = self.prepared()
        result = subprocess.run([sys.executable, str(cli), "--job-context", str(job.root / "job-context.json"),
                                 "--user-confirmation", "确认本次配置"],
                                cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        state.require_runnable(job, "inspect")

    def test_real_preflight_confirmation_and_inspection_from_another_directory(self):
        from edit.hd.tests.test_preflight_truthfulness import preflight
        from edit.hd.tools.inspect_inputs import inspect_job
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=1080x1920:r=24:d=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-c:a", "aac", "-shortest", str(self.video),
        ], check=True, capture_output=True)
        job, context, config, report_path = self.prepared()
        skill = Path(context["skill_release"]["root"])
        module = preflight()
        references = Path(os.environ.get("HD_TEST_REFERENCE_ROOT", str(ROOT / "参考项目/B-roll开源方案")))
        report = module.build_report(skill / "references/dependency-manifest.json", ROOT,
                                     references, module._default_skill_roots(),
                                     job_context_path=job.root / "job-context.json")
        self.assertEqual(report["summary"]["required_missing"], 0,
                         [x for x in report["dependencies"] if x["required"] and x["status"] not in module.SUCCESS_STATUSES])
        report_path.write_text(json.dumps(report))
        result = subprocess.run([sys.executable, str(skill / "scripts/confirm_job_setup.py"),
                                 "--job-context", str(job.root / "job-context.json"),
                                 "--user-confirmation", "测试夹具的配置确认，不是用户生产审批"],
                                cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        inspect_job(state.load_job(job.job_dir))
        self.assertEqual(state.load_job(job.job_dir).stages["inspect"]["status"], "ready_for_review")

    def test_context_through_symlinked_parent_is_rejected(self):
        startup = self.startup()
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "context.json").write_text("{}")
        link = self.root / "linked"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(state.WorkflowError, "regular|symlink"):
            startup._read(link / "context.json", "context")


if __name__ == "__main__":
    unittest.main()

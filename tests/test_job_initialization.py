"""Bootstrap regression tests; no media decoding, network or user Job changes."""

from __future__ import annotations

import hashlib
import fcntl
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import create_job_workspace as workspace_module
import initialize_video_job as initializer
from edit.hd.tools import state

PROJECT = Path(state.__file__).resolve().parents[3]


class JobInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.jobs = self.root / "jobs"
        self.video = self.root / "原片.mp4"
        self.script = self.root / "文案.md"
        self.video.write_bytes(b"tiny-video-fixture")
        self.script.write_text("分享一次真实的 AI 使用经历。\n", encoding="utf-8")
        # Maintenance tests exercise unreleased code. Package integrity itself is
        # tested, without mocking, by test_release_integrity and startup tests.
        manifest = SKILL / "release-manifest.json"
        self.release = {
            "status": "pass", "root": str(SKILL), "failures": [],
            "release_id": json.loads(manifest.read_text())["release_id"],
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }
        patcher = mock.patch.object(initializer, "verify_release", return_value=self.release)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, **kwargs):
        return initializer.initialize_video_job(
            self.jobs, "恢复测试", self.video, self.script, project_root=PROJECT, **kwargs,
        )

    def pending(self):
        with mock.patch.object(state, "create_job", side_effect=OSError("injected state failure")):
            with self.assertRaisesRegex(RuntimeError, "injected|初始化|initialize"):
                try:
                    self.create()
                except OSError as exc:
                    raise RuntimeError(str(exc)) from exc
        roots = list(self.jobs.iterdir())
        self.assertEqual(len(roots), 1)
        self.assertTrue((roots[0] / "initialization.json").is_file(),
                        "published workspace needs a recovery record before state creation")
        return roots[0]

    def resume(self, workspace):
        self.assertTrue(callable(getattr(initializer, "resume_video_job", None)),
                        "same-workspace resume API is missing")
        return initializer.resume_video_job(workspace, project_root=PROJECT)

    def test_state_failure_publishes_recovery_record_not_context(self):
        workspace = self.pending()
        self.assertFalse((workspace / "job-context.json").exists())
        record = json.loads((workspace / "initialization.json").read_text())
        self.assertEqual(record["phase"], "imported")
        self.assertEqual(record["workspace"], str(workspace))
        self.assertEqual(set(record["inputs"]), {"video", "script"})

    def test_state_engine_error_reports_retained_workspace(self):
        with mock.patch.object(state, "create_job", side_effect=state.WorkflowError("engine stopped")):
            with self.assertRaisesRegex(initializer.InitializeJobError, "retained workspace"):
                self.create()
        self.assertEqual(len(list(self.jobs.iterdir())), 1)

    def test_resume_uses_imported_bytes_even_if_originals_are_gone(self):
        workspace = self.pending()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (workspace / "00-user-provided").rglob("*") if p.is_file()}
        self.video.unlink()
        self.script.unlink()
        with mock.patch.object(workspace_module.shutil, "copy2", side_effect=AssertionError("recopied")):
            job, context = self.resume(workspace)
        self.assertEqual(context["workspace"], str(workspace))
        self.assertEqual(len(list(self.jobs.iterdir())), 1)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        self.assertEqual(job.version, 2)

    def test_resume_after_state_commit_preserves_workflow_revision(self):
        original = state.create_job

        def commit_then_fail(*args, **kwargs):
            job = original(*args, **kwargs)
            state.revise(job, "inspect", "fixture revision to preserve")
            raise OSError("injected after commit")

        with mock.patch.object(state, "create_job", side_effect=commit_then_fail):
            with self.assertRaises((OSError, RuntimeError)):
                self.create()
        workspace = next(self.jobs.iterdir())
        workflow = next(workspace.glob("edit/hd/jobs/*/workflow.json"))
        before = (workflow.read_bytes(), workflow.stat().st_mtime_ns)
        job, _ = self.resume(workspace)
        self.assertEqual(job.revision, 1)
        self.assertEqual((workflow.read_bytes(), workflow.stat().st_mtime_ns), before)

    def test_ready_resume_is_idempotent_and_does_not_reset_approval_state(self):
        job, context = self.create()
        state.revise(job, "inspect", "fixture state")
        context_path = Path(context["workspace"]) / "job-context.json"
        before = (context_path.read_bytes(), context_path.stat().st_mtime_ns)
        resumed, same = self.resume(job.root)
        self.assertEqual(resumed.revision, job.revision)
        self.assertEqual(same, context)
        self.assertEqual((context_path.read_bytes(), context_path.stat().st_mtime_ns), before)

    def test_inline_script_is_utf8_and_only_stored_inside_workspace(self):
        self.assertIn("script_text", inspect.signature(initializer.initialize_video_job).parameters,
                      "inline script input is missing")
        content = "  这是逐字保留的中文文案 🚀\n第二行。\n"
        job, context = initializer.initialize_video_job(
            self.jobs, "聊天文案", self.video, script_text=content, project_root=PROJECT,
        )
        imported = Path(context["script"])
        self.assertTrue(imported.is_relative_to(job.root / "00-user-provided/documents"))
        self.assertEqual(imported.read_bytes(), content.encode("utf-8"))
        self.assertEqual(job.inputs["script"]["sha256"], hashlib.sha256(content.encode()).hexdigest())

    def test_invalid_inline_inputs_are_rejected_before_copy(self):
        self.assertIn("script_text", inspect.signature(initializer.initialize_video_job).parameters)
        for script, text in ((self.script, "冲突"), (None, " \n"), (None, None)):
            with self.subTest(script=script, text=text):
                with self.assertRaises(initializer.InitializeJobError):
                    initializer.initialize_video_job(
                        self.jobs, "无效", self.video, script, script_text=text, project_root=PROJECT,
                    )
                self.assertFalse(self.jobs.exists())

    def test_changed_imported_bytes_stop_resume_without_new_workspace(self):
        workspace = self.pending()
        index = json.loads((workspace / "00-user-provided/material-index.json").read_text())
        source = workspace / index["materials"][0]["imported_path"]
        source.write_bytes(b"damaged copy")
        with self.assertRaisesRegex(initializer.InitializeJobError, "changed|hash|integrity"):
            self.resume(workspace)
        self.assertEqual(len(list(self.jobs.iterdir())), 1)
        self.assertFalse((workspace / "job-context.json").exists())

    def test_input_changed_between_validation_and_state_creation_cannot_publish_context(self):
        workspace = self.pending()
        original = state.create_job

        def change_then_create(root, video, script, **kwargs):
            video.write_bytes(b"changed just before state engine reads")
            return original(root, video, script, **kwargs)

        with mock.patch.object(state, "create_job", side_effect=change_then_create):
            with self.assertRaisesRegex(initializer.InitializeJobError, "inputs|identity"):
                self.resume(workspace)
        self.assertFalse((workspace / "job-context.json").exists())

    def test_changed_release_stops_resume_without_resigning(self):
        workspace = self.pending()
        marker = workspace / "initialization.json"
        before = marker.read_bytes()
        self.release["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(initializer.InitializeJobError, "identity|release|migration"):
            self.resume(workspace)
        self.assertEqual(marker.read_bytes(), before)

    def test_copy_corruption_is_rejected_before_workspace_publication(self):
        original = workspace_module.shutil.copy2

        def corrupt(source, destination):
            result = original(source, destination)
            Path(destination).write_bytes(b"injected wrong bytes")
            return result

        with mock.patch.object(workspace_module.shutil, "copy2", side_effect=corrupt):
            with self.assertRaisesRegex(workspace_module.WorkspaceError, "changed|hash|copy"):
                workspace_module.create_workspace(self.jobs, "copy check", [self.video])
        self.assertEqual(list(self.jobs.iterdir()), [])
        self.assertEqual(self.video.read_bytes(), b"tiny-video-fixture")

    def test_ready_job_missing_workflow_directory_is_not_recreated(self):
        job, _ = self.create()
        job.job_dir.rename(self.root / "preserved-workflow")
        with self.assertRaises((initializer.InitializeJobError, state.WorkflowError)):
            self.resume(job.root)
        self.assertFalse(job.job_dir.exists())

    def test_conflicting_context_is_rejected_before_creating_workflow(self):
        workspace = self.pending()
        context = workspace / "job-context.json"
        context.write_text('{"job_id": "another-job"}')
        before = context.read_bytes()
        with self.assertRaisesRegex(initializer.InitializeJobError, "context"):
            self.resume(workspace)
        self.assertEqual(context.read_bytes(), before)
        self.assertFalse((workspace / "edit").exists())

    def test_context_write_failure_resumes_without_rewriting_workflow(self):
        original = initializer._write_json_atomic

        def fail_context(path, payload):
            if path.name == "job-context.json":
                raise OSError("injected context write")
            return original(path, payload)

        with mock.patch.object(initializer, "_write_json_atomic", side_effect=fail_context):
            with self.assertRaisesRegex(initializer.InitializeJobError, "retained workspace"):
                self.create()
        workspace = next(self.jobs.iterdir())
        self.assertFalse((workspace / "job-context.json").exists())
        workflow = next(workspace.glob("edit/hd/jobs/*/workflow.json"))
        before = (workflow.read_bytes(), workflow.stat().st_mtime_ns)
        self.resume(workspace)
        self.assertEqual((workflow.read_bytes(), workflow.stat().st_mtime_ns), before)

    def test_context_committed_but_ready_marker_failed_can_resume(self):
        original = initializer._write_json_atomic

        def fail_ready(path, payload):
            if path.name == "initialization.json":
                raise OSError("injected ready marker write")
            return original(path, payload)

        with mock.patch.object(initializer, "_write_json_atomic", side_effect=fail_ready):
            with self.assertRaises(initializer.InitializeJobError):
                self.create()
        workspace = next(self.jobs.iterdir())
        context = workspace / "job-context.json"
        before = (context.read_bytes(), context.stat().st_mtime_ns)
        self.resume(workspace)
        self.assertEqual((context.read_bytes(), context.stat().st_mtime_ns), before)

    def test_committed_context_prevents_rebuilding_missing_imported_phase_workflow(self):
        original = initializer._write_json_atomic

        def fail_ready(path, payload):
            if path.name == "initialization.json":
                raise OSError("injected ready marker write")
            return original(path, payload)

        with mock.patch.object(initializer, "_write_json_atomic", side_effect=fail_ready):
            with self.assertRaises(initializer.InitializeJobError):
                self.create()
        workspace = next(self.jobs.iterdir())
        context = json.loads((workspace / "job-context.json").read_text())
        job_dir = Path(context["job_dir"])
        job_dir.rename(self.root / "preserved-workflow")
        with self.assertRaisesRegex(initializer.InitializeJobError, "committed workflow"):
            self.resume(workspace)
        self.assertFalse(job_dir.exists())

    def test_empty_uncommitted_state_directory_can_resume(self):
        with mock.patch.object(state, "save_job", side_effect=OSError("injected save failure")):
            with self.assertRaises(initializer.InitializeJobError):
                self.create()
        workspace = next(self.jobs.iterdir())
        empty = next(workspace.glob("edit/hd/jobs/*"))
        self.assertEqual(list(empty.iterdir()), [])
        job, _ = self.resume(workspace)
        self.assertEqual(job.job_dir, empty)
        self.assertTrue((empty / "workflow.json").is_file())

    def test_nonempty_partial_state_is_preserved_and_refused(self):
        with mock.patch.object(state, "save_job", side_effect=OSError("injected save failure")):
            with self.assertRaises(initializer.InitializeJobError):
                self.create()
        workspace = next(self.jobs.iterdir())
        debris = next(workspace.glob("edit/hd/jobs/*")) / "recover-me.json"
        debris.write_bytes(b"retained transaction evidence")
        with self.assertRaisesRegex(initializer.InitializeJobError, "nonempty partial"):
            self.resume(workspace)
        self.assertEqual(debris.read_bytes(), b"retained transaction evidence")

    def test_concurrent_resume_refuses_without_touching_records(self):
        workspace = self.pending()
        marker = workspace / "initialization.json"
        before = marker.read_bytes()
        with (workspace / ".initialization.lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(initializer.InitializeJobError, "another initializer"):
                self.resume(workspace)
        self.assertEqual(marker.read_bytes(), before)
        self.resume(workspace)

    def test_symlink_import_cannot_substitute_identical_external_bytes(self):
        workspace = self.pending()
        record = json.loads((workspace / "initialization.json").read_text())
        imported = workspace / record["inputs"]["video"]["path"]
        imported.unlink()
        imported.symlink_to(self.video)
        with self.assertRaisesRegex(initializer.InitializeJobError, "symlink"):
            self.resume(workspace)

    def test_changed_runtime_is_refused_without_identity_rewrite(self):
        workspace = self.pending()
        marker = workspace / "initialization.json"
        record = json.loads(marker.read_text())
        record["runtime"]["python"]["executable"] = "/another/python"
        marker.write_text(json.dumps(record))
        before = marker.read_bytes()
        with self.assertRaisesRegex(initializer.InitializeJobError, "identity changed"):
            self.resume(workspace)
        self.assertEqual(marker.read_bytes(), before)

    def test_duplicate_json_keys_in_recovery_record_are_rejected(self):
        workspace = self.pending()
        marker = workspace / "initialization.json"
        marker.write_text(marker.read_text().replace('{', '{"phase":"ready",', 1))
        with self.assertRaisesRegex(initializer.InitializeJobError, "invalid recovery record"):
            self.resume(workspace)

    def test_inline_duplicate_reuses_asset_and_preserves_both_names(self):
        text = self.script.read_text(encoding="utf-8")
        job, _ = initializer.initialize_video_job(
            self.jobs, "去重", self.video, user_files=[self.script],
            script_text=text, project_root=PROJECT,
        )
        index = json.loads((job.root / "00-user-provided/material-index.json").read_text())
        self.assertEqual(len(index["assets"]), 2)
        self.assertEqual(len(index["materials"]), 3)
        self.assertEqual(index["materials"][1]["asset_id"], index["materials"][2]["asset_id"])

    def test_real_cli_inline_stdin_and_resume_from_another_directory(self):
        content = '  中文逐字稿 🚀\r\n引号 " 与 $HOME 保持原样。\n'
        command = [sys.executable, str(SKILL / "scripts/initialize_video_job.py")]
        result = subprocess.run(
            command + ["--project-root", str(PROJECT), "--jobs-root", str(self.jobs),
                       "--title", "CLI 空格测试", "--video", str(self.video), "--script-stdin"],
            input=content.encode("utf-8"), capture_output=True, cwd=self.root, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        context = json.loads(result.stdout)
        self.assertEqual(Path(context["script"]).read_bytes(), content.encode("utf-8"))
        workflow = Path(context["workflow"])
        before = (workflow.read_bytes(), workflow.stat().st_mtime_ns)
        self.video.unlink()
        resumed = subprocess.run(
            command + ["--resume-workspace", context["workspace"]],
            capture_output=True, cwd=self.root, check=False,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr.decode())
        self.assertEqual(json.loads(resumed.stdout), context)
        self.assertEqual((workflow.read_bytes(), workflow.stat().st_mtime_ns), before)
        self.assertEqual(len(list(self.jobs.iterdir())), 1)

    def test_real_cli_refuses_mixed_resume_and_new_input_flags(self):
        result = subprocess.run(
            [sys.executable, str(SKILL / "scripts/initialize_video_job.py"),
             "--resume-workspace", str(self.root), "--script-text", "不应导入"],
            capture_output=True, text=True, cwd=self.root, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resume accepts only", result.stderr)
        self.assertFalse(self.jobs.exists())


if __name__ == "__main__":
    unittest.main()

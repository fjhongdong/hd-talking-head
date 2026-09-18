"""Material changes use tiny files, real state, and no media processes."""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
import fcntl
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import initialize_video_job as initializer
from edit.hd.tools import material_usage, state

PROJECT = Path(state.__file__).resolve().parents[3]


class MaterialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.video = self.root / "口播.mp4"
        self.script = self.root / "文案.md"
        self.image = self.root / "参考.png"
        for path, data in ((self.video, b"video"), (self.script, b"script"),
                           (self.image, b"image")):
            path.write_bytes(data)
        manifest = SKILL / "release-manifest.json"
        release = {"status": "pass", "root": str(SKILL), "failures": [],
                   "release_id": json.loads(manifest.read_text())["release_id"],
                   "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
        # Unpublished maintenance code: only bypass the package hash here.
        patcher = mock.patch.object(initializer, "verify_release", return_value=release)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job, _ = initializer.initialize_video_job(
            self.root / "jobs", "资料测试", self.video, self.script,
            user_files=[self.image], project_root=PROJECT,
        )
        self.index_path = self.job.root / "00-user-provided/material-index.json"
        self.workflow = self.job.job_dir / "workflow.json"

    def api(self):
        self.assertTrue((SKILL / "scripts/manage_user_materials.py").is_file(),
                        "unique material-change entrypoint is missing")
        return importlib.import_module("manage_user_materials")

    def plan(self, operation="append", **kwargs):
        return self.api().plan_material_change(
            self.job.root, operation, operation_id="test-change-1", **kwargs,
        )

    def apply(self, plan, *, confirmed=True):
        return self.api().apply_material_change(
            self.job.root,
            plan,
            confirmed_plan_hash=plan["plan_hash"] if confirmed else None,
        )

    def index(self):
        return json.loads(self.index_path.read_text())

    def approve_visual_usage(self, segment_ids=("seg-001", "seg-002")):
        producers = {
            "inspect": "edit.hd.tools.inspect_inputs",
            "content_analysis": "edit.hd.tools.content_analysis",
            "cover_direction": "edit.hd.tools.cover_direction",
            "cover": "edit.hd.tools.cover",
            "speech_cleanup": "edit.hd.tools.speech_cleanup",
            "edit_structure": "edit.hd.tools.edit_structure",
        }
        directories = {
            "inspect": "01-inspect",
            "content_analysis": "02-content-analysis",
            "cover_direction": "03-cover-direction",
            "cover": "04-cover",
            "speech_cleanup": "05-speech-cleanup",
            "edit_structure": "06-edit-structure",
        }
        with mock.patch("edit.hd.tools.startup.require_startup"):
            for stage_id in (
                "inspect",
                "content_analysis",
                "cover_direction",
                "cover",
                "speech_cleanup",
                "edit_structure",
            ):
                artifact = self.job.job_dir / directories[stage_id] / "fixture.json"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text('{"fixture":true}\n')
                material_usage.publish_and_mark_ready(
                    self.job,
                    stage_id,
                    (artifact,),
                    producer=producers[stage_id],
                    producer_version="test",
                    stage_input_records=material_usage.current_stage_input_records(
                        self.job, stage_id
                    ),
                    references=[],
                )
                state.approve(self.job, stage_id)

        target = self.index()["materials"][2]
        artifact = self.job.job_dir / "07-visual-direction/visual-plan.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"schema_version":3}\n')
        references = [
            {
                "material_id": target["material_id"],
                "material_sha256": target["sha256"],
                "consumer_kind": "visual_segment",
                "consumer_id": segment_id,
                "binding_path": f"/segments/{index}/bindings/base/material_id",
                "artifact_paths": [
                    "07-visual-direction/visual-plan.json"
                ],
            }
            for index, segment_id in enumerate(segment_ids)
        ]
        with mock.patch("edit.hd.tools.startup.require_startup"):
            material_usage.publish_and_mark_ready(
                self.job,
                "visual_direction",
                (artifact,),
                producer="edit.hd.tools.visual_plan",
                producer_version="test",
                stage_input_records=material_usage.current_stage_input_records(
                    self.job, "visual_direction"
                ),
                references=references,
            )
            state.approve(self.job, "visual_direction")

    def test_append_preserves_workflow_and_originals(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (self.workflow, self.video, self.script, self.image)}
        plan = self.plan(source=self.image)
        result = self.apply(plan)
        self.assertEqual(result["material_revision"], 1)
        self.assertEqual(len(self.index()["assets"]), 3)
        self.assertEqual(len(self.index()["materials"]), 4)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_replace_keeps_old_bytes_and_allocates_new_id(self):
        replacement = self.root / "新图.png"
        replacement.write_bytes(b"new-image")
        old = self.index()["materials"][2]
        result = self.apply(self.plan("replace", source=replacement, material_id=old["material_id"]))
        retired = self.index()["materials"][2]
        self.assertEqual(retired["status"], "superseded")
        self.assertEqual(retired["sha256"], old["sha256"])
        self.assertEqual((self.job.root / old["imported_path"]).read_bytes(), b"image")
        self.assertNotEqual(result["material_id"], old["material_id"])

    def test_primary_input_cannot_be_replaced_or_withdrawn(self):
        for operation in ("replace", "withdraw"):
            plan = self.plan(operation, material_id="material-0001",
                             **({"source": self.image} if operation == "replace" else {}))
            self.assertIn("primary_input", plan["blockers"])
            with self.assertRaises(self.api().MaterialChangeError):
                self.apply(plan)

    def test_receipts_report_every_segment_and_plan_precise_revision(self):
        self.approve_visual_usage()
        plan = self.plan("withdraw", material_id="material-0003")
        self.assertEqual(
            [item["consumer_id"] for item in plan["direct_references"]],
            ["seg-001", "seg-002"],
        )
        self.assertEqual(plan["earliest_stage"], "visual_direction")
        self.assertEqual(plan["artifact_scope"], ["seg-001", "seg-002"])
        self.assertEqual(plan["workflow_action"], "revise")
        self.assertIn("visual_assets", plan["affected_stages"])
        self.assertIn("delivery", plan["affected_stages"])
        self.assertEqual(plan["blockers"], [])

    def test_used_replacement_revises_once_after_confirmed_plan(self):
        self.approve_visual_usage(("seg-009",))
        replacement = self.root / "new-reference.png"
        replacement.write_bytes(b"new-reference")
        plan = self.plan(
            "replace", source=replacement, material_id="material-0003"
        )
        with mock.patch.object(state, "revise", wraps=state.revise) as revise:
            result = self.apply(plan)
        revise.assert_called_once()
        self.assertEqual(result["workflow_action"], "revise")
        self.assertEqual(result["artifact_scope"], ["seg-009"])
        current = state.load_job(self.job.job_dir)
        self.assertEqual(current.stages["visual_direction"]["status"], "needs_revision")

    def test_used_revision_failure_resumes_without_duplicate_material_commit(self):
        self.approve_visual_usage(("seg-009",))
        replacement = self.root / "retry-reference.png"
        replacement.write_bytes(b"retry-reference")
        plan = self.plan(
            "replace", source=replacement, material_id="material-0003"
        )
        revision_before = state.load_job(self.job.job_dir).revision
        with mock.patch("edit.hd.tools.startup.require_startup"), mock.patch.object(
            state, "revise", side_effect=RuntimeError("injected revise failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.apply(plan)
        self.assertEqual(self.index()["material_revision"], 1)
        self.assertEqual(len(self.index()["changes"]), 1)

        with mock.patch("edit.hd.tools.startup.require_startup"):
            result = self.apply(plan)
        self.assertEqual(result["workflow_revision_after"], revision_before + 1)
        self.assertEqual(self.index()["material_revision"], 1)
        self.assertEqual(len(self.index()["changes"]), 1)

    def test_planning_is_strictly_read_only(self):
        before = {
            path.relative_to(self.job.root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.job.root.rglob("*")
            if path.is_file()
        }
        revision = state.load_job(self.job.job_dir).revision
        plan = self.plan("withdraw", material_id="material-0003")
        after = {
            path.relative_to(self.job.root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.job.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertEqual(state.load_job(self.job.job_dir).revision, revision)
        self.assertEqual(plan["required_human_gates"], ["confirm_material_change_plan"])

    def test_apply_requires_the_exact_human_confirmed_plan_hash(self):
        plan = self.plan(source=self.image)
        with self.assertRaisesRegex(self.api().MaterialChangeError, "confirmation"):
            self.apply(plan, confirmed=False)
        with self.assertRaisesRegex(self.api().MaterialChangeError, "confirmation"):
            self.api().apply_material_change(
                self.job.root,
                plan,
                confirmed_plan_hash="0" * 64,
            )

    def test_replay_after_commit_needs_no_original_and_no_new_revision(self):
        plan = self.plan(source=self.image)
        result = self.apply(plan)
        before = self.index_path.read_bytes()
        self.image.unlink()
        self.assertEqual(self.apply(plan), result)
        self.assertEqual(self.index_path.read_bytes(), before)

    def test_same_operation_id_cannot_be_reused_for_another_plan(self):
        self.apply(self.plan(source=self.image))
        with self.assertRaisesRegex(self.api().MaterialChangeError, "operation ID"):
            self.apply(self.plan(source=self.script))

    def test_stale_index_preserves_annotations_and_does_not_apply_old_plan(self):
        plan = self.plan(source=self.image)
        index = self.index()
        index["materials"][2]["topics"] = ["人物身份"]
        self.index_path.write_text(json.dumps(index))
        with self.assertRaisesRegex(self.api().MaterialChangeError, "stale"):
            self.apply(plan)
        self.apply(self.plan(source=self.image))
        self.assertEqual(self.index()["materials"][2]["topics"], ["人物身份"])

    def test_source_change_rejects_stale_plan(self):
        plan = self.plan(source=self.image)
        before = self.index_path.read_bytes()
        self.image.write_bytes(b"different-image")
        with self.assertRaisesRegex(self.api().MaterialChangeError, "stale"):
            self.apply(plan)
        self.assertEqual(self.index_path.read_bytes(), before)

    def test_workflow_change_rejects_stale_plan(self):
        plan = self.plan(source=self.image)
        state.revise(self.job, "inspect", "fixture unrelated revision")
        with self.assertRaisesRegex(self.api().MaterialChangeError, "stale"):
            self.apply(plan)

    def test_unknown_draft_is_not_treated_as_unused(self):
        path = self.job.job_dir / "04-cover/unknown.bin"
        path.write_bytes(b"not a reference manifest")
        plan = self.plan("withdraw", material_id="material-0003")
        self.assertEqual(plan["direct_references"], [])
        self.assertEqual(plan["unverified_stages"], [])
        self.assertEqual(plan["workflow_action"], "preserve")
        self.apply(plan)

    def test_formal_legacy_stage_without_receipt_fails_closed(self):
        artifact = self.job.job_dir / "01-inspect/legacy.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n")
        with mock.patch("edit.hd.tools.startup.require_startup"):
            state.mark_ready(self.job, "inspect", (artifact,))
            state.approve(self.job, "inspect")
        plan = self.plan("withdraw", material_id="material-0003")
        self.assertEqual(plan["direct_references"], [])
        self.assertEqual(plan["unverified_stages"], ["inspect"])
        self.assertIn("material_usage_unverified", plan["blockers"])
        with self.assertRaises(self.api().MaterialChangeError):
            self.apply(plan)

    def test_append_does_not_reset_existing_drafts(self):
        path = self.job.job_dir / "04-cover/approved-reference.png"
        path.write_bytes(b"keep")
        before = (path.read_bytes(), path.stat().st_mtime_ns, self.workflow.read_bytes())
        self.apply(self.plan(source=self.image))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, self.workflow.read_bytes()), before)

    def test_append_preserves_real_state_engine_approvals(self):
        # This fixture tests state preservation, not provider connectivity or
        # approval of actual media. Do not run preflight/generation in this test.
        with mock.patch("edit.hd.tools.startup.require_startup"):
            for stage, directory in (("inspect", "01-inspect"),
                                     ("content_analysis", "02-content-analysis"),
                                     ("cover_direction", "03-cover-direction"),
                                     ("cover", "04-cover")):
                path = self.job.job_dir / directory / "fixture.json"
                path.write_text('{"fixture": "state-only"}')
                state.mark_ready(self.job, stage, [path])
                state.approve(self.job, stage)
        before = self.workflow.read_bytes()
        self.apply(self.plan(source=self.image))
        loaded = state.load_job(self.job.job_dir)
        self.assertEqual(loaded.stages["cover"]["status"], "approved")
        self.assertEqual(loaded.stages["content_analysis"]["status"], "approved")
        self.assertEqual(loaded.revision, self.job.revision)
        self.assertEqual(self.workflow.read_bytes(), before)

    def test_withdraw_retains_bytes_and_blocks_active_lookup(self):
        old = self.index()["materials"][2]
        self.apply(self.plan("withdraw", material_id=old["material_id"]))
        self.assertEqual(self.index()["materials"][2]["status"], "withdrawn")
        self.assertEqual((self.job.root / old["imported_path"]).read_bytes(), b"image")
        with self.assertRaisesRegex(self.api().MaterialChangeError, "withdrawn"):
            self.api().require_active_material(self.job.root, old["material_id"])

    def test_cover_lookup_rejects_withdrawn_material(self):
        from edit.hd.tools import cover_direction
        self.apply(self.plan("withdraw", material_id="material-0003"))
        with self.assertRaises(cover_direction.CoverDirectionError):
            cover_direction._user_material(self.job, "material-0003")

    def test_broll_lookup_rejects_retired_material_even_if_copy_survives(self):
        from edit.hd.tools import broll_media
        from edit.hd.tests.test_broll_media import _component, _recipe
        self.apply(self.plan("withdraw", material_id="material-0003"))
        imported = self.index()["materials"][2]
        copy_path = self.job.job_dir / "09-visual-assets/official/copy.png"
        copy_path.write_bytes(b"image")
        component = _component("local-photo", "local_material", path="09-visual-assets/official/copy.png")
        component.update(material_id="material-0003", sha256=imported["sha256"])
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_active_broll_copy_remains_usable(self):
        from edit.hd.tools import broll_media
        from edit.hd.tests.test_broll_media import _component, _recipe
        imported = self.index()["materials"][2]
        copy_path = self.job.job_dir / "09-visual-assets/official/copy.png"
        copy_path.write_bytes(b"image")
        component = _component("local-photo", "local_material", path="09-visual-assets/official/copy.png")
        component.update(material_id="material-0003", sha256=imported["sha256"])
        result = broll_media.resolve_recipe_media(self.job, _recipe([component]))
        self.assertEqual(result[0].sha256, imported["sha256"])

    def test_failed_index_publish_leaves_no_partial_record_and_can_retry(self):
        new_file = self.root / "new.png"
        new_file.write_bytes(b"new asset")
        plan = self.plan(source=new_file)
        before = self.index_path.read_bytes()
        with mock.patch.object(self.api(), "_write_json_atomic", side_effect=OSError("injected commit failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.apply(plan)
        self.assertEqual(self.index_path.read_bytes(), before)
        self.assertEqual(self.apply(plan)["material_revision"], 1)
        self.assertEqual(len(self.index()["materials"]), 4)

    def test_error_after_index_commit_is_replayable(self):
        plan = self.plan(source=self.image)
        writer = self.api()._write_json_atomic

        def publish_then_fail(*args):
            writer(*args)
            raise OSError("injected post-commit failure")

        with mock.patch.object(self.api(), "_write_json_atomic", side_effect=publish_then_fail):
            with self.assertRaises(OSError):
                self.apply(plan)
        self.assertEqual(self.apply(plan)["material_revision"], 1)
        self.assertEqual(len(self.index()["changes"]), 1)

    def test_duplicate_index_ids_are_rejected(self):
        index = self.index()
        index["materials"].append(dict(index["materials"][0]))
        self.index_path.write_text(json.dumps(index))
        with self.assertRaises(self.api().MaterialChangeError):
            self.plan(source=self.image)

    def test_symlink_source_is_rejected(self):
        source = self.root / "linked.png"
        source.symlink_to(self.image)
        with self.assertRaises(self.api().MaterialChangeError):
            self.plan(source=source)

    def test_external_paths_in_index_are_rejected(self):
        index = self.index()
        index["assets"][2]["imported_path"] = str(self.image)
        self.index_path.write_text(json.dumps(index))
        with self.assertRaises(self.api().MaterialChangeError):
            self.plan(source=self.image)

    def test_corrupt_imported_asset_is_rejected(self):
        (self.job.root / self.index()["materials"][2]["imported_path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(self.api().MaterialChangeError, "identity changed"):
            self.plan(source=self.image)

    def test_changed_plan_and_cross_workspace_are_rejected(self):
        plan = self.plan(source=self.image)
        plan["blockers"] = ["fake"]
        with self.assertRaisesRegex(self.api().MaterialChangeError, "plan identity"):
            self.apply(plan)

    def test_material_lock_rejects_parallel_operation(self):
        plan = self.plan(source=self.image)
        with (self.job.root / "00-user-provided/.materials.lock").open("w") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(self.api().MaterialChangeError, "another material"):
                self.apply(plan)

    def test_missing_index_fails_closed_for_managed_broll(self):
        from edit.hd.tools import broll_media
        from edit.hd.tests.test_broll_media import _component, _recipe
        imported = self.index()["materials"][2]
        copy_path = self.job.job_dir / "09-visual-assets/official/copy.png"
        copy_path.write_bytes(b"image")
        component = _component("local-photo", "local_material", path="09-visual-assets/official/copy.png")
        component.update(material_id="material-0003", sha256=imported["sha256"])
        self.index_path.unlink()
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_copy_corruption_does_not_publish_material_record(self):
        source = self.root / "new.png"
        source.write_bytes(b"new image")
        plan = self.plan(source=source)
        before = self.index_path.read_bytes()

        def corrupt_copy(src, dst, size):
            dst.write(b"corrupt")

        with mock.patch.object(self.api().shutil, "copyfileobj", side_effect=corrupt_copy):
            with self.assertRaisesRegex(self.api().MaterialChangeError, "during copy"):
                self.apply(plan)
        self.assertEqual(self.index_path.read_bytes(), before)
        self.assertEqual(source.read_bytes(), b"new image")

    def test_replacement_id_is_active_and_old_id_is_rejected(self):
        source = self.root / "new.png"
        source.write_bytes(b"new image")
        result = self.apply(self.plan("replace", material_id="material-0003", source=source))
        with self.assertRaises(self.api().MaterialChangeError):
            self.api().require_active_material(self.job.root, "material-0003")
        self.assertEqual(self.api().require_active_material(self.job.root, result["material_id"])["sha256"],
                         hashlib.sha256(b"new image").hexdigest())

    def test_cli_plan_apply_and_replay_outside_project_with_real_release_check(self):
        command = [sys.executable, str(SKILL / "scripts/manage_user_materials.py"),
                   "--workspace", str(self.job.root)]
        planned = subprocess.run(command + ["plan", "append", "--operation-id", "cli-check-1",
                                 "--source", str(self.image)], cwd=self.root,
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        path = self.job.job_dir / "manifests/material-plan.json"
        path.write_text(planned.stdout)
        before = self.workflow.read_bytes()
        results = []
        for _ in range(2):
            result = subprocess.run(command + ["apply", "--plan", str(path),
                                    "--confirmed-plan-hash", json.loads(planned.stdout)["plan_hash"]], cwd=self.root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(json.loads(result.stdout))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.workflow.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

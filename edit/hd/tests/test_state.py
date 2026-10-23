import copy
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import edit.hd.tools.state as state_module
from edit.hd.tools.state import (
    STAGE_IDS,
    STAGE_STATUSES,
    WorkflowError,
    approve,
    block,
    create_job,
    load_job,
    mark_ready,
    require_runnable,
    revise,
    save_job,
)


class WorkflowStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.txt"
        self.video.write_bytes(b"video-source")
        self.script.write_text("test script", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def create(self):
        return create_job(self.root, self.video, self.script, profile="legacy-v1")

    def create_full_v2(self):
        return create_job(
            self.root, self.video, self.script, profile="full-v2"
        )

    def approve_full_v2(self):
        job = self.create_full_v2()
        for stage_id in state_module.FULL_V2_STAGE_IDS:
            artifact = self.artifact(
                job, stage_id=stage_id, content=stage_id.encode("utf-8")
            )
            mark_ready(job, stage_id, [artifact])
            approve(job, stage_id)
        return job

    def artifact(self, job, stage_id="inspect", content=b"artifact"):
        artifact = job.job_dir / stage_id / "result.bin"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_bytes(content)
        return artifact

    def workflow_payload(self, job):
        return json.loads((job.job_dir / "workflow.json").read_text(encoding="utf-8"))

    def overwrite_workflow(self, job, payload):
        (job.job_dir / "workflow.json").write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=True) + "\n",
            encoding="utf-8",
        )

    def test_create_job_only_inspect_is_runnable(self):
        job = self.create()

        require_runnable(job, "inspect")
        with self.assertRaises(WorkflowError):
            require_runnable(job, "speech_cleanup")

    def test_explicit_full_v2_job_uses_twelve_stage_review_order(self):
        job = self.create_full_v2()

        self.assertEqual(job.version, 2)
        self.assertEqual(tuple(job.stages), state_module.FULL_V2_STAGE_IDS)
        self.assertEqual(state_module.current_stage(job), "inspect")

    def test_version_one_job_loads_without_inserting_new_stages(self):
        job = self.create()

        loaded = load_job(job.job_dir)

        self.assertEqual(loaded.version, 1)
        self.assertEqual(
            state_module.stage_ids_for(loaded), state_module.LEGACY_V1_STAGE_IDS
        )
        self.assertNotIn("content_analysis", loaded.stages)

    def test_full_v2_review_order_is_single_even_across_dag_branches(self):
        job = self.create_full_v2()
        artifact = self.artifact(job, "inspect", b"inspect")
        mark_ready(job, "inspect", [artifact])
        approve(job, "inspect")

        self.assertEqual(state_module.current_stage(job), "content_analysis")
        require_runnable(job, "content_analysis")
        with self.assertRaises(WorkflowError):
            require_runnable(job, "speech_cleanup")

    def test_revising_full_v2_cover_keeps_visual_and_subtitles_approved(self):
        job = self.approve_full_v2()

        revise(job, "cover", "调整封面人物动作")

        self.assertEqual(job.stages["cover"]["status"], "needs_revision")
        self.assertEqual(job.stages["preview"]["status"], "pending")
        self.assertEqual(job.stages["delivery"]["status"], "pending")
        self.assertEqual(job.stages["visual_assets"]["status"], "approved")
        self.assertEqual(job.stages["subtitles"]["status"], "approved")

    def test_full_v2_visual_revision_records_segment_scope(self):
        job = self.approve_full_v2()

        revise(
            job,
            "visual_assets",
            "只修正第七个镜头",
            artifact_scope=("segment-07",),
        )

        self.assertEqual(
            job.stages["visual_assets"]["artifact_scope"], ["segment-07"]
        )
        self.assertEqual(job.stages["cover"]["status"], "approved")
        self.assertEqual(job.stages["preview"]["status"], "pending")
        self.assertEqual(job.stages["delivery"]["status"], "pending")

    def test_approval_requires_ready_and_unlocks_next_stage(self):
        job = self.create()
        artifact = job.job_dir / "inspect" / "report.json"
        artifact.parent.mkdir()
        artifact.write_text("{}\n", encoding="utf-8")

        with self.assertRaises(WorkflowError):
            approve(job, "inspect")
        mark_ready(job, "inspect", [artifact])
        approve(job, "inspect")

        self.assertEqual(job.stages["inspect"]["status"], "approved")
        require_runnable(job, "speech_cleanup")

    def test_blocked_stage_cannot_run_or_unlock_downstream(self):
        job = self.create()
        block(job, "inspect", "AI unavailable", 2)

        self.assertEqual(job.stages["inspect"]["status"], "blocked")
        self.assertEqual(job.stages["inspect"]["ai_attempts"], 2)
        with self.assertRaises(WorkflowError):
            require_runnable(job, "inspect")
        with self.assertRaises(WorkflowError):
            require_runnable(job, "speech_cleanup")
        with self.assertRaises(WorkflowError):
            block(job, "inspect", "retry", True)

    def test_revise_resets_current_and_downstream_bindings(self):
        job = self.create()
        for stage_id in STAGE_IDS[:3]:
            artifact = job.job_dir / stage_id / "result.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(stage_id.encode())
            mark_ready(job, stage_id, [artifact])
            approve(job, stage_id)

        revise(job, "speech_cleanup", "tighten cuts")

        self.assertEqual(job.stages["inspect"]["status"], "approved")
        self.assertEqual(job.stages["speech_cleanup"]["status"], "needs_revision")
        self.assertEqual(job.stages["speech_cleanup"]["artifacts"], [])
        for stage_id in STAGE_IDS[2:]:
            self.assertEqual(job.stages[stage_id]["status"], "pending")
            self.assertEqual(job.stages[stage_id]["artifacts"], [])

    def test_revise_atomically_records_the_trigger_and_event_revision_downstream(self):
        job = self.create()
        for stage_id in STAGE_IDS[:3]:
            artifact = job.job_dir / stage_id / "result.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(stage_id.encode())
            mark_ready(job, stage_id, [artifact])
            approve(job, stage_id)
        event_revision = job.revision + 1

        revise(job, "speech_cleanup", "correct transcript")

        self.assertIsNone(
            state_module._cascade_event(job.stages["speech_cleanup"]["reason"])
        )
        for stage_id in STAGE_IDS[2:]:
            self.assertEqual(
                state_module._cascade_event(job.stages[stage_id]["reason"]),
                {"trigger_stage": "speech_cleanup", "revision": event_revision},
            )
        self.assertEqual(load_job(job.job_dir).stages, job.stages)

    def test_save_job_cannot_introduce_a_forged_cascade_event(self):
        job = self.create()
        before = (job.job_dir / "workflow.json").read_bytes()
        job.stages["inspect"].update(
            status="needs_revision",
            reason="forged revise",
        )
        for stage_id in STAGE_IDS[1:]:
            job.stages[stage_id]["reason"] = state_module._cascade_reason("inspect", 1)
        job.revision = 1

        with self.assertRaises(WorkflowError):
            save_job(job)

        self.assertEqual((job.job_dir / "workflow.json").read_bytes(), before)

    def test_existing_cascade_pending_stage_is_frozen_against_ordinary_save_job(self):
        attacks = (
            "status", "reason", "artifacts", "ai_attempts", "lineage", "replay",
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                self.video.write_bytes(f"video-{attack}".encode("utf-8"))
                job = self.create()
                artifacts = {}
                for stage_id in STAGE_IDS[:5]:
                    artifact = self.artifact(
                        job, stage_id=stage_id, content=stage_id.encode("utf-8")
                    )
                    artifacts[stage_id] = artifact
                    mark_ready(job, stage_id, [artifact])
                    approve(job, stage_id)
                revise(job, "speech_cleanup", "correct upstream transcript")
                pending = job.stages["visual_assets"]
                self.assertIsNotNone(state_module._cascade_event(pending["reason"]))
                before_workflow = (job.job_dir / "workflow.json").read_bytes()
                before_stage = copy.deepcopy(
                    load_job(job.job_dir).stages["visual_assets"]
                )

                if attack == "status":
                    pending.update(status="blocked", reason="forged block")
                elif attack == "reason":
                    pending["reason"] = None
                elif attack == "artifacts":
                    source = artifacts["visual_assets"]
                    pending["artifacts"] = [{
                        "path": source.relative_to(job.job_dir).as_posix(),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "bytes": source.stat().st_size,
                    }]
                elif attack == "ai_attempts":
                    pending["ai_attempts"] = 1
                elif attack == "replay":
                    job.revision += 1
                else:
                    foreign = artifacts["visual_assets"].with_name(
                        "foreign-owned.bin"
                    )
                    foreign.write_bytes(b"foreign-owned\n")
                    file_status = foreign.stat()
                    parent_status = foreign.parent.stat()
                    pending["lineage"].append({
                        "path": foreign.relative_to(job.job_dir).as_posix(),
                        "sha256": hashlib.sha256(foreign.read_bytes()).hexdigest(),
                        "bytes": foreign.stat().st_size,
                        "device": file_status.st_dev,
                        "inode": file_status.st_ino,
                        "parent_device": parent_status.st_dev,
                        "parent_inode": parent_status.st_ino,
                    })

                with self.assertRaises(WorkflowError):
                    save_job(job)

                self.assertEqual(
                    (job.job_dir / "workflow.json").read_bytes(), before_workflow
                )
                self.assertEqual(
                    load_job(job.job_dir).stages["visual_assets"], before_stage
                )

    def test_authorized_resolution_can_finish_or_block_a_cascade_pending_stage(self):
        for resolution in ("ready", "blocked"):
            with self.subTest(resolution=resolution):
                self.video.write_bytes(f"video-{resolution}".encode("utf-8"))
                job = self.create()
                artifacts = {}
                for stage_id in STAGE_IDS[:5]:
                    artifact = self.artifact(
                        job, stage_id=stage_id, content=stage_id.encode("utf-8")
                    )
                    artifacts[stage_id] = artifact
                    mark_ready(job, stage_id, [artifact])
                    approve(job, stage_id)
                revise(job, "speech_cleanup", "correct upstream transcript")
                for stage_id in (
                    "speech_cleanup", "edit_structure", "visual_direction"
                ):
                    mark_ready(job, stage_id, [artifacts[stage_id]])
                    approve(job, stage_id)

                if resolution == "ready":
                    mark_ready(job, "visual_assets", [artifacts["visual_assets"]])
                    self.assertEqual(
                        job.stages["visual_assets"]["status"], "ready_for_review"
                    )
                else:
                    block(job, "visual_assets", "AI unavailable", 1)
                    self.assertEqual(
                        job.stages["visual_assets"]["status"], "blocked"
                    )

    def test_revise_captures_exact_artifact_and_parent_lineage(self):
        job = self.create()
        artifacts = {}
        for stage_id in STAGE_IDS[:3]:
            artifact = job.job_dir / stage_id / "result.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(stage_id.encode())
            artifacts[stage_id] = artifact
            mark_ready(job, stage_id, [artifact])
            approve(job, stage_id)

        revise(job, "speech_cleanup", "capture lineage")

        self.assertEqual(job.stages["inspect"]["lineage"], [])
        for stage_id in STAGE_IDS[1:3]:
            artifact = artifacts[stage_id]
            file_status = artifact.stat()
            parent_status = artifact.parent.stat()
            self.assertEqual(job.stages[stage_id]["lineage"], [{
                "path": artifact.relative_to(job.job_dir).as_posix(),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "bytes": artifact.stat().st_size,
                "device": file_status.st_dev,
                "inode": file_status.st_ino,
                "parent_device": parent_status.st_dev,
                "parent_inode": parent_status.st_ino,
            }])
        self.assertEqual(load_job(job.job_dir).stages, job.stages)

    def test_revise_rejects_same_inode_and_replacement_drift_atomically(self):
        for attack in ("same_inode", "replacement"):
            with self.subTest(attack=attack):
                self.video.write_bytes(attack.encode())
                job = self.create()
                artifact = self.artifact(job, content=b"original")
                mark_ready(job, "inspect", [artifact])
                approve(job, "inspect")
                workflow = job.job_dir / "workflow.json"
                before_workflow = workflow.read_bytes()
                before_stages = copy.deepcopy(job.stages)
                before_revision = job.revision
                real_verify = state_module._verify_pins
                attacked = False

                def drift(pins):
                    nonlocal attacked
                    real_verify(pins)
                    if not attacked:
                        attacked = True
                        if attack == "same_inode":
                            artifact.write_bytes(b"changed!")
                        else:
                            held = artifact.with_name("held-result.bin")
                            os.replace(artifact, held)
                            artifact.write_bytes(b"original")

                with mock.patch.object(state_module, "_verify_pins", side_effect=drift):
                    with self.assertRaises(WorkflowError):
                        revise(job, "inspect", "drift")
                self.assertTrue(attacked)
                self.assertEqual(workflow.read_bytes(), before_workflow)
                self.assertEqual(job.stages, before_stages)
                self.assertEqual(job.revision, before_revision)

    def test_revise_pin_keyboard_interrupt_preserves_primary_despite_close_fault(self):
        job = self.create()
        artifact = self.artifact(job)
        mark_ready(job, "inspect", [artifact])
        approve(job, "inspect")
        workflow = job.job_dir / "workflow.json"
        before_workflow = workflow.read_bytes()
        before_stages = copy.deepcopy(job.stages)
        before_revision = job.revision
        before_descriptors = len(os.listdir("/dev/fd"))
        real_pin = state_module._pin_record
        real_close = state_module._close_descriptor

        def interrupt_artifact(base, record):
            if record["path"] == "inspect/result.bin":
                raise KeyboardInterrupt()
            return real_pin(base, record)

        def close_then_report(descriptor):
            error = real_close(descriptor)
            return error or OSError("close fault")

        with mock.patch.object(state_module, "_pin_record", side_effect=interrupt_artifact), \
                mock.patch.object(state_module, "_close_descriptor", side_effect=close_then_report):
            with self.assertRaises(KeyboardInterrupt):
                revise(job, "inspect", "pin failure")
        self.assertEqual(workflow.read_bytes(), before_workflow)
        self.assertEqual(job.stages, before_stages)
        self.assertEqual(job.revision, before_revision)
        self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)

    def test_revise_preserves_empty_artifact_lineage_mark_ready_clears_and_block_keeps(self):
        record = {
            "path": "old/result.bin", "sha256": "a" * 64, "bytes": 3,
            "device": 1, "inode": 2, "parent_device": 1, "parent_inode": 3,
        }
        job = self.create()
        mark_ready(job, "inspect", [self.artifact(job)])
        approve(job, "inspect")
        job.stages["speech_cleanup"]["lineage"] = [record]
        save_job(job)
        revise(job, "speech_cleanup", "keep lineage")
        self.assertEqual(job.stages["speech_cleanup"]["lineage"], [record])

        self.video.write_bytes(b"blocked-lineage")
        blocked = self.create()
        blocked.stages["inspect"]["lineage"] = [record]
        save_job(blocked)
        block(blocked, "inspect", "unavailable", 0)
        self.assertEqual(blocked.stages["inspect"]["lineage"], [record])

        self.video.write_bytes(b"ready-lineage")
        ready = self.create()
        ready.stages["inspect"]["lineage"] = [record]
        save_job(ready)
        mark_ready(ready, "inspect", [self.artifact(ready)])
        self.assertEqual(ready.stages["inspect"]["lineage"], [])

    def test_stage_constants_are_fixed(self):
        self.assertEqual(
            STAGE_IDS,
            (
                "inspect",
                "speech_cleanup",
                "edit_structure",
                "visual_direction",
                "visual_assets",
                "subtitles",
                "cover",
                "preview",
                "delivery",
            ),
        )
        self.assertEqual(
            STAGE_STATUSES,
            ("pending", "ready_for_review", "approved", "needs_revision", "blocked"),
        )

    def test_artifacts_are_regular_bound_files_relative_to_job(self):
        job = self.create()
        artifact = self.artifact(job, content=b"bound artifact")

        mark_ready(job, "inspect", [artifact])

        record = job.stages["inspect"]["artifacts"][0]
        self.assertEqual(record["path"], "inspect/result.bin")
        self.assertEqual(record["sha256"], hashlib.sha256(b"bound artifact").hexdigest())
        self.assertEqual(record["bytes"], len(b"bound artifact"))

    def test_artifacts_reject_missing_directory_outside_and_symlink(self):
        for kind in ("missing", "directory", "outside", "symlink"):
            with self.subTest(kind=kind):
                job = self.create()
                if kind == "missing":
                    artifact = job.job_dir / "missing.bin"
                elif kind == "directory":
                    artifact = job.job_dir / "artifact-dir"
                    artifact.mkdir()
                elif kind == "outside":
                    artifact = self.root / "outside.bin"
                    artifact.write_bytes(b"outside")
                else:
                    target = self.artifact(job)
                    artifact = job.job_dir / "artifact-link"
                    artifact.symlink_to(target)
                with self.assertRaises(WorkflowError):
                    mark_ready(job, "inspect", [artifact])

    def test_changed_artifact_fails_closed_before_approval(self):
        job = self.create()
        artifact = self.artifact(job, content=b"first")
        mark_ready(job, "inspect", [artifact])
        artifact.write_bytes(b"changed")

        with self.assertRaises(WorkflowError):
            approve(job, "inspect")

    def test_job_id_and_input_bindings_are_stable_safe_and_content_derived(self):
        first = self.create()
        second = create_job(self.root, self.video, self.script, profile="legacy-v1")

        self.assertEqual(first.job_id, second.job_id)
        self.assertRegex(first.job_id, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(first.job_dir, self.root / "edit" / "hd" / "jobs" / first.job_id)
        self.assertEqual(first.inputs["video"]["path"], "source.mp4")
        self.assertEqual(first.inputs["video"]["bytes"], len(b"video-source"))
        self.assertEqual(
            first.inputs["video"]["sha256"], hashlib.sha256(b"video-source").hexdigest()
        )

        self.video.write_bytes(b"different video")
        changed = create_job(self.root, self.video, self.script, profile="legacy-v1")
        self.assertNotEqual(changed.job_id, first.job_id)

    def test_changed_inputs_fail_closed_on_load_and_run(self):
        job = self.create()
        self.video.write_bytes(b"tampered")

        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)
        with self.assertRaises(WorkflowError):
            require_runnable(job, "inspect")

    def test_inputs_reject_non_regular_symlink_and_symlink_ancestor_without_path_leak(self):
        bad_inputs = []
        directory = self.root / "directory-input"
        directory.mkdir()
        bad_inputs.append(directory)
        link = self.root / "video-link"
        link.symlink_to(self.video)
        bad_inputs.append(link)
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        nested = real_parent / "nested.mp4"
        nested.write_bytes(b"nested")
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        bad_inputs.append(linked_parent / "nested.mp4")

        for bad_input in bad_inputs:
            with self.subTest(path=bad_input.name):
                with self.assertRaises(WorkflowError) as raised:
                    create_job(self.root, bad_input, self.script, profile="legacy-v1")
                self.assertNotIn(str(bad_input), str(raised.exception))

    def test_workflow_rejects_duplicate_keys_and_nonfinite_numbers(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        original = workflow.read_text(encoding="utf-8")
        workflow.write_text(original.replace('"version": 1', '"version": 1, "version": 1', 1))
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

        workflow.write_text(original.replace('"revision": 0', '"revision": NaN', 1))
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

        workflow.write_text(original.replace('"revision": 0', '"revision": Infinity', 1))
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

    def test_workflow_requires_exact_schema_known_values_and_exact_ints(self):
        job = self.create()
        original = self.workflow_payload(job)
        mutations = []

        extra = json.loads(json.dumps(original)); extra["extra"] = None
        mutations.append(extra)
        missing = json.loads(json.dumps(original)); del missing["revision"]
        mutations.append(missing)
        unknown_stage = json.loads(json.dumps(original)); unknown_stage["stages"]["unknown"] = unknown_stage["stages"].pop("cover")
        mutations.append(unknown_stage)
        unknown_status = json.loads(json.dumps(original)); unknown_status["stages"]["inspect"]["status"] = "running"
        mutations.append(unknown_status)
        stage_extra = json.loads(json.dumps(original)); stage_extra["stages"]["inspect"]["extra"] = 1
        mutations.append(stage_extra)
        input_extra = json.loads(json.dumps(original)); input_extra["inputs"]["video"]["extra"] = 1
        mutations.append(input_extra)
        bool_revision = json.loads(json.dumps(original)); bool_revision["revision"] = True
        mutations.append(bool_revision)
        bool_size = json.loads(json.dumps(original)); bool_size["inputs"]["video"]["bytes"] = True
        mutations.append(bool_size)
        bool_attempts = json.loads(json.dumps(original)); bool_attempts["stages"]["inspect"]["ai_attempts"] = False
        mutations.append(bool_attempts)
        wrong_version = json.loads(json.dumps(original)); wrong_version["version"] = 2
        mutations.append(wrong_version)

        for payload in mutations:
            with self.subTest(payload=payload):
                self.overwrite_workflow(job, payload)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_lineage_schema_is_new_default_and_only_uniform_legacy_is_accepted(self):
        job = self.create()
        payload = self.workflow_payload(job)
        self.assertTrue(all(stage["lineage"] == [] for stage in payload["stages"].values()))

        legacy = copy.deepcopy(payload)
        for stage in legacy["stages"].values():
            del stage["lineage"]
        self.overwrite_workflow(job, legacy)
        loaded = load_job(job.job_dir)
        self.assertTrue(all(stage["lineage"] == [] for stage in loaded.stages.values()))
        save_job(loaded)
        self.assertTrue(all(
            stage["lineage"] == []
            for stage in self.workflow_payload(loaded)["stages"].values()
        ))

        mixed = copy.deepcopy(legacy)
        mixed["stages"]["inspect"]["lineage"] = []
        self.overwrite_workflow(job, mixed)
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

    def test_lineage_records_are_strict_but_do_not_pin_current_files(self):
        job = self.create()
        payload = self.workflow_payload(job)
        valid = {
            "path": "retired/result.bin", "sha256": "b" * 64, "bytes": 7,
            "device": 4, "inode": 5, "parent_device": 4, "parent_inode": 6,
        }
        payload["stages"]["inspect"]["lineage"] = [valid]
        self.overwrite_workflow(job, payload)
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["lineage"], [valid])

        mutations = []
        for key, value in (
            ("bytes", True), ("device", True), ("inode", 0),
            ("parent_device", -1), ("parent_inode", False), ("path", "../bad"),
        ):
            mutation = copy.deepcopy(payload)
            mutation["stages"]["inspect"]["lineage"][0][key] = value
            mutations.append(mutation)
        extra = copy.deepcopy(payload)
        extra["stages"]["inspect"]["lineage"][0]["extra"] = 1
        mutations.append(extra)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.overwrite_workflow(job, mutation)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_load_rejects_unsafe_job_paths_and_symlinks(self):
        job = self.create()
        bad_strings = (
            str(job.job_dir) + "/../" + job.job_id,
            str(job.job_dir) + "\\child",
            str(job.job_dir) + "\x00child",
        )
        for value in bad_strings:
            with self.subTest(value=repr(value)):
                with self.assertRaises(WorkflowError):
                    load_job(value)

        leaf = job.job_dir.parent / ("f" * 64)
        leaf.symlink_to(job.job_dir, target_is_directory=True)
        with self.assertRaises(WorkflowError):
            load_job(leaf)

        alias_root = self.root.parent / (self.root.name + "-alias")
        alias_root.symlink_to(self.root, target_is_directory=True)
        try:
            aliased_job = alias_root / "edit" / "hd" / "jobs" / job.job_id
            with self.assertRaises(WorkflowError):
                load_job(aliased_job)
        finally:
            alias_root.unlink()

    def test_load_rejects_job_outside_required_layout(self):
        job = self.create()
        misplaced = self.root / job.job_id
        misplaced.mkdir()
        (misplaced / "workflow.json").write_bytes((job.job_dir / "workflow.json").read_bytes())

        with self.assertRaises(WorkflowError):
            load_job(misplaced)

    def test_atomic_save_fsyncs_file_and_directory_and_leaves_no_stage(self):
        job = self.create()
        real_fsync = os.fsync
        modes = []

        def recording_fsync(descriptor):
            modes.append(os.fstat(descriptor).st_mode)
            return real_fsync(descriptor)

        job.revision += 1
        with mock.patch.object(state_module.os, "fsync", side_effect=recording_fsync):
            save_job(job)

        self.assertGreaterEqual(len(modes), 2)
        self.assertTrue(any(stat.S_ISREG(mode) for mode in modes))
        self.assertTrue(any(stat.S_ISDIR(mode) for mode in modes))
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def test_atomic_save_preserves_previous_on_replace_error_and_base_exception(self):
        for failure in (OSError("replace failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                job.revision += 1
                with mock.patch.object(
                    state_module, "_atomic_exchange_rename", side_effect=failure,
                ):
                    with self.assertRaises(type(failure)):
                        save_job(job)
                self.assertEqual(workflow.read_bytes(), previous)
                self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def test_atomic_save_rolls_back_when_directory_fsync_fails(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        job.revision += 1
        real_fsync = os.fsync
        calls = 0

        def fail_directory_fsync_once(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("directory fsync failed")
            return real_fsync(descriptor)

        with mock.patch.object(state_module.os, "fsync", side_effect=fail_directory_fsync_once):
            with self.assertRaises(OSError):
                save_job(job)

        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def test_load_and_operations_reject_impossible_stage_topology(self):
        job = self.create()
        artifact = self.artifact(job, "speech_cleanup", b"review")
        record = {
            "path": "speech_cleanup/result.bin",
            "sha256": hashlib.sha256(b"review").hexdigest(),
            "bytes": len(b"review"),
        }
        payload = self.workflow_payload(job)
        payload["stages"]["speech_cleanup"] = {
            "status": "ready_for_review",
            "reason": None,
            "artifacts": [record],
            "ai_attempts": 0,
        }
        self.overwrite_workflow(job, payload)

        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

        job.stages = payload["stages"]
        with self.assertRaises(WorkflowError):
            approve(job, "speech_cleanup")
        with self.assertRaises(WorkflowError):
            mark_ready(job, "speech_cleanup", [artifact])
        with self.assertRaises(WorkflowError):
            require_runnable(job, "speech_cleanup")

    def test_atomic_save_recovers_when_replace_publishes_then_interrupts(self):
        for existing in (True, False):
            with self.subTest(existing=existing):
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes() if existing else None
                if not existing:
                    workflow.unlink()
                job.revision += 1
                real_exchange = state_module._atomic_exchange_rename
                real_noreplace = state_module._atomic_noreplace_rename

                def publish_then_interrupt(move):
                    def interrupted(source, destination):
                        result = move(source, destination)
                        if (Path(source).name.endswith(".stage")
                                and Path(destination) == workflow):
                            raise KeyboardInterrupt()
                        return result
                    return interrupted

                with mock.patch.object(
                    state_module, "_atomic_exchange_rename",
                    side_effect=publish_then_interrupt(real_exchange),
                ), mock.patch.object(
                    state_module, "_atomic_noreplace_rename",
                    side_effect=publish_then_interrupt(real_noreplace),
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        save_job(job)

                if previous is None:
                    self.assertFalse(workflow.exists())
                else:
                    self.assertEqual(workflow.read_bytes(), previous)
                self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])
                self.assertEqual(list(job.job_dir.glob(".workflow.*.backup")), [])
                self.assertEqual(list(job.job_dir.glob(".workflow.*.marker")), [])

    def test_approve_rolls_back_if_artifact_changes_during_publication(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                if replacement:
                    self.video.write_bytes(b"replacement-video-source")
                job = self.create()
                artifact = self.artifact(job, content=b"bound artifact")
                mark_ready(job, "inspect", [artifact])
                workflow = job.job_dir / "workflow.json"
                ready = workflow.read_bytes()
                original_inode = artifact.stat().st_ino
                real_replace = os.replace
                real_exchange = state_module._atomic_exchange_rename
                changed = False

                def exchange_then_change_artifact(source, destination):
                    nonlocal changed
                    result = real_exchange(source, destination)
                    source_name = Path(source).name
                    if destination == workflow and source_name.endswith(".stage") and not changed:
                        changed = True
                        if replacement:
                            replacement_path = artifact.with_name("replacement.bin")
                            replacement_path.write_bytes(b"replacement artifact")
                            real_replace(replacement_path, artifact)
                        else:
                            artifact.write_bytes(b"changed artifact")
                    return result

                with mock.patch.object(
                    state_module, "_atomic_exchange_rename",
                    side_effect=exchange_then_change_artifact,
                ):
                    with self.assertRaises(WorkflowError):
                        approve(job, "inspect")

                self.assertTrue(changed)
                self.assertEqual(workflow.read_bytes(), ready)
                self.assertEqual(
                    json.loads(workflow.read_text(encoding="utf-8"))["stages"]["inspect"]["status"],
                    "ready_for_review",
                )
                self.assertEqual(job.stages["inspect"]["status"], "ready_for_review")
                self.assertTrue(artifact.exists())
                if not replacement:
                    self.assertEqual(artifact.stat().st_ino, original_inode)

    def test_artifacts_reject_workflow_and_transaction_files_but_allow_unknown_files(self):
        for name in ("workflow.json", ".workflow.json.token.stage", ".workflow.json.token.backup"):
            with self.subTest(name=name):
                job = self.create()
                artifact = job.job_dir / name
                if not artifact.exists():
                    artifact.write_bytes(b"internal")
                try:
                    with self.assertRaises(WorkflowError):
                        mark_ready(job, "inspect", [artifact])
                finally:
                    if artifact.name != "workflow.json":
                        artifact.unlink()

        job = self.create()
        artifact = job.job_dir / "unknown-artifact.bin"
        artifact.write_bytes(b"allowed")
        mark_ready(job, "inspect", [artifact])
        self.assertEqual(job.stages["inspect"]["artifacts"][0]["path"], "unknown-artifact.bin")

    def test_atomic_save_preserves_backup_when_rollback_cannot_restore(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        job.revision += 1
        real_exchange = state_module._atomic_exchange_rename
        exchange_count = 0

        def publish_then_interrupt_or_fail_rollback(source, destination):
            nonlocal exchange_count
            if destination == workflow and Path(source).name.endswith(".stage"):
                exchange_count += 1
                if exchange_count == 1:
                    real_exchange(source, destination)
                    raise KeyboardInterrupt()
                if exchange_count == 2:
                    raise OSError("rollback failed")
            return real_exchange(source, destination)

        with mock.patch.object(
            state_module, "_atomic_exchange_rename",
            side_effect=publish_then_interrupt_or_fail_rollback,
        ):
            try:
                save_job(job)
            except BaseException as error:
                raised = error
            else:
                self.fail("save_job must fail when rollback cannot restore")

        backups = list(job.job_dir.glob(".workflow.*.backup"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(hashlib.sha256(backups[0].read_bytes()).hexdigest(),
                         hashlib.sha256(previous).hexdigest())
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])
        self.assertIsInstance(raised, WorkflowError)
        self.assertIsNone(raised.__cause__)
        self.assertIn("manual recovery", str(raised))
        self.assertIn(backups[0].name, str(raised))
        self.assertNotIn(str(self.root), str(raised))
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

    def test_artifacts_reject_all_internal_transaction_name_patterns(self):
        for name in (
            ".workflow.generated.stage",
            ".workflow.generated.backup",
            ".workflow.generated.marker",
            ".workflow.generated.recovery",
            ".workflow.generated.quarantine",
            ".workflow.00000000000000000000000000000000.stage."
            "0000000000000000000000000000000000000000000000000000000000000000.1.retained",
        ):
            with self.subTest(name=name):
                job = self.create()
                artifact = job.job_dir / name
                artifact.write_bytes(b"internal")
                try:
                    with self.assertRaises(WorkflowError):
                        mark_ready(job, "inspect", [artifact])
                finally:
                    artifact.unlink()

        job = self.create()
        artifact = job.job_dir / "normal.workflow.notes.json"
        artifact.write_bytes(b"ordinary")
        mark_ready(job, "inspect", [artifact])
        self.assertEqual(job.stages["inspect"]["artifacts"][0]["path"], artifact.name)

    def test_initial_save_preserves_bound_recovery_when_target_quarantine_fails(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        workflow.unlink()
        job.revision += 1
        real_noreplace = state_module._atomic_noreplace_rename

        def publish_then_interrupt(source, destination):
            if destination == workflow and Path(source).name.endswith(".stage"):
                real_noreplace(source, destination)
                raise KeyboardInterrupt()
            return real_noreplace(source, destination)

        def fail_target_quarantine(source, destination):
            if source == workflow:
                raise OSError("rollback move failed")
            return publish_then_interrupt(source, destination)

        with mock.patch.object(
            state_module, "_atomic_noreplace_rename", side_effect=fail_target_quarantine,
        ):
            try:
                save_job(job)
            except BaseException as error:
                raised = error
            else:
                self.fail("save_job must fail when first-write rollback cannot unlink target")

        markers = list(job.job_dir.glob(".workflow.*.recovery"))
        self.assertEqual(len(markers), 1)
        marker = json.loads(markers[0].read_text(encoding="utf-8"))
        self.assertEqual(set(marker), {"version", "target", "sha256", "bytes"})
        self.assertEqual(marker["version"], 1)
        self.assertEqual(marker["target"], "workflow.json")
        self.assertEqual(marker["sha256"], hashlib.sha256(workflow.read_bytes()).hexdigest())
        self.assertEqual(marker["bytes"], workflow.stat().st_size)
        self.assertIsInstance(raised, WorkflowError)
        self.assertIsNone(raised.__cause__)
        self.assertIn("manual recovery", str(raised))
        self.assertIn(markers[0].name, str(raised))
        self.assertNotIn(str(self.root), str(raised))
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)
        with self.assertRaises(WorkflowError):
            save_job(job)
        with self.assertRaises(WorkflowError):
            require_runnable(job, "inspect")

    def test_initial_save_cleans_recovery_if_unlink_completed_before_error(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        workflow.unlink()
        job.revision += 1
        real_noreplace = state_module._atomic_noreplace_rename

        def publish_then_interrupt(source, destination):
            if destination == workflow and Path(source).name.endswith(".stage"):
                real_noreplace(source, destination)
                raise KeyboardInterrupt()
            if source == workflow:
                real_noreplace(source, destination)
                raise OSError("unlink completed then failed")
            return real_noreplace(source, destination)

        with mock.patch.object(
            state_module, "_atomic_noreplace_rename", side_effect=publish_then_interrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                save_job(job)

        self.assertFalse(workflow.exists())
        self.assertEqual(list(job.job_dir.glob(".workflow.*.recovery")), [])
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def test_atomic_save_preserves_backup_when_publish_and_rollback_fsync_fail(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        job.revision += 1
        real_fsync = os.fsync
        directory_calls = 0

        def fail_both_directory_fsyncs(descriptor):
            nonlocal directory_calls
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                directory_calls += 1
                if directory_calls in (1, 2):
                    raise OSError("directory fsync failed")
            return real_fsync(descriptor)

        with mock.patch.object(state_module.os, "fsync", side_effect=fail_both_directory_fsyncs):
            with self.assertRaises(WorkflowError) as raised:
                save_job(job)

        backups = list(job.job_dir.glob(".workflow.*.backup"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)
        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])
        self.assertIn(backups[0].name, str(raised.exception))
        self.assertNotIn(str(self.root), str(raised.exception))
        for action in (lambda: load_job(job.job_dir), lambda: save_job(job),
                       lambda: require_runnable(job, "inspect")):
            with self.assertRaises(WorkflowError):
                action()

    def test_initial_save_preserves_marker_when_publish_and_rollback_fsync_fail(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        workflow.unlink()
        job.revision += 1
        real_fsync = os.fsync
        directory_calls = 0

        def fail_publish_and_rollback_directory_fsyncs(descriptor):
            nonlocal directory_calls
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                directory_calls += 1
                if directory_calls in (2, 3):
                    raise OSError("directory fsync failed")
            return real_fsync(descriptor)

        with mock.patch.object(
            state_module.os, "fsync", side_effect=fail_publish_and_rollback_directory_fsyncs
        ):
            with self.assertRaises(WorkflowError) as raised:
                save_job(job)

        markers = list(job.job_dir.glob(".workflow.*.recovery"))
        self.assertEqual(len(markers), 1)
        self.assertFalse(workflow.exists())
        self.assertIn(markers[0].name, str(raised.exception))
        self.assertNotIn(str(self.root), str(raised.exception))
        for action in (lambda: load_job(job.job_dir), lambda: save_job(job),
                       lambda: require_runnable(job, "inspect")):
            with self.assertRaises(WorkflowError):
                action()

    def test_create_job_returns_existing_progress_without_reset(self):
        job = self.create()
        artifact = self.artifact(job)
        mark_ready(job, "inspect", [artifact])
        approve(job, "inspect")
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()

        existing = create_job(self.root, self.video, self.script, profile="legacy-v1")

        self.assertEqual(existing.revision, job.revision)
        self.assertEqual(existing.stages, job.stages)
        self.assertEqual(existing.stages["inspect"]["status"], "approved")
        self.assertEqual(workflow.read_bytes(), previous)

    def test_create_job_rejects_existing_corruption_and_input_path_conflict(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        alternate_video = self.root / "alternate.mp4"
        alternate_script = self.root / "alternate.txt"
        alternate_video.write_bytes(self.video.read_bytes())
        alternate_script.write_bytes(self.script.read_bytes())

        with self.assertRaises(WorkflowError):
            create_job(self.root, alternate_video, alternate_script, profile="legacy-v1")
        self.assertEqual(workflow.read_bytes(), previous)

        workflow.write_bytes(b"not JSON")
        with self.assertRaises(WorkflowError):
            create_job(self.root, self.video, self.script, profile="legacy-v1")

        pending = job.job_dir / ".workflow.pending.backup"
        workflow.write_bytes(previous)
        pending.write_bytes(previous)
        try:
            with self.assertRaises(WorkflowError):
                create_job(self.root, self.video, self.script, profile="legacy-v1")
        finally:
            pending.unlink()

    def test_hardlinked_inputs_artifacts_and_workflow_are_rejected(self):
        input_alias = self.root / "input-alias.mp4"
        os.link(self.video, input_alias)
        try:
            with self.assertRaises(WorkflowError):
                self.create()
        finally:
            input_alias.unlink()

        job = self.create()
        artifact = self.artifact(job)
        artifact_alias = self.root / "artifact-alias.bin"
        os.link(artifact, artifact_alias)
        try:
            with self.assertRaises(WorkflowError):
                mark_ready(job, "inspect", [artifact])
        finally:
            artifact_alias.unlink()

        workflow_alias = self.root / "workflow-alias.json"
        os.link(job.job_dir / "workflow.json", workflow_alias)
        try:
            with self.assertRaises(WorkflowError):
                load_job(job.job_dir)
        finally:
            workflow_alias.unlink()

    def test_publish_rolls_back_when_workflow_is_hardlinked_during_publish(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        alias = self.root / "published-workflow-alias.json"
        real_exchange = state_module._atomic_exchange_rename
        linked = False

        def exchange_then_link_published_workflow(source, destination):
            nonlocal linked
            result = real_exchange(source, destination)
            if (destination == workflow and Path(source).name.endswith(".stage")
                    and not linked):
                linked = True
                os.link(workflow, alias)
            return result

        with mock.patch.object(
            state_module, "_atomic_exchange_rename", side_effect=exchange_then_link_published_workflow
        ):
            with self.assertRaises(WorkflowError):
                block(job, "inspect", "unavailable", 1)

        self.assertTrue(linked)
        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(job.stages["inspect"]["status"], "pending")
        alias.unlink()

    def test_failed_state_mutations_restore_memory_and_disk(self):
        for operation in ("ready", "revise", "block"):
            for failure_type in (OSError, KeyboardInterrupt):
                with self.subTest(operation=operation, failure=failure_type.__name__):
                    job = self.create()
                    workflow = job.job_dir / "workflow.json"
                    previous_workflow = workflow.read_bytes()
                    previous_stages = copy.deepcopy(job.stages)
                    previous_revision = job.revision
                    artifact = self.artifact(job)

                    with mock.patch.object(
                        state_module, "_atomic_exchange_rename", side_effect=failure_type(),
                    ):
                        with self.assertRaises(failure_type):
                            if operation == "ready":
                                mark_ready(job, "inspect", [artifact])
                            elif operation == "revise":
                                revise(job, "inspect", "retry")
                            else:
                                block(job, "inspect", "unavailable", 1)

                    self.assertEqual(workflow.read_bytes(), previous_workflow)
                    self.assertEqual(job.stages, previous_stages)
                    self.assertEqual(job.revision, previous_revision)
                    with self.assertRaises(WorkflowError):
                        approve(job, "inspect")

    def test_publish_stage_rejects_mutation_replacement_and_replace_window_swap(self):
        for kind in ("mutate", "replace", "swap_after_replace"):
            with self.subTest(kind=kind):
                self.video.write_bytes(f"publish-{kind}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                job.revision += 1
                real_replace = os.replace
                real_exchange = state_module._atomic_exchange_rename

                def exchange_with_stage_attack(source, destination):
                    source_path = Path(source)
                    if destination == workflow and source_path.name.endswith(".stage"):
                        if kind == "mutate":
                            source_path.write_bytes(previous)
                        elif kind == "replace":
                            attacker = source_path.with_name("attacker-stage.json")
                            attacker.write_bytes(previous)
                            real_replace(attacker, source_path)
                        result = real_exchange(source, destination)
                        if kind == "swap_after_replace":
                            attacker = source_path.with_name("attacker-target.json")
                            attacker.write_bytes(previous)
                            real_replace(attacker, destination)
                        return result
                    return real_exchange(source, destination)

                with mock.patch.object(
                    state_module, "_atomic_exchange_rename", side_effect=exchange_with_stage_attack
                ):
                    with self.assertRaises(WorkflowError):
                        save_job(job)

                self.assertEqual(workflow.read_bytes(), previous)

    def test_rollback_stage_rejects_mutation_replacement_and_replace_window_swap(self):
        for kind in ("mutate", "replace", "swap_after_replace"):
            with self.subTest(kind=kind):
                self.video.write_bytes(f"rollback-{kind}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                job.revision += 1
                real_replace = os.replace
                real_exchange = state_module._atomic_exchange_rename

                exchange_count = 0

                def exchange_with_rollback_attack(source, destination):
                    nonlocal exchange_count
                    source_path = Path(source)
                    if destination == workflow and Path(source).name.endswith(".stage"):
                        exchange_count += 1
                        if exchange_count == 1:
                            real_exchange(source, destination)
                            raise KeyboardInterrupt()
                        if kind == "mutate":
                            source_path.write_bytes(b"tampered rollback")
                        elif kind == "replace":
                            attacker = source_path.with_name("attacker-rollback.json")
                            attacker.write_bytes(b"tampered rollback")
                            real_replace(attacker, source_path)
                        result = real_exchange(source, destination)
                        if kind == "swap_after_replace":
                            attacker = source_path.with_name("attacker-rollback-target.json")
                            attacker.write_bytes(b"tampered rollback")
                            real_replace(attacker, destination)
                        return result
                    return real_exchange(source, destination)

                with mock.patch.object(
                    state_module, "_atomic_exchange_rename",
                    side_effect=exchange_with_rollback_attack,
                ):
                    try:
                        save_job(job)
                    except BaseException as error:
                        raised = error
                    else:
                        self.fail("tampered rollback stage must not be accepted")

                backups = list(job.job_dir.glob(".workflow.*.backup"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), previous)
                self.assertIsInstance(raised, WorkflowError)
                self.assertIn(backups[0].name, str(raised))
                self.assertNotEqual(workflow.read_bytes(), previous)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_stage_cleanup_failures_close_descriptors_and_preserve_old_state(self):
        for removed, failure_type in ((False, OSError), (False, KeyboardInterrupt),
                                      (True, OSError), (True, KeyboardInterrupt)):
            with self.subTest(removed=removed, failure=failure_type.__name__):
                self.video.write_bytes(f"stage-cleanup-{removed}-{failure_type.__name__}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                real_unlink = Path.unlink
                before_descriptors = len(os.listdir("/dev/fd"))

                def fail_stage_cleanup(path, *args, **kwargs):
                    if path.name.endswith(".stage"):
                        if removed:
                            real_unlink(path, *args, **kwargs)
                        raise failure_type("cleanup failed") if failure_type is OSError else failure_type()
                    return real_unlink(path, *args, **kwargs)

                with mock.patch.object(
                    state_module, "_atomic_exchange_rename", side_effect=OSError("publish failed"),
                ), \
                        mock.patch.object(state_module.Path, "unlink", new=fail_stage_cleanup):
                    try:
                        block(job, "inspect", "unavailable", 1)
                    except BaseException:
                        pass
                    else:
                        self.fail("failed publish cleanup must not report success")

                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                self.assertEqual(workflow.read_bytes(), previous)
                self.assertEqual(job.stages["inspect"]["status"], "pending")
                self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])
                retained = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".retained")
                ]
                self.assertEqual(len(retained), 3)
                self.assertTrue(all(state_module._is_valid_retained_entry(path) for path in retained))
                self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "pending")

    def test_backup_cleanup_pre_and_post_failures_keep_memory_and_disk_consistent(self):
        for removed, failure_type in ((False, OSError), (False, KeyboardInterrupt),
                                      (True, OSError), (True, KeyboardInterrupt)):
            with self.subTest(removed=removed, failure=failure_type.__name__):
                self.video.write_bytes(f"backup-cleanup-{removed}-{failure_type.__name__}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                real_unlink = Path.unlink
                before_descriptors = len(os.listdir("/dev/fd"))

                def fail_backup_cleanup(path, *args, **kwargs):
                    if path.name.endswith(".backup"):
                        if removed:
                            real_unlink(path, *args, **kwargs)
                        raise failure_type("cleanup failed") if failure_type is OSError else failure_type()
                    return real_unlink(path, *args, **kwargs)

                with mock.patch.object(state_module.Path, "unlink", new=fail_backup_cleanup):
                    try:
                        block(job, "inspect", "unavailable", 1)
                    except BaseException as error:
                        raised = error
                    else:
                        raised = None

                self.assertIsNone(raised)
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                self.assertEqual(job.stages["inspect"]["status"], "blocked")
                self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "blocked")
                self.assertEqual(list(job.job_dir.glob(".workflow.*.backup")), [])
                retained = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".retained") and ".backup." in path.name
                ]
                self.assertEqual(len(retained), 1)
                self.assertTrue(state_module._is_valid_retained_entry(retained[0]))

    def test_backup_cleanup_directory_fsync_failure_keeps_committed_memory_and_disk(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        real_unlink = Path.unlink
        real_fsync = os.fsync
        directory_calls = 0
        before_descriptors = len(os.listdir("/dev/fd"))

        def unlink_then_interrupt(path, *args, **kwargs):
            if path.name.endswith(".backup"):
                real_unlink(path, *args, **kwargs)
                raise KeyboardInterrupt()
            return real_unlink(path, *args, **kwargs)

        def fail_backup_cleanup_directory_fsync(descriptor):
            nonlocal directory_calls
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                directory_calls += 1
                if directory_calls == 3:
                    raise OSError("backup cleanup fsync failed")
            return real_fsync(descriptor)

        with mock.patch.object(state_module.Path, "unlink", new=unlink_then_interrupt), \
                mock.patch.object(state_module.os, "fsync", side_effect=fail_backup_cleanup_directory_fsync):
            try:
                block(job, "inspect", "unavailable", 1)
            except BaseException as error:
                raised = error
            else:
                raised = None

        self.assertIsInstance(raised, WorkflowError)
        self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
        self.assertEqual(job.stages["inspect"]["status"], "blocked")
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "blocked")
        self.assertEqual(list(job.job_dir.glob(".workflow.*.backup")), [])
        self.assertTrue(workflow.exists())

    def test_backup_cleanup_does_not_delete_an_unknown_replacement(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        real_replace = os.replace
        real_exchange = state_module._atomic_exchange_rename
        replaced_backup = None

        def exchange_then_replace_backup(source, destination):
            nonlocal replaced_backup
            result = real_exchange(source, destination)
            if destination == workflow and Path(source).name.endswith(".stage"):
                backup, = job.job_dir.glob(".workflow.*.backup")
                attacker = job.job_dir / "unknown-external.bin"
                attacker.write_bytes(b"do not delete")
                real_replace(attacker, backup)
                replaced_backup = backup
            return result

        with mock.patch.object(
            state_module, "_atomic_exchange_rename", side_effect=exchange_then_replace_backup
        ):
            with self.assertRaises(WorkflowError):
                block(job, "inspect", "unavailable", 1)

        self.assertIsNotNone(replaced_backup)
        quarantines = [
            path for path in job.job_dir.iterdir()
            if path.name.endswith(".quarantine")
        ]
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(quarantines[0].read_bytes(), b"do not delete")
        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(job.stages["inspect"]["status"], "pending")
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

    def test_backup_cleanup_rejects_dangling_symlink_replacement(self):
        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                self.video.write_bytes(f"backup-link-{failure_type.__name__}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                real_unlink = Path.unlink
                real_atomic = state_module._atomic_noreplace_rename
                before_descriptors = len(os.listdir("/dev/fd"))

                def replace_backup_with_link(source, destination):
                    source_path = Path(source)
                    destination_path = Path(destination)
                    if (source_path.name.endswith(".backup")
                            and destination_path.name.endswith(".quarantine")):
                        real_unlink(source_path)
                        source_path.symlink_to("missing-backup")
                    return real_atomic(source, destination)

                with mock.patch.object(
                    state_module, "_atomic_noreplace_rename", side_effect=replace_backup_with_link,
                ):
                    with self.assertRaises(WorkflowError):
                        block(job, "inspect", "unavailable", 1)

                quarantine, = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".quarantine")
                ]
                self.assertTrue(os.path.lexists(quarantine))
                self.assertTrue(quarantine.is_symlink())
                self.assertEqual(workflow.read_bytes(), previous)
                self.assertEqual(job.stages["inspect"]["status"], "pending")
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_initial_recovery_cleanup_rejects_dangling_symlink_replacement(self):
        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                self.video.write_bytes(f"recovery-link-{failure_type.__name__}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                workflow.unlink()
                real_unlink = Path.unlink
                real_atomic = state_module._atomic_noreplace_rename
                before_descriptors = len(os.listdir("/dev/fd"))

                def replace_marker_with_link(source, destination):
                    source_path = Path(source)
                    destination_path = Path(destination)
                    if (source_path.name.endswith(".recovery")
                            and destination_path.name.endswith(".quarantine")):
                        real_unlink(source_path)
                        source_path.symlink_to("missing-recovery")
                    return real_atomic(source, destination)

                with mock.patch.object(
                    state_module, "_atomic_noreplace_rename", side_effect=replace_marker_with_link,
                ):
                    with self.assertRaises(WorkflowError):
                        block(job, "inspect", "unavailable", 1)

                quarantine, = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".quarantine")
                ]
                self.assertTrue(os.path.lexists(quarantine))
                self.assertTrue(quarantine.is_symlink())
                self.assertFalse(workflow.exists())
                self.assertEqual(job.stages["inspect"]["status"], "pending")
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_transaction_write_failure_preserves_unknown_replacement(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        real_replace = os.replace
        real_write = os.write
        before_descriptors = len(os.listdir("/dev/fd"))

        def replace_stage_then_fail_write(descriptor, data):
            stages = list(job.job_dir.glob(".workflow.*.stage"))
            if not stages:
                return real_write(descriptor, data)
            stage, = stages
            attacker = job.job_dir / "unknown-write-replacement.bin"
            attacker.write_bytes(b"do not delete")
            real_replace(attacker, stage)
            raise OSError("write failed")

        with mock.patch.object(state_module.os, "write", side_effect=replace_stage_then_fail_write):
            with self.assertRaises(OSError):
                save_job(job)

        stage, = job.job_dir.glob(".workflow.*.stage")
        self.assertEqual(stage.read_bytes(), b"do not delete")
        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
        with self.assertRaises(WorkflowError):
            load_job(job.job_dir)

    def test_original_transaction_descriptor_close_failure_leaves_no_orphan(self):
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        previous = workflow.read_bytes()
        real_mkstemp = tempfile.mkstemp
        real_close = os.close
        created_descriptor = None
        close_fired = False
        before_descriptors = len(os.listdir("/dev/fd"))

        def record_mkstemp(*args, **kwargs):
            nonlocal created_descriptor
            created_descriptor, name = real_mkstemp(*args, **kwargs)
            return created_descriptor, name

        def close_then_interrupt(descriptor):
            nonlocal close_fired
            if descriptor == created_descriptor and not close_fired:
                close_fired = True
                real_close(descriptor)
                raise KeyboardInterrupt()
            return real_close(descriptor)

        with mock.patch.object(state_module.tempfile, "mkstemp", side_effect=record_mkstemp), \
                mock.patch.object(state_module.os, "close", side_effect=close_then_interrupt):
            try:
                block(job, "inspect", "unavailable", 1)
            except BaseException:
                pass
            else:
                self.fail("transaction descriptor close interruption must not report success")

        self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
        self.assertEqual(workflow.read_bytes(), previous)
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "pending")

    def test_pinned_transaction_descriptor_close_failures_keep_committed_state(self):
        for removed, failure_type in ((False, OSError), (False, KeyboardInterrupt),
                                      (True, OSError), (True, KeyboardInterrupt)):
            with self.subTest(removed=removed, failure=failure_type.__name__):
                self.video.write_bytes(f"pinned-close-{removed}-{failure_type.__name__}".encode())
                job = self.create()
                real_open = os.open
                real_close = os.close
                pinned_descriptor = None
                close_fired = False
                stage_opens = 0
                before_descriptors = len(os.listdir("/dev/fd"))

                def record_stage_open(path, flags, *args, **kwargs):
                    nonlocal pinned_descriptor, stage_opens
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path).name.endswith(".stage"):
                        stage_opens += 1
                        if stage_opens == 2:
                            pinned_descriptor = descriptor
                    return descriptor

                def fail_pinned_close(descriptor):
                    nonlocal close_fired
                    if descriptor == pinned_descriptor and not close_fired:
                        close_fired = True
                        if removed:
                            real_close(descriptor)
                        raise failure_type("close failed") if failure_type is OSError else failure_type()
                    return real_close(descriptor)

                with mock.patch.object(state_module.os, "open", side_effect=record_stage_open), \
                        mock.patch.object(state_module.os, "close", side_effect=fail_pinned_close):
                    try:
                        block(job, "inspect", "unavailable", 1)
                    except BaseException as error:
                        raised = error
                    else:
                        raised = None

                self.assertIsInstance(raised, WorkflowError)
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                self.assertEqual(job.stages["inspect"]["status"], "blocked")
                self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "blocked")
                self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def _assert_cleanup_quarantine_attack_is_closed(self, kind):
        for replacement in ("file", "symlink"):
            with self.subTest(kind=kind, replacement=replacement):
                self.video.write_bytes(f"quarantine-{kind}-{replacement}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                previous = workflow.read_bytes()
                if kind == "recovery":
                    workflow.unlink()
                real_replace = os.replace
                real_atomic = state_module._atomic_noreplace_rename
                real_exchange = state_module._atomic_exchange_rename
                real_unlink = Path.unlink
                planted = False
                before_descriptors = len(os.listdir("/dev/fd"))

                def replace_with_unknown(path):
                    nonlocal planted
                    if planted:
                        return
                    planted = True
                    if replacement == "file":
                        attacker = job.job_dir / f"unknown-{kind}.bin"
                        attacker.write_bytes(b"do not delete")
                        real_replace(attacker, path)
                    else:
                        real_unlink(path)
                        path.symlink_to(f"missing-{kind}")

                def swap_at_old_unlink(path, *args, **kwargs):
                    if path.name.endswith(f".{kind}"):
                        replace_with_unknown(path)
                    return real_unlink(path, *args, **kwargs)

                def swap_before_quarantine(source, destination):
                    source_path = Path(source)
                    destination_path = Path(destination)
                    if (source_path.name.endswith(f".{kind}")
                            and destination_path.name.endswith(".quarantine")):
                        replace_with_unknown(source_path)
                    return real_atomic(source, destination)

                def fail_stage_publish(source, destination):
                    if (Path(source).name.endswith(".stage")
                            and Path(destination) == workflow):
                        raise OSError("publish failed")
                    return real_exchange(source, destination)

                patches = [
                    mock.patch.object(state_module.Path, "unlink", new=swap_at_old_unlink),
                    mock.patch.object(
                        state_module, "_atomic_noreplace_rename", side_effect=swap_before_quarantine,
                    ),
                ]
                if kind == "stage":
                    patches.append(mock.patch.object(
                        state_module, "_atomic_exchange_rename", side_effect=fail_stage_publish,
                    ))
                with patches[0], patches[1]:
                    if len(patches) == 3:
                        with patches[2]:
                            with self.assertRaises(BaseException):
                                block(job, "inspect", "unavailable", 1)
                    else:
                        with self.assertRaises(WorkflowError):
                            block(job, "inspect", "unavailable", 1)

                quarantines = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".quarantine")
                ]
                self.assertEqual(len(quarantines), 1)
                quarantine = quarantines[0]
                if replacement == "file":
                    self.assertEqual(quarantine.read_bytes(), b"do not delete")
                else:
                    self.assertTrue(os.path.lexists(quarantine))
                    self.assertTrue(quarantine.is_symlink())
                if kind == "recovery":
                    self.assertFalse(os.path.lexists(workflow))
                else:
                    self.assertEqual(workflow.read_bytes(), previous)
                self.assertEqual(job.stages["inspect"]["status"], "pending")
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_stage_cleanup_quarantines_last_moment_unknown_replacement(self):
        self._assert_cleanup_quarantine_attack_is_closed("stage")

    def test_backup_cleanup_quarantines_last_moment_unknown_replacement(self):
        self._assert_cleanup_quarantine_attack_is_closed("backup")

    def test_recovery_cleanup_quarantines_last_moment_unknown_replacement(self):
        self._assert_cleanup_quarantine_attack_is_closed("recovery")

    def test_valid_retained_cleanup_entries_do_not_block_recovery_or_loading(self):
        job = self.create()

        retained = [
            path for path in job.job_dir.iterdir()
            if path.name.endswith(".retained")
        ]
        self.assertEqual(len(retained), 1)
        self.assertTrue(all(state_module._is_valid_retained_entry(path) for path in retained))
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "pending")

        block(job, "inspect", "unavailable", 1)
        retained = [
            path for path in job.job_dir.iterdir()
            if path.name.endswith(".retained")
        ]
        self.assertEqual(len(retained), 3)
        self.assertTrue(all(state_module._is_valid_retained_entry(path) for path in retained))
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "blocked")

        workflow = job.job_dir / "workflow.json"
        with mock.patch.object(
            state_module, "_atomic_exchange_rename", side_effect=OSError("publish failed"),
        ):
            with self.assertRaises(OSError):
                revise(job, "inspect", "retry")

        retained = [
            path for path in job.job_dir.iterdir()
            if path.name.endswith(".retained")
        ]
        self.assertEqual(len(retained), 5)
        self.assertTrue(all(state_module._is_valid_retained_entry(path) for path in retained))
        self.assertEqual(load_job(job.job_dir).stages["inspect"]["status"], "blocked")
        self.assertTrue(workflow.is_file())

    def test_quarantine_move_never_overwrites_existing_destination(self):
        for replacement in ("file", "symlink"):
            for timing in ("before", "window"):
                with self.subTest(replacement=replacement, timing=timing):
                    job = self.create()
                    source = job.job_dir / f"owned-{replacement}-{timing}"
                    destination = job.job_dir / f"unknown-{replacement}-{timing}"
                    source.write_bytes(b"owned transaction")
                    if replacement == "file":
                        destination.write_bytes(b"do not delete")
                    else:
                        destination.symlink_to("missing-destination")
                    before_descriptors = len(os.listdir("/dev/fd"))
                    descriptor = os.open(str(source), os.O_RDONLY | os.O_NOFOLLOW)
                    opened = os.fstat(descriptor)
                    transaction = state_module._PinnedTransactionFile(
                        source, descriptor, opened.st_dev, opened.st_ino,
                        hashlib.sha256(b"owned transaction").hexdigest(),
                        len(b"owned transaction"),
                    )
                    real_exists = state_module._entry_exists

                    def hide_window_destination(path):
                        if timing == "window" and Path(path) == destination:
                            return False
                        return real_exists(path)

                    try:
                        with mock.patch.object(
                            state_module, "_entry_exists", side_effect=hide_window_destination,
                        ):
                            with self.assertRaises(WorkflowError):
                                state_module._rename_owned_entry(
                                    source, destination,
                                    lambda path: state_module._verify_transaction_file(
                                        transaction, path,
                                    ),
                                )
                    finally:
                        state_module._close_transaction_file(transaction)

                    self.assertEqual(source.read_bytes(), b"owned transaction")
                    if replacement == "file":
                        self.assertEqual(destination.read_bytes(), b"do not delete")
                    else:
                        self.assertTrue(os.path.lexists(destination))
                        self.assertTrue(destination.is_symlink())
                    self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)

    def test_first_write_rollback_quarantines_replaced_workflow_target(self):
        for replacement in ("file", "symlink"):
            with self.subTest(replacement=replacement):
                self.video.write_bytes(f"target-race-{replacement}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                workflow.unlink()
                real_replace = os.replace
                real_unlink = Path.unlink
                real_atomic = state_module._atomic_noreplace_rename
                planted = False
                before_descriptors = len(os.listdir("/dev/fd"))

                def replace_with_unknown(path):
                    nonlocal planted
                    if planted:
                        return
                    planted = True
                    if replacement == "file":
                        attacker = job.job_dir / "unknown-workflow.bin"
                        attacker.write_bytes(b"do not delete")
                        real_replace(attacker, path)
                    else:
                        real_unlink(path)
                        path.symlink_to("missing-workflow")

                def swap_before_atomic_move(source, destination):
                    if (Path(source).name.endswith(".stage")
                            and Path(destination) == workflow):
                        real_atomic(source, destination)
                        raise KeyboardInterrupt()
                    if Path(source) == workflow:
                        replace_with_unknown(Path(source))
                    return real_atomic(source, destination)

                with mock.patch.object(
                    state_module, "_atomic_noreplace_rename",
                    side_effect=swap_before_atomic_move,
                ):
                    with self.assertRaises(BaseException):
                        block(job, "inspect", "unavailable", 1)

                quarantines = [
                    path for path in job.job_dir.iterdir()
                    if path.name.endswith(".quarantine")
                ]
                self.assertEqual(len(quarantines), 1)
                quarantine = quarantines[0]
                if replacement == "file":
                    self.assertEqual(quarantine.read_bytes(), b"do not delete")
                else:
                    self.assertTrue(os.path.lexists(quarantine))
                    self.assertTrue(quarantine.is_symlink())
                self.assertFalse(os.path.lexists(workflow))
                self.assertEqual(job.stages["inspect"]["status"], "pending")
                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)

    def test_publication_preserves_target_changed_after_backup(self):
        for replacement in ("file", "symlink", "workflow"):
            with self.subTest(replacement=replacement):
                self.video.write_bytes(f"publish-cas-{replacement}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                before_stages = copy.deepcopy(job.stages)
                before_revision = job.revision
                real_replace = os.replace
                real_exchange = getattr(state_module, "_atomic_exchange_rename", None)
                attacker_bytes = b"external workflow"

                def replace_target_before_publish(source, destination, *args, **kwargs):
                    nonlocal attacker_bytes
                    if (Path(source).name.endswith(".stage")
                            and Path(destination) == workflow):
                        if replacement == "file":
                            attacker = job.job_dir / "external.bin"
                            attacker.write_bytes(attacker_bytes)
                            real_replace(attacker, destination)
                        elif replacement == "symlink":
                            destination.unlink()
                            destination.symlink_to("missing-workflow")
                        else:
                            payload = self.workflow_payload(job)
                            payload["revision"] = 77
                            attacker_bytes = (
                                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                                + "\n"
                            ).encode("utf-8")
                            destination.write_bytes(attacker_bytes)
                    return real_replace(source, destination, *args, **kwargs)

                def exchange_target_before_publish(source, destination):
                    if Path(destination) == workflow:
                        if replacement == "file":
                            attacker = job.job_dir / "external-exchange.bin"
                            attacker.write_bytes(attacker_bytes)
                            real_replace(attacker, destination)
                        elif replacement == "symlink":
                            destination.unlink()
                            destination.symlink_to("missing-workflow")
                        else:
                            destination.write_bytes(attacker_bytes)
                    if real_exchange is None:
                        raise AssertionError("exchange helper is unavailable")
                    return real_exchange(source, destination)

                with mock.patch.object(
                    state_module.os, "replace", side_effect=replace_target_before_publish,
                ), mock.patch.object(
                    state_module, "_atomic_exchange_rename",
                    side_effect=exchange_target_before_publish, create=True,
                ):
                    try:
                        block(job, "inspect", "publish conflict", 1)
                    except BaseException as error:
                        raised = error
                    else:
                        raised = None

                self.assertIsInstance(raised, WorkflowError)
                if replacement == "symlink":
                    self.assertTrue(os.path.lexists(workflow))
                    self.assertTrue(workflow.is_symlink())
                else:
                    self.assertEqual(workflow.read_bytes(), attacker_bytes)
                self.assertEqual(job.stages, before_stages)
                self.assertEqual(job.revision, before_revision)

    def test_stale_loaded_job_cannot_overwrite_first_transition(self):
        original = self.create()
        first = load_job(original.job_dir)
        second = load_job(original.job_dir)

        block(first, "inspect", "first result", 1)
        first_workflow = (first.job_dir / "workflow.json").read_bytes()

        with self.assertRaises(WorkflowError):
            block(second, "inspect", "stale result", 2)

        self.assertEqual((first.job_dir / "workflow.json").read_bytes(), first_workflow)
        self.assertEqual(load_job(first.job_dir).stages["inspect"]["reason"], "first result")
        self.assertEqual(second.stages["inspect"]["status"], "pending")
        self.assertEqual(second.revision, 0)

    def test_transaction_pin_failures_close_unowned_descriptor(self):
        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(kind="fstat", failure=failure_type.__name__):
                self.video.write_bytes(f"pin-fstat-{failure_type.__name__}".encode())
                job = self.create()
                workflow = job.job_dir / "workflow.json"
                before_workflow = workflow.read_bytes()
                before_descriptors = len(os.listdir("/dev/fd"))
                real_open = os.open
                real_fstat = os.fstat
                pinned_descriptor = None
                fstat_fired = False
                stage_opens = 0

                def record_pinned_open(path, flags, *args, **kwargs):
                    nonlocal pinned_descriptor, stage_opens
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path).name.endswith(".stage"):
                        stage_opens += 1
                        if stage_opens == 2:
                            pinned_descriptor = descriptor
                    return descriptor

                def fail_pinned_fstat(descriptor):
                    nonlocal fstat_fired
                    if descriptor == pinned_descriptor and not fstat_fired:
                        fstat_fired = True
                        raise failure_type("pinned fstat failed")
                    return real_fstat(descriptor)

                with mock.patch.object(state_module.os, "open", side_effect=record_pinned_open), \
                        mock.patch.object(state_module.os, "fstat", side_effect=fail_pinned_fstat):
                    with self.assertRaises(failure_type):
                        state_module._write_transaction_file(job.job_dir, ".stage", b"pin failure")

                self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
                self.assertEqual(workflow.read_bytes(), before_workflow)
                self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

        self.video.write_bytes(b"pin-constructor")
        job = self.create()
        workflow = job.job_dir / "workflow.json"
        before_workflow = workflow.read_bytes()
        before_descriptors = len(os.listdir("/dev/fd"))
        real_open = os.open
        real_constructor = state_module._PinnedTransactionFile
        pinned_descriptor = None
        stage_opens = 0

        def record_constructor_open(path, flags, *args, **kwargs):
            nonlocal pinned_descriptor, stage_opens
            descriptor = real_open(path, flags, *args, **kwargs)
            if Path(path).name.endswith(".stage"):
                stage_opens += 1
                if stage_opens == 2:
                    pinned_descriptor = descriptor
            return descriptor

        def fail_pinned_constructor(*args):
            if args[1] == pinned_descriptor:
                raise OSError("pinned construction failed")
            return real_constructor(*args)

        with mock.patch.object(state_module.os, "open", side_effect=record_constructor_open), \
                mock.patch.object(
                    state_module, "_PinnedTransactionFile", side_effect=fail_pinned_constructor,
                ):
            with self.assertRaises(OSError):
                state_module._write_transaction_file(job.job_dir, ".stage", b"constructor failure")

        self.assertEqual(len(os.listdir("/dev/fd")), before_descriptors)
        self.assertEqual(workflow.read_bytes(), before_workflow)
        self.assertEqual(list(job.job_dir.glob(".workflow.*.stage")), [])

    def test_rollback_preserves_target_replaced_after_publish(self):
        for replacement in ("file", "symlink", "same_revision", "new_revision"):
            with self.subTest(replacement=replacement):
                self.video.write_bytes(f"post-publish-{replacement}".encode())
                job = self.create()
                artifact = self.artifact(job, content=b"bound artifact")
                mark_ready(job, "inspect", [artifact])
                workflow = job.job_dir / "workflow.json"
                ready_stages = copy.deepcopy(job.stages)
                ready_revision = job.revision
                real_publish = state_module._publish_transaction
                real_replace = os.replace
                attacker_bytes = b"attacker workflow"

                def publish_then_replace_target(transaction, target, **kwargs):
                    nonlocal attacker_bytes
                    real_publish(transaction, target, **kwargs)
                    if replacement == "file":
                        attacker = job.job_dir / "post-publish-unknown.bin"
                        attacker.write_bytes(attacker_bytes)
                        real_replace(attacker, target)
                    elif replacement == "symlink":
                        target.unlink()
                        target.symlink_to("missing-workflow")
                    else:
                        payload = self.workflow_payload(job)
                        if replacement == "same_revision":
                            payload["stages"]["inspect"]["ai_attempts"] = 7
                        else:
                            payload["revision"] += 7
                        attacker_bytes = (
                            json.dumps(
                                payload, ensure_ascii=False, indent=2, sort_keys=True,
                                allow_nan=False,
                            )
                            + "\n"
                        ).encode("utf-8")
                        target.write_bytes(attacker_bytes)
                    artifact.write_bytes(b"artifact changed after publish")

                with mock.patch.object(
                    state_module, "_publish_transaction",
                    side_effect=publish_then_replace_target,
                ):
                    with self.assertRaises(WorkflowError):
                        approve(job, "inspect")

                if replacement == "symlink":
                    self.assertTrue(os.path.lexists(workflow))
                    self.assertTrue(workflow.is_symlink())
                else:
                    self.assertEqual(workflow.read_bytes(), attacker_bytes)
                self.assertEqual(job.stages, ready_stages)
                self.assertEqual(job.revision, ready_revision)
                self.assertEqual(
                    len(list(job.job_dir.glob(".workflow.*.backup"))), 1,
                )
                with self.assertRaises(WorkflowError):
                    load_job(job.job_dir)


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.txt"
        self.video.write_bytes(b"video-source")
        self.script.write_text("test script", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_cli_module_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec("edit.hd.tools.cli"))

    def run_cli(self, *argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = importlib.import_module("edit.hd.tools.cli").main(list(argv))
            except SystemExit as exc:
                code = int(exc.code)
        return code, stdout.getvalue(), stderr.getvalue()

    def init(self):
        code, stdout, stderr = self.run_cli(
            "init", "--root", str(self.root), "--video", str(self.video),
            "--script", str(self.script),
        )
        self.assertEqual(code, 0, stderr)
        return json.loads(stdout)

    def test_init_returns_safe_single_line_summary_and_rejects_bad_inputs(self):
        summary = self.init()

        self.assertEqual(set(summary), {"job_id", "job", "status"})
        self.assertEqual(summary["job_id"], summary["job"].rsplit("/", 1)[-1])
        self.assertEqual(summary["status"], "created")
        self.assertNotIn(str(self.root), json.dumps(summary))

        missing = self.root / "missing.mp4"
        dangerous = self.root / ".." / "outside.mp4"
        for video in (missing, dangerous):
            with self.subTest(video=str(video)):
                code, stdout, stderr = self.run_cli(
                    "init", "--root", str(self.root), "--video", str(video),
                    "--script", str(self.script),
                )
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("错误: "))
                self.assertNotIn(str(video), stderr)

    def test_status_returns_only_safe_summary(self):
        created = self.init()
        job_dir = self.root / created["job"]

        code, stdout, stderr = self.run_cli("status", "--job", str(job_dir))

        self.assertEqual(code, 0, stderr)
        summary = json.loads(stdout)
        self.assertEqual(
            set(summary), {"version", "job_id", "revision", "current_stage", "stages"}
        )
        self.assertEqual(summary["current_stage"], "inspect")
        self.assertNotIn(str(self.root), stdout)
        self.assertNotIn(str(self.video), stdout)
        self.assertNotIn(str(self.script), stdout)

    def test_ready_and_approve_enforce_stage_rules(self):
        created = self.init()
        job_dir = self.root / created["job"]
        artifact = job_dir / "inspect" / "report.json"
        artifact.parent.mkdir()
        artifact.write_text("{}\n", encoding="utf-8")

        code, _, stderr = self.run_cli("approve", "--job", str(job_dir), "--stage", "inspect")
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("错误: "))

        code, _, stderr = self.run_cli(
            "ready", "--job", str(job_dir), "--stage", "inspect", "--artifact", str(artifact)
        )
        self.assertEqual(code, 0, stderr)
        code, stdout, stderr = self.run_cli(
            "approve", "--job", str(job_dir), "--stage", "inspect"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["stages"]["inspect"]["status"], "approved")

        code, _, stderr = self.run_cli("approve", "--job", str(job_dir))
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "错误: 无效的工作流请求\n")
        code, _, stderr = self.run_cli(
            "approve", "--job", str(job_dir), "--stage", "unknown"
        )
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("错误: "))

    def test_revise_and_block_validate_attempts_and_persist_state(self):
        created = self.init()
        job_dir = self.root / created["job"]

        code, _, stderr = self.run_cli(
            "revise", "--job", str(job_dir), "--stage", "inspect", "--reason", "tighten cuts"
        )
        self.assertEqual(code, 0, stderr)
        code, stdout, stderr = self.run_cli(
            "block", "--job", str(job_dir), "--stage", "inspect", "--reason", "AI unavailable",
            "--ai-attempts", "2",
        )
        self.assertEqual(code, 0, stderr)
        stage = json.loads(stdout)["stages"]["inspect"]
        self.assertEqual(stage["status"], "blocked")
        self.assertEqual(stage["ai_attempts"], 2)
        self.assertEqual(load_job(job_dir).stages["inspect"]["reason"], "AI unavailable")

        for attempts in ("true", "False", "-1", "not-a-number"):
            with self.subTest(attempts=attempts):
                code, _, _ = self.run_cli(
                    "block", "--job", str(job_dir), "--stage", "inspect", "--reason", "retry",
                    "--ai-attempts", attempts,
                )
                self.assertEqual(code, 2)

    def test_ready_binds_multiple_artifacts_and_rejects_unsafe_artifacts(self):
        created = self.init()
        job_dir = self.root / created["job"]
        first = job_dir / "inspect" / "first.bin"
        second = job_dir / "inspect" / "second.bin"
        first.parent.mkdir()
        first.write_bytes(b"one")
        second.write_bytes(b"two")

        code, stdout, stderr = self.run_cli(
            "ready", "--job", str(job_dir), "--stage", "inspect", "--artifact", str(first),
            "--artifact", str(second),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["stages"]["inspect"]["artifact_count"], 2)

        second_job = self.init()
        second_dir = self.root / second_job["job"]
        for artifact in (self.root / "missing.bin", self.root / "outside.bin"):
            if artifact.name == "outside.bin":
                artifact.write_bytes(b"outside")
            with self.subTest(artifact=artifact.name):
                code, _, stderr = self.run_cli(
                    "ready", "--job", str(second_dir), "--stage", "inspect", "--artifact", str(artifact)
                )
                self.assertEqual(code, 2)
                self.assertTrue(stderr.startswith("错误: "))

        link = second_dir / "artifact-link"
        link.symlink_to(first)
        code, _, stderr = self.run_cli(
            "ready", "--job", str(second_dir), "--stage", "inspect", "--artifact", str(link)
        )
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("错误: "))

        code, _, stderr = self.run_cli("ready", "--job", str(second_dir), "--stage", "inspect")
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "错误: 无效的工作流请求\n")

    def test_domain_errors_are_safe_and_main_returns_integer(self):
        secret_path = self.root / "secret_sk-should-not-appear.mp4"
        code, stdout, stderr = self.run_cli(
            "init", "--root", str(self.root), "--video", str(secret_path), "--script", str(self.script)
        )

        self.assertIsInstance(code, int)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertRegex(stderr, r"\A错误: .+\n\Z")
        self.assertNotIn(str(secret_path), stderr)
        self.assertNotIn(str(self.script), stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotRegex(stderr, r"sk-[A-Za-z0-9_-]+")

    def test_parser_errors_are_single_line_and_do_not_echo_arguments(self):
        secret = str(self.root / "secret_sk-parser-must-not-appear.mp4")
        for argv in (
            ("unknown-command", secret),
            ("status", "--job", secret, "--unknown-flag"),
            ("init", "--root", str(self.root), "--video", secret),
        ):
            with self.subTest(argv=argv):
                code, stdout, stderr = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "错误: 无效的工作流请求\n")
                self.assertNotIn(secret, stderr)
                self.assertNotIn(str(self.root), stderr)
                self.assertNotIn("usage:", stderr)

        code, stdout, stderr = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("usage:", stdout)
        self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()

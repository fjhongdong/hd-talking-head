"""Authoritative material-usage receipt contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from edit.hd.tools import material_usage, state


class MaterialUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"video")
        self.script.write_text("script", encoding="utf-8")
        self.job = state.create_job(
            self.root, self.video, self.script, profile="full-v2"
        )
        self.stage_dir = self.job.job_dir / "01-inspect"
        self.stage_dir.mkdir()
        self.artifact = self.stage_dir / "inspection.json"
        self.artifact.write_text('{"ok": true}\n', encoding="utf-8")

    def input_records(self) -> list[dict[str, object]]:
        return material_usage.current_stage_input_records(self.job, "inspect")

    def build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "producer": "edit.hd.tools.inspect_inputs",
            "producer_version": "test-v1",
            "stage_input_records": self.input_records(),
            "references": [],
            "artifact_paths": [self.artifact],
        }
        arguments.update(overrides)
        return material_usage.build_receipt(
            self.job, "inspect", **arguments  # type: ignore[arg-type]
        )

    def test_complete_empty_declaration_is_valid(self) -> None:
        receipt = self.build()

        checked = material_usage.validate_receipt(
            self.job,
            "inspect",
            receipt,
            published_artifacts=[self.artifact],
            expected_stage_revision=self.job.revision + 1,
        )

        self.assertTrue(checked["complete_reference_declaration"])
        self.assertEqual(checked["references"], [])
        self.assertEqual(checked["stage_revision"], self.job.revision + 1)

    def test_stage_inputs_are_authoritative_and_order_independent(self) -> None:
        records = self.input_records()
        receipt = self.build(stage_input_records=list(reversed(records)))
        expected = hashlib.sha256(
            json.dumps(
                sorted(records, key=lambda item: str(item["path"])),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(receipt["stage_input_sha256"], expected)
        with self.assertRaises(material_usage.MaterialUsageError):
            self.build(stage_input_records=records[:-1])

    def test_reference_requires_exact_identity_and_published_artifacts(self) -> None:
        index_dir = self.job.root / "00-user-provided"
        index_dir.mkdir()
        digest = hashlib.sha256(b"image").hexdigest()
        (index_dir / "material-index.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "assets": [],
                    "materials": [
                        {
                            "material_id": "material-0003",
                            "sha256": digest,
                            "status": "active",
                        }
                    ],
                    "changes": [],
                    "material_revision": 0,
                }
            ),
            encoding="utf-8",
        )
        reference = {
            "material_id": "material-0003",
            "material_sha256": digest,
            "consumer_kind": "input_inspection",
            "consumer_id": "primary-reference",
            "binding_path": "/inputs/reference/material_id",
            "artifact_paths": ["01-inspect/inspection.json"],
        }

        receipt = self.build(references=[reference])
        self.assertEqual(receipt["references"], [reference])

        for mutation in (
            lambda value: value.pop("binding_path"),
            lambda value: value.update(material_sha256="0" * 64),
            lambda value: value.update(artifact_paths=["../escape.png"]),
            lambda value: value.update(artifact_paths=["01-inspect/missing.png"]),
        ):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(reference)
                mutation(changed)
                with self.assertRaises(material_usage.MaterialUsageError):
                    self.build(references=[changed])

        with self.assertRaises(material_usage.MaterialUsageError):
            self.build(references=[reference, copy.deepcopy(reference)])

    def test_mismatched_job_stage_revision_producer_and_completeness_are_rejected(self) -> None:
        original = self.build()
        mutations = (
            ("job_id", "other-job"),
            ("stage_id", "cover"),
            ("stage_revision", 99),
            ("producer", "unknown.producer"),
            ("complete_reference_declaration", False),
            ("stage_input_sha256", "0" * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                with self.assertRaises(material_usage.MaterialUsageError):
                    material_usage.validate_receipt(
                        self.job,
                        "inspect",
                        changed,
                        published_artifacts=[self.artifact],
                        expected_stage_revision=self.job.revision + 1,
                    )

    def test_publish_binds_receipt_as_formal_artifact(self) -> None:
        receipt_path = material_usage.publish_and_mark_ready(
            self.job,
            "inspect",
            [self.artifact],
            producer="edit.hd.tools.inspect_inputs",
            producer_version="test-v1",
            stage_input_records=self.input_records(),
            references=[],
        )

        loaded = state.load_job(self.job.job_dir)
        paths = {item["path"] for item in loaded.stages["inspect"]["artifacts"]}
        self.assertEqual(receipt_path, self.stage_dir / "material-usage.json")
        self.assertIn("01-inspect/material-usage.json", paths)
        receipt = material_usage.load_current_receipt(loaded, "inspect")
        self.assertEqual(receipt["stage_revision"], 1)

    def test_staged_receipt_uses_final_paths_without_touching_target(self) -> None:
        staging = self.job.job_dir / ".01-inspect.stage-test"
        staging.mkdir()
        (staging / "report.json").write_text("{}\n", encoding="utf-8")
        target = self.job.job_dir / "01-inspect-next"

        receipt_path = material_usage.write_staged_receipt(
            self.job,
            "inspect",
            staging,
            target,
            ["report.json"],
            producer="edit.hd.tools.inspect_inputs",
            producer_version="test-v1",
            stage_input_records=self.input_records(),
            references=[],
        )

        self.assertEqual(receipt_path, staging / "material-usage.json")
        self.assertFalse(target.exists())
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        material_usage.validate_receipt(
            self.job,
            "inspect",
            payload,
            published_artifacts=[staging / "report.json"],
            published_path_overrides=["01-inspect-next/report.json"],
            expected_stage_revision=self.job.revision + 1,
        )

    def test_publish_failure_does_not_leave_a_receipt(self) -> None:
        receipt_path = self.stage_dir / "material-usage.json"
        with mock.patch.object(state, "mark_ready", side_effect=state.WorkflowError("boom")):
            with self.assertRaises(state.WorkflowError):
                material_usage.publish_and_mark_ready(
                    self.job,
                    "inspect",
                    [self.artifact],
                    producer="edit.hd.tools.inspect_inputs",
                    producer_version="test-v1",
                    stage_input_records=self.input_records(),
                    references=[],
                )
        self.assertFalse(receipt_path.exists())

    def test_failed_republication_restores_previous_receipt_bytes(self) -> None:
        receipt_path = self.stage_dir / "material-usage.json"
        receipt_path.write_bytes(b"previous receipt")
        with mock.patch.object(state, "mark_ready", side_effect=state.WorkflowError("boom")):
            with self.assertRaises(state.WorkflowError):
                material_usage.publish_and_mark_ready(
                    self.job,
                    "inspect",
                    [self.artifact],
                    producer="edit.hd.tools.inspect_inputs",
                    producer_version="test-v1",
                    stage_input_records=self.input_records(),
                    references=[],
                )
        self.assertEqual(receipt_path.read_bytes(), b"previous receipt")

    def test_committed_state_error_keeps_the_bound_receipt(self) -> None:
        real_mark_ready = state.mark_ready

        def commit_then_fail(*args: object, **kwargs: object) -> None:
            real_mark_ready(*args, **kwargs)  # type: ignore[arg-type]
            raise state.WorkflowError("cleanup failed after commit")

        with mock.patch.object(state, "mark_ready", side_effect=commit_then_fail):
            with self.assertRaises(state.WorkflowError):
                material_usage.publish_and_mark_ready(
                    self.job,
                    "inspect",
                    [self.artifact],
                    producer="edit.hd.tools.inspect_inputs",
                    producer_version="test-v1",
                    stage_input_records=self.input_records(),
                    references=[],
                )

        loaded = state.load_job(self.job.job_dir)
        receipt = material_usage.load_current_receipt(loaded, "inspect")
        self.assertEqual(receipt["stage_revision"], 1)

    def test_dependencies_are_exposed_from_the_real_state_graph(self) -> None:
        self.assertEqual(state.dependencies_for(self.job, "inspect"), ())
        self.assertEqual(
            state.dependencies_for(self.job, "visual_direction"),
            ("content_analysis", "edit_structure"),
        )
        with self.assertRaises(state.WorkflowError):
            state.dependencies_for(self.job, "unknown")


if __name__ == "__main__":
    unittest.main()

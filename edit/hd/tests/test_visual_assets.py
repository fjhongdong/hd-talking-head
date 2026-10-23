"""Public visual-assets entry tests for ShotRecipe v2 Jobs."""

from __future__ import annotations

import copy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from edit.hd.tools import (
    contract_artifacts,
    state,
    visual_assets,
    visual_assets_v2,
)


class VisualAssetsSchemaEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"source")
        self.script.write_text("测试文案", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _tree_bytes(root: Path) -> dict[str, bytes]:
        if not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def _assert_rejected_without_mutation(self, job: state.JobState) -> None:
        formal = job.job_dir / "09-visual-assets"
        formal.mkdir(parents=True, exist_ok=True)
        manifest = formal / "asset-manifest.json"
        manifest.write_bytes(b'{"schema_version":0}\n')
        track = formal / "visual-track.mp4"
        track.write_bytes(b"published-generation")
        stage_record = copy.deepcopy(job.stages["visual_assets"])
        revision = job.revision
        job_record = (job.job_dir / "workflow.json").read_bytes()
        before = self._tree_bytes(formal)
        calls = {
            "v2": mock.Mock(side_effect=AssertionError("v2 builder must not run")),
            "v2_recover": mock.Mock(
                side_effect=AssertionError("recovery must not run")
            ),
            "ready": mock.Mock(side_effect=AssertionError("state must not change")),
        }

        with mock.patch.object(
            visual_assets_v2, "prepare_visual_assets_v2", calls["v2"]
        ), mock.patch.object(
            visual_assets_v2, "_recover_publication", calls["v2_recover"]
        ), mock.patch.object(
            state, "mark_ready", calls["ready"]
        ), self.assertRaisesRegex(
            visual_assets.VisualAssetsError, "^BROLL_SCHEMA_UNSUPPORTED$"
        ):
            visual_assets.prepare_visual_assets(job, component_adapters={})

        self.assertEqual(job.revision, revision)
        self.assertEqual(job.stages["visual_assets"], stage_record)
        self.assertEqual((job.job_dir / "workflow.json").read_bytes(), job_record)
        self.assertEqual(self._tree_bytes(formal), before)
        for entrypoint in calls.values():
            entrypoint.assert_not_called()

    def test_old_job_is_rejected_before_any_visual_assets_operation(self) -> None:
        job = state.create_job(self.root, self.video, self.script, profile="legacy-v1")
        self._assert_rejected_without_mutation(job)

    def test_old_visual_plan_schema_is_rejected_before_v2_builder(self) -> None:
        job = state.create_job(
            self.root,
            self.video,
            self.script,
            profile="full-v2",
        )
        plan = job.job_dir / "07-visual-direction/visual-plan.json"
        contract_artifacts.write_json_artifact(
            plan,
            {"schema_version": 2, "segments": []},
        )
        self._assert_rejected_without_mutation(job)

    def test_invalid_v3_plan_is_rejected_before_publication_recovery(self) -> None:
        job = state.create_job(
            self.root,
            self.video,
            self.script,
            profile="full-v2",
        )
        plan = job.job_dir / "07-visual-direction/visual-plan.json"
        contract_artifacts.write_json_artifact(
            plan,
            {"schema_version": 3, "segments": []},
        )
        self._assert_rejected_without_mutation(job)

    def test_public_entry_has_no_old_job_runner_parameters(self) -> None:
        parameters = inspect.signature(visual_assets.prepare_visual_assets).parameters
        for removed in (
            "official_preview_root",
            "api_key",
            "base_url",
            "provider",
            "mask_provider",
            "hyperframes_binary",
            "segment_renderer",
        ):
            self.assertNotIn(removed, parameters)
        self.assertIn("component_adapters", parameters)
        self.assertIn("segment_ffmpeg_runner", parameters)

    def test_direct_v2_entry_rejects_old_job_before_lock_or_recovery(self) -> None:
        job = state.create_job(self.root, self.video, self.script, profile="legacy-v1")
        before = (job.job_dir / "workflow.json").read_bytes()
        recover = mock.Mock(side_effect=AssertionError("recovery must not run"))
        writer = mock.Mock(side_effect=AssertionError("writer lock must not open"))

        with mock.patch.object(
            visual_assets_v2, "_recover_publication", recover
        ), mock.patch.object(
            visual_assets_v2, "_visual_assets_writer", writer, create=True
        ), self.assertRaises(visual_assets_v2.VisualAssetsV2Error):
            visual_assets_v2.prepare_visual_assets_v2(
                job,
                component_adapters={},
            )

        recover.assert_not_called()
        writer.assert_not_called()
        self.assertEqual((job.job_dir / "workflow.json").read_bytes(), before)
        self.assertFalse(
            (job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME).exists()
        )
        self.assertFalse((job.job_dir / ".09-visual-assets.lock").exists())


class VisualAssetsPublicApiTests(unittest.TestCase):
    def test_module_exports_only_current_visual_assets_entry(self) -> None:
        self.assertEqual(
            visual_assets.__all__,
            ["VisualAssetsError", "prepare_visual_assets"],
        )
        for removed in (
            "AiStageBlocked",
            "AiJob",
            "AttemptLedger",
            "generation_id_for",
            "render_presentation_document",
            "render_review_document",
            "build_person_layers",
            "generate_ai_asset",
        ):
            self.assertFalse(hasattr(visual_assets, removed), removed)


if __name__ == "__main__":
    unittest.main()

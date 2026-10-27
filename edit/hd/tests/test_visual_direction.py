"""Integration tests for compiling visual direction into schema v3."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from edit.hd.tests.test_content_analysis import SCRIPT, VALID_ANALYSIS
from edit.hd.tests.test_visual_plan import binding, strategy_component, visual_intent
from edit.hd.tests.test_avatar_contract import avatar_fixture
from edit.hd.tests.test_startup import approve_fixture_setup
from edit.hd.tools import (
    content_analysis,
    contract_artifacts,
    material_usage,
    segment_render,
    state,
    talkcraft_workbench_bridge,
    visual_plan,
)


def candidate(asset_id: str, kind: str) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "kind": kind,
        "semantic_match_score": 0.9,
        "quality_score": 0.8,
        "hard_gates": {"semantic_match": True, "factual_reliability": True, "native_vertical": True, "quality_readability": True},
    }


def draft_segment(
    kinds: tuple[str, ...],
    *,
    segment_id: str = "seg-001",
    start: float = 0.0,
    end: float = 3.0,
) -> dict[str, object]:
    components = [strategy_component(f"component-{index + 1}", kind) for index, kind in enumerate(kinds)]
    for component in components[1:]:
        component["layer_role"] = "annotation"
        component["layout_slot"] = "annotation"
    mode = "none" if not components else "single" if len(components) == 1 else "hybrid"
    base_ids = [component["component_id"] for component in components if component["layer_role"] == "base"]
    snapshots = {
        component["component_id"]: [candidate(f"asset-{index + 1}", str(component["kind"]))]
        for index, component in enumerate(components)
        if component["kind"] in {"local_material", "official_material", "external_stock"}
    }
    return {
        "segment_id": segment_id,
        "start": start,
        "end": end,
        "content_item_ids": ["idea-01"],
        "visible_text": [],
        "visual_intent": visual_intent(segment_id),
        "visual_strategy": {
            "schema_version": 1,
            "segment_id": segment_id,
            "mode": mode,
            "rationale": "The approved composition explains the intended meaning.",
            "components": components,
            "composition": {
                "family": "no_broll" if mode == "none" else "single_full_frame" if mode == "single" else "evidence_with_data_overlay",
                "presenter_mode": "full_frame" if mode == "none" else "bottom_window",
                **({"avatar": avatar_fixture(frames=max(3, round((end - start) * 24)), source_sha256=hashlib.sha256(b"edited-aroll").hexdigest())} if mode != "none" else {}),
                "reading_order": [item["component_id"] for item in components],
                "component_dependencies": [
                    {"component_id": item["component_id"], "depends_on": base_ids[:1]}
                    for item in components
                    if item["layer_role"] == "annotation"
                ],
            },
        },
        "candidate_snapshots": snapshots,
        "bindings": {
            str(component["component_id"]): binding(str(component["kind"]), f"asset-{index + 1}")
            for index, component in enumerate(components)
        },
        "strategy_revision": 1,
    }


def replace_draft_segment_id(segment: dict[str, object], value: str) -> None:
    segment["segment_id"] = value
    segment["visual_intent"]["segment_id"] = value
    segment["visual_strategy"]["segment_id"] = value


def replace_draft_component_id(segment: dict[str, object], value: str) -> None:
    old = segment["visual_strategy"]["components"][0]["component_id"]
    segment["visual_strategy"]["components"][0]["component_id"] = value
    segment["visual_strategy"]["composition"]["reading_order"][0] = value
    segment["candidate_snapshots"][value] = segment["candidate_snapshots"].pop(old)
    segment["bindings"][value] = segment["bindings"].pop(old)


class VisualDirectionSchemaV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"video")
        self.script.write_text(SCRIPT, encoding="utf-8")
        self.job = state.create_job(self.root, self.video, self.script, profile="full-v2")
        self._approve_file("inspect", "01-inspect/report.json", b"{}\n")
        self.analysis = content_analysis.prepare_content_analysis(self.job, copy.deepcopy(VALID_ANALYSIS))
        state.approve(self.job, "content_analysis")
        self._approve_file("cover_direction", "03-cover-direction/cover-direction.json", b"{}\n")
        self._approve_file("cover", "04-cover/cover-report.json", b"{}\n")
        self._approve_file("speech_cleanup", "05-speech-cleanup/word-transcript.json",
            json.dumps({"version": 1, "words": [{"text": "Approved source evidence",
                       "start": 0.0, "end": 3.0}]}).encode())
        edit_dir = self.job.job_dir / "06-edit-structure"
        edit_plan = edit_dir / "edit-plan.json"
        timeline = edit_dir / "timeline-map.json"
        edited = edit_dir / "edited-aroll.mp4"
        contract_artifacts.write_json_artifact(edit_plan, {"canvas": {"width": 1080, "height": 1920, "fps": 24}})
        contract_artifacts.write_json_artifact(timeline, {"output_duration": 3.0, "segments": [
            {"source_start": 0.0, "source_end": 3.0, "timeline_start": 0.0, "timeline_end": 3.0}]})
        edited.write_bytes(b"edited-aroll")
        state.mark_ready(self.job, "edit_structure", (edit_plan, timeline, edited))
        state.approve(self.job, "edit_structure")
        self.asset_root = self.root / "source-snapshots"
        self.asset_root.mkdir()
        self.brief = self.root / "visual-brief.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _approve_file(self, stage_id: str, relative: str, payload: bytes) -> None:
        path = self.job.job_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        state.mark_ready(self.job, stage_id, (path,))
        state.approve(self.job, stage_id)

    def _write_brief(self, *segments: dict[str, object]) -> None:
        contract_artifacts.write_json_artifact(self.brief, {"schema_version": 3, "segments": list(segments)})

    def _install_local_material_index(self) -> None:
        material_root = self.root / "00-user-provided"
        material_root.mkdir(exist_ok=True)
        contract_artifacts.write_json_artifact(
            material_root / "material-index.json",
            {
                "schema_version": 1,
                "materials": [
                    {"material_id": "asset-1", "sha256": "1" * 64}
                ],
            },
        )
        approve_fixture_setup(self.job)

    def _assert_corrupt_published_revision_is_retained(
        self, *, as_float: bool
    ) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "corrupt recovery fixture")
        self._write_brief(draft_segment(("ai_generated",)))
        command = (
            "from pathlib import Path; "
            "from edit.hd.tools import state, visual_plan; "
            f"job=state.load_job(Path({str(self.job.job_dir)!r})); "
            f"visual_plan.prepare_visual_direction(job, Path({str(self.brief)!r}), "
            f"Path({str(self.asset_root)!r}))"
        )
        environment = os.environ.copy()
        environment["HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT"] = "staged"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 91, completed.stderr)

        journal_path = self.job.job_dir / ".visual-direction-v3.transaction.json"
        journal = contract_artifacts.read_json_artifact(journal_path)
        revision_value = (
            float(journal["new_manifest"]["published_revision"])
            if as_float
            else True
        )
        journal["new_manifest"]["published_revision"] = revision_value
        contract_artifacts.write_json_artifact(journal_path, journal)
        stage = self.job.job_dir / (
            f".visual-direction-v3.stage-{journal['generation_id']}"
        )
        before_journal = journal_path.read_bytes()
        before_target = {path.name: path.read_bytes() for path in target.iterdir()}
        before_stage = {path.name: path.read_bytes() for path in stage.iterdir()}

        fresh = state.load_job(self.job.job_dir)
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                fresh, self.brief, self.asset_root
            )

        self.assertEqual(journal_path.read_bytes(), before_journal)
        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()},
            before_target,
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in stage.iterdir()},
            before_stage,
        )

    def test_expected_workflow_and_brief_identity_fail_before_publication(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        revision = self.job.revision
        workflow_sha256 = self.job.expected_sha256
        brief_sha256 = contract_artifacts.sha256_json(
            contract_artifacts.read_json_artifact(self.brief)
        )
        compiler = mock.Mock()
        cases = (
            {
                "expected_revision": revision - 1,
                "expected_workflow_sha256": workflow_sha256,
                "director_brief_sha256": brief_sha256,
            },
            {
                "expected_revision": revision,
                "expected_workflow_sha256": workflow_sha256,
                "director_brief_sha256": "f" * 64,
            },
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(
                visual_plan.VisualPlanError
            ):
                visual_plan.prepare_visual_direction(
                    self.job,
                    self.brief,
                    self.asset_root,
                    strategy_compiler=compiler,
                    **arguments,
                )
            self.assertEqual(self.job.revision, revision)
            self.assertEqual(
                self.job.stages["visual_direction"]["status"], "pending"
            )
        compiler.assert_not_called()

    def test_paper_collage_requires_a_real_native_binding(self) -> None:
        segment = draft_segment(("code_generated",))
        segment["bindings"]["component-1"]["dependency_id"] = "paper-collage-ad"
        segment["bindings"]["component-1"]["primary_renderer"] = "PaperCollage"
        self._write_brief(segment)

        with self.assertRaisesRegex(visual_plan.VisualPlanError, "native scene or native-component binding"):
            visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        self.assertEqual(self.job.stages["visual_direction"]["status"], "pending")
        self.assertFalse((self.job.job_dir / "07-visual-direction/visual-plan.json").exists())

    def test_rejects_segment_id_that_renderer_cannot_render(self) -> None:
        segment = draft_segment((), segment_id="broll-old-process")
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "segment_id"):
            visual_plan.parse_visual_brief_json(json.dumps({
                "schema_version": 3,
                "segments": [segment],
            }))

    def test_workbench_bridge_revises_and_publishes_from_two_checkpoints(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        state.approve(self.job, "visual_direction")
        draft_dir = self.job.job_dir / ".workbench" / "drafts"
        draft_dir.mkdir(parents=True)
        revised = draft_dir / "revision.json"
        contract_artifacts.write_json_artifact(
            revised,
            {"schema_version": 3, "segments": [draft_segment(("ai_generated",))]},
        )
        base_revision = self.job.revision
        base_sha256 = self.job.expected_sha256

        result = talkcraft_workbench_bridge.apply_visual_direction_revision(
            self.job.job_dir,
            revised,
            self.asset_root,
            base_revision=base_revision,
            base_workflow_sha256=base_sha256,
            reason="Workbench parameter revision",
        )

        self.assertEqual(result["outcome"], "ready_for_review")
        self.assertEqual(result["approval_status"], "not_approved")
        self.assertEqual(result["revised_checkpoint"]["revision"], base_revision + 1)
        self.assertEqual(result["published_checkpoint"]["revision"], base_revision + 2)
        current = state.load_job(self.job.job_dir)
        self.assertEqual(current.stages["visual_direction"]["status"], "ready_for_review")

    def test_workbench_bridge_rejects_stale_v4_and_unsafe_drafts_without_writes(self) -> None:
        draft_dir = self.job.job_dir / ".workbench" / "drafts"
        draft_dir.mkdir(parents=True)
        valid = draft_dir / "valid.json"
        contract_artifacts.write_json_artifact(
            valid,
            {"schema_version": 3, "segments": [draft_segment(("external_stock",))]},
        )
        base_revision = self.job.revision
        base_sha256 = self.job.expected_sha256
        cases = []
        cases.append((valid, base_revision + 1, base_sha256, "conflicts"))
        v4 = draft_dir / "v4.json"
        contract_artifacts.write_json_artifact(v4, {"schema_version": 4})
        cases.append((v4, base_revision, base_sha256, "v4 publication"))
        outside = self.root / "outside.json"
        contract_artifacts.write_json_artifact(
            outside,
            {"schema_version": 3, "segments": [draft_segment(("external_stock",))]},
        )
        cases.append((outside, base_revision, base_sha256, "inside Job"))
        symlink = draft_dir / "linked.json"
        symlink.symlink_to(valid)
        cases.append((symlink, base_revision, base_sha256, "inside Job"))
        for path, revision, workflow_sha256, message in cases:
            with self.subTest(path=path), self.assertRaisesRegex(
                talkcraft_workbench_bridge.TalkCraftWorkbenchBridgeError,
                message,
            ):
                talkcraft_workbench_bridge.apply_visual_direction_revision(
                    self.job.job_dir,
                    path,
                    self.asset_root,
                    base_revision=revision,
                    base_workflow_sha256=workflow_sha256,
                    reason="Workbench revision",
                )
            current = state.load_job(self.job.job_dir)
            self.assertEqual(current.revision, base_revision)
            self.assertEqual(current.stages["visual_direction"]["status"], "pending")

    def test_workbench_bridge_publishes_frozen_payload_when_path_changes(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        state.approve(self.job, "visual_direction")
        draft_dir = self.job.job_dir / ".workbench" / "drafts"
        draft_dir.mkdir(parents=True)
        revised = draft_dir / "revision.json"
        contract_artifacts.write_json_artifact(
            revised,
            {"schema_version": 3, "segments": [draft_segment(("ai_generated",))]},
        )
        base_revision = self.job.revision
        base_sha256 = self.job.expected_sha256
        original_prepare = visual_plan.prepare_visual_direction

        def replace_before_prepare(*args, **kwargs):
            contract_artifacts.write_json_artifact(
                revised,
                {"schema_version": 3, "segments": [draft_segment(())]},
            )
            return original_prepare(*args, **kwargs)

        with mock.patch.object(
            talkcraft_workbench_bridge.visual_plan,
            "prepare_visual_direction",
            side_effect=replace_before_prepare,
        ):
            result = talkcraft_workbench_bridge.apply_visual_direction_revision(
                self.job.job_dir,
                revised,
                self.asset_root,
                base_revision=base_revision,
                base_workflow_sha256=base_sha256,
                reason="Workbench revision",
            )
        current = state.load_job(self.job.job_dir)
        self.assertEqual(result["outcome"], "ready_for_review")
        self.assertEqual(current.revision, base_revision + 2)
        plan = contract_artifacts.read_json_artifact(
            self.job.job_dir / result["visual_plan_path"]
        )
        self.assertEqual(plan["source_summary"], {"ai_generated": 1})

    def test_compiles_external_stock_single_into_shot_recipe_v2(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        output = visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        plan = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(plan["schema_version"], 3)
        self.assertEqual(plan["segments"][0]["visual_strategy"]["mode"], "single")
        self.assertEqual(plan["segments"][0]["shot_recipe"]["schema_version"], 2)
        self.assertEqual(plan["segments"][0]["shot_recipe"]["components"][0]["kind"], "external_stock")
        self.assertEqual(
            plan["segments"][0]["shot_recipe"]["components"][0]["render_window"]["end_frame"],
            72,
        )
        self.assertEqual(plan["source_summary"], {"external_stock": 1})
        self.assertEqual(output.parent.name, "07-visual-direction")
        self.assertEqual(self.job.stages["visual_direction"]["status"], "ready_for_review")
        self.assertEqual(
            [record["path"] for record in self.job.stages["visual_direction"]["artifacts"]],
            [
                "07-visual-direction/visual-plan.json",
                "07-visual-direction/visual-routing.md",
                "07-visual-direction/material-usage.json",
                "07-visual-direction/ownership.json",
            ],
        )
        receipt = material_usage.load_current_receipt(
            self.job, "visual_direction"
        )
        self.assertEqual(receipt["references"], [])

    def test_declares_exact_local_material_reference_and_requires_wake_opening(self) -> None:
        self._install_local_material_index()
        self._write_brief(draft_segment(("local_material",)))
        segment = contract_artifacts.read_json_artifact(self.brief)["segments"][0]
        contract_artifacts.write_json_artifact(self.job.job_dir / "manifests/confirmed-content.json", {
            "schema_version": 1, "job_id": self.job.job_id,
            "source_words": [{"index": 0, "text": "Approved source evidence"}],
            "visuals": [{"component_id": "component-1", "composition_family": "single_full_frame",
                         "visible_text": [], "binding": segment["bindings"]["component-1"]}]})
        from edit.hd.tools import motion_match_cache
        director = contract_artifacts.read_json_artifact(self.brief)
        treatment = {"numbering_scope_id": "local-material-publication-test",
            "semantic_lists": {"overlay": [], "broll": [{"row_id": "local-evidence",
            "start_word": 0, "end_word": 1, "quote": "Approved source evidence",
            "semantic": "说明已有本地资料", "visual_task": "展示原始资料",
            "components": [{"segment_id": "seg-001", "component_id": "component-1"}]}]},
            "motion_queries": [{"segment_id": "seg-001", "component_id": "component-1", "tags": ["真实资料"]}],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [], "overlay_beats": [],
                "overlay_assignments": [], "history_note": "本地资料引用测试",
                "fixed_context": [{"segment_id": "seg-001", "component_id": "component-1",
                    "start": 0.0, "end": 3.0, "skill_id": "local_material", "source_ref": "asset-1",
                    "visual_pattern": "source-evidence"}]}}
        treatment = motion_match_cache.match_once(Path(__file__).resolve().parents[3], director, treatment)
        treatment["beat_sheet"] = [{"start_word": 0, "end_word": 1, "quote": "Approved source evidence",
            "decision": "broll", "visual": "展示本地资料",
            "components": [{"segment_id": "seg-001", "component_id": "component-1"}]}]
        treatment["motion_readability"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "targets": [], "no_critical_text_reason": "metadata fixture has no authored visual labels"}]
        treatment_path = self.job.job_dir / "native-inputs/treatment.json"
        treatment_path.parent.mkdir(parents=True, exist_ok=True)
        contract_artifacts.write_json_artifact(treatment_path, treatment)
        from edit.hd.tools import visual_confirmation
        # Managed jobs must reject this old material-first draft.  Check the
        # material declaration at its own public boundary; a valid Wake Job's
        # publication/readback is covered by the native business smoke.
        with self.assertRaisesRegex(ValueError, "fixed lemo-wake/wake opening declaration"):
            visual_confirmation.prepare_visual_confirmation(self.job, self.brief, treatment_path)
        published = ["07-visual-direction/visual-plan.json", "07-visual-direction/visual-routing.md"]
        references = material_usage.visual_segment_references(director["segments"],
            consumer_kind="visual_segment", artifact_paths_by_segment={"seg-001": published})
        receipt = material_usage.build_receipt_for_publication(self.job, "visual_direction",
            producer="edit.hd.tools.visual_plan", producer_version="3",
            stage_input_records=material_usage.current_stage_input_records(self.job, "visual_direction"),
            references=references, artifact_paths=published)
        self.assertEqual(
            receipt["references"],
            [
                {
                    "material_id": "asset-1",
                    "material_sha256": "1" * 64,
                    "consumer_kind": "visual_segment",
                    "consumer_id": "seg-001",
                    "binding_path": "/segments/0/bindings/component-1/material_id",
                    "artifact_paths": [
                        "07-visual-direction/visual-plan.json",
                        "07-visual-direction/visual-routing.md",
                    ],
                }
            ],
        )

    def test_exact_segment_frames_reach_recipe_and_renderer_before_callbacks(self) -> None:
        captured: list[int] = []

        def compiler(strategy, context):
            captured.append(context["segment_frames"])
            return visual_plan._canonical_compile_strategy(strategy, context)

        self._write_brief(draft_segment(("external_stock",)))
        output = visual_plan.prepare_visual_direction(
            self.job,
            self.brief,
            self.asset_root,
            strategy_compiler=compiler,
        )
        plan = json.loads(output.read_text(encoding="utf-8"))
        segment = plan["segments"][0]
        self.assertEqual(captured[-1], 72)
        self.assertEqual(
            segment["shot_recipe"]["components"][0]["render_window"]["end_frame"],
            72,
        )
        self.assertEqual(segment_render.expected_frames(segment), 72)

        state.revise(self.job, "edit_structure", "test five second segment")
        edit_dir = self.job.job_dir / "06-edit-structure"
        timeline = edit_dir / "timeline-map.json"
        contract_artifacts.write_json_artifact(timeline, {"output_duration": 5.0})
        state.mark_ready(
            self.job,
            "edit_structure",
            (
                edit_dir / "edit-plan.json",
                timeline,
                edit_dir / "edited-aroll.mp4",
            ),
        )
        state.approve(self.job, "edit_structure")
        self._write_brief(draft_segment(("external_stock",), end=5.0))
        output = visual_plan.prepare_visual_direction(
            self.job,
            self.brief,
            self.asset_root,
            strategy_compiler=compiler,
        )
        segment = json.loads(output.read_text(encoding="utf-8"))["segments"][0]
        self.assertEqual(captured[-1], 120)
        self.assertEqual(
            segment["shot_recipe"]["components"][0]["render_window"]["end_frame"],
            120,
        )
        self.assertEqual(segment_render.expected_frames(segment), 120)

        state.revise(self.job, "visual_direction", "test frame clock rejection")
        self._write_brief(draft_segment(("external_stock",), end=3.01))
        freezer = mock.Mock()
        binding_freezer = mock.Mock()
        invalid_compiler = mock.Mock()
        state_writer = mock.Mock()
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                candidate_freezers={"external_stock": freezer},
                binding_freezers={"external_stock": binding_freezer},
                strategy_compiler=invalid_compiler,
                state_writer=state_writer,
            )
        self.assertEqual(
            (
                freezer.call_count,
                binding_freezer.call_count,
                invalid_compiler.call_count,
                state_writer.call_count,
            ),
            (0, 0, 0, 0),
        )

    def test_compiles_none_and_hybrid_without_kind_quotas(self) -> None:
        for kinds in ((), ("official_material", "external_stock", "ai_generated")):
            with self.subTest(kinds=kinds):
                if self.job.stages["visual_direction"]["status"] != "pending":
                    state.revise(self.job, "visual_direction", "test next composition")
                self._write_brief(draft_segment(kinds))
                plan = json.loads(visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root).read_text(encoding="utf-8"))
                self.assertEqual(plan["segments"][0]["shot_recipe"]["mode"], "none" if not kinds else "hybrid")
                self.assertEqual(plan["source_summary"], {kind: kinds.count(kind) for kind in dict.fromkeys(kinds)})

    def test_verified_official_pdf_keeps_official_material_classification(self) -> None:
        segment = draft_segment(("official_material",))
        segment["bindings"]["component-1"]["snapshot_path"] = "00-user-provided/research/official-report.pdf"
        self._write_brief(segment)
        plan = json.loads(visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root).read_text(encoding="utf-8"))
        self.assertEqual(plan["source_summary"], {"official_material": 1})
        self.assertEqual(plan["segments"][0]["shot_recipe"]["components"][0]["kind"], "official_material")

    def test_old_schema_fails_before_freezing_compiling_or_state_write(self) -> None:
        contract_artifacts.write_json_artifact(self.brief, {"schema_version": 2, "segments": []})
        before_revision = self.job.revision
        before_stage = copy.deepcopy(self.job.stages["visual_direction"])
        official_download = mock.Mock()
        stock_search = mock.Mock()
        ai_generation = mock.Mock()
        compiler = mock.Mock()
        state_writer = mock.Mock()
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "^BROLL_SCHEMA_UNSUPPORTED$"):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                candidate_freezers={"official_material": official_download, "external_stock": stock_search},
                binding_freezers={"ai_generated": ai_generation},
                strategy_compiler=compiler,
                state_writer=state_writer,
            )
        self.assertEqual((official_download.call_count, stock_search.call_count, ai_generation.call_count, compiler.call_count, state_writer.call_count), (0, 0, 0, 0, 0))
        self.assertEqual(self.job.revision, before_revision)
        self.assertEqual(self.job.stages["visual_direction"], before_stage)
        self.assertFalse((self.job.job_dir / "07-visual-direction").exists())

    def test_schema_v3_visual_direction_rejects_legacy_workflow_job(self) -> None:
        legacy_video = self.root / "legacy.mp4"
        legacy_script = self.root / "legacy.md"
        legacy_video.write_bytes(b"legacy-video")
        legacy_script.write_text("legacy script", encoding="utf-8")
        legacy = state.create_job(self.root, legacy_video, legacy_script, profile="legacy-v1")
        self._write_brief(draft_segment(("external_stock",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                legacy, self.brief, self.asset_root
            )

        self.assertFalse((legacy.job_dir / "07-visual-direction").exists())
        self.assertFalse(
            (legacy.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_invalid_v3_is_pure_before_all_injected_operations(self) -> None:
        segment = draft_segment(("external_stock",))
        segment["visual_strategy"]["components"][0]["kind"] = "stock"
        self._write_brief(segment)
        freezer, binding_freezer, compiler, state_writer = mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                candidate_freezers={"external_stock": freezer},
                binding_freezers={"external_stock": binding_freezer},
                strategy_compiler=compiler,
                state_writer=state_writer,
            )
        self.assertEqual((freezer.call_count, binding_freezer.call_count, compiler.call_count, state_writer.call_count), (0, 0, 0, 0))

    def test_invalid_binding_is_rejected_before_all_injected_operations(self) -> None:
        segment = draft_segment(("external_stock",))
        del segment["bindings"]["component-1"]["license_snapshot"]
        self._write_brief(segment)
        freezer, binding_freezer, compiler, state_writer = mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                candidate_freezers={"external_stock": freezer},
                binding_freezers={"external_stock": binding_freezer},
                strategy_compiler=compiler,
                state_writer=state_writer,
            )
        self.assertEqual(
            (freezer.call_count, binding_freezer.call_count, compiler.call_count, state_writer.call_count),
            (0, 0, 0, 0),
        )

    def test_identifier_controls_fail_before_callbacks_or_artifacts(self) -> None:
        cases = (
            (replace_draft_segment_id, "segment\ninjected"),
            (replace_draft_component_id, "component\x1bescape"),
            (replace_draft_component_id, "component\x7fdelete"),
        )
        for mutate, value in cases:
            with self.subTest(value=repr(value)):
                segment = draft_segment(("external_stock",))
                mutate(segment, value)
                self._write_brief(segment)
                freezer = mock.Mock()
                binding_freezer = mock.Mock()
                compiler = mock.Mock()
                state_writer = mock.Mock()
                with self.assertRaises(visual_plan.VisualPlanError):
                    visual_plan.prepare_visual_direction(
                        self.job,
                        self.brief,
                        self.asset_root,
                        candidate_freezers={"external_stock": freezer},
                        binding_freezers={"external_stock": binding_freezer},
                        strategy_compiler=compiler,
                        state_writer=state_writer,
                    )
                self.assertEqual(
                    (
                        freezer.call_count,
                        binding_freezer.call_count,
                        compiler.call_count,
                        state_writer.call_count,
                    ),
                    (0, 0, 0, 0),
                )
                self.assertFalse(
                    (self.job.job_dir / "07-visual-direction").exists()
                )
                self.assertFalse(
                    (
                        self.job.job_dir
                        / ".visual-direction-v3.transaction.json"
                    ).exists()
                )
                self.assertEqual(
                    list(self.job.job_dir.glob(".07-visual-direction.*")), []
                )

    def test_segment_freezes_all_bindings_before_native_rejection(self) -> None:
        kinds = ("local_material", "official_material", "external_stock", "code_generated", "ai_generated")
        segment = draft_segment(kinds)
        events: list[tuple[str, str]] = []

        def freeze_candidate(kind: str, values: list[dict[str, object]]) -> dict[str, object]:
            events.append(("candidate", kind))
            return copy.deepcopy(values[0])

        def freeze_binding(kind: str, value: dict[str, object]) -> dict[str, object]:
            events.append(("binding", kind))
            return copy.deepcopy(value)

        def compile_strategy(strategy: dict[str, object], context: dict[str, object]) -> dict[str, object]:
            events.append(("compile", str(strategy["mode"])))
            return visual_plan._canonical_compile_strategy(strategy, context)

        # Test the actual per-segment freeze seam. New full publication also
        # requires the independently tested semantic/cache/native qualification.
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "native scene or native-component binding"):
            visual_plan._freeze_and_compile_segment(
                segment,
                candidate_freezers={kind: freeze_candidate for kind in kinds[:3]},
                binding_freezers={kind: freeze_binding for kind in kinds},
                strategy_compiler=compile_strategy,
            )
        self.assertEqual(events, [
            ("candidate", "local_material"), ("binding", "local_material"),
            ("candidate", "official_material"), ("binding", "official_material"),
            ("candidate", "external_stock"), ("binding", "external_stock"),
            ("binding", "code_generated"), ("binding", "ai_generated"),
            ("compile", "hybrid"),
        ])

    def test_input_objects_are_not_mutated_and_output_is_repeatable(self) -> None:
        segment = draft_segment(("external_stock", "ai_generated"))
        before = copy.deepcopy(segment)
        self._write_brief(segment)
        first_path = visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        first_bytes = first_path.read_bytes()
        self.assertEqual(segment, before)
        state.revise(self.job, "visual_direction", "repeat deterministic compile")
        second_path = visual_plan.prepare_visual_direction(self.job, self.brief, self.asset_root)
        self.assertEqual(first_bytes, second_path.read_bytes())

    def test_staging_failure_publishes_nothing_and_does_not_advance_state(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        before_revision = self.job.revision

        def write_partial(path, plan_payload, _review_payload, _manifest):
            path.mkdir(mode=0o700)
            contract_artifacts.write_bytes_atomic(
                path / "visual-plan.json", plan_payload
            )
            raise contract_artifacts.ContractArtifactError("injected")

        with mock.patch.object(
            visual_plan, "_write_generation", side_effect=write_partial
        ), self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )
        self.assertEqual(self.job.revision, before_revision)
        self.assertEqual(self.job.stages["visual_direction"]["status"], "pending")
        self.assertFalse((self.job.job_dir / "07-visual-direction").exists())
        self.assertEqual(
            list(self.job.job_dir.glob(".07-visual-direction.*")), []
        )
        self.assertEqual(
            sorted(
                path.name
                for path in self.job.job_dir.iterdir()
                if path.name.startswith(".visual-direction-v3.")
            ),
            [".visual-direction-v3.lock"],
        )

    def test_crash_after_journal_reservation_is_recovered_before_publish(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        command = (
            "from pathlib import Path; "
            "from edit.hd.tools import state, visual_plan; "
            f"job=state.load_job(Path({str(self.job.job_dir)!r})); "
            f"visual_plan.prepare_visual_direction(job, Path({str(self.brief)!r}), "
            f"Path({str(self.asset_root)!r}))"
        )
        environment = os.environ.copy()
        environment["HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT"] = "reserved"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 91, completed.stderr)

        output = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        )
        self.assertTrue(output.is_file())
        self.assertEqual(
            sorted(
                path.name
                for path in self.job.job_dir.iterdir()
                if path.name.startswith(".visual-direction-v3.")
            ),
            [".visual-direction-v3.lock"],
        )

    def test_state_failure_restores_previous_complete_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        previous = {
            path.name: path.read_bytes()
            for path in target.iterdir()
            if path.is_file()
        }
        state.revise(self.job, "visual_direction", "try a different semantic plan")
        self._write_brief(draft_segment(("ai_generated",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                state_writer=mock.Mock(side_effect=RuntimeError("injected")),
            )

        restored = {
            path.name: path.read_bytes()
            for path in target.iterdir()
            if path.is_file()
        }
        self.assertEqual(restored, previous)
        self.assertEqual(self.job.stages["visual_direction"]["status"], "needs_revision")
        self.assertEqual(list(self.job.job_dir.glob(".07-visual-direction.*")), [])

    def test_state_writer_noop_fails_and_rolls_back_first_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        before = (self.job.revision, copy.deepcopy(self.job.stages))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                state_writer=mock.Mock(),
            )

        persisted = state.load_job(self.job.job_dir)
        self.assertEqual((persisted.revision, persisted.stages), before)
        self.assertEqual((self.job.revision, self.job.stages), before)
        self.assertFalse((self.job.job_dir / "07-visual-direction").exists())

    def test_state_writer_noop_does_not_confuse_identical_revision_for_commit(self) -> None:
        segment = draft_segment(("external_stock",))
        self._write_brief(segment)
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        previous = {path.name: path.read_bytes() for path in target.iterdir()}
        state.revise(self.job, "visual_direction", "repeat identical plan")
        before = (self.job.revision, copy.deepcopy(self.job.stages))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                state_writer=mock.Mock(),
            )

        self.assertEqual((self.job.revision, self.job.stages), before)
        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, previous
        )

    def test_state_writer_commit_then_throw_finalizes_committed_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "commit-then-throw test")
        previous = {path.name: path.read_bytes() for path in target.iterdir()}
        self._write_brief(draft_segment(("ai_generated",)))

        def commit_then_throw(job, stage_id, artifacts) -> None:
            state.mark_ready(job, stage_id, artifacts)
            raise RuntimeError("injected after durable commit")

        output = visual_plan.prepare_visual_direction(
            self.job,
            self.brief,
            self.asset_root,
            state_writer=commit_then_throw,
        )

        persisted = state.load_job(self.job.job_dir)
        self.assertEqual(output.parent, target)
        self.assertEqual(
            persisted.stages["visual_direction"]["status"], "ready_for_review"
        )
        self.assertEqual(self.job.revision, persisted.revision)
        self.assertNotEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, previous
        )
        self.assertEqual(
            sorted(
                path.name
                for path in self.job.job_dir.iterdir()
                if path.name.startswith(".visual-direction-v3.")
            ),
            [".visual-direction-v3.lock"],
        )

    def test_committed_journal_fsync_error_still_returns_success(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        remove = visual_plan._remove_journal

        def remove_then_fsync_error(path, expected) -> None:
            remove(path, expected)
            raise OSError("injected after journal unlink")

        with mock.patch.object(
            visual_plan, "_remove_journal", side_effect=remove_then_fsync_error
        ):
            output = visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertTrue(output.is_file())
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )

    def test_committed_lock_release_error_still_returns_success(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        release = visual_plan._release_job_lock

        def release_then_error(descriptor) -> None:
            release(descriptor)
            raise OSError("injected after lock release")

        with mock.patch.object(
            visual_plan, "_release_job_lock", side_effect=release_then_error
        ):
            output = visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertTrue(output.is_file())
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )

    def test_unrelated_concurrent_winner_is_preserved_with_journal(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        raced: dict[str, bytes] = {}

        def concurrent_winner(job, stage_id, _artifacts) -> None:
            alternate = job.job_dir / "07-alternate" / "winner.json"
            alternate.parent.mkdir()
            alternate.write_bytes(b"{}\n")
            state.mark_ready(job, stage_id, (alternate,))
            raced["workflow"] = (
                self.job.job_dir / "workflow.json"
            ).read_bytes()

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                state_writer=concurrent_winner,
            )

        self.assertTrue(raced)
        self.assertEqual(
            (self.job.job_dir / "workflow.json").read_bytes(), raced["workflow"]
        )
        persisted = state.load_job(self.job.job_dir)
        self.assertEqual(
            persisted.stages["visual_direction"]["artifacts"][0]["path"],
            "07-alternate/winner.json",
        )
        self.assertTrue(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").is_file()
        )

    def test_old_concurrent_winner_rolls_back_without_overwrite(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        previous = {path.name: path.read_bytes() for path in target.iterdir()}
        state.revise(self.job, "visual_direction", "same-content concurrent winner")

        def concurrent_block(_job, _stage_id, _artifacts) -> None:
            concurrent = state.load_job(self.job.job_dir)
            state.block(
                concurrent,
                "visual_direction",
                "concurrent winner",
                ai_attempts=0,
            )

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                state_writer=concurrent_block,
            )

        persisted = state.load_job(self.job.job_dir)
        self.assertEqual(
            persisted.stages["visual_direction"]["status"], "blocked"
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, previous
        )
        self.assertFalse(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_foreign_initial_target_is_never_replaced_or_deleted(self) -> None:
        target = self.job.job_dir / "07-visual-direction"
        target.mkdir()
        foreign = target / "keep.txt"
        foreign.write_bytes(b"foreign")
        self._write_brief(draft_segment(("external_stock",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(foreign.read_bytes(), b"foreign")
        self.assertEqual({path.name for path in target.iterdir()}, {"keep.txt"})
        self.assertEqual(self.job.stages["visual_direction"]["status"], "pending")

    def test_unknown_sibling_in_owned_target_blocks_revision_without_touching_tree(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "new strategy")
        unknown = target / "unknown.txt"
        unknown.write_bytes(b"do-not-touch")
        before = {path.name: path.read_bytes() for path in target.iterdir()}
        self._write_brief(draft_segment(("ai_generated",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, before
        )
        self.assertEqual(unknown.read_bytes(), b"do-not-touch")

    def test_polluted_ownership_manifest_is_never_replaced_or_deleted(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "manifest test")
        manifest = target / "ownership.json"
        manifest.write_bytes(b'{"schema_version":3}\n')
        before = {path.name: path.read_bytes() for path in target.iterdir()}
        self._write_brief(draft_segment(("ai_generated",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, before
        )

    def test_boolean_manifest_revision_is_retained_without_cleanup(self) -> None:
        self._assert_corrupt_published_revision_is_retained(as_float=False)

    def test_float_manifest_revision_is_retained_without_cleanup(self) -> None:
        self._assert_corrupt_published_revision_is_retained(as_float=True)

    def test_symlink_member_is_never_followed_or_removed(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "symlink test")
        external = self.root / "foreign-routing.md"
        external.write_bytes(b"foreign")
        routing = target / "visual-routing.md"
        routing.unlink()
        routing.symlink_to(external)
        self._write_brief(draft_segment(("ai_generated",)))

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertTrue(routing.is_symlink())
        self.assertEqual(external.read_bytes(), b"foreign")

    def test_directory_exchange_race_fails_closed_and_keeps_previous_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "race test")
        previous = {path.name: path.read_bytes() for path in target.iterdir()}
        self._write_brief(draft_segment(("ai_generated",)))
        exchange = state._atomic_exchange_rename

        def exchange_then_revert(source: Path, destination: Path) -> None:
            exchange(source, destination)
            if destination.name == "07-visual-direction":
                exchange(source, destination)

        with mock.patch.object(
            state,
            "_atomic_exchange_rename",
            side_effect=exchange_then_revert,
        ), self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()},
            previous,
        )
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )
        self.assertFalse(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_crash_after_directory_swap_is_recovered_before_next_publish(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        command = (
            "from pathlib import Path; "
            "from edit.hd.tools import state, visual_plan; "
            f"job=state.load_job(Path({str(self.job.job_dir)!r})); "
            f"visual_plan.prepare_visual_direction(job, Path({str(self.brief)!r}), "
            f"Path({str(self.asset_root)!r}))"
        )
        environment = os.environ.copy()
        environment["HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT"] = "swapped"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 91, completed.stderr)
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "pending",
        )

        output = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        )

        self.assertTrue(output.is_file())
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )
        self.assertEqual(
            sorted(
                path.name
                for path in self.job.job_dir.iterdir()
                if path.name.startswith(".visual-direction-v3.")
            ),
            [".visual-direction-v3.lock"],
        )

    def test_crash_after_state_commit_finalizes_exact_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        command = (
            "from pathlib import Path; "
            "from edit.hd.tools import state, visual_plan; "
            f"job=state.load_job(Path({str(self.job.job_dir)!r})); "
            f"visual_plan.prepare_visual_direction(job, Path({str(self.brief)!r}), "
            f"Path({str(self.asset_root)!r}))"
        )
        environment = os.environ.copy()
        environment["HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT"] = "state_committed"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 91, completed.stderr)
        persisted = state.load_job(self.job.job_dir)
        self.assertEqual(
            persisted.stages["visual_direction"]["status"], "ready_for_review"
        )
        target = self.job.job_dir / "07-visual-direction"
        committed = {path.name: path.read_bytes() for path in target.iterdir()}

        fresh = state.load_job(self.job.job_dir)
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                fresh, self.brief, self.asset_root
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, committed
        )
        self.assertEqual(
            fresh.stages["visual_direction"]["status"], "ready_for_review"
        )
        self.assertEqual(
            sorted(
                path.name
                for path in self.job.job_dir.iterdir()
                if path.name.startswith(".visual-direction-v3.")
            ),
            [".visual-direction-v3.lock"],
        )

    def test_cleanup_throw_after_previous_removal_returns_committed_generation(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "cleanup crash test")
        self._write_brief(draft_segment(("ai_generated",)))
        remove = visual_plan._remove_generation
        injected = False

        def remove_then_throw(path, manifest) -> None:
            nonlocal injected
            remove(path, manifest)
            if path.name.startswith(".visual-direction-v3.stage-") and not injected:
                injected = True
                raise RuntimeError("injected after old generation removal")

        with mock.patch.object(
            visual_plan,
            "_remove_generation",
            side_effect=remove_then_throw,
        ):
            output = visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(output.parent, target)
        committed = {path.name: path.read_bytes() for path in target.iterdir()}
        self.assertTrue(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").is_file()
        )
        fresh = state.load_job(self.job.job_dir)
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                fresh, self.brief, self.asset_root
            )
        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, committed
        )
        self.assertFalse(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_committed_target_succeeds_when_old_cleanup_is_polluted(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "polluted cleanup")
        self._write_brief(draft_segment(("ai_generated",)))
        remove = visual_plan._remove_generation
        polluted = False

        def pollute_old_stage(path, manifest) -> None:
            nonlocal polluted
            if path.name.startswith(".visual-direction-v3.stage-") and not polluted:
                polluted = True
                (path / "foreign.txt").write_bytes(b"foreign")
            remove(path, manifest)

        with mock.patch.object(
            visual_plan, "_remove_generation", side_effect=pollute_old_stage
        ):
            output = visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        self.assertEqual(output.parent, target)
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )
        self.assertTrue(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").is_file()
        )

    def test_cleanup_runtime_error_before_mutation_keeps_committed_success(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "cleanup runtime error")
        self._write_brief(draft_segment(("ai_generated",)))

        with mock.patch.object(
            visual_plan,
            "_remove_generation",
            side_effect=RuntimeError("cleanup failed before mutation"),
        ):
            output = visual_plan.prepare_visual_direction(
                self.job, self.brief, self.asset_root
            )

        committed = {path.name: path.read_bytes() for path in target.iterdir()}
        self.assertEqual(output.parent, target)
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["visual_direction"]["status"],
            "ready_for_review",
        )
        self.assertTrue(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").is_file()
        )

        fresh = state.load_job(self.job.job_dir)
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                fresh, self.brief, self.asset_root
            )
        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, committed
        )
        self.assertFalse(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_crash_during_previous_cleanup_resumes_committed_finalize(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))
        target = visual_plan.prepare_visual_direction(
            self.job, self.brief, self.asset_root
        ).parent
        state.revise(self.job, "visual_direction", "partial cleanup crash")
        self._write_brief(draft_segment(("ai_generated",)))
        command = (
            "from pathlib import Path; "
            "from edit.hd.tools import state, visual_plan; "
            f"job=state.load_job(Path({str(self.job.job_dir)!r})); "
            f"visual_plan.prepare_visual_direction(job, Path({str(self.brief)!r}), "
            f"Path({str(self.asset_root)!r}))"
        )
        environment = os.environ.copy()
        environment["HD_VISUAL_PLAN_V3_CRASH_CHECKPOINT"] = "cleanup_partial"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 91, completed.stderr)
        committed = {path.name: path.read_bytes() for path in target.iterdir()}

        fresh = state.load_job(self.job.job_dir)
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                fresh, self.brief, self.asset_root
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in target.iterdir()}, committed
        )
        self.assertFalse(
            (self.job.job_dir / ".visual-direction-v3.transaction.json").exists()
        )

    def test_compiler_cannot_mutate_approved_recipe_identity_or_revision(self) -> None:
        fields = {
            "strategy_revision": lambda recipe: recipe.update(strategy_revision=99),
            "segment_id": lambda recipe: recipe.update(segment_id="other"),
            "component_id": lambda recipe: recipe["components"][0].update(component_id="other"),
            "kind": lambda recipe: recipe["components"][0].update(kind="ai_generated"),
            "semantic_role": lambda recipe: recipe["components"][0].update(semantic_role="mood"),
            "media_type": lambda recipe: recipe["components"][0].update(media_type="video"),
            "layout_slot": lambda recipe: recipe["components"][0]["render_window"].update(layout_slot="other"),
        }
        for field, mutate in fields.items():
            with self.subTest(field=field):
                self._write_brief(draft_segment(("external_stock",)))

                def compiler(strategy, context, mutate=mutate):
                    compiled = visual_plan._canonical_compile_strategy(strategy, context)
                    mutate(compiled)
                    return compiled

                with self.assertRaises(visual_plan.VisualPlanError):
                    visual_plan.prepare_visual_direction(
                        self.job,
                        self.brief,
                        self.asset_root,
                        strategy_compiler=compiler,
                    )
                self.assertEqual(
                    self.job.stages["visual_direction"]["status"], "pending"
                )

    def test_compiler_mutating_its_strategy_copy_cannot_change_approved_fields(self) -> None:
        self._write_brief(draft_segment(("external_stock",)))

        def compiler(strategy, context):
            strategy["components"][0].update(
                layer_role="annotation",
                brief="mutated callback brief",
            )
            return visual_plan._canonical_compile_strategy(strategy, context)

        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan.prepare_visual_direction(
                self.job,
                self.brief,
                self.asset_root,
                strategy_compiler=compiler,
            )
        self.assertEqual(self.job.stages["visual_direction"]["status"], "pending")

    def test_block_reason_rejects_ascii_control_characters_without_state_change(self) -> None:
        before = (self.job.revision, copy.deepcopy(self.job.stages))
        for codepoint in (*range(0x20), 0x7F):
            reason = f"invalid{chr(codepoint)}reason"
            with self.subTest(codepoint=codepoint), self.assertRaises(
                visual_plan.VisualPlanError
            ):
                visual_plan.block_visual_direction(self.job, reason)
            self.assertEqual((self.job.revision, self.job.stages), before)


if __name__ == "__main__":
    unittest.main()

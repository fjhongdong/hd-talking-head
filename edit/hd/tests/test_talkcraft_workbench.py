from __future__ import annotations

import copy
import unittest

from edit.hd.tests.test_render_span import v4_plan
from edit.hd.tests.test_talkcraft_contract import brief as production_brief
from edit.hd.tests.test_visual_plan import valid_plan
from edit.hd.tools import (
    contract_artifacts,
    render_span,
    semantic_events,
    talkcraft_contract,
    talkcraft_workbench,
)


def transition_plan() -> dict[str, object]:
    plan = valid_plan(())
    plan["schema_version"] = 4
    first = plan["segments"][0]
    first["end"] = 1.5
    second = copy.deepcopy(first)
    second["segment_id"] = "seg-002"
    second["start"] = 1.5
    second["end"] = 3.0
    second["visual_intent"]["segment_id"] = "seg-002"
    second["visual_strategy"]["segment_id"] = "seg-002"
    second["shot_recipe"]["segment_id"] = "seg-002"
    plan["segments"] = [first, second]
    transition_card = next(
        card["card_id"]
        for card in talkcraft_contract.load_card_registry()["cards"]
        if card["production"]["production_role"] == "transition"
    )
    target = {
        "kind": "boundary",
        "boundary_id": "edge-001",
        "card_slot_id": "edge-001-card-001",
        "card_id": transition_card,
        "start_frame": 32,
        "end_frame": 40,
    }
    chunks = [
        {
            "chunk_id": "chunk-001",
            "start_frame": 0,
            "end_frame": 48,
            "execution_targets": [target],
        },
        {
            "chunk_id": "chunk-002",
            "start_frame": 48,
            "end_frame": 72,
            "execution_targets": [],
        },
    ]
    for chunk in chunks:
        chunk["spec_sha256"] = render_span.chunk_spec_sha256(
            "span-001", chunk
        )
    plan["render_spans"] = [{
        "span_id": "span-001",
        "mode": "transition_chain",
        "segment_ids": ["seg-001", "seg-002"],
        "start_frame": 0,
        "end_frame": 72,
        "scene_brief_sha256": "e" * 64,
        "boundaries": [{
            "boundary_id": "edge-001",
            "card_slot_id": "edge-001-card-001",
            "from_segment_id": "seg-001",
            "to_segment_id": "seg-002",
            "card_id": transition_card,
            "start_frame": 32,
            "end_frame": 40,
        }],
        "chunks": chunks,
    }]
    unsigned = {
        key: value for key, value in plan.items()
        if key != "visual_plan_sha256"
    }
    plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
    return plan


def brief_bundles(plan: dict[str, object]) -> dict[str, object]:
    chunk = plan["render_spans"][0]["chunks"][0]
    target = chunk["execution_targets"][0]
    payload = production_brief()
    registry = talkcraft_contract.load_card_registry()
    card = next(item for item in registry["cards"] if item["card_id"] == target["card_id"])
    payload["card_id"] = target["card_id"]
    payload["owner"] = {
        "type": "span",
        "id": "span-001",
        "chunk_id": "chunk-001",
        "visual_plan_sha256": plan["visual_plan_sha256"],
        "spec_sha256": chunk["spec_sha256"],
        "scene_brief_sha256": plan["render_spans"][0]["scene_brief_sha256"],
    }
    payload["execution_target"] = copy.deepcopy(target)
    payload["execution_target"].pop("card_id")
    payload["execution_target"].pop("start_frame")
    payload["execution_target"].pop("end_frame")
    payload["frame_scope"].update(
        global_start_frame=chunk["start_frame"],
        global_end_frame=chunk["end_frame"],
        span_start_frame=chunk["start_frame"],
        span_end_frame=chunk["end_frame"],
        scene_duration_frames=chunk["end_frame"],
    )
    payload["render"].update(
        entrypoint=card["production"]["derived_entrypoint"],
        implementation_sha256=card["production"]["implementation_sha256"],
        adapter_version=card["production"]["adapter_version"],
        qualification_id=card["production"]["qualification_id"],
        duration_frames=chunk["end_frame"] - chunk["start_frame"],
    )
    entry = {
        "brief": payload,
        "brief_sha256": contract_artifacts.sha256_json(payload),
    }
    unsigned = {
        "schema_version": "talkcraft-brief-bundle/v1",
        "owner": copy.deepcopy(payload["owner"]),
        "briefs": [entry],
    }
    return {
        "chunk-001": {
            **unsigned,
            "bundle_sha256": contract_artifacts.sha256_json(unsigned),
        }
    }


class TalkCraftWorkbenchReviewTests(unittest.TestCase):
    def test_review_mapping_preserves_semantics_and_uses_local_canary_frames(self) -> None:
        mapping = talkcraft_workbench.build_v4_review_mapping(
            transition_plan(), canary_chunk_ids=("chunk-001",)
        )
        self.assertFalse(mapping["complete_visual_track"])
        self.assertEqual(mapping["canary_selection"]["approval_status"], "not_evaluated")
        self.assertEqual(mapping["canary_selection"]["total_frames"], 48)
        chunk = mapping["render_spans"][0]["chunks"][0]
        self.assertEqual(
            chunk["segment_overlaps"],
            [
                {"segment_id": "seg-001", "start_frame": 0, "end_frame": 36},
                {"segment_id": "seg-002", "start_frame": 36, "end_frame": 48},
            ],
        )
        self.assertEqual(
            chunk["canary_preview_range"],
            {"output_start_frame": 0, "output_end_frame": 48},
        )
        self.assertEqual(chunk["execution_targets"][0]["kind"], "boundary")

    def test_review_mapping_is_deterministic_and_rejects_false_canaries(self) -> None:
        plan = transition_plan()
        first = talkcraft_workbench.build_v4_review_mapping(plan)
        second = talkcraft_workbench.build_v4_review_mapping(plan)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(
            talkcraft_workbench.TalkCraftWorkbenchError,
            "execution targets",
        ):
            talkcraft_workbench.build_v4_review_mapping(
                plan, canary_chunk_ids=("chunk-002",)
            )
        with self.assertRaisesRegex(
            talkcraft_workbench.TalkCraftWorkbenchError,
            "requires VisualPlan v4",
        ):
            talkcraft_workbench.build_v4_review_mapping(valid_plan())

    def test_review_mapping_accepts_component_card_canary(self) -> None:
        card_id = talkcraft_contract.load_card_registry()["cards"][0]["card_id"]
        mapping = talkcraft_workbench.build_v4_review_mapping(
            v4_plan(card_id), canary_chunk_ids=("chunk-001",)
        )
        chunk = mapping["render_spans"][0]["chunks"][0]
        self.assertEqual(chunk["talkcraft_target_count"], 1)
        self.assertEqual(mapping["canary_selection"]["total_frames"], 72)

    def test_edit_contract_applies_safe_overrides_to_new_draft_bundle(self) -> None:
        plan = transition_plan()
        bundles = brief_bundles(plan)
        contract = talkcraft_workbench.build_v4_edit_contract(plan, bundles)
        target_id = contract["targets"][0]["target_id"]
        self.assertEqual(contract["role"], "editable_draft_only")
        self.assertEqual(
            [item["key"] for item in contract["targets"][0]["parameters"]],
            ["display_text", "theme"],
        )
        revised = talkcraft_workbench.apply_v4_overrides(
            plan,
            bundles,
            {target_id: {"display_text": "新标题", "theme": "apple-light"}},
        )
        original = bundles["chunk-001"]["briefs"][0]["brief"]
        edited = revised["chunk-001"]["briefs"][0]["brief"]
        self.assertEqual(original["text"]["display"], "这是显示文字")
        self.assertEqual(edited["text"]["display"], "新标题")
        self.assertEqual(edited["style"]["theme"], "apple-light")
        talkcraft_contract.validate_draft_brief_bundle(revised["chunk-001"])

    def test_edit_contract_can_expose_bound_event_ids(self) -> None:
        plan = transition_plan()
        bundles = brief_bundles(plan)
        event_plan = semantic_events.build_semantic_event_plan(
            visual_plan_sha256=plan["visual_plan_sha256"],
            transcript_identity="transcript-v1",
            visual_plan=plan,
            events=[{
                "event_id": "segment-start",
                "kind": "segment",
                "segment_id": "seg-001",
                "span_id": None,
                "word_range": [0, 1],
                "start_frame": 0,
                "end_frame": 48,
                "semantic_role": "process",
                "trigger": "segment_start",
                "channels": {"visual": [], "caption": {}, "audio": [], "spatial": {}, "transition": {}},
            }],
        )
        bundles["chunk-001"]["briefs"][0]["brief"]["events"] = [{
            "anchor_id": "segment-start", "type": "text", "frame": 12,
            "payload": {"text": "事件标题"},
        }]
        brief_entry = bundles["chunk-001"]["briefs"][0]
        brief_entry["brief_sha256"] = contract_artifacts.sha256_json(
            brief_entry["brief"]
        )
        unsigned_bundle = {
            key: value
            for key, value in bundles["chunk-001"].items()
            if key != "bundle_sha256"
        }
        bundles["chunk-001"]["bundle_sha256"] = contract_artifacts.sha256_json(
            unsigned_bundle
        )
        contract = talkcraft_workbench.build_v4_edit_contract(
            plan, bundles, semantic_event_plan=event_plan
        )
        self.assertEqual(contract["semantic_event_plan_sha256"], event_plan["plan_sha256"])
        self.assertEqual(contract["targets"][0]["event_ids"], ["segment-start"])
        revised = talkcraft_workbench.apply_v4_overrides(
            plan,
            bundles,
            {contract["targets"][0]["target_id"]: {"theme": "apple-light"}},
            semantic_event_plan=event_plan,
        )
        self.assertEqual(
            revised["chunk-001"]["briefs"][0]["brief"]["style"]["theme"],
            "apple-light",
        )

    def test_edit_contract_rejects_unknown_targets_and_fields(self) -> None:
        plan = transition_plan()
        bundles = brief_bundles(plan)
        with self.assertRaisesRegex(
            talkcraft_workbench.TalkCraftWorkbenchError, "unknown target"
        ):
            talkcraft_workbench.apply_v4_overrides(
                plan, bundles, {"component:missing:missing": {"theme": "apple-dark"}}
            )
        target_id = talkcraft_workbench.build_v4_edit_contract(
            plan, bundles
        )["targets"][0]["target_id"]
        with self.assertRaisesRegex(
            talkcraft_workbench.TalkCraftWorkbenchError, "fields"
        ):
            talkcraft_workbench.apply_v4_overrides(
                plan, bundles, {target_id: {"timing": 12}}
            )


if __name__ == "__main__":
    unittest.main()

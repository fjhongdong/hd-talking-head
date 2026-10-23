"""Focused tests for the first Hypit-inspired contract layer."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from edit.hd.tools.card_event_capabilities import (
    CardEventCapabilityError,
    can_card_consume_event,
    validate_card_event_capabilities,
)
from edit.hd.tools.contract_artifacts import canonical_json_bytes, sha256_json
from edit.hd.tools import event_audio
from edit.hd.tools.event_binding import (
    EventBindingError,
    build_event_binding_manifest,
    validate_event_binding_manifest,
)
from edit.hd.tools.semantic_events import (
    SemanticEventError,
    build_segment_event_plan,
    build_semantic_event_plan,
    validate_subtitle_event_alignment,
    validate_audio_event_alignment,
    validate_semantic_event_plan,
)
from edit.hd.tools.variant_matrix import VariantMatrixError, build_variant_matrix, validate_variant_matrix
from edit.hd.tools.region_timeline import (
    RegionTimelineError,
    build_region_timeline,
    resolve_event_box,
    validate_region_timeline,
)
from edit.hd.tools.talkcraft_matcher import (
    TalkCraftMatchError,
    DEFAULT_EVENT_CAPABILITIES,
    match_cards,
)
from edit.hd.tools.visual_span_contract import (
    _optional_semantic_event_plan,
)


def visual_plan_fixture() -> dict[str, object]:
    return {
        "schema_version": 3,
        "segments": [{"segment_id": "seg-01"}],
        "render_spans": [{"span_id": "span-01"}],
    }


def event_plan_fixture() -> dict[str, object]:
    visual_plan = visual_plan_fixture()
    return build_semantic_event_plan(
        visual_plan_sha256=sha256_json(visual_plan),
        transcript_identity="transcript-v1",
        visual_plan=visual_plan,
        events=[
            {
                "event_id": "moment-problem-01",
                "kind": "moment",
                "segment_id": "seg-01",
                "span_id": "span-01",
                "word_range": [0, 3],
                "start_frame": 0,
                "end_frame": 24,
                "semantic_role": "problem",
                "trigger": "semantic_boundary",
                "channels": {
                    "visual": ["impact-open-title"],
                    "caption": {"emphasis": True},
                    "audio": ["impact-hit"],
                    "spatial": {"reserve": "top_safe_zone"},
                    "transition": {},
                },
            }
        ],
    )


def candidate(candidate_id: str = "cand-visual-01") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "target_id": "final-video",
        "slot": "visual",
        "status": "approved",
        "input_fingerprint": "1" * 64,
        "artifact_sha256": "2" * 64,
        "source_revision": "rev-01",
        "reuse_from": None,
        "affected_scope": ["seg-01"],
        "approval": {
            "status": "approved",
            "stage": "visual_canary",
            "revision": "rev-01",
            "receipt_sha256": "3" * 64,
        },
    }


class SemanticEventContractTests(unittest.TestCase):
    def test_segment_event_compiler_uses_approved_word_offsets(self) -> None:
        plan = {
            **visual_plan_fixture(),
            "visual_plan_sha256": "a" * 64,
        }
        plan["segments"][0]["content_item_ids"] = ["idea-01"]
        plan["segments"][0].update({"start": 0.0, "end": 1.0})
        compiled = build_segment_event_plan(
            visual_plan=plan,
            transcript_identity="word-transcript-v1",
            content_items=[{
                "id": "idea-01",
                "source_text": "这是测试",
                "source_span": [0, 4],
                "semantic_type": "process",
            }],
            words=[
                {"text": "这", "start": 0.0, "end": 0.2},
                {"text": "是", "start": 0.2, "end": 0.4},
                {"text": "测试", "start": 0.4, "end": 0.8},
            ],
        )
        self.assertEqual(compiled["events"][0]["word_range"], [0, 3])
        self.assertEqual(compiled["events"][0]["start_frame"], 0)
        self.assertEqual(compiled["events"][0]["end_frame"], 24)

    def test_subtitle_cues_bind_to_one_event_window(self) -> None:
        event_plan = event_plan_fixture()
        subtitle_plan = {
            "cues": [{"id": "cue-01", "segment_id": "seg-01", "start": 0.25, "end": 0.75}]
        }
        binding = validate_subtitle_event_alignment(subtitle_plan, event_plan)
        self.assertEqual(binding[0]["event_id"], "moment-problem-01")
        invalid = {"cues": [{"id": "cue-01", "segment_id": "seg-unknown", "start": 0.25, "end": 0.75}]}
        with self.assertRaises(SemanticEventError):
            validate_subtitle_event_alignment(invalid, event_plan)

    def test_audio_cues_require_explicit_event_identity(self) -> None:
        event_plan = event_plan_fixture()
        audio = {"cues": [{"cue_id": "impact-hit", "event_id": "moment-problem-01", "start_frame": 4, "end_frame": 16}]}
        self.assertEqual(validate_audio_event_alignment(audio, event_plan)[0]["event_id"], "moment-problem-01")
        invalid = {"cues": [{"cue_id": "impact-hit", "event_id": "wrong", "start_frame": 4, "end_frame": 16}]}
        with self.assertRaises(SemanticEventError):
            validate_audio_event_alignment(invalid, event_plan)

    def test_build_and_validate_event_plan(self) -> None:
        plan = event_plan_fixture()
        self.assertEqual(plan["schema_version"], "semantic-event-plan/v1")
        self.assertEqual(plan["plan_sha256"], sha256_json({key: value for key, value in plan.items() if key != "plan_sha256"}))
        self.assertEqual(validate_semantic_event_plan(plan, visual_plan=visual_plan_fixture()), plan)

    def test_event_plan_rejects_wrong_visual_plan_or_order(self) -> None:
        plan = event_plan_fixture()
        with self.assertRaises(SemanticEventError):
            validate_semantic_event_plan(plan, expected_visual_plan_sha256="b" * 64)
        invalid = copy.deepcopy(plan)
        invalid["events"][0]["segment_id"] = "unknown"
        invalid["plan_sha256"] = sha256_json({key: value for key, value in invalid.items() if key != "plan_sha256"})
        with self.assertRaises(SemanticEventError):
            validate_semantic_event_plan(invalid, visual_plan=visual_plan_fixture())

    def test_event_ids_bind_to_brief_events_and_frame_scope(self) -> None:
        plan_visual = {"visual_plan_sha256": "a" * 64, "segments": [{"segment_id": "seg-01"}]}
        plan = build_semantic_event_plan(
            visual_plan_sha256="a" * 64,
            transcript_identity="transcript-v1",
            visual_plan=plan_visual,
            events=[{
                "event_id": "moment-problem-01",
                "kind": "moment",
                "segment_id": "seg-01",
                "span_id": "span-01",
                "word_range": [0, 2],
                "start_frame": 8,
                "end_frame": 24,
                "semantic_role": "problem",
                "trigger": "semantic_boundary",
                "channels": {"visual": ["impact-open-title"], "caption": {}, "audio": ["impact-hit"], "spatial": {}, "transition": {}},
            }],
        )
        bundle = {
            "briefs": [{
                "brief": {
                    "execution_target": {"kind": "component", "segment_id": "seg-01", "component_id": "title"},
                    "frame_scope": {"span_start_frame": 0, "span_end_frame": 48},
                    "events": [{"anchor_id": "moment-problem-01", "type": "text", "frame": 12}],
                }
            }]
        }
        manifest = build_event_binding_manifest(
            plan,
            bundle,
            span_id="span-01",
            span_start_frame=0,
            span_end_frame=48,
            span_segment_ids={"seg-01"},
            visual_plan=plan_visual,
        )
        self.assertEqual(validate_event_binding_manifest(manifest), manifest)
        invalid = copy.deepcopy(bundle)
        invalid["briefs"][0]["brief"]["events"][0]["anchor_id"] = "unknown"
        with self.assertRaises(EventBindingError):
            build_event_binding_manifest(plan, invalid, span_id="span-01", span_start_frame=0, span_end_frame=48, span_segment_ids={"seg-01"}, visual_plan=plan_visual)

    def test_visual_span_loader_keeps_legacy_jobs_optional(self) -> None:
        visual_plan = visual_plan_fixture()
        with tempfile.TemporaryDirectory() as directory:
            job_dir = Path(directory)
            legacy = SimpleNamespace(
                job_dir=job_dir,
                stages={"visual_direction": {"status": "approved", "artifacts": []}},
            )
            self.assertIsNone(_optional_semantic_event_plan(legacy, visual_plan))
            event_plan = event_plan_fixture()
            checked_plan = {
                **visual_plan,
                "visual_plan_sha256": event_plan["visual_plan_sha256"],
            }
            path = job_dir / "07-visual-direction/semantic-events.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(canonical_json_bytes(event_plan))
            legacy.stages["visual_direction"]["artifacts"] = [{
                "path": "07-visual-direction/semantic-events.json",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }]
            self.assertEqual(_optional_semantic_event_plan(legacy, checked_plan), event_plan)


class VariantMatrixTests(unittest.TestCase):
    def test_build_and_validate_candidate_matrix(self) -> None:
        matrix = build_variant_matrix(
            job_revision="rev-01",
            targets=[{"target_id": "final-video", "candidates": {"visual": "cand-visual-01"}}],
            candidates=[candidate()],
        )
        self.assertEqual(validate_variant_matrix(matrix, expected_job_revision="rev-01"), matrix)

    def test_candidate_reference_must_be_declared(self) -> None:
        matrix = build_variant_matrix(
            job_revision="rev-01",
            targets=[{"target_id": "final-video", "candidates": {"visual": "cand-visual-01"}}],
            candidates=[candidate()],
        )
        invalid = copy.deepcopy(matrix)
        invalid["targets"][0]["candidates"]["visual"] = "cand-other"
        invalid["manifest_sha256"] = sha256_json({key: value for key, value in invalid.items() if key != "manifest_sha256"})
        with self.assertRaises(VariantMatrixError):
            validate_variant_matrix(invalid)


class RegionTimelineTests(unittest.TestCase):
    def test_event_box_moves_away_from_active_presenter(self) -> None:
        timeline = build_region_timeline(
            visual_plan_sha256="a" * 64,
            regions=[{
                "region_id": "presenter-1",
                "role": "presenter",
                "start_frame": 0,
                "end_frame": 48,
                "rect": {"x": 0, "y": 1200, "width": 1080, "height": 720},
                "event_id": None,
            }],
        )
        result = resolve_event_box(
            timeline,
            event_id="title-1",
            start_frame=12,
            end_frame=36,
            requested={"x": 0, "y": 1300, "width": 600, "height": 240},
        )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["rect"]["y"], 80)

    def test_unavoidable_overlap_enters_manual_review(self) -> None:
        timeline = build_region_timeline(
            visual_plan_sha256="b" * 64,
            regions=[{
                "region_id": "presenter-1",
                "role": "presenter",
                "start_frame": 0,
                "end_frame": 48,
                "rect": {"x": 0, "y": 0, "width": 1080, "height": 1920},
                "event_id": None,
            }],
        )
        result = resolve_event_box(
            timeline,
            event_id="title-1",
            start_frame=12,
            end_frame=36,
            requested={"x": 100, "y": 100, "width": 400, "height": 200},
        )
        self.assertEqual(result["status"], "manual_review")
        with self.assertRaises(RegionTimelineError):
            validate_region_timeline({**timeline, "timeline_sha256": "c" * 64})


class EventAudioPlanTests(unittest.TestCase):
    def test_event_audio_plan_rejects_sources_outside_trusted_root(self) -> None:
        event_plan = event_plan_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = (parent / "trusted").resolve()
            root.mkdir()
            asset = root / "safe.mp3"
            asset.write_bytes(b"safe fixture")
            unsigned = {
                "schema_version": "event-audio-plan/v1",
                "job_id": "job-01",
                "fps": 24,
                "total_frames": 48,
                "semantic_event_plan_sha256": event_plan["plan_sha256"],
                "cues": [{
                    "cue_id": "impact-hit",
                    "event_id": "moment-problem-01",
                    "start_frame": 4,
                    "end_frame": 16,
                    "asset_key": "safe",
                    "path": str(asset),
                    "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                    "volume": 0.2,
                }],
            }
            plan = {**unsigned, "plan_sha256": sha256_json(unsigned)}
            event_audio.validate_plan(
                plan,
                event_plan,
                job_id="job-01",
                total_frames=48,
                allowed_roots=(root,),
            )

            outside = copy.deepcopy(plan)
            outside_asset = (parent / "outside.mp3").resolve()
            outside_asset.write_bytes(b"outside fixture")
            outside["cues"][0]["path"] = str(outside_asset)
            outside["cues"][0]["sha256"] = hashlib.sha256(outside_asset.read_bytes()).hexdigest()
            outside["plan_sha256"] = sha256_json({k: v for k, v in outside.items() if k != "plan_sha256"})
            with self.assertRaises(event_audio.EventAudioError):
                event_audio.validate_plan(
                    outside,
                    event_plan,
                    job_id="job-01",
                    total_frames=48,
                    allowed_roots=(root,),
                )


class CardCapabilityTests(unittest.TestCase):
    def test_verified_capability_can_authorize_event(self) -> None:
        unsigned = {
            "schema_version": "talkcraft-card-event-capabilities/v1",
            "registry_version": "registry-v1",
            "registry_sha256": "a" * 64,
            "cards": [{
                "card_id": "impact-open-title",
                "status": "verified",
                "event_kinds": ["moment"],
                "output_roles": ["visual", "audio"],
                "required_media": [],
                "requires_presenter": False,
                "min_frames": 12,
                "max_frames": 120,
                "notes": "Verified against the portrait qualification case.",
            }],
        }
        index = {**unsigned, "index_sha256": sha256_json(unsigned)}
        checked = validate_card_event_capabilities(index, qualified_card_ids=["impact-open-title"])
        self.assertTrue(can_card_consume_event(checked["cards"][0], event_kind="moment", output_role="visual", frame_count=24))
        self.assertFalse(can_card_consume_event(checked["cards"][0], event_kind="selection", output_role="visual", frame_count=24))
        self.assertFalse(can_card_consume_event(checked["cards"][0], event_kind="bad", output_role="visual", available_media=None))
        self.assertFalse(can_card_consume_event(checked["cards"][0], event_kind=[], output_role="visual"))
        self.assertFalse(can_card_consume_event(checked["cards"][0], event_kind="moment", output_role="visual", frame_count="x"))

    def test_unknown_capability_is_not_authorized(self) -> None:
        unsigned = {
            "schema_version": "talkcraft-card-event-capabilities/v1",
            "registry_version": "registry-v1",
            "registry_sha256": "a" * 64,
            "cards": [{
                "card_id": "pending-card",
                "status": "unknown",
                "event_kinds": ["moment"],
                "output_roles": ["visual"],
                "required_media": [],
                "requires_presenter": False,
                "min_frames": 12,
                "max_frames": 120,
                "notes": "Needs a production qualification case.",
            }],
        }
        index = {**unsigned, "index_sha256": sha256_json(unsigned)}
        checked = validate_card_event_capabilities(index, qualified_card_ids=["pending-card"])
        self.assertFalse(can_card_consume_event(checked["cards"][0], event_kind="moment", output_role="visual", frame_count=24))
        invalid = copy.deepcopy(index)
        invalid["cards"][0]["status"] = "verified"
        with self.assertRaises(CardEventCapabilityError):
            validate_card_event_capabilities(invalid, qualified_card_ids=["pending-card"])

    def test_matcher_rejects_capability_when_required_media_is_missing(self) -> None:
        with self.assertRaises(TalkCraftMatchError):
            match_cards(
                "我们按时间看看每一步发生了什么",
                semantic_family="timeline",
                keywords=["时间线"],
                information_units=3,
                target_role="scene",
                available_media=["image"],
                event_kind="segment",
                output_role="visual",
                frame_count=120,
                capability_index_path=DEFAULT_EVENT_CAPABILITIES,
            )

    def test_generated_capabilities_bind_to_real_qualification_cases(self) -> None:
        index_path = DEFAULT_EVENT_CAPABILITIES
        index = json.loads(index_path.read_text(encoding="utf-8"))
        cards = {card["card_id"]: card for card in index["cards"]}
        self.assertEqual(len(cards), 108)
        self.assertTrue(all(card["status"] == "verified" for card in cards.values()))
        self.assertIn("audio", cards["subscribe-cta"]["output_roles"])
        self.assertIn("presenter", cards["shape-wipe-transition"]["required_media"])
        self.assertTrue(cards["shape-wipe-transition"]["requires_presenter"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from edit.hd.tests.test_talkcraft_contract import brief
from edit.hd.tests.test_visual_plan import valid_plan
from edit.hd.tools import contract_artifacts, render_span, talkcraft_contract, visual_plan


def v4_plan(card_id: str | None = None) -> dict[str, object]:
    plan = valid_plan(("code_generated",) if card_id else ("external_stock",))
    plan["schema_version"] = 4
    targets = []
    if card_id is not None:
        source = plan["segments"][0]["bindings"]["component-1"]
        source.update(
            dependency_id=talkcraft_contract.DEPENDENCY_ID,
            entrypoint="edit/hd/integrations/talkcraft/runtime/render.mjs",
            producer_version="1.0.0",
            primary_renderer=talkcraft_contract.PRIMARY_RENDERER,
            renderer_version="1.0.0",
            template_id=f"hd-talking-head/talkcraft/{card_id}",
            template_version="1.0.0",
        )
        source["invocation_record"] = {
            "argv": [
                "node",
                "edit/hd/integrations/talkcraft/runtime/render.mjs",
            ],
            "exit_code": None,
            "status": "planned",
            "template_request": {
                "semantic_family": "explanation",
                "information_units": 3,
                "numeric_values": [],
                "numeric_scale": "not_applicable",
            },
        }
        plan["segments"][0]["shot_recipe"]["components"][0].update(copy.deepcopy(source))
        targets.append({
            "kind": "component",
            "segment_id": "seg-001",
            "component_id": "component-1",
            "card_id": card_id,
            "start_frame": 0,
            "end_frame": 72,
        })
    chunk = {"chunk_id": "chunk-001", "start_frame": 0, "end_frame": 72, "execution_targets": targets}
    chunk["spec_sha256"] = render_span.chunk_spec_sha256("span-001", chunk)
    plan["render_spans"] = [{
        "span_id": "span-001",
        "mode": "isolated",
        "segment_ids": ["seg-001"],
        "start_frame": 0,
        "end_frame": 72,
        "scene_brief_sha256": "e" * 64,
        "boundaries": [],
        "chunks": [chunk],
    }]
    unsigned = {key: value for key, value in plan.items() if key != "visual_plan_sha256"}
    plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
    return plan


class RenderSpanContractTests(unittest.TestCase):
    def test_v3_behavior_remains_and_v4_is_accepted(self) -> None:
        self.assertEqual(visual_plan.validate_visual_plan(valid_plan())["schema_version"], 3)
        self.assertEqual(visual_plan.validate_visual_plan(v4_plan()), v4_plan())

    def test_span_request_binds_approved_chunk_identity(self) -> None:
        plan = visual_plan.validate_visual_plan(v4_plan())
        span, chunk = render_span.select_span_chunk(
            render_span.SpanExecutionRequest(plan, "span-001", "chunk-001")
        )
        self.assertEqual(span["span_id"], "span-001")
        self.assertEqual(chunk["start_frame"], 0)

    def test_rejects_overlap_gap_oversize_and_stale_identity(self) -> None:
        mutators = (
            lambda plan: plan["render_spans"][0].update(start_frame=1),
            lambda plan: plan["render_spans"][0]["chunks"][0].update(end_frame=721),
            lambda plan: plan["render_spans"][0]["chunks"][0].update(spec_sha256="f" * 64),
        )
        for mutate in mutators:
            plan = v4_plan()
            mutate(plan)
            unsigned = {key: value for key, value in plan.items() if key != "visual_plan_sha256"}
            plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
            with self.subTest(mutate=mutate), self.assertRaises(visual_plan.VisualPlanError):
                visual_plan.validate_visual_plan(plan)

    def test_request_rejects_non_v4_and_unknown_chunk(self) -> None:
        with self.assertRaises(render_span.RenderSpanError):
            render_span.select_span_chunk(render_span.SpanExecutionRequest(valid_plan(), "span-001", "chunk-001"))
        with self.assertRaises(render_span.RenderSpanError):
            render_span.select_span_chunk(render_span.SpanExecutionRequest(v4_plan(), "span-001", "missing"))

    def test_transition_and_long_world_spans_use_real_chunks(self) -> None:
        segments = [
            {"segment_id": "seg-001", "start": 0.0, "end": 15.0},
            {"segment_id": "seg-002", "start": 15.0, "end": 31.0},
        ]
        transition_card = next(
            card["card_id"]
            for card in talkcraft_contract.load_card_registry()["cards"]
            if card["production"]["production_role"] == "transition"
        )
        chunks = [
            {"chunk_id": "chunk-001", "start_frame": 0, "end_frame": 720, "execution_targets": [{
                "kind": "boundary", "boundary_id": "edge-001",
                "card_slot_id": "edge-001-card-001", "card_id": transition_card,
                "start_frame": 352, "end_frame": 368,
            }]},
            {"chunk_id": "chunk-002", "start_frame": 720, "end_frame": 744, "execution_targets": []},
        ]
        for chunk in chunks:
            chunk["spec_sha256"] = render_span.chunk_spec_sha256("span-001", chunk)
        transition = [{
            "span_id": "span-001",
            "mode": "transition_chain",
            "segment_ids": ["seg-001", "seg-002"],
            "start_frame": 0,
            "end_frame": 744,
            "scene_brief_sha256": "a" * 64,
            "boundaries": [{
                "boundary_id": "edge-001",
                "card_slot_id": "edge-001-card-001",
                "from_segment_id": "seg-001",
                "to_segment_id": "seg-002",
                "card_id": transition_card,
                "start_frame": 352,
                "end_frame": 368,
            }],
            "chunks": chunks,
        }]
        self.assertEqual(
            render_span.validate_render_spans(transition, segments=segments, duration_frames=744),
            transition,
        )
        world = copy.deepcopy(transition)
        world[0]["mode"] = "world"
        world[0]["boundaries"] = []
        world[0]["chunks"][0]["execution_targets"] = []
        for world_chunk in world[0]["chunks"]:
            world_chunk["spec_sha256"] = render_span.chunk_spec_sha256(
                "span-001", world_chunk
            )
        self.assertEqual(
            render_span.validate_render_spans(world, segments=segments, duration_frames=744),
            world,
        )

    def test_transition_rejects_non_transition_card(self) -> None:
        segments = [
            {"segment_id": "seg-001", "start": 0.0, "end": 1.0},
            {"segment_id": "seg-002", "start": 1.0, "end": 2.0},
        ]
        chunk = {"chunk_id": "chunk-001", "start_frame": 0, "end_frame": 48, "execution_targets": []}
        chunk["spec_sha256"] = render_span.chunk_spec_sha256("span-001", chunk)
        spans = [{
            "span_id": "span-001", "mode": "transition_chain",
            "segment_ids": ["seg-001", "seg-002"], "start_frame": 0, "end_frame": 48,
            "scene_brief_sha256": "a" * 64,
            "boundaries": [{"boundary_id": "edge-001", "card_slot_id": "edge-001-card-001", "from_segment_id": "seg-001", "to_segment_id": "seg-002", "card_id": "alt-block-lines", "start_frame": 20, "end_frame": 28}],
            "chunks": [chunk],
        }]
        with self.assertRaisesRegex(render_span.RenderSpanError, "transition card"):
            render_span.validate_render_spans(spans, segments=segments, duration_frames=48)

    def test_transition_crossing_chunk_boundary_is_bound_in_both_chunks(self) -> None:
        segments = [
            {"segment_id": "seg-001", "start": 0.0, "end": 1.0},
            {"segment_id": "seg-002", "start": 1.0, "end": 2.0},
        ]
        card_id = next(
            card["card_id"]
            for card in talkcraft_contract.load_card_registry()["cards"]
            if card["production"]["production_role"] == "transition"
        )
        target = {
            "kind": "boundary", "boundary_id": "edge-001",
            "card_slot_id": "edge-001-card-001", "card_id": card_id,
            "start_frame": 20, "end_frame": 28,
        }
        chunks = [
            {"chunk_id": "chunk-001", "start_frame": 0, "end_frame": 24,
             "execution_targets": [copy.deepcopy(target)]},
            {"chunk_id": "chunk-002", "start_frame": 24, "end_frame": 48,
             "execution_targets": [copy.deepcopy(target)]},
        ]
        for chunk in chunks:
            chunk["spec_sha256"] = render_span.chunk_spec_sha256("span-001", chunk)
        spans = [{
            "span_id": "span-001", "mode": "transition_chain",
            "segment_ids": ["seg-001", "seg-002"],
            "start_frame": 0, "end_frame": 48,
            "scene_brief_sha256": "a" * 64,
            "boundaries": [{
                "boundary_id": "edge-001", "card_slot_id": "edge-001-card-001",
                "from_segment_id": "seg-001", "to_segment_id": "seg-002",
                "card_id": card_id, "start_frame": 20, "end_frame": 28,
            }],
            "chunks": chunks,
        }]
        self.assertEqual(
            render_span.validate_render_spans(
                spans, segments=segments, duration_frames=48
            ),
            spans,
        )

    def test_transition_window_cannot_cross_two_member_edges(self) -> None:
        segments = [
            {"segment_id": "seg-001", "start": 0.0, "end": 1.0},
            {"segment_id": "seg-002", "start": 1.0, "end": 2.0},
            {"segment_id": "seg-003", "start": 2.0, "end": 3.0},
        ]
        transition_card = next(
            card["card_id"]
            for card in talkcraft_contract.load_card_registry()["cards"]
            if card["production"]["production_role"] == "transition"
        )
        chunk = {"chunk_id": "chunk-001", "start_frame": 0, "end_frame": 72, "execution_targets": []}
        chunk["spec_sha256"] = render_span.chunk_spec_sha256("span-001", chunk)
        spans = [{
            "span_id": "span-001", "mode": "transition_chain",
            "segment_ids": ["seg-001", "seg-002", "seg-003"],
            "start_frame": 0, "end_frame": 72,
            "scene_brief_sha256": "a" * 64,
            "boundaries": [
                {"boundary_id": "edge-001", "card_slot_id": "edge-001-card-001", "from_segment_id": "seg-001", "to_segment_id": "seg-002", "card_id": transition_card, "start_frame": 20, "end_frame": 52},
                {"boundary_id": "edge-002", "card_slot_id": "edge-002-card-001", "from_segment_id": "seg-002", "to_segment_id": "seg-003", "card_id": transition_card, "start_frame": 44, "end_frame": 52},
            ],
            "chunks": [chunk],
        }]
        with self.assertRaisesRegex(render_span.RenderSpanError, "exactly one"):
            render_span.validate_render_spans(spans, segments=segments, duration_frames=72)

    def test_rendered_chunk_replay_binds_files_probe_brief_and_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path = root / "registry.json"
            registry = json.loads(
                talkcraft_contract.DEFAULT_CARD_REGISTRY.read_text(encoding="utf-8")
            )
            production = registry["cards"][0]["production"]
            production.update(
                status="qualified",
                derived_entrypoint="edit/hd/integrations/talkcraft/runtime/render.mjs",
                implementation_sha256="b" * 64,
                adapter_version="1.0.0",
                qualification_id="c" * 64,
            )
            registry["cards"][1]["production"].update(
                status="pending_portrait_adapter",
                derived_entrypoint=None,
                implementation_sha256=None,
                input_adapter_sha256=None,
                adapter_version=None,
                qualification_id=None,
            )
            registry["qualification_policy"].update(
                state="partially_qualified", production_enabled=True
            )
            contract_artifacts.write_json_artifact(registry_path, registry)

            production_brief = brief()
            production_brief["registry"] = {
                "version": registry["registry_version"],
                "sha256": contract_artifacts.sha256_file(registry_path),
            }
            production_brief["render"].update(
                entrypoint="edit/hd/integrations/talkcraft/runtime/render.mjs",
                implementation_sha256="b" * 64,
                adapter_version="1.0.0",
                qualification_id="c" * 64,
            )
            plan = visual_plan.validate_visual_plan(
                v4_plan(production_brief["card_id"])
            )
            request = render_span.SpanExecutionRequest(
                plan, "span-001", "chunk-001"
            )
            production_brief["owner"].update(
                visual_plan_sha256=plan["visual_plan_sha256"],
                spec_sha256=plan["render_spans"][0]["chunks"][0]["spec_sha256"],
                scene_brief_sha256=plan["render_spans"][0]["scene_brief_sha256"],
            )
            brief_entry = {
                "brief": production_brief,
                "brief_sha256": contract_artifacts.sha256_json(production_brief),
            }
            unsigned_bundle = {
                "schema_version": "talkcraft-brief-bundle/v1",
                "owner": copy.deepcopy(production_brief["owner"]),
                "briefs": [brief_entry],
            }
            brief_bundle = {
                **unsigned_bundle,
                "bundle_sha256": contract_artifacts.sha256_json(unsigned_bundle),
            }

            job = root / "job"
            video = job / "08-visual-canary/spans/span-001/chunk-001.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"final-span-video")
            component_path = video.parent / "component.mov"
            component_path.write_bytes(b"talkcraft-component")
            component_relative = component_path.relative_to(job).as_posix()
            component_sha256 = hashlib.sha256(component_path.read_bytes()).hexdigest()
            component_artifact = {
                "schema_version": 1,
                "status": "success",
                "job_id": "job-001",
                "segment_id": "seg-001",
                "component_id": "component-1",
                "kind": "code_generated",
                "strategy_revision": 1,
                "media_type": "video",
                "render_window": {
                    "start_frame": 0,
                    "end_frame": 72,
                    "z_index": 1,
                    "layout_slot": "main",
                    "opacity": 1.0,
                    "safe_zone": {"top": 120, "bottom": 360, "left": 48, "right": 48},
                },
                "z_index": 1,
                "layout_slot": "main",
                "opacity": 1.0,
                "safe_zone": {"top": 120, "bottom": 360, "left": 48, "right": 48},
                "artifact_contract": {
                    "width": 1080, "height": 1920, "fps": 24, "alpha": True
                },
                "source_media_type": "animation",
                "artifact_media_type": "video",
                "media_probe": {
                    "container": "mov", "codec": "prores_ks", "pixel_format": "yuva444p10le",
                    "width": 1080, "height": 1920, "fps": 24,
                    "frame_count": 72, "duration": 3.0,
                },
                "input_sha256": "a" * 64,
                "job_path": component_relative,
                "byte_count": component_path.stat().st_size,
                "output_sha256": component_sha256,
                "invocation_evidence": {
                    "span_id": "span-001",
                    "chunk_id": "chunk-001",
                    "spec_sha256": plan["render_spans"][0]["chunks"][0]["spec_sha256"],
                    "production_brief_sha256": contract_artifacts.sha256_json(production_brief),
                    "production_brief_bundle_sha256": brief_bundle["bundle_sha256"],
                    "output_job_path": component_relative,
                    "output_sha256": component_sha256,
                },
                "qa": {"passed": True, "checks": ["fixture"]},
                "error_code": None,
            }
            keyframes = {}
            for name, frame in (("entry", 1), ("hold", 36), ("exit", 70)):
                path = video.parent / f"{name}.png"
                path.write_bytes(name.encode("utf-8"))
                keyframes[name] = {
                    "job_path": path.relative_to(job).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                    "frame": frame,
                }
            value = {
                "schema_version": "rendered-span-chunk/v1",
                "visual_plan_sha256": plan["visual_plan_sha256"],
                "span_id": "span-001",
                "chunk_id": "chunk-001",
                "spec_sha256": plan["render_spans"][0]["chunks"][0]["spec_sha256"],
                "scene_brief_sha256": plan["render_spans"][0]["scene_brief_sha256"],
                "production_brief_bundle_sha256": brief_bundle["bundle_sha256"],
                "video": {
                    "job_path": video.relative_to(job).as_posix(),
                    "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                    "bytes": video.stat().st_size,
                },
                "frames": 72,
                "component_artifacts": [{
                    "component_id": "component-1",
                    "execution_target": {
                        "kind": "component",
                        "segment_id": "seg-001",
                        "component_id": "component-1",
                    },
                    "artifact": component_artifact,
                }],
                "output_probe": {
                    "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
                    "width": 1080, "height": 1920, "fps": 24, "frame_count": 72,
                    "duration": 3.0, "audio_streams": 0,
                },
                "keyframes": keyframes,
                "renderer": {
                    "dependency_id": talkcraft_contract.DEPENDENCY_ID,
                    "primary_renderer": talkcraft_contract.PRIMARY_RENDERER,
                    "adapter_id": "talkcraft-reference-v1",
                    "adapter_version": "1.0.0",
                    "entrypoint": "edit/hd/integrations/talkcraft/runtime/render.mjs",
                    "implementation_sha256": "b" * 64,
                },
            }
            value["render_identity"] = contract_artifacts.sha256_json(value)
            self.assertEqual(
                render_span.validate_rendered_span_chunk(
                    value,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                ),
                value,
            )
            legacy_field = copy.deepcopy(value)
            legacy_field["production_brief_sha256"] = legacy_field.pop(
                "production_brief_bundle_sha256"
            )
            with self.assertRaisesRegex(render_span.RenderSpanError, "fields"):
                render_span.validate_rendered_span_chunk(
                    legacy_field,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )
            invalid_probe = copy.deepcopy(value)
            invalid_probe["output_probe"]["audio_streams"] = False
            unsigned = {
                key: item
                for key, item in invalid_probe.items()
                if key != "render_identity"
            }
            invalid_probe["render_identity"] = contract_artifacts.sha256_json(unsigned)
            with self.assertRaisesRegex(render_span.RenderSpanError, "output probe"):
                render_span.validate_rendered_span_chunk(
                    invalid_probe,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )
            missing_components = copy.deepcopy(value)
            missing_components["component_artifacts"] = []
            unsigned = {
                key: item
                for key, item in missing_components.items()
                if key != "render_identity"
            }
            missing_components["render_identity"] = contract_artifacts.sha256_json(unsigned)
            with self.assertRaisesRegex(render_span.RenderSpanError, "non-empty"):
                render_span.validate_rendered_span_chunk(
                    missing_components,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )
            wrong_chunk_artifact = copy.deepcopy(value)
            wrong_chunk_artifact["component_artifacts"][0]["artifact"][
                "invocation_evidence"
            ]["chunk_id"] = "chunk-previous"
            unsigned = {
                key: item
                for key, item in wrong_chunk_artifact.items()
                if key != "render_identity"
            }
            wrong_chunk_artifact["render_identity"] = contract_artifacts.sha256_json(unsigned)
            with self.assertRaisesRegex(render_span.RenderSpanError, "ComponentArtifact"):
                render_span.validate_rendered_span_chunk(
                    wrong_chunk_artifact,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )
            component_path.write_bytes(b"changed-component")
            with self.assertRaisesRegex(render_span.RenderSpanError, "bytes changed"):
                render_span.validate_rendered_span_chunk(
                    value,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )
            component_path.write_bytes(b"talkcraft-component")
            video.write_bytes(b"changed")
            with self.assertRaisesRegex(render_span.RenderSpanError, "bytes changed"):
                render_span.validate_rendered_span_chunk(
                    value,
                    request,
                    brief_bundle,
                    job_dir=job,
                    registry_path=registry_path,
                )


if __name__ == "__main__":
    unittest.main()

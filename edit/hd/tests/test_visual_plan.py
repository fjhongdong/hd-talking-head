"""Contract tests for visual-plan schema v3."""

from __future__ import annotations

import copy
import inspect
import unittest
from unittest import mock

from edit.hd.tools import contract_artifacts, visual_plan
from edit.hd.tools.visual_plan import VisualPlanError, parse_visual_brief_json, validate_visual_plan
from edit.hd.tests.test_avatar_contract import avatar_fixture


SOURCE_KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)


def visual_intent(segment_id: str = "seg-001") -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "statement": "Explain the approved idea with semantically matched visuals.",
        "semantic_goals": ["explain"],
        "claims": [{"type": "concept", "value": "One approved visual explains the idea.", "verification_required": False}],
        "entities": [],
        "relations": [],
        "requirements": {
            "verifiability": "medium",
            "realism": "medium",
            "abstraction": "medium",
            "product_specificity": "low",
            "emotional_intensity": "low",
        },
        "presenter_presence": "allowed",
    }


def strategy_component(component_id: str, kind: str) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": "base",
        "media_type": "animation" if kind == "code_generated" else "image",
        "layout_slot": "main",
        "brief": f"Explain the idea with the approved {kind} component.",
    }


def visual_strategy(kinds: tuple[str, ...] = ("external_stock",), *, segment_id: str = "seg-001") -> dict[str, object]:
    components = [strategy_component(f"component-{index + 1}", kind) for index, kind in enumerate(kinds)]
    for component in components[1:]:
        component["layer_role"] = "annotation"
        component["layout_slot"] = "annotation"
    mode = "none" if not components else "single" if len(components) == 1 else "hybrid"
    base_ids = [component["component_id"] for component in components if component["layer_role"] == "base"]
    return {
        "schema_version": 1,
        "segment_id": segment_id,
        "mode": mode,
        "rationale": "The approved composition explains the intended meaning.",
        "components": components,
        "composition": {
            "family": "no_broll" if mode == "none" else "single_full_frame" if mode == "single" else "evidence_with_data_overlay",
            "presenter_mode": "full_frame" if mode == "none" else "bottom_window",
            **({"avatar": avatar_fixture(frames=72)} if mode != "none" else {}),
            "reading_order": [item["component_id"] for item in components],
            "component_dependencies": [
                {"component_id": item["component_id"], "depends_on": base_ids[:1]}
                for item in components
                if item["layer_role"] == "annotation"
            ],
        },
    }


def binding(kind: str, asset_id: str) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "local_material": {"material_id": asset_id, "job_path": f"00-user-provided/{asset_id}.png", "sha256": "1" * 64},
        "official_material": {
            "source_id": asset_id,
            "publisher": "Example Institute",
            "source_url": "https://example.org/report",
            "snapshot_path": f"00-user-provided/{asset_id}.pdf",
            "fetched_at": "2026-08-31T12:00:00+08:00",
            "sha256": "2" * 64,
        },
        "external_stock": {
            "provider": "Example Stock",
            "provider_asset_id": asset_id,
            "author": "Example Author",
            "asset_page": f"https://stock.example/assets/{asset_id}",
            "job_path": f"stock/{asset_id}.mp4",
            "license_snapshot": f"licenses/{asset_id}.html",
            "downloaded_at": "2026-08-31T12:00:00+08:00",
            "sha256": "3" * 64,
        },
        "code_generated": {
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "packages/adapter-hyperframes/src/render.ts",
            "producer_version": "0123456789abcdef0123456789abcdef01234567",
            "brief_sha256": "4" * 64,
            "invocation_record": {
                "argv": ["node", "packages/adapter-hyperframes/src/render.ts"], "exit_code": 0,
                "template_request": {"semantic_family": "explanation", "information_units": 3,
                                     "numeric_values": [], "numeric_scale": "not_applicable"},
            },
            "primary_renderer": "HyperFrames",
            "renderer_version": "renderer-v1",
            "template_origin": "custom_fallback",
            "template_id": "fixture-code-template",
            "template_version": "fixture-version",
            "verification_id": "7" * 64,
            "adaptation_level": "structural",
            "source_entrypoint": "templates/fixture-code-template/index.html",
            "source_sha256": "8" * 64,
            "sample_sha256": "9" * 64,
            "semantic_families": ["explanation"],
            "capacity": {"min_units": 1, "max_units": 8},
        },
        "ai_generated": {
            "provider": "xAI",
            "model": "grok-imagine-video",
            "endpoint_id": "video-generation",
            "prompt_sha256": "5" * 64,
            "generation_id": asset_id,
            "sha256": "6" * 64,
        },
    }
    return copy.deepcopy(values[kind])


def recipe(kinds: tuple[str, ...] = ("external_stock",), *, segment_id: str = "seg-001") -> dict[str, object]:
    components = []
    for index, kind in enumerate(kinds):
        component_id = f"component-{index + 1}"
        components.append({
            "component_id": component_id,
            "kind": kind,
            "semantic_role": "explanation",
            "layer_role": "base" if index == 0 else "annotation",
            "executor": "test-executor",
            "media_type": "animation" if kind == "code_generated" else "image",
            "render_window": {
                "start_frame": 0,
                "end_frame": 72,
                "z_index": index * 10,
                "layout_slot": "main" if index == 0 else "annotation",
                "opacity": 1.0,
                "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
            },
            "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": kind == "code_generated"},
            **binding(kind, f"asset-{index + 1}"),
        })
    mode = "none" if not components else "single" if len(components) == 1 else "hybrid"
    base_ids = [component["component_id"] for component in components if component["layer_role"] == "base"]
    return {
        "schema_version": 2,
        "segment_id": segment_id,
        "strategy_revision": 1,
        "mode": mode,
        "composition": {
            "family": "no_broll" if mode == "none" else "single_full_frame" if mode == "single" else "evidence_with_data_overlay",
            "presenter_mode": "full_frame" if mode == "none" else "bottom_window",
            **({"avatar": avatar_fixture(frames=72)} if mode != "none" else {}),
            "reading_order": [item["component_id"] for item in components],
            "component_dependencies": [
                {"component_id": item["component_id"], "depends_on": base_ids[:1]}
                for item in components
                if item["layer_role"] == "annotation"
            ],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }


def valid_plan(kinds: tuple[str, ...] = ("external_stock",)) -> dict[str, object]:
    summary: dict[str, int] = {}
    for kind in kinds:
        summary[kind] = summary.get(kind, 0) + 1
    candidates = {
        f"component-{index + 1}": [{
            "asset_id": f"asset-{index + 1}",
            "kind": kind,
            "semantic_match_score": 0.9,
            "quality_score": 0.8,
            "hard_gates": {
                "semantic_match": True,
                "factual_reliability": True,
                "native_vertical": True,
                "quality_readability": True,
            },
        }]
        for index, kind in enumerate(kinds)
        if kind in {"local_material", "official_material", "external_stock"}
    }
    plan = {
        "schema_version": 3,
        "content_analysis_sha256": "a" * 64,
        "edit_plan_sha256": "b" * 64,
        "timeline_map_sha256": "c" * 64,
        "edited_aroll_sha256": "d" * 64,
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "duration": 3.0,
        "segments": [{
            "segment_id": "seg-001",
            "start": 0.0,
            "end": 3.0,
            "content_item_ids": ["idea-01"],
            "visible_text": [],
            "visual_intent": visual_intent(),
            "visual_strategy": visual_strategy(kinds),
            "candidate_snapshots": candidates,
            "bindings": {f"component-{index + 1}": binding(kind, f"asset-{index + 1}") for index, kind in enumerate(kinds)},
            "shot_recipe": recipe(kinds),
        }],
        "source_summary": summary,
    }
    return {
        **plan,
        "visual_plan_sha256": contract_artifacts.sha256_json(plan),
    }


def replace_segment_id(plan: dict[str, object], value: str) -> None:
    segment = plan["segments"][0]
    segment["segment_id"] = value
    segment["visual_intent"]["segment_id"] = value
    segment["visual_strategy"]["segment_id"] = value
    segment["shot_recipe"]["segment_id"] = value


def replace_component_id(plan: dict[str, object], value: str) -> None:
    segment = plan["segments"][0]
    old = segment["visual_strategy"]["components"][0]["component_id"]
    segment["visual_strategy"]["components"][0]["component_id"] = value
    segment["visual_strategy"]["composition"]["reading_order"][0] = value
    segment["shot_recipe"]["components"][0]["component_id"] = value
    segment["candidate_snapshots"][value] = segment["candidate_snapshots"].pop(old)
    segment["bindings"][value] = segment["bindings"].pop(old)


class VisualPlanSchemaV3Tests(unittest.TestCase):
    def test_review_text_builds_one_sorted_table_from_plan_and_checks(self):
        def seg(sid, start, kind, source, layer):
            return {"segment_id": sid, "start": start, "end": start + 1.0,
                    "visual_strategy": {"mode": "none", "components": [{"component_id": "c", "kind": kind, "layer_role": layer}]},
                    "visual_intent": {"statement": sid + " semantic"},
                    "bindings": {"c": {"template_id" if kind == "code_generated" else "source_id": source}}}
        plan = {"source_summary": {}, "content_analysis_sha256": "x",
                "segments": [seg("b", 2.0, "code_generated", "real-broll", "base"),
                             seg("a", 1.0, "code_generated", "real-overlay", "annotation"),
                             seg("c", 3.0, "official_material", "official-source-1", "base")]}
        selection = {"assignments": [{"segment_id": "b", "component_id": "c", "template_id": "fake-query"}],
                     "motion_queries": [{"segment_id": "b", "component_id": "c", "tags": ["b"]},
                                        {"segment_id": "a", "component_id": "c", "tags": ["a"],
                                         "matched_template": "fake-query", "start": 999}],
                     "motion_review": {"checks": [{"segment_id": "b", "component_id": "c", "selected": "checked-b"},
                                                    {"segment_id": "a", "component_id": "c", "selected": "checked-a"}],
                                       "spoken_segments": {"c": "引用实际现场"}}}
        text = visual_plan._review_text(plan, skill_selection=selection)
        self.assertLess(text.index("1.000–2.000s"), text.index("2.000–3.000s"))
        self.assertIn("| 贴片 |", text)
        self.assertIn("| B-roll |", text)
        self.assertIn("`real-overlay`", text)
        self.assertIn("`real-broll`", text)
        self.assertIn("`official-source-1`", text)
        self.assertIn("引用实际现场", text)
        table = text.split("## 内部选型与整片协调记录", 1)[0]
        self.assertNotIn("fake-query", table)
        self.assertNotIn("999", table)
        self.assertIn("| 1 | 1.000–2.000s |", table)
        frozen = visual_plan._review_text(plan, skill_selection=selection,
                                         numbering={"a:c": 4, "b:c": 7, "c:c": 9})
        self.assertIn("| 4 | 1.000–2.000s |", frozen)
        self.assertIn("| 7 | 2.000–3.000s |", frozen)
    def test_completed_lovart_binding_survives_freeze_and_final_validation(self):
        for width, height in ((720, 1280), (1080, 1920)):
            with self.subTest(width=width):
                segment = valid_plan(("ai_generated",))["segments"][0]
                segment.pop("shot_recipe")
                segment["strategy_revision"] = 1
                segment["visual_strategy"]["components"][0]["media_type"] = "video"
                bound = segment["bindings"]["component-1"]
                bound.update(provider="Lovart", model="kling/kling-video-o1",
                             endpoint_id="mcp__lovart__generate_video",
                             execution_mode="reuse_completed_lovart_video",
                             source_dimensions={"width": width, "height": height})
                original = copy.deepcopy(bound)
                checked = parse_visual_brief_json(contract_artifacts.canonical_json_bytes(
                    {"schema_version": 3, "segments": [segment]}).decode())["segments"][0]
                frozen = visual_plan._freeze_and_compile_segment(
                    checked, candidate_freezers={}, binding_freezers={},
                    strategy_compiler=visual_plan._load_router_module().compile_strategy)
                self.assertEqual(visual_plan._validate_semantic_segment(frozen, draft=False), frozen)
                self.assertEqual(frozen["bindings"]["component-1"], original)
                compiled = frozen["shot_recipe"]["components"][0]
                self.assertEqual(compiled["executor"], "lovart_existing_video")
                self.assertEqual(compiled["artifact_contract"],
                                 {"width": width, "height": height, "fps": 24, "alpha": False})
                self.assertNotIn("execution_mode", compiled)
                self.assertNotIn("source_dimensions", compiled)
                for field, value in (("executor", "other-executor"),
                                     ("artifact_contract", {"width": 720 if width == 1080 else 1080,
                                                            "height": 1280 if height == 1920 else 1920,
                                                            "fps": 24, "alpha": False})):
                    altered = copy.deepcopy(frozen)
                    altered["shot_recipe"]["components"][0][field] = value
                    with self.assertRaises(VisualPlanError):
                        visual_plan._validate_semantic_segment(altered, draft=False)

    def test_completed_lovart_prevalidation_rejects_incomplete_or_injected_binding(self):
        strategy = visual_strategy(("ai_generated",))
        strategy["components"][0]["media_type"] = "video"
        bound = binding("ai_generated", "asset-1")
        bound.update(provider="Lovart", endpoint_id="mcp__lovart__generate_video",
                     execution_mode="reuse_completed_lovart_video",
                     source_dimensions={"width": 1080, "height": 1920})
        for field in ("execution_mode", "source_dimensions", "executor", "artifact_contract"):
            altered = copy.deepcopy(bound)
            if field in {"execution_mode", "source_dimensions"}:
                altered.pop(field)
            else:
                altered[field] = "injected"
            with self.subTest(field=field), self.assertRaises(VisualPlanError):
                visual_plan._prevalidate_draft_bindings(strategy, {"component-1": altered}, 1, 72)

    def test_public_surface_stays_stage_scoped(self) -> None:
        self.assertEqual(visual_plan.__all__, ["VisualPlanError", "parse_visual_brief_json", "validate_visual_plan", "block_visual_direction", "prepare_visual_direction"])

    def test_accepts_none_single_hybrid_and_external_stock(self) -> None:
        for kinds in ((), ("external_stock",), ("official_material", "code_generated")):
            plan = valid_plan(kinds)
            with self.subTest(kinds=kinds):
                checked = validate_visual_plan(plan)
                self.assertEqual(checked, plan)
                self.assertIsNot(checked, plan)

    def test_source_summary_uses_only_actual_component_kinds(self) -> None:
        plan = valid_plan(("official_material", "official_material", "ai_generated"))
        self.assertEqual(validate_visual_plan(plan)["source_summary"], {"official_material": 2, "ai_generated": 1})

    def test_user_provided_verified_official_pdf_keeps_official_kind(self) -> None:
        plan = valid_plan(("official_material",))
        component = plan["segments"][0]["shot_recipe"]["components"][0]
        self.assertTrue(component["snapshot_path"].startswith("00-user-provided/"))
        checked = validate_visual_plan(plan)
        self.assertEqual(checked["segments"][0]["visual_strategy"]["components"][0]["kind"], "official_material")
        self.assertEqual(checked["source_summary"], {"official_material": 1})

    def test_rejects_every_non_v3_plan_with_stable_error(self) -> None:
        for plan in ({"version": 1, "segments": []}, {"schema_version": 2, "segments": []}, {"schema_version": True, "segments": []}, {}, []):
            with self.subTest(plan=plan), self.assertRaisesRegex(VisualPlanError, "^BROLL_SCHEMA_UNSUPPORTED$"):
                validate_visual_plan(plan)

    def test_rejects_removed_single_route_fields(self) -> None:
        for field in ("route", "implementation", "selected_" + "material_id"):
            plan = valid_plan()
            plan["segments"][0][field] = "obsolete"
            with self.subTest(field=field), self.assertRaises(VisualPlanError):
                validate_visual_plan(plan)

    def test_delegates_to_authoritative_contract_validators(self) -> None:
        with mock.patch.object(visual_plan, "validate_visual_intent", wraps=visual_plan.validate_visual_intent) as intent_validator, mock.patch.object(visual_plan, "validate_visual_strategy", wraps=visual_plan.validate_visual_strategy) as strategy_validator, mock.patch.object(visual_plan, "validate_shot_recipe_v2", wraps=visual_plan.validate_shot_recipe_v2) as recipe_validator:
            validate_visual_plan(valid_plan())
        self.assertEqual((intent_validator.call_count, strategy_validator.call_count, recipe_validator.call_count), (1, 1, 1))

    def test_rejects_cross_contract_mismatch_and_wrong_summary(self) -> None:
        mutators = (
            lambda plan: plan["segments"][0]["visual_intent"].update(segment_id="other"),
            lambda plan: plan["segments"][0]["visual_strategy"].update(segment_id="other"),
            lambda plan: plan["segments"][0]["shot_recipe"].update(mode="none"),
            lambda plan: plan.update(source_summary={"local_material": 1}),
        )
        for mutate in mutators:
            plan = valid_plan()
            mutate(plan)
            with self.subTest(mutate=mutate), self.assertRaises(VisualPlanError):
                validate_visual_plan(plan)

    def test_source_summary_rejects_boolean_and_zero_counts(self) -> None:
        for summary in ({"external_stock": True}, {"external_stock": 0}):
            plan = valid_plan()
            plan["source_summary"] = summary
            with self.subTest(summary=summary), self.assertRaises(VisualPlanError):
                validate_visual_plan(plan)

    def test_validation_is_pure_and_deterministic(self) -> None:
        plan = valid_plan(("external_stock", "ai_generated"))
        before = copy.deepcopy(plan)
        first = validate_visual_plan(plan)
        second = validate_visual_plan(plan)
        self.assertEqual(plan, before)
        self.assertEqual(first, second)
        self.assertIsNot(first["segments"], plan["segments"])

    def test_recipe_components_follow_approved_reading_order(self) -> None:
        plan = valid_plan(("official_material", "code_generated"))
        strategy = plan["segments"][0]["visual_strategy"]
        strategy["components"] = list(reversed(strategy["components"]))
        unsigned = {
            key: item for key, item in plan.items() if key != "visual_plan_sha256"
        }
        plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        checked = validate_visual_plan(plan)
        self.assertEqual(
            [
                component["component_id"]
                for component in checked["segments"][0]["shot_recipe"]["components"]
            ],
            strategy["composition"]["reading_order"],
        )

    def test_visual_plan_identity_is_self_verified(self) -> None:
        plan = valid_plan()
        plan["visual_plan_sha256"] = "f" * 64
        with self.assertRaises(VisualPlanError):
            validate_visual_plan(plan)

    def test_identifiers_reject_internal_c0_and_del(self) -> None:
        cases = (
            (replace_segment_id, "segment\ninjected"),
            (replace_component_id, "component\x1bescape"),
            (replace_component_id, "component\x7fdelete"),
        )
        for mutate, value in cases:
            plan = valid_plan()
            mutate(plan, value)
            unsigned = {
                key: item
                for key, item in plan.items()
                if key != "visual_plan_sha256"
            }
            plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
            with self.subTest(value=repr(value)), self.assertRaises(VisualPlanError):
                validate_visual_plan(plan)

    def test_ownership_and_journal_revisions_are_strict_integers(self) -> None:
        manifest = {
            "schema_version": 3,
            "generation_id": "a" * 32,
            "job_id": "job-001",
            "base_revision": 0,
            "published_revision": 1,
            "files": [
                {"path": "visual-plan.json", "sha256": "b" * 64, "bytes": 1},
                {"path": "visual-routing.md", "sha256": "c" * 64, "bytes": 1},
            ],
        }
        for field, value in (
            ("base_revision", True),
            ("base_revision", 0.0),
            ("base_revision", -1),
            ("published_revision", True),
            ("published_revision", 1.0),
            ("published_revision", -1),
            ("published_revision", 2),
        ):
            corrupted = copy.deepcopy(manifest)
            corrupted[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                VisualPlanError
            ):
                visual_plan._validate_manifest(corrupted)

        journal = {
            "schema_version": 3,
            "generation_id": "a" * 32,
            "job_id": "job-001",
            "base_revision": 0,
            "base_workflow_sha256": "d" * 64,
            "new_manifest": manifest,
            "previous_manifest": None,
        }
        for value in (True, 0.0, -1):
            corrupted = copy.deepcopy(journal)
            corrupted["base_revision"] = value
            with self.subTest(journal_base_revision=value), self.assertRaises(
                VisualPlanError
            ):
                visual_plan._validate_journal(corrupted)

    def test_parser_rejects_duplicate_nonfinite_and_old_schema(self) -> None:
        for source in ('{"schema_version":3,"schema_version":3,"segments":[]}', '{"schema_version":3,"segments":[NaN]}', '{"schema_version":2,"segments":[]}'):
            with self.subTest(source=source), self.assertRaises(VisualPlanError):
                parse_visual_brief_json(source)

    def test_module_has_no_old_plan_compatibility_or_execution(self) -> None:
        source = inspect.getsource(visual_plan)
        for forbidden in ("_V2_ROUTES", "selected_" + "material_id", "legacy visual", "schema_version == 2", "subprocess"):
            self.assertNotIn(forbidden, source)

    def test_reviewed_visual_text_gate_rejects_aliases_and_unapproved_tokens(self) -> None:
        analysis = {
            "analysis_sha256": "a" * 64,
            "analysis": {
                "thesis": "把待办交给全能模式",
                "items": [{"id": "idea-01", "source_text": "把待办交给全能模式"}],
            },
        }
        segments = [{
            "segment_id": "seg-001",
            "content_item_ids": ["idea-01"],
            "visible_text": ["你的待办箱"],
        }]
        valid = {
            "content_analysis_sha256": "a" * 64,
            "entries": [{
                "segment_id": "seg-001", "text": "你的待办箱",
                "source_ref": "item:idea-01", "source_quote": "把待办交给全能模式",
                "reason": "把抽象能力转成日常可理解的屏显。",
            }],
        }
        self.assertEqual(visual_plan._validate_reviewed_visual_text(valid, analysis_record=analysis, segments=segments), valid["entries"])
        for field, value in (("content_analysis_sha256", "b" * 64), ("text", "全能模式 2026"), ("text", "你的 GPT 待办箱"), ("source_ref", "item:other"), ("source_quote", "被篡改的原文")):
            altered = copy.deepcopy(valid)
            if field == "content_analysis_sha256":
                altered[field] = value
            else:
                altered["entries"][0][field] = value
                if field == "text":
                    altered_segments = copy.deepcopy(segments)
                    altered_segments[0]["visible_text"] = [value]
                else:
                    altered_segments = segments
            if field == "content_analysis_sha256":
                altered_segments = segments
            with self.subTest(field=field), self.assertRaises(VisualPlanError):
                visual_plan._validate_reviewed_visual_text(altered, analysis_record=analysis, segments=altered_segments)
        alias = copy.deepcopy(valid)
        alias["entries"][0]["source_ref"] = "confirmed-content:idea-01"
        with self.assertRaises(VisualPlanError):
            visual_plan._validate_reviewed_visual_text(alias, analysis_record=analysis, segments=segments)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import unittest

from edit.hd.tools import visual_strategy


SOURCE_KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)
LEGACY_KINDS = (
    "user",
    "official",
    "project",
    "code",
    "ai_reference",
    "ai_metaphor",
    "stock",
    "ai",
)
SEMANTIC_GOALS = (
    "evidence",
    "demonstrate",
    "explain",
    "contextualize",
    "evoke",
    "metaphorize",
)
SEMANTIC_ROLES = (
    "evidence",
    "demonstration",
    "explanation",
    "context",
    "mood",
    "metaphor",
)
MEDIA_TYPES = ("image", "video", "document", "webpage", "ui_capture", "animation")
SHA256 = "a" * 64


class ExplodingEquality:
    def __eq__(self, _other: object) -> bool:
        raise RuntimeError("unexpected equality must not run")


def valid_intent(**overrides: object) -> dict[str, object]:
    intent: dict[str, object] = {
        "segment_id": "seg-001",
        "statement": "Governed data needs evidence and a clear explanation.",
        "semantic_goals": ["evidence", "explain"],
        "claims": [
            {
                "type": "concept",
                "value": "Governance makes provenance inspectable.",
                "verification_required": False,
            }
        ],
        "entities": [{"type": "product_category", "name": "data platform"}],
        "relations": [{"type": "explains", "subject": "governance", "object": "provenance"}],
        "requirements": {
            "verifiability": "medium",
            "realism": "medium",
            "abstraction": "medium",
            "product_specificity": "low",
            "emotional_intensity": "low",
        },
        "presenter_presence": "allowed",
    }
    intent.update(overrides)
    return intent


def strategy_component(
    component_id: str = "component-1",
    kind: str = "official_material",
    **overrides: object,
) -> dict[str, object]:
    component: dict[str, object] = {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": "base",
        "media_type": "document",
        "layout_slot": "full_frame",
        "brief": "Show the approved source with a readable explanatory overlay.",
    }
    component.update(overrides)
    return component


def valid_strategy(
    components: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    resolved_components = components if components is not None else [strategy_component()]
    ids = [str(item.get("component_id", "missing")) for item in resolved_components]
    base_ids = [
        str(item.get("component_id", "missing"))
        for item in resolved_components
        if item.get("layer_role") == "base"
    ]
    dependencies = [
        {"component_id": str(item.get("component_id", "missing")), "depends_on": base_ids[:1]}
        for item in resolved_components
        if item.get("layer_role") == "annotation"
    ]
    family = (
        "no_broll"
        if not resolved_components
        else "single_full_frame"
        if len(resolved_components) == 1
        else "evidence_with_data_overlay"
    )
    strategy: dict[str, object] = {
        "schema_version": 1,
        "segment_id": "seg-001",
        "mode": "single" if len(resolved_components) == 1 else "hybrid",
        "rationale": "The source proves the claim while the layout keeps it readable.",
        "components": resolved_components,
        "composition": {
            "family": family,
            "presenter_mode": "full_frame" if family == "no_broll" else "bottom_window",
            "reading_order": ids,
            "component_dependencies": dependencies,
        },
    }
    strategy.update(overrides)
    return strategy


def render_window(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "start_frame": 0,
        "end_frame": 96,
        "z_index": 0,
        "layout_slot": "full_frame",
        "opacity": 1.0,
        "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
    }
    value.update(overrides)
    return value


def artifact_contract(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "width": 1080,
        "height": 1920,
        "fps": 24,
        "alpha": False,
    }
    value.update(overrides)
    return value


def binding_for(kind: str) -> dict[str, object]:
    bindings: dict[str, dict[str, object]] = {
        "local_material": {
            "material_id": "material-001",
            "job_path": "inputs/material-001.mp4",
            "sha256": SHA256,
        },
        "official_material": {
            "source_id": "source-001",
            "publisher": "Example Research Lab",
            "source_url": "https://example.org/research",
            "snapshot_path": "snapshots/source-001.html",
            "fetched_at": "2026-08-31T12:00:00+08:00",
            "sha256": SHA256,
        },
        "external_stock": {
            "provider": "Example Stock",
            "provider_asset_id": "stock-001",
            "author": "Example Author",
            "asset_page": "https://stock.example/asset/001",
            "job_path": "stock/stock-001.mp4",
            "license_snapshot": "licenses/stock-001.html",
            "downloaded_at": "2026-08-31T12:00:00+08:00",
            "sha256": SHA256,
        },
        "code_generated": {
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "packages/renderer/render.py",
            "producer_version": "renderer-v1",
            "brief_sha256": SHA256,
            "invocation_record": {
                "argv": ["python3", "packages/renderer/render.py", "brief.json"],
                "exit_code": 0,
            },
            "primary_renderer": "html-video",
            "renderer_version": "1.2.3",
            "template_origin": "verified_third_party",
            "template_id": "hyperframes-vignelli",
            "template_version": "version-1",
            "verification_id": SHA256,
            "adaptation_level": "content_reflow",
            "source_entrypoint": "registry/examples/vignelli/index.html",
            "source_sha256": SHA256,
            "sample_sha256": SHA256,
            "semantic_families": ["comparison", "thesis"],
            "capacity": {"min_units": 3, "max_units": 7},
        },
        "ai_generated": {
            "provider": "Example AI",
            "model": "image-model-v1",
            "endpoint_id": "endpoint-001",
            "prompt_sha256": SHA256,
            "generation_id": "generation-001",
            "sha256": SHA256,
        },
    }
    return copy.deepcopy(bindings[kind])


def recipe_component(
    component_id: str,
    kind: str,
    **overrides: object,
) -> dict[str, object]:
    component: dict[str, object] = {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": "base",
        "executor": "fixture-executor",
        "media_type": "animation" if kind == "code_generated" else "image",
        "render_window": render_window(),
        "artifact_contract": artifact_contract(alpha=kind == "code_generated"),
        **binding_for(kind),
    }
    component.update(overrides)
    return component


def valid_recipe(
    components: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    resolved_components = components if components is not None else [
        recipe_component("component-1", "official_material")
    ]
    ids = [str(item.get("component_id", "missing")) for item in resolved_components]
    base_ids = [
        str(item.get("component_id", "missing"))
        for item in resolved_components
        if item.get("layer_role") == "base"
    ]
    dependencies = [
        {"component_id": str(item.get("component_id", "missing")), "depends_on": base_ids[:1]}
        for item in resolved_components
        if item.get("layer_role") == "annotation"
    ]
    recipe: dict[str, object] = {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 1,
        "mode": "single" if len(resolved_components) == 1 else "hybrid",
        "composition": {
            "family": (
                "no_broll"
                if not resolved_components
                else "single_full_frame"
                if len(resolved_components) == 1
                else "evidence_with_data_overlay"
            ),
            "presenter_mode": "full_frame" if not resolved_components else "bottom_window",
            "reading_order": ids,
            "component_dependencies": dependencies,
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": resolved_components,
        "final_compositor": "ffmpeg",
    }
    recipe.update(overrides)
    return recipe


def candidate(
    asset_id: str,
    kind: str = "official_material",
    *,
    semantic_match_score: float = 0.8,
    quality_score: float = 0.8,
    failed_gate: str | None = None,
) -> dict[str, object]:
    gates = {
        "semantic_match": True,
        "factual_reliability": True,
        "native_vertical": True,
        "quality_readability": True,
    }
    if failed_gate is not None:
        gates[failed_gate] = False
    return {
        "asset_id": asset_id,
        "kind": kind,
        "semantic_match_score": semantic_match_score,
        "quality_score": quality_score,
        "hard_gates": gates,
    }


class VisualIntentTests(unittest.TestCase):
    def test_accepts_every_semantic_goal_and_presenter_presence_value(self) -> None:
        for goal in SEMANTIC_GOALS:
            with self.subTest(goal=goal):
                result = visual_strategy.validate_visual_intent(
                    valid_intent(semantic_goals=[goal])
                )
                self.assertEqual(result["semantic_goals"], [goal])
        for presence in ("required", "allowed", "hidden"):
            with self.subTest(presence=presence):
                result = visual_strategy.validate_visual_intent(
                    valid_intent(presenter_presence=presence)
                )
                self.assertEqual(result["presenter_presence"], presence)

    def test_requires_exact_top_level_shape_and_field_types(self) -> None:
        base = valid_intent()
        for field in base:
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(invalid)
        invalid_cases = (
            [],
            valid_intent(extra=True),
            valid_intent(segment_id=""),
            valid_intent(statement="  "),
            valid_intent(semantic_goals=[]),
            valid_intent(claims={}),
            valid_intent(entities={}),
            valid_intent(relations={}),
            valid_intent(requirements=[]),
            valid_intent(presenter_presence="visible"),
            valid_intent(presenter_presence=[]),
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(invalid)

    def test_exact_shape_errors_name_missing_and_extra_fields(self) -> None:
        missing = valid_intent()
        del missing["segment_id"]
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"missing: segment_id"
        ):
            visual_strategy.validate_visual_intent(missing)
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"extra: unexpected"
        ):
            visual_strategy.validate_visual_intent(valid_intent(unexpected=True))

    def test_rejects_unknown_duplicate_and_presenter_semantic_goals(self) -> None:
        for goals in (
            ["priority"],
            ["presenter"],
            ["presence"],
            ["explain", "explain"],
        ):
            with self.subTest(goals=goals):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(valid_intent(semantic_goals=goals))

    def test_claims_and_requirement_levels_are_strict(self) -> None:
        claim = copy.deepcopy(valid_intent()["claims"][0])
        for field in ("type", "value", "verification_required"):
            with self.subTest(missing_claim_field=field):
                invalid_claim = copy.deepcopy(claim)
                del invalid_claim[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(valid_intent(claims=[invalid_claim]))
        for invalid_claim in (
            "claim",
            {**claim, "type": ""},
            {**claim, "value": 12},
            {**claim, "verification_required": 1},
        ):
            with self.subTest(invalid_claim=invalid_claim):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(valid_intent(claims=[invalid_claim]))
        requirements = copy.deepcopy(valid_intent()["requirements"])
        for field in requirements:
            with self.subTest(requirement=field):
                for level in ("low", "medium", "high"):
                    accepted = copy.deepcopy(requirements)
                    accepted[field] = level
                    visual_strategy.validate_visual_intent(valid_intent(requirements=accepted))
                invalid = copy.deepcopy(requirements)
                invalid[field] = "critical"
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_intent(valid_intent(requirements=invalid))
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_intent(
                valid_intent(requirements={**requirements, "priority": "high"})
            )

    def test_returns_a_deep_copy_without_mutating_input(self) -> None:
        intent = valid_intent()
        before = copy.deepcopy(intent)
        result = visual_strategy.validate_visual_intent(intent)
        self.assertEqual(intent, before)
        self.assertEqual(result, before)
        result["requirements"]["realism"] = "high"
        result["claims"][0]["value"] = "changed"
        self.assertEqual(intent, before)


class VisualStrategyTests(unittest.TestCase):
    def test_aroll_with_overlay_accepts_alpha_code_annotations_without_base(self) -> None:
        component = recipe_component(
            "overlay", "code_generated", layer_role="annotation",
            render_window=render_window(layout_slot="annotation", z_index=10),
            artifact_contract=artifact_contract(alpha=True),
        )
        recipe = valid_recipe(
            [component],
            mode="none",
            composition={
                "family": "aroll_with_overlay",
                "presenter_mode": "full_frame",
                "reading_order": ["overlay"],
                "component_dependencies": [],
            },
        )
        self.assertEqual(
            visual_strategy.validate_shot_recipe_v2(recipe)["composition"]["family"],
            "aroll_with_overlay",
        )

    def test_aroll_with_overlay_rejects_base_opaque_or_dependency(self) -> None:
        cases = [
            ([recipe_component("base", "official_material")], "base"),
            ([recipe_component(
                "overlay", "code_generated", layer_role="annotation",
                render_window=render_window(layout_slot="annotation", z_index=10),
                artifact_contract=artifact_contract(alpha=False),
            )], "opaque"),
        ]
        for components, _label in cases:
            recipe = valid_recipe(
                components,
                mode="none",
                composition={
                    "family": "aroll_with_overlay",
                    "presenter_mode": "full_frame",
                    "reading_order": [components[0]["component_id"]],
                    "component_dependencies": [],
                },
            )
            with self.assertRaises(visual_strategy.VisualStrategyError):
                visual_strategy.validate_shot_recipe_v2(recipe)

        component = recipe_component(
            "overlay", "code_generated", layer_role="annotation",
            render_window=render_window(layout_slot="annotation", z_index=10),
            artifact_contract=artifact_contract(alpha=True),
        )
        recipe = valid_recipe(
            [component], mode="none",
            composition={
                "family": "aroll_with_overlay", "presenter_mode": "full_frame",
                "reading_order": ["overlay"],
                "component_dependencies":[{"component_id":"overlay","depends_on":[]}],
            },
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_shot_recipe_v2(recipe)

    def test_layout_slots_follow_the_shared_layer_role_contract(self) -> None:
        expected = {
            "base": frozenset(
                {"main", "background", "full_frame", "background_blur", "content_safe"}
            ),
            "overlay": frozenset({"overlay", "main_overlay"}),
            "inset": frozenset({"inset"}),
            "annotation": frozenset({"annotation", "lower-third", "main_overlay"}),
        }
        self.assertEqual(visual_strategy.LAYER_ROLE_LAYOUT_SLOTS, expected)

        for layer_role, slots in expected.items():
            for layout_slot in slots:
                with self.subTest(layer_role=layer_role, layout_slot=layout_slot):
                    component = strategy_component(
                        "tested", layer_role=layer_role, layout_slot=layout_slot
                    )
                    components = [component]
                    if layer_role != "base":
                        components = [
                            strategy_component("base"),
                            strategy_component(
                                "annotation",
                                kind="code_generated",
                                layer_role="annotation",
                                layout_slot="annotation",
                            ),
                            component,
                        ]
                    visual_strategy.validate_visual_strategy(
                        valid_intent(), valid_strategy(components)
                    )

        for layer_role, layout_slot in (
            ("base", "lower-third"),
            ("annotation", "background"),
            ("inset", "main"),
            ("overlay", "inset"),
        ):
            with self.subTest(layer_role=layer_role, layout_slot=layout_slot):
                component = strategy_component(
                    layer_role=layer_role, layout_slot=layout_slot
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(
                        valid_intent(), valid_strategy([component])
                    )

    def test_presenter_modes_have_family_and_intent_semantics(self) -> None:
        visual_strategy.validate_visual_strategy(
            valid_intent(presenter_presence="required"), valid_strategy()
        )
        visual_strategy.validate_visual_strategy(
            valid_intent(presenter_presence="hidden"),
            valid_strategy(
                composition={
                    **valid_strategy()["composition"],
                    "presenter_mode": "hidden",
                }
            ),
        )
        visual_strategy.validate_visual_strategy(
            valid_intent(), valid_strategy([], mode="none")
        )

        for invalid in (
            valid_strategy(
                composition={
                    **valid_strategy()["composition"],
                    "presenter_mode": "visible",
                }
            ),
            valid_strategy(
                composition={
                    **valid_strategy()["composition"],
                    "presenter_mode": "full_frame",
                }
            ),
            valid_strategy(
                [],
                mode="none",
                composition={
                    **valid_strategy([], mode="none")["composition"],
                    "presenter_mode": "bottom_window",
                },
            ),
        ):
            with self.subTest(composition=invalid["composition"]), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_visual_strategy(valid_intent(), invalid)

    def test_accepts_none_single_and_hybrid_component_counts(self) -> None:
        none_strategy = valid_strategy([], mode="none")
        single = valid_strategy()
        hybrid = valid_strategy(
            [
                strategy_component("official", semantic_role="evidence"),
                strategy_component(
                    "explanation",
                    kind="code_generated",
                    semantic_role="explanation",
                    media_type="animation",
                    layer_role="annotation",
                    layout_slot="annotation",
                ),
            ]
        )
        for strategy in (none_strategy, single, hybrid):
            with self.subTest(mode=strategy["mode"]):
                self.assertEqual(
                    visual_strategy.validate_visual_strategy(valid_intent(), strategy),
                    strategy,
                )

    def test_composition_is_exact_and_reading_order_covers_every_component_once(self) -> None:
        base = valid_strategy()
        for field in (
            "family",
            "presenter_mode",
            "reading_order",
            "component_dependencies",
        ):
            invalid = copy.deepcopy(base)
            del invalid["composition"][field]
            with self.subTest(missing=field), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_visual_strategy(valid_intent(), invalid)
        invalid_cases = []
        for reading_order in ([], ["component-1", "component-1"], ["other"]):
            invalid = copy.deepcopy(base)
            invalid["composition"]["reading_order"] = reading_order
            invalid_cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["composition"]["unexpected"] = True
        invalid_cases.append(invalid)
        for invalid in invalid_cases:
            with self.subTest(composition=invalid["composition"]), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_visual_strategy(valid_intent(), invalid)

    def test_annotation_dependencies_bind_existing_base_components(self) -> None:
        base_one = strategy_component("base-one")
        base_two = strategy_component("base-two")
        annotation = strategy_component(
            "annotation",
            kind="code_generated",
            layer_role="annotation",
            layout_slot="annotation",
            media_type="animation",
        )
        approved = valid_strategy([base_one, base_two, annotation])
        approved["composition"]["component_dependencies"] = [
            {"component_id": "annotation", "depends_on": ["base-two"]}
        ]
        self.assertEqual(
            visual_strategy.validate_visual_strategy(valid_intent(), approved), approved
        )

        invalid_dependencies = (
            [],
            [{"component_id": "annotation", "depends_on": ["missing"]}],
            [{"component_id": "annotation", "depends_on": ["annotation"]}],
            [{"component_id": "base-one", "depends_on": ["base-two"]}],
            [{"component_id": "annotation", "depends_on": []}],
        )
        for dependencies in invalid_dependencies:
            invalid = copy.deepcopy(approved)
            invalid["composition"]["component_dependencies"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_visual_strategy(valid_intent(), invalid)

        reversed_order = copy.deepcopy(approved)
        reversed_order["composition"]["reading_order"] = [
            "annotation",
            "base-one",
            "base-two",
        ]
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(valid_intent(), reversed_order)

    def test_requires_exact_strategy_shape_segment_and_component_count(self) -> None:
        base = valid_strategy()
        for field in base:
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(valid_intent(), invalid)
        invalid_cases = (
            valid_strategy(extra=True),
            valid_strategy(schema_version=2),
            valid_strategy(segment_id="seg-other"),
            valid_strategy(segment_id=ExplodingEquality()),
            valid_strategy(mode="priority"),
            valid_strategy(components={}),
            valid_strategy(composition=[]),
            valid_strategy([], mode="single"),
            valid_strategy([strategy_component(), strategy_component("two")], mode="single"),
            valid_strategy([], mode="hybrid"),
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(valid_intent(), invalid)

    def test_rationale_must_be_a_non_empty_string(self) -> None:
        for rationale in ("", "   ", None, [], 7):
            with self.subTest(rationale=rationale):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(
                        valid_intent(), valid_strategy(rationale=rationale)
                    )

    def test_rationale_is_non_executable_audit_text(self) -> None:
        for rationale in (
            "A close crop makes the interaction legible.",
            "Place the annotation above the inset to preserve reading order.",
            "Use source animation after the presenter moves aside.",
            "Prefer official material before external stock when the source is unavailable.",
            "Fallback to material; source priority is audit context only.",
        ):
            with self.subTest(rationale=rationale):
                validated = visual_strategy.validate_visual_strategy(
                    valid_intent(), valid_strategy(rationale=rationale)
                )
                self.assertEqual(validated["rationale"], rationale)

    def test_component_enums_and_exact_shape_are_strict(self) -> None:
        for kind in SOURCE_KINDS:
            component = strategy_component(kind=kind)
            visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy([component]))
        for role in SEMANTIC_ROLES:
            component = strategy_component(semantic_role=role)
            visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy([component]))
        slots = {
            "base": "full_frame",
            "overlay": "overlay",
            "inset": "inset",
            "annotation": "annotation",
        }
        for layer in ("base", "overlay", "inset", "annotation"):
            component = strategy_component(
                "tested", layer_role=layer, layout_slot=slots[layer]
            )
            if layer == "base":
                components = [component]
            elif layer == "annotation":
                components = [strategy_component("base"), component]
            else:
                components = [
                    strategy_component("base"),
                    strategy_component(
                        "annotation", layer_role="annotation", layout_slot="annotation"
                    ),
                    component,
                ]
            visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy(components))
        for media_type in MEDIA_TYPES:
            component = strategy_component(media_type=media_type)
            visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy([component]))

        base = strategy_component()
        for field in base:
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy([invalid]))
        invalid_components = (
            {**base, "extra": True},
            {**base, "component_id": ""},
            {**base, "kind": "official"},
            {**base, "semantic_role": "priority"},
            {**base, "layer_role": "foreground"},
            {**base, "media_type": "audio"},
            {**base, "layout_slot": ""},
            {**base, "brief": []},
        )
        for component in invalid_components:
            with self.subTest(component=component):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy([component]))

    def test_rejects_duplicate_component_ids_and_legacy_kinds(self) -> None:
        duplicate = [strategy_component("same"), strategy_component("same")]
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(valid_intent(), valid_strategy(duplicate))
        for kind in LEGACY_KINDS:
            with self.subTest(kind=kind):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(
                        valid_intent(), valid_strategy([strategy_component(kind=kind)])
                    )

    def test_ai_and_stock_cannot_evidence_protected_factual_claims(self) -> None:
        for claim_type in ("named_person_identity", "official_statement", "precise_fact"):
            for verification_required in (False, True):
                intent = valid_intent(
                    claims=[
                        {
                            "type": claim_type,
                            "value": "A structured factual claim",
                            "verification_required": verification_required,
                        }
                    ]
                )
                for kind in ("external_stock", "ai_generated"):
                    with self.subTest(
                        claim_type=claim_type,
                        verification_required=verification_required,
                        kind=kind,
                    ):
                        component = strategy_component(kind=kind, semantic_role="evidence")
                        with self.assertRaises(visual_strategy.VisualStrategyError):
                            visual_strategy.validate_visual_strategy(
                                intent, valid_strategy([component])
                            )

        shadowed_named_person = valid_intent(
            entities=[
                {
                    "type": "entity",
                    "entity_type": "named_person",
                    "name": "Named Presenter",
                }
            ]
        )
        ai_evidence = strategy_component(
            kind="ai_generated", semantic_role="evidence", media_type="image"
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                shadowed_named_person, valid_strategy([ai_evidence])
            )

    def test_every_verified_claim_rejects_generated_or_stock_evidence(self) -> None:
        intent = valid_intent(
            claims=[
                {
                    "type": "exact_number",
                    "value": "3→7",
                    "verification_required": True,
                }
            ]
        )
        for kind in ("ai_generated", "external_stock", "code_generated"):
            with self.subTest(kind=kind):
                component = strategy_component(
                    kind=kind,
                    semantic_role="evidence",
                    media_type="animation" if kind == "code_generated" else "image",
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(
                        intent, valid_strategy([component])
                    )

    def test_high_specificity_ui_capture_requires_local_or_official_material(self) -> None:
        requirements = copy.deepcopy(valid_intent()["requirements"])
        requirements["product_specificity"] = "high"
        intent = valid_intent(requirements=requirements)
        for role in SEMANTIC_ROLES:
            for kind in SOURCE_KINDS:
                with self.subTest(role=role, kind=kind):
                    component = strategy_component(
                        kind=kind,
                        semantic_role=role,
                        media_type="ui_capture",
                    )
                    strategy = valid_strategy([component])
                    if kind in {"local_material", "official_material"}:
                        visual_strategy.validate_visual_strategy(intent, strategy)
                    else:
                        with self.assertRaises(visual_strategy.VisualStrategyError):
                            visual_strategy.validate_visual_strategy(intent, strategy)

    def test_real_product_ui_signals_require_local_or_official_ui_capture(self) -> None:
        intents = {
            "claim": valid_intent(
                claims=[
                    {
                        "type": "claim",
                        "claim_type": "real_product_ui",
                        "value": "Show the named product screen exactly.",
                        "verification_required": False,
                    }
                ]
            ),
            "entity": valid_intent(
                entities=[
                    {
                        "type": "entity",
                        "entity_type": "real_product_ui",
                        "name": "Named product screen",
                    }
                ]
            ),
            "relation": valid_intent(
                relations=[
                    {
                        "type": "relation",
                        "relation_type": "represents_real_product",
                        "subject": "capture",
                        "object": "named product",
                    }
                ]
            ),
        }
        for signal, intent in intents.items():
            for kind in SOURCE_KINDS:
                with self.subTest(signal=signal, kind=kind):
                    component = strategy_component(
                        kind=kind,
                        semantic_role="explanation",
                        media_type="ui_capture",
                    )
                    strategy = valid_strategy([component])
                    if kind in {"local_material", "official_material"}:
                        self.assertEqual(
                            visual_strategy.validate_visual_strategy(intent, strategy),
                            strategy,
                        )
                    else:
                        with self.assertRaises(visual_strategy.VisualStrategyError):
                            visual_strategy.validate_visual_strategy(intent, strategy)

    def test_code_cannot_be_evidence_or_impersonate_product_ui(self) -> None:
        code_evidence = strategy_component(
            kind="code_generated", semantic_role="evidence", media_type="animation"
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                valid_intent(), valid_strategy([code_evidence])
            )

        requirements = copy.deepcopy(valid_intent()["requirements"])
        requirements["product_specificity"] = "high"
        fake_ui = strategy_component(
            kind="code_generated",
            semantic_role="demonstration",
            media_type="ui_capture",
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                valid_intent(requirements=requirements), valid_strategy([fake_ui])
            )
        ui_claim_intent = valid_intent(
            claims=[
                {
                    "type": "real_product_ui",
                    "value": "The named product screen must be shown exactly.",
                    "verification_required": True,
                }
            ]
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                ui_claim_intent, valid_strategy([fake_ui])
            )

    def test_stock_cannot_stand_for_a_specific_real_event(self) -> None:
        intents = (
            valid_intent(
                relations=[
                    {
                        "type": "specific_real_event",
                        "subject": "named_launch",
                        "object": "2026_keynote",
                    }
                ]
            ),
            valid_intent(
                claims=[
                    {
                        "type": "specific_real_event",
                        "value": "The named launch occurred at the 2026 keynote.",
                        "verification_required": True,
                    }
                ]
            ),
            valid_intent(
                relations=[
                    {
                        "type": "relation",
                        "relation_type": "specific_real_event",
                        "subject": "named_launch",
                        "object": "2026_keynote",
                    }
                ]
            ),
        )
        stock = strategy_component(kind="external_stock", semantic_role="context")
        for intent in intents:
            with self.subTest(intent=intent):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(intent, valid_strategy([stock]))
        atmospheric_stock = strategy_component(
            kind="external_stock", semantic_role="mood"
        )
        visual_strategy.validate_visual_strategy(
            intents[0], valid_strategy([atmospheric_stock])
        )

    def test_missing_official_evidence_cannot_be_replaced_and_hybrid_is_legal(self) -> None:
        intent = valid_intent(
            claims=[
                {
                    "type": "official_statement",
                    "value": "The publisher made this statement.",
                    "verification_required": True,
                }
            ]
        )
        replacement = strategy_component(
            kind="ai_generated", semantic_role="explanation", media_type="animation"
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(intent, valid_strategy([replacement]))

        hybrid = valid_strategy(
            [
                strategy_component("official", semantic_role="evidence"),
                strategy_component(
                    "code",
                    kind="code_generated",
                    semantic_role="explanation",
                    media_type="animation",
                    layer_role="annotation",
                    layout_slot="annotation",
                ),
            ]
        )
        self.assertEqual(
            visual_strategy.validate_visual_strategy(intent, hybrid),
            hybrid,
        )

        attributed_intent = valid_intent(
            relations=[
                {
                    "type": "official_attribution",
                    "subject": "statement",
                    "object": "publisher",
                }
            ]
        )
        official_plus_ai_evidence = valid_strategy(
            [
                strategy_component("official", semantic_role="evidence"),
                strategy_component(
                    "ai-evidence",
                    kind="ai_generated",
                    semantic_role="evidence",
                    media_type="image",
                    layer_role="inset",
                ),
            ]
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                attributed_intent, official_plus_ai_evidence
            )

        shadowed_attribution = valid_intent(
            relations=[
                {
                    "type": "relation",
                    "relation_type": "official_attribution",
                    "subject": "statement",
                    "object": "publisher",
                }
            ]
        )
        for kind in ("ai_generated", "code_generated", "external_stock"):
            with self.subTest(shadowed_official_attribution=kind):
                replacement = strategy_component(
                    kind=kind,
                    semantic_role="explanation",
                    media_type="animation" if kind != "external_stock" else "video",
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_visual_strategy(
                        shadowed_attribution, valid_strategy([replacement])
                    )

        shadowed_claim = valid_intent(
            claims=[
                {
                    "type": "claim",
                    "claim_type": "official_statement",
                    "value": "The publisher made this statement.",
                    "verification_required": True,
                }
            ]
        )
        code_explanation = strategy_component(
            kind="code_generated",
            semantic_role="explanation",
            media_type="animation",
        )
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_visual_strategy(
                shadowed_claim, valid_strategy([code_explanation])
            )

    def test_returns_deep_copies_of_intent_and_strategy_data(self) -> None:
        intent = valid_intent()
        strategy = valid_strategy()
        intent_before = copy.deepcopy(intent)
        strategy_before = copy.deepcopy(strategy)
        result = visual_strategy.validate_visual_strategy(intent, strategy)
        self.assertEqual(intent, intent_before)
        self.assertEqual(strategy, strategy_before)
        result["components"][0]["brief"] = "changed"
        self.assertEqual(strategy, strategy_before)


class ShotRecipeV2Tests(unittest.TestCase):
    def test_recipe_preserves_layer_roles_and_the_exact_composition(self) -> None:
        base = recipe_component("base", "official_material")
        annotation = recipe_component(
            "annotation",
            "code_generated",
            layer_role="annotation",
            render_window=render_window(
                z_index=10, layout_slot="annotation", start_frame=8, end_frame=80
            ),
        )
        recipe = valid_recipe([base, annotation])
        self.assertEqual(
            visual_strategy.validate_shot_recipe_v2(recipe)["composition"],
            recipe["composition"],
        )
        self.assertEqual(
            [item["layer_role"] for item in recipe["components"]],
            ["base", "annotation"],
        )

        for dependencies in (
            [],
            [{"component_id": "annotation", "depends_on": ["missing"]}],
        ):
            invalid = copy.deepcopy(recipe)
            invalid["composition"]["component_dependencies"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_shot_recipe_v2(invalid)

    def test_code_annotation_depends_only_on_real_material_bases(self) -> None:
        for kind in ("local_material", "official_material", "external_stock"):
            with self.subTest(real_base=kind):
                base = recipe_component("base", kind)
                annotation = recipe_component(
                    "annotation",
                    "code_generated",
                    layer_role="annotation",
                    render_window=render_window(z_index=10, layout_slot="annotation"),
                )
                visual_strategy.validate_shot_recipe_v2(valid_recipe([base, annotation]))

        for kind in ("code_generated", "ai_generated"):
            with self.subTest(non_material_base=kind):
                base = recipe_component("base", kind)
                annotation = recipe_component(
                    "annotation",
                    "code_generated",
                    layer_role="annotation",
                    render_window=render_window(z_index=10, layout_slot="annotation"),
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(
                        valid_recipe([base, annotation])
                    )
    def test_accepts_five_discriminated_component_bindings(self) -> None:
        for kind in SOURCE_KINDS:
            with self.subTest(kind=kind):
                recipe = valid_recipe([recipe_component("component-1", kind)])
                self.assertEqual(visual_strategy.validate_shot_recipe_v2(recipe), recipe)

    def test_accepts_none_single_and_complete_hybrid_windows(self) -> None:
        extensible_code = recipe_component("extensible-code", "code_generated")
        extensible_code["invocation_record"]["signal"] = None
        recipes = (
            valid_recipe([], mode="none"),
            valid_recipe(),
            valid_recipe([extensible_code]),
            valid_recipe(
                [
                    recipe_component("official", "official_material"),
                    recipe_component(
                        "code",
                        "code_generated",
                        layer_role="annotation",
                        render_window=render_window(z_index=1, layout_slot="annotation", opacity=0.8),
                    ),
                ]
            ),
        )
        for recipe in recipes:
            with self.subTest(mode=recipe["mode"]):
                visual_strategy.validate_shot_recipe_v2(recipe)

    def test_render_window_rejects_nested_extra_fields(self) -> None:
        component = recipe_component("component-1", "code_generated")
        component["render_window"]["anchor"] = "center"
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"extra: anchor"
        ):
            visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_top_level_recipe_canvas_and_compositor_are_strict(self) -> None:
        base = valid_recipe()
        for field in base:
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(invalid)
        invalid_cases = (
            [],
            valid_recipe(extra=True),
            valid_recipe(schema_version=1),
            valid_recipe(segment_id=""),
            valid_recipe(strategy_revision=0),
            valid_recipe(strategy_revision=True),
            valid_recipe(mode="fallback"),
            valid_recipe(canvas={"width": 1920, "height": 1080, "fps": 24}),
            valid_recipe(final_compositor="remotion"),
            valid_recipe(final_compositor=ExplodingEquality()),
            valid_recipe([], mode="single"),
            valid_recipe(
                [recipe_component("a", "local_material"), recipe_component("b", "ai_generated")],
                mode="single",
            ),
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(invalid)

    def test_integer_minimum_error_names_the_bound(self) -> None:
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"at least 1"
        ):
            visual_strategy.validate_shot_recipe_v2(valid_recipe(strategy_revision=0))

    def test_component_common_fields_and_enums_are_strict(self) -> None:
        base = recipe_component("component-1", "local_material")
        for field in (
            "component_id",
            "kind",
            "semantic_role",
            "layer_role",
            "executor",
            "media_type",
            "render_window",
            "artifact_contract",
        ):
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([invalid]))
        invalid_components = (
            {**base, "component_id": ""},
            {**base, "kind": "local"},
            {**base, "semantic_role": "priority"},
            {**base, "executor": []},
            {**base, "media_type": "audio"},
        )
        for component in invalid_components:
            with self.subTest(component=component):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_render_window_and_artifact_contract_are_strict(self) -> None:
        for field in render_window():
            with self.subTest(missing_window_field=field):
                window = render_window()
                del window[field]
                component = recipe_component("component-1", "local_material", render_window=window)
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))
        invalid_windows = (
            render_window(start_frame=-1),
            render_window(start_frame=True),
            render_window(end_frame=0),
            render_window(z_index=1.5),
            render_window(layout_slot=""),
            render_window(opacity=-0.1),
            render_window(opacity=1.1),
            render_window(safe_zone=[]),
        )
        for window in invalid_windows:
            with self.subTest(window=window):
                component = recipe_component("component-1", "local_material", render_window=window)
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

        for field in artifact_contract():
            with self.subTest(missing_artifact_field=field):
                contract = artifact_contract()
                del contract[field]
                component = recipe_component("component-1", "local_material", artifact_contract=contract)
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))
        for contract in (
            artifact_contract(width=640, height=360),
            artifact_contract(width=0),
            artifact_contract(height=-1),
            artifact_contract(fps=30),
            artifact_contract(alpha=1),
            {**artifact_contract(), "codec": "h264"},
        ):
            with self.subTest(contract=contract):
                component = recipe_component("component-1", "local_material", artifact_contract=contract)
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_720p_is_only_accepted_for_opaque_ai_broll_video(self) -> None:
        source = artifact_contract(width=720, height=1280)
        component = recipe_component(
            "component-1", "ai_generated", media_type="video", artifact_contract=source
        )
        recipe = visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))
        self.assertEqual(recipe["canvas"], {"width": 1080, "height": 1920, "fps": 24})
        self.assertEqual(recipe["components"][0]["artifact_contract"], source)

        for kind, media_type, contract in (
            ("ai_generated", "image", source),
            ("ai_generated", "video", artifact_contract(width=720, height=1280, alpha=True)),
            ("code_generated", "animation", artifact_contract(width=720, height=1280, alpha=True)),
            ("local_material", "video", source),
            ("ai_generated", "video", artifact_contract(width=720, height=1278)),
            ("ai_generated", "video", artifact_contract(width=720, height=1280, fps=30)),
        ):
            with self.subTest(kind=kind, media_type=media_type, contract=contract):
                component = recipe_component(
                    "component-1", kind, media_type=media_type, artifact_contract=contract
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_integer_opacity_is_normalized_without_mutating_recipe(self) -> None:
        for opacity in (0, 1):
            with self.subTest(opacity=opacity):
                component = recipe_component(
                    "component-1",
                    "local_material",
                    render_window=render_window(opacity=opacity),
                )
                recipe = valid_recipe([component])
                before = copy.deepcopy(recipe)

                validated = visual_strategy.validate_shot_recipe_v2(recipe)

                normalized = validated["components"][0]["render_window"][
                    "opacity"
                ]
                self.assertIs(type(normalized), float)
                self.assertEqual(normalized, float(opacity))
                self.assertEqual(recipe, before)

    def test_safe_zone_is_exact_nonnegative_and_inside_the_canvas(self) -> None:
        invalid_safe_zones = (
            "not-a-safe-zone",
            {"top": 120, "bottom": 320, "left": 40},
            {**render_window()["safe_zone"], "center": 0},
            {**render_window()["safe_zone"], "top": True},
            {**render_window()["safe_zone"], "left": -1},
            {"top": 120, "bottom": 320, "left": 540, "right": 540},
            {"top": 960, "bottom": 960, "left": 40, "right": 40},
        )
        for safe_zone in invalid_safe_zones:
            with self.subTest(safe_zone=safe_zone):
                component = recipe_component(
                    "component-1",
                    "local_material",
                    render_window=render_window(safe_zone=safe_zone),
                )
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_material_paths_and_source_urls_are_structurally_validated(self) -> None:
        invalid_paths = (
            "/absolute/material.mp4",
            "../material.mp4",
            "inputs/../material.mp4",
            r"inputs\material.mp4",
            "https://example.org/material.mp4",
        )
        for kind, field in (
            ("local_material", "job_path"),
            ("official_material", "snapshot_path"),
            ("external_stock", "job_path"),
            ("external_stock", "license_snapshot"),
        ):
            for value in invalid_paths:
                with self.subTest(kind=kind, field=field, value=value):
                    component = recipe_component("component-1", kind)
                    component[field] = value
                    with self.assertRaises(visual_strategy.VisualStrategyError):
                        visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

        for kind, field in (
            ("official_material", "source_url"),
            ("external_stock", "asset_page"),
        ):
            for value in (
                "http://example.org/asset",
                "https:///missing-host",
                "relative/asset-page",
                "https://bad host.example/asset",
                "https://example.org:bad/asset",
                "https://example.org:99999/asset",
                "https://user:pass@example.org/asset",
                "https://example.org/asset#fragment",
                "https://example.org/asset#",
                "https://example.org/\nasset",
                "https://example.org/\x01asset",
            ):
                with self.subTest(kind=kind, field=field, value=value):
                    component = recipe_component("component-1", kind)
                    component[field] = value
                    with self.assertRaises(visual_strategy.VisualStrategyError):
                        visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

        visual_strategy.validate_shot_recipe_v2(
            valid_recipe(
                [
                    recipe_component(
                        "component-1", "ai_generated", endpoint_id="not-a-url"
                    )
                ]
            )
        )

    def test_each_kind_requires_every_binding_field(self) -> None:
        for kind in SOURCE_KINDS:
            for field in binding_for(kind):
                with self.subTest(kind=kind, missing=field):
                    component = recipe_component("component-1", kind)
                    del component[field]
                    with self.assertRaises(visual_strategy.VisualStrategyError):
                        visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_code_binding_rejects_forged_template_provenance(self) -> None:
        code = recipe_component("component-1", "code_generated")
        forged = copy.deepcopy(code)
        forged["template_origin"] = "verified_third_party"
        forged["adaptation_level"] = "structural"
        with self.assertRaisesRegex(visual_strategy.VisualStrategyError, "structural"):
            visual_strategy.validate_shot_recipe_v2(valid_recipe([forged]))

        invalid_shapes = (
            {**code, "semantic_families": []},
            {**code, "semantic_families": ["comparison", "comparison"]},
            {**code, "capacity": {"min_units": 7, "max_units": 3}},
            {**code, "capacity": {"min_units": True, "max_units": 7}},
            {**code, "capacity": {"min_units": 3, "max_units": 7, "extra": 1}},
        )
        for component in invalid_shapes:
            with self.subTest(component=component):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_local_canonical_template_may_bind_structural_adaptation(self) -> None:
        code = recipe_component("component-1", "code_generated")
        code["template_origin"] = "verified_local_canonical"
        code["adaptation_level"] = "structural"

        visual_strategy.validate_shot_recipe_v2(valid_recipe([code]))

    def test_discriminated_union_rejects_cross_kind_pollution(self) -> None:
        pollution = {
            "local_material": ("publisher", "foreign publisher"),
            "official_material": ("material_id", "foreign-material"),
            "external_stock": ("generation_id", "foreign-generation"),
            "code_generated": ("source_id", "foreign-source"),
            "ai_generated": ("dependency_id", "foreign-dependency"),
        }
        for kind, (field, value) in pollution.items():
            with self.subTest(kind=kind, field=field):
                component = recipe_component("component-1", kind)
                component[field] = value
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_binding_shape_error_names_missing_and_extra_fields(self) -> None:
        missing = recipe_component("component-1", "local_material")
        del missing["job_path"]
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"missing: job_path"
        ):
            visual_strategy.validate_shot_recipe_v2(valid_recipe([missing]))

        polluted = recipe_component("component-1", "local_material")
        polluted["publisher"] = "foreign publisher"
        with self.assertRaisesRegex(
            visual_strategy.VisualStrategyError, r"extra: publisher"
        ):
            visual_strategy.validate_shot_recipe_v2(valid_recipe([polluted]))

    def test_all_hashes_and_code_execution_evidence_are_strict(self) -> None:
        for kind in SOURCE_KINDS:
            component = recipe_component("component-1", kind)
            hash_fields = [field for field in component if field.endswith("sha256")]
            for field in hash_fields:
                with self.subTest(kind=kind, hash_field=field):
                    invalid = copy.deepcopy(component)
                    invalid[field] = "not-a-sha256"
                    with self.assertRaises(visual_strategy.VisualStrategyError):
                        visual_strategy.validate_shot_recipe_v2(valid_recipe([invalid]))

        code = recipe_component("component-1", "code_generated")
        invalid_code = (
            {**code, "primary_renderer": ["one", "two"]},
            {**code, "invocation_record": {"argv": [], "exit_code": 0}},
            {**code, "invocation_record": {"argv": [""], "exit_code": 0}},
            {**code, "invocation_record": {"argv": ["python3", 7], "exit_code": 0}},
            {**code, "invocation_record": {"argv": ["python3"], "exit_code": 7}},
            {**code, "invocation_record": {"argv": ["python3"], "exit_code": False}},
        )
        for component in invalid_code:
            with self.subTest(component=component):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_duplicate_component_ids_and_legacy_kinds_are_rejected(self) -> None:
        duplicate = [
            recipe_component("same", "local_material"),
            recipe_component("same", "official_material"),
        ]
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_shot_recipe_v2(valid_recipe(duplicate))
        for kind in LEGACY_KINDS:
            with self.subTest(kind=kind):
                component = recipe_component("component-1", "local_material")
                component["kind"] = kind
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.validate_shot_recipe_v2(valid_recipe([component]))

    def test_returns_a_deep_copy_without_mutating_recipe(self) -> None:
        recipe = valid_recipe()
        before = copy.deepcopy(recipe)
        result = visual_strategy.validate_shot_recipe_v2(recipe)
        self.assertEqual(recipe, before)
        result["components"][0]["render_window"]["opacity"] = 0.5
        self.assertEqual(recipe, before)


class StableSameKindCandidateTests(unittest.TestCase):
    def test_filters_gates_then_sorts_stably_and_order_independently(self) -> None:
        candidates = [
            candidate("z-quality", semantic_match_score=0.9, quality_score=0.8),
            candidate("a-tie", semantic_match_score=0.9, quality_score=0.9),
            candidate("b-tie", semantic_match_score=0.9, quality_score=0.9),
            candidate(
                "failed-high",
                semantic_match_score=1.0,
                quality_score=1.0,
                failed_gate="quality_readability",
            ),
            candidate("lower", semantic_match_score=0.7, quality_score=1.0),
        ]
        expected_ids = ["a-tie", "b-tie", "z-quality", "lower"]
        before = copy.deepcopy(candidates)
        forward = visual_strategy.stable_same_kind_candidates(candidates, "official_material")
        reverse = visual_strategy.stable_same_kind_candidates(
            list(reversed(candidates)), "official_material"
        )
        self.assertEqual([item["asset_id"] for item in forward], expected_ids)
        self.assertEqual(forward, reverse)
        self.assertEqual(candidates, before)
        forward[0]["hard_gates"]["semantic_match"] = False
        self.assertEqual(candidates, before)

    def test_every_false_gate_is_filtered_and_all_filtered_is_rejected(self) -> None:
        gates = (
            "semantic_match",
            "factual_reliability",
            "native_vertical",
            "quality_readability",
        )
        for gate in gates:
            with self.subTest(gate=gate):
                selected = visual_strategy.stable_same_kind_candidates(
                    [candidate("failed", failed_gate=gate), candidate("eligible")],
                    "official_material",
                )
                self.assertEqual([item["asset_id"] for item in selected], ["eligible"])
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.stable_same_kind_candidates(
                [candidate(f"failed-{gate}", failed_gate=gate) for gate in gates],
                "official_material",
            )

    def test_candidate_shape_gates_scores_and_expected_kind_are_strict(self) -> None:
        base = candidate("asset")
        for field in base:
            with self.subTest(missing=field):
                invalid = copy.deepcopy(base)
                del invalid[field]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates([invalid], "official_material")
        for gate in base["hard_gates"]:
            with self.subTest(missing_gate=gate):
                invalid = copy.deepcopy(base)
                del invalid["hard_gates"][gate]
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates([invalid], "official_material")
        invalid_candidates = (
            {**base, "extra": True},
            {**base, "asset_id": ""},
            {**base, "semantic_match_score": True},
            {**base, "quality_score": float("nan")},
            {**base, "quality_score": 10**400},
            {**base, "hard_gates": {**base["hard_gates"], "semantic_match": 1}},
            {**base, "hard_gates": {**base["hard_gates"], "extra": True}},
        )
        for invalid in invalid_candidates:
            with self.subTest(invalid=invalid):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates([invalid], "official_material")
        for invalid_input in (None, {}, "assets"):
            with self.subTest(invalid_input=invalid_input):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates(invalid_input, "official_material")
        for expected_kind in (*LEGACY_KINDS, "unknown"):
            with self.subTest(expected_kind=expected_kind):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates([base], expected_kind)

        unbounded_scores = [
            candidate("high", semantic_match_score=10.0, quality_score=-3.0),
            candidate("low", semantic_match_score=-1.0, quality_score=100.0),
        ]
        self.assertEqual(
            [
                item["asset_id"]
                for item in visual_strategy.stable_same_kind_candidates(
                    unbounded_scores, "official_material"
                )
            ],
            ["high", "low"],
        )

        for kind in SOURCE_KINDS:
            with self.subTest(accepted_kind=kind):
                self.assertEqual(
                    visual_strategy.stable_same_kind_candidates(
                        [candidate("asset", kind)], kind
                    )[0]["kind"],
                    kind,
                )

    def test_mixed_kind_and_foreign_only_candidates_stop_explicitly(self) -> None:
        mixed = [candidate("official"), candidate("stock", "external_stock")]
        foreign = [candidate("stock", "external_stock")]
        for candidates in (mixed, foreign):
            with self.subTest(candidates=candidates):
                with self.assertRaises(visual_strategy.VisualStrategyError):
                    visual_strategy.stable_same_kind_candidates(
                        candidates, "official_material"
                    )


if __name__ == "__main__":
    unittest.main()

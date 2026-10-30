from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import broll_component_executor, broll_systems, segment_render
from edit.hd.tests.test_avatar_contract import avatar_fixture


ROOT = Path(__file__).resolve().parents[3]
ROUTER_PATH = ROOT / "skill-development/hd-talking-head/scripts/broll_capability_router.py"
SOURCE_KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)
LEGACY_SOURCE_KINDS = (
    "user",
    "official",
    "project",
    "code",
    "ai_reference",
    "ai_metaphor",
)


def _load_router():
    spec = importlib.util.spec_from_file_location("broll_capability_router", ROUTER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load B-roll capability router")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _visual_intent(segment_id: str = "seg-router") -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "statement": "Use the approved visual components to explain the segment.",
        "semantic_goals": ["explain"],
        "claims": [
            {
                "type": "concept",
                "value": "The approved components explain one idea together.",
                "verification_required": False,
            }
        ],
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


def _strategy_component(
    component_id: str,
    kind: str,
    *,
    layout_slot: str = "main",
) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": (
            "base"
            if layout_slot in {"main", "background", "full_frame", "background_blur", "content_safe"}
            else "annotation"
            if layout_slot in {"lower-third", "annotation"}
            else "inset"
            if layout_slot == "inset"
            else "overlay"
        ),
        "media_type": "animation" if kind == "code_generated" else "image",
        "layout_slot": layout_slot,
        "brief": f"Render the approved {kind} component without changing its kind.",
    }


def _visual_strategy(
    components: list[dict[str, object]],
    *,
    segment_id: str = "seg-router",
) -> dict[str, object]:
    base_ids = [
        str(component["component_id"])
        for component in components
        if component["layer_role"] == "base"
    ]
    return {
        "schema_version": 1,
        "segment_id": segment_id,
        "mode": "single" if len(components) == 1 else "hybrid",
        "rationale": "Each component has an approved semantic role in the composition.",
        "components": components,
        "composition": {
            "family": "single_full_frame" if len(components) == 1 else "evidence_with_data_overlay",
            "presenter_mode": "bottom_window",
            "reading_order": [component["component_id"] for component in components],
            "component_dependencies": [
                {
                    "component_id": component["component_id"],
                    "depends_on": base_ids[:1],
                }
                for component in components
                if component["layer_role"] == "annotation"
            ],
        },
    }


def _candidate(
    asset_id: str,
    kind: str,
    *,
    semantic_score: float = 0.9,
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
        "semantic_match_score": semantic_score,
        "quality_score": quality_score,
        "hard_gates": gates,
    }


def _template_candidate(
    template_id: str,
    origin: str,
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "template_origin": origin,
        "template_id": template_id,
        "template_version": "version-1",
        "verification_id": "7" * 64,
        "adaptation_level": "content_reflow",
        "source_entrypoint": f"templates/{template_id}/index.html",
        "source_sha256": "8" * 64,
        "sample_sha256": "9" * 64,
        "semantic_families": ["comparison"],
        "capacity": {"min_units": 3, "max_units": 7},
        "semantic_match_score": 0.9,
        "quality_score": 0.9,
        "reuse_gap": 12,
    }
    value.update(overrides)
    return value


def _native_template_candidate(**overrides: object) -> dict[str, object]:
    """Real native route identity; sample/scores are structure-only test data."""
    entry = "scripts/hyperframes_native_adapter.py"
    value = _template_candidate(
        "hyperframes-screen-flow-carousel-portrait-adaptation", "custom_fallback",
        template_version="1.3.0", adaptation_level="structural",
        source_entrypoint=entry,
        source_sha256=hashlib.sha256((ROUTER_PATH.parents[1] / entry).read_bytes()).hexdigest(),
        semantic_families=["screen_sequence"], capacity={"min_units": 2, "max_units": 5},
    )
    value.update(overrides)
    return value


def _binding(kind: str, asset_id: str) -> dict[str, object]:
    bindings: dict[str, dict[str, object]] = {
        "local_material": {
            "material_id": asset_id,
            "job_path": f"inputs/{asset_id}.mp4",
            "sha256": "1" * 64,
        },
        "official_material": {
            "source_id": asset_id,
            "publisher": "Example Research Lab",
            "source_url": "https://example.org/research",
            "snapshot_path": f"snapshots/{asset_id}.html",
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
                "argv": ["node", "packages/adapter-hyperframes/src/render.ts"],
                "exit_code": 0,
                "template_request": {"semantic_family": "comparison", "information_units": 5,
                                     "numeric_values": [], "numeric_scale": "not_applicable"},
            },
            "primary_renderer": "HyperFrames",
            "renderer_version": "renderer-v1",
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
    return copy.deepcopy(bindings[kind])


def _compile_context(
    components: list[dict[str, object]],
    *,
    segment_frames: int = 72,
    candidate_overrides: dict[str, object] | None = None,
    binding_overrides: dict[str, object] | None = None,
    template_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshots: dict[str, object] = {}
    bindings: dict[str, object] = {}
    template_candidates: dict[str, object] = {}
    for component in components:
        component_id = str(component["component_id"])
        kind = str(component["kind"])
        if kind not in {"code_generated", "ai_generated"}:
            snapshots[component_id] = [_candidate(f"asset-{component_id}", kind)]
        if kind == "code_generated":
            candidate = _native_template_candidate()
            if component["layer_role"] == "annotation":
                candidate = _native_template_candidate(
                    template_id="hyperframes-mk-specs-list-portrait-adaptation",
                    semantic_families=["feature_list"],
                )
            template_candidates[component_id] = {
                "semantic_family": candidate["semantic_families"][0],
                "information_units": 5,
                "candidates": [candidate],
            }
        bindings[component_id] = _binding(kind, f"asset-{component_id}")
        if kind == "code_generated":
            binding = bindings[component_id]
            binding.update(
                dependency_id="hyperframes-native-adaptation",
                entrypoint=candidate["source_entrypoint"], producer_version="1.3.0",
                renderer_version="0.8.167",
            )
            binding["invocation_record"]["argv"] = ["python3", binding["entrypoint"]]
            binding["invocation_record"]["template_request"]["semantic_family"] = candidate["semantic_families"][0]
    if candidate_overrides:
        snapshots.update(candidate_overrides)
    if binding_overrides:
        bindings.update(binding_overrides)
    if template_overrides:
        template_candidates.update(template_overrides)
    return {
        "intent": _visual_intent(),
        "candidate_snapshots": snapshots,
        "bindings": bindings,
        "template_candidates": template_candidates,
        "segment_frames": segment_frames,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class BrollCapabilityRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.router = _load_router()

    def test_composition_alpha_distinguishes_hybrid_annotation_and_base(self):
        from edit.hd.tools.dependency_contracts import output_alpha
        self.assertTrue(output_alpha('code_generated', 'barty-motion-graphics', 'evidence_with_data_overlay', 'annotation'))
        self.assertFalse(output_alpha('code_generated', 'barty-motion-graphics', 'evidence_with_data_overlay', 'base'))
        self.assertTrue(output_alpha('code_generated', 'barty-motion-graphics', 'aroll_with_overlay', 'annotation'))
        self.assertFalse(output_alpha('code_generated', 'barty-motion-graphics', 'single_full_frame', 'base'))
        self.assertFalse(output_alpha('ai_generated', None, 'evidence_with_data_overlay', 'base'))

    def test_adu_compiles_opaque_reference_adapter_and_rejects_evidence(self) -> None:
        component = _strategy_component("adu", "code_generated", layout_slot="full_frame")
        binding = _binding("code_generated", "asset-adu")
        binding.update(dependency_id="adu-motion-video", primary_renderer="HTMLCanvas",
                       entrypoint="scripts/render_adu_native.mjs", producer_version="2.3.0",
                       renderer_version="2.3.0")
        binding["invocation_record"]["argv"] = ["node", binding["entrypoint"]]
        binding["invocation_record"]["template_request"] = {
            "semantic_family": "old_new_comparison", "information_units": 3,
            "numeric_values": [], "numeric_scale": "not_applicable"}
        context = _compile_context([component], segment_frames=144,
            binding_overrides={"adu": binding}, template_overrides={"adu": {
                "semantic_family": "old_new_comparison", "information_units": 3,
                "candidates": [_template_candidate("adu-motion-video/native-compare", "custom_fallback",
                    template_version="2.3.0", source_entrypoint=binding["entrypoint"],
                    source_sha256=hashlib.sha256((ROUTER_PATH.parents[1] / binding["entrypoint"]).read_bytes()).hexdigest(),
                    adaptation_level="structural", semantic_families=["old_new_comparison"],
                    capacity={"min_units": 2, "max_units": 6})]}})
        result = self.router.compile_strategy(_visual_strategy([component]), context)
        compiled = result["components"][0]
        self.assertEqual(compiled["executor"], "reference_adapter")
        self.assertEqual(compiled["primary_renderer"], "HTMLCanvas")
        self.assertFalse(compiled["artifact_contract"]["alpha"])
        component["semantic_role"] = "evidence"
        with self.assertRaisesRegex(self.router.RouterError, "factual evidence"):
            self.router.compile_strategy(_visual_strategy([component]), context)

    def registered_context(self):
        component = _strategy_component("code", "code_generated")
        context = _compile_context([component])
        context.pop("template_candidates")
        record = json.loads((ROUTER_PATH.parents[1] / "references/verified-template-registry.json").read_text())["templates"][0]
        binding = context["bindings"]["code"]
        for field in self.router._TEMPLATE_PROVENANCE_FIELDS:
            binding[field] = copy.deepcopy(record[field])
        binding["dependency_id"] = record["upstream"]["project"]
        binding["primary_renderer"] = "Remotion"
        # Contract fixture only; this does not attest a runnable Remotion adapter.
        binding["entrypoint"] = "fixtures/render-remotion.mjs"
        binding["invocation_record"]["argv"] = ["node", binding["entrypoint"]]
        binding["invocation_record"]["template_request"] = {
            "semantic_family": "bar_chart", "information_units": 3,
            "numeric_values": [2, 5, 9], "numeric_scale": "linear",
        }
        return _visual_strategy([component]), context, record

    def local_registered_record(self):
        record = copy.deepcopy(json.loads(
            (ROUTER_PATH.parents[1] / "references/verified-template-registry.json")
            .read_text(encoding="utf-8")
        )["templates"][0])
        record["template_origin"] = "verified_local_canonical"
        record["template_id"] = "local/viewpoint-comparison"
        record["adaptation_level"] = "structural"
        record["upstream"] = {
            "project": "hd-talking-head-local-canonical",
            "repository": ".",
            "commit": "local-canonical-v1",
        }
        record["render_contract"]["engine"] = "Remotion"
        return record

    def test_forged_verifier_record_is_not_a_trusted_candidate(self) -> None:
        _, _, record = self.registered_context()
        record["capacity"]["max_units"] = 999
        with self.assertRaisesRegex(self.router.RouterError, "registered"):
            self.router.candidate_from_verified_template_record(
                record, semantic_match_score=1, quality_score=1, reuse_gap=0)

    def test_registered_remotion_template_compiles_with_actual_engine(self) -> None:
        strategy, context, _ = self.registered_context()
        recipe = self.router.compile_strategy(strategy, context)
        self.assertEqual(recipe["components"][0]["primary_renderer"], "Remotion")
        self.assertEqual(recipe["components"][0]["executor"], "reference_adapter")

    def test_registered_template_cannot_claim_wrong_engine_or_forged_capacity(self) -> None:
        for change in ("engine", "capacity"):
            with self.subTest(change=change):
                strategy, context, _ = self.registered_context()
                binding = context["bindings"]["code"]
                if change == "engine":
                    binding["primary_renderer"] = "HyperFrames"
                else:
                    binding["capacity"]["max_units"] = 999
                with self.assertRaises(self.router.RouterError):
                    self.router.compile_strategy(strategy, context)

    def test_qualification_snapshot_is_explicit_and_does_not_become_production_registry(self) -> None:
        relative = (
            "assets/verified-templates/hyperframes/notification-cascade/execution-v2/"
            "qualification/source-registry.json"
        )
        path = ROUTER_PATH.parents[1] / relative
        candidate = json.loads(path.read_text(encoding="utf-8"))["templates"][0]
        binding = {field: copy.deepcopy(candidate[field]) for field in self.router._TEMPLATE_PROVENANCE_FIELDS}
        binding.update({
            "dependency_id": "hyperframes",
            "primary_renderer": "HyperFrames",
            "entrypoint": "scripts/render_hyperframes_notification.cjs",
            "invocation_record": {
                "argv": ["node", "scripts/render_hyperframes_notification.cjs"],
                "template_request": {
                    "semantic_family": "progress_sequence",
                    "information_units": 4,
                    "numeric_values": [],
                    "numeric_scale": "not_applicable",
                },
            },
        })
        qualification = {
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

        with self.assertRaises(self.router.RouterError):
            self.router.validate_template_binding(binding)
        self.router.validate_template_binding(binding, qualification_registry=qualification)

    def test_frozen_content_rechecks_semantics_capacity_and_numeric_precision(self) -> None:
        invalid = [
            {"semantic_family": "timeline"},
            {"information_units": 9},
            {"numeric_values": [1.5, 3, 9]},
            {"numeric_values": [-1, 3, 9]},
            {"numeric_values": [1, 3, 50]},
            {"numeric_values": [float("nan"), 3, 9]},
            {"numeric_values": [True, 3, 9]},
            {"numeric_values": [2, 9]},
            {"numeric_scale": "log"},
        ]
        for change in invalid:
            with self.subTest(change=change):
                strategy, context, _ = self.registered_context()
                context["bindings"]["code"]["invocation_record"]["template_request"].update(change)
                with self.assertRaises(self.router.RouterError):
                    self.router.compile_strategy(strategy, context)

    def test_missing_current_content_requires_explicit_rebinding(self) -> None:
        strategy, context, _ = self.registered_context()
        del context["bindings"]["code"]["invocation_record"]["template_request"]
        with self.assertRaisesRegex(self.router.RouterError, "template_request"):
            self.router.compile_strategy(strategy, context)

    def test_public_surface_exposes_exact_five_equal_source_kinds(self) -> None:
        self.assertEqual(tuple(self.router.SOURCE_KINDS), SOURCE_KINDS)
        for name in (
            "freeze_candidate",
            "validate_strategy",
            "validate_invocation_evidence",
            "compile_strategy",
        ):
            self.assertTrue(callable(getattr(self.router, name)))

    def test_registry_preserves_exact_lazy_capabilities_and_heavy_limit(self) -> None:
        self.assertEqual(
            set(self.router.CAPABILITY_REGISTRY),
            {
                "html-video",
                "erduo-broll-loop-engineering",
                "video-use",
                "video-autopilot-kit",
                "HyperFrames",
                "Remotion",
                "OpenMontage",
                "Generative-Media-Skills",
                "Open-Generative-AI",
            },
        )
        self.assertTrue(
            all(item["load"] == "lazy" for item in self.router.CAPABILITY_REGISTRY.values())
        )
        self.assertEqual(self.router.HEAVY_CONCURRENCY, 1)
        self.assertIn("fact", self.router.FAMILY_CANDIDATES)
        self.assertIn("process", self.router.FAMILY_CANDIDATES)
        self.assertIn("evidence", self.router.ENTRY_CANDIDATES)

    def test_semantic_match_precedes_template_qualification(self) -> None:
        ranked = self.router.rank_code_templates(
            [
                _native_template_candidate(semantic_match_score=1.0),
                _template_candidate(
                    "local",
                    "verified_local_canonical",
                    semantic_match_score=1.0,
                    semantic_families=["screen_sequence"],
                ),
                _template_candidate("third-party", "verified_third_party",
                                    semantic_families=["screen_sequence"]),
            ],
            semantic_family="screen_sequence",
            information_units=5,
        )
        self.assertEqual(ranked[0]["template_id"], "hyperframes-screen-flow-carousel-portrait-adaptation")
        self.assertNotIn("local", [item["template_id"] for item in ranked])

    def test_retired_local_and_unregistered_custom_cannot_replace_ineligible_native(self) -> None:
        with self.assertRaisesRegex(self.router.RouterError, "no eligible"):
            self.router.rank_code_templates(
                [
                    _template_candidate(
                        "third-party", "verified_third_party",
                        semantic_families=["timeline"],
                    ),
                    _template_candidate("custom", "custom_fallback"),
                    _template_candidate("local", "verified_local_canonical"),
                ],
                semantic_family="comparison",
                information_units=5,
            )

    def test_registered_local_record_validates_history_but_cannot_enter_new_production(self) -> None:
        record = self.local_registered_record()
        with mock.patch.object(self.router, "_registered_template", return_value=record):
            candidate = self.router.candidate_from_verified_template_record(
                record, semantic_match_score=.95, quality_score=.93, reuse_gap=9,
            )
            with self.assertRaisesRegex(self.router.RouterError, "no eligible"):
                self.router.rank_code_templates(
                    [candidate], semantic_family="bar_chart", information_units=3,
                )
            binding = {
                **{field: copy.deepcopy(record[field])
                   for field in self.router._TEMPLATE_PROVENANCE_FIELDS},
                "dependency_id": "hd-talking-head-local-canonical",
                "primary_renderer": "Remotion",
                "entrypoint": record["source_entrypoint"],
                "invocation_record": {
                    "argv": ["node", record["source_entrypoint"]],
                    "template_request": {
                        "semantic_family": "bar_chart",
                        "information_units": 3,
                        "numeric_values": [],
                        "numeric_scale": "not_applicable",
                    },
                },
            }
            self.router.validate_template_binding(binding)
            component = _strategy_component("code", "code_generated")
            context = _compile_context([component], binding_overrides={"code": binding})
            context.pop("template_candidates")
            with self.assertRaisesRegex(self.router.RouterError, "new production requires a native"):
                self.router.compile_strategy(_visual_strategy([component]), context)

    def test_local_registered_identity_cannot_be_forged(self) -> None:
        registered = self.local_registered_record()
        for field, value in (
            ("template_origin", "verified_third_party"),
            ("source_sha256", "0" * 64),
            ("verification_id", "1" * 64),
        ):
            forged = copy.deepcopy(registered)
            forged[field] = value
            with self.subTest(field=field), mock.patch.object(
                self.router, "_registered_template", return_value=registered,
            ), self.assertRaises(self.router.RouterError):
                self.router.candidate_from_verified_template_record(
                    forged, semantic_match_score=1, quality_score=1, reuse_gap=0,
                )

    def test_template_router_rejects_structural_and_capacity_mismatch(self) -> None:
        ranked = self.router.rank_code_templates(
            [
                _template_candidate(
                    "structural",
                    "verified_third_party",
                    adaptation_level="structural",
                    semantic_families=["screen_sequence"],
                ),
                _template_candidate(
                    "too-small",
                    "verified_third_party",
                    capacity={"min_units": 1, "max_units": 2},
                    semantic_families=["screen_sequence"],
                ),
                _native_template_candidate(),
            ],
            semantic_family="screen_sequence",
            information_units=5,
        )
        self.assertEqual([item["template_id"] for item in ranked],
                         ["hyperframes-screen-flow-carousel-portrait-adaptation"])

    def test_template_router_is_input_order_independent(self) -> None:
        candidates = [
            _template_candidate("zeta", "verified_third_party"),
            _template_candidate("alpha", "verified_third_party"),
        ]
        first = self.router.rank_code_templates(
            candidates,
            semantic_family="comparison",
            information_units=5,
        )
        second = self.router.rank_code_templates(
            list(reversed(candidates)),
            semantic_family="comparison",
            information_units=5,
        )
        self.assertEqual(first, second)
        self.assertEqual(first[0]["template_id"], "alpha")

    def test_unused_template_does_not_override_semantic_eligibility(self) -> None:
        ranked = self.router.rank_code_templates([
            _native_template_candidate(template_id="hyperframes-beat-timeline-portrait-adaptation",
                                       semantic_families=["timeline"], reuse_gap=999),
            _native_template_candidate(reuse_gap=0),
        ], semantic_family="screen_sequence", information_units=5)
        self.assertEqual([value["template_id"] for value in ranked],
                         ["hyperframes-screen-flow-carousel-portrait-adaptation"])

    def test_verified_registry_record_can_enter_template_router(self) -> None:
        registry_path = ROUTER_PATH.parents[1] / "references/verified-template-registry.json"
        record = json.loads(registry_path.read_text(encoding="utf-8"))["templates"][0]

        candidate = self.router.candidate_from_verified_template_record(
            record,
            semantic_match_score=0.94,
            quality_score=0.92,
            reuse_gap=15,
        )
        ranked = self.router.rank_code_templates(
            [candidate], semantic_family="bar_chart", information_units=5
        )

        self.assertEqual(ranked[0]["template_id"], "html-video/frame-data-rollup")
        self.assertEqual(ranked[0]["template_origin"], "verified_third_party")

    def test_retired_chatgpt_exchange_cannot_reenter_from_historical_qualification(self) -> None:
        registry_path = ROUTER_PATH.parents[1] / "references/verified-template-registry.json"
        records = {
            item["template_id"]: item
            for item in json.loads(registry_path.read_text(encoding="utf-8"))["templates"]
        }
        self.assertNotIn("hyperframes/chatgpt-exchange", records)
        historical_path = ROUTER_PATH.parents[1] / (
            "assets/verified-templates/hyperframes/chatgpt-exchange/"
            "execution-v2/qualification/source-registry.json"
        )
        historical = json.loads(historical_path.read_text(encoding="utf-8"))["templates"][0]
        self.assertEqual(historical["template_id"], "hyperframes/chatgpt-exchange")
        with self.assertRaisesRegex(self.router.RouterError, "registered"):
            self.router.candidate_from_verified_template_record(
                historical, semantic_match_score=0.96, quality_score=0.94, reuse_gap=20,
            )

    def test_template_router_rejects_invalid_contract_fields(self) -> None:
        invalid_candidates = {
            "unknown origin": _template_candidate("bad", "unverified_external"),
            "bad hash": _template_candidate(
                "bad",
                "verified_third_party",
                source_sha256="NOT-A-SHA256",
            ),
            "boolean score": _template_candidate(
                "bad",
                "verified_third_party",
                quality_score=True,
            ),
            "additional field": _template_candidate(
                "bad",
                "verified_third_party",
                unexpected=True,
            ),
        }
        for label, candidate in invalid_candidates.items():
            with self.subTest(label=label), self.assertRaises(self.router.RouterError):
                self.router.rank_code_templates(
                    [candidate],
                    semantic_family="comparison",
                    information_units=5,
                )

    def test_compile_code_component_freezes_verified_template_provenance(self) -> None:
        strategy, context, record = self.registered_context()
        candidate = self.router.candidate_from_verified_template_record(
            record, semantic_match_score=.94, quality_score=.92, reuse_gap=15)
        for field in self.router._TEMPLATE_PROVENANCE_FIELDS:
            context["bindings"]["code"].pop(field)
        context["template_candidates"] = {"code": {
            "semantic_family": "bar_chart", "information_units": 3,
            "candidates": [candidate, _template_candidate(
                "custom", "custom_fallback", semantic_families=["bar_chart"],
                semantic_match_score=.94)],
        }}
        recipe = self.router.compile_strategy(strategy, context)
        compiled = recipe["components"][0]
        self.assertEqual(compiled["template_id"], record["template_id"])
        self.assertEqual(compiled["template_origin"], "verified_third_party")
        self.assertNotIn("semantic_match_score", compiled)
        self.assertNotIn("quality_score", compiled)
        self.assertNotIn("reuse_gap", compiled)

    def test_compile_rejects_missing_or_unapproved_template_candidates(self) -> None:
        component = _strategy_component("code", "code_generated")
        missing = _compile_context([component])
        missing["template_candidates"] = {}
        with self.assertRaises(self.router.RouterError):
            self.router.compile_strategy(_visual_strategy([component]), missing)

        unapproved = _compile_context([component])
        unapproved["template_candidates"]["foreign"] = {
            "semantic_family": "comparison",
            "information_units": 5,
            "candidates": [_template_candidate("foreign", "verified_third_party")],
        }
        with self.assertRaisesRegex(self.router.RouterError, "unapproved"):
            self.router.compile_strategy(_visual_strategy([component]), unapproved)

    def test_validate_strategy_delegates_to_canonical_authority(self) -> None:
        intent = _visual_intent()
        strategy = _visual_strategy([_strategy_component("code", "code_generated")])
        validated = self.router.validate_strategy(intent, strategy)
        self.assertEqual(validated, strategy)
        self.assertIsNot(validated, strategy)

        invalid = copy.deepcopy(strategy)
        invalid["unexpected"] = True
        with self.assertRaises(self.router.RouterError):
            self.router.validate_strategy(intent, invalid)

    def test_validate_strategy_rejects_mismatched_intent(self) -> None:
        strategy = _visual_strategy(
            [_strategy_component("local", "local_material")],
            segment_id="other-segment",
        )
        with self.assertRaises(self.router.RouterError):
            self.router.validate_strategy(_visual_intent(), strategy)

    def test_freeze_candidate_accepts_every_kind(self) -> None:
        for kind in SOURCE_KINDS:
            with self.subTest(kind=kind):
                selected = self.router.freeze_candidate(kind, [_candidate(f"asset-{kind}", kind)])
                self.assertEqual(selected["kind"], kind)

    def test_freeze_candidate_uses_hard_gates_and_stable_same_kind_sorting(self) -> None:
        candidates = [
            _candidate("zeta", "external_stock", semantic_score=0.9, quality_score=0.8),
            _candidate("alpha", "external_stock", semantic_score=0.9, quality_score=0.8),
            _candidate(
                "failed",
                "external_stock",
                semantic_score=1.0,
                quality_score=1.0,
                failed_gate="factual_reliability",
            ),
        ]
        self.assertEqual(
            self.router.freeze_candidate("external_stock", candidates)["asset_id"],
            "alpha",
        )

    def test_freeze_candidate_rejects_cross_kind_unknown_and_legacy(self) -> None:
        with self.assertRaises(self.router.RouterError):
            self.router.freeze_candidate(
                "local_material",
                [_candidate("local", "local_material"), _candidate("ai", "ai_generated")],
            )
        for kind in ("unknown", *LEGACY_SOURCE_KINDS):
            with self.subTest(kind=kind), self.assertRaises(self.router.RouterError):
                self.router.freeze_candidate(kind, [])

    def test_every_approved_kind_compiles_without_cross_kind_priority(self) -> None:
        for kind in SOURCE_KINDS:
            with self.subTest(kind=kind):
                component = _strategy_component("only", kind)
                recipe = self.router.compile_strategy(
                    _visual_strategy([component]),
                    _compile_context([component]),
                )
                self.assertEqual(recipe["components"][0]["kind"], kind)
                self.assertNotIn("status", recipe)
                self.assertNotIn("selected_source", recipe)

    def test_hybrid_compilation_is_deterministic_with_one_ffmpeg_compositor(self) -> None:
        components = [
            _strategy_component("local", "local_material", layout_slot="main"),
            _strategy_component("code", "code_generated", layout_slot="lower-third"),
            _strategy_component("stock", "external_stock", layout_slot="inset"),
            _strategy_component("ai", "ai_generated", layout_slot="background"),
        ]
        strategy = _visual_strategy(components)
        strategy["composition"]["avatar"] = avatar_fixture(frames=72)
        context = _compile_context(components)
        first = self.router.compile_strategy(strategy, context)
        second = self.router.compile_strategy(strategy, context)
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 2)
        self.assertEqual(first["final_compositor"], "ffmpeg")
        self.assertEqual(first["mode"], "hybrid")
        self.assertEqual(first["composition"], strategy["composition"])
        self.assertEqual(
            [component["layer_role"] for component in first["components"]],
            [component["layer_role"] for component in components],
        )
        self.assertEqual(
            [component["render_window"]["z_index"] for component in first["components"]],
            [0, 10, 20, 30],
        )
        self.assertEqual(
            [component["render_window"]["layout_slot"] for component in first["components"]],
            ["main", "lower-third", "inset", "background"],
        )
        artifacts = tuple(
            broll_component_executor.ComponentArtifact(
                schema_version=1,
                status="success",
                job_id="job-router",
                segment_id="seg-router",
                component_id=component["component_id"],
                kind=component["kind"],
                strategy_revision=1,
                media_type="image",
                render_window=component["render_window"],
                z_index=component["render_window"]["z_index"],
                layout_slot=component["render_window"]["layout_slot"],
                opacity=component["render_window"]["opacity"],
                safe_zone=component["render_window"]["safe_zone"],
                artifact_contract=component["artifact_contract"],
                source_media_type=component["media_type"],
                artifact_media_type="image",
                media_probe={},
                input_sha256="7" * 64,
                job_path=f"artifacts/{component['component_id']}.png",
                byte_count=1,
                output_sha256="8" * 64,
                invocation_evidence=(
                    {
                        "primary_renderer": component["primary_renderer"],
                        "output_job_path": f"artifacts/{component['component_id']}.png",
                        "output_sha256": "8" * 64,
                    }
                    if component["kind"] == "code_generated"
                    else {
                        "output_job_path": f"artifacts/{component['component_id']}.png",
                        "output_sha256": "8" * 64,
                    }
                ),
                qa={"passed": True},
                error_code=None,
            )
            for component in first["components"]
        )
        checked = broll_systems.validate_composition(first, artifacts)
        self.assertEqual(checked.family, "evidence_with_data_overlay")
        graph = segment_render.build_filter_graph(first, artifacts, frames=72)
        self.assertIn("overlay=768:1400", graph)
        self.assertIn("between(n,0,71)", graph)

    def test_segment_frames_are_required_positive_and_define_every_window(self) -> None:
        component = _strategy_component("official", "official_material")
        strategy = _visual_strategy([component])
        for frames in (72, 120):
            with self.subTest(frames=frames):
                recipe = self.router.compile_strategy(
                    strategy,
                    _compile_context([component], segment_frames=frames),
                )
                window = recipe["components"][0]["render_window"]
                self.assertEqual((window["start_frame"], window["end_frame"]), (0, frames))
        missing = _compile_context([component])
        del missing["segment_frames"]
        with self.assertRaises(self.router.RouterError):
            self.router.compile_strategy(strategy, missing)
        for invalid in (True, 0, -1, 72.0, "72"):
            context = _compile_context([component])
            context["segment_frames"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(
                self.router.RouterError
            ):
                self.router.compile_strategy(strategy, context)

    def test_compiler_rejects_layer_role_and_layout_slot_mismatch(self) -> None:
        component = _strategy_component("base", "official_material")
        component["layout_slot"] = "lower-third"
        with self.assertRaises(self.router.RouterError):
            self.router.compile_strategy(
                _visual_strategy([component]), _compile_context([component])
            )

    def test_compiler_rejects_annotation_without_a_real_base_dependency(self) -> None:
        components = [
            _strategy_component("base-one", "official_material"),
            _strategy_component("base-two", "local_material"),
            _strategy_component("annotation", "code_generated", layout_slot="annotation"),
        ]
        strategy = _visual_strategy(components)
        strategy["composition"]["component_dependencies"] = [
            {"component_id": "annotation", "depends_on": ["base-two"]}
        ]
        recipe = self.router.compile_strategy(strategy, _compile_context(components))
        self.assertEqual(recipe["composition"], strategy["composition"])

        for dependencies in (
            [],
            [{"component_id": "annotation", "depends_on": ["missing"]}],
        ):
            invalid = copy.deepcopy(strategy)
            invalid["composition"]["component_dependencies"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaises(
                self.router.RouterError
            ):
                self.router.compile_strategy(invalid, _compile_context(components))

    def test_compiler_uses_approved_reading_order_for_layers(self) -> None:
        annotation = _strategy_component(
            "annotation", "code_generated", layout_slot="main_overlay"
        )
        annotation["layer_role"] = "annotation"
        base = _strategy_component("base", "official_material")
        components = [annotation, base]
        strategy = _visual_strategy(components)
        strategy["composition"]["reading_order"] = ["base", "annotation"]
        recipe = self.router.compile_strategy(
            strategy, _compile_context(components)
        )
        self.assertEqual(
            [component["component_id"] for component in recipe["components"]],
            ["base", "annotation"],
        )
        self.assertEqual(
            [component["render_window"]["z_index"] for component in recipe["components"]],
            [0, 10],
        )
        artifacts = tuple(
            SimpleNamespace(
                component_id=component["component_id"],
                kind=component["kind"],
                invocation_evidence=(
                    {"primary_renderer": component["primary_renderer"]}
                    if component["kind"] == "code_generated"
                    else {}
                ),
            )
            for component in recipe["components"]
        )
        self.assertEqual(
            broll_systems.validate_composition(recipe, artifacts).component_ids,
            ("base", "annotation"),
        )

        invalid = copy.deepcopy(strategy)
        invalid["composition"]["reading_order"] = ["annotation", "base"]
        with self.assertRaises(self.router.RouterError):
            self.router.compile_strategy(invalid, _compile_context(components))

    def test_candidate_snapshot_rejects_mixed_and_foreign_kinds(self) -> None:
        component = _strategy_component("local", "local_material")
        strategy = _visual_strategy([component])
        base = _compile_context([component])
        for snapshot in (
            [_candidate("local", "local_material"), _candidate("ai", "ai_generated")],
            [_candidate("official", "official_material")],
        ):
            with self.subTest(snapshot=snapshot), self.assertRaises(self.router.RouterError):
                context = copy.deepcopy(base)
                context["candidate_snapshots"]["local"] = snapshot
                self.router.compile_strategy(strategy, context)

    def test_candidate_binding_must_match_frozen_same_kind_asset(self) -> None:
        component = _strategy_component("stock", "external_stock")
        context = _compile_context([component])
        context["bindings"]["stock"]["provider_asset_id"] = "different"
        with self.assertRaisesRegex(self.router.RouterError, "does not match"):
            self.router.compile_strategy(_visual_strategy([component]), context)

    def test_non_generated_kind_requires_candidate_snapshot(self) -> None:
        component = _strategy_component("official", "official_material")
        context = _compile_context([component])
        context["candidate_snapshots"] = {}
        with self.assertRaisesRegex(self.router.RouterError, "snapshot.*missing"):
            self.router.compile_strategy(_visual_strategy([component]), context)

    def test_code_and_ai_single_components_compile_without_candidate_snapshots(self) -> None:
        for kind in ("code_generated", "ai_generated"):
            with self.subTest(kind=kind):
                components = [_strategy_component("only", kind)]
                recipe = self.router.compile_strategy(
                    _visual_strategy(components),
                    _compile_context(components),
                )
                self.assertEqual(recipe["components"][0]["kind"], kind)

    def test_bindings_reject_common_recipe_fields_before_merge(self) -> None:
        common_fields = {
            "schema_version": 2,
            "segment_id": "unexpected-value",
            "strategy_revision": 99,
            "mode": "none",
            "canvas": {},
            "components": [],
            "final_compositor": "unexpected-value",
            "component_id": "unexpected-value",
            "kind": "ai_generated",
            "semantic_role": "mood",
            "layer_role": "overlay",
            "media_type": "video",
            "layout_slot": "unexpected-value",
            "brief": "unexpected-value",
            "executor": "unexpected-value",
            "render_window": {},
            "artifact_contract": {},
            "z_index": 999,
        }
        component = _strategy_component("code", "code_generated")
        for field, value in common_fields.items():
            with self.subTest(field=field):
                binding = _binding("code_generated", "asset-code")
                binding[field] = value
                with self.assertRaisesRegex(self.router.RouterError, "reserved fields"):
                    self.router.compile_strategy(
                        _visual_strategy([component]),
                        _compile_context(
                            [component],
                            binding_overrides={"code": binding},
                        ),
                    )

    def test_authoritative_recipe_validator_rejects_missing_extra_and_cross_kind_binding(self) -> None:
        component = _strategy_component("local", "local_material")
        invalid_bindings = []
        missing = _binding("local_material", "asset-local")
        del missing["sha256"]
        invalid_bindings.append(missing)
        extra = _binding("local_material", "asset-local")
        extra["invented"] = "value"
        invalid_bindings.append(extra)
        invalid_bindings.append(_binding("official_material", "asset-local"))
        for binding in invalid_bindings:
            with self.subTest(binding=binding), self.assertRaises(self.router.RouterError):
                self.router.compile_strategy(
                    _visual_strategy([component]),
                    _compile_context(
                        [component],
                        binding_overrides={"local": binding},
                    ),
                )

    def test_router_does_not_copy_the_five_kind_binding_schema(self) -> None:
        source = ROUTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assigned_names = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("_BINDING_KEYS", assigned_names)
        self.assertNotIn("_RECIPE_BINDING_FIELDS", assigned_names)
        self.assertNotIn("_CODE_BINDING_FIELDS", assigned_names)

    def test_canonical_binding_rejects_execution_only_fields_without_side_effects(self) -> None:
        component = _strategy_component("code", "code_generated")
        execution_fields: dict[str, object] = {
            "producer_command": ["python", "write-sentinel.py"],
            "job_root": "/tmp/job",
            "dependency_root": "/tmp/dependency",
            "output_path": "/tmp/media.mp4",
            "timeout_seconds": 1,
            "staging_output_path": "/tmp/staging.mp4",
        }
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "must-not-exist"
            for field, value in execution_fields.items():
                with self.subTest(field=field):
                    binding = _binding("code_generated", "asset-code")
                    binding[field] = value
                    with self.assertRaises(self.router.RouterError):
                        self.router.compile_strategy(
                            _visual_strategy([component]),
                            _compile_context(
                                [component],
                                binding_overrides={"code": binding},
                            ),
                        )
                    self.assertFalse(sentinel.exists())

    def test_canonical_strategy_rejects_execution_only_fields(self) -> None:
        component = _strategy_component("code", "code_generated")
        for field in ("producer_command", "job_root", "dependency_root", "output_path"):
            with self.subTest(field=field):
                strategy = _visual_strategy([component])
                strategy[field] = "forbidden"
                with self.assertRaises(self.router.RouterError):
                    self.router.compile_strategy(strategy, _compile_context([component]))

    def test_compile_strategy_rejects_flat_strategy_without_side_effects(self) -> None:
        flat = {
            "strategy_id": "obsolete-flat",
            "kind": "code_generated",
            "approval_revision": 1,
            "semantic_reason": "obsolete",
            "primary_renderer": "HyperFrames",
            "producer_command": ["python", "producer.py"],
            "job_root": "/tmp/job",
            "dependency_root": "/tmp/dependency",
            "output_path": "/tmp/output.mp4",
        }
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "sentinel"
            with self.assertRaisesRegex(self.router.RouterError, "canonical|schema_version"):
                self.router.compile_strategy(flat, {"side_effect_path": str(sentinel)})
            self.assertFalse(sentinel.exists())

    def test_validate_invocation_evidence_is_structural_not_provenance_attestation(self) -> None:
        evidence = _binding("code_generated", "asset-code")
        evidence["entrypoint"] = "/definitely/not/present/render.ts"
        evidence["invocation_record"]["argv"] = [
            "node",
            "/definitely/not/present/render.ts",
        ]
        validated = self.router.validate_invocation_evidence(evidence)
        self.assertEqual(validated, evidence)
        self.assertIsNot(validated, evidence)
        self.assertNotIn("status", validated)
        self.assertNotIn("ready", validated)
        self.assertNotIn("provenance_verified", validated)

    def test_candidate_selection_cannot_replace_a_frozen_template(self) -> None:
        component = _strategy_component("code", "code_generated")
        context = _compile_context([component])
        recipe = self.router.compile_strategy(_visual_strategy([component]), context)
        frozen = recipe["components"][0]
        fields = ("template_origin", "template_id", "template_version", "verification_id",
                  "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
                  "semantic_families", "capacity")
        context["bindings"]["code"].update({field: frozen[field] for field in fields})
        context["template_candidates"]["code"]["candidates"][0]["template_id"] = "different-template"
        with self.assertRaisesRegex(self.router.RouterError, "changed a frozen binding"):
            self.router.compile_strategy(_visual_strategy([component]), context)

    def test_no_candidate_and_no_frozen_provenance_is_rejected(self) -> None:
        component = _strategy_component("code", "code_generated")
        context = _compile_context([component])
        context.pop("template_candidates")
        with self.assertRaisesRegex(self.router.RouterError, "requires template candidates or frozen provenance"):
            self.router.compile_strategy(_visual_strategy([component]), context)

    def test_validate_invocation_evidence_rejects_invalid_structure_and_cross_fields(self) -> None:
        cases: list[dict[str, object]] = []
        missing = _binding("code_generated", "asset-code")
        del missing["renderer_version"]
        cases.append(missing)
        extra = _binding("code_generated", "asset-code")
        extra["output_sha256"] = "a" * 64
        cases.append(extra)
        absent_entrypoint = _binding("code_generated", "asset-code")
        absent_entrypoint["invocation_record"]["argv"] = ["node", "decoy.ts"]
        cases.append(absent_entrypoint)
        duplicate_entrypoint = _binding("code_generated", "asset-code")
        duplicate_entrypoint["invocation_record"]["argv"].append(duplicate_entrypoint["entrypoint"])
        cases.append(duplicate_entrypoint)
        bad_exit = _binding("code_generated", "asset-code")
        bad_exit["invocation_record"]["exit_code"] = 1
        cases.append(bad_exit)
        for evidence in cases:
            with self.subTest(evidence=evidence), self.assertRaises(self.router.RouterError):
                self.router.validate_invocation_evidence(evidence)

    def test_dependency_renderer_mapping_is_exact_in_validator_and_compiler(self) -> None:
        pairs = (("html-video", "HyperFrames"), ("doudou-remotion-whiteboard", "Remotion"),
                 ("paper-collage-ad", "PaperCollage"), ("whiteboard-video", "Whiteboard"))
        for dependency_id, renderer in pairs:
            with self.subTest(dependency_id=dependency_id, renderer=renderer):
                evidence = _binding("code_generated", "asset-code")
                evidence["dependency_id"] = dependency_id
                evidence["primary_renderer"] = renderer
                self.assertEqual(self.router.validate_invocation_evidence(evidence), evidence)
                evidence["primary_renderer"] = (
                    "Remotion" if renderer == "HyperFrames" else "HyperFrames"
                )
                with self.assertRaises(self.router.RouterError):
                    self.router.validate_invocation_evidence(evidence)
                component = _strategy_component("code", "code_generated")
                with self.assertRaises(self.router.RouterError):
                    self.router.compile_strategy(
                        _visual_strategy([component]),
                        _compile_context([component], binding_overrides={"code": evidence}),
                    )

    def test_code_binding_requires_structural_invocation_record(self) -> None:
        component = _strategy_component("code", "code_generated")
        binding = _binding("code_generated", "asset-code")
        del binding["invocation_record"]
        with self.assertRaises(self.router.RouterError):
            self.router.compile_strategy(
                _visual_strategy([component]),
                _compile_context([component], binding_overrides={"code": binding}),
            )

    def test_code_recipe_is_vertical_and_uses_one_primary_renderer(self) -> None:
        component = _strategy_component("code", "code_generated")
        recipe = self.router.compile_strategy(
            _visual_strategy([component]),
            _compile_context([component]),
        )
        compiled = recipe["components"][0]
        self.assertEqual(recipe["canvas"], {"width": 1080, "height": 1920, "fps": 24})
        self.assertEqual(compiled["primary_renderer"], "HyperFrames")
        self.assertEqual(compiled["executor"], "reference_adapter")
        self.assertFalse(compiled["artifact_contract"]["alpha"])
        self.assertNotIn("status", recipe)

        self.assertEqual(
            self.router._executor(
                "code_generated",
                {"dependency_id": "hd-talking-head-talkcraft"},
            ),
            "reference_adapter",
        )
        self.router._validate_renderer_binding(
            "hd-talking-head-talkcraft", "Remotion"
        )
        with self.assertRaises(self.router.RouterError):
            self.router._validate_renderer_binding(
                "hd-talking-head-talkcraft", "HyperFrames"
            )

        doudou_binding = _binding("code_generated", "asset-code")
        doudou_binding.update(
            dependency_id="doudou-remotion-whiteboard",
            primary_renderer="Remotion",
            entrypoint="scripts/render_doudou.mjs", producer_version="2.0.0",
            renderer_version="4.0.520",
        )
        doudou_binding["invocation_record"]["argv"] = ["node", doudou_binding["entrypoint"]]
        doudou_binding["invocation_record"]["template_request"]["semantic_family"] = "process_flow"
        doudou_candidate = _template_candidate(
            "doudou-reviewed-scene", "custom_fallback", template_version="2.0.0",
            adaptation_level="structural", source_entrypoint=doudou_binding["entrypoint"],
            source_sha256=hashlib.sha256((ROUTER_PATH.parents[1] / doudou_binding["entrypoint"]).read_bytes()).hexdigest(),
            semantic_families=["process_flow"], capacity={"min_units": 5, "max_units": 5},
        )
        doudou = self.router.compile_strategy(
            _visual_strategy([component]),
            _compile_context(
                [component],
                binding_overrides={"code": doudou_binding},
                template_overrides={"code": {"semantic_family": "process_flow", "information_units": 5,
                                               "candidates": [doudou_candidate]}},
            ),
        )["components"][0]
        self.assertEqual(doudou["executor"], "reference_adapter")
        self.assertEqual(
            self.router._executor("code_generated", {"dependency_id": "hd-talking-head-local-canonical"}),
            "reference_adapter",
        )

    def test_removed_broll_dependencies_cannot_compile(self) -> None:
        component = _strategy_component("code", "code_generated")
        for dependency_id in ("video-shotcraft", "stickman-video-director", "story-to-handdrawn-video",
                              "unregistered-source", None):
            with self.subTest(dependency_id=dependency_id):
                binding = _binding("code_generated", "asset-code")
                binding.update(dependency_id=dependency_id, primary_renderer="Remotion")
                with self.assertRaises(self.router.RouterError):
                    self.router.compile_strategy(
                        _visual_strategy([component]),
                        _compile_context([component], binding_overrides={"code": binding}),
                    )

    def test_exact_grok_model_uses_openmontage_direct_adapter(self) -> None:
        component = _strategy_component("ai", "ai_generated")
        recipe = self.router.compile_strategy(
            _visual_strategy([component]),
            _compile_context([component]),
        )
        compiled = recipe["components"][0]
        self.assertEqual(compiled["model"], "grok-imagine-video")
        self.assertEqual(compiled["executor"], "OpenMontage:GrokVideo")

    def test_cli_writes_reproducible_canonical_recipe(self) -> None:
        component = _strategy_component("official", "official_material")
        strategy = _visual_strategy([component])
        context = _compile_context([component])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intent_path = root / "intent.json"
            strategy_path = root / "strategy.json"
            snapshots_path = root / "snapshots.json"
            bindings_path = root / "bindings.json"
            first_output = root / "first.json"
            second_output = root / "second.json"
            _write_json(intent_path, context["intent"])
            _write_json(strategy_path, strategy)
            _write_json(snapshots_path, context["candidate_snapshots"])
            _write_json(bindings_path, context["bindings"])
            argv = [
                "--intent", str(intent_path),
                "--strategy", str(strategy_path),
                "--candidate-snapshots", str(snapshots_path),
                "--bindings", str(bindings_path),
                "--segment-frames", str(context["segment_frames"]),
            ]
            self.assertEqual(self.router.main([*argv, "--output", str(first_output)]), 0)
            self.assertEqual(self.router.main([*argv, "--output", str(second_output)]), 0)
            self.assertEqual(first_output.read_bytes(), second_output.read_bytes())
            compiled = json.loads(first_output.read_text())
            self.assertEqual(compiled["schema_version"], 2)
            self.assertEqual(compiled["components"][0]["render_window"]["end_frame"], 72)
            missing_frames_output = root / "missing-frames.json"
            without_frames = argv[:-2]
            with redirect_stderr(StringIO()):
                self.assertNotEqual(
                    self.router.main(
                        [*without_frames, "--output", str(missing_frames_output)]
                    ),
                    0,
                )
            self.assertFalse(missing_frames_output.exists())

    def test_cli_reports_output_io_failure_without_overwrite_or_temp_residue(self) -> None:
        component = _strategy_component("official", "official_material")
        strategy = _visual_strategy([component])
        context = _compile_context([component])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intent_path = root / "intent.json"
            strategy_path = root / "strategy.json"
            snapshots_path = root / "snapshots.json"
            bindings_path = root / "bindings.json"
            output = root / "recipe.json"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            _write_json(intent_path, context["intent"])
            _write_json(strategy_path, strategy)
            _write_json(snapshots_path, context["candidate_snapshots"])
            _write_json(bindings_path, context["bindings"])
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = self.router.main(
                    [
                        "--intent", str(intent_path),
                        "--strategy", str(strategy_path),
                        "--candidate-snapshots", str(snapshots_path),
                        "--bindings", str(bindings_path),
                        "--segment-frames", str(context["segment_frames"]),
                        "--output", str(output),
                    ]
                )
            self.assertNotEqual(result, 0)
            self.assertEqual(stderr.getvalue().strip(), "output I/O failure")
            self.assertTrue(output.is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(root.glob(".recipe.json.*.tmp")), [])

    def test_cli_rejects_flat_unknown_and_missing_schema_without_output(self) -> None:
        invalid_strategies = [
            {
                "strategy_id": "flat",
                "kind": "code_generated",
                "producer_command": ["python", "producer.py"],
            },
            {"schema_version": 9, "components": []},
            {"components": []},
        ]
        for invalid in invalid_strategies:
            with self.subTest(strategy=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                intent_path = root / "intent.json"
                strategy_path = root / "strategy.json"
                snapshots_path = root / "snapshots.json"
                bindings_path = root / "bindings.json"
                output = root / "recipe.json"
                _write_json(intent_path, _visual_intent())
                _write_json(strategy_path, invalid)
                _write_json(snapshots_path, {})
                _write_json(bindings_path, {})
                stderr = StringIO()
                with redirect_stderr(stderr):
                    result = self.router.main(
                        [
                            "--intent", str(intent_path),
                            "--strategy", str(strategy_path),
                            "--candidate-snapshots", str(snapshots_path),
                            "--bindings", str(bindings_path),
                            "--segment-frames", "72",
                            "--output", str(output),
                        ]
                    )
                self.assertNotEqual(result, 0)
                self.assertFalse(output.exists())
                self.assertTrue(stderr.getvalue())

    def test_cli_rejects_execution_only_binding_without_media_or_recipe_output(self) -> None:
        component = _strategy_component("code", "code_generated")
        strategy = _visual_strategy([component])
        context = _compile_context([component])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_output = root / "media.mp4"
            context["bindings"]["code"]["producer_command"] = ["python", "producer.py"]
            context["bindings"]["code"]["output_path"] = str(media_output)
            paths = {
                "intent": root / "intent.json",
                "strategy": root / "strategy.json",
                "candidate-snapshots": root / "snapshots.json",
                "bindings": root / "bindings.json",
                "output": root / "recipe.json",
            }
            _write_json(paths["intent"], context["intent"])
            _write_json(paths["strategy"], strategy)
            _write_json(paths["candidate-snapshots"], context["candidate_snapshots"])
            _write_json(paths["bindings"], context["bindings"])
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = self.router.main(
                    [
                        *[
                            item
                            for key, path in paths.items()
                            for item in (f"--{key}", str(path))
                        ],
                        "--segment-frames",
                        str(context["segment_frames"]),
                    ]
                )
            self.assertNotEqual(result, 0)
            self.assertFalse(paths["output"].exists())
            self.assertFalse(media_output.exists())

    def test_cli_invalid_input_does_not_replace_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "recipe.json"
            output.write_text("keep", encoding="utf-8")
            missing = root / "missing.json"
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = self.router.main(
                    [
                        "--intent", str(missing),
                        "--strategy", str(missing),
                        "--candidate-snapshots", str(missing),
                        "--bindings", str(missing),
                        "--segment-frames", "72",
                        "--output", str(output),
                    ]
                )
            self.assertNotEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_router_has_no_flat_or_executor_implementation(self) -> None:
        source = ROUTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"subprocess", "signal", "stat"}.isdisjoint(imports))
        self.assertTrue(
            {
                "route_shot",
                "resolve_capability_paths",
                "_compile_flat_strategy",
                "_invoke_code_dependency",
                "_run_in_process_group",
                "_private_staging_path",
            }.isdisjoint(functions)
        )
        for forbidden in (
            "SOURCE_PRIORITY",
            "def select_source",
            "固定来源优先级",
            "用户资料优先于官方",
            "producer_command",
            "job_root",
            "dependency_root",
            "staging_output_path",
            "Popen(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

"""Contracts for approved B-roll composition families."""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from edit.hd.tools import broll_systems, visual_strategy


KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)


def _component(
    component_id: str,
    kind: str,
    *,
    slot: str = "full_frame",
    z_index: int = 0,
    primary_renderer: str = "HyperFrames",
) -> dict[str, object]:
    value: dict[str, object] = {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": (
            "annotation"
            if slot in {"annotation", "lower-third"}
            else "overlay"
            if slot in {"overlay", "main_overlay"}
            else "inset"
            if slot == "inset"
            else "base"
        ),
        "executor": f"approved:{kind}",
        "media_type": "animation" if kind == "code_generated" else "image",
        "render_window": {
            "start_frame": 0,
            "end_frame": 48,
            "z_index": z_index,
            "layout_slot": slot,
            "opacity": 1.0,
            "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
        },
        "artifact_contract": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "alpha": slot == "annotation",
        },
    }
    bindings: dict[str, dict[str, object]] = {
        "local_material": {
            "material_id": component_id,
            "job_path": f"source/{component_id}.png",
            "sha256": "1" * 64,
        },
        "official_material": {
            "source_id": component_id,
            "publisher": "Example Institute",
            "source_url": "https://example.org/report",
            "snapshot_path": f"source/{component_id}.png",
            "fetched_at": "2026-08-31T12:00:00+08:00",
            "sha256": "2" * 64,
        },
        "external_stock": {
            "provider": "Example Stock",
            "provider_asset_id": component_id,
            "author": "Example Author",
            "asset_page": "https://example.org/stock",
            "job_path": f"source/{component_id}.png",
            "license_snapshot": f"source/{component_id}.json",
            "downloaded_at": "2026-08-31T12:00:00+08:00",
            "sha256": "3" * 64,
        },
        "code_generated": {
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "render.py",
            "producer_version": "approved-version",
            "brief_sha256": "4" * 64,
            "invocation_record": {"argv": ["python3", "render.py"], "exit_code": 0},
            "primary_renderer": primary_renderer,
            "renderer_version": "approved-renderer",
            "template_origin": "verified_third_party",
            "template_id": "hyperframes-vignelli",
            "template_version": "version-1",
            "verification_id": "4" * 64,
            "adaptation_level": "content_reflow",
            "source_entrypoint": "registry/examples/vignelli/index.html",
            "source_sha256": "4" * 64,
            "sample_sha256": "4" * 64,
            "semantic_families": ["comparison", "thesis"],
            "capacity": {"min_units": 3, "max_units": 7},
        },
        "ai_generated": {
            "provider": "Example AI",
            "model": "image-model-v1",
            "endpoint_id": "image-generation",
            "prompt_sha256": "5" * 64,
            "generation_id": component_id,
            "sha256": "6" * 64,
        },
    }
    value.update(bindings[kind])
    return value


def _recipe(components: list[dict[str, object]]) -> dict[str, object]:
    base_ids = [
        str(component["component_id"])
        for component in components
        if component["layer_role"] == "base"
    ]
    recipe = {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 1,
        "mode": "single" if len(components) == 1 else "hybrid",
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
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }
    return visual_strategy.validate_shot_recipe_v2(recipe)


def _artifact(
    component: dict[str, object],
    *,
    evidence_renderer: str | None = None,
    receipt_renderer: str | None = None,
) -> SimpleNamespace:
    evidence: dict[str, object] = {}
    if evidence_renderer is not None:
        evidence["primary_renderer"] = evidence_renderer
    if receipt_renderer is not None:
        evidence["receipt"] = {"primary_renderer": receipt_renderer}
    return SimpleNamespace(
        component_id=component["component_id"],
        kind=component["kind"],
        invocation_evidence=evidence,
    )


class BrollSystemTests(unittest.TestCase):
    def test_aroll_overlay_accepts_alpha_code_without_base_dependency(self) -> None:
        component = _component("overlay", "code_generated", slot="annotation", z_index=10)
        recipe = {
            "schema_version": 2, "segment_id": "seg-001", "strategy_revision": 1,
            "mode": "none",
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "components": [component], "final_compositor": "ffmpeg",
            "composition": {
            "family": "aroll_with_overlay",
            "presenter_mode": "full_frame",
            "reading_order": ["overlay"],
            "component_dependencies": [],
            },
        }
        checked = broll_systems.validate_composition(
            recipe, (_artifact(component, evidence_renderer="HyperFrames"),)
        )
        self.assertEqual(checked.family, "aroll_with_overlay")
        self.assertEqual(checked.base_component_ids, ())

    def test_aroll_overlay_rejects_opaque_and_dependency_artifacts(self) -> None:
        component = _component("overlay", "code_generated", slot="annotation", z_index=10)
        recipe = {
            "schema_version": 2, "segment_id": "seg-001", "strategy_revision": 1,
            "mode": "none",
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "components": [component], "final_compositor": "ffmpeg",
            "composition": {
            "family": "aroll_with_overlay",
            "presenter_mode": "full_frame",
            "reading_order": ["overlay"],
            "component_dependencies": [],
            },
        }
        component["artifact_contract"]["alpha"] = False
        with self.assertRaises(broll_systems.BrollSystemError):
            broll_systems.validate_composition(
                recipe, (_artifact(component, evidence_renderer="HyperFrames"),)
            )

    def test_five_kinds_share_the_same_single_family(self) -> None:
        for kind in KINDS:
            with self.subTest(kind=kind, family="single_full_frame"):
                component = _component("primary", kind)
                checked = broll_systems.validate_composition(
                    _recipe([component]),
                    (
                        _artifact(
                            component,
                            evidence_renderer=(
                                "HyperFrames" if kind == "code_generated" else None
                            ),
                        ),
                    ),
                )
                self.assertEqual(checked.family, "single_full_frame")

    def test_code_annotation_hybrid_uses_a_bound_real_material_base(self) -> None:
        for kind in ("local_material", "official_material", "external_stock"):
            with self.subTest(kind=kind):
                base = _component("base", kind)
                annotation = _component(
                    "annotation", "code_generated", slot="annotation", z_index=10
                )
                checked = broll_systems.validate_composition(
                    _recipe([base, annotation]),
                    (
                        _artifact(base),
                        _artifact(annotation, evidence_renderer="HyperFrames"),
                    ),
                )
                self.assertEqual(checked.family, "evidence_with_data_overlay")

        for kind in ("code_generated", "ai_generated"):
            with self.subTest(non_material_base=kind):
                base = _component("base", kind)
                annotation = _component(
                    "annotation", "code_generated", slot="annotation", z_index=10
                )
                with self.assertRaises((visual_strategy.VisualStrategyError, broll_systems.BrollSystemError)):
                    broll_systems.validate_composition(
                        _recipe([base, annotation]),
                        (
                            _artifact(
                                base,
                                evidence_renderer=(
                                    "HyperFrames" if kind == "code_generated" else None
                                ),
                            ),
                            _artifact(annotation, evidence_renderer="HyperFrames"),
                        ),
                    )

    def test_annotation_window_is_contained_by_every_bound_base_window(self) -> None:
        first = _component("first", "official_material")
        second = _component("second", "local_material")
        annotation = _component(
            "annotation", "code_generated", slot="annotation", z_index=10
        )
        recipe = _recipe([first, second, annotation])
        recipe["components"][0]["render_window"]["end_frame"] = 24
        recipe["composition"]["component_dependencies"][0]["depends_on"] = [
            "first",
            "second",
        ]
        with self.assertRaises(broll_systems.BrollSystemError):
            broll_systems.validate_composition(
                recipe,
                (
                    _artifact(first),
                    _artifact(second),
                    _artifact(annotation, evidence_renderer="HyperFrames"),
                ),
            )

    def test_family_depends_on_approved_mode_and_layout_not_kind(self) -> None:
        base = _component("base", "external_stock")
        annotation = _component(
            "annotation", "code_generated", slot="annotation", z_index=20
        )
        invalid_cases = []
        no_dependency = _recipe([base, annotation])
        no_dependency["composition"]["component_dependencies"] = []
        invalid_cases.append(
            (no_dependency, (_artifact(base), _artifact(annotation, evidence_renderer="HyperFrames")))
        )
        wrong_role = _recipe([base, annotation])
        wrong_role["composition"]["component_dependencies"][0]["depends_on"] = ["annotation"]
        invalid_cases.append(
            (wrong_role, (_artifact(base), _artifact(annotation, evidence_renderer="HyperFrames")))
        )
        hidden_annotation = _recipe([base, annotation])
        hidden_annotation["components"][1]["render_window"]["z_index"] = 0
        invalid_cases.append(
            (
                hidden_annotation,
                (_artifact(base), _artifact(annotation, evidence_renderer="HyperFrames")),
            )
        )
        for recipe, artifacts in invalid_cases:
            with self.subTest(composition=recipe["composition"]):
                with self.assertRaises(broll_systems.BrollSystemError):
                    broll_systems.validate_composition(recipe, artifacts)

    def test_ffmpeg_is_the_only_final_compositor(self) -> None:
        component = _component("primary", "local_material")
        recipe = _recipe([component])
        recipe["final_compositor"] = "another-compositor"
        with self.assertRaises(broll_systems.BrollSystemError):
            broll_systems.validate_composition(
                recipe, (_artifact(component),)
            )

    def test_code_component_has_one_matching_primary_renderer(self) -> None:
        component = _component("annotation", "code_generated")
        valid = _artifact(component, evidence_renderer="HyperFrames")
        broll_systems.validate_composition(
            _recipe([component]), (valid,)
        )

        invalid = (
            _artifact(component),
            _artifact(component, evidence_renderer="Remotion"),
            _artifact(
                component,
                evidence_renderer="HyperFrames",
                receipt_renderer="Remotion",
            ),
        )
        for artifact in invalid:
            with self.subTest(evidence=artifact.invocation_evidence):
                with self.assertRaises(broll_systems.BrollSystemError):
                    broll_systems.validate_composition(
                        _recipe([component]), (artifact,)
                    )

    def test_unknown_component_kind_is_rejected(self) -> None:
        component = _component("primary", "local_material")
        recipe = _recipe([component])
        recipe["components"][0]["kind"] = "unapproved_kind"
        artifact = _artifact(component)
        artifact.kind = "unapproved_kind"
        with self.assertRaises(broll_systems.BrollSystemError):
            broll_systems.validate_composition(recipe, (artifact,))

    def test_component_failure_actions_do_not_change_kind(self) -> None:
        self.assertEqual(
            broll_systems.COMPONENT_FAILURE_ACTIONS,
            ("retry_same_strategy", "replan_visual_direction"),
        )
        source = inspect.getsource(broll_systems)
        self.assertNotIn("select_system", source)
        self.assertNotIn("route_segments", source)
        self.assertNotIn("SOURCE_PRIORITY", source)
        self.assertNotIn("fallback", source.lower())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Validate canonical visual strategies and compile deterministic ShotRecipe v2."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from edit.hd.tools.visual_strategy import (
    SOURCE_KINDS,
    VisualStrategyError,
    stable_same_kind_candidates,
    validate_shot_recipe_v2,
    validate_visual_intent,
    validate_visual_strategy,
)


HEAVY_CONCURRENCY = 1
_TEMPLATE_PROVENANCE_FIELDS = frozenset(
    {
        "template_origin",
        "template_id",
        "template_version",
        "verification_id",
        "adaptation_level",
        "source_entrypoint",
        "source_sha256",
        "sample_sha256",
        "semantic_families",
        "capacity",
    }
)
_TEMPLATE_RANKING_FIELDS = frozenset(
    {"semantic_match_score", "quality_score", "reuse_gap"}
)
_RESERVED_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "segment_id",
        "strategy_revision",
        "mode",
        "canvas",
        "components",
        "final_compositor",
        "component_id",
        "kind",
        "semantic_role",
        "layer_role",
        "media_type",
        "layout_slot",
        "brief",
        "executor",
        "render_window",
        "artifact_contract",
        "z_index",
    }
)
_PRIMARY_RENDERER = {
    "html-video": "HyperFrames",
    "hyperframes": "HyperFrames",
    "video-shotcraft": "Remotion",
    "hd-talking-head-relation-motion": "RelationMotion",
    "hd-talking-head-semantic-state": "SemanticState",
    "hd-talking-head-talkcraft": "Remotion",
}
TEMPLATE_ORIGIN_PRIORITY = {
    "verified_third_party": 0,
    "verified_local_canonical": 1,
    "custom_fallback": 2,
}
TEMPLATE_ADAPTATION_LEVELS = frozenset(
    {"tokens_only", "content_reflow", "structural"}
)
_TEMPLATE_CANDIDATE_KEYS = _TEMPLATE_PROVENANCE_FIELDS | _TEMPLATE_RANKING_FIELDS
_TEMPLATE_CAPACITY_KEYS = frozenset({"min_units", "max_units"})

CAPABILITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "html-video": {
        "directory": "html-video",
        "role": "content-graph-html-video",
        "load": "lazy",
        "entrypoints": (
            "packages/core/src/registry.ts",
            "packages/adapter-hyperframes/src/render.ts",
            "packages/adapter-remotion/src/",
        ),
    },
    "video-shotcraft": {
        "directory": "video-shotcraft",
        "role": "shot-recipe-2.5d-motion",
        "load": "lazy",
        "entrypoints": ("references/shots", "demos", "assets/lib"),
    },
    "erduo-broll-loop-engineering": {
        "directory": "erduo-broll-loop-engineering",
        "role": "truth-creative-canary-loop",
        "load": "lazy",
        "entrypoints": (
            "erduo-broll-loop-engineering/scripts/create-production-profile.mjs",
            "erduo-broll-loop-engineering/SKILL.md",
        ),
    },
    "video-use": {
        "directory": "video-use",
        "role": "audio-clock-ffmpeg-boundary-qa",
        "load": "lazy",
        "entrypoints": ("helpers/render.py", "SKILL.md"),
    },
    "video-autopilot-kit": {
        "directory": "video-autopilot-kit",
        "role": "asset-scoring-fatigue-semantic-qa",
        "load": "lazy",
        "entrypoints": (
            "src/asset_selection.py",
            "src/review_loop.py",
            "src/media_delivery_qa.py",
            "src/camera_transition_director.py",
        ),
    },
    "HyperFrames": {
        "directory": "hyperframes",
        "role": "html-gsap-d3-three-overlays",
        "load": "lazy",
        "entrypoints": ("README.md", "packages"),
    },
    "Remotion": {
        "directory": "remotion",
        "role": "react-frame-2.5d-ui-rendering",
        "load": "lazy",
        "entrypoints": ("packages/renderer", "packages/bundler", "packages/cli"),
    },
    "OpenMontage": {
        "directory": "OpenMontage",
        "role": "capability-routing-atelier",
        "load": "lazy",
        "entrypoints": (
            "tools/tool_registry.py",
            "tools/video/grok_video.py",
            "skills/creative/prompting/grok-prompting.md",
        ),
    },
    "Generative-Media-Skills": {
        "directory": "Generative-Media-Skills",
        "role": "generation-prompt-provider-adapter",
        "load": "lazy",
        "entrypoints": (
            "core/media/generate-video.sh",
            "core/media/image-to-video.sh",
            "schema_data.json",
        ),
    },
    "Open-Generative-AI": {
        "directory": "Open-Generative-AI",
        "role": "model-capability-async-generation-dag",
        "load": "lazy",
        "entrypoints": (
            "packages/studio/src/models.js",
            "packages/studio/src/videoToolCapabilities.js",
            "packages/studio/src/videoWorkflows.js",
            "packages/studio/src/modelCapabilities.js",
            "packages/studio/src/imageInputContracts.js",
            "packages/studio/src/utils/generationLifecycle.js",
        ),
    },
}

FAMILY_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "fact": (
        "official-dossier",
        "official-video",
        "evidence-investigation-wall",
        "newspaper-dossier",
        "proof-scrapbook",
    ),
    "identity": (
        "official-dossier",
        "official-video",
        "magazine-cover",
        "filmstrip-storyboard",
        "proof-scrapbook",
    ),
    "number": (
        "bold-number-impact",
        "orbit-data",
        "ribbon-timeline",
        "modular-dashboard",
        "radial-burst",
    ),
    "comparison": (
        "versus-split",
        "diagonal-debate",
        "editorial-contrast",
        "playful-sticker-board",
    ),
    "process": (
        "staircase-path",
        "blueprint-system",
        "ribbon-timeline",
        "comic-steps",
    ),
    "interface": (
        "filmstrip-storyboard",
        "modular-dashboard",
        "proof-scrapbook",
        "blueprint-system",
    ),
    "thesis": (
        "quote-artword",
        "magazine-cover",
        "editorial-contrast",
        "newspaper-dossier",
        "playful-sticker-board",
    ),
    "metaphor": (
        "ai-cinema",
        "radial-burst",
        "network-map",
        "playful-sticker-board",
    ),
}

ENTRY_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "evidence": ("layered-reveal", "scanline-focus", "document-rise"),
    "contrast": ("split-open", "counter-slide", "layered-reveal"),
    "progression": ("timeline-travel", "step-rise", "layered-reveal"),
    "cause_effect": ("node-converge", "flow-draw", "layered-reveal"),
    "hierarchy": ("tree-expand", "card-stagger", "layered-reveal"),
    "quote": ("artword-write", "editorial-rise", "layered-reveal"),
    "atmosphere": ("light-bloom", "depth-reveal", "layered-reveal"),
}


class RouterError(ValueError):
    """Raised when an approved strategy cannot be compiled without guessing."""


def _copy(value: Any, label: str) -> Any:
    try:
        return copy.deepcopy(value)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise RouterError(f"{label} cannot be copied safely") from None


def _as_dict(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RouterError(f"{name} must be an object")
    return dict(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouterError(f"{name} must be a non-empty string")
    return value


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RouterError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _finite_score(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouterError(f"{name} must be a finite number")
    score = float(value)
    if not math.isfinite(score):
        raise RouterError(f"{name} must be a finite number")
    return score


def _positive_int(value: Any, name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise RouterError(f"{name} must be a {qualifier} integer")
    return value


def _validate_template_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    value = _as_dict(candidate, "template candidate")
    if frozenset(value) != _TEMPLATE_CANDIDATE_KEYS:
        raise RouterError("template candidate fields do not match the contract")

    origin = _text(value["template_origin"], "template_origin")
    if origin not in TEMPLATE_ORIGIN_PRIORITY:
        raise RouterError(f"unsupported template_origin: {origin}")

    adaptation_level = _text(value["adaptation_level"], "adaptation_level")
    if adaptation_level not in TEMPLATE_ADAPTATION_LEVELS:
        raise RouterError(f"unsupported adaptation_level: {adaptation_level}")

    _text(value["template_id"], "template_id")
    _text(value["template_version"], "template_version")
    _text(value["source_entrypoint"], "source_entrypoint")
    _sha256(value["verification_id"], "verification_id")
    _sha256(value["source_sha256"], "source_sha256")
    _sha256(value["sample_sha256"], "sample_sha256")

    families = value["semantic_families"]
    if (
        not isinstance(families, list)
        or not families
        or any(not isinstance(item, str) or not item.strip() for item in families)
        or len(set(families)) != len(families)
    ):
        raise RouterError("semantic_families must be a non-empty array of unique strings")

    capacity = _as_dict(value["capacity"], "capacity")
    if frozenset(capacity) != _TEMPLATE_CAPACITY_KEYS:
        raise RouterError("capacity fields do not match the contract")
    min_units = _positive_int(capacity["min_units"], "capacity.min_units")
    max_units = _positive_int(capacity["max_units"], "capacity.max_units")
    if min_units > max_units:
        raise RouterError("capacity.min_units must not exceed capacity.max_units")

    _finite_score(value["semantic_match_score"], "semantic_match_score")
    _finite_score(value["quality_score"], "quality_score")
    _positive_int(value["reuse_gap"], "reuse_gap", allow_zero=True)
    return value


def rank_code_templates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    semantic_family: str,
    information_units: int,
) -> List[Dict[str, Any]]:
    """Rank eligible code-generated templates without changing source-kind routing."""

    family = _text(semantic_family, "semantic_family")
    units = _positive_int(information_units, "information_units")
    eligible: List[Dict[str, Any]] = []
    for candidate in candidates:
        value = _validate_template_candidate(candidate)
        capacity = value["capacity"]
        if (
            value["adaptation_level"] == "structural"
            and value["template_origin"] == "verified_third_party"
        ):
            continue
        if family not in value["semantic_families"]:
            continue
        if not capacity["min_units"] <= units <= capacity["max_units"]:
            continue
        eligible.append(value)

    if not eligible:
        raise RouterError("no eligible code-generated template")

    eligible.sort(
        key=lambda item: (
            TEMPLATE_ORIGIN_PRIORITY[item["template_origin"]],
            -float(item["semantic_match_score"]),
            -float(item["quality_score"]),
            -item["reuse_gap"],
            item["template_id"],
        )
    )
    return _copy(eligible, "ranked code templates")


def candidate_from_verified_template_record(
    record: Mapping[str, Any],
    *,
    semantic_match_score: float,
    quality_score: float,
    reuse_gap: int,
) -> Dict[str, Any]:
    """Bind one verifier-approved registry record to current-content scores."""

    checked = _as_dict(record, "verified template record")
    missing = _TEMPLATE_PROVENANCE_FIELDS - set(checked)
    if missing:
        raise RouterError(
            "verified template record is missing " + ", ".join(sorted(missing))
        )
    if checked.get("template_origin") not in {
        "verified_third_party", "verified_local_canonical",
    }:
        raise RouterError(
            "verified template record must be verified_third_party or verified_local_canonical"
        )
    registered = _registered_template(checked)
    if checked != registered:
        raise RouterError("record differs from the registered template")
    candidate = {
        field: _copy(checked[field], f"verified template record.{field}")
        for field in _TEMPLATE_PROVENANCE_FIELDS
    }
    candidate.update(
        {
            "semantic_match_score": semantic_match_score,
            "quality_score": quality_score,
            "reuse_gap": reuse_gap,
        }
    )
    return _validate_template_candidate(candidate)


def _kind(value: Any, name: str = "kind") -> str:
    if not isinstance(value, str) or value not in SOURCE_KINDS:
        raise RouterError(f"unsupported {name}: {value}")
    return value


def _authority(callable_object: Any, *args: Any) -> Any:
    try:
        return callable_object(*args)
    except VisualStrategyError as error:
        raise RouterError(str(error)) from None


def freeze_candidate(
    expected_kind: str,
    candidates: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Freeze one candidate through the authoritative same-kind ranker."""

    approved_kind = _kind(expected_kind, "approved kind")
    candidate_list = [_as_dict(item, "candidate") for item in candidates]
    ranked = _authority(stable_same_kind_candidates, candidate_list, approved_kind)
    return _copy(ranked[0], "frozen candidate")


def _validate_renderer_binding(dependency_id: str, primary_renderer: str) -> None:
    expected = _PRIMARY_RENDERER.get(dependency_id)
    if expected is not None and primary_renderer != expected:
        raise RouterError(
            f"{dependency_id} requires exactly one {expected} primary renderer"
        )


def _registered_template(
    binding: Mapping[str, Any],
    qualification_registry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    # Resolve the sibling from the single package, never a caller-supplied registry.
    path = Path(__file__).resolve().with_name("verify_broll_template.py")
    spec = importlib.util.spec_from_file_location("hd_registered_template", path)
    if spec is None or spec.loader is None:
        raise RouterError("registered template verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        if qualification_registry is not None:
            candidate = _as_dict(qualification_registry, "qualification_registry")
            if set(candidate) != {"path", "sha256"}:
                raise RouterError("qualification_registry must contain only path and sha256")
            return module.verify_candidate_binding(
                binding,
                _text(candidate["path"], "qualification_registry.path"),
                _text(candidate["sha256"], "qualification_registry.sha256"),
            )
        return module.verify_registered_binding(binding)
    except module.RegistryError as exc:
        raise RouterError(str(exc)) from exc


def _validate_code_cross_fields(
    component: Mapping[str, Any],
    qualification_registry: Optional[Mapping[str, Any]] = None,
) -> None:
    dependency_id = _text(component.get("dependency_id"), "dependency_id")
    primary_renderer = _text(component.get("primary_renderer"), "primary_renderer")
    entrypoint = _text(component.get("entrypoint"), "entrypoint")
    record = _as_dict(component.get("invocation_record"), "invocation_record")
    argv = record.get("argv")
    if not isinstance(argv, list):
        raise RouterError("invocation_record.argv must be an array")
    if argv.count(entrypoint) != 1:
        raise RouterError("invocation_record.argv must bind entrypoint exactly once")
    if dependency_id == "hd-talking-head-semantic-state" and component.get("template_origin") != "verified_local_canonical":
        raise RouterError("SemanticState requires a qualified local canonical template")
    if component.get("template_origin") in {
        "verified_third_party", "verified_local_canonical",
    }:
        registered = _registered_template(component, qualification_registry)
        expected = {"remotion": "Remotion", "hyperframes": "HyperFrames",
                    "relationmotion": "RelationMotion", "semanticstate": "SemanticState"}.get(
            registered["render_contract"]["engine"].lower()
        )
        if dependency_id != registered["upstream"]["project"] or primary_renderer != expected:
            raise RouterError("binding renderer/dependency differs from the registered template")
    else:
        _validate_renderer_binding(dependency_id, primary_renderer)


def validate_template_binding(
    binding: Mapping[str, Any],
    *,
    qualification_registry: Optional[Mapping[str, Any]] = None,
) -> None:
    """Recheck frozen content and provenance before compiling or executing code."""
    invocation = _as_dict(binding.get("invocation_record"), "invocation_record")
    request = _as_dict(invocation.get("template_request"), "invocation_record.template_request")
    if set(request) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}:
        raise RouterError("template_request must freeze semantic_family, information_units, numeric_values and numeric_scale")
    family = _text(request["semantic_family"], "template_request.semantic_family")
    units = _positive_int(request["information_units"], "template_request.information_units")
    if family not in binding["semantic_families"]:
        raise RouterError("template_request semantic_family does not match the frozen template")
    capacity = binding["capacity"]
    if not capacity["min_units"] <= units <= capacity["max_units"]:
        raise RouterError("template_request information_units exceeds frozen capacity")
    numbers = request["numeric_values"]
    if not isinstance(numbers, list) or any(
        type(value) not in {int, float} or not abs(value) <= sys.float_info.max for value in numbers
    ):
        raise RouterError("template_request numeric_values must contain finite numbers, not booleans")
    if type(request["numeric_scale"]) is not str or request["numeric_scale"] not in {"linear", "log", "not_applicable"}:
        raise RouterError("template_request numeric_scale is invalid")
    if numbers and request["numeric_scale"] == "not_applicable":
        raise RouterError("numeric_values require an explicit numeric_scale")
    _validate_code_cross_fields(binding, qualification_registry)
    # Exact upstream source inspected for rounding and automatic log remapping.
    # A different revision must receive its own reviewed precision policy.
    if binding["template_origin"] == "verified_third_party" and binding["template_id"] == "html-video/frame-data-rollup":
        if binding["source_sha256"] != "af3bea37764c04e571bdf158748e3442b9cc788dbc7e94226c6519586d752e15":
            raise RouterError("DataRollup source changed; numeric policy needs review")
        if len(numbers) != units or request["numeric_scale"] != "linear":
            raise RouterError("DataRollup requires one exact numeric value per unit and linear scale")
        if any(value < 0 or value > 2**53 - 1 or int(value) != value for value in numbers):
            raise RouterError("DataRollup cannot preserve decimals, negatives or unsafe integers")
        positives = [value for value in numbers if value > 0]
        if positives and max(positives) / min(positives) >= 50:
            raise RouterError("DataRollup would silently change to log scale; choose a compatible template")


def validate_invocation_evidence(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate code-binding schema consistency without executing the component."""

    checked = _as_dict(evidence, "invocation evidence")
    reserved = set(checked) & _RESERVED_BINDING_FIELDS
    if reserved:
        raise RouterError(
            "invocation evidence contains reserved fields: "
            + ", ".join(sorted(reserved))
        )
    component: Dict[str, Any] = {
        "component_id": "evidence-contract",
        "kind": "code_generated",
        "semantic_role": "explanation",
        "layer_role": "base",
        "executor": "code-broll:evidence-contract",
        "media_type": "animation",
        "render_window": {
            "start_frame": 0,
            "end_frame": 1,
            "z_index": 0,
            "layout_slot": "main",
            "opacity": 1.0,
            "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        },
        "artifact_contract": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "alpha": True,
        },
    }
    for field in sorted(checked):
        component[field] = _copy(checked[field], f"invocation evidence.{field}")
    # This probe checks invocation structure, not template authenticity. Do not
    # replace provenance already frozen by visual_direction with probe values.
    if not (set(checked) & _TEMPLATE_PROVENANCE_FIELDS):
        component.update({
            "template_origin": "custom_fallback",
            "template_id": "invocation-evidence-placeholder",
            "template_version": "unrendered",
            "verification_id": "0" * 64,
            "adaptation_level": "structural",
            "source_entrypoint": "templates/invocation-evidence-placeholder/index.html",
            "source_sha256": "0" * 64,
            "sample_sha256": "0" * 64,
            "semantic_families": ["thesis"],
            "capacity": {"min_units": 1, "max_units": 1},
        })
    recipe = {
        "schema_version": 2,
        "segment_id": "evidence-contract",
        "strategy_revision": 1,
        "mode": "single",
        "composition": {
            "family": "single_full_frame",
            "presenter_mode": "hidden",
            "reading_order": ["evidence-contract"],
            "component_dependencies": [],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": [component],
        "final_compositor": "ffmpeg",
    }
    validated = _authority(validate_shot_recipe_v2, recipe)
    _validate_code_cross_fields(validated["components"][0])
    return _copy(checked, "invocation evidence")


def validate_strategy(
    intent: Mapping[str, Any], strategy: Mapping[str, Any]
) -> Dict[str, Any]:
    """Delegate canonical VisualIntent and VisualStrategy validation to Task2."""

    checked_intent = _authority(validate_visual_intent, intent)
    return _authority(validate_visual_strategy, checked_intent, strategy)


def _canonical_snapshot(
    candidates: Any, expected_kind: str, component_id: str
) -> Dict[str, Any]:
    if not isinstance(candidates, list):
        raise RouterError(f"candidate snapshot for {component_id} must be an array")
    candidate_list = [_as_dict(item, "candidate") for item in candidates]
    ranked = _authority(stable_same_kind_candidates, candidate_list, expected_kind)
    return ranked[0]


def _executor(kind: str, binding: Mapping[str, Any]) -> str:
    if kind == "local_material":
        return "local-media"
    if kind == "official_material":
        return "official-media"
    if kind == "external_stock":
        return "external-stock"
    if kind == "code_generated":
        dependency_id = binding.get("dependency_id")
        executors = {
            "html-video": "reference_adapter",
            "video-shotcraft": "skill_invocation",
            "hd-talking-head-local-canonical": "reference_adapter",
            "hd-talking-head-relation-motion": "reference_adapter",
            "hd-talking-head-semantic-state": "reference_adapter",
            "hd-talking-head-talkcraft": "reference_adapter",
        }
        if not isinstance(dependency_id, str):
            return "invalid-binding"
        return executors.get(dependency_id, "invalid-binding")
    model = binding.get("model")
    if not isinstance(model, str) or not model:
        model = "invalid-binding"
    if model == "grok-imagine-video":
        return "OpenMontage:GrokVideo"
    provider = binding.get("provider")
    if not isinstance(provider, str) or not provider:
        provider = "invalid-binding"
    return f"ai-provider:{provider}:{model}"


def _binding_matches_candidate(
    kind: str, binding: Mapping[str, Any], selected: Mapping[str, Any]
) -> None:
    id_field = {
        "local_material": "material_id",
        "official_material": "source_id",
        "external_stock": "provider_asset_id",
        "ai_generated": "generation_id",
    }.get(kind)
    if id_field is not None and binding.get(id_field) != selected.get("asset_id"):
        raise RouterError(
            f"{kind} binding {id_field} does not match frozen candidate asset_id"
        )


def _canonical_binding(binding: Mapping[str, Any], component_id: str) -> Dict[str, Any]:
    checked = _as_dict(binding, f"binding for {component_id}")
    reserved = set(checked) & _RESERVED_BINDING_FIELDS
    if reserved:
        raise RouterError(
            f"binding for {component_id} contains reserved fields: "
            + ", ".join(sorted(reserved))
        )
    return _copy(checked, f"binding for {component_id}")


def _compile_shot_recipe(
    strategy: Mapping[str, Any], context: Mapping[str, Any]
) -> Dict[str, Any]:
    checked_context = _as_dict(context, "compile context")
    required_context = {
        "intent",
        "candidate_snapshots",
        "bindings",
        "segment_frames",
    }
    missing_context = required_context - set(checked_context)
    if missing_context:
        raise RouterError(
            "compile context is missing " + ", ".join(sorted(missing_context))
        )
    extra_context = set(checked_context) - required_context - {
        "strategy_revision",
        "template_candidates",
    }
    if extra_context:
        raise RouterError(
            "compile context contains unexpected fields: "
            + ", ".join(sorted(extra_context))
        )
    approved = validate_strategy(checked_context["intent"], strategy)
    snapshots = _as_dict(checked_context["candidate_snapshots"], "candidate_snapshots")
    bindings = _as_dict(checked_context["bindings"], "bindings")
    template_candidates = _as_dict(
        checked_context.get("template_candidates", {}), "template_candidates"
    )
    component_ids = [component["component_id"] for component in approved["components"]]
    if set(snapshots) - set(component_ids):
        raise RouterError("candidate_snapshots contains an unapproved component_id")
    if set(bindings) != set(component_ids):
        raise RouterError("bindings keys must match approved component_ids")
    code_component_ids = {
        component["component_id"]
        for component in approved["components"]
        if component["kind"] == "code_generated"
    }
    if set(template_candidates) - code_component_ids:
        raise RouterError("template_candidates contains an unapproved component_id")
    revision = checked_context.get("strategy_revision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise RouterError("strategy_revision must be a positive integer")
    segment_frames = checked_context["segment_frames"]
    if (
        not isinstance(segment_frames, int)
        or isinstance(segment_frames, bool)
        or segment_frames < 1
    ):
        raise RouterError("segment_frames must be a positive integer")

    recipe_components: List[Dict[str, Any]] = []
    selected_candidates: Dict[str, Dict[str, Any]] = {}
    approved_by_id = {
        component["component_id"]: component for component in approved["components"]
    }
    approved_order = [
        approved_by_id[component_id]
        for component_id in approved["composition"]["reading_order"]
    ]
    for index, approved_component in enumerate(approved_order):
        component_id = approved_component["component_id"]
        kind = approved_component["kind"]
        binding = _canonical_binding(bindings[component_id], component_id)
        if kind == "code_generated":
            if component_id in template_candidates:
                request = _as_dict(template_candidates[component_id], "template candidates")
                if set(request) != {"semantic_family", "information_units", "candidates"}:
                    raise RouterError("template candidate request fields do not match the contract")
                if not isinstance(request["candidates"], list):
                    raise RouterError("template candidates must be an array")
                selected_template = rank_code_templates(
                    request["candidates"], semantic_family=request["semantic_family"],
                    information_units=request["information_units"],
                )[0]
                for field in sorted(_TEMPLATE_PROVENANCE_FIELDS):
                    if field in binding and binding[field] != selected_template[field]:
                        raise RouterError("template selection changed a frozen binding")
                    binding[field] = _copy(selected_template[field], f"template binding.{field}")
            elif not _TEMPLATE_PROVENANCE_FIELDS.issubset(binding):
                raise RouterError("code component requires template candidates or frozen provenance")
            validate_template_binding(binding)
            validate_invocation_evidence(binding)
            if component_id in template_candidates:
                content = binding["invocation_record"]["template_request"]
                if any(request[field] != content[field] for field in ("semantic_family", "information_units")):
                    raise RouterError("template candidate request differs from frozen template_request")
        if component_id in snapshots:
            selected_candidates[component_id] = _canonical_snapshot(
                snapshots[component_id], kind, component_id
            )
        elif kind not in {"code_generated", "ai_generated"}:
            raise RouterError(f"candidate snapshot for {component_id} is missing")

        component: Dict[str, Any] = {
            "component_id": component_id,
            "kind": kind,
            "semantic_role": approved_component["semantic_role"],
            "layer_role": approved_component["layer_role"],
            "executor": _executor(kind, binding),
            "media_type": approved_component["media_type"],
            "render_window": {
                "start_frame": 0,
                "end_frame": segment_frames,
                "z_index": index * 10,
                "layout_slot": approved_component["layout_slot"],
                "opacity": 1.0,
                "safe_zone": {
                    "top": 120,
                    "bottom": 320,
                    "left": 40,
                    "right": 40,
                },
            },
            "artifact_contract": {
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "alpha": kind == "code_generated",
            },
        }
        for field in sorted(binding):
            component[field] = binding[field]
        recipe_components.append(component)

    recipe = {
        "schema_version": 2,
        "segment_id": approved["segment_id"],
        "strategy_revision": revision,
        "mode": approved["mode"],
        "composition": approved["composition"],
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": recipe_components,
        "final_compositor": "ffmpeg",
    }
    validated_recipe = _authority(validate_shot_recipe_v2, recipe)
    for component in validated_recipe["components"]:
        component_id = component["component_id"]
        if component["kind"] == "code_generated":
            _validate_code_cross_fields(component)
        if component_id in selected_candidates:
            _binding_matches_candidate(
                component["kind"], component, selected_candidates[component_id]
            )
    return validated_recipe


def compile_strategy(
    strategy: Mapping[str, Any], context: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compile one canonical VisualStrategy v1 into a pure ShotRecipe v2 value."""

    checked = _as_dict(strategy, "visual strategy")
    if checked.get("schema_version") != 1 or not isinstance(
        checked.get("components"), list
    ):
        raise RouterError(
            "compile_strategy requires canonical VisualStrategy schema_version 1"
        )
    return _compile_shot_recipe(checked, context)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, type=Path)
    parser.add_argument("--strategy", required=True, type=Path)
    parser.add_argument("--candidate-snapshots", required=True, type=Path)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--template-candidates", type=Path)
    parser.add_argument("--segment-frames", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_request:
        return int(exit_request.code or 0)
    try:
        strategy = _read_json(args.strategy)
        intent = _read_json(args.intent)
        candidate_snapshots = _read_json(args.candidate_snapshots)
        bindings = _read_json(args.bindings)
        template_candidates = (
            _read_json(args.template_candidates) if args.template_candidates else {}
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        print("B-roll strategy compilation failed: invalid input JSON", file=sys.stderr)
        return 2
    try:
        recipe = compile_strategy(
            strategy,
            {
                "intent": intent,
                "candidate_snapshots": candidate_snapshots,
                "bindings": bindings,
                "template_candidates": template_candidates,
                "segment_frames": args.segment_frames,
            },
        )
    except RouterError as error:
        print(f"B-roll strategy compilation failed: {error}", file=sys.stderr)
        return 2
    except (TypeError, ValueError):
        print("B-roll strategy compilation failed: invalid input JSON", file=sys.stderr)
        return 2
    try:
        _write_json_atomic(args.output, recipe)
    except OSError:
        print("output I/O failure", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

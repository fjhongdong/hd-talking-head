"""Pure validators for semantic visual strategies and bound shot recipes."""

from __future__ import annotations

import copy
import math
import re
from pathlib import PurePosixPath
from typing import Mapping
from urllib.parse import urlsplit

from . import avatar_profile


SOURCE_KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)
COMPOSITION_FAMILIES = {
    "no_broll": "none",
    "aroll_with_overlay": "none",
    "single_full_frame": "single",
    "evidence_with_data_overlay": "hybrid",
}
PRESENTER_MODES = ("hidden", "bottom_window", "full_frame")
LAYER_ROLE_LAYOUT_SLOTS = {
    "base": frozenset(
        {"main", "background", "full_frame", "background_blur", "content_safe"}
    ),
    "overlay": frozenset({"overlay", "main_overlay"}),
    "inset": frozenset({"inset"}),
    "annotation": frozenset({"annotation", "lower-third", "main_overlay"}),
}

__all__ = [
    "SOURCE_KINDS",
    "COMPOSITION_FAMILIES",
    "PRESENTER_MODES",
    "LAYER_ROLE_LAYOUT_SLOTS",
    "VisualStrategyError",
    "validate_visual_intent",
    "validate_visual_strategy",
    "validate_composition_contract",
    "validate_shot_recipe_v2",
    "stable_same_kind_candidates",
]

_SEMANTIC_GOALS = {
    "evidence",
    "demonstrate",
    "explain",
    "contextualize",
    "evoke",
    "metaphorize",
}
_SEMANTIC_ROLES = {
    "evidence",
    "demonstration",
    "explanation",
    "context",
    "mood",
    "metaphor",
}
_LAYER_ROLES = set(LAYER_ROLE_LAYOUT_SLOTS)
_REAL_MATERIAL_KINDS = {
    "local_material",
    "official_material",
    "external_stock",
}
_MEDIA_TYPES = {"image", "video", "document", "webpage", "ui_capture", "animation"}
_MODES = {"none", "single", "hybrid"}
_LEVELS = {"low", "medium", "high"}
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_TEMPLATE_ORIGINS = {
    "verified_third_party",
    "verified_local_canonical",
    "custom_fallback",
}
_TEMPLATE_ADAPTATION_LEVELS = {"tokens_only", "content_reflow", "structural"}
_TEMPLATE_CAPACITY_KEYS = {"min_units", "max_units"}
_RELATION_MOTION_IDENTITY = {
    "executor": "reference_adapter",
    "dependency_id": "hd-talking-head-relation-motion",
    "template_origin": "verified_local_canonical",
    "template_id": "hd-talking-head/relation-motion",
    "template_version": "1.0.0",
    "entrypoint": "scripts/relation_motion_renderer_bundle.py",
    "source_entrypoint": "scripts/relation_motion_renderer_bundle.py",
    "producer_version": "1.0.0",
    "primary_renderer": "RelationMotion",
    "renderer_version": "1.0.0",
}

_INTENT_KEYS = {
    "segment_id",
    "statement",
    "semantic_goals",
    "claims",
    "entities",
    "relations",
    "requirements",
    "presenter_presence",
}
_REQUIREMENT_KEYS = {
    "verifiability",
    "realism",
    "abstraction",
    "product_specificity",
    "emotional_intensity",
}
_STRATEGY_KEYS = {
    "schema_version",
    "segment_id",
    "mode",
    "rationale",
    "components",
    "composition",
}
_STRATEGY_COMPONENT_KEYS = {
    "component_id",
    "kind",
    "semantic_role",
    "layer_role",
    "media_type",
    "layout_slot",
    "brief",
}
_RECIPE_KEYS = {
    "schema_version",
    "segment_id",
    "strategy_revision",
    "mode",
    "composition",
    "canvas",
    "components",
    "final_compositor",
}
_RECIPE_COMMON_KEYS = {
    "component_id",
    "kind",
    "semantic_role",
    "layer_role",
    "executor",
    "media_type",
    "render_window",
    "artifact_contract",
}
_COMPOSITION_KEYS = {
    "family",
    "presenter_mode",
    "reading_order",
    "component_dependencies",
}
_DEPENDENCY_KEYS = {"component_id", "depends_on"}
_RENDER_WINDOW_KEYS = {
    "start_frame",
    "end_frame",
    "z_index",
    "layout_slot",
    "opacity",
    "safe_zone",
}
_SAFE_ZONE_KEYS = {"top", "bottom", "left", "right"}
_ARTIFACT_KEYS = {"width", "height", "fps", "alpha"}
_BINDING_KEYS = {
    "local_material": {"material_id", "job_path", "sha256"},
    "official_material": {
        "source_id",
        "publisher",
        "source_url",
        "snapshot_path",
        "fetched_at",
        "sha256",
    },
    "external_stock": {
        "provider",
        "provider_asset_id",
        "author",
        "asset_page",
        "job_path",
        "license_snapshot",
        "downloaded_at",
        "sha256",
    },
    "code_generated": {
        "producer_type",
        "dependency_id",
        "entrypoint",
        "producer_version",
        "brief_sha256",
        "invocation_record",
        "primary_renderer",
        "renderer_version",
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
    },
    "ai_generated": {
        "provider",
        "model",
        "endpoint_id",
        "prompt_sha256",
        "generation_id",
        "sha256",
    },
}
_CANDIDATE_KEYS = {
    "asset_id",
    "kind",
    "semantic_match_score",
    "quality_score",
    "hard_gates",
}
_GATE_KEYS = {
    "semantic_match",
    "factual_reliability",
    "native_vertical",
    "quality_readability",
}

_PROTECTED_CLAIM_TYPES = {
    "named_person_identity",
    "person_identity",
    "identity",
    "official_statement",
    "official_claim",
    "official_quote",
    "precise_fact",
    "exact_fact",
    "fact",
    "statistic",
}
_OFFICIAL_CLAIM_TYPES = {"official_statement", "official_claim", "official_quote"}
_NAMED_PERSON_ENTITY_TYPES = {"named_person", "person_identity"}
_SPECIFIC_EVENT_TYPES = {"specific_real_event", "real_event_identity", "historical_event"}
_REAL_PRODUCT_UI_TYPES = {"real_product_ui", "official_product_ui"}


class VisualStrategyError(ValueError):
    """Raised when a visual strategy contract is invalid."""


def _error(message: str) -> VisualStrategyError:
    return VisualStrategyError(message)


def _dict(value: object, *, label: str) -> dict:
    if type(value) is not dict:
        raise _error(f"{label} must be a dict")
    return value


def _exact_dict(value: object, keys: set[str], *, label: str) -> dict:
    result = _dict(value, label=label)
    actual = set(result)
    missing = keys - actual
    extra = actual - keys
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"extra: {', '.join(sorted(str(field) for field in extra))}")
        raise _error(f"{label} fields are invalid ({'; '.join(details)})")
    return result


def _list(value: object, *, label: str) -> list:
    if type(value) is not list:
        raise _error(f"{label} must be a list")
    return value


def _text(value: object, *, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise _error(f"{label} must be a non-empty string")
    return value


def _integer(value: object, *, label: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise _error(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise _error(f"{label} must be at least {minimum}")
    return value


def _finite_number(value: object, *, label: str) -> float:
    if type(value) not in {int, float}:
        raise _error(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise _error(f"{label} must be finite") from None
    if not math.isfinite(result):
        raise _error(f"{label} must be finite")
    return result


def _opacity(value: object, *, label: str) -> float:
    result = _finite_number(value, label=label)
    if not 0.0 <= result <= 1.0:
        raise _error(f"{label} must be between zero and one")
    return result


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise _error(f"{label} must be a 64-character hexadecimal sha256")
    return value


def _job_relative_posix_path(value: object, *, label: str) -> str:
    path_text = _text(value, label=label)
    try:
        parsed = urlsplit(path_text)
    except ValueError:
        raise _error(f"{label} must be a Job-relative POSIX path") from None
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or "\\" in path_text
        or bool(parsed.scheme)
        or bool(parsed.netloc)
    ):
        raise _error(f"{label} must be a Job-relative POSIX path")
    return path_text


def _https_url(value: object, *, label: str) -> str:
    url = _text(value, label=label)
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in url
    ):
        raise _error(f"{label} must be an https URL with a hostname")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise _error(f"{label} must be an https URL with a hostname") from None
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "#" in url
    ):
        raise _error(f"{label} must be an https URL with a hostname")
    return url


def _copy(value: object, *, label: str):
    try:
        return copy.deepcopy(value)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _error(f"{label} cannot be copied safely") from None


def _validate_mode_count(
    mode: object, components: list, *, label: str, family: object = None
) -> str:
    if type(mode) is not str or mode not in _MODES:
        raise _error(f"{label} mode is invalid")
    count = len(components)
    if (
        (mode == "none" and count != 0 and family != "aroll_with_overlay")
        or (mode == "single" and count != 1)
        or (mode == "hybrid" and count < 2)
    ):
        raise _error(f"{label} mode does not match component count")
    return mode


def validate_composition_contract(
    composition: object,
    components: list[dict],
    mode: object,
    *,
    label: str = "composition",
) -> dict:
    """Validate the shared strategy and ShotRecipe composition contract."""

    if type(components) is not list or any(
        type(component) is not dict for component in components
    ):
        raise _error(f"{label} components must be a list of objects")

    keys = _COMPOSITION_KEYS | ({"avatar"} if type(composition) is dict and "avatar" in composition else set())
    checked = _exact_dict(composition, keys, label=label)
    family = checked["family"]
    if type(family) is not str or COMPOSITION_FAMILIES.get(family) != mode:
        raise _error(f"{label} family does not match mode")
    presenter_mode = checked["presenter_mode"]
    if type(presenter_mode) is not str or presenter_mode not in PRESENTER_MODES:
        raise _error(f"{label} presenter_mode is invalid")
    if "avatar" in checked:
        if presenter_mode != "bottom_window":
            raise _error(f"{label} avatar is unused in this presenter mode")
        try:
            checked["avatar"] = avatar_profile.validate_avatar(checked["avatar"])
        except (ValueError, OSError) as error:
            raise _error(str(error)) from None
    if (family in {"no_broll", "aroll_with_overlay"} and presenter_mode != "full_frame") or (
        family not in {"no_broll", "aroll_with_overlay"} and presenter_mode == "full_frame"
    ):
        raise _error(f"{label} presenter_mode does not match family")

    component_ids = [component.get("component_id") for component in components]
    if any(type(component_id) is not str or not component_id for component_id in component_ids):
        raise _error(f"{label} component ids are invalid")
    reading_order = _list(checked["reading_order"], label=f"{label}.reading_order")
    if (
        any(type(component_id) is not str for component_id in reading_order)
        or len(reading_order) != len(component_ids)
        or len(set(reading_order)) != len(reading_order)
        or set(reading_order) != set(component_ids)
    ):
        raise _error(f"{label} reading_order must contain every component_id once")

    by_id = {str(component["component_id"]): component for component in components}
    reading_positions = {
        component_id: index for index, component_id in enumerate(reading_order)
    }
    annotation_ids = [
        component_id
        for component_id in reading_order
        if by_id[component_id].get("layer_role") == "annotation"
    ]
    base_ids = {
        component_id
        for component_id in reading_order
        if by_id[component_id].get("layer_role") == "base"
    }
    dependencies = _list(
        checked["component_dependencies"],
        label=f"{label}.component_dependencies",
    )
    dependent_ids: list[str] = []
    if family == "aroll_with_overlay" and dependencies:
        raise _error(f"{label} aroll_with_overlay must not declare dependencies")
    for index, dependency_value in enumerate(dependencies):
        dependency = _exact_dict(
            dependency_value,
            _DEPENDENCY_KEYS,
            label=f"{label}.component_dependencies[{index}]",
        )
        component_id = _text(
            dependency["component_id"],
            label=f"{label}.component_dependencies[{index}].component_id",
        )
        targets = _list(
            dependency["depends_on"],
            label=f"{label}.component_dependencies[{index}].depends_on",
        )
        if (
            component_id not in by_id
            or by_id[component_id].get("layer_role") != "annotation"
            or not targets
            or any(type(target) is not str for target in targets)
            or len(set(targets)) != len(targets)
            or any(target == component_id or target not in base_ids for target in targets)
            or targets != [item for item in reading_order if item in set(targets)]
            or any(
                reading_positions[target] >= reading_positions[component_id]
                for target in targets
            )
        ):
            raise _error(f"{label} component dependency is invalid")
        if by_id[component_id].get("kind") == "code_generated":
            for target in targets:
                base = by_id[target]
                if base.get("kind") in _REAL_MATERIAL_KINDS:
                    continue
                if (
                    base.get("kind") == "ai_generated"
                    and base.get("semantic_role") != "evidence"
                    and by_id[component_id].get("semantic_role") != "evidence"
                ):
                    continue
                raise _error(
                    f"{label} code annotation requires real material or non-evidence AI bases"
                )
        dependent_window = by_id[component_id].get("render_window")
        target_windows = [by_id[target].get("render_window") for target in targets]
        if type(dependent_window) is dict and all(
            type(window) is dict for window in target_windows
        ):
            common_start = max(int(window["start_frame"]) for window in target_windows)
            common_end = min(int(window["end_frame"]) for window in target_windows)
            if (
                dependent_window["start_frame"] < common_start
                or dependent_window["end_frame"] > common_end
            ):
                raise _error(
                    f"{label} annotation window must fit every dependency window"
                )
        dependent_ids.append(component_id)
    if family != "aroll_with_overlay" and dependent_ids != annotation_ids:
        raise _error(f"{label} must bind every annotation exactly once")

    roles = [component.get("layer_role") for component in components]
    if family == "no_broll" and (components or dependencies):
        raise _error(f"{label} no_broll must be empty")
    if family == "aroll_with_overlay":
        if (
            presenter_mode != "full_frame"
            or not components
            or dependencies
            or any(
                component.get("layer_role") != "annotation"
                or component.get("kind") != "code_generated"
                for component in components
            )
        ):
            raise _error(
                f"{label} aroll_with_overlay requires non-empty code annotations"
            )
    if family == "single_full_frame" and (
        len(components) != 1 or roles != ["base"] or dependencies
    ):
        raise _error(f"{label} single_full_frame requires one base component")
    if family == "evidence_with_data_overlay" and (
        len(components) < 2 or not base_ids or not annotation_ids
    ):
        raise _error(f"{label} evidence_with_data_overlay requires base and annotation")
    return _copy(checked, label=label)


def _structured_types(value: dict, *field_names: str) -> set[str]:
    result: set[str] = set()
    for field in field_names:
        item = value.get(field)
        if type(item) is str:
            result.add(item)
    return result


def validate_visual_intent(intent: object) -> dict:
    """Validate a VisualIntent and return an independent deep copy."""
    checked = _exact_dict(intent, _INTENT_KEYS, label="visual intent")
    _text(checked["segment_id"], label="visual intent segment_id")
    _text(checked["statement"], label="visual intent statement")

    goals = _list(checked["semantic_goals"], label="semantic_goals")
    if not goals or any(type(goal) is not str or goal not in _SEMANTIC_GOALS for goal in goals):
        raise _error("semantic_goals contains an invalid goal")
    if len(goals) != len(set(goals)):
        raise _error("semantic_goals must not contain duplicates")

    claims = _list(checked["claims"], label="claims")
    for index, claim_value in enumerate(claims):
        claim = _dict(claim_value, label=f"claims[{index}]")
        if not {"type", "value", "verification_required"}.issubset(claim):
            raise _error(f"claims[{index}] is missing required fields")
        _text(claim["type"], label=f"claims[{index}].type")
        if "claim_type" in claim:
            _text(claim["claim_type"], label=f"claims[{index}].claim_type")
        _text(claim["value"], label=f"claims[{index}].value")
        if type(claim["verification_required"]) is not bool:
            raise _error(f"claims[{index}].verification_required must be a bool")

    for field in ("entities", "relations"):
        items = _list(checked[field], label=field)
        for index, item in enumerate(items):
            structured = _dict(item, label=f"{field}[{index}]")
            signal_fields = (
                ("type", "entity_type")
                if field == "entities"
                else ("type", "relation_type")
            )
            for signal_field in signal_fields:
                if signal_field in structured:
                    _text(
                        structured[signal_field],
                        label=f"{field}[{index}].{signal_field}",
                    )

    requirements = _exact_dict(
        checked["requirements"], _REQUIREMENT_KEYS, label="requirements"
    )
    if any(type(level) is not str or level not in _LEVELS for level in requirements.values()):
        raise _error("requirements contains an invalid level")
    if (
        type(checked["presenter_presence"]) is not str
        or checked["presenter_presence"] not in {"required", "allowed", "hidden"}
    ):
        raise _error("presenter_presence is invalid")
    return _copy(checked, label="visual intent")


def _intent_signals(intent: dict) -> tuple[bool, bool, bool, bool]:
    claim_types = {
        item_type
        for claim in intent["claims"]
        for item_type in _structured_types(claim, "type", "claim_type")
    }
    verified_claim_types = {
        item_type
        for claim in intent["claims"]
        if claim["verification_required"] is True
        for item_type in _structured_types(claim, "type", "claim_type")
    }
    entity_types = {
        item_type
        for item in intent["entities"]
        for item_type in _structured_types(item, "type", "entity_type")
    }
    relation_types = {
        item_type
        for item in intent["relations"]
        for item_type in _structured_types(item, "type", "relation_type")
    }
    protected_evidence = bool(
        any(claim["verification_required"] is True for claim in intent["claims"])
        or claim_types & _PROTECTED_CLAIM_TYPES
        or entity_types & _NAMED_PERSON_ENTITY_TYPES
        or "official_attribution" in relation_types
        or any(
            "person" in _structured_types(entity, "type", "entity_type")
            and type(entity.get("name")) is str
            and bool(entity["name"].strip())
            for entity in intent["entities"]
        )
    )
    official_evidence = bool(
        verified_claim_types & _OFFICIAL_CLAIM_TYPES
        or "official_attribution" in relation_types
    )
    specific_event = bool(
        claim_types & _SPECIFIC_EVENT_TYPES
        or entity_types & _SPECIFIC_EVENT_TYPES
        or relation_types & _SPECIFIC_EVENT_TYPES
    )
    real_product_ui = bool(
        intent["requirements"]["product_specificity"] == "high"
        or claim_types & _REAL_PRODUCT_UI_TYPES
        or entity_types & _REAL_PRODUCT_UI_TYPES
        or "represents_real_product" in relation_types
    )
    return protected_evidence, official_evidence, specific_event, real_product_ui


def validate_visual_strategy(intent: object, strategy: object) -> dict:
    """Validate a strategy against a structured VisualIntent."""
    checked_intent = validate_visual_intent(intent)
    checked = _exact_dict(strategy, _STRATEGY_KEYS, label="visual strategy")
    if type(checked["schema_version"]) is not int or checked["schema_version"] != 1:
        raise _error("visual strategy schema_version must be one")
    segment_id = _text(checked["segment_id"], label="visual strategy segment_id")
    if segment_id != checked_intent["segment_id"]:
        raise _error("visual strategy segment_id does not match intent")
    _text(checked["rationale"], label="visual strategy rationale")
    components = _list(checked["components"], label="visual strategy components")
    composition_value = checked["composition"]
    family_hint = composition_value.get("family") if type(composition_value) is dict else None
    mode = _validate_mode_count(
        checked["mode"], components, label="visual strategy", family=family_hint
    )

    component_ids: set[str] = set()
    validated_components: list[dict] = []
    for index, component_value in enumerate(components):
        component = _exact_dict(
            component_value,
            _STRATEGY_COMPONENT_KEYS,
            label=f"visual strategy components[{index}]",
        )
        component_id = _text(
            component["component_id"], label=f"components[{index}].component_id"
        )
        if component_id in component_ids:
            raise _error("visual strategy component_id must be unique")
        component_ids.add(component_id)
        if type(component["kind"]) is not str or component["kind"] not in SOURCE_KINDS:
            raise _error(f"components[{index}].kind is invalid")
        if (
            type(component["semantic_role"]) is not str
            or component["semantic_role"] not in _SEMANTIC_ROLES
        ):
            raise _error(f"components[{index}].semantic_role is invalid")
        if type(component["layer_role"]) is not str or component["layer_role"] not in _LAYER_ROLES:
            raise _error(f"components[{index}].layer_role is invalid")
        if type(component["media_type"]) is not str or component["media_type"] not in _MEDIA_TYPES:
            raise _error(f"components[{index}].media_type is invalid")
        layout_slot = _text(
            component["layout_slot"], label=f"components[{index}].layout_slot"
        )
        if layout_slot not in LAYER_ROLE_LAYOUT_SLOTS[component["layer_role"]]:
            raise _error(
                f"components[{index}].layout_slot does not match layer_role"
            )
        _text(component["brief"], label=f"components[{index}].brief")
        validated_components.append(component)

    composition = validate_composition_contract(
        checked["composition"],
        validated_components,
        mode,
        label="visual strategy composition",
    )
    if (
        checked_intent["presenter_presence"] == "required"
        and composition["presenter_mode"] not in {"bottom_window", "full_frame"}
    ) or (
        checked_intent["presenter_presence"] == "hidden"
        and composition["presenter_mode"] != "hidden"
    ):
        raise _error("visual strategy presenter_mode does not match intent")

    protected, official, specific_event, real_product_ui = _intent_signals(checked_intent)
    for component in validated_components:
        kind = component["kind"]
        role = component["semantic_role"]
        if kind == "code_generated" and role == "evidence":
            raise _error("code_generated cannot serve as factual evidence")
        if protected and kind in {"external_stock", "ai_generated"} and role == "evidence":
            raise _error(f"{kind} cannot evidence a protected factual claim")
        if (
            real_product_ui
            and component["media_type"] == "ui_capture"
            and kind not in {"local_material", "official_material"}
        ):
            raise _error(
                "real-product UI capture requires local_material or official_material"
            )
        if (
            kind == "external_stock"
            and specific_event
            and role in {"evidence", "demonstration", "context"}
        ):
            raise _error("external_stock cannot represent a specific real event")

    if official and not any(
        component["kind"] == "official_material"
        and component["semantic_role"] == "evidence"
        for component in validated_components
    ):
        raise _error("verified official evidence is missing")
    return _copy(checked, label="visual strategy")


def _validate_render_window(value: object, *, index: int) -> None:
    window = _exact_dict(
        value, _RENDER_WINDOW_KEYS, label=f"components[{index}].render_window"
    )
    start = _integer(window["start_frame"], label="render_window.start_frame", minimum=0)
    end = _integer(window["end_frame"], label="render_window.end_frame", minimum=1)
    if end <= start:
        raise _error("render_window.end_frame must be greater than start_frame")
    _integer(window["z_index"], label="render_window.z_index")
    _text(window["layout_slot"], label="render_window.layout_slot")
    _opacity(window["opacity"], label="render_window.opacity")
    safe_zone = _exact_dict(
        window["safe_zone"], _SAFE_ZONE_KEYS, label="render_window.safe_zone"
    )
    for side in _SAFE_ZONE_KEYS:
        _integer(safe_zone[side], label=f"render_window.safe_zone.{side}", minimum=0)
    if safe_zone["left"] + safe_zone["right"] >= 1080:
        raise _error("render_window.safe_zone horizontal margins must total less than 1080")
    if safe_zone["top"] + safe_zone["bottom"] >= 1920:
        raise _error("render_window.safe_zone vertical margins must total less than 1920")


def _validate_artifact_contract(
    value: object, *, index: int, kind: str, media_type: str
) -> None:
    contract = _exact_dict(
        value, _ARTIFACT_KEYS, label=f"components[{index}].artifact_contract"
    )
    size = (contract["width"], contract["height"])
    allowed_sizes = {(1080, 1920)}
    if kind == "ai_generated" and media_type == "video" and contract["alpha"] is False:
        allowed_sizes.add((720, 1280))
    if (
        type(contract["width"]) is not int
        or type(contract["height"]) is not int
        or size not in allowed_sizes
        or type(contract["fps"]) is not int
        or contract["fps"] != 24
        or type(contract["alpha"]) is not bool
    ):
        raise _error("artifact_contract must be 1080x1920/24 fps, or 720x1280/24 fps for opaque AI video")


def _validate_native_motion_report(
    component: dict, invocation: dict, *, index: int
) -> None:
    label = f"components[{index}].invocation_record.semantic_motion"
    identity = _RELATION_MOTION_IDENTITY
    family = "relation"
    if component.get("dependency_id") == "hd-talking-head-semantic-state":
        families = ("replacement", "threshold", "delay", "hierarchy", "feedback")
        family = next((value for value in families if component.get("template_id")
                       == "hd-talking-head/semantic-state-" + value), None)
        if family is None:
            raise _error("unknown native SemanticState template")
        identity = {**identity,
            "dependency_id": "hd-talking-head-semantic-state",
            "template_id": "hd-talking-head/semantic-state-" + family,
            "entrypoint": "scripts/semantic_state_renderer_bundle.py",
            "source_entrypoint": "scripts/semantic_state_renderer_bundle.py",
            "primary_renderer": "SemanticState"}
    if any(component.get(field) != expected for field, expected in identity.items()):
        raise _error(
            "semantic_motion is not supported outside a native motion adapter"
        )
    report = _exact_dict(
        invocation["semantic_motion"],
        {"execution_status", "plan", "check_frames", "content_analysis_sha256"},
        label=label,
    )
    if report["execution_status"] != "planning_only":
        raise _error(f"{label}.execution_status must be planning_only")
    _sha256(
        report["content_analysis_sha256"],
        label=f"{label}.content_analysis_sha256",
    )
    plan = _dict(report["plan"], label=f"{label}.plan")
    if plan.get("family") != family:
        raise _error(f"native motion template accepts only the {family} family")
    window = component["render_window"]
    if plan.get("duration_frames") != window["end_frame"] - window["start_frame"]:
        raise _error("semantic_motion duration differs from render_window")

    # This reconstructs only the planner's structural/check-frame result.  The
    # source text is self-described here; current Job approval is authenticated
    # separately by the native adapter immediately before execution.
    from . import semantic_motion

    item = {
        "id": plan.get("content_item_id"),
        "source_text": plan.get("source_text"),
        "evidence_status": "supported",
    }
    try:
        rebuilt = semantic_motion.build_motion_plan(plan, approved_items=[item])
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(f"{label} structure is invalid: {exc}") from None
    expected = {
        **rebuilt,
        "content_analysis_sha256": report["content_analysis_sha256"],
    }
    if report != expected:
        raise _error(f"{label}.check_frames differs from the validated plan")


def native_motion_exit_window(component: object) -> tuple[int, int] | None:
    """Return the structurally validated native motion local exit window."""

    checked = _dict(component, label="RelationMotion component")
    if checked.get("kind") != "code_generated":
        return None
    invocation = _dict(
        checked.get("invocation_record"), label="RelationMotion invocation_record"
    )
    if "semantic_motion" not in invocation:
        return None
    _validate_native_motion_report(checked, invocation, index=0)
    exit_window = invocation["semantic_motion"]["plan"]["exit_window"]
    return exit_window["start_frame"], exit_window["end_frame"]


def relation_motion_exit_window(component: object) -> tuple[int, int] | None:
    """Retain the relation-only entry point for existing consumers."""
    checked = _dict(component, label="RelationMotion component")
    if checked.get("dependency_id") == "hd-talking-head-semantic-state":
        raise _error("RelationMotion entry point does not accept SemanticState")
    return native_motion_exit_window(checked)


def _validate_binding(component: dict, *, index: int) -> None:
    kind = component["kind"]
    binding_keys = _BINDING_KEYS[kind]
    if kind == 'official_material' and 'portrait_crop' in component:
        if component.get('media_type') != 'image':
            raise _error('official portrait crop supports static images only')
        binding_keys = binding_keys | {'portrait_crop'}
        official_portrait_crop(component)
    _exact_dict(
        component,
        _RECIPE_COMMON_KEYS | binding_keys,
        label=f"components[{index}] binding",
    )
    structured_fields = {"invocation_record", "semantic_families", "capacity", "portrait_crop"}
    for field in binding_keys - structured_fields:
        _text(component[field], label=f"components[{index}].{field}")
    for field in binding_keys:
        if field.endswith("sha256"):
            _sha256(component[field], label=f"components[{index}].{field}")
    if kind == "local_material":
        _job_relative_posix_path(
            component["job_path"], label=f"components[{index}].job_path"
        )
    elif kind == "official_material":
        _job_relative_posix_path(
            component["snapshot_path"], label=f"components[{index}].snapshot_path"
        )
        _https_url(component["source_url"], label=f"components[{index}].source_url")
    elif kind == "external_stock":
        _job_relative_posix_path(
            component["job_path"], label=f"components[{index}].job_path"
        )
        _job_relative_posix_path(
            component["license_snapshot"],
            label=f"components[{index}].license_snapshot",
        )
        _https_url(component["asset_page"], label=f"components[{index}].asset_page")
    if kind != "code_generated":
        return
    invocation = _dict(
        component["invocation_record"], label=f"components[{index}].invocation_record"
    )
    if "semantic_motion" in invocation:
        _validate_native_motion_report(component, invocation, index=index)
    if not {"argv", "exit_code"}.issubset(invocation):
        raise _error("code invocation_record is missing invocation fields")
    argv = _list(invocation["argv"], label="code invocation_record.argv")
    if not argv or any(type(argument) is not str or not argument for argument in argv):
        raise _error("code invocation_record.argv must be a non-empty list of strings")
    # The input recipe describes a request; only the executor's output receipt
    # can prove execution. Keep historical successful binding records readable.
    if invocation.get("status") == "planned":
        if invocation["exit_code"] is not None:
            raise _error("planned invocation_record.exit_code must be null")
    elif type(invocation["exit_code"]) is not int or invocation["exit_code"] != 0:
        raise _error("code invocation_record.exit_code must be zero")
    _text(component["primary_renderer"], label="code primary_renderer")

    origin = component["template_origin"]
    if origin not in _TEMPLATE_ORIGINS:
        raise _error(f"unsupported code template_origin: {origin}")
    adaptation_level = component["adaptation_level"]
    if adaptation_level not in _TEMPLATE_ADAPTATION_LEVELS:
        raise _error(f"unsupported code adaptation_level: {adaptation_level}")
    if origin == "verified_third_party" and adaptation_level == "structural":
        raise _error("structural adaptation cannot retain verified third-party provenance")
    _sha256(component["verification_id"], label="code verification_id")

    families = _list(
        component["semantic_families"], label="code semantic_families"
    )
    if (
        not families
        or any(type(family) is not str or not family.strip() for family in families)
        or len(set(families)) != len(families)
    ):
        raise _error("code semantic_families must contain unique non-empty strings")

    capacity = _exact_dict(
        component["capacity"],
        _TEMPLATE_CAPACITY_KEYS,
        label="code template capacity",
    )
    min_units = _integer(
        capacity["min_units"], label="code capacity.min_units", minimum=1
    )
    max_units = _integer(
        capacity["max_units"], label="code capacity.max_units", minimum=1
    )
    if min_units > max_units:
        raise _error("code capacity.min_units must not exceed capacity.max_units")
    _job_relative_posix_path(
        component["source_entrypoint"], label="code source_entrypoint"
    )


def validate_shot_recipe_v2(recipe: object) -> dict:
    """Validate an already-bound ShotRecipe v2 without invoking any executor."""
    checked = _exact_dict(recipe, _RECIPE_KEYS, label="shot recipe v2")
    if type(checked["schema_version"]) is not int or checked["schema_version"] != 2:
        raise _error("shot recipe schema_version must be two")
    _text(checked["segment_id"], label="shot recipe segment_id")
    _integer(checked["strategy_revision"], label="strategy_revision", minimum=1)
    components = _list(checked["components"], label="shot recipe components")
    composition_value = checked["composition"]
    family_hint = composition_value.get("family") if type(composition_value) is dict else None
    mode = _validate_mode_count(
        checked["mode"], components, label="shot recipe", family=family_hint
    )
    canvas = _exact_dict(checked["canvas"], {"width", "height", "fps"}, label="canvas")
    if (
        type(canvas["width"]) is not int
        or canvas["width"] != 1080
        or type(canvas["height"]) is not int
        or canvas["height"] != 1920
        or type(canvas["fps"]) is not int
        or canvas["fps"] != 24
    ):
        raise _error("shot recipe canvas must be 1080x1920 at 24 fps")
    if (
        type(checked["final_compositor"]) is not str
        or checked["final_compositor"] != "ffmpeg"
    ):
        raise _error("shot recipe final_compositor must be ffmpeg")

    component_ids: set[str] = set()
    for index, component_value in enumerate(components):
        component = _dict(component_value, label=f"shot recipe components[{index}]")
        if not _RECIPE_COMMON_KEYS.issubset(component):
            raise _error(f"shot recipe components[{index}] is missing common fields")
        component_id = _text(
            component["component_id"], label=f"components[{index}].component_id"
        )
        if component_id in component_ids:
            raise _error("shot recipe component_id must be unique")
        component_ids.add(component_id)
        kind = component["kind"]
        if type(kind) is not str or kind not in SOURCE_KINDS:
            raise _error(f"components[{index}].kind is invalid")
        role = component["semantic_role"]
        if type(role) is not str or role not in _SEMANTIC_ROLES:
            raise _error(f"components[{index}].semantic_role is invalid")
        layer_role = component["layer_role"]
        if type(layer_role) is not str or layer_role not in _LAYER_ROLES:
            raise _error(f"components[{index}].layer_role is invalid")
        _text(component["executor"], label=f"components[{index}].executor")
        media_type = component["media_type"]
        if type(media_type) is not str or media_type not in _MEDIA_TYPES:
            raise _error(f"components[{index}].media_type is invalid")
        _validate_render_window(component["render_window"], index=index)
        layout_slot = component["render_window"]["layout_slot"]
        if layout_slot not in LAYER_ROLE_LAYOUT_SLOTS[layer_role]:
            raise _error(
                f"components[{index}].render_window.layout_slot does not match layer_role"
            )
        _validate_artifact_contract(
            component["artifact_contract"], index=index, kind=kind, media_type=media_type
        )
        if (
            family_hint == "aroll_with_overlay"
            and component["artifact_contract"]["alpha"] is not True
        ):
            raise _error("aroll_with_overlay components must have alpha artifacts")
        _validate_binding(component, index=index)
    validate_composition_contract(
        checked["composition"],
        components,
        mode,
        label="shot recipe composition",
    )
    by_id = {c['component_id']: c for c in components}
    for component in components:
        alignment = component.get('invocation_record', {}).get('canvas_alignment')
        if alignment is None:
            continue
        if (not isinstance(alignment, dict) or set(alignment) != {'mode', 'base_component_id', 'base_sha256', 'layer_sha256'}
                or alignment['mode'] != 'identity' or family_hint != 'evidence_with_data_overlay'
                or component['kind'] != 'code_generated' or component['layer_role'] != 'annotation'
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': True}):
            raise _error('canvas alignment needs a transparent full-canvas hybrid annotation')
        base = by_id.get(alignment['base_component_id'])
        if (not base or base['layer_role'] != 'base' or base['render_window']['layout_slot'] != 'full_frame'
                or base['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': False}
                or any(base['render_window']['safe_zone'].values())):
            raise _error('canvas alignment needs a matching full-canvas opaque base')
        _sha256(alignment['base_sha256'], label='canvas alignment base_sha256')
        _sha256(alignment['layer_sha256'], label='canvas alignment layer_sha256')
    result = _copy(checked, label="shot recipe v2")
    for component in result["components"]:
        window = component["render_window"]
        window["opacity"] = _opacity(
            window["opacity"], label="render_window.opacity"
        )
    return result


def official_portrait_crop(binding: Mapping) -> dict | None:
    """Describe an in-bounds 9:16 crop without changing the original source identity."""
    crop = binding.get('portrait_crop')
    if crop is None:
        return None
    keys = {'source_sha256', 'source_width', 'source_height', 'x', 'y', 'width', 'height'}
    if (not isinstance(crop, dict) or set(crop) != keys
            or crop['source_sha256'] != binding.get('sha256')
            or any(type(crop[k]) is not int for k in keys - {'source_sha256'})
            or min(crop['source_width'], crop['source_height'], crop['width'], crop['height']) <= 0
            or min(crop['x'], crop['y']) < 0
            or crop['x'] + crop['width'] > crop['source_width']
            or crop['y'] + crop['height'] > crop['source_height']
            or crop['width'] * 16 != crop['height'] * 9):
        raise _error('official portrait crop must bind the same source and an in-bounds 9:16 rectangle')
    return dict(crop)


def stable_same_kind_candidates(candidates: object, expected_kind: str, *, framing_binding=None) -> list[dict]:
    """Filter hard gates and deterministically rank candidates of one kind."""
    if type(expected_kind) is not str or expected_kind not in SOURCE_KINDS:
        raise _error("expected_kind is invalid")
    checked = _list(candidates, label="candidates")
    validated: list[dict] = []
    for index, candidate_value in enumerate(checked):
        candidate = _exact_dict(
            candidate_value, _CANDIDATE_KEYS, label=f"candidates[{index}]"
        )
        _text(candidate["asset_id"], label=f"candidates[{index}].asset_id")
        kind = candidate["kind"]
        if type(kind) is not str or kind not in SOURCE_KINDS:
            raise _error(f"candidates[{index}].kind is invalid")
        if kind != expected_kind:
            raise _error("candidates must contain only the expected kind")
        _finite_number(
            candidate["semantic_match_score"],
            label=f"candidates[{index}].semantic_match_score",
        )
        _finite_number(
            candidate["quality_score"], label=f"candidates[{index}].quality_score"
        )
        gates = _exact_dict(
            candidate["hard_gates"], _GATE_KEYS, label=f"candidates[{index}].hard_gates"
        )
        if any(type(gates[gate]) is not bool for gate in _GATE_KEYS):
            raise _error(f"candidates[{index}].hard_gates values must be bool")
        validated.append(candidate)

    crop = official_portrait_crop(framing_binding) if expected_kind == 'official_material' and framing_binding else None
    eligible = [candidate for candidate in validated if all(
        passed or (gate == 'native_vertical' and crop is not None
                   and candidate['asset_id'] == framing_binding.get('source_id'))
        for gate, passed in candidate['hard_gates'].items())]
    if not eligible:
        raise _error("no same-kind candidate passed every hard gate")
    eligible.sort(
        key=lambda candidate: (
            -float(candidate["semantic_match_score"]),
            -float(candidate["quality_score"]),
            candidate["asset_id"],
        )
    )
    return _copy(eligible, label="candidate result")

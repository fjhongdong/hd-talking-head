"""Validate approved component composition and renderer responsibilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import visual_strategy


class BrollSystemError(RuntimeError):
    """Raised when an approved component composition is internally inconsistent."""


COMPONENT_FAILURE_ACTIONS = (
    "retry_same_strategy",
    "replan_visual_direction",
)

SUPPORTED_LAYOUT_SLOTS = frozenset(
    slot
    for slots in visual_strategy.LAYER_ROLE_LAYOUT_SLOTS.values()
    for slot in slots
)
COMPOSITION_FAMILIES = visual_strategy.COMPOSITION_FAMILIES


@dataclass(frozen=True)
class CompositionContract:
    family: str
    mode: str
    component_ids: tuple[str, ...]
    base_component_ids: tuple[str, ...]
    annotation_component_ids: tuple[str, ...]
    component_dependencies: tuple[tuple[str, tuple[str, ...]], ...]
    final_compositor: str = "ffmpeg"


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        try:
            return value[name]
        except KeyError:
            raise BrollSystemError("approved composition is incomplete") from None
    try:
        return getattr(value, name)
    except AttributeError:
        raise BrollSystemError("approved composition is incomplete") from None


def _renderer_values(evidence: object) -> set[str]:
    if not isinstance(evidence, Mapping):
        raise BrollSystemError("component renderer evidence is invalid")
    values: set[str] = set()
    direct = evidence.get("primary_renderer")
    if direct is not None:
        if type(direct) is not str or not direct:
            raise BrollSystemError("component renderer evidence is invalid")
        values.add(direct)
    receipt = evidence.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, Mapping):
            raise BrollSystemError("component renderer evidence is invalid")
        nested = receipt.get("primary_renderer")
        if type(nested) is not str or not nested:
            raise BrollSystemError("component renderer evidence is invalid")
        values.add(nested)
    return values


def validate_composition(
    recipe: Mapping[str, Any],
    artifacts: tuple[object, ...],
) -> CompositionContract:
    """Validate one approved family without selecting or rewriting a component kind."""

    try:
        checked_recipe = visual_strategy.validate_shot_recipe_v2(recipe)
    except visual_strategy.VisualStrategyError:
        raise BrollSystemError("approved composition is invalid") from None
    composition = checked_recipe["composition"]
    family = composition["family"]
    expected_mode = COMPOSITION_FAMILIES[family]
    components = checked_recipe["components"]
    if (
        checked_recipe["mode"] != expected_mode
        or checked_recipe["final_compositor"] != "ffmpeg"
        or type(components) is not list
        or (not components and family != "aroll_with_overlay")
        or type(artifacts) is not tuple
        or len(artifacts) != len(components)
    ):
        raise BrollSystemError("approved composition is invalid")

    component_ids: list[str] = []
    base_ids: list[str] = []
    annotation_ids: list[str] = []
    for component, artifact in zip(components, artifacts):
        if type(component) is not dict:
            raise BrollSystemError("approved component is invalid")
        component_id = component.get("component_id")
        kind = component.get("kind")
        layer_role = component.get("layer_role")
        window = component.get("render_window")
        if (
            type(component_id) is not str
            or not component_id
            or component_id in component_ids
            or type(kind) is not str
            or kind not in visual_strategy.SOURCE_KINDS
            or type(window) is not dict
            or _field(artifact, "component_id") != component_id
            or _field(artifact, "kind") != kind
        ):
            raise BrollSystemError("approved component binding is invalid")
        slot = window.get("layout_slot")
        allowed_slots = visual_strategy.LAYER_ROLE_LAYOUT_SLOTS.get(layer_role)
        if allowed_slots is None or slot not in allowed_slots:
            raise BrollSystemError("approved layout slot does not match layer role")
        if layer_role == "base":
            base_ids.append(component_id)
        elif layer_role == "annotation":
            annotation_ids.append(component_id)

        if kind == "code_generated":
            primary_renderer = component.get("primary_renderer")
            evidence_renderers = _renderer_values(
                _field(artifact, "invocation_evidence")
            )
            if (
                type(primary_renderer) is not str
                or not primary_renderer
                or evidence_renderers != {primary_renderer}
            ):
                raise BrollSystemError("code component renderer binding is inconsistent")
        if family == "aroll_with_overlay" and (
            layer_role != "annotation"
            or kind != "code_generated"
            or component.get("artifact_contract", {}).get("alpha") is not True
        ):
            raise BrollSystemError("aroll overlay must be alpha code annotations")
        component_ids.append(component_id)

    dependency_records: list[tuple[str, tuple[str, ...]]] = []
    by_id = {component["component_id"]: component for component in components}
    for dependency in composition["component_dependencies"]:
        dependent = by_id[dependency["component_id"]]
        dependent_window = dependent["render_window"]
        targets = tuple(dependency["depends_on"])
        if family == "aroll_with_overlay":
            raise BrollSystemError("aroll overlay must not declare dependencies")
        common_start = max(
            by_id[target_id]["render_window"]["start_frame"] for target_id in targets
        )
        common_end = min(
            by_id[target_id]["render_window"]["end_frame"] for target_id in targets
        )
        if (
            dependent_window["start_frame"] < common_start
            or dependent_window["end_frame"] > common_end
        ):
            raise BrollSystemError(
                "annotation frame window must fit every dependency window"
            )
        for target_id in targets:
            target_window = by_id[target_id]["render_window"]
            if dependent_window["z_index"] <= target_window["z_index"]:
                raise BrollSystemError(
                    "component dependency layer order or frame window is invalid"
                )
        dependency_records.append((dependency["component_id"], targets))

    return CompositionContract(
        family=family,
        mode=expected_mode,
        component_ids=tuple(component_ids),
        base_component_ids=tuple(base_ids),
        annotation_component_ids=tuple(annotation_ids),
        component_dependencies=tuple(dependency_records),
    )


__all__ = [
    "BrollSystemError",
    "COMPONENT_FAILURE_ACTIONS",
    "COMPOSITION_FAMILIES",
    "SUPPORTED_LAYOUT_SLOTS",
    "CompositionContract",
    "validate_composition",
]

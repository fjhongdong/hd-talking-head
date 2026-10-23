"""Capability contract for mapping semantic events to qualified TalkCraft cards."""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping

from .contract_artifacts import sha256_json


class CardEventCapabilityError(ValueError):
    """Raised when a card capability index cannot safely authorize a binding."""


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_STATUS = frozenset({"unknown", "verified"})
_EVENT_KINDS = frozenset({"segment", "selection", "moment"})
_ROLES = frozenset({"visual", "caption", "audio", "spatial", "transition"})


def _fail(message: str) -> None:
    raise CardEventCapabilityError(message)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if _IDENTIFIER.fullmatch(result) is None:
        _fail(f"{label} must be a safe identifier")
    return result


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase sha256")
    return value


def _strict(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} fields are invalid")
    return value


def _string_list(value: object, label: str, *, allowed: set[str] | None = None) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        _fail(f"{label} must be a list of non-empty text")
    if len(value) != len(set(value)):
        _fail(f"{label} must not contain duplicates")
    if allowed is not None and any(item not in allowed for item in value):
        _fail(f"{label} contains an unsupported value")
    return list(value)


def _validate_capability_record(value: object, label: str) -> dict[str, Any]:
    card = _strict(
        value,
        {
            "card_id", "status", "event_kinds", "output_roles", "required_media",
            "requires_presenter", "min_frames", "max_frames", "notes",
        },
        label,
    )
    card_id = _identifier(card["card_id"], f"{label}.card_id")
    status = _text(card["status"], f"{label}.status")
    if status not in _STATUS:
        _fail(f"{label}.status is unsupported")
    event_kinds = _string_list(card["event_kinds"], f"{label}.event_kinds", allowed=set(_EVENT_KINDS))
    output_roles = _string_list(card["output_roles"], f"{label}.output_roles", allowed=set(_ROLES))
    required_media = _string_list(card["required_media"], f"{label}.required_media", allowed={"presenter", "video", "image"})
    if type(card["requires_presenter"]) is not bool:
        _fail(f"{label}.requires_presenter must be boolean")
    if card["requires_presenter"] != ("presenter" in required_media):
        _fail(f"{label}.requires_presenter must agree with required_media")
    for field in ("min_frames", "max_frames"):
        if type(card[field]) is not int or card[field] < 1:
            _fail(f"{label}.{field} must be a positive integer")
    if card["max_frames"] < card["min_frames"]:
        _fail(f"{label} frame capacity is reversed")
    notes = _text(card["notes"], f"{label}.notes")
    return {
        "card_id": card_id,
        "status": status,
        "event_kinds": event_kinds,
        "output_roles": output_roles,
        "required_media": required_media,
        "requires_presenter": card["requires_presenter"],
        "min_frames": card["min_frames"],
        "max_frames": card["max_frames"],
        "notes": notes,
    }


def validate_card_event_capabilities(
    value: object,
    *,
    qualified_card_ids: Iterable[str] | None = None,
    expected_registry_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate a capability sidecar without granting qualification status."""

    index = _strict(
        value,
        {"schema_version", "registry_version", "registry_sha256", "cards", "index_sha256"},
        "card event capability index",
    )
    if index["schema_version"] != "talkcraft-card-event-capabilities/v1":
        _fail("unsupported card event capability schema")
    _identifier(index["registry_version"], "registry_version")
    registry_hash = _sha(index["registry_sha256"], "registry_sha256")
    if expected_registry_sha256 is not None and registry_hash != _sha(expected_registry_sha256, "expected_registry_sha256"):
        _fail("capability index is bound to a different registry")
    qualified = None if qualified_card_ids is None else {_identifier(item, "qualified_card_id") for item in qualified_card_ids}
    cards_value = index["cards"]
    if type(cards_value) is not list or not cards_value:
        _fail("cards must be a non-empty list")
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item_index, raw_card in enumerate(cards_value):
        card = _validate_capability_record(raw_card, f"cards[{item_index}]")
        card_id = card["card_id"]
        if card_id in seen:
            _fail("card_id values must be unique")
        seen.add(card_id)
        if qualified is not None and card_id not in qualified:
            _fail(f"capability card is not qualified: {card_id}")
        cards.append(copy.deepcopy(card))
    unsigned = {
        "schema_version": index["schema_version"],
        "registry_version": index["registry_version"],
        "registry_sha256": registry_hash,
        "cards": cards,
    }
    if index["index_sha256"] != sha256_json(unsigned):
        _fail("card event capability index hash does not match its contents")
    return {**unsigned, "index_sha256": index["index_sha256"]}


def can_card_consume_event(
    capability: Mapping[str, object],
    *,
    event_kind: str,
    output_role: str,
    available_media: Iterable[str] = (),
    presenter_required: bool = False,
    frame_count: int | None = None,
) -> bool:
    """Return a conservative authorization result for a frozen event binding."""

    try:
        capability = _validate_capability_record(capability, "capability")
    except CardEventCapabilityError:
        return False
    if capability.get("status") != "verified":
        return False
    if type(event_kind) is not str or type(output_role) is not str:
        return False
    if event_kind not in _EVENT_KINDS or output_role not in _ROLES:
        return False
    if event_kind not in capability["event_kinds"] or output_role not in capability["output_roles"]:
        return False
    try:
        media = set(available_media)
    except (TypeError, ValueError):
        return False
    if not media.issubset({"presenter", "video", "image"}):
        return False
    required = set(capability.get("required_media", ()))
    if not required.issubset(media):
        return False
    if presenter_required and not capability.get("requires_presenter"):
        return False
    if frame_count is not None and (type(frame_count) is not int or frame_count < 1):
        return False
    if frame_count is not None and not (
        capability.get("min_frames", 0) <= frame_count <= capability.get("max_frames", -1)
    ):
        return False
    return True

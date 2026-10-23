"""Strict contracts for the HD TalkCraft card registry and render briefs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .contract_artifacts import canonical_json_bytes


class TalkCraftContractError(ValueError):
    """Raised before rendering when a TalkCraft identity or brief is invalid."""


INTEGRATION_ROOT = Path(__file__).parents[1] / "integrations" / "talkcraft"
DEFAULT_UPSTREAM_MANIFEST = INTEGRATION_ROOT / "upstream-manifest.json"
DEFAULT_CARD_REGISTRY = INTEGRATION_ROOT / "runtime" / "card-registry.json"
DEPENDENCY_ID = "hd-talking-head-talkcraft"
PRIMARY_RENDERER = "Remotion"
MAX_CHUNK_FRAMES = 720

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CARD_KEYS = {"card_id", "category", "upstream", "production"}
_UPSTREAM_KEYS = {
    "reference_sha256",
    "source_sha256",
    "demo_sha256",
    "workbench_sha256",
}
_PRODUCTION_KEYS = {
    "status",
    "production_role",
    "layer_roles",
    "derived_entrypoint",
    "implementation_sha256",
    "input_adapter_sha256",
    "adapter_version",
    "qualification_id",
}
_OWNER_KEYS = {
    "type", "id", "chunk_id", "visual_plan_sha256",
    "spec_sha256", "scene_brief_sha256",
}
_COMPONENT_TARGET_KEYS = {"kind", "segment_id", "component_id"}
_BOUNDARY_TARGET_KEYS = {"kind", "boundary_id", "card_slot_id"}


def _fail(message: str) -> None:
    raise TalkCraftContractError(message)


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


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} fields are invalid")
    return value


def _load_json_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TalkCraftContractError(f"{label} is unreadable") from exc
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    return value, payload


def _load_json(path: Path, label: str) -> dict[str, Any]:
    return _load_json_bytes(path, label)[0]


def _job_path(value: object, label: str) -> str:
    result = _text(value, label)
    path = PurePosixPath(result)
    if (
        path.is_absolute()
        or ".." in path.parts
        or result.startswith("./")
        or "://" in result
        or "\\" in result
    ):
        _fail(f"{label} must be a safe Job-relative path")
    return result


def validate_card_registry(
    value: object,
    *,
    upstream_manifest_path: Path = DEFAULT_UPSTREAM_MANIFEST,
) -> dict[str, Any]:
    """Validate the unique 108-card registry against the pinned upstream manifest."""

    registry = _exact(
        value,
        {
            "schema_version",
            "registry_version",
            "upstream_manifest",
            "runtime_compatibility",
            "qualification_policy",
            "cards",
        },
        "TalkCraft registry",
    )
    if registry["schema_version"] != "talkcraft-card-registry/v1":
        _fail("unsupported TalkCraft registry schema")
    registry_version = _identifier(registry["registry_version"], "registry_version")
    manifest_binding = _exact(
        registry["upstream_manifest"],
        {"path", "sha256", "repository", "commit"},
        "upstream_manifest",
    )
    _text(manifest_binding["path"], "upstream_manifest.path")
    _sha(manifest_binding["sha256"], "upstream_manifest.sha256")
    _text(manifest_binding["repository"], "upstream_manifest.repository")
    if type(manifest_binding["commit"]) is not str or _GIT_COMMIT.fullmatch(manifest_binding["commit"]) is None:
        _fail("upstream_manifest.commit must be a full lowercase Git commit")
    upstream, upstream_bytes = _load_json_bytes(
        upstream_manifest_path, "upstream manifest"
    )
    if hashlib.sha256(upstream_bytes).hexdigest() != manifest_binding["sha256"]:
        _fail("upstream manifest hash does not match the pinned registry")
    if upstream.get("schema_version") != "talkcraft-upstream-manifest/v1":
        _fail("unsupported upstream manifest schema")
    source = upstream.get("source")
    if type(source) is not dict or source.get("repository") != manifest_binding["repository"] or source.get("commit") != manifest_binding["commit"]:
        _fail("upstream source identity does not match the registry")
    runtime_compatibility = _exact(
        registry["runtime_compatibility"],
        {
            "path", "sha256", "source_closure_sha256",
            "target_closure_sha256", "covered_qualifications",
        },
        "runtime_compatibility",
    )
    _job_path(runtime_compatibility["path"], "runtime_compatibility.path")
    _sha(runtime_compatibility["sha256"], "runtime_compatibility.sha256")
    _sha(runtime_compatibility["source_closure_sha256"], "runtime_compatibility.source_closure_sha256")
    _sha(runtime_compatibility["target_closure_sha256"], "runtime_compatibility.target_closure_sha256")
    if type(runtime_compatibility["covered_qualifications"]) is not int or runtime_compatibility["covered_qualifications"] < 1:
        _fail("runtime_compatibility.covered_qualifications must be positive")
    policy = _exact(
        registry["qualification_policy"],
        {"state", "production_enabled", "legacy_registry_inherited"},
        "qualification_policy",
    )
    if (
        policy["state"] not in {
            "pending_new_qualification",
            "partially_qualified",
            "qualified",
        }
        or type(policy["production_enabled"]) is not bool
        or policy["legacy_registry_inherited"] is not False
    ):
        _fail("TalkCraft qualification policy is invalid")
    source_cards = upstream.get("cards")
    cards = registry["cards"]
    if type(source_cards) is not list or len(source_cards) != 108 or type(cards) is not list or len(cards) != 108:
        _fail("TalkCraft registry must contain exactly 108 cards")
    upstream_by_id = {item.get("card_id"): item for item in source_cards if type(item) is dict}
    if len(upstream_by_id) != 108:
        _fail("upstream card identities are not unique")
    normalized_cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(cards):
        card = _exact(item, _CARD_KEYS, f"cards[{index}]")
        card_id = _identifier(card["card_id"], f"cards[{index}].card_id")
        if card_id in seen or card_id not in upstream_by_id:
            _fail("TalkCraft registry card set differs from upstream")
        seen.add(card_id)
        source_card = upstream_by_id[card_id]
        if card["category"] != source_card.get("category"):
            _fail(f"category changed for {card_id}")
        hashes = _exact(card["upstream"], _UPSTREAM_KEYS, f"cards[{index}].upstream")
        if hashes != source_card.get("upstream"):
            _fail(f"upstream hashes changed for {card_id}")
        for key, digest in hashes.items():
            _sha(digest, f"cards[{index}].upstream.{key}")
        production = _exact(card["production"], _PRODUCTION_KEYS, f"cards[{index}].production")
        _text(production["production_role"], f"cards[{index}].production_role")
        roles = production["layer_roles"]
        if type(roles) is not list or not roles or any(role not in {"base", "overlay", "inset", "annotation"} for role in roles) or len(roles) != len(set(roles)):
            _fail(f"invalid layer roles for {card_id}")
        if production["status"] == "pending_portrait_adapter":
            if any(production[field] is not None for field in {"derived_entrypoint", "implementation_sha256", "input_adapter_sha256", "adapter_version", "qualification_id"}):
                _fail(f"pending card {card_id} must not claim a production identity")
        elif production["status"] == "qualified":
            _job_path(production["derived_entrypoint"], f"cards[{index}].derived_entrypoint")
            _sha(production["implementation_sha256"], f"cards[{index}].implementation_sha256")
            _sha(production["input_adapter_sha256"], f"cards[{index}].input_adapter_sha256")
            _text(production["adapter_version"], f"cards[{index}].adapter_version")
            _sha(production["qualification_id"], f"cards[{index}].qualification_id")
        else:
            _fail(f"invalid production status for {card_id}")
        normalized_cards.append(copy.deepcopy(card))
    if seen != set(upstream_by_id):
        _fail("TalkCraft registry card set differs from upstream")
    qualified_count = sum(
        card["production"]["status"] == "qualified"
        for card in normalized_cards
    )
    expected_policy = (
        ("pending_new_qualification", False)
        if qualified_count == 0
        else ("qualified", True)
        if qualified_count == 108
        else ("partially_qualified", True)
    )
    if (policy["state"], policy["production_enabled"]) != expected_policy:
        _fail("TalkCraft qualification policy differs from its card states")
    return {
        "schema_version": "talkcraft-card-registry/v1",
        "registry_version": registry_version,
        "upstream_manifest": copy.deepcopy(manifest_binding),
        "runtime_compatibility": copy.deepcopy(runtime_compatibility),
        "qualification_policy": copy.deepcopy(policy),
        "cards": normalized_cards,
    }


def load_card_registry(path: Path = DEFAULT_CARD_REGISTRY) -> dict[str, Any]:
    return _load_card_registry_with_sha256(path)[0]


def _load_card_registry_with_sha256(
    path: Path = DEFAULT_CARD_REGISTRY,
) -> tuple[dict[str, Any], str]:
    value, payload = _load_json_bytes(path, "TalkCraft registry")
    return validate_card_registry(value), hashlib.sha256(payload).hexdigest()


def _json_value(value: object, label: str) -> Any:
    try:
        encoded = canonical_json_bytes(value)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TalkCraftContractError(f"{label} must be finite JSON") from exc
    return decoded


def _validate_brief(
    value: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    allow_pending: bool,
) -> dict[str, Any]:
    brief = _exact(
        value,
        {
            "schema_version", "card_id", "registry", "owner", "content_item_ids",
            "text", "numbers", "canvas", "frame_scope", "events", "media",
            "style", "presentation_kind", "render", "execution_target",
        },
        "TalkCraftProductionBrief",
    )
    if brief["schema_version"] != "talkcraft-production-brief/v1":
        _fail("unsupported TalkCraft production brief schema")
    registry, registry_sha256 = _load_card_registry_with_sha256(registry_path)
    registry_binding = _exact(brief["registry"], {"version", "sha256"}, "registry")
    if registry_binding["version"] != registry["registry_version"] or _sha(registry_binding["sha256"], "registry.sha256") != registry_sha256:
        _fail("production brief registry identity is stale")
    card_id = _identifier(brief["card_id"], "card_id")
    card = next((item for item in registry["cards"] if item["card_id"] == card_id), None)
    if card is None:
        _fail("unknown TalkCraft card_id")
    if card["production"]["status"] != "qualified" and not allow_pending:
        _fail("TalkCraft card is not qualified for production")
    owner = _exact(
        brief["owner"],
        _OWNER_KEYS,
        "owner",
    )
    if owner["type"] not in {"segment", "span"}:
        _fail("owner.type must be segment or span")
    _identifier(owner["id"], "owner.id")
    _sha(owner["visual_plan_sha256"], "owner.visual_plan_sha256")
    if owner["type"] == "segment":
        if any(owner[field] is not None for field in {"chunk_id", "spec_sha256", "scene_brief_sha256"}):
            _fail("segment-owned brief cannot claim span identities")
    if owner["type"] == "span":
        _identifier(owner["chunk_id"], "owner.chunk_id")
        _sha(owner["spec_sha256"], "owner.spec_sha256")
        _sha(owner["scene_brief_sha256"], "owner.scene_brief_sha256")
    target = brief["execution_target"]
    if type(target) is not dict or target.get("kind") not in {"component", "boundary"}:
        _fail("execution_target is invalid")
    if target["kind"] == "component":
        target = _exact(target, _COMPONENT_TARGET_KEYS, "execution_target")
        _identifier(target["segment_id"], "execution_target.segment_id")
        _identifier(target["component_id"], "execution_target.component_id")
    else:
        target = _exact(target, _BOUNDARY_TARGET_KEYS, "execution_target")
        _identifier(target["boundary_id"], "execution_target.boundary_id")
        _identifier(target["card_slot_id"], "execution_target.card_slot_id")
    content_ids = brief["content_item_ids"]
    if type(content_ids) is not list or not content_ids or len(content_ids) != len(set(content_ids)):
        _fail("content_item_ids must be a unique non-empty list")
    for item in content_ids:
        _identifier(item, "content_item_id")
    text = _exact(brief["text"], {"spoken", "display"}, "text")
    _text(text["spoken"], "text.spoken")
    _text(text["display"], "text.display")
    numbers = brief["numbers"]
    if type(numbers) is not list:
        _fail("numbers must be a list")
    for index, item in enumerate(numbers):
        number = _exact(item, {"raw", "display", "unit"}, f"numbers[{index}]")
        if type(number["raw"]) not in {int, float} or not math.isfinite(float(number["raw"])):
            _fail(f"numbers[{index}].raw must be finite")
        _text(number["display"], f"numbers[{index}].display")
        if number["unit"] is not None:
            _text(number["unit"], f"numbers[{index}].unit")
    canvas = _exact(brief["canvas"], {"width", "height", "fps"}, "canvas")
    if canvas != {"width": 1080, "height": 1920, "fps": 24}:
        _fail("TalkCraft canvas must be 1080x1920 at 24 fps")
    scope = _exact(
        brief["frame_scope"],
        {"global_start_frame", "global_end_frame", "span_start_frame", "span_end_frame", "scene_duration_frames", "enter_frames", "exit_frames"},
        "frame_scope",
    )
    for key in scope:
        _integer(scope[key], f"frame_scope.{key}")
    if not (scope["global_start_frame"] < scope["global_end_frame"] and scope["span_start_frame"] < scope["span_end_frame"] <= scope["scene_duration_frames"]):
        _fail("frame_scope ranges are invalid")
    if scope["global_end_frame"] - scope["global_start_frame"] != scope["span_end_frame"] - scope["span_start_frame"]:
        _fail("global and span-local output ranges must have equal duration")
    if scope["global_end_frame"] - scope["global_start_frame"] > MAX_CHUNK_FRAMES:
        _fail("TalkCraft output chunk exceeds 720 frames")
    if scope["enter_frames"] + scope["exit_frames"] > scope["scene_duration_frames"]:
        _fail("enter and exit actions exceed the scene")
    events = brief["events"]
    if type(events) is not list:
        _fail("events must be a list")
    anchors: set[str] = set()
    previous_frame = -1
    for index, item in enumerate(events):
        event = _exact(item, {"anchor_id", "type", "frame", "payload"}, f"events[{index}]")
        anchor = _identifier(event["anchor_id"], f"events[{index}].anchor_id")
        if anchor in anchors:
            _fail("event anchor_id must be unique")
        anchors.add(anchor)
        if event["type"] not in {"text", "data", "target", "media", "sfx"}:
            _fail(f"events[{index}].type is invalid")
        frame = _integer(event["frame"], f"events[{index}].frame")
        if frame < previous_frame or frame >= scope["scene_duration_frames"]:
            _fail("event frames must be ordered inside the scene")
        previous_frame = frame
        _json_value(event["payload"], f"events[{index}].payload")
    media = brief["media"]
    if type(media) is not list:
        _fail("media must be a list")
    for index, item in enumerate(media):
        medium = _exact(item, {"job_path", "sha256", "width", "height", "fps", "start_frame", "end_frame", "source_kind", "authorization_ref"}, f"media[{index}]")
        _job_path(medium["job_path"], f"media[{index}].job_path")
        _sha(medium["sha256"], f"media[{index}].sha256")
        _integer(medium["width"], f"media[{index}].width", minimum=1)
        _integer(medium["height"], f"media[{index}].height", minimum=1)
        if type(medium["fps"]) not in {int, float} or not math.isfinite(float(medium["fps"])) or medium["fps"] <= 0:
            _fail(f"media[{index}].fps must be positive")
        start = _integer(medium["start_frame"], f"media[{index}].start_frame")
        end = _integer(medium["end_frame"], f"media[{index}].end_frame", minimum=1)
        if end <= start:
            _fail(f"media[{index}] range is invalid")
        if medium["source_kind"] not in {"local_material", "official_material", "external_stock", "ai_generated", "presenter"}:
            _fail(f"media[{index}].source_kind is invalid")
        _text(medium["authorization_ref"], f"media[{index}].authorization_ref")
    style = _exact(brief["style"], {"theme", "background", "frame", "layout", "max_scale", "presenter_safe_zone"}, "style")
    for field in {"theme", "background", "frame", "layout"}:
        _identifier(style[field], f"style.{field}")
    if type(style["max_scale"]) not in {int, float} or not math.isfinite(float(style["max_scale"])) or not 0 < style["max_scale"] <= 2:
        _fail("style.max_scale must be in (0, 2]")
    zone = _exact(style["presenter_safe_zone"], {"top", "bottom", "left", "right"}, "presenter_safe_zone")
    for side in zone:
        _integer(zone[side], f"presenter_safe_zone.{side}")
    if brief["presentation_kind"] not in {"evidence", "redrawn_illustration", "simulated_ui"}:
        _fail("presentation_kind is invalid")
    render = _exact(
        brief["render"],
        {"dependency_id", "entrypoint", "implementation_sha256", "adapter_version", "qualification_id", "renderer", "output_media_type", "alpha", "duration_frames"},
        "render",
    )
    if render["dependency_id"] != DEPENDENCY_ID or render["renderer"] != PRIMARY_RENDERER:
        _fail("TalkCraft render dependency is invalid")
    _job_path(render["entrypoint"], "render.entrypoint")
    production = card["production"]
    if production["status"] == "qualified":
        for field in {"implementation_sha256", "adapter_version", "qualification_id"}:
            if render[field] != production[field]:
                _fail(f"render.{field} differs from the qualified card identity")
        if render["entrypoint"] != production["derived_entrypoint"]:
            _fail("render.entrypoint differs from the qualified card identity")
    elif any(render[field] is not None for field in {"implementation_sha256", "adapter_version", "qualification_id"}):
        _fail("pending card must not claim a qualified render identity")
    if render["output_media_type"] not in {"video", "animation"} or type(render["alpha"]) is not bool:
        _fail("TalkCraft render output contract is invalid")
    if _integer(render["duration_frames"], "render.duration_frames", minimum=1) != scope["global_end_frame"] - scope["global_start_frame"]:
        _fail("render duration differs from the output frame range")
    return copy.deepcopy(brief)


def validate_production_brief(
    value: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    """Validate a qualified, hash-bound brief immediately before execution."""

    return _validate_brief(value, registry_path=registry_path, allow_pending=False)


def validate_draft_brief(
    value: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    """Validate structure for preview/editing without granting production use."""

    return _validate_brief(value, registry_path=registry_path, allow_pending=True)


def _validate_brief_bundle(
    value: object,
    *,
    registry_path: Path,
    allow_pending: bool,
) -> dict[str, Any]:
    bundle = _exact(
        value,
        {"schema_version", "owner", "briefs", "bundle_sha256"},
        "TalkCraftBriefBundle",
    )
    if bundle["schema_version"] != "talkcraft-brief-bundle/v1":
        _fail("unsupported TalkCraft brief bundle schema")
    owner = _exact(bundle["owner"], _OWNER_KEYS, "bundle.owner")
    if owner["type"] != "span":
        _fail("TalkCraft brief bundle must be span-owned")
    entries = bundle["briefs"]
    if type(entries) is not list or not entries:
        _fail("TalkCraft brief bundle must contain briefs")
    normalized: list[dict[str, Any]] = []
    target_keys: set[tuple[str, ...]] = set()
    validator = validate_draft_brief if allow_pending else validate_production_brief
    for index, raw in enumerate(entries):
        entry = _exact(raw, {"brief", "brief_sha256"}, f"briefs[{index}]")
        brief = validator(entry["brief"], registry_path=registry_path)
        brief_digest = hashlib.sha256(canonical_json_bytes(brief)).hexdigest()
        if _sha(entry["brief_sha256"], f"briefs[{index}].brief_sha256") != brief_digest:
            _fail("TalkCraft brief identity changed")
        if brief["owner"] != owner:
            _fail("TalkCraft briefs must share the bundle owner")
        target = brief["execution_target"]
        target_key = tuple(str(target[key]) for key in sorted(target))
        if target_key in target_keys:
            _fail("TalkCraft execution_target must be unique")
        target_keys.add(target_key)
        normalized.append({"brief": brief, "brief_sha256": brief_digest})
    unsigned = {
        "schema_version": "talkcraft-brief-bundle/v1",
        "owner": copy.deepcopy(owner),
        "briefs": normalized,
    }
    expected = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    if _sha(bundle["bundle_sha256"], "bundle_sha256") != expected:
        _fail("TalkCraft brief bundle identity changed")
    return {**unsigned, "bundle_sha256": expected}


def validate_production_brief_bundle(
    value: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    return _validate_brief_bundle(
        value, registry_path=registry_path, allow_pending=False
    )


def validate_draft_brief_bundle(
    value: object,
    *,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
) -> dict[str, Any]:
    return _validate_brief_bundle(
        value, registry_path=registry_path, allow_pending=True
    )


def brief_sha256(value: object, *, registry_path: Path = DEFAULT_CARD_REGISTRY) -> str:
    return hashlib.sha256(canonical_json_bytes(validate_production_brief(value, registry_path=registry_path))).hexdigest()


def draft_brief_sha256(value: object, *, registry_path: Path = DEFAULT_CARD_REGISTRY) -> str:
    return hashlib.sha256(canonical_json_bytes(validate_draft_brief(value, registry_path=registry_path))).hexdigest()


__all__ = [
    "TalkCraftContractError", "DEFAULT_CARD_REGISTRY", "DEFAULT_UPSTREAM_MANIFEST",
    "DEPENDENCY_ID", "PRIMARY_RENDERER", "MAX_CHUNK_FRAMES", "validate_card_registry",
    "load_card_registry", "validate_production_brief", "validate_draft_brief",
    "validate_production_brief_bundle", "validate_draft_brief_bundle",
    "brief_sha256", "draft_brief_sha256",
]

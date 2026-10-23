"""Deterministically match approved speech intent to qualified TalkCraft cards."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .card_event_capabilities import (
    can_card_consume_event,
    validate_card_event_capabilities,
)
from .contract_artifacts import read_json_artifact
from .talkcraft_contract import (
    DEFAULT_CARD_REGISTRY,
    DEPENDENCY_ID,
    PRIMARY_RENDERER,
    load_card_registry,
)


class TalkCraftMatchError(ValueError):
    pass


_CARDS_ROOT = DEFAULT_CARD_REGISTRY.parents[1] / "upstream" / "references" / "cards"
DEFAULT_SEMANTIC_INDEX = DEFAULT_CARD_REGISTRY.with_name("card-semantic-index.json")
DEFAULT_EVENT_CAPABILITIES = DEFAULT_CARD_REGISTRY.with_name("card-event-capabilities.json")
EXPECTED_SEMANTIC_INDEX_SHA256 = "316dd5ff9f101fe20c16af8d62dddf57a39f5064862f2ef2361550a7cacd1889"
_RENDERER_VERSION = "4.0.520"
_ROLE_VALUES = frozenset({"scene", "overlay", "annotation", "transition", "camera"})
_MEDIA_VALUES = frozenset({"presenter", "video", "image"})
_CATEGORY_FAMILIES = {
    "字幕花字": ("thesis", "emphasis", "kinetic_text"),
    "数据信息图": ("explanation", "data_summary", "comparison", "process"),
    "素材呈现": ("explanation", "evidence", "demonstration", "comparison"),
    "强调标注": ("emphasis", "annotation", "focus"),
    "转场结构": ("transition", "chapter_change"),
    "人物互动": ("presenter_interaction", "explanation", "call_to_action"),
    "运镜": ("camera_move", "reveal", "focus"),
}
_ID_FAMILIES = {
    "chart": "data_summary", "number": "numeric_comparison", "metric": "metric",
    "timeline": "timeline", "step": "process", "compare": "comparison",
    "quote": "quote", "title": "thesis", "word": "kinetic_text",
    "text": "kinetic_text", "highlight": "emphasis", "underline": "emphasis",
    "annotation": "annotation", "callout": "annotation", "transition": "transition",
    "zoom": "camera_move", "focus": "focus", "ui": "ui_demo", "code": "code_demo",
    "map": "map", "host": "presenter_interaction", "follow": "call_to_action",
}
_MEDIA_HEADERS = {"口播视频": "presenter", "B-roll 视频": "video", "图片": "image"}


def _fail(message: str) -> None:
    raise TalkCraftMatchError(message)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        _fail(f"{label} must be non-empty text")
    return value.strip()


def _text_list(values: Iterable[str], label: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        _fail(f"{label} must be a sequence of text values")
    result = []
    for value in values:
        item = _text(value, label)
        if item not in result:
            result.append(item)
    return result


def _frontmatter(source: str, card_id: str) -> tuple[dict[str, str], str]:
    if not source.startswith("---\n") or "\n---\n" not in source[4:]:
        _fail(f"TalkCraft reference frontmatter is invalid: {card_id}")
    header, body = source[4:].split("\n---\n", 1)
    values: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    for key in ("name", "标题", "一句话", "适用", "类别"):
        if not values.get(key):
            _fail(f"TalkCraft reference is missing {key}: {card_id}")
    if values["name"] != card_id:
        _fail(f"TalkCraft reference name differs from card_id: {card_id}")
    return values, body


def _media_contract(body: str) -> tuple[list[str], list[str]]:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if "| 口播视频 | B-roll 视频 | 图片 |" not in line or index + 2 >= len(lines):
            continue
        cells = [cell.strip() for cell in lines[index + 2].strip().strip("|").split("|")]
        if len(cells) != 3:
            break
        allowed: list[str] = []
        required: list[str] = []
        for header, cell in zip(_MEDIA_HEADERS, cells):
            medium = _MEDIA_HEADERS[header]
            if "不适用" not in cell and "不建议" not in cell:
                allowed.append(medium)
            if "默认输入" in cell:
                required.append(medium)
        return allowed, required
    return [], []


def _families(card_id: str, category: str) -> list[str]:
    values = list(_CATEGORY_FAMILIES.get(category, ("explanation",)))
    for token in card_id.split("-"):
        family = _ID_FAMILIES.get(token)
        if family and family not in values:
            values.append(family)
    return values


def build_semantic_index(
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    *,
    cards_root: Path = _CARDS_ROOT,
) -> dict[str, Any]:
    """Build the locked semantic index from the pinned 108 card references."""

    registry = load_card_registry(registry_path)
    cards: list[dict[str, Any]] = []
    for card in registry["cards"]:
        production = card["production"]
        if production["status"] != "qualified":
            continue
        path = cards_root / f"{card['card_id']}.md"
        try:
            payload = path.read_bytes()
            source = payload.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise TalkCraftMatchError(
                f"TalkCraft reference is unavailable: {card['card_id']}"
            ) from error
        if hashlib.sha256(payload).hexdigest() != card["upstream"]["reference_sha256"]:
            _fail(f"TalkCraft reference identity changed: {card['card_id']}")
        metadata, body = _frontmatter(source, card["card_id"])
        if metadata["类别"] != card["category"]:
            _fail(f"TalkCraft reference category changed: {card['card_id']}")
        allowed_media, required_media = _media_contract(body)
        cards.append({
            "card_id": card["card_id"],
            "reference_sha256": card["upstream"]["reference_sha256"],
            "title": metadata["标题"],
            "summary": metadata["一句话"],
            "suitable_for": metadata["适用"],
            "category": card["category"],
            "production_role": production["production_role"],
            "layer_roles": list(production["layer_roles"]),
            "semantic_families": _families(card["card_id"], card["category"]),
            "allowed_media": allowed_media,
            "required_media": required_media,
            "search_text": " ".join((metadata["标题"], metadata["一句话"], metadata["适用"], body)),
        })
    if len(cards) != 108:
        _fail("TalkCraft automatic matching requires all 108 cards to be qualified")
    return {
        "schema_version": "talkcraft-card-semantic-index/v1",
        "registry_version": registry["registry_version"],
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "cards": cards,
    }


def load_card_catalog(
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    *,
    index_path: Path = DEFAULT_SEMANTIC_INDEX,
) -> list[dict[str, Any]]:
    """Load the locked index and join it to the current qualified identities."""

    registry = load_card_registry(registry_path)
    try:
        index_payload = index_path.read_bytes()
        index = json.loads(index_payload.decode("utf-8"))
        registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TalkCraftMatchError("TalkCraft semantic index is unavailable") from error
    if (
        hashlib.sha256(index_payload).hexdigest() != EXPECTED_SEMANTIC_INDEX_SHA256
        or type(index) is not dict
        or set(index) != {"schema_version", "registry_version", "registry_sha256", "cards"}
        or index["schema_version"] != "talkcraft-card-semantic-index/v1"
        or index["registry_version"] != registry["registry_version"]
        or index["registry_sha256"] != registry_sha256
        or type(index["cards"]) is not list
        or len(index["cards"]) != 108
    ):
        _fail("TalkCraft semantic index differs from the qualified registry")
    registry_by_id = {card["card_id"]: card for card in registry["cards"]}
    indexed_ids = [card.get("card_id") for card in index["cards"] if type(card) is dict]
    if len(indexed_ids) != len(set(indexed_ids)) or set(indexed_ids) != set(registry_by_id):
        _fail("TalkCraft semantic index card set is invalid")
    catalog: list[dict[str, Any]] = []
    expected_keys = {
        "card_id", "reference_sha256", "title", "summary", "suitable_for",
        "category", "production_role", "layer_roles", "semantic_families",
        "allowed_media", "required_media", "search_text",
    }
    for item in index["cards"]:
        if set(item) != expected_keys:
            _fail("TalkCraft semantic index card fields are invalid")
        source = registry_by_id[item["card_id"]]
        production = source["production"]
        if (
            production["status"] != "qualified"
            or item["reference_sha256"] != source["upstream"]["reference_sha256"]
            or item["category"] != source["category"]
            or item["production_role"] != production["production_role"]
            or item["layer_roles"] != production["layer_roles"]
        ):
            _fail(f"TalkCraft semantic index identity changed: {item['card_id']}")
        catalog.append({
            **item,
            "production": dict(production),
            "sample_sha256": source["upstream"]["demo_sha256"],
        })
    return catalog


def _features(value: str) -> set[str]:
    normalized = value.lower()
    latin = set(re.findall(r"[a-z0-9]+", normalized))
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk: set[str] = set()
    for run in cjk_runs:
        cjk.update(run)
        cjk.update(run[index:index + 2] for index in range(len(run) - 1))
    return latin | cjk


def match_cards(
    transcript: str,
    *,
    semantic_family: str,
    semantic_goals: Iterable[str] = (),
    keywords: Iterable[str] = (),
    information_units: int = 1,
    target_role: str | None = None,
    available_media: Iterable[str] = (),
    presenter_required: bool = False,
    recent_card_ids: Iterable[str] = (),
    limit: int = 5,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    index_path: Path = DEFAULT_SEMANTIC_INDEX,
    event_kind: str | None = None,
    output_role: str | None = None,
    frame_count: int | None = None,
    capability_index_path: Path | None = None,
) -> dict[str, Any]:
    """Return a stable ranked shortlist from the complete qualified catalog."""

    spoken = _text(transcript, "transcript")
    family = _text(semantic_family, "semantic_family")
    goals = _text_list(semantic_goals, "semantic_goals")
    words = _text_list(keywords, "keywords")
    recent = _text_list(recent_card_ids, "recent_card_ids")
    if type(information_units) is not int or not 1 <= information_units <= 8:
        _fail("information_units must be an integer from 1 to 8")
    if target_role is not None and target_role not in _ROLE_VALUES:
        _fail("target_role is invalid")
    media = set(_text_list(available_media, "available_media"))
    if media - _MEDIA_VALUES:
        _fail("available_media contains an unsupported value")
    if type(presenter_required) is not bool or type(limit) is not int or not 1 <= limit <= 20:
        _fail("presenter_required or limit is invalid")
    if event_kind is not None and event_kind not in {"segment", "selection", "moment"}:
        _fail("event_kind is invalid")
    if output_role is not None and output_role not in {"visual", "caption", "audio", "spatial", "transition"}:
        _fail("output_role is invalid")
    if frame_count is not None and (type(frame_count) is not int or frame_count < 1):
        _fail("frame_count is invalid")

    query = _features(" ".join((spoken, family, *goals, *words)))
    weighted = [(spoken, 1.0), (family, 8.0)]
    weighted.extend((value, 3.0) for value in goals)
    weighted.extend((value, 5.0) for value in words)
    catalog = load_card_catalog(registry_path, index_path=index_path)
    capability_by_id: dict[str, dict[str, Any]] = {}
    capability_index_sha256: str | None = None
    if capability_index_path is not None:
        try:
            capability_payload = read_json_artifact(capability_index_path)
            registry_payload = load_card_registry(registry_path)
            qualified_ids = [
                card["card_id"]
                for card in registry_payload["cards"]
                if card["production"]["status"] == "qualified"
            ]
            capability_index = validate_card_event_capabilities(
                capability_payload,
                qualified_card_ids=qualified_ids,
                expected_registry_sha256=hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            )
            capability_by_id = {
                item["card_id"]: item for item in capability_index["cards"]
            }
            capability_index_sha256 = hashlib.sha256(capability_index_path.read_bytes()).hexdigest()
        except (OSError, ValueError) as error:
            raise TalkCraftMatchError("TalkCraft event capability index is invalid") from error
    ranked: list[dict[str, Any]] = []
    for card in catalog:
        if target_role is not None and card["production_role"] != target_role:
            continue
        if not set(card["required_media"]).issubset(media):
            continue
        if presenter_required and "presenter" not in card["allowed_media"]:
            continue
        if capability_index_path is not None:
            capability = capability_by_id.get(card["card_id"])
            if capability is None or event_kind is None or output_role is None:
                continue
            if not can_card_consume_event(
                capability,
                event_kind=event_kind,
                output_role=output_role,
                available_media=media,
                presenter_required=presenter_required,
                frame_count=frame_count,
            ):
                continue
        title_features = _features(card["title"] + " " + card["card_id"])
        core_features = _features(card["summary"] + " " + card["suitable_for"])
        document_features = _features(card["search_text"])
        overlap = 5 * len(query & title_features) + 3 * len(query & core_features) + len(query & document_features)
        family_match = family in card["semantic_families"]
        phrase_score = 0.0
        haystack = card["search_text"].lower()
        for value, weight in weighted:
            needle = value.lower().strip()
            if len(needle) >= 2 and needle in haystack:
                phrase_score += weight
        media_score = 2.0 * len(media & set(card["allowed_media"]))
        presenter_score = 4.0 if presenter_required and "presenter" in card["allowed_media"] else 0.0
        recency_penalty = 12.0 if card["card_id"] in recent else 0.0
        score = overlap + (18.0 if family_match else 0.0) + phrase_score + media_score + presenter_score - recency_penalty
        if score <= 0:
            continue
        ranked.append({
            "card_id": card["card_id"],
            "title": card["title"],
            "category": card["category"],
            "production_role": card["production_role"],
            "semantic_families": card["semantic_families"],
            "allowed_media": card["allowed_media"],
            "required_media": card["required_media"],
            "score": round(score, 3),
            "family_match": family_match,
            "production": card["production"],
            "sample_sha256": card["sample_sha256"],
            **({"event_capability": capability_by_id[card["card_id"]]} if capability_index_path is not None else {}),
        })
    ranked.sort(key=lambda item: (-item["score"], item["card_id"]))
    if not ranked:
        _fail("no qualified TalkCraft card matches the current speech and constraints")
    return {
        "schema_version": "talkcraft-auto-match/v1",
        "catalog_size": len(catalog),
        "semantic_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "event_capability_index_sha256": capability_index_sha256,
        "eligible_count": len(ranked),
        "request": {
            "transcript": spoken,
            "semantic_family": family,
            "semantic_goals": goals,
            "keywords": words,
            "information_units": information_units,
            "target_role": target_role,
            "available_media": sorted(media),
            "presenter_required": presenter_required,
            "recent_card_ids": recent,
            "event_kind": event_kind,
            "output_role": output_role,
            "frame_count": frame_count,
        },
        "matches": ranked[:limit],
    }


def build_binding(
    match_result: dict[str, Any],
    *,
    brief_sha256: str,
    registry_path: Path = DEFAULT_CARD_REGISTRY,
    index_path: Path = DEFAULT_SEMANTIC_INDEX,
) -> dict[str, Any]:
    """Freeze the selected qualified card into the existing ShotRecipe binding."""

    if type(match_result) is not dict or match_result.get("schema_version") != "talkcraft-auto-match/v1":
        _fail("match_result is invalid")
    matches = match_result.get("matches")
    request = match_result.get("request")
    if type(matches) is not list or not matches or type(request) is not dict:
        _fail("match_result has no selected card")
    if type(brief_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", brief_sha256) is None:
        _fail("brief_sha256 must be lowercase sha256")
    try:
        current_index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    except OSError as error:
        raise TalkCraftMatchError("TalkCraft semantic index is unavailable") from error
    if match_result.get("semantic_index_sha256") != current_index_sha256:
        _fail("match_result semantic index identity is stale")
    selected_result = matches[0]
    if type(selected_result) is not dict or type(selected_result.get("card_id")) is not str:
        _fail("match_result selected card is invalid")
    selected = next(
        (
            card
            for card in load_card_catalog(registry_path, index_path=index_path)
            if card["card_id"] == selected_result["card_id"]
        ),
        None,
    )
    if selected is None:
        _fail("match_result selected card is no longer qualified")
    production = selected["production"]
    family = _text(request.get("semantic_family"), "match_result semantic_family")
    information_units = request.get("information_units")
    if type(information_units) is not int or not 1 <= information_units <= 8:
        _fail("match_result information_units is invalid")
    families = list(selected["semantic_families"])
    if family not in families:
        families.append(family)
    entrypoint = production["derived_entrypoint"]
    return {
        "producer_type": "dependency",
        "dependency_id": DEPENDENCY_ID,
        "entrypoint": entrypoint,
        "producer_version": production["adapter_version"],
        "brief_sha256": brief_sha256,
        "invocation_record": {
            "argv": ["node", entrypoint],
            "exit_code": None,
            "status": "planned",
            "template_request": {
                "semantic_family": family,
                "information_units": information_units,
                "numeric_values": [],
                "numeric_scale": "not_applicable",
            },
        },
        "primary_renderer": PRIMARY_RENDERER,
        "renderer_version": _RENDERER_VERSION,
        "template_origin": "custom_fallback",
        "template_id": f"hd-talking-head/talkcraft/{selected['card_id']}",
        "template_version": production["adapter_version"],
        "verification_id": production["qualification_id"],
        "adaptation_level": "structural",
        "source_entrypoint": entrypoint,
        "source_sha256": production["implementation_sha256"],
        "sample_sha256": selected["sample_sha256"],
        "semantic_families": families,
        "capacity": {"min_units": 1, "max_units": 8},
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Match speech to qualified TalkCraft cards")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--semantic-family", required=True)
    parser.add_argument("--semantic-goal", action="append", default=[])
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--information-units", type=int, default=1)
    parser.add_argument("--target-role", choices=sorted(_ROLE_VALUES))
    parser.add_argument("--available-media", action="append", default=[])
    parser.add_argument("--presenter-required", action="store_true")
    parser.add_argument("--recent-card-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args()
    result = match_cards(
        arguments.transcript,
        semantic_family=arguments.semantic_family,
        semantic_goals=arguments.semantic_goal,
        keywords=arguments.keyword,
        information_units=arguments.information_units,
        target_role=arguments.target_role,
        available_media=arguments.available_media,
        presenter_required=arguments.presenter_required,
        recent_card_ids=arguments.recent_card_id,
        limit=arguments.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TalkCraftMatchError",
    "DEFAULT_SEMANTIC_INDEX",
    "EXPECTED_SEMANTIC_INDEX_SHA256",
    "build_semantic_index",
    "load_card_catalog",
    "match_cards",
    "build_binding",
]

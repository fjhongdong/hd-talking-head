"""Strict semantic-event contracts for visual, caption, audio and spatial cues."""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping

from .contract_artifacts import sha256_json


class SemanticEventError(ValueError):
    """Raised when a semantic event plan cannot be safely consumed."""


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_KINDS = frozenset({"segment", "selection", "moment"})
_CHANNELS = frozenset({"visual", "caption", "audio", "spatial", "transition"})


def _fail(message: str) -> None:
    raise SemanticEventError(message)


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


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        _fail(f"{label} must be a list of non-empty text")
    if len(value) != len(set(value)):
        _fail(f"{label} must not contain duplicates")
    return list(value)


def _visual_plan_ids(visual_plan: Mapping[str, object] | None) -> tuple[set[str], set[str]]:
    if visual_plan is None:
        return set(), set()
    if type(visual_plan) is not dict:
        _fail("visual_plan must be an object")
    segments = visual_plan.get("segments")
    if type(segments) is not list or not segments:
        _fail("visual_plan.segments must be a non-empty list")
    segment_ids: set[str] = set()
    for index, segment in enumerate(segments):
        if type(segment) is not dict or type(segment.get("segment_id")) is not str:
            _fail(f"visual_plan.segments[{index}] is invalid")
        segment_ids.add(segment["segment_id"])
    span_ids: set[str] = set()
    spans = visual_plan.get("render_spans", [])
    if spans is not None:
        if type(spans) is not list:
            _fail("visual_plan.render_spans must be a list")
        for index, span in enumerate(spans):
            if type(span) is not dict or type(span.get("span_id")) is not str:
                _fail(f"visual_plan.render_spans[{index}] is invalid")
            span_ids.add(span["span_id"])
    return segment_ids, span_ids


def _validate_channels(value: object, label: str) -> dict[str, Any]:
    channels = _strict(value, set(_CHANNELS), label)
    visual = channels["visual"]
    audio = channels["audio"]
    if type(visual) is not list or any(type(item) is not str or not item.strip() for item in visual):
        _fail(f"{label}.visual must be a list of card or component ids")
    if type(audio) is not list or any(type(item) is not str or not item.strip() for item in audio):
        _fail(f"{label}.audio must be a list of cue ids")
    if len(visual) != len(set(visual)) or len(audio) != len(set(audio)):
        _fail(f"{label} channel lists must not contain duplicates")
    for channel in ("caption", "spatial", "transition"):
        if type(channels[channel]) not in {dict, list, str, bool, int, float, type(None)}:
            _fail(f"{label}.{channel} must be JSON-compatible")
    return copy.deepcopy(channels)


def _validate_event(
    value: object,
    index: int,
    *,
    segment_ids: set[str],
    span_ids: set[str],
) -> dict[str, Any]:
    event = _strict(
        value,
        {
            "event_id", "kind", "segment_id", "span_id", "word_range",
            "start_frame", "end_frame", "semantic_role", "trigger", "channels",
        },
        f"events[{index}]",
    )
    event_id = _identifier(event["event_id"], f"events[{index}].event_id")
    kind = _text(event["kind"], f"events[{index}].kind")
    if kind not in _KINDS:
        _fail(f"events[{index}].kind is unsupported")
    segment_id = _identifier(event["segment_id"], f"events[{index}].segment_id")
    if segment_ids and segment_id not in segment_ids:
        _fail(f"events[{index}].segment_id is not in the visual plan")
    span_id = event["span_id"]
    if span_id is not None:
        span_id = _identifier(span_id, f"events[{index}].span_id")
        if span_ids and span_id not in span_ids:
            _fail(f"events[{index}].span_id is not in the visual plan")
    word_range = event["word_range"]
    if type(word_range) is not list or len(word_range) != 2:
        _fail(f"events[{index}].word_range must contain two integers")
    word_start = _int(word_range[0], f"events[{index}].word_range[0]")
    word_end = _int(word_range[1], f"events[{index}].word_range[1]")
    if word_end < word_start:
        _fail(f"events[{index}].word_range is reversed")
    start_frame = _int(event["start_frame"], f"events[{index}].start_frame")
    end_frame = _int(event["end_frame"], f"events[{index}].end_frame")
    if end_frame <= start_frame:
        _fail(f"events[{index}] must have a positive frame range")
    return {
        "event_id": event_id,
        "kind": kind,
        "segment_id": segment_id,
        "span_id": span_id,
        "word_range": [word_start, word_end],
        "start_frame": start_frame,
        "end_frame": end_frame,
        "semantic_role": _text(event["semantic_role"], f"events[{index}].semantic_role"),
        "trigger": _text(event["trigger"], f"events[{index}].trigger"),
        "channels": _validate_channels(event["channels"], f"events[{index}].channels"),
    }


def validate_semantic_event_plan(
    value: object,
    *,
    visual_plan: Mapping[str, object] | None = None,
    expected_visual_plan_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate an event plan without executing any provider or renderer."""

    plan = _strict(
        value,
        {"schema_version", "visual_plan_sha256", "transcript_identity", "events", "plan_sha256"},
        "semantic event plan",
    )
    if plan["schema_version"] != "semantic-event-plan/v1":
        _fail("unsupported semantic event plan schema")
    visual_hash = _sha(plan["visual_plan_sha256"], "visual_plan_sha256")
    actual_visual_hash = None
    if visual_plan is not None:
        declared_plan_hash = visual_plan.get("visual_plan_sha256") if type(visual_plan) is dict else None
        actual_visual_hash = (
            _sha(declared_plan_hash, "visual_plan.visual_plan_sha256")
            if declared_plan_hash is not None
            else sha256_json(visual_plan)
        )
        if visual_hash != actual_visual_hash:
            _fail("semantic event plan is not bound to the supplied visual plan")
    if expected_visual_plan_sha256 is not None:
        expected = _sha(expected_visual_plan_sha256, "expected_visual_plan_sha256")
        if visual_hash != expected or (actual_visual_hash is not None and expected != actual_visual_hash):
            _fail("semantic event plan is bound to a different visual plan")
    _text(plan["transcript_identity"], "transcript_identity")
    events_value = plan["events"]
    if type(events_value) is not list:
        _fail("events must be a list")
    segment_ids, span_ids = _visual_plan_ids(visual_plan)
    events = [
        _validate_event(item, index, segment_ids=segment_ids, span_ids=span_ids)
        for index, item in enumerate(events_value)
    ]
    event_ids = [item["event_id"] for item in events]
    if len(event_ids) != len(set(event_ids)):
        _fail("event_id values must be unique")
    ordered = [(item["start_frame"], item["end_frame"], item["event_id"]) for item in events]
    if ordered != sorted(ordered):
        _fail("events must be ordered by start_frame, end_frame and event_id")
    unsigned = {
        "schema_version": plan["schema_version"],
        "visual_plan_sha256": visual_hash,
        "transcript_identity": plan["transcript_identity"],
        "events": events,
    }
    if plan["plan_sha256"] != sha256_json(unsigned):
        _fail("semantic event plan hash does not match its contents")
    return {**unsigned, "plan_sha256": plan["plan_sha256"]}


def build_semantic_event_plan(
    *,
    visual_plan_sha256: str,
    transcript_identity: str,
    events: Iterable[Mapping[str, object]],
    visual_plan: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a canonical event plan and calculate its content hash."""

    unsigned = {
        "schema_version": "semantic-event-plan/v1",
        "visual_plan_sha256": visual_plan_sha256,
        "transcript_identity": transcript_identity,
        "events": [copy.deepcopy(dict(item)) for item in events],
    }
    unsigned["plan_sha256"] = sha256_json(
        {key: value for key, value in unsigned.items() if key != "plan_sha256"}
    )
    return validate_semantic_event_plan(unsigned, visual_plan=visual_plan)


def build_segment_event_plan(
    *,
    visual_plan: Mapping[str, object],
    transcript_identity: str,
    content_items: Iterable[Mapping[str, object]],
    words: Iterable[Mapping[str, object]],
) -> dict[str, Any]:
    """Compile one deterministic segment event per approved visual segment.

    Source spans are resolved against the approved word transcript by character
    offsets.  No semantic labels or card choices are invented here; the first
    approved content item's ``semantic_type`` is retained as the event role and
    visual/audio channels stay empty until a brief explicitly binds them.
    """

    if type(visual_plan) is not dict:
        _fail("visual_plan must be an object")
    segments = visual_plan.get("segments")
    if type(segments) is not list or not segments:
        _fail("visual_plan.segments must be a non-empty list")
    items_by_id: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(content_items):
        if type(raw) is not dict or type(raw.get("id")) is not str:
            _fail(f"content_items[{index}] is invalid")
        if raw["id"] in items_by_id:
            _fail("content item ids must be unique")
        source_span = raw.get("source_span")
        if type(source_span) is not list or len(source_span) != 2 or any(type(value) is not int for value in source_span):
            _fail(f"content_items[{index}].source_span is invalid")
        if source_span[1] <= source_span[0] or type(raw.get("source_text")) is not str or not raw["source_text"]:
            _fail(f"content_items[{index}] source span is invalid")
        items_by_id[raw["id"]] = raw
    checked_words = list(words)
    if not checked_words or any(
        type(word) is not dict
        or type(word.get("text")) is not str
        or not word["text"]
        or type(word.get("start")) not in {int, float}
        or type(word.get("end")) not in {int, float}
        or word["end"] <= word["start"]
        for word in checked_words
    ):
        _fail("words must be a non-empty timed transcript")
    offsets: list[int] = [0]
    for word in checked_words:
        offsets.append(offsets[-1] + len(word["text"]))

    def word_range(source_span: object, label: str) -> list[int]:
        if type(source_span) is not list or len(source_span) != 2 or any(type(value) is not int for value in source_span):
            _fail(f"{label} source_span is invalid")
        start, end = source_span
        candidates = [
            index for index in range(len(checked_words))
            if offsets[index] == start and offsets[index + 1] <= end
        ]
        if not candidates:
            _fail(f"{label} source_span does not align to words")
        first = candidates[0]
        last = first
        while last < len(checked_words) and offsets[last + 1] <= end:
            last += 1
        if offsets[first] != start or offsets[last] != end:
            _fail(f"{label} source_span does not align to words")
        return [first, last]

    events: list[dict[str, object]] = []
    for index, segment in enumerate(segments):
        if type(segment) is not dict:
            _fail(f"visual_plan.segments[{index}] is invalid")
        segment_id = segment.get("segment_id")
        item_ids = segment.get("content_item_ids")
        if type(segment_id) is not str or type(item_ids) is not list or not item_ids:
            _fail(f"visual_plan.segments[{index}] content binding is invalid")
        selected = [items_by_id.get(item_id) for item_id in item_ids]
        if any(item is None for item in selected):
            _fail(f"visual_plan.segments[{index}] references an unknown content item")
        ranges = [word_range(item["source_span"], f"content item {item['id']}") for item in selected]
        semantic_role = selected[0].get("semantic_type")
        if type(semantic_role) is not str or not semantic_role.strip():
            _fail(f"content item {selected[0]['id']} semantic_type is invalid")
        start_frame = round(float(segment.get("start")) * 24)
        end_frame = round(float(segment.get("end")) * 24)
        if end_frame <= start_frame:
            _fail(f"visual_plan.segments[{index}] frame range is invalid")
        events.append({
            "event_id": f"segment-{segment_id}",
            "kind": "segment",
            "segment_id": segment_id,
            "span_id": None,
            "word_range": [min(item[0] for item in ranges), max(item[1] for item in ranges)],
            "start_frame": start_frame,
            "end_frame": end_frame,
            "semantic_role": semantic_role,
            "trigger": "segment_start",
            "channels": {"visual": [], "caption": {}, "audio": [], "spatial": {}, "transition": {}},
        })
    return build_semantic_event_plan(
        visual_plan_sha256=str(visual_plan.get("visual_plan_sha256", "")),
        transcript_identity=transcript_identity,
        visual_plan=visual_plan,
        events=events,
    )


def validate_subtitle_event_alignment(
    subtitle_plan: Mapping[str, object],
    event_plan: Mapping[str, object],
) -> list[dict[str, object]]:
    """Bind every subtitle cue to exactly one overlapping semantic event."""

    if type(subtitle_plan) is not dict or type(subtitle_plan.get("cues")) is not list:
        _fail("subtitle_plan.cues must be a list")
    checked_event_plan = validate_semantic_event_plan(event_plan)
    events = checked_event_plan["events"]
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    previous_end = -1
    for index, cue in enumerate(subtitle_plan["cues"]):
        if type(cue) is not dict:
            _fail(f"subtitle cues[{index}] is invalid")
        cue_id = cue.get("id")
        segment_id = cue.get("segment_id")
        start = cue.get("start")
        end = cue.get("end")
        if (
            type(cue_id) is not str or not cue_id.strip() or cue_id in seen
            or type(segment_id) is not str or not segment_id.strip()
            or type(start) not in {int, float} or type(end) not in {int, float}
            or end <= start or start < 0
        ):
            _fail(f"subtitle cues[{index}] is invalid")
        seen.add(cue_id)
        start_frame = round(float(start) * 24)
        end_frame = round(float(end) * 24)
        if start_frame < previous_end:
            _fail("subtitle cues must preserve time order")
        previous_end = end_frame
        matches = [
            event for event in events
            if event["segment_id"] == segment_id
            and max(start_frame, event["start_frame"]) < min(end_frame, event["end_frame"])
        ]
        if len(matches) != 1:
            _fail(f"subtitle cue {cue_id} does not bind to exactly one semantic event")
        event = matches[0]
        explicit_event_id = cue.get("event_id")
        if explicit_event_id is not None and explicit_event_id != event["event_id"]:
            _fail(f"subtitle cue {cue_id} event_id does not match its semantic event")
        result.append({
            "cue_id": cue_id,
            "event_id": event["event_id"],
            "start_frame": start_frame,
            "end_frame": end_frame,
        })
    return result


def validate_audio_event_alignment(
    audio_plan: Mapping[str, object],
    event_plan: Mapping[str, object],
) -> list[dict[str, object]]:
    """Validate explicit audio cue/event_id bindings against event windows."""

    if type(audio_plan) is not dict or type(audio_plan.get("cues")) is not list:
        _fail("audio_plan.cues must be a list")
    checked_event_plan = validate_semantic_event_plan(event_plan)
    events = checked_event_plan["events"]
    events_by_cue: dict[str, dict[str, object]] = {}
    for event in events:
        audio = event["channels"]["audio"]
        for cue_id in audio:
            if cue_id in events_by_cue:
                _fail(f"audio cue {cue_id} is bound to multiple events")
            events_by_cue[cue_id] = event
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, cue in enumerate(audio_plan["cues"]):
        if type(cue) is not dict:
            _fail(f"audio cues[{index}] is invalid")
        cue_id = cue.get("cue_id")
        event_id = cue.get("event_id")
        start_frame = cue.get("start_frame")
        end_frame = cue.get("end_frame")
        if (
            type(cue_id) is not str or not cue_id.strip() or cue_id in seen
            or type(event_id) is not str or not event_id.strip()
            or type(start_frame) is not int or type(end_frame) is not int
            or start_frame < 0 or end_frame <= start_frame
        ):
            _fail(f"audio cues[{index}] is invalid")
        seen.add(cue_id)
        event = events_by_cue.get(cue_id)
        if event is None or event["event_id"] != event_id:
            _fail(f"audio cue {cue_id} has an invalid event binding")
        if start_frame < event["start_frame"] or end_frame > event["end_frame"]:
            _fail(f"audio cue {cue_id} falls outside its event window")
        result.append({
            "cue_id": cue_id,
            "event_id": event_id,
            "start_frame": start_frame,
            "end_frame": end_frame,
        })
    if seen != set(events_by_cue):
        _fail("audio plan does not cover every declared semantic audio cue")
    return result

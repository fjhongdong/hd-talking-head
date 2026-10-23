"""Speech and timing checks for the Huashu native single-metric overlay."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

DEPENDENCY_ID = "huashu-motion-native"
ROUTE = "huashu-stat"
FPS = 24


def _adapter():
    path = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/huashu_stat_adapter.py"
    spec = importlib.util.spec_from_file_location("_huashu_stat_execution_contract", path)
    if spec is None or spec.loader is None:
        raise ValueError("Huashu stat adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _word_time(word: Mapping, cuts: Sequence[Mapping]) -> float:
    positions = [word["start"] + p["timeline_start"] - p["source_start"]
                 for p in cuts if p["source_start"] <= word["start"] < p["source_end"]]
    if len(positions) != 1:
        raise ValueError("Huashu stat anchor is not in edited speech")
    return float(positions[0])


def validate_brief(brief: Mapping, *, segment: Mapping, words: Sequence[Mapping],
                   cuts: Sequence[Mapping], events: Sequence[Mapping]) -> list[dict]:
    module = _adapter()
    brief = module.validate_brief(brief)
    source = brief.get("source_binding")
    expected = {k: segment.get(k) for k in ("aroll_sha256", "segment_id", "start", "end")}
    if not isinstance(source, Mapping) or any(source.get(k) != v for k, v in expected.items()):
        raise ValueError("Huashu stat source binding differs from approved A-roll segment")
    comp = brief.get("composition")
    if not isinstance(comp, Mapping) or {k: comp.get(k) for k in ("width", "height", "fps", "alpha")} != {"width": 1080, "height": 1920, "fps": FPS, "alpha": True}:
        raise ValueError("Huashu stat composition must be 1080x1920/24fps with alpha")
    metric = brief.get("metric")
    if not isinstance(metric, Mapping):
        raise ValueError("Huashu stat metric is missing")
    value_text, label = module.metric_texts(brief)
    label = metric.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Huashu stat label is missing")
    visible = [value_text, label]
    if segment.get("visible_text") != visible:
        raise ValueError("Huashu stat labels differ from segment visible text")
    request = brief.get("template_request")
    if not isinstance(request, Mapping) or request.get("numeric_values") != [metric.get("value")]:
        raise ValueError("Huashu stat exact numeric request differs from metric")
    if not isinstance(events, Sequence) or len(events) != 1:
        raise ValueError("Huashu stat treatment requires exactly one event")
    event = events[0]
    if not isinstance(event, Mapping) or event.get("slot") != 0 or event.get("kind") != "count_landing" or event.get("text") != value_text or event.get("basis") != "current_clause":
        raise ValueError("Huashu stat event differs from native count landing")
    anchor = event.get("anchor")
    if not isinstance(anchor, Mapping) or type(anchor.get("index")) is not int:
        raise ValueError("Huashu stat event anchor is missing")
    index = anchor["index"]
    if not 0 <= index < len(words) or words[index].get("text") != anchor.get("text"):
        raise ValueError("Huashu stat anchor differs from approved transcript")
    word = words[index]
    if (type(word.get("start")) not in (int, float) or type(word.get("end")) not in (int, float)
            or not math.isfinite(word["start"]) or not math.isfinite(word["end"])
            or word["end"] <= word["start"]):
        raise ValueError("Huashu stat requires a positive-duration speech word")
    anchor_time = _word_time(word, cuts)
    target = metric.get("target_frame")
    hold = metric.get("hold_frames")
    frames = comp.get("frames")
    if type(target) is not int or type(hold) is not int or type(frames) is not int or target < 15 or hold < 24 or target + hold > frames - 2:
        raise ValueError("Huashu stat frame timing is outside the native contract")
    landing = float(segment["start"]) + target / FPS
    if not float(segment["start"]) <= landing < float(segment["end"]):
        raise ValueError("Huashu stat landing is outside this shot")
    if not float(segment["start"]) <= anchor_time < float(segment["end"]) or abs(landing - anchor_time) > 1 / FPS + 1e-8:
        raise ValueError("Huashu stat landing is not aligned with the spoken clause")
    native_exit = float(segment["start"]) + (target + hold) / FPS
    if native_exit > float(segment["end"]) + 1e-6:
        raise ValueError("Huashu stat exits after the shot")
    return [{"slot": 0, "kind": "count_landing", "text": value_text, "basis": "current_clause",
             "anchor": anchor, "anchor_time": anchor_time, "effective_time": landing,
             "native_exit": native_exit}]


def validate_approved(job, segment, component_id, brief, brief_sha256):
    """Recheck the already-published speech evidence without a second event ledger."""
    from .overlay_alignment import _approved
    review, _ = _approved(job, "visual_direction", "07-visual-direction/visual-routing.md")
    matches = re.findall(r"## 原生贴片实际词锚与时钟\s+```json\s*([\s\S]*?)\s*```", review.read_text())
    if len(matches) != 1:
        raise ValueError("Approved native stat speech report is missing")
    rows = [row for row in json.loads(matches[0])
            if row.get("segment_id") == segment["segment_id"] and row.get("component_id") == component_id]
    if len(rows) != 1 or rows[0].get("route") != ROUTE or rows[0].get("brief_sha256") != brief_sha256:
        raise ValueError("Approved stat speech report differs from this component")
    transcript, _ = _approved(job, "speech_cleanup", "05-speech-cleanup/word-transcript.json")
    timeline, _ = _approved(job, "edit_structure", "06-edit-structure/timeline-map.json")
    _, arroll_sha = _approved(job, "edit_structure", "06-edit-structure/edited-aroll.mp4")
    checked = validate_brief(brief, segment={**segment, "aroll_sha256": arroll_sha},
        words=json.loads(transcript.read_bytes())["words"],
        cuts=json.loads(timeline.read_bytes())["segments"], events=rows[0].get("events"))
    if checked != rows[0]["events"] or rows[0].get("native_exit") != checked[0]["native_exit"]:
        raise ValueError("Approved stat speech timing has changed")
    return checked

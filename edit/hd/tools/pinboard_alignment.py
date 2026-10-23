"""Own validation for Overlay Studio's native pin-board adapter."""
from __future__ import annotations
import importlib.util
import math
from pathlib import Path
from typing import Mapping, Sequence
DEPENDENCY_ID = "overlay-studio-native"
ROUTE = "pin-board"
FPS = 24
def _segment_word_time(word: Mapping, cuts: Sequence[Mapping]) -> float:
    positions = [word["start"] + p["timeline_start"] - p["source_start"] for p in cuts if p["source_start"] <= word["start"] < p["source_end"]]
    if len(positions) != 1: raise ValueError("pin-board anchor is not in edited speech")
    return float(positions[0])
def validate_brief(brief: Mapping, *, segment: Mapping, words: Sequence[Mapping], cuts: Sequence[Mapping], events: Sequence[Mapping]) -> list[dict]:
    # The adapter owns the execution schema; this module only adds speech checks.
    entry = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/overlay_studio_adapter.py"
    spec = importlib.util.spec_from_file_location("_pinboard_execution_contract", entry)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    brief = module.validate_brief(brief)
    source = brief.get("source_binding"); expected = {"aroll_sha256": segment.get("aroll_sha256"), "segment_id": segment.get("segment_id"), "start": segment.get("start"), "end": segment.get("end")}
    if not isinstance(source, Mapping) or set(source) != set(expected) or any(source.get(k) != v for k,v in expected.items()): raise ValueError("pin-board source binding differs from approved A-roll segment")
    comp = brief.get("composition")
    if not isinstance(comp, Mapping) or {k: comp.get(k) for k in ("width","height","fps","alpha")} != {"width":1080,"height":1920,"fps":FPS,"alpha":True}: raise ValueError("pin-board composition must be 1080x1920/24fps with alpha")
    doc = brief.get("doc")
    if not isinstance(doc, Mapping) or doc.get("version") != 1 or set(doc)-{"version","theme","font","inkColor","glow","breath","cam","cards"}: raise ValueError("pin-board OverlayDoc is invalid")
    cards = doc.get("cards")
    if not isinstance(cards,list) or len(cards)!=1 or not isinstance(cards[0],Mapping): raise ValueError("pin-board brief must contain exactly one native card")
    card = cards[0]
    if card.get("kind") != "pin-board" or not isinstance(card.get("start"),(int,float)) or not isinstance(card.get("end"),(int,float)): raise ValueError("pin-board card timing is invalid")
    params = card.get("params")
    if not isinstance(params,Mapping) or params.get("title","") or params.get("subtitle",""): raise ValueError("pin-board title and subtitle must remain empty")
    items = [v.strip() for v in str(params.get("items","")).split("|") if v.strip()]; times = [v.strip() for v in str(params.get("times","")).split("|") if v.strip()]
    if not items or len(items)!=len(times): raise ValueError("pin-board items and native times must be one-to-one")
    if not isinstance(events,Sequence) or len(events)!=len(items): raise ValueError("pin-board treatment events must cover every item")
    if items != segment.get("visible_text"): raise ValueError("pin-board labels differ from segment visible text")
    out=[]
    for slot,(item,raw,event) in enumerate(zip(items,times,events,strict=True)):
        try: local=float(raw)
        except (TypeError,ValueError): raise ValueError("pin-board native time is not numeric") from None
        if not math.isfinite(local) or local<0: raise ValueError("pin-board native time is invalid")
        if not isinstance(event,Mapping) or event.get("slot")!=slot or event.get("kind")!="pin_drop" or event.get("text")!=item: raise ValueError("pin-board event differs from native item")
        if event.get("basis") not in {"current_clause","recap"}: raise ValueError("overlay anchor basis must be current_clause or recap")
        anchor=event.get("anchor")
        if not isinstance(anchor,Mapping) or type(anchor.get("index")) is not int: raise ValueError("pin-board event anchor is missing")
        index=anchor["index"]
        if not 0<=index<len(words) or words[index].get("text")!=anchor.get("text"): raise ValueError("pin-board anchor differs from approved transcript")
        word=words[index]
        if word.get("end",0)<=word.get("start",0): raise ValueError("zero-duration ASR noise cannot anchor a label")
        anchor_time=_segment_word_time(word,cuts); effective=float(segment["start"])+float(card["start"])+local
        if not float(segment["start"])<=effective<float(segment["end"]): raise ValueError("pin-board event is outside this shot")
        if event["basis"]=="current_clause":
            if not float(segment["start"])<=anchor_time<float(segment["end"]): raise ValueError("current-clause anchor is outside this shot")
            if effective<anchor_time-1/FPS or effective>anchor_time+0.8: raise ValueError("pin-board reveal is not aligned with spoken clause")
        elif effective<anchor_time: raise ValueError("recap refers to speech that has not happened")
        out.append({"slot":slot,"kind":"pin_drop","text":item,"basis":event["basis"],"anchor":anchor,"anchor_time":anchor_time,"effective_time":effective})
    if float(card["end"])<=float(card["start"]): raise ValueError("pin-board card must have a positive duration")
    return out

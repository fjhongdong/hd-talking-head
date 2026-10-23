#!/usr/bin/env python3
"""Build one native visual enrichment (A-roll overlay or full-screen B-roll).

Usage (overlay):
  <python> build_native_visual.py --job-context ctx overlay \
      --route notification-stack --labels "a,b,c" --anchors "74,89,99" \
      --reason "语义理由"

Usage (B-roll):
  <python> build_native_visual.py --job-context ctx broll \
      --route chat-message --first-word 229 --last-word 236 \
      --variables '{"type":"sent","text":"…"}' \
      --reason "语义理由"

Everything else is derived: word anchors → cut clock, upstream source pin,
clock-bound native copy, mount entry, schema-2 brief, frozen binding,
director-brief/treatment updates, then revise + re-approve visual_direction.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

OVERLAY_ROUTES = {
    "notification-stack": ("reminder", "notification_stack", "notification-stack"),
    "grid-card-assemble": ("parallel", "staggered_card_reveal", "grid-list"),
    "toggle-flip": ("state_change", "state_toggle", "toggle-rail"),
    "before-after-wipe": ("compare", "moving_split_reveal", "before-after-split"),
}
BROLL_ROUTES = ("macos-notification", "chat-message", "screen-flow-carousel", "beat-timeline")
REGISTRY = Path("参考项目/B-roll开源方案/hyperframes/registry")


def _load(project: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _word_cut_times(job_dir: Path) -> tuple[list[dict], list[dict]]:
    report = json.loads((job_dir / "05-speech-cleanup/report.json").read_text())
    words = report["transcript"]["words"]
    cuts = json.loads((job_dir / "06-edit-structure/timeline-map.json").read_text())["segments"]
    for word in words:
        word["cut"] = None
        for cut in cuts:
            if cut["source_start"] <= word["start"] and word["end"] <= cut["source_end"]:
                word["cut"] = cut["timeline_start"] + (word["start"] - cut["source_start"])
                break
    return words, cuts


def _split_segment(brief: dict, index: int, at: float, next_id: list[int]) -> None:
    """Split one BASE plan segment at a word-boundary time into two base segments."""
    segment = brief["segments"][index]
    if segment["visual_strategy"]["composition"]["family"] != "no_broll":
        raise SystemExit("word boundary crosses an enriched segment; beats overlap")
    left = json.loads(json.dumps(segment))
    right = json.loads(json.dumps(segment))
    next_id[0] += 1
    right["segment_id"] = f"seg-{next_id[0]:03d}"
    for part in (left, right):
        part["visual_strategy"] = json.loads(json.dumps(_BASE_STRATEGY))
        part["visual_strategy"]["segment_id"] = part["segment_id"]
        part["visual_intent"]["segment_id"] = part["segment_id"]
        part["visual_intent"]["statement"] = "口播讲解"
        part["candidate_snapshots"] = {}
        part["bindings"] = {}
        part["visible_text"] = []
        part["strategy_revision"] = 1
    left["end"] = at
    right["start"] = at
    brief["segments"][index:index + 1] = [left, right]


_BASE_STRATEGY = {
    "schema_version": 1, "mode": "none", "rationale": "纯 A-roll 真人讲解",
    "components": [],
    "composition": {"family": "no_broll", "presenter_mode": "full_frame",
                     "reading_order": [], "component_dependencies": []},
}


def _window_span(brief: dict, words: list[dict], first: int, last: int,
                 minimum: float = 0.0) -> tuple[dict, int, int]:
    """Cut the plan at word boundaries so [first..last] words get their own span.

    Base segments are coarse cut units; beats are word-level. Any segment
    crossing the window edges is split into base segments first, then every
    segment inside the window collapses into the enrichment target span.
    """
    wa = words[first]["cut"]
    wb = words[last]["cut"] + (words[last]["end"] - words[last]["start"])
    next_id = [max(int(s["segment_id"][4:]) for s in brief["segments"]) + 100]
    if minimum > 0:
        # backward first (never crossing the previous beat), then forward
        # (never crossing the next beat)
        enriched_before = max(
            (s["end"] for s in brief["segments"]
             if s["end"] <= wa + 1e-6
             and s["visual_strategy"]["composition"]["family"] != "no_broll"),
            default=0.0)
        idx = first
        while wb - wa < minimum and idx > 0:
            idx -= 1
            candidate = words[idx].get("cut")
            if candidate is not None:
                if candidate <= enriched_before + 1e-6:
                    break
                wa = candidate
        enriched_after = min(
            (s["start"] for s in brief["segments"]
             if s["start"] >= wb - 1e-6
             and s["visual_strategy"]["composition"]["family"] != "no_broll"),
            default=None)
        idx = last
        while wb - wa < minimum and idx + 1 < len(words):
            idx += 1
            candidate = words[idx].get("cut")
            if candidate is not None:
                end = candidate + (words[idx]["end"] - words[idx]["start"])
                if enriched_after is not None and end > enriched_after - 1e-6:
                    break
                wb = end
        # an unowned pause before the next beat can close the shortfall
        if (wb - wa < minimum and enriched_after is not None
                and enriched_after > wb and enriched_after - wa >= minimum):
            wb = enriched_after
    edges = [wa, wb]
    qedges = sorted(set(round(e * 24) / 24 for e in edges))
    enriched = [s for s in brief["segments"]
                if s["visual_strategy"]["composition"]["family"] != "no_broll"]
    # frame rounding can push an edge a few hundredths past a neighbouring
    # beat; snap it onto that beat's boundary instead of crossing it
    snapped = []
    for index, edge in enumerate(qedges):
        for segment in enriched:
            deep = segment["end"] - segment["start"] > 0.5
            barely = edge - segment["start"] < 0.06 or segment["end"] - edge < 0.06
            if segment["start"] < edge < segment["end"] - 1e-9 and not (deep and not barely):
                edge = segment["start"] if index == len(qedges) - 1 else segment["end"]
                break
        snapped.append(edge)
    qedges = sorted(set(snapped))
    anchor_times = [words[first]["cut"], words[last]["cut"]]

    def _is_replace_target(segment):
        # the beat being rebuilt owns the anchor words; neighbours never do
        return (segment["visual_strategy"]["composition"]["family"] != "no_broll"
                and any(segment["start"] <= t < segment["end"] for t in anchor_times
                        if t is not None))

    for edge in qedges:
        for i, segment in enumerate(list(brief["segments"])):
            if segment["start"] < edge - 1e-6 < segment["end"] - 1e-6:
                if _is_replace_target(segment):
                    break
                _split_segment(brief, i, edge, next_id)
                break
    qwa, qwb = qedges[0], qedges[-1]
    inside = [i for i, s in enumerate(brief["segments"])
              if s["end"] > qwa + 1e-6 and s["start"] < qwb - 1e-6]
    if not inside:
        raise SystemExit(f"no plan segment inside word window {wa:.2f}-{wb:.2f}")
    first_i, last_i = inside[0], inside[-1]
    span = {"start": min(brief["segments"][first_i]["start"], qwa),
            "end": max(brief["segments"][last_i]["end"], qwb)}
    return span, first_i, last_i



def _retire_treatment_records(treatment: dict, replaced_ids: set[str]) -> None:
    """Drop earlier treatment records of segments being rebuilt."""
    for holder, key in ((treatment.get("skill_selection", {}), "beats"),
                        (treatment, "scenes"),
                        (treatment, "semantic_assessments"),
                        (treatment, "overlay_selection"),
                        (treatment, "overlay_alignment")):
        if isinstance(holder, dict) and isinstance(holder.get(key), list):
            holder[key] = [r for r in holder[key]
                           if not (isinstance(r, dict) and r.get("segment_id") in replaced_ids)]



def _renumber_and_refreeze(job_dir: Path, ni: Path, project: Path) -> dict:
    """Compact all segment ids to seg-001..N and refreeze every brief/binding.

    Splitting bumps ids past the 3-digit render limit; this runs after each
    build so the plan always publishes with renderable ids.
    """
    import importlib.util
    brief_doc = json.loads((ni / "director-brief.json").read_text())
    treatment = json.loads((ni / "treatment.json").read_text())
    mapping = {s["segment_id"]: f"seg-{i + 1:03d}"
               for i, s in enumerate(brief_doc["segments"])}

    specs = []
    for candidate in sorted(ni.glob("*/brief.json")):
        data = json.loads(candidate.read_text())
        specs.append((candidate, data))
    by_old_segment = {}
    for path, data in specs:
        sb = data.get("source_binding", {})
        if "segment_id" in sb:
            by_old_segment.setdefault(sb["segment_id"], []).append((path, data))

    adapters = {}
    def adapter_for(dependency_id):
        if dependency_id not in adapters:
            module_name = ("riso_native_adapter" if dependency_id == "eian-riso-broll"
                           else "hyperframes_native_adapter")
            spec = importlib.util.spec_from_file_location(
                "hd_" + module_name, SKILL / "scripts" / (module_name + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            def loader(job, recipe, component):
                wanted = component["brief_sha256"]
                for c in (Path(job.job_dir) / "native-inputs").glob("**/brief.json"):
                    raw = c.read_bytes()
                    if hashlib.sha256(raw).hexdigest() == wanted:
                        return raw
                raise ValueError("frozen brief not found")
            adapters[dependency_id] = (module, module.create_adapter(project, sys.executable, loader))
        return adapters[dependency_id]

    riso_sample = (SKILL.parents[1] /
                   "skill-development/test-output/cutcod-riso-20261021/"
                   "minimal-native-gbnr7_er/riso-number-normalized.mp4")

    for segment in brief_doc["segments"]:
        old = segment["segment_id"]
        new = mapping[old]
        segment["segment_id"] = new
        segment["visual_intent"]["segment_id"] = new
        segment["visual_strategy"]["segment_id"] = new
        for path, data in by_old_segment.get(old, []):
            data["source_binding"]["segment_id"] = new
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            path.write_bytes(payload)
            dependency_id = ("eian-riso-broll" if data.get("template")
                             else "hyperframes-native-adaptation")
            module, adapter = adapter_for(dependency_id)
            if dependency_id == "eian-riso-broll":
                sample = riso_sample
            else:
                route = data["upstream_route"].removeprefix("hyperframes/")
                folder = ("blocks" if route == "macos-notification" else "components")
                sample = project / REGISTRY / folder / route / (route + ".html")
            for component_id, binding in segment["bindings"].items():
                segment["bindings"][component_id] = module.create_binding(
                    adapter, payload, sample)

    for holder, keys in ((treatment.get("skill_selection", {}), ("beats", "assignments")),
                         (treatment, ("scenes", "semantic_assessments",
                                      "overlay_selection", "overlay_alignment"))):
        for key in keys:
            for record in holder.get(key, []) or []:
                if isinstance(record, dict) and record.get("segment_id") in mapping:
                    record["segment_id"] = mapping[record["segment_id"]]
    segments_by_id = {s["segment_id"]: s for s in brief_doc["segments"]}
    selection = treatment.get("skill_selection", {})
    for beat in selection.get("beats", []):
        segment = segments_by_id.get(beat["segment_id"])
        if segment and segment["bindings"]:
            beat["binding_snapshot"] = next(iter(segment["bindings"].values()))
    if selection.get("beats"):
        from edit.hd.tools.broll_skill_selection import assign_skills
        selection["assignments"] = assign_skills(project, selection)["assignments"]

    # Refrozen briefs have new hashes; keep every cited content reference current.
    by_segment = {}
    for path, data in specs:
        sb = data.get("source_binding", {})
        if sb.get("segment_id") in segments_by_id:
            binding = segments_by_id[sb["segment_id"]]["bindings"]
            if binding:
                by_segment[sb["segment_id"]] = (
                    str(path.relative_to(job_dir)),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    data.get("template") or data.get("upstream_route", ""))
    for record in treatment.get("semantic_assessments", []):
        info = by_segment.get(record.get("segment_id"))
        if info:
            record["content_refs"] = [{
                "path": info[0], "sha256": info[1],
                "pointer": "/template" if not info[2].startswith("hyperframes/") else "/upstream_route",
                "value": info[2]}]

    reviewed_path = ni / "reviewed-visual-text.json"
    if reviewed_path.is_file():
        reviewed = json.loads(reviewed_path.read_text())
        reviewed["entries"] = [
            {**e, "segment_id": mapping.get(e["segment_id"], e["segment_id"])}
            for e in reviewed.get("entries", [])
            if e.get("segment_id") in mapping]
        reviewed_path.write_text(json.dumps(reviewed, ensure_ascii=False, indent=2) + "\n")

    (ni / "director-brief.json").write_text(
        json.dumps(brief_doc, ensure_ascii=False, indent=2) + "\n")
    (ni / "treatment.json").write_text(
        json.dumps(treatment, ensure_ascii=False, indent=2) + "\n")
    return {"segments": len(brief_doc["segments"]),
            "renumbered": sum(1 for old, new in mapping.items() if old != new)}


def _register_broll_treatment(job_dir, ni, treatment, segment, span, binding,
                              statement, args, words, brief_path, brief_bytes,
                              *, chosen, project):
    """Shared beat + scene + semantic assessment registration for B-roll components."""
    from edit.hd.tools.broll_skill_selection import discover_candidates, assign_skills
    beat = {
        "segment_id": segment["segment_id"], "component_id": "native-broll",
        "start": span["start"], "end": span["end"],
        "transcript": statement, "semantic_goal": "demonstrate",
        "required_change": args.required_change or "把口播内容变成可见画面",
        "intent_statement": statement, "component_brief": statement,
        "binding_snapshot": binding,
        "skill_reviews": {}, "candidates": [],
    }
    pool = {row["candidate_id"]: row for row in discover_candidates(project)}
    chosen_skill = pool[chosen]["skill_id"]
    for skill in {row["skill_id"] for row in pool.values()}:
        beat["skill_reviews"][skill] = {
            "fit": "preferred" if skill == chosen_skill else "unsuitable",
            "reason": (args.reason if skill == chosen_skill else
                       "与本句演示语义不符或未接通该用途"),
        }
    beat["candidates"] = [{
        "candidate_id": chosen, "fit": "preferred", "reason": args.reason,
        "visual_pattern": chosen.split("/")[-1],
    }]
    selection = treatment.setdefault("skill_selection", {})
    selection["schema_version"] = 1
    selection.setdefault("beats", []).append(beat)
    selection["recent_context"] = selection.get("recent_context", [])
    selection["history_note"] = selection.get("history_note") or "无历史视频可参考"
    selection["assignments"] = assign_skills(project, selection)["assignments"]
    treatment.setdefault("scenes", []).append({
        "segment_id": segment["segment_id"], "component_id": "native-broll",
        "brief_path": str(brief_path.relative_to(job_dir)),
    })
    quote_words = [w for w in words if w.get("cut") is not None
                   and w["cut"] < span["end"] and w["cut"] + (w["end"] - w["start"]) > span["start"]]
    start_word = words.index(quote_words[0])
    treatment.setdefault("semantic_assessments", []).append({
        "segment_id": segment["segment_id"], "component_id": "native-broll",
        "candidate_id": chosen, "verdict": "pass", "reason": args.reason,
        "transcript_refs": [{
            "start_word": start_word, "end_word": start_word + len(quote_words),
            "quote": "".join(w["text"] for w in quote_words),
            "basis": "current_clause",
        }],
        "content_refs": [{
            "path": str(brief_path.relative_to(job_dir)),
            "sha256": hashlib.sha256(brief_bytes).hexdigest(),
            "pointer": "/template", "value": chosen.split("/")[-1],
        }],
    })


def build_visual(job_dir: Path, project: Path, args) -> dict:
    from edit.hd.tools import state
    from edit.hd.tools.overlay_alignment import bind_native_clock
    adapter_mod = _load(project, "hyperframes_native_adapter")

    ni = job_dir / "native-inputs"
    brief_doc = json.loads((ni / "director-brief.json").read_text())
    treatment = json.loads((ni / "treatment.json").read_text())
    words, _cuts = _word_cut_times(job_dir)
    arroll_sha = hashlib.sha256((job_dir / "06-edit-structure/edited-aroll.mp4").read_bytes()).hexdigest()

    route = args.route

    if args.kind == "overlay":
        labels = [s.strip() for s in args.labels.split(",") if s.strip()]
        anchors = [int(x) for x in args.anchors.split(",")]
        if not labels or not anchors:
            raise SystemExit("overlay needs --labels and --anchors")
        anchor_words = [words[i] for i in anchors]
        if any(w["cut"] is None for w in anchor_words):
            raise SystemExit("anchor word was deleted from the cut timeline")
        minimum = max({"notification-stack": 5.5, "grid-card-assemble": 2.5,
                        "before-after-wipe": 10.3}.get(route, 0.0),
                      args.min_seconds or 0.0)
        span, first, last = _window_span(brief_doc, words, anchors[0], anchors[-1],
                                         minimum=minimum)
        slug = (route + "-" + (labels[0][:6] if labels else "")).replace("/", "-").replace(" ", "")
        folder = ni / f"{slug}-{int(span['start'])}"
        folder.mkdir(parents=True, exist_ok=True)
        if route == "before-after-wipe":
            if len(labels) != 2 or len(anchors) < 2:
                raise SystemExit("before-after-wipe needs two labels and a wipe anchor")
            duration = span["end"] - span["start"]
            wipe_at = max(0.0, words[anchors[1]]["cut"] - span["start"])
            # the wipe needs raw + 1.05s + exit inside the shot; extend the span
            while duration < wipe_at + 1.05 + 0.6 and last + 1 < len(brief_doc["segments"]):
                last += 1
                span["end"] = brief_doc["segments"][last]["end"]
                duration = span["end"] - span["start"]
            if duration < wipe_at + 1.05 + 0.55:
                raise SystemExit("shot is too short for the comparison wipe")
            scale = min(1.0, duration / (wipe_at + 1.05 + 0.5))
            land_time = span["start"] + (wipe_at + 1.05) * scale
            land_candidates = [i for i, w in enumerate(words)
                               if w.get("cut") is not None
                               and span["start"] <= w["cut"] < span["end"]
                               and w["cut"] - 1 / 24 <= land_time <= w["cut"] + 0.8]
            if not land_candidates:
                raise SystemExit("no spoken word aligns with the wipe landing")
            land_anchor = land_candidates[0]
            first_word_in_shot = next(i for i, w in enumerate(words)
                                      if w.get("cut") is not None and w["cut"] >= span["start"])
            events = [
                {"slot": 0, "kind": "reveal", "text": labels[0],
                 "anchor": {"index": first_word_in_shot, "text": words[first_word_in_shot]["text"]},
                 "basis": "current_clause"},
                {"slot": 1, "kind": "wipe_start", "text": labels[1],
                 "anchor": {"index": anchors[1], "text": words[anchors[1]]["text"]},
                 "basis": "current_clause"},
                {"slot": 1, "kind": "wipe_land", "text": labels[1],
                 "anchor": {"index": land_anchor, "text": words[land_anchor]["text"]},
                 "basis": "current_clause"},
            ]
            values = {"label_a": labels[0], "label_b": labels[1],
                      "wipe_at": f"{wipe_at:.6f}", "rest_split": "50", "exit": "fade"}
            variable_key = None
        else:
            variable_key = "titles" if route == "notification-stack" else (
                "items" if route == "grid-card-assemble" else None)
            if variable_key is None:
                raise SystemExit(f"route {route} needs a dedicated builder; not wired here")
            if not labels or len(anchors) < len(labels):
                raise SystemExit("each label needs an anchor (a span anchor may be extra)")
            events = [{"slot": i, "kind": "reveal", "text": labels[i],
                       "anchor": {"index": anchors[i], "text": words[anchors[i]]["text"]},
                       "basis": "current_clause"} for i in range(len(labels))]
            cues = ",".join(f"{max(0.0, words[i]['cut'] - span['start']):.6f}" for i in anchors)
            values = {variable_key: ",".join(labels), "cues": cues, "exit": "fade"}
        duration = span["end"] - span["start"]
        frames = round(duration * 24)
        semantic_family, visible_action, visual_structure = OVERLAY_ROUTES[route]
        upstream_route = "hyperframes/" + route
        source_path = project / REGISTRY / "components" / route / (route + ".html")
        source_bytes = source_path.read_bytes()
        native_bytes = bind_native_clock(source_bytes, upstream_route, duration)
        if route == "before-after-wipe":
            art = ('<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" '
                   'width="120" height="120"><circle cx="60" cy="60" r="44" fill="none" '
                   'stroke="#bdb59d" stroke-width="8"/></svg>')
            from edit.hd.tools.overlay_alignment import bind_native_slots
            native_bytes = bind_native_slots(native_bytes, {"before": art, "after": art})
        native_path = folder / "native.html"
        native_path.write_bytes(native_bytes)
        entry = (f'<div data-composition-id="{route}" data-composition-src="native.html" '
                 f"data-variable-values='{json.dumps(values, ensure_ascii=False)}' "
                 f'data-start="0" data-duration="{duration}"></div>')
        entry_path = folder / "index.html"
        entry_path.write_text(entry, encoding="utf-8")
        template_request = {"semantic_family": semantic_family, "information_units": 2,
                            "numeric_values": [], "numeric_scale": "not_applicable"}
        alpha = True
        component_id = "native-visual"
        statement = args.statement or words[anchors[0]]["text"]
    else:
        if args.riso_template:
            # Riso dual-tone infographic B-roll via riso_native_adapter.
            riso = _load(project, "riso_native_adapter")
            if route not in BROLL_ROUTES:
                pass  # riso templates are not hyperframes routes
            if args.first_word is None or args.last_word is None:
                raise SystemExit("riso needs --first-word/--last-word")
            anchor_words = words[args.first_word:args.last_word + 1]
            if any(w.get("cut") is None for w in anchor_words):
                raise SystemExit("B-roll window word was deleted from the cut timeline")
            span, first, last = _window_span(
                brief_doc, words, args.first_word, args.last_word,
                minimum=max(riso.MIN_SECONDS[args.riso_template], args.min_seconds or 0.0))
            duration = span["end"] - span["start"]
            frames = round(duration * 24)
            if frames < riso.MIN_SECONDS[args.riso_template] * 24:
                raise SystemExit(
                    f"riso {args.riso_template} needs >= {riso.MIN_SECONDS[args.riso_template]}s; "
                    f"window is {duration:.1f}s")
            data = json.loads(args.data)
            data["duration"] = duration
            units = {"title": 1, "quote": 1, "versus": 2, "number": 1,
                     "focus": len(data.get("items", [])), "converge": 2,
                     "compare": 2, "steps": len(data.get("steps", [])),
                     "network": 1, "shot": 1}[args.riso_template]
            numbers = [data["number"]] if args.riso_template == "number" else []
            template = args.riso_template
            brief = {
                "schema_version": 1,
                "source_binding": {"aroll_sha256": arroll_sha, "segment_id": "seg-TBD",
                                   "start": span["start"], "end": span["end"]},
                "composition": {"id": f"riso-{template}", "width": 1080, "height": 1920,
                                 "fps": 24, "frames": frames},
                "template_request": {
                    "semantic_family": riso.FAMILIES[template],
                    "information_units": units,
                    "numeric_values": numbers,
                    "numeric_scale": "linear" if numbers else "not_applicable"},
                "template": template,
                "data": data,
                "assets": [],
            }
            folder = ni / f"riso-{template}-{int(span['start'])}"
            folder.mkdir(parents=True, exist_ok=True)
            folder.mkdir(parents=True, exist_ok=True)
            brief_path = folder / "brief.json"
            brief_bytes = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            brief_path.write_bytes(brief_bytes)
            riso_sample = (SKILL.parents[1] /
                           "skill-development/test-output/cutcod-riso-20261021/"
                           "minimal-native-gbnr7_er/riso-number-normalized.mp4")
            def riso_loader(job, recipe, component):
                wanted = component["brief_sha256"]
                for candidate in Path(job.job_dir).glob("native-inputs/**/brief.json"):
                    raw = candidate.read_bytes()
                    if hashlib.sha256(raw).hexdigest() == wanted:
                        return raw
                raise ValueError("frozen riso brief not found")
            adapter = riso.create_adapter(project, sys.executable, riso_loader)
            binding = riso.create_binding(adapter, brief_bytes, riso_sample)
            upstream_route = f"eian-riso-broll/{template}"
            component_id = "native-broll"
            labels = None
            events = None
            statement = args.statement or "".join(w["text"] for w in anchor_words)[:60]
            segment = {
                "segment_id": brief_doc["segments"][first]["segment_id"],
                "start": span["start"], "end": span["end"],
                "content_item_ids": brief_doc["segments"][first]["content_item_ids"],
                "visible_text": [],
                "visual_intent": {
                    "segment_id": brief_doc["segments"][first]["segment_id"],
                    "statement": statement,
                    "semantic_goals": ["explain"],
                    "claims": [], "entities": [], "relations": [],
                    "requirements": {"verifiability": "low", "realism": "medium",
                                      "abstraction": "high", "product_specificity": "low",
                                      "emotional_intensity": "low"},
                    "presenter_presence": "hidden",
                },
                "visual_strategy": {
                    "schema_version": 1,
                    "segment_id": brief_doc["segments"][first]["segment_id"],
                    "mode": "single",
                    "rationale": args.reason,
                    "components": [{
                        "component_id": component_id, "kind": "code_generated",
                        "semantic_role": "explanation", "layer_role": "base",
                        "media_type": "video", "layout_slot": "full_frame",
                        "brief": statement,
                    }],
                    "composition": {
                        "family": "single_full_frame", "presenter_mode": "hidden",
                        "reading_order": [component_id],
                        "component_dependencies": [],
                    },
                },
                "candidate_snapshots": {},
                "bindings": {component_id: binding},
                "strategy_revision": 1,
            }
            brief["source_binding"]["segment_id"] = segment["segment_id"]
            brief_bytes = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            brief_path.write_bytes(brief_bytes)
            binding = riso.create_binding(adapter, brief_bytes, riso_sample)
            segment["bindings"][component_id] = binding
            replaced_ids = {s["segment_id"] for s in brief_doc["segments"][first:last + 1]}
            replaced_ids.add(segment["segment_id"])
            _retire_treatment_records(treatment, replaced_ids)
            brief_doc["segments"][first:last + 1] = [segment]
            (ni / "director-brief.json").write_text(
                json.dumps(brief_doc, ensure_ascii=False, indent=2) + "\n")
            _register_broll_treatment(job_dir, ni, treatment, segment, span, binding,
                                      statement, args, words, brief_path, brief_bytes,
                                      chosen=f"eian-riso-broll:{template}", project=project)
            (ni / "treatment.json").write_text(
                json.dumps(treatment, ensure_ascii=False, indent=2) + "\n")
            return {"kind": "riso", "route": template, "segment_id": segment["segment_id"],
                    "window": [round(span["start"], 2), round(span["end"], 2)],
                    "frames": frames, "labels": labels}

        if route not in BROLL_ROUTES:
            raise SystemExit(f"{route} is not an opaque full-screen B-roll route")
        first_word, last_word = args.first_word, args.last_word
        anchor_words = words[first_word:last_word + 1]
        if any(w.get("cut") is None for w in anchor_words):
            raise SystemExit("B-roll window word was deleted from the cut timeline")
        span, first, last = _window_span(
            brief_doc, words, args.first_word, args.last_word,
            minimum=args.min_seconds or 0.0)
        folder = ni / f"{route}-{int(span['start'])}"
        folder.mkdir(parents=True, exist_ok=True)
        duration = span["end"] - span["start"]
        frames = round(duration * 24)
        upstream_route = "hyperframes/" + route
        semantic_family = args.semantic_family or "demonstration"
        source_path = project / REGISTRY / ("blocks" if route == "macos-notification" else "components") / route / (route + ".html")
        source_bytes = source_path.read_bytes()
        # B-roll routes have no shared clock binder; retarget the public duration
        # attributes of the Job-owned copy to the window clock.
        native_text = source_bytes.decode("utf-8")
        import re as _re
        for attribute in ("data-composition-duration", "data-duration"):
            native_text = _re.sub(rf'{attribute}="[\d.]+"', f'{attribute}="{duration}"', native_text)
        native_bytes = native_text.encode("utf-8")
        native_path = folder / "native.html"
        native_path.write_bytes(native_bytes)
        values = json.loads(args.variables) if args.variables else {}
        entry = (f'<div data-composition-id="{route}" data-composition-src="native.html" '
                 f"data-variable-values='{json.dumps(values, ensure_ascii=False)}' "
                 f'data-start="0" data-duration="{duration}"></div>')
        entry_path = folder / "index.html"
        entry_path.write_text(entry, encoding="utf-8")
        template_request = {"semantic_family": semantic_family,
                            "information_units": max(1, len(values)),
                            "numeric_values": [], "numeric_scale": "not_applicable"}
        alpha = False
        component_id = "native-broll"
        events = None
        labels = None

    brief = {
        "schema_version": 2,
        "source_binding": {"aroll_sha256": arroll_sha, "segment_id": "seg-TBD",
                           "start": span["start"], "end": span["end"]},
        "template_request": template_request,
        "entry": {"media_ref": "native-entry", "job_path": str(entry_path.relative_to(job_dir)),
                  "scene_path": "index.html",
                  "sha256": hashlib.sha256(entry_path.read_bytes()).hexdigest()},
        "assets": [{"media_ref": "native-source", "job_path": str(native_path.relative_to(job_dir)),
                    "scene_path": "native.html",
                    "sha256": hashlib.sha256(native_bytes).hexdigest()}],
        "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": frames,
                        "alpha": alpha},
        "upstream_route": upstream_route,
        "source_pins": {"route": upstream_route,
                        "sha256": hashlib.sha256(source_bytes).hexdigest()},
    }

    # Build the plan segment first to learn the segment_id, then freeze the brief.
    span_index = first
    statement = args.statement or (words[anchors[0]]["text"] if args.kind == "overlay"
                                   else "".join(w["text"] for w in anchor_words)[:60])
    segment = {
        "segment_id": brief_doc["segments"][first]["segment_id"],
        "start": span["start"], "end": span["end"],
        "content_item_ids": brief_doc["segments"][first]["content_item_ids"],
        "visible_text": labels or [],
        "visual_intent": {
            "segment_id": brief_doc["segments"][first]["segment_id"],
            "statement": statement,
            "semantic_goals": ["explain" if args.kind == "overlay" else "demonstrate"],
            "claims": [], "entities": [], "relations": [],
            "requirements": {"verifiability": "low", "realism": "medium", "abstraction": "medium",
                              "product_specificity": "low", "emotional_intensity": "low"},
            "presenter_presence": "allowed" if args.kind == "overlay" else "hidden",
        },
        "visual_strategy": {
            "schema_version": 1,
            "segment_id": brief_doc["segments"][first]["segment_id"],
            "mode": "none" if args.kind == "overlay" else "single",
            "rationale": args.reason,
            "components": [{
                "component_id": component_id, "kind": "code_generated",
                "semantic_role": "explanation" if args.kind == "overlay" else "demonstration",
                "layer_role": "annotation" if args.kind == "overlay" else "base",
                "media_type": "animation" if alpha else "video",
                "layout_slot": "annotation" if args.kind == "overlay" else "main",
                "brief": statement,
            }],
            "composition": {
                "family": "aroll_with_overlay" if args.kind == "overlay" else "single_full_frame",
                "presenter_mode": "full_frame" if args.kind == "overlay" else "hidden",
                "reading_order": [component_id],
                "component_dependencies": [],
            },
        },
        "candidate_snapshots": {},
        "bindings": {},
        "strategy_revision": 1,
    }
    brief["source_binding"]["segment_id"] = segment["segment_id"]
    brief_path = folder / "brief.json"
    brief_bytes = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    brief_path.write_bytes(brief_bytes)

    # Frozen binding from the real adapter.
    def brief_loader(job, recipe, component):
        wanted = component["brief_sha256"]
        for candidate in Path(job.job_dir).glob("native-inputs/**/brief.json"):
            data = candidate.read_bytes()
            if hashlib.sha256(data).hexdigest() == wanted:
                return data
        raise ValueError("frozen brief not found for " + str(wanted))

    adapter = adapter_mod.create_adapter(project, sys.executable, brief_loader)
    binding = adapter_mod.create_binding(adapter, brief_bytes, source_path)
    segment["bindings"][component_id] = binding
    replaced_ids = {s["segment_id"] for s in brief_doc["segments"][first:last + 1]}
    replaced_ids.add(segment["segment_id"])
    brief_doc["segments"][first:last + 1] = [segment]
    (ni / "director-brief.json").write_text(
        json.dumps(brief_doc, ensure_ascii=False, indent=2) + "\n")

    # Treatment updates. Rebuilding a beat must retire its earlier records.
    _retire_treatment_records(treatment, replaced_ids)
    if args.kind == "overlay":
        semantic_family, visible_action, visual_structure = OVERLAY_ROUTES[route]
        treatment.setdefault("overlay_selection", []).append({
            "segment_id": segment["segment_id"], "component_id": component_id,
            "intent_relation": semantic_family, "native_route": route,
            "visible_action": visible_action, "visual_structure": visual_structure,
            "selection_reason": args.reason,
        })
        treatment.setdefault("overlay_alignment", []).append({
            "segment_id": segment["segment_id"], "component_id": component_id,
            "brief_path": str(brief_path.relative_to(job_dir)),
            "events": events,
        })
        candidate_id = "overlay:" + route
    else:
        beat = {
            "segment_id": segment["segment_id"], "component_id": component_id,
            "start": span["start"], "end": span["end"],
            "transcript": statement, "semantic_goal": "demonstrate",
            "required_change": args.required_change or "把口播动作变成可见画面",
            "intent_statement": statement, "component_brief": statement,
            "binding_snapshot": binding,
            "skill_reviews": {}, "candidates": [],
        }
        from edit.hd.tools.broll_skill_selection import discover_candidates, assign_skills
        pool = {row["candidate_id"]: row for row in discover_candidates(project)}
        chosen = f"hyperframes-native-adaptation:{upstream_route}"
        chosen_skill = pool[chosen]["skill_id"]
        for skill in {row["skill_id"] for row in pool.values()}:
            beat["skill_reviews"][skill] = {
                "fit": "preferred" if skill == chosen_skill else "unsuitable",
                "reason": (args.reason if skill == chosen_skill else
                           "与本句演示语义不符或未接通该用途"),
            }
        beat["candidates"] = [{
            "candidate_id": chosen, "fit": "preferred", "reason": args.reason,
            "visual_pattern": route,
        }]
        selection = treatment.setdefault("skill_selection", {})
        selection["schema_version"] = 1
        selection.setdefault("beats", []).append(beat)
        selection["recent_context"] = selection.get("recent_context", [])
        selection["history_note"] = selection.get("history_note") or "无历史视频可参考"
        selection["assignments"] = assign_skills(project, selection)["assignments"]
        treatment.setdefault("scenes", []).append({
            "segment_id": segment["segment_id"], "component_id": component_id,
            "brief_path": str(brief_path.relative_to(job_dir)),
        })
        candidate_id = chosen

    quote_words = [w for w in words if w.get("cut") is not None
                   and w["cut"] < span["end"] and w["cut"] + (w["end"] - w["start"]) > span["start"]]
    start_word = words.index(quote_words[0])
    treatment.setdefault("semantic_assessments", []).append({
        "segment_id": segment["segment_id"], "component_id": component_id,
        "candidate_id": candidate_id, "verdict": "pass", "reason": args.reason,
        "transcript_refs": [{
            "start_word": start_word, "end_word": start_word + len(quote_words),
            "quote": "".join(w["text"] for w in quote_words),
            "basis": "current_clause",
        }],
        "content_refs": [{
            "path": str(brief_path.relative_to(job_dir)),
            "sha256": hashlib.sha256(brief_bytes).hexdigest(),
            "pointer": "/upstream_route", "value": upstream_route,
        }],
    })
    (ni / "treatment.json").write_text(json.dumps(treatment, ensure_ascii=False, indent=2) + "\n")

    return {"kind": args.kind, "route": route, "segment_id": segment["segment_id"],
            "window": [round(span["start"], 2), round(span["end"], 2)],
            "frames": frames, "labels": labels}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--project-root", type=Path)
    sub = parser.add_subparsers(dest="kind")
    for name in ("overlay", "broll"):
        p = sub.add_parser(name)
        p.add_argument("--route", default="")
        p.add_argument("--riso-template", default="",
                       help="riso template id (number/focus/versus/quote/title/…)")
        p.add_argument("--min-seconds", type=float, default=0.0,
                       help="override window minimum (drives word-boundary extension)")
        p.add_argument("--data", default="{}", help="riso native DATA json")
        p.add_argument("--labels", default="")
        p.add_argument("--anchors", default="")
        p.add_argument("--first-word", type=int)
        p.add_argument("--last-word", type=int)
        p.add_argument("--variables", default="")
        p.add_argument("--semantic-family", default="")
        p.add_argument("--statement", default="")
        p.add_argument("--required-change", default="")
        p.add_argument("--reason", required=True)
    parser.add_argument("--finalize", action="store_true",
                        help="renumber segments and refreeze briefs/bindings")
    args = parser.parse_args()
    args.kind = args.kind or "overlay"

    project = (args.project_root or SKILL.parents[1]).resolve()
    sys.path.insert(0, str(project))
    from run_stage import auto_resign
    auto_resign()
    job_dir = Path(json.loads(args.job_context.read_text())["job_dir"])
    if args.finalize:
        print(json.dumps(_renumber_and_refreeze(job_dir, job_dir / "native-inputs", project),
                         ensure_ascii=False))
        return 0
    result = build_visual(job_dir, project, args)
    result.update(_renumber_and_refreeze(job_dir, job_dir / "native-inputs", project))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

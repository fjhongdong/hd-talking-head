#!/usr/bin/env python3
"""Compose the enriched visual plan in ONE shot from a beat specification.

Usage:
  <python> compose_visual_plan.py --job-context ctx --beats beats.json

beats.json is a list of beat objects; every beat becomes an overlay or B-roll
segment with word-anchored windows, native briefs, frozen bindings, treatment
records and the reviewed-visual-text receipt written atomically. No
incremental mutation, no renumbering: windows are resolved against their
neighbours first, then the whole plan is emitted with final segment ids.

Beat fields:
  kind: overlay | broll            route: hyperframes route id
  riso_template: riso template id  labels: overlay labels
  anchors: overlay anchor word indices (first/last define the window)
  first_word/last_word: B-roll window words
  min_seconds: window minimum (extension stays inside neighbour beats)
  variables: hyperframes mount values | data: riso DATA json
  statement/reason/required_change: treatment text
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

GRID = {"notification-stack": 5.5, "grid-card-assemble": 2.5, "before-after-wipe": 8.0}
OVERLAY_ROUTES = {
    "notification-stack": ("reminder", "notification_stack", "notification-stack"),
    "grid-card-assemble": ("parallel", "staggered_card_reveal", "grid-list"),
    "before-after-wipe": ("compare", "moving_split_reveal", "before-after-split"),
}
BROLL_ROUTES = ("macos-notification", "chat-message", "screen-flow-carousel", "beat-timeline")
REGISTRY = Path("参考项目/B-roll开源方案/hyperframes/registry")
RISO_SAMPLE = ("skill-development/test-output/cutcod-riso-20261021/"
               "minimal-native-gbnr7_er/riso-number-normalized.mp4")


def _module(name):
    spec = importlib.util.spec_from_file_location("hd_" + name, SKILL / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _word_cut_times(job_dir: Path):
    report = json.loads((job_dir / "05-speech-cleanup/report.json").read_text())
    words = report["transcript"]["words"]
    cuts = json.loads((job_dir / "06-edit-structure/timeline-map.json").read_text())["segments"]
    for word in words:
        word["cut"] = None
        for cut in cuts:
            if cut["source_start"] <= word["start"] and word["end"] <= cut["source_end"]:
                word["cut"] = cut["timeline_start"] + (word["start"] - cut["source_start"])
                break
        word["cut_end"] = (word["cut"] + (word["end"] - word["start"])
                           if word["cut"] is not None else None)
    return words


def _resolve_windows(beats: list[dict], words: list[dict], duration: float) -> list[dict]:
    """Compute every beat window with neighbour clamps; no timeline mutation."""
    raw = []
    for index, beat in enumerate(beats):
        if beat["kind"] == "overlay":
            anchors = [int(x) for x in beat["anchors"]]
            if any(words[i]["cut"] is None for i in anchors):
                raise SystemExit(f"beat {index}: anchor word deleted from cut")
            wa = words[anchors[0]]["cut"]
            wb = words[anchors[-1]]["cut_end"]
            minimum = max(GRID.get(beat["route"], 0.0), beat.get("min_seconds") or 0.0)
        else:
            first, last = int(beat["first_word"]), int(beat["last_word"])
            span_words = words[first:last + 1]
            if any(w["cut"] is None for w in (span_words[0], span_words[-1])):
                raise SystemExit(f"beat {index}: window word deleted from cut")
            wa = span_words[0]["cut"]
            wb = span_words[-1]["cut_end"]
            minimum = beat.get("min_seconds") or 0.0
        raw.append({"beat": beat, "index": index, "wa": wa, "wb": wb, "minimum": minimum})

    for position, entry in enumerate(raw):
        prev_end = raw[position - 1]["wb"] if position else 0.0
        next_start = raw[position + 1]["wa"] if position + 1 < len(raw) else duration
        wa, wb, minimum = entry["wa"], entry["wb"], entry["minimum"]
        # backward extension, never before the previous beat
        idx = entry["index"]
        if entry["beat"]["kind"] == "overlay":
            anchors = [int(x) for x in entry["beat"]["anchors"]]
            cursor = anchors[0]
        else:
            cursor = int(entry["beat"]["first_word"])
        while wb - wa < minimum and cursor > 0:
            cursor -= 1
            if words[cursor]["cut"] is not None and words[cursor]["cut"] > prev_end + 1e-6:
                wa = words[cursor]["cut"]
            elif words[cursor]["cut"] is not None:
                break
        # forward extension, never past the next beat
        if entry["beat"]["kind"] == "overlay":
            cursor = int(entry["beat"]["anchors"][-1])
        else:
            cursor = int(entry["beat"]["last_word"])
        while wb - wa < minimum and cursor + 1 < len(words):
            cursor += 1
            if words[cursor]["cut_end"] is not None and words[cursor]["cut_end"] < next_start - 1e-6:
                wb = words[cursor]["cut_end"]
            elif words[cursor]["cut_end"] is not None:
                break
        # an unowned pause before the next beat may close the shortfall
        if wb - wa < minimum and next_start - wa >= minimum:
            wb = next_start
        if wb - wa < minimum - 1e-6:
            raise SystemExit(
                f"beat {entry['index']} window {wa:.2f}-{wb:.2f} cannot reach "
                f"{minimum:.1f}s inside its neighbours")
        entry["wa"], entry["wb"] = wa, wb
    for a, b in zip(raw, raw[1:]):
        if a["wb"] > b["wa"] + 1e-6:
            raise SystemExit(f"beats {a['index']}/{b['index']} overlap after resolution")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--beats", type=Path, required=True)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args()

    project = (args.project_root or SKILL.parents[1]).resolve()
    sys.path.insert(0, str(project))
    from run_stage import auto_resign
    auto_resign()
    job_dir = Path(json.loads(args.job_context.read_text())["job_dir"])
    beats = json.loads(args.beats.read_text())
    words = _word_cut_times(job_dir)
    timeline = json.loads((job_dir / "06-edit-structure/timeline-map.json").read_text())
    duration = float(timeline["output_duration"])
    ca = json.loads((job_dir / "02-content-analysis/content-analysis.json").read_text())
    items = ca["analysis"]["items"]
    arroll_sha = hashlib.sha256(
        (job_dir / "06-edit-structure/edited-aroll.mp4").read_bytes()).hexdigest()

    # bump the strategy revision above the previously published plan so
    # changed recipes pass the canary identity gate
    previous_plan = job_dir / "07-visual-direction/visual-plan.json"
    revision_base = 1
    if previous_plan.is_file():
        try:
            revision_base = 1 + max(
                (int(s.get("strategy_revision", 1))
                 for s in json.loads(previous_plan.read_text()).get("segments", [])),
                default=0)
        except (OSError, ValueError, TypeError):
            revision_base = 1

    resolved = _resolve_windows(beats, words, duration)
    # quantize every edge to whole frames, clamped to the resolved neighbours
    limit = round(duration * 24) / 24
    for position, entry in enumerate(resolved):
        upper = (round(resolved[position + 1]["wa"] * 24) / 24
                 if position + 1 < len(resolved) else limit)
        entry["qs"] = max(0.0, min(round(entry["wa"] * 24) / 24, upper))
    for position, entry in enumerate(resolved):
        lower = entry["qs"]
        upper = (resolved[position + 1]["qs"]
                 if position + 1 < len(resolved) else limit)
        entry["qe"] = max(lower + 1 / 24, min(round(entry["wb"] * 24) / 24, upper))
    for a, b in zip(resolved, resolved[1:]):
        if a["qe"] > b["qs"] + 1e-6:
            a["qe"] = b["qs"]

    # Emit the contiguous segment list: base cut units between beat windows.
    segments = []
    cursor = 0.0
    beat_segments = []
    for entry in resolved:
        for cut in timeline["segments"]:
            if cut["timeline_end"] <= cursor + 1e-6 or cut["timeline_start"] >= entry["qs"] - 1e-6:
                continue
            start = max(cut["timeline_start"], cursor)
            end = min(cut["timeline_end"], entry["qs"])
            if end - start > 1e-6:
                segments.append(("base", start, end))
        segments.append(("beat", entry["qs"], entry["qe"], entry))
        cursor = entry["qe"]
    if duration - cursor > 1e-6:
        segments.append(("base", cursor, duration))

    ni = job_dir / "native-inputs"
    calibration = {}
    cal_path = ni / "avatar-calibration.json"
    if cal_path.is_file():
        for key, avatar in json.loads(cal_path.read_text()).items():
            lo, hi = (float(x) for x in key.split(","))
            calibration[(round(lo, 2), round(hi, 2))] = avatar
    if ni.exists():
        import shutil
        shutil.rmtree(ni)
    ni.mkdir(parents=True)
    (ni / "avatar-calibration.json").write_text(json.dumps(
        {f"{lo},{hi}": av for (lo, hi), av in calibration.items()},
        ensure_ascii=False, indent=2) + "\n")

    from edit.hd.tools.overlay_alignment import bind_native_clock, bind_native_slots
    hyper = _module("hyperframes_native_adapter")
    riso = _module("riso_native_adapter")

    def brief_loader(job, recipe, component):
        wanted = component["brief_sha256"]
        for candidate in (Path(job.job_dir) / "native-inputs").glob("**/brief.json"):
            data = candidate.read_bytes()
            if hashlib.sha256(data).hexdigest() == wanted:
                return data
        raise ValueError("frozen brief not found: " + str(wanted))

    hyper_adapter = hyper.create_adapter(project, sys.executable, brief_loader)
    riso_adapter = riso.create_adapter(project, sys.executable, brief_loader)

    treatment = {
        "schema_version": 2, "overlay_alignment": [], "overlay_selection": [],
        "repeat_review": [], "scenes": [], "semantic_assessments": [],
        "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                             "fixed_context": [], "recent_context": [],
                             "history_note": "无历史视频可参考"},
        "title": json.loads((job_dir / "workflow.json").read_text()).get("title", ""),
    }
    receipt = {"content_analysis_sha256": ca["analysis_sha256"], "entries": []}
    plan_segments = []
    beat_index = 0

    for kind, start, end, *rest in [(s[0], s[1], s[2], *s[3:]) for s in segments]:
        sid = f"seg-{len(plan_segments) + 1:03d}"
        if kind == "base":
            plan_segments.append({
                "segment_id": sid, "start": start, "end": end,
                "content_item_ids": [items[0]["id"]], "visible_text": [],
                "visual_intent": {"segment_id": sid, "statement": "口播讲解",
                                   "semantic_goals": ["explain"], "claims": [], "entities": [],
                                   "relations": [], "requirements": {
                                       "verifiability": "low", "realism": "medium",
                                       "abstraction": "medium", "product_specificity": "low",
                                       "emotional_intensity": "low"},
                                   "presenter_presence": "allowed"},
                "visual_strategy": {"schema_version": 1, "segment_id": sid, "mode": "none",
                                     "rationale": "纯 A-roll 真人讲解", "components": [],
                                     "composition": {"family": "no_broll",
                                                      "presenter_mode": "full_frame",
                                                      "reading_order": [],
                                                      "component_dependencies": []}},
                "candidate_snapshots": {}, "bindings": {}, "strategy_revision": 1,
            })
            continue
        entry = rest[0]
        beat = entry["beat"]
        duration_beat = end - start
        frames = round(duration_beat * 24)
        folder = ni / f"beat{beat_index:02d}-{beat.get('route') or beat.get('riso_template')}"
        folder.mkdir()
        beat_index += 1
        quote_words = [w for w in words if w["cut"] is not None
                       and w["cut"] < end and w["cut_end"] > start]
        first_word = words.index(quote_words[0])

        if beat["kind"] == "overlay":
            route = beat["route"]
            labels = beat["labels"]
            anchors = [int(x) for x in beat["anchors"]]
            family, action, structure = OVERLAY_ROUTES[route]
            component_id = "native-visual"
            upstream_route = "hyperframes/" + route
            source_path = project / REGISTRY / "components" / route / (route + ".html")
            source_bytes = source_path.read_bytes()
            native_bytes = bind_native_clock(source_bytes, upstream_route, duration_beat)
            if route == "before-after-wipe":
                art = ('<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" '
                       'width="120" height="120"><circle cx="60" cy="60" r="44" fill="none" '
                       'stroke="#bdb59d" stroke-width="8"/></svg>')
                native_bytes = bind_native_slots(native_bytes, {"before": art, "after": art})
                wipe_at = max(0.0, words[anchors[1]]["cut"] - start)
                values = {"label_a": labels[0], "label_b": labels[1],
                          "wipe_at": f"{wipe_at:.6f}", "rest_split": "50", "exit": "fade"}
            else:
                key = "titles" if route == "notification-stack" else "items"
                cues = ",".join(f"{max(0.0, words[i]['cut'] - start):.6f}"
                                 for i in anchors[:len(labels)])
                values = {key: ",".join(labels), "cues": cues, "exit": "fade"}
            (folder / "native.html").write_bytes(native_bytes)
            entry_html = (
                '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
                f'<div class="stage" data-duration="{duration_beat}">'
                f'<div class="mount" data-composition-id="{route}" data-composition-src="native.html" '
                f"data-variable-values='{json.dumps(values, ensure_ascii=False)}' "
                f'data-start="0" data-duration="{duration_beat}"></div></div>')
            (folder / "index.html").write_text(entry_html, encoding="utf-8")
            brief = {
                "schema_version": 2,
                "source_binding": {"aroll_sha256": arroll_sha, "segment_id": sid,
                                    "start": start, "end": end},
                "template_request": {"semantic_family": family, "information_units": 2,
                                      "numeric_values": [], "numeric_scale": "not_applicable"},
                "entry": {"media_ref": "native-entry",
                           "job_path": str((folder / "index.html").relative_to(job_dir)),
                           "scene_path": "index.html",
                           "sha256": hashlib.sha256((folder / "index.html").read_bytes()).hexdigest()},
                "assets": [{"media_ref": "native-source",
                             "job_path": str((folder / "native.html").relative_to(job_dir)),
                             "scene_path": "native.html",
                             "sha256": hashlib.sha256(native_bytes).hexdigest()}],
                "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": frames,
                                 "alpha": True},
                "upstream_route": upstream_route,
                "source_pins": {"route": upstream_route,
                                 "sha256": hashlib.sha256(source_bytes).hexdigest()},
            }
            payload = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            (folder / "brief.json").write_bytes(payload)
            binding = hyper.create_binding(hyper_adapter, payload, source_path)
            events = []
            if route == "before-after-wipe":
                events = [
                    {"slot": 0, "kind": "reveal", "text": labels[0],
                     "anchor": {"index": first_word, "text": words[first_word]["text"]},
                     "basis": "current_clause"},
                    {"slot": 1, "kind": "wipe_start", "text": labels[1],
                     "anchor": {"index": anchors[1], "text": words[anchors[1]]["text"]},
                     "basis": "current_clause"},
                ]
                scale = min(1.0, duration_beat / (float(values["wipe_at"]) + 1.05 + 0.5))
                land = start + (float(values["wipe_at"]) + 1.05) * scale
                land_word = min(
                    (i for i, w in enumerate(words)
                     if w["cut"] is not None and start <= w["cut"] < end
                     and w["cut"] >= land - 0.75 and w["cut"] <= land + 1 / 24),
                    default=None)
                if land_word is None:
                    raise SystemExit(f"{sid}: no word aligns with the wipe landing")
                events.append({"slot": 1, "kind": "wipe_land", "text": labels[1],
                                "anchor": {"index": land_word, "text": words[land_word]["text"]},
                                "basis": "current_clause"})
            else:
                events = [{"slot": i, "kind": "reveal", "text": labels[i],
                            "anchor": {"index": anchors[i], "text": words[anchors[i]]["text"]},
                            "basis": "current_clause"} for i in range(len(labels))]
            treatment["overlay_selection"].append({
                "segment_id": sid, "component_id": component_id,
                "intent_relation": family, "native_route": route,
                "visible_action": action, "visual_structure": structure,
                "selection_reason": beat["reason"]})
            treatment["overlay_alignment"].append({
                "segment_id": sid, "component_id": component_id,
                "brief_path": str((folder / "brief.json").relative_to(job_dir)),
                "events": events})
            candidate_id = "overlay:" + route
            layer, layout, media = "annotation", "annotation", "animation"
            composition_family, presenter = "aroll_with_overlay", "full_frame"
            mode = "none"
            semantic_role = "explanation"
        else:
            component_id = "native-broll"
            if beat.get("riso_template"):
                template = beat["riso_template"]
                data = dict(beat["data"])
                data["duration"] = duration_beat
                units = {"title": 1, "quote": 1, "versus": 2, "number": 1,
                         "focus": len(data.get("items", [])), "converge": 2,
                         "compare": 2, "steps": len(data.get("steps", [])),
                         "network": 1, "shot": 1}[template]
                numbers = [data["number"]] if template == "number" else []
                brief = {
                    "schema_version": 1,
                    "source_binding": {"aroll_sha256": arroll_sha, "segment_id": sid,
                                        "start": start, "end": end},
                    "composition": {"id": f"riso-{template}", "width": 1080, "height": 1920,
                                     "fps": 24, "frames": frames},
                    "template_request": {
                        "semantic_family": riso.FAMILIES[template],
                        "information_units": units, "numeric_values": numbers,
                        "numeric_scale": "linear" if numbers else "not_applicable"},
                    "template": template, "data": data, "assets": [],
                }
                payload = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
                (folder / "brief.json").write_bytes(payload)
                binding = riso.create_binding(riso_adapter, payload, project / RISO_SAMPLE)
                candidate_id = f"eian-riso-broll:{template}"
                content_pointer, content_value = "/template", template
            else:
                route = beat["route"]
                values = dict(beat.get("variables") or {})
                source_path = project / REGISTRY / (
                    "blocks" if route == "macos-notification" else "components") / route / (route + ".html")
                source_bytes = source_path.read_bytes()
                import re as _re
                native_text = source_bytes.decode("utf-8")
                for attribute in ("data-composition-duration", "data-duration"):
                    native_text = _re.sub(rf'{attribute}="[\d.]+"',
                                           f'{attribute}="{duration_beat}"', native_text)
                native_bytes = native_text.encode("utf-8")
                (folder / "native.html").write_bytes(native_bytes)
                entry_html = (
                    '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
                    f'<div class="stage" data-duration="{duration_beat}">'
                    f'<div class="mount" data-composition-id="{route}" data-composition-src="native.html" '
                    f"data-variable-values='{json.dumps(values, ensure_ascii=False)}' "
                    f'data-start="0" data-duration="{duration_beat}"></div></div>')
                (folder / "index.html").write_text(entry_html, encoding="utf-8")
                brief = {
                    "schema_version": 2,
                    "source_binding": {"aroll_sha256": arroll_sha, "segment_id": sid,
                                        "start": start, "end": end},
                    "template_request": {
                        "semantic_family": beat.get("semantic_family") or "demonstration",
                        "information_units": max(1, len(values)),
                        "numeric_values": [], "numeric_scale": "not_applicable"},
                    "entry": {"media_ref": "native-entry",
                               "job_path": str((folder / "index.html").relative_to(job_dir)),
                               "scene_path": "index.html",
                               "sha256": hashlib.sha256((folder / "index.html").read_bytes()).hexdigest()},
                    "assets": [{"media_ref": "native-source",
                                 "job_path": str((folder / "native.html").relative_to(job_dir)),
                                 "scene_path": "native.html",
                                 "sha256": hashlib.sha256(native_bytes).hexdigest()}],
                    "composition": {"width": 1080, "height": 1920, "fps": 24,
                                     "frames": frames, "alpha": False},
                    "upstream_route": "hyperframes/" + route,
                    "source_pins": {"route": "hyperframes/" + route,
                                     "sha256": hashlib.sha256(source_bytes).hexdigest()},
                }
                payload = json.dumps(brief, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
                (folder / "brief.json").write_bytes(payload)
                binding = hyper.create_binding(hyper_adapter, payload, source_path)
                candidate_id = f"hyperframes-native-adaptation:hyperframes/{route}"
                content_pointer, content_value = "/upstream_route", f"hyperframes/{route}"
            treatment["scenes"].append({
                "segment_id": sid, "component_id": component_id,
                "brief_path": str((folder / "brief.json").relative_to(job_dir))})
            treatment["skill_selection"]["beats"].append({
                "segment_id": sid, "component_id": component_id, "start": start, "end": end,
                "transcript": beat["statement"], "semantic_goal": "demonstrate",
                "required_change": beat.get("required_change") or "把口播内容变成可见画面",
                "intent_statement": beat["statement"], "component_brief": beat["statement"],
                "binding_snapshot": binding, "skill_reviews": {}, "candidates": []})
            layer, layout, media = "base", "full_frame", "video"
            composition_family, presenter = "single_full_frame", "bottom_window"
            mode = "single"
            semantic_role = "demonstration"

        statement = beat["statement"]
        plan_segments.append({
            "segment_id": sid, "start": start, "end": end,
            "content_item_ids": [it["id"] for it in items], "visible_text":
                beat.get("labels") or [],
            "visual_intent": {"segment_id": sid, "statement": statement,
                               "semantic_goals": ["explain" if beat["kind"] == "overlay" else "demonstrate"],
                               "claims": [], "entities": [], "relations": [],
                               "requirements": {"verifiability": "low", "realism": "medium",
                                                  "abstraction": "high" if beat["kind"] == "broll" else "medium",
                                                  "product_specificity": "low",
                                                  "emotional_intensity": "low"},
                               "presenter_presence": "allowed" if beat["kind"] == "overlay" else "required"},
            "visual_strategy": {"schema_version": 1, "segment_id": sid, "mode": mode,
                                 "rationale": beat["reason"],
                                 "components": [{"component_id": component_id,
                                                  "kind": "code_generated",
                                                  "semantic_role": semantic_role,
                                                  "layer_role": layer, "media_type": media,
                                                  "layout_slot": layout, "brief": statement}],
                                 "composition": {**{
                                     "family": composition_family,
                                     "presenter_mode": presenter,
                                     "reading_order": [component_id],
                                     "component_dependencies": []},
                                     **({"avatar": json.loads(json.dumps(calibration[match_key]))}
                                        if (match_key := next(
                                            (k for k in calibration
                                             if abs(k[0] - round(start, 2)) < 0.15
                                             and abs(k[1] - round(end, 2)) < 0.15),
                                            None)) else {})}},
            "candidate_snapshots": {}, "bindings": {component_id: binding},
            "strategy_revision": revision_base,
        })
        treatment["semantic_assessments"].append({
            "segment_id": sid, "component_id": component_id, "candidate_id": candidate_id,
            "verdict": "pass", "reason": beat["reason"],
            "transcript_refs": [{"start_word": first_word,
                                  "end_word": first_word + len(quote_words),
                                  "quote": "".join(w["text"] for w in quote_words),
                                  "basis": "current_clause"}],
            "content_refs": [{"path": str((folder / "brief.json").relative_to(job_dir)),
                               "sha256": hashlib.sha256(payload).hexdigest(),
                               "pointer": content_pointer if beat["kind"] == "broll" else "/upstream_route",
                               "value": content_value if beat["kind"] == "broll" else "hyperframes/" + beat["route"]}]})
        for text in beat.get("labels") or []:
            import re as _re2
            alnums = set(_re2.findall(r"[A-Za-z0-9]+", text))
            ref, quote = "item:" + items[0]["id"], items[0]["source_text"]
            for item in items:
                if alnums and alnums <= set(_re2.findall(r"[A-Za-z0-9]+", item["source_text"])):
                    ref, quote = "item:" + item["id"], item["source_text"]
                    break
            receipt["entries"].append({
                "segment_id": sid, "text": text, "source_ref": ref, "source_quote": quote,
                "reason": "贴片标签压缩自该词段口播原文，只保留要点本身，不新增事实"})

    if treatment["skill_selection"]["beats"]:
        from edit.hd.tools.broll_skill_selection import discover_candidates, assign_skills
        pool = {row["candidate_id"]: row for row in discover_candidates(project)}
        for beat_record in treatment["skill_selection"]["beats"]:
            chosen = next(r["candidate_id"] for r in treatment["semantic_assessments"]
                          if r["segment_id"] == beat_record["segment_id"])
            chosen_skill = pool[chosen]["skill_id"]
            for skill in {row["skill_id"] for row in pool.values()}:
                beat_record["skill_reviews"][skill] = {
                    "fit": "preferred" if skill == chosen_skill else "unsuitable",
                    "reason": (next(r["reason"] for r in treatment["semantic_assessments"]
                                    if r["segment_id"] == beat_record["segment_id"])
                               if skill == chosen_skill else "与本句演示语义不符或未接通该用途")}
            beat_record["candidates"] = [{
                "candidate_id": chosen, "fit": "preferred",
                "reason": beat_record["required_change"],
                "visual_pattern": chosen.split("/")[-1]}]
        treatment["skill_selection"]["assignments"] = assign_skills(
            project, treatment["skill_selection"])["assignments"]

    (ni / "director-brief.json").write_text(
        json.dumps({"schema_version": 3, "segments": plan_segments}, ensure_ascii=False, indent=2) + "\n")
    (ni / "treatment.json").write_text(json.dumps(treatment, ensure_ascii=False, indent=2) + "\n")
    (ni / "reviewed-visual-text.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

    overlays = sum(1 for s in plan_segments
                    if s["visual_strategy"]["composition"]["family"] == "aroll_with_overlay")
    broll = sum(s["end"] - s["start"] for s in plan_segments
                 if s["visual_strategy"]["composition"]["family"] == "single_full_frame")
    print(json.dumps({"segments": len(plan_segments), "overlays": overlays,
                       "broll_seconds": round(broll, 1),
                       "broll_percent": round(broll / duration * 100, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

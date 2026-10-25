"""Check native overlay text and effective timing before visual publication."""
from __future__ import annotations

import math
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from . import contract_artifacts as artifacts
from . import pinboard_alignment
from . import huashu_stat_alignment


class _Mounts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.mounts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "data-composition-src" in values:
            self.mounts.append(values)


class _ClockTags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.lines = source.splitlines(keepends=True)

    def handle_starttag(self, tag, attrs):
        line, column = self.getpos()
        offset = sum(len(s) for s in self.lines[:line - 1]) + column
        self.tags.append((tag, dict(attrs), offset, self.get_starttag_text()))


def _clock_tags(source, route):
    name = route.removeprefix("hyperframes/")
    if name not in {"grid-card-assemble", "notification-stack", "toggle-flip", "before-after-wipe"}:
        raise ValueError("unsupported native clock route")
    parser = _ClockTags(source)
    parser.feed(source)
    roots = [t for t in parser.tags if t[1].get("id") == "root"]
    clips = [t for t in parser.tags if t[1].get("id") == name + "-clip"]
    metadata = [t for t in parser.tags if t[0] == "html" and "data-composition-duration" in t[1]]
    if (len(roots) != 1 or len(clips) != 1 or len(metadata) > 1
            or roots[0][1].get("data-composition-id") != name
            or _number(clips[0][1].get("data-start", 0)) != 0):
        raise ValueError("native root and full-window clip must be unique and start at zero")
    return roots[0], clips[0], metadata


def bind_native_clock(source: bytes, route: str, duration: float) -> bytes:
    """Bind clock parameters around unchanged synchronous native initialization."""
    duration = _number(duration)
    if duration <= 0:
        raise ValueError("native clock duration must be positive")
    text = source.decode("utf-8")
    root, clip, metadata = _clock_tags(text, route)
    original = _number(root[1]["data-duration"])
    replacements = []
    for tag, attribute in [(root, "data-duration"), (clip, "data-duration"),
                           *[(t, "data-composition-duration") for t in metadata]]:
        if _number(tag[1][attribute]) != original:
            raise ValueError("original native clocks differ")
        expression = re.compile(r"(?<![\w-])" + attribute + r"\s*=\s*([\"'])([^\"']*)\1")
        matches = list(expression.finditer(tag[3]))
        if len(matches) != 1:
            raise ValueError("native clock attribute is missing or ambiguous")
        match = matches[0]
        replacements.append((tag[2] + match.start(2), tag[2] + match.end(2)))
    for start, end in sorted(replacements, reverse=True):
        text = text[:start] + str(duration) + text[end:]
    # HyperFrames strips the inner root's timing attributes during assembly.
    # Restore D only while the unchanged primitive builds its own timeline.
    scripts = list(re.finditer(r"<script\b[^>]*>.*?</script>", text, re.S))
    if len(scripts) != 2:
        raise ValueError("native initialization scripts changed")
    name = json.dumps(route.removeprefix("hyperframes/"))
    value = json.dumps(str(duration))
    # Custom elements inside the template upgrade during the assembly clone
    # and may already have written the mount clock onto #root; a pre-set
    # correct value is accepted, a wrong one is still a hard failure.
    before = ('<script data-hd-native-clock="bind">(function(){'
              'var r=document.getElementById("root");'
              'if(!r)throw new Error("native clock setup target differs");'
              'var v=r.getAttribute("data-duration");'
              f'if(v!==null&&v!=={value})throw new Error("native clock setup target differs");'
              f'if(v===null)r.setAttribute("data-duration",{value});'
              '})();</script>')
    after = ('<script data-hd-native-clock="cleanup">(function(){'
             'var r=document.getElementById("root");'
             f'if(!r||r.getAttribute("data-duration")!=={value}||!window.__timelines[{name}])'
             'throw new Error("native clock initialization failed");'
             'r.removeAttribute("data-duration");'
             '})();</script>')
    text = text[:scripts[-1].end()] + after + text[scripts[-1].end():]
    text = text[:scripts[0].start()] + before + text[scripts[0].start():]
    return text.encode("utf-8")


class _ContentSlots(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.stack = []
        self.ranges = {}
        self.lines = source.splitlines(keepends=True)

    def _source_offset(self):
        line, column = self.getpos()
        return sum(len(s) for s in self.lines[:line - 1]) + column

    def handle_starttag(self, tag, attrs):
        if tag in {"meta", "link", "img", "br", "hr", "input"}:
            return
        slot = dict(attrs).get("data-slot")
        if slot and (slot not in {"before", "after"} or slot in self.ranges):
            raise ValueError("comparison content slots differ from the native source")
        self.stack.append((tag, slot, self._source_offset() + len(self.get_starttag_text())))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError("comparison content has unbalanced tags")
        _, slot, start = self.stack.pop()
        if slot:
            self.ranges[slot] = (start, self._source_offset())

    def handle_startendtag(self, tag, attrs):
        if dict(attrs).get("data-slot"):
            raise ValueError("native content slots must have separate opening and closing tags")
        if tag in {"meta", "link", "img", "br", "hr", "input"}:
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


class _StaticContent(HTMLParser):
    """The public comparison slots contain static art, never another timeline."""
    def handle_starttag(self, tag, attrs):
        if tag not in {"div", "span", "svg", "path", "rect", "line", "circle", "ellipse", "polyline", "polygon", "g"}:
            raise ValueError("comparison slots accept only static markup")
        allowed = {"class", "aria-hidden", "viewbox", "xmlns", "width", "height", "x", "y", "x1", "x2", "y1", "y2",
                   "cx", "cy", "rx", "ry", "r", "d", "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"}
        if any(key not in allowed or value is None or re.search(r"url\s*\(|https?://|javascript:", value, re.I)
               and not (key == "xmlns" and value == "http://www.w3.org/2000/svg") for key, value in attrs):
            raise ValueError("comparison slots cannot contain scripts, styles or external assets")

    def handle_data(self, data):
        if data.strip():
            raise ValueError("comparison text must use the checked native label_a / label_b slots")


def bind_native_slots(source: bytes, contents: dict[str, str]) -> bytes:
    """Fill only the two public static content slots; retain all native code."""
    if not isinstance(contents, dict) or set(contents) != {"before", "after"}:
        raise ValueError("both native comparison slots are required")
    text = source.decode("utf-8")
    parser = _ContentSlots(text)
    parser.feed(text)
    if set(parser.ranges) != set(contents):
        raise ValueError("native comparison content slots are missing")
    for slot, content in contents.items():
        if not isinstance(content, str) or not content.strip():
            raise ValueError("native comparison content is empty")
        static = _StaticContent()
        static.feed(content)
        balanced = _ContentSlots(content)
        balanced.feed(content)
        if balanced.stack:
            raise ValueError("comparison content has unbalanced tags")
    for slot, (start, end) in sorted(parser.ranges.items(), key=lambda item: item[1][0], reverse=True):
        text = text[:start] + contents[slot] + text[end:]
    return text.encode("utf-8")


def _native_clock(source, actual, route, duration):
    expected = bind_native_clock(source, route, duration)
    if route == "hyperframes/before-after-wipe":
        text = actual.decode("utf-8")
        slots = _ContentSlots(text)
        slots.feed(text)
        if set(slots.ranges) != {"before", "after"}:
            raise ValueError("native comparison content slots are missing")
        expected = bind_native_slots(expected, {key: text[start:end] for key, (start, end) in slots.ranges.items()})
    if actual != expected:
        raise ValueError("native asset differs beyond the duration parameters and initialization glue")
    root, clip, metadata = _clock_tags(actual.decode("utf-8"), route)
    clocks = [_number(root[1]["data-duration"]), _number(clip[1]["data-duration"]),
              *[_number(t[1]["data-composition-duration"]) for t in metadata]]
    if any(abs(clock - duration) > 1e-6 for clock in clocks):
        raise ValueError("native and mount clocks differ")
    return clocks[0]


def _clock_budgets(entries):
    # Public preview startup (30+15+10s), then 200ms per effective frame.
    # Individual checks remain bounded; a larger table gets a larger total.
    budgets = [min(300, 55 + (math.ceil(_number(e['duration']) * 24) + 3) * .2)
               for e in entries]
    return budgets, 40 + sum(budget + 5 for budget in budgets) + 15


def _stop_clock_check(process, identity, directory):
    from .relation_browser_watchdog import _terminate_registered
    browser_record = directory / 'browser.json'
    if process.poll() is None:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    groups = {process.pid: identity}
    # Stop the registrar first, then read its final browser registry. The exec
    # shim refuses to start Chrome if that parent has already gone away.
    _terminate_registered(groups)
    process.wait(timeout=5)
    if browser_record.exists():
        browser = json.loads(browser_record.read_text())
        if (set(browser) != {'pid', 'identity'} or type(browser['pid']) is not int
                or browser['pid'] <= 1 or not isinstance(browser['identity'], str)):
            raise ValueError('native clock browser ownership record is invalid')
        groups = {browser['pid']: browser['identity']}
        _terminate_registered(groups)
    # Chrome has its own detached process group; stopping Node alone is not
    # sufficient. The shared helper checks start identities before signaling.
    process.communicate(timeout=5)


def _assembled_clocks(entries):
    """Execute the actual installed compiler and native timelines, without export."""
    project = Path(__file__).resolve().parents[3]
    checker = project / "skill-development/hd-talking-head/scripts/check_native_overlay_clock.mjs"
    from .relation_browser_watchdog import _process_start_identity
    budgets, timeout = _clock_budgets(entries)
    with tempfile.TemporaryDirectory(prefix='hf-clock-') as temporary:
        directory = Path(temporary)
        request = {'project_root': str(project), 'work_directory': str(directory),
                   'python_executable': sys.executable,
                   'entries': [{**entry, 'timeout_ms': round(budget * 1000)}
                               for entry, budget in zip(entries, budgets)]}
        process = subprocess.Popen([shutil.which('node'), str(checker)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
            env={**os.environ, 'TMPDIR': str(directory)})
        identity = _process_start_identity(process.pid)
        try:
            if identity is None:
                raise ValueError('native clock process identity is unavailable')
            try:
                stdout, stderr = process.communicate(input=json.dumps(request), timeout=timeout)
            except subprocess.TimeoutExpired as error:
                progress = directory / 'progress.json'
                try:
                    detail = progress.read_text()[:2000]
                except OSError:
                    detail = 'progress unavailable'
                raise ValueError('assembled native clock check timed out: ' + detail) from error
            if process.returncode:
                raise ValueError('assembled native clock check failed: ' + stderr[-5000:])
            observed = json.loads(stdout)
        finally:
            if identity is not None:
                _stop_clock_check(process, identity, directory)
            else:
                process.kill()
                process.communicate(timeout=5)
    if observed.get("ok") is not True or len(observed.get("entries", [])) != len(entries):
        raise ValueError("assembled native clock evidence is incomplete")
    return observed["entries"]


def _path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("overlay input must have a Job-relative path")
    path = root / relative
    if path.resolve() != path.absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("overlay input is not a regular file in this Job")
    return path


def _approved(job, stage_id, relative):
    stage = job.stages[stage_id]
    records = [r for r in stage["artifacts"] if r["path"] == relative]
    if stage["status"] != "approved" or len(records) != 1:
        raise ValueError(f"{relative} must belong to an approved stage")
    path = _path(job.job_dir, relative)
    if artifacts.sha256_file(path) != records[0]["sha256"] or path.stat().st_size != records[0]["bytes"]:
        raise ValueError(f"approved {relative} changed")
    return path, records[0]["sha256"]


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("overlay timing must be finite")
    return result


def _split(value):
    if not isinstance(value, str):
        raise ValueError("native text and cue slots must be strings")
    return [v.strip() for v in value.split(",")]


def _native_events(route, mount, fps, native_duration):
    values = json.loads(mount["data-variable-values"])
    start, duration = _number(mount.get("data-start", 0)), _number(native_duration)
    if start < 0 or duration <= 0:
        raise ValueError("invalid native mount window")
    name = route.removeprefix("hyperframes/")
    if name == "before-after-wipe":
        labels = [values.get("label_a"), values.get("label_b")]
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("comparison overlay requires both public labels")
        split = _number(values.get("rest_split", 50))
        raw = _number(values.get("wipe_at", 0.25))
        if not 0 < split < 100 or not 0 <= raw <= 8:
            raise ValueError("comparison split or wipe time is outside the native public range")
        out = 0 if values.get("exit", "none") == "none" else 0.5
        scale = min(1, duration / (raw + 1.05 + out))
        wipe = raw * scale
        if abs(wipe - raw) > 1 / fps + 1e-6:
            raise ValueError("native comparison wipe is clamped before its spoken anchor")
        return [(0, "reveal", labels[0], start),
                (1, "wipe_start", labels[1], start + wipe),
                (1, "wipe_land", labels[1], start + (raw + 1.05) * scale)], start + duration
    if name == "toggle-flip":
        label = values.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("toggle overlay needs its public label")
        events = [(0, "reveal", label, start),
                  (0, "toggle_flip", label, start + 0.5 * min(1, duration / 1.4))]
        return events, start + duration
    if name == "notification-stack":
        labels = [s for s in _split(values.get("titles", "")) if s][:5]
        bodies = _split(values.get("bodies", ""))
        if any(bodies):
            raise ValueError("notification body text needs a separately supported timing contract")
    elif name == "grid-card-assemble":
        labels = [s for s in _split(values.get("items", "")) if s][:12]
        if any(":" in s or "：" in s for s in labels):
            raise ValueError("grid body text needs a separately supported timing contract")
    else:
        raise ValueError(f"unsupported native overlay route: {route}")
    if not labels:
        raise ValueError("native default labels cannot substitute for current speech")
    cues = _split(values.get("cues", ""))
    out = 0 if values.get("exit", "none") == "none" else min(0.45, duration * 0.25)
    avail = duration - out
    tile = min(0.65, max(0.2, avail - 0.15))
    latest = max(0, avail - (1.05 if name == "notification-stack" else tile))
    first = min(0.15, latest)
    last = min(latest, max(0.6 * duration - tile, 0.15 + 0.1 * (len(labels) - 1)))
    gap = max(0, last - first) / max(1, len(labels) - 1)
    starts = []
    events = []
    for i, label in enumerate(labels):
        raw = (_number(cues[i]) if i < len(cues) and cues[i] else
               0.2 + 0.55 * i if name == "notification-stack" else first + gap * i)
        effective = max(raw, starts[-1] + 0.05) if starts and name == "notification-stack" else raw
        effective = max(0, min(effective, latest))
        if starts and name == "notification-stack":
            effective = max(effective, starts[-1])
        if abs(raw - effective) > 1 / fps + 1e-6:
            raise ValueError(f"native cue is clamped before its spoken anchor: slot {i}")
        starts.append(effective)
        events.append((i, "reveal", label, start + effective))
    return events, start + duration


def validate_treatment(job, draft, treatment_path) -> list[dict]:
    """Read actual HTML inputs, not duplicated intended trigger times."""
    targets = []
    for segment in draft["segments"]:
        if segment["visual_strategy"]["composition"]["family"] != "aroll_with_overlay":
            continue
        for cid, binding in segment["bindings"].items():
            if binding.get("dependency_id") in {"hyperframes-native-adaptation", pinboard_alignment.DEPENDENCY_ID, huashu_stat_alignment.DEPENDENCY_ID}:
                targets.append((segment, cid, binding))
    if not targets:
        return []
    if treatment_path is None:
        raise ValueError("native overlay treatment is required")
    treatment_path = Path(treatment_path)
    relative = str(treatment_path.relative_to(job.job_dir)) if treatment_path.is_absolute() else str(treatment_path)
    treatment = artifacts.read_json_artifact(_path(job.job_dir, relative))
    records = treatment.get("overlay_alignment")
    if not isinstance(records, list):
        raise ValueError("overlay_alignment records are required")
    keys = [(r["segment_id"], r["component_id"]) for r in records]
    expected = {(s["segment_id"], cid) for s, cid, _ in targets}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("overlay records are missing, duplicated, or unrelated")
    transcript, _ = _approved(job, "speech_cleanup", "05-speech-cleanup/word-transcript.json")
    timeline, _ = _approved(job, "edit_structure", "06-edit-structure/timeline-map.json")
    _, arroll_sha = _approved(job, "edit_structure", "06-edit-structure/edited-aroll.mp4")
    words = artifacts.read_json_artifact(transcript)["words"]
    cuts = artifacts.read_json_artifact(timeline)["segments"]
    fps = 24
    report = []
    assembled_inputs = []
    for segment, cid, binding in targets:
        sid = segment["segment_id"]
        record = records[keys.index((sid, cid))]
        brief_path = _path(job.job_dir, record["brief_path"])
        if artifacts.sha256_file(brief_path) != binding["brief_sha256"]:
            raise ValueError(f"overlay brief differs from binding: {sid}")
        brief = artifacts.read_json_artifact(brief_path)
        expected_source = {"aroll_sha256": arroll_sha, "segment_id": sid,
                           "start": segment["start"], "end": segment["end"]}
        if brief.get("source_binding") != expected_source or brief.get("composition", {}).get("alpha") is not True:
            raise ValueError(f"overlay source or alpha contract changed: {sid}")
        if brief["composition"]["fps"] != fps:
            raise ValueError("native overlay requires the approved 24 fps clock")
        if binding.get("dependency_id") == pinboard_alignment.DEPENDENCY_ID:
            checked = pinboard_alignment.validate_brief(
                brief,
                segment={**segment, "aroll_sha256": arroll_sha},
                words=words,
                cuts=cuts,
                events=record.get("events"),
            )
            report.append({"segment_id": sid, "component_id": cid, "route": pinboard_alignment.ROUTE,
                           "brief_path": record["brief_path"], "brief_sha256": binding["brief_sha256"],
                           "events": checked})
            continue
        if binding.get("dependency_id") == huashu_stat_alignment.DEPENDENCY_ID:
            checked = huashu_stat_alignment.validate_brief(
                brief, segment={**segment, "aroll_sha256": arroll_sha},
                words=words, cuts=cuts, events=record.get("events"),
            )
            report.append({"segment_id": sid, "component_id": cid, "route": huashu_stat_alignment.ROUTE,
                           "brief_path": record["brief_path"], "brief_sha256": binding["brief_sha256"],
                           "events": checked, "native_exit": checked[0]["native_exit"]})
            continue
        entry = _path(job.job_dir, brief["entry"]["job_path"])
        entry_sha = artifacts.sha256_file(entry)
        if entry_sha != brief["entry"]["sha256"]:
            raise ValueError(f"overlay HTML changed: {sid}")
        parser = _Mounts()
        parser.feed(entry.read_text(encoding="utf-8"))
        if len(parser.mounts) != 1:
            raise ValueError("native overlay requires exactly one mounted primitive")
        mount = parser.mounts[0]
        route = brief["upstream_route"]
        assets = [r for r in brief["assets"] if r["scene_path"] == mount["data-composition-src"]]
        name = route.removeprefix("hyperframes/")
        if (mount.get("data-composition-id") != name
                or len(assets) != 1
                or artifacts.sha256_file(_path(job.job_dir, assets[0]["job_path"])) != assets[0]["sha256"]):
            raise ValueError(f"mounted native source differs from the declared route: {sid}")
        source_path = (Path(__file__).resolve().parents[3] / "参考项目/B-roll开源方案/hyperframes"
                       / "registry/components" / name / (name + ".html"))
        if artifacts.sha256_file(source_path) != brief["source_pins"]["sha256"]:
            raise ValueError(f"original native source changed: {sid}")
        native_duration = _native_clock(source_path.read_bytes(),
            _path(job.job_dir, assets[0]["job_path"]).read_bytes(), route, _number(mount["data-duration"]))
        actual, exit_time = _native_events(route, mount, fps, native_duration)
        assembled_inputs.append({"entry_directory": str(entry.parent), "route": route,
            "duration": native_duration, "start": _number(mount.get("data-start", 0)),
            "events": [{"slot": slot, "kind": kind, "text": text, "time": time}
                       for slot, kind, text, time in actual]})
        duration = segment["end"] - segment["start"]
        if exit_time > duration + 1e-6:
            raise ValueError(f"overlay exits after the next shot: {sid}")
        if list(dict.fromkeys(e[2] for e in actual)) != segment["visible_text"]:
            raise ValueError(f"reviewed labels differ from actual native labels: {sid}")
        events = record["events"]
        event_keys = [(e["slot"], e["kind"]) for e in events]
        if len(event_keys) != len(set(event_keys)) or set(event_keys) != {(e[0], e[1]) for e in actual}:
            raise ValueError(f"each native label and action needs exactly one anchor: {sid}")
        checked = []
        for slot, kind, text, local_time in actual:
            event = events[event_keys.index((slot, kind))]
            if event["text"] != text or text not in segment["visible_text"]:
                raise ValueError(f"native visible text differs from reviewed text: {sid}")
            anchor = event["anchor"]
            index = anchor["index"]
            if type(index) is not int or not 0 <= index < len(words) or words[index]["text"] != anchor["text"]:
                raise ValueError(f"overlay source word differs from the approved transcript: {sid}")
            word = words[index]
            if word["end"] <= word["start"]:
                raise ValueError("zero-duration ASR noise cannot anchor a label")
            positions = [word["start"] + part["timeline_start"] - part["source_start"] for part in cuts
                         if part["source_start"] <= word["start"] < part["source_end"]]
            if len(positions) != 1:
                raise ValueError("overlay anchor is not in the edited speech")
            anchor_time = positions[0]
            effective_time = segment["start"] + local_time
            if not segment["start"] <= effective_time < segment["end"]:
                raise ValueError(f"overlay event is outside this shot: {sid}")
            basis = event["basis"]
            if basis == "current_clause":
                if not segment["start"] <= anchor_time < segment["end"]:
                    raise ValueError(f"current-clause anchor is outside this shot: {sid}")
                if effective_time < anchor_time - 1 / fps or effective_time > anchor_time + 0.8:
                    raise ValueError(f"overlay reveal is not aligned with the spoken clause: {sid}")
            elif basis == "recap":
                if effective_time < anchor_time:
                    raise ValueError(f"recap refers to speech that has not happened: {sid}")
            else:
                raise ValueError("overlay anchor basis must be current_clause or recap")
            checked.append({"slot": slot, "kind": kind, "text": text, "basis": basis,
                            "anchor": anchor, "anchor_time": anchor_time, "effective_time": effective_time})
        report.append({"segment_id": sid, "component_id": cid, "route": brief["upstream_route"],
                       "brief_path": record["brief_path"], "brief_sha256": binding["brief_sha256"],
                       "entry_sha256": entry_sha, "native_duration": native_duration,
                       "original_source_sha256": brief["source_pins"]["sha256"],
                       "bound_asset_sha256": assets[0]["sha256"],
                       "events": checked, "native_exit": segment["start"] + exit_time})
    if assembled_inputs:
        clock_items = [item for item in report if item["route"].startswith("hyperframes/")]
        for item, evidence in zip(clock_items, _assembled_clocks(assembled_inputs), strict=True):
            item["assembled_clock"] = evidence
    return report

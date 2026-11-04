"""Check native overlay text and effective timing before visual publication."""
from __future__ import annotations
from scripts.package_paths import PACKAGE_ROOT

import math
import hashlib
import importlib.util
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

GRID_STABLE_HOLD_FRAMES = 12  # Parent readability contract, not upstream animation duration.


class GridClockConflict(ValueError):
    """A valid Grid input cannot finish landing and retain its stable reading window."""


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
    def __init__(self, label=None):
        super().__init__()
        self.label = label
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"div", "span", "svg", "path", "rect", "line", "circle", "ellipse", "polyline", "polygon", "g", "text"}:
            raise ValueError("comparison slots accept only static markup")
        allowed = {"class", "aria-hidden", "viewbox", "xmlns", "width", "height", "x", "y", "x1", "x2", "y1", "y2",
                   "cx", "cy", "rx", "ry", "r", "d", "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
                   "font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline"}
        if any(key not in allowed or value is None or re.search(r"url\s*\(|https?://|javascript:", value, re.I)
               and not (key == "xmlns" and value == "http://www.w3.org/2000/svg") for key, value in attrs):
            raise ValueError("comparison slots cannot contain scripts, styles or external assets")

    def handle_data(self, data):
        if data.strip():
            if not isinstance(self.label, str) or not self.label.strip():
                raise ValueError("comparison text needs its checked before/after label")
            self.text.append(data.strip())

    def check_text(self):
        if self.text and "".join(self.text) != self.label:
            raise ValueError("comparison slot text differs from its checked label")


def bind_native_slots(source: bytes, contents: dict[str, str], *, labels=None) -> bytes:
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
        static = _StaticContent((labels or {}).get(slot))
        static.feed(content)
        static.check_text()
        balanced = _ContentSlots(content)
        balanced.feed(content)
        if balanced.stack:
            raise ValueError("comparison content has unbalanced tags")
    for slot, (start, end) in sorted(parser.ranges.items(), key=lambda item: item[1][0], reverse=True):
        text = text[:start] + contents[slot] + text[end:]
    return text.encode("utf-8")


def _native_clock(source, actual, route, duration, *, labels=None):
    expected = bind_native_clock(source, route, duration)
    if route == "hyperframes/before-after-wipe":
        text = actual.decode("utf-8")
        slots = _ContentSlots(text)
        slots.feed(text)
        if set(slots.ranges) != {"before", "after"}:
            raise ValueError("native comparison content slots are missing")
        expected = bind_native_slots(expected, {key: text[start:end] for key, (start, end) in slots.ranges.items()}, labels=labels)
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
    project = PACKAGE_ROOT
    checker = project / "scripts/check_native_overlay_clock.mjs"
    from .relation_browser_watchdog import _process_start_identity
    budgets, timeout = _clock_budgets(entries)
    with tempfile.TemporaryDirectory(prefix='hf-clock-') as temporary:
        root = Path(temporary)
        directory = root / 'check'
        directory.mkdir()
        prepared = []
        for index, (entry, budget) in enumerate(zip(entries, budgets)):
            scene = root / f'source-{index}'
            scene.mkdir()
            for item in entry['files']:
                source = Path(item['source'])
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('assembled native input changed before clock check')
                target = scene / item['scene_path']
                if not target.resolve().is_relative_to(scene.resolve()):
                    raise ValueError('assembled native input leaves its scene directory')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            prepared.append({**{k: v for k, v in entry.items() if k not in {'files', 'entry_directory'}},
                             'entry_directory': str(scene), 'timeout_ms': round(budget * 1000)})
        request = {'project_root': str(project), 'work_directory': str(directory),
                   'python_executable': sys.executable,
                   'entries': prepared}
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
    if stage["status"] != "completed" or len(records) != 1:
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


def _grid_tile_seconds(source, duration):
    """Read the actual native settle rule; reject unknown source expressions."""
    text = source.decode("utf-8")
    constants = {}
    for name in ("BASE_START", "TILE_BASE"):
        matches = re.findall(r"\bvar\s+" + name + r"\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;", text)
        if len(matches) != 1 or _number(matches[0]) <= 0:
            raise ValueError("Grid native timing declaration changed: " + name)
        constants[name] = _number(matches[0])
    floor = re.findall(r"var\s+TILE\s*=\s*Math\.min\(TILE_BASE,\s*Math\.max\(([0-9]+(?:\.[0-9]+)?),\s*avail\s*-\s*BASE_START\)\)\s*;", text)
    for expression in (r'var\s+OUT\s*=\s*exit\s*===\s*"none"\s*\?\s*0\s*:',
                       r'var\s+avail\s*=\s*duration\s*-\s*OUT\s*;',
                       r'var\s+latestStart\s*=\s*Math\.max\(0,\s*avail\s*-\s*TILE\)\s*;',
                       r'return\s+Math\.max\(0,\s*Math\.min\(start,\s*latestStart\)\)\s*;'):
        if len(re.findall(expression, text)) != 1:
            raise ValueError("Grid native clock expression changed")
    if len(floor) != 1 or _number(floor[0]) <= 0:
        raise ValueError("Grid native compression expression changed")
    return min(constants["TILE_BASE"], max(_number(floor[0]), duration - constants["BASE_START"]))


def grid_input_clock(root, brief):
    """Read hash-bound public Grid inputs without preparing a runtime or claiming rendered QA."""
    project = PACKAGE_ROOT
    entry = project / "scripts/hyperframes_native_adapter.py"
    spec = importlib.util.spec_from_file_location("_grid_execution_contract", entry)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    native.validate_brief(artifacts.canonical_json_bytes(brief))
    if brief["upstream_route"] != "hyperframes/grid-card-assemble" or brief["composition"]["alpha"] is not True:
        raise ValueError("Grid clock evidence must name the transparent native Grid route")
    records = [brief["entry"], *brief["assets"]]
    if len({r["scene_path"] for r in records}) != len(records):
        raise ValueError("Grid input contains duplicate scene files")
    data = {}
    for record in records:
        value = _path(root, record["job_path"]).read_bytes()
        if hashlib.sha256(value).hexdigest() != record["sha256"]:
            raise ValueError("Grid native input file checksum differs")
        data[record["scene_path"]] = value
    parser = _Mounts()
    parser.feed(data["index.html"].decode("utf-8"))
    if len(parser.mounts) != 1:
        raise ValueError("Grid input needs exactly one native mount")
    mount = parser.mounts[0]
    if mount.get("data-composition-id") != "grid-card-assemble" or _number(mount.get("data-start", 0)) != 0:
        raise ValueError("Grid clock evidence needs the native full-window mount")
    duration = brief["composition"]["frames"] / 24
    if abs(_number(mount["data-duration"]) - duration) > 1e-6:
        raise ValueError("Grid mount differs from the exact candidate window")
    source = (project / "vendor/hyperframes/registry/components/grid-card-assemble/grid-card-assemble.html").read_bytes()
    if hashlib.sha256(source).hexdigest() != brief["source_pins"]["sha256"]:
        raise ValueError("Grid original native source checksum differs")
    target = mount.get("data-composition-src")
    if target not in data or target == "index.html":
        raise ValueError("Grid mounted source is missing or ambiguous")
    _native_clock(source, data[target], brief["upstream_route"], duration)
    values = json.loads(mount["data-variable-values"], object_pairs_hook=artifacts._strict_object,
                        parse_constant=artifacts._reject_nonfinite)
    if not isinstance(values, dict) or values.get("exit") != "none":
        raise ValueError("Grid clock evidence currently requires explicit exit=none")
    labels, cues = _split(values.get("items")), _split(values.get("cues"))
    if (not 1 <= len(labels) <= 12 or any(not label or ":" in label or "：" in label for label in labels)
            or len(cues) != len(labels) or any(not cue for cue in cues)):
        raise ValueError("Grid clock needs complete explicit items and cues without body-text fallback")
    times = [_number(cue) for cue in cues]
    if any(not 0 <= time < duration for time in times):
        raise ValueError("Grid declared cue is outside the candidate window")
    return [(i, "reveal", label, time) for i, (label, time) in enumerate(zip(labels, times, strict=True))], source, duration


def validate_grid_clock(events, source, duration):
    """Keep native settle and the parent's stable reading budget separate."""
    tile = _grid_tile_seconds(source, duration)
    if max(e[3] for e in events) + tile + GRID_STABLE_HOLD_FRAMES / 24 > duration + 1e-8:
        raise GridClockConflict("Grid needs its native landing plus 12 stable reading frames in the current window")


def _native_events(route, mount, fps, native_duration, *, comparison_labels=None):
    values = json.loads(mount["data-variable-values"])
    start, duration = _number(mount.get("data-start", 0)), _number(native_duration)
    if start < 0 or duration <= 0:
        raise ValueError("invalid native mount window")
    name = route.removeprefix("hyperframes/")
    if name == "before-after-wipe":
        labels = [values.get(key) or (comparison_labels or {}).get(slot)
                  for key, slot in (("label_a", "before"), ("label_b", "after"))]
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("comparison overlay requires both public labels")
        split = _number(values.get("rest_split", 50))
        raw = _number(values.get("wipe_at", 0.25))
        if not 0 < split <= 100 or not 0 <= raw <= 8:
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


def validate_native_events(actual, *, segment, words, cuts, events, allow_spoken_labels=False):
    """Check the same truthful word anchors for published overlays and candidate clocks."""
    sid, fps = segment["segment_id"], 24
    labels = pinboard_alignment.checked_labels(list(dict.fromkeys(e[2] for e in actual)),
        segment=segment, words=words, cuts=cuts, allow_spoken=allow_spoken_labels)
    event_keys = [(e["slot"], e["kind"]) for e in events]
    if len(event_keys) != len(set(event_keys)) or set(event_keys) != {(e[0], e[1]) for e in actual}:
        raise ValueError(f"each native label and action needs exactly one anchor: {sid}")
    checked = []
    for slot, kind, text, local_time in actual:
        event = events[event_keys.index((slot, kind))]
        if event["text"] != text or text not in labels:
            raise ValueError(f"native visible text differs from reviewed text: {sid}")
        anchor = event["anchor"]
        index = anchor["index"]
        if type(index) is not int or not 0 <= index < len(words) or words[index]["text"] != anchor["text"]:
            raise ValueError(f"overlay source word differs from the approved transcript: {sid}")
        word = words[index]
        if word["end"] <= word["start"]:
            raise ValueError("zero-duration ASR noise cannot anchor a label")
        if allow_spoken_labels and not segment.get('visible_text') and (
                not pinboard_alignment._label_text(word['text'])
                or pinboard_alignment._label_text(word['text']) not in pinboard_alignment._label_text(text)):
            raise ValueError('derived comparison label anchor must belong to its spoken label')
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
    return checked


def validate_treatment(job, draft, treatment_path, *, phase='completed', target_keys=None) -> list[dict]:
    """Read actual HTML inputs, not duplicated intended trigger times."""
    targets = []
    for segment in draft["segments"]:
        if segment["visual_strategy"]["composition"]["family"] != "aroll_with_overlay":
            continue
        for cid, binding in segment["bindings"].items():
            if target_keys is not None and (segment['segment_id'], cid) not in target_keys:
                continue
            if binding.get("dependency_id") in {"hyperframes-native-adaptation", pinboard_alignment.DEPENDENCY_ID, huashu_stat_alignment.DEPENDENCY_ID, "motion-graphics-native", "barty-motion-graphics"}:
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
    if target_keys is not None:
        records = [r for r in records if (r.get('segment_id'), r.get('component_id')) in target_keys]
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
        alpha = brief.get('alpha') if binding.get('dependency_id') == 'barty-motion-graphics' else brief.get('composition', {}).get('alpha')
        if brief.get("source_binding") != expected_source or alpha is not True:
            raise ValueError(f"overlay source or alpha contract changed: {sid}")
        if brief["composition"]["fps"] != fps:
            raise ValueError("native overlay requires the approved 24 fps clock")
        if binding.get('dependency_id') == 'barty-motion-graphics':
            from . import motion_capabilities
            from .subtitles import _map_words
            from importlib import import_module
            native = import_module('motion_native_skill_adapter')
            native.validate_brief(brief_path.read_bytes(), dependency_id='barty-motion-graphics')
            route = 'barty-motion-graphics/motion-broll'
            motion_capabilities.validate_overlay_capability(route, binding)
            mapped = _map_words(words, {'segments': cuts})
            anchors = [{'text': word['text'], 'start': max(word['start'], segment['start']) - segment['start'],
                        'end': min(word['end'], segment['end']) - segment['start']}
                       for word in mapped if word['start'] < segment['end'] and word['end'] > segment['start']]
            from .visual_confirmation import local_word_anchors_match
            if not local_word_anchors_match(brief['word_anchors'], anchors):
                raise ValueError('Barty overlay word anchors differ from the approved edited speech')
            if phase not in {'planning', 'completed'}:
                raise ValueError('Unknown native overlay verification phase')
            result = native.inspect_result(job.job_dir, brief_path.read_bytes()) if phase == 'completed' else None
            report.append({'segment_id': sid, 'component_id': cid, 'route': route,
                           'brief_path': record['brief_path'], 'brief_sha256': binding['brief_sha256'],
                           'word_anchors': anchors, 'phase': phase,
                           **({'native_media_sha256': result['media']['sha256']} if result else {}),
                           'note': 'Native Skill owns motion; actual visibility and readability are checked on its rendered result'})
            continue
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
        if binding.get("dependency_id") == "motion-graphics-native":
            from . import motion_capabilities
            motion_capabilities.validate_overlay_capability("callout-pin", binding)
            from importlib import import_module
            motion = import_module("motion_graphics_adapter")
            motion.validate_brief(brief)
            entry = _path(job.job_dir, brief["entry"]["job_path"])
            if artifacts.sha256_file(entry) != brief["entry"]["sha256"]:
                raise ValueError(f"overlay HTML changed: {sid}")
            observed = motion.inspect_native_clock(PACKAGE_ROOT, entry, brief)
            events = record.get("events")
            if (not isinstance(events, list) or len(events) != 1
                    or events[0].get("slot") != 0 or events[0].get("kind") != "reveal"
                    or events[0].get("text") != observed["label"]
                    or segment["visible_text"] != [observed["label"]]):
                raise ValueError("callout needs one actual label and source-word event")
            event = events[0]
            anchor = event.get("anchor", {})
            index = anchor.get("index")
            if (type(index) is not int or not 0 <= index < len(words)
                    or words[index]["text"] != anchor.get("text")):
                raise ValueError("callout source word differs from the approved transcript")
            word = words[index]
            positions = [word["start"] + part["timeline_start"] - part["source_start"] for part in cuts
                         if part["source_start"] <= word["start"] < part["source_end"]]
            if len(positions) != 1 or word["end"] <= word["start"]:
                raise ValueError("callout anchor is outside the edited speech")
            anchor_time = positions[0]
            effective = segment["start"] + observed["reveal_time"]
            basis = event.get("basis")
            if basis == "current_clause":
                if (not segment["start"] <= anchor_time < segment["end"]
                        or effective < anchor_time - 1 / fps or effective > anchor_time + .8):
                    raise ValueError("native callout reveal differs from its source word")
            elif basis != "recap" or effective < anchor_time:
                raise ValueError("callout recap refers to speech that has not happened")
            checked = [{**event, "anchor_time": anchor_time, "effective_time": effective}]
            report.append({"segment_id": sid, "component_id": cid, "route": "callout-pin",
                           "brief_path": record["brief_path"], "brief_sha256": binding["brief_sha256"],
                           "entry_sha256": brief["entry"]["sha256"], "native_clock": observed,
                           "events": checked})
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
        source_path = (PACKAGE_ROOT / "vendor/hyperframes"
                       / "registry/components" / name / (name + ".html"))
        if artifacts.sha256_file(source_path) != brief["source_pins"]["sha256"]:
            raise ValueError(f"original native source changed: {sid}")
        comparison_labels = None
        if route == "hyperframes/before-after-wipe":
            comparison_labels = {}
            for index, slot in enumerate(("before", "after")):
                texts = {event.get("text") for event in record["events"] if event.get("slot") == index}
                if len(texts) != 1 or not all(isinstance(text, str) and text.strip() for text in texts):
                    raise ValueError("comparison slots need one speech-bound label per state")
                comparison_labels[slot] = texts.pop()
        native_duration = _native_clock(source_path.read_bytes(),
            _path(job.job_dir, assets[0]["job_path"]).read_bytes(), route, _number(mount["data-duration"]), labels=comparison_labels)
        actual, exit_time = _native_events(route, mount, fps, native_duration, comparison_labels=comparison_labels)
        assembled_inputs.append({"entry_directory": str(entry.parent), "route": route,
            "files": [{"source": str(_path(job.job_dir, item["job_path"])),
                       "scene_path": item["scene_path"], "sha256": item["sha256"]}
                      for item in [brief["entry"], *brief["assets"]]],
            "duration": native_duration, "start": _number(mount.get("data-start", 0)),
            "events": [{"slot": slot, "kind": kind, "text": text, "time": time}
                       for slot, kind, text, time in actual]})
        duration = segment["end"] - segment["start"]
        if exit_time > duration + 1e-6:
            raise ValueError(f"overlay exits after the next shot: {sid}")
        checked = validate_native_events(actual, segment=segment, words=words,
                                         cuts=cuts, events=record["events"], allow_spoken_labels=route == "hyperframes/before-after-wipe")
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

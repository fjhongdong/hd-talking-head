"""Call pinned Huashu native clips through the existing component executor."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction

SKILL = Path(__file__).resolve().parents[1] if __file__ != "<stdin>" else None
ENTRY = "scripts/huashu_motion_adapter.py"
VERSION = "1.1.0"
DEPENDENCY_ID = "huashu-art-motion"
UPSTREAM_COMMIT = "26dba25b2b495c2138848c29a2c90df356a20325"
DEFAULT_REGISTRY = "references/verified-template-registry.json"
PACKAGES = {"playwright": "1.61.0", "numpy": "2.5.3", "Pillow": "12.3.0",
            "fonttools": "4.66.1", "brotli": "1.2.0"}
KINDS = {
    "y2_vox": {"image", "highlight"},
    "y1_kurzgesagt": {"title", "point"},
    "t2_keynote_ui": {"title", "card"},
}
FAMILIES = {
    "y2_vox": {"evidence_source"},
    "y1_kurzgesagt": {"process_flow", "mechanism_system"},
    "t2_keynote_ui": {"product_features"},
}
PROVENANCE = ("template_origin", "template_id", "template_version", "verification_id",
              "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
              "semantic_families", "capacity")
ICONS = {"wave", "memory", "agent", "clock", "phone", "layers", "chart", "code",
         "check", "play", "bolt", "lock"}
_FAILURE_EMITTED = False
_FAILURE_STAGE = "preflight.input"
_NATIVE_DETAIL = ""


def native_render_argv(python, native_entry, spec, output):
    """Build the one native child invocation shared by every Huashu grammar."""
    python, native_entry = Path(python), Path(native_entry).resolve(strict=True)
    native_argv = [str(native_entry), "--spec", str(Path(spec)), "--out", str(Path(output))]
    startup = (
        "import runpy,socketserver,sys;"
        "socketserver.TCPServer.request_queue_size=64;"
        "sys.argv=" + repr(native_argv) + ";"
        "sys.path[0]=" + repr(str(native_entry.parent)) + ";"
        "runpy.run_path(" + repr(str(native_entry)) + ",run_name='__main__')"
    )
    return [str(python), "-B", "-c", startup]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode()


def exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"Huashu {name}: unknown or missing fields")


def relative(value):
    if type(value) is not str or not value or Path(value).is_absolute() or ".." in Path(value).parts or Path(value).as_posix() != value:
        raise ValueError("Huashu requires a canonical relative path")
    return Path(value)


def finite(value):
    return type(value) in {int, float} and math.isfinite(value)


def text(value, name, limit=48):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Huashu {name}: invalid or over-capacity text")


def validate_brief(payload):
    b = json.loads(payload) if type(payload) in {bytes, str} else payload
    exact(b, ("schema_version", "dependency_id", "source_binding", "canvas",
              "template_request", "props", "assets"), "brief")
    if type(b["schema_version"]) is not int or b["schema_version"] != 1 or b["dependency_id"] != DEPENDENCY_ID:
        raise ValueError("Huashu brief version/dependency mismatch")
    s, c, r = b["source_binding"], b["canvas"], b["template_request"]
    exact(s, ("aroll_sha256", "segment_id", "start", "end"), "source_binding")
    if not re.fullmatch(r"[a-f0-9]{64}", str(s["aroll_sha256"])) or type(s["segment_id"]) is not str or not s["segment_id"]:
        raise ValueError("Huashu source identity missing")
    if not finite(s["start"]) or not finite(s["end"]) or not 0 <= s["start"] < s["end"]:
        raise ValueError("Huashu source window invalid")
    exact(c, ("width", "height", "fps", "duration_in_frames"), "canvas")
    if any(type(c[k]) is not int or c[k] != v for k, v in (("width", 1080), ("height", 1920), ("fps", 24))):
        raise ValueError("Huashu requires 1080x1920@24")
    frames = c["duration_in_frames"]
    if type(frames) is not int or not 48 <= frames <= 480 or abs((s["end"] - s["start"]) * 24 - frames) > 1e-5:
        raise ValueError("Huashu source window and frame count differ")
    exact(b["props"], ("data",), "props")
    d = b["props"]["data"]
    exact(d, ("grammar", "data", "cues", "safe"), "props.data")
    g = d["grammar"]
    if type(g) is not str or g not in KINDS or type(d["data"]) is not dict:
        raise ValueError("Huashu grammar is not connected")
    allowed_data = {"y2_vox": set(), "y1_kurzgesagt": {"center", "flow"},
                    "t2_keynote_ui": {"eyebrow", "title", "subtitle", "accent"}}[g]
    if set(d["data"]) - allowed_data:
        raise ValueError("Huashu unsupported grammar data")
    for key in ("center", "eyebrow", "title", "subtitle"):
        if key in d["data"]:
            text(d["data"][key], key, 24)
    if "flow" in d["data"] and type(d["data"]["flow"]) is not bool:
        raise ValueError("Huashu flow must be boolean")
    safe = d["safe"]
    exact(safe, ("top", "bottom"), "safe")
    if any(type(v) is not int or v < 0 for v in safe.values()) or safe["top"] + safe["bottom"] > 1050:
        raise ValueError("Huashu unsupported safe-zone geometry")
    if type(b["assets"]) is not list:
        raise ValueError("Huashu assets must be an array")
    assets = {}
    for a in b["assets"]:
        exact(a, ("media_ref", "job_path", "sha256"), "asset")
        relative(a["job_path"])
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(a["media_ref"])) or a["media_ref"] in assets or not re.fullmatch(r"[a-f0-9]{64}", str(a["sha256"])):
            raise ValueError("Huashu duplicate or invalid asset")
        assets[a["media_ref"]] = a
    cues = d["cues"]
    if type(cues) is not list or not cues or len(cues) > 10:
        raise ValueError("Huashu cue capacity exceeded")
    used, units, numbers, last, level = set(), 0, [], -1.0, 0
    for qi, q in enumerate(cues):
        if type(q) is not dict or set(q) - {"at", "kind", "text", "sub", "image", "data", "dur"} or not {"at", "kind"} <= set(q):
            raise ValueError("Huashu cue fields invalid")
        at, kind = q["at"], q["kind"]
        if type(kind) is not str or kind not in KINDS[g] or not finite(at) or at < last or not 0 <= at < frames / 24 or abs(at * 24 - round(at * 24)) > 1e-5:
            raise ValueError("Huashu unknown, unordered or off-frame cue")
        last = at
        for key in ("text", "sub"):
            if key in q:
                text(q[key], key, 32)
        if "dur" in q and (not finite(q["dur"]) or q["dur"] <= 0 or at + q["dur"] + .5 > frames / 24 or not (g == "y1_kurzgesagt" and kind == "enter")):
            raise ValueError("Huashu unsupported/incomplete cue duration")
        data = q.get("data", {})
        if type(data) is not dict:
            raise ValueError("Huashu cue data must be an object")
        keys = ({"rect"} if kind == "highlight" else
                {"color"} if g == "y1_kurzgesagt" and kind == "point" else
                {"icon"} if g == "t2_keynote_ui" and kind == "card" else
                {"halftone"} if kind == "image" else set())
        if set(data) - keys:
            raise ValueError("Huashu cue has ignored data fields")
        if "icon" in data and data["icon"] not in ICONS:
            raise ValueError("Huashu unknown icon")
        if kind == "point" or (kind == "title" and g != "t2_keynote_ui"):
            text(q.get("text"), kind, 32)
        if kind in {"card", "step"} and "image" not in q:
            text(q.get("text"), kind, 24)
        if "image" in q:
            if type(q["image"]) is not str or q["image"] not in assets or kind not in {"image", "clip", "card", "step"}:
                raise ValueError("Huashu image is not a bound media_ref")
            used.add(q["image"])
        if g == "y2_vox" and kind in {"image", "clip"} and "image" not in q:
            raise ValueError("Huashu Vox image cue requires an actual image")
        if kind == "highlight" and g != "y1_kurzgesagt":
            rect = data.get("rect")
            if not any("image" in previous for previous in cues[:qi]) or type(rect) is not list or len(rect) != 4 or not all(finite(v) for v in rect) or not (0 <= rect[0] < 1 and 0 <= rect[1] < 1 and 0 < rect[2] <= 1 - rect[0] and 0 < rect[3] <= 1 - rect[1]):
                raise ValueError("Huashu highlight must locate an actual image region")
        if kind in {"enter", "highlight"} and g == "y1_kurzgesagt":
            index = data.get("index", 0)
            if type(index) is not int or not 0 <= index < level:
                raise ValueError("Huashu node action has no existing target")
            if kind == "enter":
                level = 0
                duration = q.get("dur", 1.6)
                if at + duration + .5 > frames / 24 or any(z["kind"] == "point" and z["at"] < at + duration for z in cues[qi + 1:]):
                    raise ValueError("Huashu enter cannot finish before new nodes")
        if kind == "number" or "value" in data:
            value = data.get("value")
            if not finite(value) or (kind == "number" and at < .9):
                raise ValueError("Huashu number requires a finite value and count-in")
            numbers.append(value)
        if kind in {"point", "card", "step", "image", "clip", "number"}:
            units += 1
        if g == "y1_kurzgesagt" and kind == "point":
            level += 1
        if at + .5 >= frames / 24:
            raise ValueError("Huashu cue has no final reading interval")
    if set(assets) != used or not 1 <= units <= 3:
        raise ValueError("Huashu media/content capacity mismatch")
    if (g == "y2_vox" and (len(assets) != 1 or units != 1 or cues[0]["kind"] != "image")
            or g == "y1_kurzgesagt" and d["data"].get("flow") is not True
            or g != "y2_vox" and assets):
        raise ValueError("Huashu input is outside the qualified native recipe")
    exact(r, ("semantic_family", "information_units", "numeric_values", "numeric_scale"), "template_request")
    if type(r["numeric_values"]) is not list or any(not finite(v) for v in r["numeric_values"]) or r["semantic_family"] not in FAMILIES[g] or type(r["information_units"]) is not int or r["information_units"] != units or r["numeric_values"] != numbers or r["numeric_scale"] != ("linear" if numbers else "not_applicable"):
        raise ValueError("Huashu request differs from actual content")
    return b


def native_spec(brief):
    b = validate_brief(brief)
    c = b["canvas"]
    return {**json.loads(json.dumps(b["props"]["data"])), "width": c["width"],
            "height": c["height"], "fps": c["fps"],
            "duration": c["duration_in_frames"] / c["fps"], "alpha": False}


def local_cue_frame(word_frame, segment_start_frame):
    if type(word_frame) is not int or type(segment_start_frame) is not int or word_frame < segment_start_frame:
        raise ValueError("Huashu word must use the approved A-roll frame clock")
    return (word_frame - segment_start_frame) / 24


def source_snapshot(project_root):
    root = Path(project_root).resolve(strict=True) / "skill-development/vendor/huashu-art-motion"
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != UPSTREAM_COMMIT:
        raise ValueError("Huashu vendor commit changed")
    paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "scripts/engine/lib",
        "scripts/engine/render.py", "scripts/engine/clip.html", "scripts/engine/clip.js",
        *["scripts/engine/clips/" + g + ".js" for g in KINDS]], text=True).splitlines()
    if not paths or subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--", *paths], text=True).strip():
        raise ValueError("Huashu source has local changes")
    files = {}
    for name in paths:
        p = root / relative(name)
        if p.is_symlink() or not p.is_file():
            raise ValueError("Huashu source closure incomplete")
        files[name] = sha(p)
    return {"root": str(root), "commit": head, "files": files}


def check_runtime(project_root, *, browser_probe=False, executable_paths=None):
    runtime = source_snapshot(project_root)
    python = Path(runtime["root"]) / ".venv/bin/python"
    if not python.is_file():
        raise ValueError("Huashu project venv is missing; run project ensure")
    code = "import importlib.metadata as m,json; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(json.dumps(dict(versions={k:m.version(k) for k in " + repr(list(PACKAGES)) + "},browser=p.chromium.executable_path))); p.stop()"
    result = subprocess.run([str(python), "-B", "-c", code], check=True, capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    if info["versions"] != PACKAGES or not Path(info["browser"]).is_file():
        raise ValueError("Huashu render dependencies/browser mismatch")
    ffmpeg, ffprobe = ((executable_paths[k] if executable_paths else shutil.which(k))
                      for k in ("ffmpeg", "ffprobe"))
    if not ffmpeg or not ffprobe:
        raise ValueError("Huashu ffmpeg/ffprobe missing")
    if browser_probe:
        subprocess.run([str(python), "-B", "-c", "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()"], check=True, capture_output=True, timeout=30)
    runtime.update(python=str(python), python_sha256=sha(python), packages=info["versions"],
                   browser=info["browser"], browser_sha256=sha(info["browser"]),
                   ffmpeg=str(Path(ffmpeg).resolve()), ffprobe=str(Path(ffprobe).resolve()))
    runtime.update(ffmpeg_sha256=sha(runtime["ffmpeg"]), ffprobe_sha256=sha(runtime["ffprobe"]))
    return runtime


def prepare_runtime(project_root):
    source = source_snapshot(project_root)
    python = Path(source["root"]) / ".venv/bin/python"
    if not python.exists():
        base = shutil.which("python3.12")
        if not base:
            raise ValueError("Huashu requires the project Python 3.12 runtime")
        subprocess.run([base, "-m", "venv", str(python.parent.parent)], check=True, timeout=60)
    modules = subprocess.run([str(python), "-c", "import playwright,numpy,PIL,fontTools,brotli"], capture_output=True)
    if modules.returncode:
        subprocess.run([str(python), "-m", "pip", "install", *[k + "==" + v for k, v in PACKAGES.items()]], check=True, timeout=240)
    from_path = subprocess.check_output([str(python), "-c", "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()"], text=True).strip()
    if not Path(from_path).is_file():
        subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True, timeout=240)
    return check_runtime(project_root, browser_probe=True)


def registry_template(registry_path, grammar):
    path = SKILL / relative(registry_path)
    spec = importlib.util.spec_from_file_location("huashu_registry", SKILL / "scripts/verify_broll_template.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    if registry_path == DEFAULT_REGISTRY:
        report = verifier.verify_registry(path)
        if report["failures"]:
            raise ValueError("Huashu template registry failed: " + "; ".join(report["failures"]))
        matches = [t for t in report["verified"] if t["template_id"] == "huashu-art-motion/" + grammar]
    else:
        records = json.loads(path.read_bytes())
        exact(records, ("schema_version", "templates"), "candidate registry")
        if records["schema_version"] != 1 or len(records["templates"]) != 1:
            raise ValueError("Huashu candidate snapshot must contain one template")
        record = records["templates"][0]
        verifier.verify_candidate_binding(record, registry_path, sha(path))
        matches = [record] if record["template_id"] == "huashu-art-motion/" + grammar else []
    if len(matches) != 1 or matches[0]["upstream"]["project"] != DEPENDENCY_ID:
        raise ValueError("Huashu template is not registered for this mode")
    return matches[0]


def create_adapter(project_root, python_executable, brief_loader, *, registry_path=DEFAULT_REGISTRY):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project)
    launcher = Path(python_executable).resolve(strict=True)
    registry = SKILL / relative(registry_path)
    if not registry.is_file():
        raise ValueError("Huashu requires a real template qualification record")
    entry_sha, registry_sha = sha(SKILL / ENTRY), sha(registry)

    def guarded(job, recipe, component):
        from edit.hd.tools import contract_artifacts, visual_canary
        if sha(SKILL / ENTRY) != entry_sha or sha(registry) != registry_sha or check_runtime(project) != runtime:
            raise ValueError("Huashu source/runtime/registry changed after binding")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        qualification_context = None
        if registry_path != DEFAULT_REGISTRY:
            qualification_context = {
                "segment_id": recipe["segment_id"],
                "component_id": component["component_id"],
                "dependency_id": DEPENDENCY_ID,
                "template_id": component["template_id"],
                "recipe_sha256": contract_artifacts.sha256_json(recipe),
                "qualification_registry": {"path": registry_path, "sha256": registry_sha},
            }
        plan = visual_canary.load_approved_visual_plan(
            job, qualification_context=qualification_context
        )
        segment = next((s for s in plan["segments"] if s["segment_id"] == recipe["segment_id"]), None)
        if segment is None or segment["shot_recipe"] != json.loads(json.dumps(recipe)):
            raise ValueError("Huashu recipe is not the approved segment")
        aroll = visual_canary.approved_aroll_record(job, plan)
        source = {"aroll_sha256": aroll["sha256"], "segment_id": segment["segment_id"], "start": segment["start"], "end": segment["end"]}
        if b["source_binding"] != source or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"])) or component["artifact_contract"]["alpha"] or component["render_window"]["end_frame"] - component["render_window"]["start_frame"] != b["canvas"]["duration_in_frames"] or any(recipe["canvas"][k] != b["canvas"][k] for k in ("width", "height", "fps")):
            raise ValueError("Huashu approved source, request or clock mismatch")
        registry_template(registry_path, b["props"]["data"]["grammar"])
        return payload

    def media(job, recipe, component, payload):
        return tuple(ReferenceProcessMedia(**a) for a in validate_brief(payload)["assets"])

    return ReferenceProcessAdapter(adapter_id="huashu-native-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="HTMLCanvas",
        renderer_version=UPSTREAM_COMMIT, artifact_media_type="video", launcher=launcher,
        launcher_sha256=sha(launcher), brief_loader=guarded, media_loader=media,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--output", "{output_path}",
            "--media-manifest", "{media_manifest_fd}", "--skill-root", str(SKILL),
            "--project-root", str(project), "--registry-path", registry_path,
            "--registry-sha256", registry_sha, "--runtime", base64.b64encode(canonical(runtime)).decode()),
        qualification_registry_path=None if registry_path == DEFAULT_REGISTRY else registry_path,
        qualification_registry_sha256=None if registry_path == DEFAULT_REGISTRY else registry_sha)


def create_binding(adapter, brief_bytes, *, registry_path=DEFAULT_REGISTRY):
    b = validate_brief(brief_bytes)
    record = registry_template(registry_path, b["props"]["data"]["grammar"])
    r = b["template_request"]
    if r["semantic_family"] not in record["semantic_families"] or not record["capacity"]["min_units"] <= r["information_units"] <= record["capacity"]["max_units"]:
        raise ValueError("Huashu input exceeds the qualified template")
    return {**{k: record[k] for k in PROVENANCE}, "producer_type": "dependency",
        "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY, "producer_version": VERSION,
        "primary_renderer": "HTMLCanvas", "renderer_version": UPSTREAM_COMMIT,
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned",
            "exit_code": None, "template_request": r}}


def create_artifact_probe(ffprobe_executable):
    from data_rollup_adapter import create_artifact_probe as native_probe
    return native_probe(ffprobe_executable=ffprobe_executable)


def _emit_native_failure(exc):
    """Expose only a bounded, useful native failure without leaking invocation data."""
    global _NATIVE_DETAIL
    output = []
    for stream in (getattr(exc, "stdout", b""), getattr(exc, "stderr", b"")):
        if isinstance(stream, bytes):
            stream = stream.decode("utf-8", "replace")
        if stream:
            output.append(stream)
    stderr = "\n".join(output)
    allowed = ("Error", "error", "ERR_", "page", "Page", "resource", "Resource", "exit")
    lines = [line.strip() for line in stderr.splitlines()
             if line.strip() and any(token in line for token in allowed)
             and not any(token in line for token in ('File "', 'Command ', 'Traceback', 'subprocess.'))]
    safe = []
    for line in lines:
        line = re.sub(r"https?://[^\s]+", "<local-resource-url>", line)
        line = re.sub(r"(?i)(token|secret|password|api[_-]?key)=([^\s]+)", r"\1=<redacted>", line)
        line = re.sub(r"(?i)(authorization|api[_-]?key)\s*:\s*[^|]+", r"\1: <redacted>", line)
        line = re.sub(r"/(?:Users|private|tmp|opt|var)/[^\s\"']+", "<local-path>", line)
        safe.append(line)
    if lines:
        _NATIVE_DETAIL = " | ".join(safe)[:1900]


def _emit_failure_summary(exc, stage):
    """Emit one stable, non-sensitive diagnostic for wrapper failures."""
    global _FAILURE_EMITTED
    if _FAILURE_EMITTED:
        return
    reason = {
        "preflight.input": "input brief invalid", "preflight.runtime": "runtime validation failed",
        "preflight.registry": "registry validation failed", "preflight.media": "media validation failed",
        "preflight.native_closure": "native source validation failed", "preflight.glyph": "glyph validation failed",
        "native.render": "native render failed", "normalize": "normalization failed",
    }.get(stage, "validation failed")
    message = str(exc)
    for needle, mapped in (
        ("brief", "input brief invalid"), ("runtime", "runtime validation failed"),
        ("registry", "registry validation failed"), ("media", "media validation failed"),
        ("glyph", "glyph validation failed"), ("executable", "frozen executable validation failed"),
        ("normalize", "normalization failed"), ("output", "native output invalid"),
    ):
        if needle in message.lower():
            reason = mapped
            break
    detail = f" | {_NATIVE_DETAIL}" if _NATIVE_DETAIL else ""
    print(f"Huashu native renderer diagnostic: {stage}: {reason}{detail}", file=sys.stderr)
    _FAILURE_EMITTED = True


def normalize_native_output(native_path, output_path, *, ffmpeg, ffprobe, expected_frames):
    """Normalize the pinned native MP4 without changing its decoded media."""
    native_path, output_path = Path(native_path), Path(output_path)

    def probe(path):
        try:
            result = subprocess.run(
                [str(ffprobe), "-v", "error", "-count_frames", "-show_streams",
                 "-show_format", "-of", "json", str(path)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
            _emit_native_failure(exc)
            raise ValueError("Huashu native output probe failed") from exc

    def validate(info, *, allow_missing_aspect):
        streams = info.get("streams", [])
        video = [s for s in streams if s.get("codec_type") == "video"]
        if (len(streams) != 1 or len(video) != 1 or
                any(s.get("codec_type") == "audio" for s in streams) or
                "mp4" not in str(info.get("format", {}).get("format_name", "")).split(",")):
            raise ValueError("Huashu native output must be one silent video stream")
        stream = video[0]
        if (stream.get("codec_name") != "h264" or stream.get("width") != 1080 or
                stream.get("height") != 1920 or stream.get("pix_fmt") != "yuv420p" or
                stream.get("field_order") not in (None, "progressive")):
            raise ValueError("Huashu native output video contract mismatch")
        try:
            fps = Fraction(stream["avg_frame_rate"])
            nominal_fps = Fraction(stream["r_frame_rate"])
        except (KeyError, ValueError, ZeroDivisionError):
            raise ValueError("Huashu native output frame rate missing")
        if (fps != 24 or nominal_fps != 24 or
                stream.get("nb_read_frames") not in (str(expected_frames), expected_frames)):
            raise ValueError("Huashu native output frame count/rate mismatch")
        try:
            duration = float(info.get("format", {}).get("duration", stream.get("duration")))
        except (TypeError, ValueError):
            raise ValueError("Huashu native output duration missing")
        if not math.isfinite(duration) or abs(duration - expected_frames / 24) > 1 / 24:
            raise ValueError("Huashu native output duration mismatch")
        for key, wanted in (("sample_aspect_ratio", "1:1"), ("display_aspect_ratio", "9:16")):
            if stream.get(key) != wanted and (not allow_missing_aspect or stream.get(key) is not None):
                raise ValueError("Huashu native output aspect ratio mismatch")
        rotations = [str(stream.get("tags", {}).get("rotate", "0"))]
        rotations.extend(str(item.get("rotation")) for item in stream.get("side_data_list", [])
                         if item.get("rotation") is not None)
        if any(rotation not in ("0", "") for rotation in rotations):
            raise ValueError("Huashu native output rotation mismatch")
        return info

    validate(probe(native_path), allow_missing_aspect=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="huashu-normalized-", dir=str(native_path.parent)) as temp:
        normalized = Path(temp) / "normalized.mp4"
        try:
            subprocess.run(
                [str(ffmpeg), "-y", "-i", str(native_path), "-map", "0:v:0", "-c:v", "copy",
                 "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1", "-aspect", "9:16",
                 "-an", str(normalized)],
                check=True, capture_output=True, text=True, timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            _emit_native_failure(exc)
            raise ValueError("Huashu native output normalization failed") from exc
        validate(probe(normalized), allow_missing_aspect=False)
        shutil.copyfile(normalized, output_path)
    return output_path


def render(args):
    global _FAILURE_STAGE
    _FAILURE_STAGE = "preflight.input"
    raw = Path(args.brief).read_bytes()
    b = validate_brief(raw)
    _FAILURE_STAGE = "preflight.runtime"
    runtime = json.loads(base64.b64decode(args.runtime))
    if check_runtime(args.project_root, executable_paths=runtime) != runtime or sha(SKILL / relative(args.registry_path)) != args.registry_sha256:
        raise ValueError("Huashu frozen source/runtime/registry mismatch")
    ffmpeg_dir = str(Path(runtime["ffmpeg"]).parent)
    frozen_path = os.pathsep.join(dict.fromkeys((
        ffmpeg_dir, str(Path(runtime["ffprobe"]).parent), "/usr/bin", "/bin")))
    for executable in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(executable, path=frozen_path)
        if not resolved or Path(resolved).resolve() != Path(runtime[executable]).resolve():
            raise ValueError("Huashu frozen executable path mismatch")
    os.environ["PATH"] = frozen_path
    _FAILURE_STAGE = "preflight.registry"
    registry_template(args.registry_path, b["props"]["data"]["grammar"])
    _FAILURE_STAGE = "preflight.media"
    mf = str(args.media_manifest)
    manifest = json.loads(Path("/dev/fd/" + mf if mf.isdigit() else mf).read_bytes())
    records = {r["media_ref"]: r for r in manifest.get("media", [])}
    if manifest.get("schema_version") != "reference-process-media/v1" or manifest.get("brief_sha256") != hashlib.sha256(raw).hexdigest() or len(records) != len(manifest.get("media", [])) or set(records) != {a["media_ref"] for a in b["assets"]}:
        raise ValueError("Huashu frozen media manifest mismatch")
    with tempfile.TemporaryDirectory(prefix="huashu-native-") as temp:
        tmp = Path(temp)
        root = Path(runtime["root"])
        _FAILURE_STAGE = "preflight.native_closure"
        for name, digest in runtime["files"].items():
            source = root / relative(name)
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Huashu native source changed during snapshot")
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        spec = native_spec(b)
        paths = {}
        _FAILURE_STAGE = "preflight.media"
        for asset in b["assets"]:
            record = records[asset["media_ref"]]
            if type(record.get("fd")) is not int or record["fd"] < 0:
                raise ValueError("Huashu requires the frozen media descriptor")
            data = Path("/dev/fd/" + str(record["fd"])).read_bytes()
            if record["sha256"] != asset["sha256"] or hashlib.sha256(data).hexdigest() != asset["sha256"] or len(data) != record["byte_length"]:
                raise ValueError("Huashu media bytes differ from the approved asset")
            target = tmp / (asset["media_ref"] + ".png")
            target.write_bytes(data)
            paths[asset["media_ref"]] = str(target)
        for cue in spec["cues"]:
            if "image" in cue:
                cue["image"] = paths[cue["image"]]
        spec_path = tmp / "spec.json"
        spec_path.write_bytes(canonical(spec))
        glyph_check = "import json,sys; from pathlib import Path; from fontTools.ttLib import TTFont; d=json.loads(Path(sys.argv[1]).read_bytes()); chars={ord(c) for c in json.dumps(d,ensure_ascii=False) if ord(c)>=0x2e80}; root=Path(sys.argv[2]); maps=[set(TTFont(root/('NotoSansSC-'+w+'.woff')).getBestCmap()) for w in ('500','700','800','900')]; missing=set().union(*(chars-m for m in maps)); assert not missing, 'Missing native glyphs: '+''.join(chr(c) for c in sorted(missing))"
        _FAILURE_STAGE = "preflight.glyph"
        subprocess.run([runtime["python"], "-B", "-c", glyph_check, str(spec_path), str(tmp / "scripts/engine/lib/fonts")], check=True, capture_output=True, text=True, timeout=30)
        out = tmp / "native.mp4"
        _FAILURE_STAGE = "native.render"
        try:
            result = subprocess.run(native_render_argv(runtime["python"], tmp / "scripts/engine/render.py", spec_path, out),
                check=True, capture_output=True,
                text=True, timeout=240)
        except subprocess.CalledProcessError as exc:
            _emit_native_failure(exc)
            raise
        if any(w in result.stdout for w in ("缺字", "已丢掉", "被忽略")) or not out.is_file() or not out.stat().st_size:
            raise ValueError("Huashu native renderer reported an invalid/incomplete output")
        _FAILURE_STAGE = "normalize"
        normalize_native_output(out, args.output, ffmpeg=runtime["ffmpeg"],
                                ffprobe=runtime["ffprobe"],
                                expected_frames=b["canvas"]["duration_in_frames"])
        return {"dependency_id": DEPENDENCY_ID, "native_entrypoint": "scripts/engine/render.py",
                "grammar": spec["grammar"], "frames": b["canvas"]["duration_in_frames"]}


def main():
    global SKILL
    global _FAILURE_STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path)
    parser.add_argument("--dependency-id", default=DEPENDENCY_ID)
    parser.add_argument("--probe", action="store_true")
    for name in ("brief", "output", "media-manifest", "registry-path", "registry-sha256", "runtime"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    SKILL = args.skill_root.resolve(strict=True) if args.skill_root else SKILL
    if SKILL is None or args.dependency_id != DEPENDENCY_ID:
        parser.error("Use the Huashu adapter factory and explicit Skill root")
    try:
        if args.probe:
            _FAILURE_STAGE = "preflight.runtime"
            check_runtime(args.project_root, browser_probe=True)
            print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID,
                "entrypoint": ENTRY, "producer_version": VERSION, "adapter_identity": {
                    "adapter_type": "ReferenceProcessAdapter", "approved_executor": "reference_adapter",
                    "primary_renderer": "HTMLCanvas"}}))
        elif all(getattr(args, k) for k in ("brief", "output", "media_manifest", "registry_path", "registry_sha256", "runtime")):
            print(json.dumps(render(args)))
        else:
            parser.error("Use --probe or the complete approved render invocation")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        _emit_failure_summary(exc, _FAILURE_STAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

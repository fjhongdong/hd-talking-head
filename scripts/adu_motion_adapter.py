"""Adu motion-video reference adapter.

This module only binds a frozen, already adapted scene to the common
ReferenceProcessAdapter contract.  It does not generate or author animation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import importlib.util
import json
import math
import shutil
import subprocess
import tempfile
import sys
import os
import re
from fractions import Fraction
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENTRY = "scripts/adu_motion_adapter.py"
VERSION = "1.0.0"
DEPENDENCY_ID = "adu-motion-video"
UPSTREAM_COMMIT = "4d9777d799c73e4ed212b2ecb6ec6cece33f98a7"
SOURCE_FPS = 60
OUTPUT_FPS = 24
SOURCE_MIN_FRAMES = 882
SOURCE_MAX_HOLD_FRAMES = 360
SEMANTIC_FAMILY = "decomposition_consolidation"
SCENE_FILES = {"index.html", "config.js", "scenes.js", "style.css", "lib.js", "macro_runtime.js", "workflow.json"}
INDEX_HTML = "<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='style.css'></head><body><div id='stage'><div id='world'></div><div id='fx'></div></div><script src='config.js'></script><script src='lib.js'></script><script src='scenes.js'></script><script src='macro_runtime.js'></script></body></html>\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_bytes(record: dict) -> bytes:
    texts = {key: html.escape(value, quote=True) for key, value in record["timed_scene"]["scenes"][0]["texts"].items()}
    config = {"fps": 24, "width": 1080, "height": 1920,
              "race": {"labels": [], "keys": [0, record["composition"]["frames"] / 24]}}
    return ("window.CONFIG=" + json.dumps(config) + ";\nwindow.ADU_TEXTS="
            + json.dumps(texts, ensure_ascii=False) + ";\nwindow.MACRO_PLAN="
            + json.dumps(record["timed_scene"], ensure_ascii=False, allow_nan=False)
            + ";\nwindow.MACRO_SOURCE_SFX=[[]];\n").encode("utf-8")


def upstream_identity(root: Path) -> dict:
    patch = SKILL / "assets/adu-motion-video"
    return {"commit": UPSTREAM_COMMIT, "group": "decompose-and-consolidate",
            "source_sha256": sha(root / "packs/classic-performance/1.0.0/units/decompose-and-consolidate.js"),
            "layout_sha256": sha(patch / "scene.js"), "style_sha256": sha(patch / "style.css")}


def _relative(value: object) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts or Path(value).as_posix() != value:
        raise ValueError("A canonical relative path is required")
    return Path(value)


def prepare_scene(*, source_binding: dict, frames: int, cues: list[dict], inputs: dict,
                  source_text: str, branches: list[str], result: str,
                  part_cues: list[float], project_root: str | Path,
                  output_dir: str | Path | None = None,
                  scene_id: str = "adu-decompose-and-consolidate") -> dict:
    """Compile native 60fps choreography, then prepare its pure-visual layout.

    Caller-supplied word anchors must fit the existing three focus windows.
    A matching overall duration is not sufficient to accept a narration.
    """
    if not isinstance(source_text, str) or not source_text.strip() or not isinstance(branches, list) or len(branches) != 3 or not all(isinstance(x, str) and x.strip() for x in branches) or not isinstance(result, str) or not result.strip():
        raise ValueError("Real source text, three branches and result are required")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Real macro inputs are required")
    if not isinstance(scene_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", scene_id):
        raise ValueError("Invalid scene id")
    if not isinstance(source_binding, dict) or set(source_binding) != {"aroll_sha256", "segment_id", "start", "end"}:
        raise ValueError("source_binding is required")
    if not isinstance(source_binding["aroll_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", source_binding["aroll_sha256"]):
        raise ValueError("Invalid source hash")
    if not isinstance(source_binding["segment_id"], str) or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", source_binding["segment_id"]):
        raise ValueError("Invalid segment id")
    start, end = source_binding["start"], source_binding["end"]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, end)) or not 0 <= start < end:
        raise ValueError("Invalid source clock")
    if type(frames) is not int or not 353 <= frames <= 1440:
        raise ValueError("Adu scene requires at least 14.7 seconds at 24fps")
    if abs((end - start) * OUTPUT_FPS - frames) > 1e-6:
        raise ValueError("Output frame clock does not match source window")
    if not isinstance(cues, list) or len(cues) != 3:
        raise ValueError("Exactly three caller-supplied cues are required")
    seen = set()
    for cue in cues:
        if not isinstance(cue, dict) or set(cue) != {"id", "at"} or cue["id"] in seen:
            raise ValueError("Invalid or duplicate cue")
        if cue["id"] not in {"concept", "decompose", "result"}:
            raise ValueError("Cue ids must describe the selected source group")
        if type(cue["at"]) not in (int, float) or not start <= cue["at"] < end:
            raise ValueError("Cue lies outside the edited source window")
        seen.add(cue["id"])
    if seen != {"concept", "decompose", "result"}:
        raise ValueError("All protected source cues are required")
    if (not isinstance(part_cues, list) or len(part_cues) != 3
            or any(type(at) not in (int, float) or not math.isfinite(at) or not start <= at < end for at in part_cues)
            or not part_cues[0] < part_cues[1] < part_cues[2]):
        raise ValueError("Three increasing real part word anchors are required")
    if (not isinstance(inputs.get("parts"), list) or len(inputs["parts"]) != 3
            or not all(isinstance(part, dict) for part in inputs["parts"])
            or [part.get("label") for part in inputs["parts"]] != branches
            or not isinstance(inputs.get("result"), dict)
            or inputs["result"].get("conclusion") != result):
        raise ValueError("Content and native input bindings differ")
    root = Path(check_runtime(project_root)["root"])
    vendor_scripts = root / "scripts"
    # The compiler imports its sibling semantic-input module.
    sys.path.insert(0, str(vendor_scripts))
    try:
        spec = importlib.util.spec_from_file_location("adu_native_adapt_project", vendor_scripts / "adapt_project.py")
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        pack = root / "packs/classic-performance/1.0.0"
        manifest = json.loads((pack / "manifest.json").read_bytes())
        scene = next(s for s in manifest["scenes"] if s["id"] == "decompose-and-consolidate")
        # Remove actual presenter and branding/context slots from this one
        # structural layout, not by supplying fake talk frames or blank labels.
        scene["slots"] = [slot for slot in scene["slots"] if slot["type"] != "talk" and slot["id"] not in {"text-00", "text-01"}]
        scene["requiresFaceTracking"] = False
        scene["hasProgressRail"] = False
        manifest["scenes"] = [scene]
        target = {"id": scene_id, "sceneId": scene["id"], "durationFrames": (frames * 5 + 1) // 2,
                  "cues": {cue["id"]: {"at": cue["at"] - start} for cue in cues}, "inputs": inputs}
        transcript = [{"id": "source", "start": 0, "end": frames / OUTPUT_FPS, "text": source_text}]
        compiled = native.compile_plan(manifest, {"pack": manifest["id"], "fps": SOURCE_FPS,
            "transcript": transcript, "scenes": [target]}, spec_dir=Path.cwd())
    finally:
        sys.path.pop(0)
    timed = compiled["scenes"][0]
    def output_time(source_at):
        return native.source_to_output_frame(timed, source_at) / SOURCE_FPS
    for index, at in enumerate(part_cues):
        focus_start = output_time(90.4 + index * 1.28)
        focus_end = output_time(91.48 + index * 1.28)
        if not focus_start - 2 / OUTPUT_FPS <= at - start <= focus_end + 2 / OUTPUT_FPS:
            raise ValueError(f"Part {index + 1} word anchor conflicts with protected choreography")
    if output_time(95) < part_cues[-1] - start - 2 / OUTPUT_FPS:
        raise ValueError("Consolidation would begin before the third spoken part")
    last_frame = math.floor((frames - 1) / OUTPUT_FPS * SOURCE_FPS + 1e-6)
    points = timed["time_map"]
    last_source = native.interpolate(last_frame, [(p["output_frame"], p["source"]) for p in points])
    if last_source < max(window["sourceEnd"] for window in timed["motionWindows"]):
        raise ValueError("Last sampled frame truncates a protected action")
    record = {"schema_version": 1, "dependency_id": DEPENDENCY_ID,
            "scene_id": scene_id, "source_binding": dict(source_binding),
            "source_fps": SOURCE_FPS, "output_fps": OUTPUT_FPS,
            "min_source_frames": SOURCE_MIN_FRAMES, "max_hold_frames": SOURCE_MAX_HOLD_FRAMES,
            "source_text": source_text, "branches": list(branches), "result": result,
            "cues": [dict(c) for c in cues], "part_cues": list(part_cues), "inputs": inputs,
            "timed_scene": compiled, "last_sampled_source_time": last_source,
            "composition": {"frames": frames, "width": 1080, "height": 1920, "fps": 24}}
    if output_dir is not None:
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=False)
        patch = SKILL / "assets/adu-motion-video"
        record["upstream"] = upstream_identity(root)
        (output / "config.js").write_bytes(config_bytes(record))
        shutil.copyfile(patch / "scene.js", output / "scenes.js")
        shutil.copyfile(patch / "style.css", output / "style.css")
        shutil.copyfile(pack / "lib.js", output / "lib.js")
        shutil.copyfile(vendor_scripts / "macro_runtime.js", output / "macro_runtime.js")
        (output / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        (output / "workflow.json").write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        record["project"] = {"directory": str(output), "files": sorted(p.name for p in output.iterdir())}
    return record


def validate_brief(payload: bytes | str) -> dict:
    brief = json.loads(payload)
    if not isinstance(brief, dict) or set(brief) != {"schema_version", "dependency_id", "source_binding", "template_request", "composition", "files", "workflow_media_ref"}:
        raise ValueError("Invalid Adu scene brief")
    if brief["schema_version"] != 1 or brief["dependency_id"] != DEPENDENCY_ID:
        raise ValueError("Unsupported Adu brief")
    source = brief["source_binding"]
    composition = brief["composition"]
    if (not isinstance(source, dict) or set(source) != {"aroll_sha256", "segment_id", "start", "end"}
            or not isinstance(source["aroll_sha256"], str) or not isinstance(source["segment_id"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", source["aroll_sha256"])
            or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", source["segment_id"])
            or any(type(source[k]) not in (int, float) or not math.isfinite(source[k]) for k in ("start", "end"))
            or not 0 <= source["start"] < source["end"]):
        raise ValueError("Invalid source binding")
    if not isinstance(composition, dict) or set(composition) != {"id", "width", "height", "fps", "frames"} or (composition["width"], composition["height"], composition["fps"]) != (1080, 1920, 24):
        raise ValueError("Adu output must be 1080x1920 at 24fps")
    if (type(composition["frames"]) is not int or not 353 <= composition["frames"] <= 1440
            or abs((source["end"] - source["start"]) * 24 - composition["frames"]) > 1e-6):
        raise ValueError("Invalid 24fps composition clock")
    request = brief["template_request"]
    if (not isinstance(request, dict) or set(request) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or request["semantic_family"] != SEMANTIC_FAMILY or request["information_units"] != 3):
        raise ValueError("Adu first group requires exactly three information units")
    if (not isinstance(request["numeric_values"], list)
            or request["numeric_scale"] not in {"linear", "log", "not_applicable"}
            or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in request["numeric_values"])):
        raise ValueError("Invalid numeric request")
    files = brief["files"]
    if not isinstance(files, list) or len(files) != len(SCENE_FILES):
        raise ValueError("Freeze the seven actual Adu scene files")
    refs = set()
    paths = set()
    for item in files:
        if (not isinstance(item, dict) or set(item) != {"media_ref", "job_path", "scene_path", "sha256"}
                or not all(isinstance(item[key], str) for key in item)
                or item["media_ref"] in refs or item["scene_path"] in paths or len(item["sha256"]) != 64):
            raise ValueError("Invalid or duplicate frozen scene file")
        _relative(item["job_path"]); _relative(item["scene_path"])
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", item["media_ref"]) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ValueError("Invalid frozen file identity")
        refs.add(item["media_ref"]); paths.add(item["scene_path"])
    if (paths != SCENE_FILES or not isinstance(brief["workflow_media_ref"], str)
            or not any(item["media_ref"] == brief["workflow_media_ref"] and item["scene_path"] == "workflow.json" for item in files)):
        raise ValueError("Adu brief needs the complete browser closure and workflow record")
    return brief


def check_runtime(project_root: str | Path, dependency_id: str = DEPENDENCY_ID) -> dict:
    if dependency_id != DEPENDENCY_ID:
        raise ValueError("Unsupported dependency")
    project = Path(project_root).resolve(strict=True)
    root = project / "skill-development/vendor/adu-motion-video"
    if root.is_symlink() or not (root / ".git").exists():
        raise ValueError("Adu source must be a project-local git checkout")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True)
    if head != UPSTREAM_COMMIT or dirty:
        raise ValueError("Adu vendor commit or tracked files changed")
    node = shutil.which("node"); ffmpeg = shutil.which("ffmpeg"); ffprobe = shutil.which("ffprobe")
    browser_candidates = [shutil.which("google-chrome"), shutil.which("chromium"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    browser = next((value for value in browser_candidates if value and Path(value).is_file()), None)
    if not all((node, ffmpeg, ffprobe, browser)):
        raise ValueError("Adu requires local node, ffmpeg, ffprobe and Chrome/Chromium")
    renderer = root / "scripts/render_project.mjs"
    if not renderer.is_file():
        raise ValueError("Adu renderer is missing")
    module = root / "node_modules/playwright-core/package.json"
    if not module.is_file():
        raise ValueError("Adu Playwright Core runtime is missing")
    module_data = json.loads(module.read_text())
    if module_data.get("version") != "1.58.2":
        raise ValueError("Adu requires the pinned Playwright Core 1.58.2 runtime")
    lock = root / "package-lock.json"
    if not lock.is_file():
        raise ValueError("Adu package-lock.json is required for runtime closure")
    # Hash the complete source closure used by the reviewed macro path.  A
    # clean vendor HEAD alone is insufficient because ignored/generated files
    # can still alter browser output.
    closure = {
        "render_project.mjs": renderer,
        "chrome.mjs": root / "scripts/chrome.mjs",
        "adapt_project.py": root / "scripts/adapt_project.py",
        "semantic_inputs.py": root / "scripts/semantic_inputs.py",
        "macro_runtime.js": root / "scripts/macro_runtime.js",
        "pack_manifest.json": root / "packs/classic-performance/1.0.0/manifest.json",
        "pack_lib.js": root / "packs/classic-performance/1.0.0/lib.js",
        "pack_unit.js": root / "packs/classic-performance/1.0.0/units/decompose-and-consolidate.js",
    }
    if any(not path.is_file() for path in closure.values()):
        raise ValueError("Adu runtime source closure is incomplete")
    executable_hashes = {}
    for name, executable in (("node", node), ("ffmpeg", ffmpeg), ("ffprobe", ffprobe), ("browser", browser)):
        executable_hashes[name] = sha(Path(executable).resolve(strict=True))
    # Import the pinned local Playwright module and verify its chromium object
    # is usable; package metadata alone does not prove the runtime is callable.
    probe = subprocess.check_output([
        node, "--input-type=module", "-e",
        "const m=await import(process.argv[1]); const chromium=m.chromium||m.default?.chromium||m['module.exports']?.chromium; if (!chromium || typeof chromium.launch !== 'function') process.exit(2); console.log(chromium.executablePath ? chromium.executablePath() : '')",
        str(module.parent / "index.js"),
    ], text=True, stderr=subprocess.STDOUT).strip()
    if not probe:
        raise ValueError("Adu Playwright Chromium runtime is not importable")
    return {"root": str(root), "commit": head, "entry": str(renderer.relative_to(root)),
            "entry_sha256": sha(renderer), "node": node, "ffmpeg": ffmpeg, "ffprobe": ffprobe,
            "browser": browser, "playwright_module": str(module.parent),
            "playwright_core": module_data.get("version"), "playwright_package_sha256": sha(module),
            "package_lock_sha256": sha(lock), "closure_sha256": {name: sha(path) for name, path in closure.items()},
            "executable_hashes": executable_hashes, "playwright_browser": probe,
            "renderer_contract": "HTMLCanvas/opaque/1080x1920@24"}


def create_adapter(project_root, dependency_id, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project, dependency_id)
    launcher = Path(python_executable).resolve(strict=True)
    entry_sha = sha(SKILL / ENTRY)
    launcher_sha = sha(launcher)
    layout_identity = upstream_identity(Path(runtime["root"]))

    def check():
        if (sha(SKILL / ENTRY) != entry_sha or sha(launcher) != launcher_sha
                or check_runtime(project, dependency_id) != runtime
                or upstream_identity(Path(runtime["root"])) != layout_identity):
            raise ValueError("Adu adapter, layout or runtime closure changed")

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary
        check()
        payload = brief_loader(job, recipe, component)
        brief = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan["segments"] if s["segment_id"] == recipe["segment_id"])
        arroll = visual_canary.approved_aroll_record(job, plan)
        expected = {"aroll_sha256": arroll["sha256"], "segment_id": segment["segment_id"],
                    "start": segment["start"], "end": segment["end"]}
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or brief["source_binding"] != expected
                or brief["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or component["invocation_record"].get("production_evidence") != workflow_reference(brief)
                or component.get("template_origin") != "custom_fallback" or component.get("adaptation_level") != "structural"
                or component.get("artifact_contract") != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or component.get("source_sha256") != entry_sha
                or component.get("render_window", {}).get("start_frame") != 0
                or component.get("render_window", {}).get("end_frame") != brief["composition"]["frames"]):
            raise ValueError("Adu scene no longer matches the approved source, request or recipe")
        return payload

    def media_loader(job, recipe, component, payload):
        check()
        return tuple(ReferenceProcessMedia(media_ref=f["media_ref"], job_path=f["job_path"], sha256=f["sha256"]) for f in validate_brief(payload)["files"])

    return ReferenceProcessAdapter(adapter_id=DEPENDENCY_ID + "-scene-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="HTMLCanvas", renderer_version=runtime["commit"], artifact_media_type="video", launcher=launcher, launcher_sha256=launcher_sha, brief_loader=guarded_loader, media_loader=media_loader, self_contained_wrapper=True, timeout_seconds=300, argv_template=("{launcher}", "{entrypoint}", "--skill-root", str(SKILL), "--brief", "{brief_path}", "--media-manifest", "{media_manifest_fd}", "--runtime", base64.b64encode(json.dumps(runtime, sort_keys=True).encode()).decode(), "--output", "{output_path}"))


def workflow_reference(brief):
    item = next(f for f in brief["files"] if f["media_ref"] == brief["workflow_media_ref"])
    return {"dependency_id": DEPENDENCY_ID, "upstream_commit": UPSTREAM_COMMIT,
            "workflow_path": item["job_path"], "workflow_sha256": item["sha256"]}


def create_binding(adapter, brief_bytes, reference_sample):
    brief = validate_brief(brief_bytes)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != sha(SKILL / ENTRY):
        raise ValueError("Adu adapter identity mismatch")
    request = brief["template_request"]
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY, "producer_version": VERSION, "primary_renderer": "HTMLCanvas", "renderer_version": adapter.renderer_version, "template_origin": "custom_fallback", "template_id": DEPENDENCY_ID + "-decompose-and-consolidate-portrait", "template_version": VERSION, "verification_id": hashlib.sha256((adapter.entrypoint_sha256 + adapter.renderer_version + hashlib.sha256(brief_bytes).hexdigest()).encode()).hexdigest(), "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": adapter.entrypoint_sha256, "sample_sha256": sha(reference_sample), "semantic_families": [request["semantic_family"]], "capacity": {"min_units": 3, "max_units": 3}, "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(), "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None, "template_request": request, "production_evidence": workflow_reference(brief)}}


def validate_workflow(brief, scene: Path, root: Path):
    """Recompile the recorded inputs; arbitrary frozen HTML is not an Adu call."""
    record = json.loads((scene / "workflow.json").read_bytes())
    composition = brief["composition"]
    if (not isinstance(record, dict) or record.get("source_binding") != brief["source_binding"]
            or record.get("composition") != {key: composition[key] for key in ("frames", "width", "height", "fps")}
            or record.get("scene_id") != composition["id"]):
        raise ValueError("Adu workflow does not match the frozen source and composition")
    expected = prepare_scene(source_binding=record["source_binding"], frames=composition["frames"],
        cues=record.get("cues"), inputs=record.get("inputs"), source_text=record.get("source_text"),
        branches=record.get("branches"), result=record.get("result"), part_cues=record.get("part_cues"),
        scene_id=record["scene_id"], project_root=root.parents[2])
    expected["upstream"] = upstream_identity(root)
    if record != expected or (scene / "config.js").read_bytes() != config_bytes(expected):
        raise ValueError("Adu workflow, protected timing or native text bindings changed")
    if (scene / "index.html").read_text() != INDEX_HTML:
        raise ValueError("Adu browser entry changed")
    originals = {"scenes.js": SKILL / "assets/adu-motion-video/scene.js",
                 "style.css": SKILL / "assets/adu-motion-video/style.css",
                 "lib.js": root / "packs/classic-performance/1.0.0/lib.js",
                 "macro_runtime.js": root / "scripts/macro_runtime.js"}
    if any(sha(scene / name) != sha(original) for name, original in originals.items()):
        raise ValueError("Adu layout or original motion library changed")


def probe_video(path: Path, ffprobe: Path) -> dict:
    inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
    result = subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)], pass_fds=inherited, capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(result.stdout); streams = data.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("Adu output must be one silent video stream")
    stream = streams[0]
    if ((stream.get("width"), stream.get("height"), stream.get("sample_aspect_ratio"), stream.get("codec_name"), stream.get("pix_fmt"), Fraction(stream.get("r_frame_rate", "0/1")), Fraction(stream.get("avg_frame_rate", "0/1"))) != (1080, 1920, "1:1", "h264", "yuv420p", 24, 24) or "mp4" not in data.get("format", {}).get("format_name", "").split(",")):
        raise ValueError("Adu output dimensions, fps, codec or pixel format failed")
    return {"media_type": "video", "container": "mp4", "codec": "h264", "pixel_format": "yuv420p", "alpha": False, "width": 1080, "height": 1920, "fps": 24.0, "frame_count": int(stream.get("nb_read_frames", 0)), "duration": float(stream.get("duration", 0))}


def create_artifact_probe(ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe
    ffprobe = Path(ffprobe_executable).resolve(strict=True)
    pinned = sha(ffprobe)

    def probe(path, media_type, contract):
        if (sha(ffprobe) != pinned or media_type != "video"
                or contract != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}):
            raise ValueError("Adu artifact contract failed")
        return probe_video(path, ffprobe)

    return ArtifactProbe(probe_id="adu-motion-ffprobe", probe_version=VERSION, probe=probe)


def main():
    global SKILL
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--dependency-id", default=DEPENDENCY_ID)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--skill-root", type=Path)
    parser.add_argument("--media-manifest")
    parser.add_argument("--runtime")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.probe:
        if args.project_root is None:
            parser.error("--project-root is required with --probe")
        check_runtime(args.project_root, args.dependency_id)
        print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID,
            "entrypoint": ENTRY, "producer_version": VERSION,
            "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
                "approved_executor": "reference_adapter", "primary_renderer": "HTMLCanvas"}}, sort_keys=True))
        return 0
    if not all((args.brief, args.runtime, args.output, args.skill_root)):
        parser.error("executor mode requires --brief, --runtime, --skill-root and --output")
    # The common executor feeds the frozen wrapper over stdin and launches in
    # / with a minimal PATH. Never derive assets from <stdin> or assume a login
    # shell; use the bound source root and pinned executable directories.
    SKILL = args.skill_root.resolve(strict=True)
    if not args.media_manifest:
        parser.error("--media-manifest is required")
    brief_bytes = args.brief.read_bytes()
    brief = validate_brief(brief_bytes)
    manifest_path = str(args.media_manifest)
    if manifest_path.isdigit():
        manifest_path = f"/dev/fd/{manifest_path}"
    manifest = json.loads(Path(manifest_path).read_bytes())
    records = {item["media_ref"]: item for item in manifest.get("media", [])}
    if (manifest.get("schema_version") != "reference-process-media/v1"
            or manifest.get("brief_sha256") != hashlib.sha256(brief_bytes).hexdigest()
            or len(records) != len(manifest.get("media", []))
            or set(records) != {item["media_ref"] for item in brief["files"]}):
        raise ValueError("Frozen Adu scene media manifest mismatch")
    runtime = json.loads(base64.b64decode(args.runtime, validate=True).decode())
    runtime_root = Path(runtime["root"]).resolve(strict=True)
    os.environ["PATH"] = ":".join(dict.fromkeys(str(Path(runtime[key]).parent) for key in ("node", "ffmpeg", "ffprobe"))) + ":/usr/bin:/bin"
    if check_runtime(runtime_root.parents[2]) != runtime:
        raise ValueError("Adu runtime closure changed")
    root = Path(runtime["root"]).resolve(strict=True)
    entry = root / "scripts/render_project.mjs"
    frames = brief["composition"]["frames"]
    end = frames / 24
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="adu-scene-") as directory:
        scene = Path(directory)
        for item in brief["files"]:
            record = records[item["media_ref"]]
            if type(record.get("fd")) is not int or record["fd"] < 0:
                raise ValueError("Frozen scene descriptor required")
            data = Path(f"/dev/fd/{record['fd']}").read_bytes()
            if (hashlib.sha256(data).hexdigest() != item["sha256"]
                    or record.get("sha256") != item["sha256"]
                    or len(data) != record.get("byte_length")):
                raise ValueError("Frozen Adu scene file changed")
            target = scene / item["scene_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        index = scene / "index.html"
        if not index.is_file():
            raise SystemExit("Adu frozen scene index.html is missing")
        validate_workflow(brief, scene, root)
        native = scene / "native.mp4"
        command = [runtime["node"], str(entry), str(index), "--output", str(native),
                   "--fps", "24", "--width", "1080", "--height", "1920", "--start", "0",
                   "--end", f"{end:.9f}", "--playwright-module", runtime["playwright_module"],
                   "--browser", runtime["browser"]]
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=240)
        data = json.loads(subprocess.check_output([runtime["ffprobe"], "-v", "error", "-count_frames",
            "-show_streams", "-of", "json", str(native)], text=True))
        streams = data["streams"]
        if (len(streams) != 1 or streams[0]["codec_type"] != "video"
                or streams[0]["codec_name"] != "h264" or streams[0]["pix_fmt"] not in {"yuv420p", "yuvj420p"}
                or (streams[0]["width"], streams[0]["height"]) != (1080, 1920)
                or Fraction(streams[0]["avg_frame_rate"]) != 24
                or int(streams[0]["nb_read_frames"]) != frames):
            raise ValueError("Native Adu output does not match the frozen artifact clock")
        # Reuse the established native-result normalization: no resize, no
        # retiming and no new motion. Copy pixels unless real range conversion
        # is needed, and set square pixels explicitly.
        normalized = scene / "artifact.mp4"
        normalization = ["-c", "copy", "-aspect", "9:16", "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1"]
        if streams[0].get("color_range") == "pc":
            normalization = ["-vf", "scale=in_range=pc:out_range=tv,setsar=1", "-c:v", "libx264",
                "-crf", "16", "-pix_fmt", "yuv420p", "-color_range", "tv"]
        elif streams[0]["pix_fmt"] != "yuv420p":
            raise ValueError("Unsupported native Adu color range")
        subprocess.run([runtime["ffmpeg"], "-v", "error", "-i", str(native), *normalization,
            str(normalized)], check=True, timeout=30)
        measured = probe_video(normalized, Path(runtime["ffprobe"]))
        if measured["frame_count"] != frames or abs(measured["duration"] - end) > 1e-5:
            raise ValueError("Normalized Adu output clock changed")
        args.output.write_bytes(normalized.read_bytes())
    if not args.output.is_file():
        raise ValueError("Adu renderer did not produce an output")
    print(json.dumps({"status": "rendered", "dependency_id": DEPENDENCY_ID,
        "upstream_commit": UPSTREAM_COMMIT, "native_entry_sha256": runtime["entry_sha256"],
        "native_argv": command, "frames": frames, "production_evidence": workflow_reference(brief),
        "native_log": (result.stdout + result.stderr)[-4000:]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

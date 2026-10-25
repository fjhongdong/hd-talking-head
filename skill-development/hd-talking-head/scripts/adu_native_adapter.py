"""Call Adu's unmodified TPL.compare; the parent only places its whole board."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from adapter_kit import browser_candidates, identity_from_bytes, sha256_file as sha, validate_source_binding

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_adu_native.mjs"
DEPENDENCY_ID = "adu-motion-video"
VERSION = "2.3.0"
TEMPLATE_ID = "adu-motion-video/native-compare"
FAMILY = "old_new_comparison"
SOURCE_PIN = "4a52ae2cff542cfb0bfcf6e93e5120c55d0110cf"
FFMPEG_DIR = "skill-development/runtime/ffmpeg-9.0.2/bin"




def _text(value, label, limit):
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or c in "<>" for c in value)):
        raise ValueError(f"Invalid Adu {label}")


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    fields = {"schema_version", "source_binding", "template_request", "composition",
              "title", "left", "right", "left_frame", "right_frame", "strike_frame", "stamp"}
    if type(b) is not dict or set(b) != fields | {"typography"} or b["schema_version"] != 1:
        raise ValueError("Invalid Adu native brief")
    typography = b["typography"]
    if (type(typography) is not dict or set(typography) != {"title_px", "body_px"}
            or any(type(typography[k]) not in (int, float) or not 20 <= typography[k] <= 80
                   for k in ("title_px", "body_px"))):
        raise ValueError("Invalid Adu typography")
    if typography["title_px"] < typography["body_px"]:
        raise ValueError("Adu title typography must be at least body typography")
    s, c, r = b["source_binding"], b["composition"], b["template_request"]
    validate_source_binding(s, "Invalid Adu source binding")
    if (type(c) is not dict or set(c) != {"id", "width", "height", "fps", "frames"}
            or not re.fullmatch(r"[A-Za-z0-9_-]+", str(c["id"]))
            or any(type(c[k]) is not int or c[k] != v for k, v in (("width", 1080), ("height", 1920), ("fps", 24)))
            or type(c["frames"]) is not int or not 120 <= c["frames"] <= 240
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Invalid Adu composition clock")
    if (type(r) is not dict or set(r) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or r["semantic_family"] != FAMILY or type(r["information_units"]) is not int
            or not 2 <= r["information_units"] <= 6 or r["numeric_values"] != []
            or r["numeric_scale"] != "not_applicable"):
        raise ValueError("Invalid Adu template request")
    _text(b["title"], "title", 14)
    _text(b["stamp"], "stamp", 4)
    for name in ("left", "right"):
        side = b[name]
        if type(side) is not dict or set(side) != {"title", "items"}:
            raise ValueError("Invalid Adu comparison side")
        _text(side["title"], "side title", 8)
        if type(side["items"]) is not list or not 1 <= len(side["items"]) <= 3:
            raise ValueError("Adu compare supports 1-3 items per side")
        for item in side["items"]:
            _text(item, "item", 14)
    available_width = (760 - 2 * 44) * 0.5625
    if any(len(b[name]["title"]) * typography["title_px"] > available_width
           for name in ("left", "right")):
        raise ValueError("Adu typography title capacity exceeded")
    body_width = available_width - 2 * typography["body_px"]
    if any(len(item) * typography["body_px"] > body_width
           for name in ("left", "right") for item in b[name]["items"]):
        raise ValueError("Adu typography body capacity exceeded")
    if sum(len(b[n]["items"]) for n in ("left", "right")) != r["information_units"]:
        raise ValueError("Adu item count differs from the request")
    if typography["body_px"] > 90 * 0.5625 and any(
        len(b[name]["items"]) > 1 for name in ("left", "right")
    ):
        raise ValueError("Adu typography body line capacity exceeded")
    frames = [b[k] for k in ("left_frame", "right_frame", "strike_frame")]
    # Stamp timing belongs to TPL.compare: strikeAt + .35, then a .55s native entrance.
    if (any(type(v) is not int or v < 0 for v in frames) or frames != sorted(frames)
            or frames[-1] + 36 >= c["frames"]):
        raise ValueError("Adu native actions do not fit the voice window")
    # Values are final portrait pixels; the static host converts them to board
    # pixels after the upstream 1920x1080 board is scaled to 1080x1920.
    return b


def check_runtime(project_root):
    project = Path(project_root).resolve(strict=True)
    source = project / "skill-development/vendor/adu-motion-video"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if head != SOURCE_PIN:
        raise ValueError("Adu source revision changed")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "template", "scripts/render_project.mjs", "scripts/chrome.mjs", "scripts/color_management.py", "scripts/output-signature.mjs"],
                   cwd=source, check=True, stdout=subprocess.DEVNULL)
    browser = next((p for p in browser_candidates(project) if p.is_file() and os.access(p, os.X_OK)), project / ".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell")
    if not browser.is_file() or not os.access(browser, os.X_OK):
        raise ValueError("Project render browser unavailable")
    ffmpeg_dir = project / FFMPEG_DIR
    ffmpeg, ffprobe = ffmpeg_dir / "ffmpeg", ffmpeg_dir / "ffprobe"
    if not ffmpeg.is_file() or not os.access(ffmpeg, os.X_OK):
        raise ValueError(f"Adu requires project-local FFmpeg 9.0.2: {ffmpeg}")
    if not ffprobe.is_file() or not os.access(ffprobe, os.X_OK):
        raise ValueError(f"Adu requires project-local ffprobe paired with FFmpeg 9.0.2: {ffprobe}")
    python = Path(sys.executable).resolve(strict=True)
    color_env = {**os.environ, "PATH": f"{ffmpeg_dir}:{os.environ.get('PATH', '')}"}
    subprocess.run([str(python), str(source / "scripts/color_management.py"), "--export-plan"],
                   cwd=source, env=color_env, check=True, stdout=subprocess.DEVNULL)
    runtime = project / "skill-development/runtime/adu-native"
    module = runtime / "node_modules/playwright-core"
    if json.loads((module / "package.json").read_bytes())["version"] != "1.64.0":
        raise ValueError("Adu native bridge requires Playwright 1.64.0 in our own runtime")
    for name in ("package.json", "package-lock.json"):
        if (runtime / name).read_bytes() != (SKILL / "assets/adu-native-runtime" / name).read_bytes():
            raise ValueError("Adu dependency configuration changed")
    files = [f for f in sorted((source / "template").rglob("*")) if f.is_file()]
    geometry = SKILL / "scripts/adu_text_geometry.mjs"
    files += [source / "scripts/render_project.mjs", source / "scripts/chrome.mjs", source / "scripts/color_management.py", source / "scripts/output-signature.mjs", runtime / "package-lock.json", module / "package.json", browser, ffmpeg, ffprobe, python, geometry]
    identity = identity_from_bytes(files)
    return {"source": str(source), "browser": str(browser), "playwright": str(module), "ffmpeg": str(ffmpeg), "ffprobe": str(ffprobe), "python": str(python), "geometry": str(geometry), "geometry_sha256": sha(geometry), "identity": identity}


def prepare_runtime(project_root):
    project = Path(project_root).resolve(strict=True)
    runtime = project / "skill-development/runtime/adu-native"
    if runtime.is_symlink() or not runtime.resolve().is_relative_to(project):
        raise ValueError("Adu runtime must stay inside this project")
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        source, target = SKILL / "assets/adu-native-runtime" / name, runtime / name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError("Existing Adu dependency configuration differs")
        if not target.exists():
            shutil.copyfile(source, target)
    if not (runtime / "node_modules/playwright-core/package.json").is_file():
        subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=runtime, check=True, timeout=240)
    return check_runtime(project)


def create_adapter(project_root, node_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter
    project = Path(project_root).resolve(strict=True)
    node = Path(node_executable).resolve(strict=True)
    runtime = check_runtime(project)
    entry_sha, node_sha = sha(SKILL / ENTRY), sha(node)

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if sha(SKILL / ENTRY) != entry_sha or sha(node) != node_sha or check_runtime(project) != runtime:
            raise ValueError("Adu implementation or runtime changed")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        ar = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or b["source_binding"] != {"aroll_sha256": ar["sha256"], "segment_id": segment["segment_id"], "start": segment["start"], "end": segment["end"]}):
            raise ValueError("Adu approved source binding changed")
        if (component.get("template_id") != TEMPLATE_ID or component.get("template_origin") != "custom_fallback"
                or component.get("adaptation_level") != "structural" or component.get("source_sha256") != entry_sha
                or component.get("artifact_contract") != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or component["render_window"].get("start_frame") != 0
                or component["render_window"].get("end_frame") != b["composition"]["frames"]):
            raise ValueError("Adu component contract changed")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="adu-native-compare-v2", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="HTMLCanvas",
        renderer_version=VERSION, artifact_media_type="video", launcher=node, launcher_sha256=node_sha,
        brief_loader=guard, media_loader=None, self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--source", runtime["source"],
                       "--browser", runtime["browser"], "--playwright-module", runtime["playwright"], "--ffmpeg", runtime["ffmpeg"], "--ffprobe", runtime["ffprobe"], "--python", runtime["python"],
                       "--geometry-module", runtime["geometry"], "--geometry-sha256", runtime["geometry_sha256"], "--output", "{output_path}"))


def create_existing_adapter(project_root, node_executable, brief_loader, *, completed_record):
    from native_completed_artifact import attach_completed
    return attach_completed(create_adapter(project_root, node_executable, brief_loader), validate_brief,
                            completed_record=completed_record)


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    entry_sha = sha(SKILL / ENTRY)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != entry_sha:
        raise ValueError("Adu adapter identity changed")
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
            "producer_version": VERSION, "primary_renderer": "HTMLCanvas", "renderer_version": VERSION,
            "template_origin": "custom_fallback", "template_id": TEMPLATE_ID, "template_version": VERSION,
            "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": entry_sha,
            "sample_sha256": sha(reference_sample), "semantic_families": [FAMILY], "capacity": {"min_units": 2, "max_units": 6},
            "brief_sha256": digest, "verification_id": hashlib.sha256((entry_sha + digest).encode()).hexdigest(),
            "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None, "template_request": b["template_request"]}}


def create_artifact_probe(ffprobe_executable):
    from whiteboard_adapter import create_artifact_probe
    return create_artifact_probe(ffprobe_executable)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    check_runtime(args.project_root)
    print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
                      "producer_version": VERSION, "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
                      "approved_executor": "reference_adapter", "primary_renderer": "HTMLCanvas"}}))

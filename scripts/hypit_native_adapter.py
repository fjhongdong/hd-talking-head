"""Thin binding for Hypit's native chat scene, restricted to changed-plan dialogue."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_hypit_native.mjs"
DEPENDENCY_ID = "hypit-native-chat"
VERSION = "1.0.0"
TEMPLATE_ID = "hypit/native-plan-change-chat"
FAMILY = "plan_change_dialogue"
SOURCE_PIN = "85e01c76716498e6ec5b8bdfb6b374ca67f0195a"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text(value, label, limit):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid Hypit {label}")


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    if type(b) is not dict or set(b) != {"schema_version", "source_binding", "template_request", "composition", "title", "messages"} or b["schema_version"] != 1:
        raise ValueError("Invalid Hypit native brief")
    s, c, r = b["source_binding"], b["composition"], b["template_request"]
    if (type(s) is not dict or set(s) != {"aroll_sha256", "segment_id", "start", "end"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(s["aroll_sha256"]))
            or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", str(s["segment_id"]))
            or any(type(s[k]) not in (int, float) or not math.isfinite(s[k]) for k in ("start", "end"))
            or not 0 <= s["start"] < s["end"]):
        raise ValueError("Invalid Hypit source binding")
    if (type(c) is not dict or set(c) != {"id", "width", "height", "fps", "frames"}
            or not re.fullmatch(r"[A-Za-z0-9_-]+", str(c["id"]))
            or any(type(c[k]) is not int or c[k] != v for k, v in (("width", 1080), ("height", 1920), ("fps", 24)))
            or type(c["frames"]) is not int or not 120 <= c["frames"] <= 240
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Invalid Hypit composition clock")
    if (type(r) is not dict or set(r) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or r["semantic_family"] != FAMILY or type(r["information_units"]) is not int
            or not 2 <= r["information_units"] <= 4 or r["numeric_values"] != []
            or r["numeric_scale"] != "not_applicable"):
        raise ValueError("Invalid Hypit template request")
    _text(b["title"], "title", 14)
    messages = b["messages"]
    if type(messages) is not list or len(messages) != r["information_units"]:
        raise ValueError("Hypit requires 2-4 messages")
    frames = []
    for m in messages:
        if type(m) is not dict or set(m) != {"sender", "text", "side", "frame"}:
            raise ValueError("Invalid Hypit message")
        _text(m["sender"], "sender", 6)
        _text(m["text"], "message", 28)
        if m["side"] not in ("left", "right") or type(m["frame"]) is not int:
            raise ValueError("Invalid Hypit message side/frame")
        frames.append(m["frame"])
    if frames != sorted(set(frames)) or frames[0] < 0 or frames[-1] + 24 >= c["frames"]:
        raise ValueError("Hypit native arrivals do not fit the voice window")
    return b


def check_runtime(project_root):
    project = Path(project_root).resolve(strict=True)
    source = project / "skill-development/research/hypit-source"
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() != SOURCE_PIN:
        raise ValueError("Hypit source revision changed")
    if json.loads((source / "package.json").read_bytes())["version"] != "0.3.1":
        raise ValueError("Hypit requires the pinned 0.3.1 distribution")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "packages", "bin", "examples/semantic-composition/packages/chat-scene"],
                   cwd=source, check=True, stdout=subprocess.DEVNULL)
    native = source / "examples/semantic-composition/packages/chat-scene"
    browser = project / ".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not browser.is_file() or not os.access(browser, os.X_OK) or not ffmpeg or not ffprobe:
        raise ValueError("Hypit local render tools unavailable")
    files = [source / "pnpm-lock.yaml", source / "bin/hypit.mjs", native / "package.json",
             source / "node_modules/@fontsource-variable/noto-sans-sc/package.json", browser]
    files += [f for f in sorted((native / "dist").rglob("*")) if f.is_file()]
    if not (native / "dist/activation.js").is_file():
        raise ValueError("Hypit native chat package has not been built")
    files += [f for f in sorted((SKILL / "assets/hypit-native-layout").rglob("*")) if f.is_file()]
    identity = hashlib.sha256(b"\0".join(f.read_bytes() for f in files)).hexdigest()
    return {"source": str(source), "browser": str(browser), "ffmpeg": ffmpeg, "ffprobe": ffprobe, "identity": identity}


def prepare_runtime(project_root):
    runtime = Path(project_root).resolve(strict=True) / "skill-development/research/hypit-source"
    pnpm = shutil.which("pnpm")
    node = shutil.which("node")
    if not pnpm or not node:
        raise ValueError("Hypit requires Node >=22.15 and pnpm 10.33.0")
    if subprocess.check_output([pnpm, "--version"], text=True).strip() != "10.33.0":
        raise ValueError("Hypit requires pnpm 10.33.0")
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v").split(".")
    if tuple(map(int, version[:2])) < (22, 15):
        raise ValueError("Hypit requires Node >=22.15")
    if not (runtime / "node_modules/tsx").exists():
        subprocess.run([pnpm, "install", "--filter", "@hypit/hypit...", "--filter", "@example/chat-scene...",
                        "--filter", "@hypit/fontsource...", "--frozen-lockfile", "--ignore-scripts"],
                       cwd=runtime, env={**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "true"}, check=True, timeout=240)
    if not (runtime / "examples/semantic-composition/packages/chat-scene/dist/activation.js").is_file():
        subprocess.run([pnpm, "build:public-types"], cwd=runtime, check=True, timeout=180)
        subprocess.run([pnpm, "--filter", "@example/chat-scene", "build"], cwd=runtime, check=True, timeout=180)
    return check_runtime(project_root)


def create_adapter(project_root, node_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter
    project = Path(project_root).resolve(strict=True)
    node = Path(node_executable).resolve(strict=True)
    runtime = check_runtime(project)
    entry_sha, node_sha = sha(SKILL / ENTRY), sha(node)

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if sha(SKILL / ENTRY) != entry_sha or sha(node) != node_sha or check_runtime(project) != runtime:
            raise ValueError("Hypit implementation or runtime changed")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        ar = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or b["source_binding"] != {"aroll_sha256": ar["sha256"], "segment_id": segment["segment_id"], "start": segment["start"], "end": segment["end"]}):
            raise ValueError("Hypit approved source binding changed")
        if (component.get("template_id") != TEMPLATE_ID or component.get("template_origin") != "custom_fallback"
                or component.get("adaptation_level") != "structural" or component.get("source_sha256") != entry_sha
                or component.get("artifact_contract") != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or component["render_window"].get("start_frame") != 0
                or component["render_window"].get("end_frame") != b["composition"]["frames"]):
            raise ValueError("Hypit component contract changed")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="hypit-native-chat-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter",
        dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION,
        primary_renderer="HTMLCanvas", renderer_version=VERSION, artifact_media_type="video",
        launcher=node, launcher_sha256=node_sha, brief_loader=guard, media_loader=None,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--source", runtime["source"],
                       "--layout-root", str(SKILL / "assets/hypit-native-layout"), "--browser", runtime["browser"],
                       "--ffmpeg", runtime["ffmpeg"], "--ffprobe", runtime["ffprobe"], "--output", "{output_path}"))


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    entry_sha = sha(SKILL / ENTRY)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != entry_sha:
        raise ValueError("Hypit adapter identity changed")
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
            "producer_version": VERSION, "primary_renderer": "HTMLCanvas", "renderer_version": VERSION,
            "template_origin": "custom_fallback", "template_id": TEMPLATE_ID, "template_version": VERSION,
            "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": entry_sha,
            "sample_sha256": sha(reference_sample), "semantic_families": [FAMILY], "capacity": {"min_units": 2, "max_units": 4},
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
    print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY, "producer_version": VERSION,
                      "adapter_identity": {"adapter_type": "ReferenceProcessAdapter", "approved_executor": "reference_adapter", "primary_renderer": "HTMLCanvas"}}))

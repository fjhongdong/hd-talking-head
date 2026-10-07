"""Bind reviewed Doudou scene code to the existing component executor."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_doudou.mjs"
DEPENDENCY_ID = "doudou-remotion-whiteboard"
VERSION = "2.0.0"
COMMIT = "d41f61c889c315b2a590fee61db3a62cf003adc9"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_brief(payload):
    b = json.loads(payload)
    if (type(b) is not dict or set(b) != {"schema_version", "source_binding", "template_request", "entry", "hand", "composition"}
            or b["schema_version"] != 2):
        raise ValueError("Invalid Doudou brief")
    source = b["source_binding"]
    if (set(source) != {"aroll_sha256", "segment_id", "start", "end"}
            or not re.fullmatch(r"[a-f0-9]{64}", source["aroll_sha256"])
            or not re.fullmatch(r"seg-[a-zA-Z0-9_-]+", source["segment_id"])
            or any(type(source[k]) not in (int, float) or not math.isfinite(source[k]) for k in ("start", "end"))
            or not 0 <= source["start"] < source["end"]):
        raise ValueError("Invalid Doudou source window")
    c = b["composition"]
    if (set(c) != {"id", "width", "height", "fps", "frames"}
            or not re.fullmatch(r"[a-zA-Z0-9_-]+", c["id"])
            or (c["width"], c["height"], c["fps"]) != (1080, 1920, 24)
            or type(c["frames"]) is not int or not 1 <= c["frames"] <= 1440
            or abs((source["end"] - source["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Invalid Doudou composition clock")
    entry = b["entry"]
    p = Path(entry["job_path"])
    if (set(entry) != {"job_path", "sha256"} or p.is_absolute() or ".." in p.parts
            or p.as_posix() != entry["job_path"] or p.suffix != ".tsx"
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])):
        raise ValueError("Doudou entry must be a frozen Job-relative TSX")
    hand = b["hand"]
    hp = Path(hand.get("job_path", "")) if type(hand) is dict else Path("")
    if (type(hand) is not dict or set(hand) != {"job_path", "sha256", "width", "height", "tip_x", "tip_y"}
            or hp.is_absolute() or ".." in hp.parts
            or hp.as_posix() != hand["job_path"] or hp.suffix != ".png"
            or not re.fullmatch(r"[a-f0-9]{64}", hand["sha256"])
            or type(hand["width"]) is not int or type(hand["height"]) is not int
            or not 1 <= hand["width"] <= 4096 or not 1 <= hand["height"] <= 4096
            or type(hand["tip_x"]) is bool or type(hand["tip_y"]) is bool
            or not isinstance(hand["tip_x"], (int, float)) or not isinstance(hand["tip_y"], (int, float))
            or not math.isfinite(hand["tip_x"]) or not math.isfinite(hand["tip_y"])
            or not 0 <= hand["tip_x"] < hand["width"] or not 0 <= hand["tip_y"] < hand["height"]):
        raise ValueError("Doudou hand must be a frozen Job-relative RGBA PNG")
    request = b["template_request"]
    if (set(request) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or type(request["semantic_family"]) is not str or not request["semantic_family"]
            or type(request["information_units"]) is not int or request["information_units"] < 1
            or request["numeric_values"] != [] or request["numeric_scale"] != "not_applicable"):
        raise ValueError("Doudou route supports nonquantitative diagrams only")
    return b


def check_runtime(project):
    source = project / "skill-development/vendor/doudou-remotion-whiteboard"
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    if commit != COMMIT or dirty:
        raise ValueError("Doudou upstream source changed")
    runtime = project / "edit/hd/integrations/talkcraft/runtime"
    package = runtime / "node_modules/@remotion/renderer/package.json"
    if json.loads(package.read_bytes())["version"] != "4.0.520":
        raise ValueError("Doudou Remotion runtime changed")
    browser = project / ".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    if not browser.is_file() or not os.access(browser, os.X_OK):
        raise ValueError("Doudou project render browser is unavailable")
    return {"commit": commit, "renderer_package_sha256": sha(package), "browser_sha256": sha(browser)}


def create_adapter(project_root, node_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    node = Path(node_executable).resolve(strict=True)
    if not node.is_file() or not os.access(node, os.X_OK):
        raise ValueError("Doudou Node executable is unavailable")
    runtime = check_runtime(project)
    entry_sha, node_sha = sha(SKILL / ENTRY), sha(node)

    def check():
        if sha(SKILL / ENTRY) != entry_sha or sha(node) != node_sha or check_runtime(project) != runtime:
            raise ValueError("Doudou bound runtime identity changed")

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
        window = component["render_window"]
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"] or brief["source_binding"] != expected
                or brief["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or component["source_sha256"] != entry_sha or component["template_origin"] != "custom_fallback"
                or component["artifact_contract"] != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or window["start_frame"] != 0 or window["end_frame"] != brief["composition"]["frames"]):
            raise ValueError("Doudou approved recipe, request or source clock changed")
        return payload

    def media_loader(job, recipe, component, payload):
        check()
        brief = validate_brief(payload)
        return tuple(ReferenceProcessMedia(media_ref=key, job_path=brief[key]["job_path"], sha256=brief[key]["sha256"])
                     for key in ("entry", "hand"))

    return ReferenceProcessAdapter(adapter_id="doudou-remotion-v2", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="Remotion",
        renderer_version="4.0.520", artifact_media_type="video", launcher=node, launcher_sha256=node_sha,
        brief_loader=guarded_loader, media_loader=media_loader, self_contained_wrapper=True,
        timeout_seconds=300, argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
            "--media-manifest", "{media_manifest_fd}", "--project-root", str(project), "--output", "{output_path}"))


def create_binding(adapter, brief_bytes, reference_sample):
    brief = validate_brief(brief_bytes)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != sha(SKILL / ENTRY):
        raise ValueError("Doudou adapter identity mismatch")
    request = brief["template_request"]
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
        "producer_version": VERSION, "primary_renderer": "Remotion", "renderer_version": "4.0.520",
        "template_origin": "custom_fallback", "template_id": "doudou-reviewed-scene", "template_version": VERSION,
        "verification_id": hashlib.sha256((adapter.entrypoint_sha256 + COMMIT + brief["entry"]["sha256"] +
                                            json.dumps(brief["hand"], sort_keys=True, separators=(",", ":"))).encode()).hexdigest(),
        "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": adapter.entrypoint_sha256,
        "sample_sha256": sha(reference_sample), "semantic_families": [request["semantic_family"]],
        "capacity": {"min_units": request["information_units"], "max_units": request["information_units"]},
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None,
                              "template_request": request}}


def create_artifact_probe(ffprobe_executable):
    # The existing opaque portrait probe checks actual media, not engine identity.
    from whiteboard_adapter import create_artifact_probe as silent_portrait_probe
    return silent_portrait_probe(ffprobe_executable)


if __name__ == "__main__":
    import argparse
    import shutil
    import sys
    parser = argparse.ArgumentParser(description="Read-only Doudou binding probe; no render or external requests")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root))
    adapter = create_adapter(args.project_root, shutil.which("node"), lambda *_: b"")
    print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
        "producer_version": VERSION, "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
        "approved_executor": adapter.approved_executor, "primary_renderer": adapter.primary_renderer}}))

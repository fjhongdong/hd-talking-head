#!/usr/bin/env python3
"""Validate briefs and bind job-authored disciplined motion graphics (hyperframes/1)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and Path(__file__).name == "<stdin>":
    _parser = argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--skill-root", required=True, type=Path)
    SKILL = _parser.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from adapter_kit import sha256_file as sha  # noqa: E402

ENTRY = "scripts/render_motion_graphics.cjs"
DEPENDENCY_ID = "motion-graphics-native"
VERSION = "1.0.0"
FAMILIES = ("lower_third", "callout_pin", "logo_sting")
FAMILY_SLOTS = {
    "lower_third": (("name", 8), ("role", 12), ("org", 12)),
    "callout_pin": (("target_desc", 24), ("label", 10), ("direction", 5)),
    "logo_sting": (("mark_text", 6), ("headline", 14), ("cta", 10)),
}
OPTIONAL_SLOTS = {"org", "headline", "cta"}
FPS = 24
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SEGMENT = re.compile(r"seg-[A-Za-z0-9_-]+")


def _text(value, label, limit):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid {label} slot (max {limit} chars)")
    return value


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    required = {"schema_version", "source_binding", "template_request",
                "composition", "entry", "assets", "data"}
    if type(b) is not dict or set(b) != required or b["schema_version"] != 1:
        raise ValueError("Invalid motion graphics brief")
    s, c, r = b["source_binding"], b["composition"], b["template_request"]
    from adapter_kit import validate_source_binding
    validate_source_binding(s, "Invalid motion graphics source binding")
    family = r.get("semantic_family")
    if family not in FAMILIES:
        raise ValueError("Invalid motion graphics family")
    if (type(r.get("information_units")) is not int or not 1 <= r["information_units"] <= 6
            or r.get("numeric_values") != [] or r.get("numeric_scale") != "not_applicable"):
        raise ValueError("Invalid motion graphics template request")
    if (type(c) is not dict or set(c) != {"id", "width", "height", "fps", "frames", "alpha"}
            or not re.fullmatch(r"[A-Za-z0-9_-]+", str(c.get("id", "")))
            or (c.get("width"), c.get("height"), c.get("fps")) != (1080, 1920, FPS)
            or c.get("alpha") is not True
            or type(c.get("frames")) is not int or not 24 <= c["frames"] <= 240
            or abs((s["end"] - s["start"]) * FPS - c["frames"]) > 1e-6):
        raise ValueError("Invalid motion graphics composition clock")
    entry = b["entry"]
    ep = Path(str(entry.get("job_path", "")))
    if (set(entry) != {"job_path", "sha256"} or ep.is_absolute() or ".." in ep.parts
            or ep.as_posix() != entry["job_path"] or ep.suffix != ".html"
            or not _HEX64.fullmatch(str(entry["sha256"]))):
        raise ValueError("Motion graphics entry must be a frozen Job-relative HTML")
    if type(b["assets"]) is not list or b["assets"]:
        raise ValueError("Motion graphics assets must be empty")
    d = b["data"]
    if type(d) is not dict:
        raise ValueError("Invalid motion graphics data slots")
    expected = {name for name, _ in FAMILY_SLOTS[family]}
    if set(d) != expected:
        raise ValueError(f"Motion graphics data slots must be {sorted(expected)}")
    for name, limit in FAMILY_SLOTS[family]:
        if name in OPTIONAL_SLOTS and d[name] == "":
            continue
        _text(d[name], name, limit)
    if family == "callout_pin" and d["direction"] not in ("up", "down", "left", "right"):
        raise ValueError("Invalid callout direction")
    return b


def check_runtime(project_root):
    project = Path(project_root).resolve(strict=True)
    from hyperframes_runtime import resolve_runtime, resolve_tools
    runtime = resolve_runtime(project / "skill-development/runtime/hyperframes-0.8.167")
    tools, _ = resolve_tools()
    cli, node = runtime["cli"], tools["node"]
    return {"cli": str(cli), "node": str(node),
            "identity": hashlib.sha256(b"\0".join([sha(cli).encode(), sha(node).encode()])).hexdigest()}


def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project_root)
    entry_sha = sha(SKILL / ENTRY)
    py = Path(python_executable).resolve()

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if check_runtime(project)["identity"] != runtime["identity"] or sha(SKILL / ENTRY) != entry_sha:
            raise ValueError("Motion graphics runtime changed")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        seg = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        expected = {"aroll_sha256": plan["edited_aroll_sha256"], "segment_id": seg["segment_id"],
                    "start": seg["start"], "end": seg["end"]}
        if (json.loads(json.dumps(recipe)) != seg["shot_recipe"]
                or recipe["composition"]["family"] != "aroll_with_overlay"
                or component["layer_role"] != "annotation"
                or component["artifact_contract"] != {"width": 1080, "height": 1920, "fps": 24, "alpha": True}
                or component["render_window"]["start_frame"] != 0
                or component["render_window"]["end_frame"] != b["composition"]["frames"]
                or component["source_sha256"] != entry_sha
                or json.loads(json.dumps(component["invocation_record"]["template_request"])) != b["template_request"]
                or b["source_binding"] != expected):
            raise ValueError("Motion graphics brief no longer matches the approved shot")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="motion-graphics-native-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL,
        entrypoint=ENTRY, entrypoint_sha256=entry_sha,
        producer_version=VERSION, primary_renderer="HyperFrames",
        renderer_version="0.8.167", artifact_media_type="video",
        launcher=py, launcher_sha256=sha(py), brief_loader=guard,
        timeout_seconds=300,
        argv_template=(str(py), ENTRY, "--skill-root", str(SKILL),
                       "--project-root", str(project), "--brief", "{brief_path}",
                       "--media-manifest", "{media_manifest_fd}",
                       "--output", "{output_path}"))


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint != ENTRY
            or adapter.primary_renderer != "HyperFrames"):
        raise ValueError("Motion graphics adapter identity changed")
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID,
            "entrypoint": ENTRY, "producer_version": VERSION,
            "primary_renderer": "HyperFrames", "renderer_version": "0.8.167",
            "template_origin": "custom_fallback",
            "template_id": f"{DEPENDENCY_ID}/{b['template_request']['semantic_family']}",
            "template_version": VERSION, "adaptation_level": "structural",
            "source_entrypoint": ENTRY, "source_sha256": adapter.entrypoint_sha256,
            "sample_sha256": sha(Path(reference_sample)),
            "semantic_families": [b["template_request"]["semantic_family"]],
            "capacity": {"min_units": b["template_request"]["information_units"],
                         "max_units": b["template_request"]["information_units"]},
            "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
            "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned",
                                  "exit_code": None, "template_request": b["template_request"]}}


def create_artifact_probe(ffprobe_executable):
    from whiteboard_adapter import create_artifact_probe as opaque_probe
    return opaque_probe(ffprobe_executable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        rt = check_runtime(args.project_root)
        print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID,
                          "entrypoint": ENTRY, "producer_version": VERSION,
                          "runtime_identity": rt["identity"],
                          "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
                                               "approved_executor": "reference_adapter",
                                               "primary_renderer": "HyperFrames"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

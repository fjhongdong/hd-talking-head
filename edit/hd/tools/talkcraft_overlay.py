"""Source-bound adapter for TalkCraft primitives with the approved A-roll layout.

This is a custom layout, not one of TalkCraft's qualified full-screen cards.
The existing component executor owns process isolation and artifact publication.
"""
from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
import subprocess

from . import broll_component_executor as executor, contract_artifacts

ROOT = Path(__file__).resolve().parents[3]
ENTRY = "edit/hd/integrations/talkcraft/aroll-overlay/render.mjs"
ADAPTER = ROOT / Path(ENTRY).parent
DEPENDENCY_ID = "hd-talking-head-talkcraft-overlay"
VERSION = "2.0.0"
UPSTREAM = {
    "schematic.tsx": "0d272d9a1eaa593a26510590127fc1e6c3d8a96b09adaa1cd78d7278d869f34d",
    "icons.ts": "2035a3d7870774d112913053cd7a3e7b7ea0c4f46b3ab284009822218e1edb78",
}


def source_identity() -> str:
    files = sorted(path for path in ADAPTER.iterdir() if path.suffix in {".ts", ".tsx", ".mjs"})
    files.extend(ADAPTER / name for name in ("package.json", "package-lock.json"))
    for name, digest in UPSTREAM.items():
        path = ADAPTER.parent / "upstream/template/motion-systems" / name
        if contract_artifacts.sha256_file(path) != digest:
            raise ValueError("TalkCraft schematic upstream changed")
        files.append(path)
    files.extend(ADAPTER.parent / "runtime" / name for name in ("package.json", "package-lock.json"))
    return contract_artifacts.sha256_json({
        path.relative_to(ROOT).as_posix(): contract_artifacts.sha256_file(path)
        for path in sorted(files)
    })


def _brief(payload: bytes) -> dict:
    value = json.loads(payload)
    if type(value) is not dict or set(value) != {"schema_version", "renderer_input", "source_binding"} or value["schema_version"] != 1:
        raise ValueError("A-roll overlay brief is invalid")
    return value


def validate_source_binding(job, recipe, component, payload: bytes) -> None:
    """Resolve the current approved plan and media, never trust self-described time."""
    from . import visual_canary

    value = _brief(payload)
    plan = visual_canary.load_approved_visual_plan(job)
    matches = [item for item in plan["segments"] if item["segment_id"] == recipe["segment_id"]]
    if len(matches) != 1 or matches[0]["shot_recipe"] != json.loads(json.dumps(recipe)):
        raise ValueError("overlay recipe is not the approved segment")
    segment = matches[0]
    arroll = visual_canary.approved_aroll_record(job, plan)
    expected = {"aroll_sha256": arroll["sha256"], "segment_id": segment["segment_id"],
                "start": segment["start"], "end": segment["end"]}
    window = component["render_window"]
    canvas = value["renderer_input"]["canvas"]
    if (value["source_binding"] != expected
            or canvas != {**recipe["canvas"], "frames": window["end_frame"] - window["start_frame"]}
            or window["start_frame"] != 0
            or window["end_frame"] != round((segment["end"] - segment["start"]) * 24)
            or recipe["composition"]["family"] != "aroll_with_overlay"
            or component["artifact_contract"]["alpha"] is not True
            or component["source_sha256"] != source_identity()
            or component["template_origin"] != "custom_fallback"):
        raise ValueError("overlay source, clock, or implementation binding changed")


def create_adapter(*, node_executable, ffmpeg_executable, browser_executable, brief_loader):
    from ..integrations.talkcraft.check_runtime import check_runtime

    check_runtime()
    tools = [Path(item).resolve(strict=True) for item in
             (node_executable, ffmpeg_executable, browser_executable)]
    if any(not path.is_file() or not os.access(path, os.X_OK) for path in tools):
        raise ValueError("TalkCraft overlay executable is unavailable")
    tool_hashes = {path: contract_artifacts.sha256_file(path) for path in tools}
    implementation = source_identity()

    def guarded_loader(job, recipe, component):
        if source_identity() != implementation or any(
            contract_artifacts.sha256_file(path) != digest for path, digest in tool_hashes.items()
        ):
            raise ValueError("TalkCraft overlay dependencies changed")
        payload = brief_loader(job, recipe, component)
        if type(payload) is not bytes:
            raise ValueError("overlay brief loader must return bytes")
        validate_source_binding(job, recipe, component, payload)
        return payload

    node, ffmpeg, browser = tools
    return executor.ReferenceProcessAdapter(
        adapter_id="talkcraft-aroll-overlay-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=ROOT, entrypoint=ENTRY,
        entrypoint_sha256=contract_artifacts.sha256_file(ROOT / ENTRY),
        producer_version=VERSION, primary_renderer="Remotion", renderer_version="4.0.520",
        artifact_media_type="video", launcher=node, launcher_sha256=tool_hashes[node],
        argv_template=("{launcher}", "--input-type=module", "{entrypoint}",
                       "--brief", "{brief_path}", "--output", "{output_path}",
                       "--adapter-root", str(ADAPTER), "--ffmpeg", str(ffmpeg),
                       "--browser", str(browser), "--source-sha256", implementation),
        brief_loader=guarded_loader, self_contained_wrapper=True, timeout_seconds=300,
    )


def create_binding(adapter, brief_bytes: bytes, *, reference_sample: Path) -> dict:
    """Freeze actual source and sample bytes without claiming template qualification."""
    renderer_input = _brief(brief_bytes)["renderer_input"]
    mode = "threshold" if renderer_input["schema_version"] == 1 else renderer_input["mode"]
    units = 2 if mode == "threshold" else len(renderer_input["labels"])
    implementation = source_identity()
    return {
        "producer_type": "dependency", "dependency_id": DEPENDENCY_ID,
        "entrypoint": ENTRY, "producer_version": VERSION,
        "primary_renderer": "Remotion", "renderer_version": adapter.renderer_version,
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "template_origin": "custom_fallback", "template_id": f"talkcraft-schematic-{mode}",
        "template_version": VERSION, "verification_id": implementation,
        "adaptation_level": "structural", "source_entrypoint": ENTRY,
        "source_sha256": implementation,
        "sample_sha256": contract_artifacts.sha256_file(reference_sample),
        "semantic_families": [mode], "capacity": {"min_units": units, "max_units": units},
        "invocation_record": {"argv": ["node", ENTRY], "status": "planned", "exit_code": None,
                              "template_request": {"semantic_family": mode, "information_units": units,
                                                   "numeric_values": [], "numeric_scale": "not_applicable"}},
    }


def create_artifact_probe(*, ffprobe_executable):
    executable = str(Path(ffprobe_executable).resolve(strict=True))

    def probe(path, media_type, contract):
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run([executable, "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], pass_fds=inherited,
                                capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if len(streams) != 1:
            raise ValueError("overlay must have only one video stream")
        stream = streams[0]
        if (media_type != "video" or contract["alpha"] is not True
                or stream.get("codec_type") != "video" or stream.get("codec_name") != "qtrle"
                or stream.get("pix_fmt") != "argb" or "mov" not in data["format"]["format_name"].split(",")):
            raise ValueError("overlay must be transparent QTRLE/ARGB MOV")
        return {"media_type": "video", "container": "mov", "codec": "qtrle", "pixel_format": "argb",
                "alpha": True, "width": stream["width"], "height": stream["height"],
                "fps": float(Fraction(stream["avg_frame_rate"])),
                "frame_count": int(stream["nb_frames"]), "duration": float(stream["duration"])}

    return executor.ArtifactProbe(probe_id="talkcraft-overlay-qtrle-v1", probe_version=VERSION, probe=probe)

"""Bind the upstream HyperFrames hw-pipeline block to an approved A-roll segment."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
ENTRY = "scripts/render_hyperframes_hw_pipeline.cjs"
SOURCE = PROJECT / "参考项目/B-roll开源方案/hyperframes/registry/blocks/hw-pipeline/hw-pipeline.html"
GSAP = PROJECT / "参考项目/B-roll开源方案/hyperframes/skills/talking-head-recut/assets/vendor/gsap.min.js"
VERSION = "1.0.0"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_brief(node: Path, payload: bytes) -> dict:
    if type(payload) is not bytes or len(payload) > 65536:
        raise ValueError("hw-pipeline brief must be small JSON bytes")
    result = subprocess.run([str(node), str(SKILL / ENTRY), "--validate"], input=payload,
                            capture_output=True, check=False, timeout=10, cwd="/")
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace")[:2000])
    return json.loads(result.stdout)


def _approved_json(job, stage_id: str, relative: str) -> dict:
    stage = job.stages[stage_id]
    if stage["status"] != "approved":
        raise ValueError(f"{stage_id} must be approved")
    records = [item for item in stage["artifacts"] if item["path"] == relative]
    if len(records) != 1:
        raise ValueError(f"{relative} is not bound to the approved stage")
    path = job.job_dir / relative
    if path.stat().st_size != records[0]["bytes"] or _sha(path) != records[0]["sha256"]:
        raise ValueError(f"{relative} changed after approval")
    return json.loads(path.read_text())


def _validate_word_anchors(job, segment: dict, brief: dict) -> None:
    transcript = _approved_json(job, "speech_cleanup", "05-speech-cleanup/word-transcript.json")
    timeline = _approved_json(job, "edit_structure", "06-edit-structure/timeline-map.json")
    words = transcript["words"]
    previous_index = -1
    for anchor, frame in zip(brief["word_anchors"], brief["label_frames"]):
        index = anchor["index"]
        if index <= previous_index or index >= len(words):
            raise ValueError("hw-pipeline word anchors must increase in the current transcript")
        word = words[index]
        if word["text"] != anchor["text"]:
            raise ValueError("hw-pipeline anchor text differs from the approved transcript")
        positions = [float(word["start"]) + float(part["timeline_start"]) - float(part["source_start"])
                     for part in timeline["segments"]
                     if float(part["source_start"]) <= float(word["start"]) < float(part["source_end"])]
        if len(positions) != 1:
            raise ValueError("hw-pipeline word anchor is not in the edited A-roll")
        # The native block reveals a label 0.45 seconds after its box begins drawing.
        reveal_time = float(segment["start"]) + (frame / 24) + 0.45
        if not (float(segment["start"]) <= positions[0] < float(segment["end"])) or abs(reveal_time - positions[0]) > 0.35:
            raise ValueError("hw-pipeline label reveal is not aligned with its spoken word")
        previous_index = index


def validate_source_binding(job, recipe, component, payload: bytes, node: Path) -> None:
    from edit.hd.tools import visual_canary

    brief = _checked_brief(node, payload)
    plan = visual_canary.load_approved_visual_plan(job)
    matches = [item for item in plan["segments"] if item["segment_id"] == recipe["segment_id"]]
    if len(matches) != 1 or matches[0]["shot_recipe"] != json.loads(json.dumps(recipe)):
        raise ValueError("hw-pipeline recipe is not the approved segment")
    segment = matches[0]
    arroll = visual_canary.approved_aroll_record(job, plan)
    window = component["render_window"]
    expected = {"aroll_sha256": arroll["sha256"], "segment_id": segment["segment_id"],
                "start": segment["start"], "end": segment["end"]}
    if (brief["source_binding"] != expected
            or brief["canvas"] != {**recipe["canvas"], "frames": window["end_frame"] - window["start_frame"]}
            or window["start_frame"] != 0
            or window["end_frame"] != round((segment["end"] - segment["start"]) * 24)
            or recipe["composition"]["family"] != "aroll_with_overlay"
            or component["artifact_contract"]["alpha"] is not True
            or component["source_sha256"] != _sha(SOURCE)
            or component["template_origin"] != "custom_fallback"):
        raise ValueError("hw-pipeline source, clock, or approved plan changed")
    _validate_word_anchors(job, segment, brief)


def create_adapter(*, runtime_root, node_executable, browser_executable, ffmpeg_executable,
                   brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter

    runtime, node, browser, ffmpeg = [Path(item).resolve(strict=True) for item in
                                       (runtime_root, node_executable, browser_executable, ffmpeg_executable)]
    for executable in (node, browser, ffmpeg):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"Missing executable: {executable}")
    if _sha(SOURCE) != "5f2d91c91d37dd6b57a015a02361c67c9a62ca33849b901b3bebad8157fb7dbb":
        raise ValueError("hw-pipeline upstream source changed")
    package = json.loads((runtime / "packages/cli/package.json").read_text())
    if package.get("name") != "@hyperframes/cli" or package.get("version") != "0.8.19":
        raise ValueError("HyperFrames runtime version changed")
    hashes = {_path: _sha(_path) for _path in (node, browser, ffmpeg, SOURCE, GSAP)}

    def guarded_loader(job, recipe, component):
        if any(_sha(path) != digest for path, digest in hashes.items()):
            raise ValueError("hw-pipeline dependency changed")
        payload = brief_loader(job, recipe, component)
        validate_source_binding(job, recipe, component, payload, node)
        return payload

    return ReferenceProcessAdapter(
        adapter_id="native-hyperframes-hw-pipeline-v1", dependency_id="hyperframes",
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=_sha(SKILL / ENTRY), producer_version=VERSION,
        primary_renderer="HyperFrames", renderer_version="0.8.19", artifact_media_type="video",
        launcher=node, launcher_sha256=hashes[node], brief_loader=guarded_loader,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
                       "--output", "{output_path}", "--runtime-root", str(runtime),
                       "--source", str(SOURCE), "--vendor-gsap", str(GSAP),
                       "--browser", str(browser), "--ffmpeg", str(ffmpeg)),
    )


def create_binding(adapter, brief_bytes: bytes, *, reference_sample: Path) -> dict:
    brief = _checked_brief(adapter.launcher, brief_bytes)
    source_hash = _sha(SOURCE)
    request = brief["template_request"]
    return {
        "producer_type": "dependency", "dependency_id": "hyperframes", "entrypoint": ENTRY,
        "producer_version": VERSION, "primary_renderer": "HyperFrames", "renderer_version": "0.8.19",
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "template_origin": "custom_fallback", "template_id": "hyperframes/hw-pipeline-portrait" if len(brief["labels"]) == 3 else "hyperframes/hw-box-contrast-portrait",
        "template_version": VERSION, "verification_id": source_hash,
        "adaptation_level": "structural", "source_entrypoint": ENTRY,
        "source_sha256": source_hash, "sample_sha256": _sha(reference_sample),
        "semantic_families": [request["semantic_family"]], "capacity": {"min_units": len(brief["labels"]), "max_units": len(brief["labels"])},
        "invocation_record": {"argv": ["node", ENTRY], "status": "planned", "exit_code": None,
                              "template_request": request},
    }


def create_artifact_probe(*, ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    executable = Path(ffprobe_executable).resolve(strict=True)

    def probe(path, media_type, contract):
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run([str(executable), "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], pass_fds=inherited,
                                capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if len(streams) != 1:
            raise ValueError("hw-pipeline overlay must have one video stream and no audio")
        stream = streams[0]
        fps = Fraction(stream["avg_frame_rate"])
        if (media_type != "video" or contract["alpha"] is not True
                or stream.get("codec_type") != "video" or stream.get("codec_name") != "qtrle"
                or stream.get("pix_fmt") != "argb" or stream.get("width") != 1080
                or stream.get("height") != 1920 or fps != 24
                or "mov" not in data["format"]["format_name"].split(",")):
            raise ValueError("hw-pipeline overlay must be 1080x1920/24fps transparent QTRLE MOV")
        return {"media_type": "video", "container": "mov", "codec": "qtrle",
                "pixel_format": "argb", "alpha": True, "width": 1080, "height": 1920,
                "fps": 24.0, "frame_count": int(stream["nb_frames"]),
                "duration": float(stream["duration"])}

    return ArtifactProbe(probe_id="native-hyperframes-hw-pipeline-qtrle-v1",
                         probe_version=VERSION, probe=probe)

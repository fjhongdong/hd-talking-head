"""Bind the upstream Whiteboard SVG renderer to the shared component executor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from fractions import Fraction

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_whiteboard.py"
DEPENDENCY_ID = "whiteboard-video"
VERSION = "1.0.0"


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wrapper():
    spec = importlib.util.spec_from_file_location("whiteboard_wrapper", SKILL / ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file(value, *, preserve_venv=False):
    path = Path(value).absolute() if preserve_venv else Path(value).resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Whiteboard executable is missing or not executable")
    return path


def create_adapter(upstream_root, engine_root, python_executable, engine_python,
                   ffmpeg_executable, ffprobe_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia

    wrapper = _wrapper()
    upstream = Path(upstream_root).resolve(strict=True) / "scripts/whiteboard_cli.py"
    engine = Path(engine_root).resolve(strict=True)
    python = _file(python_executable)
    native_python = _file(engine_python, preserve_venv=True)
    ffmpeg = _file(ffmpeg_executable)
    ffprobe = _file(ffprobe_executable)
    entry_sha = _sha(SKILL / ENTRY)
    executables = {"python": python, "engine_python": native_python, "ffmpeg": ffmpeg, "ffprobe": ffprobe}
    hashes = {name: _sha(path) for name, path in executables.items()}
    runtime = wrapper.check_runtime(upstream, engine, native_python)

    def check_dependencies():
        if _sha(SKILL / ENTRY) != entry_sha:
            raise ValueError("Whiteboard bridge changed after binding")
        if any(_sha(path) != hashes[name] for name, path in executables.items()):
            raise ValueError("Whiteboard executable changed after binding")
        if wrapper.check_runtime(upstream, engine, native_python) != runtime:
            raise ValueError("Whiteboard runtime changed after binding")

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary

        check_dependencies()
        payload = brief_loader(job, recipe, component)
        brief = wrapper.validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segments = [s for s in plan["segments"] if s["segment_id"] == recipe["segment_id"]]
        if len(segments) != 1 or segments[0]["shot_recipe"] != json.loads(json.dumps(recipe)):
            raise ValueError("Whiteboard recipe is not the current approved segment")
        segment = segments[0]
        record = visual_canary.approved_aroll_record(job, plan)
        expected = {"aroll_sha256": record["sha256"], "segment_id": segment["segment_id"],
                    "start": segment["start"], "end": segment["end"]}
        render = brief["render"]
        window = component["render_window"]
        if (brief["source_binding"] != expected or component["template_origin"] != "custom_fallback"
                or component["source_sha256"] != entry_sha
                or component["artifact_contract"]["alpha"] is not False
                or any(recipe["canvas"][key] != render[key] for key in ("width", "height", "fps"))
                or brief["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or window["start_frame"] != 0
                or abs(render["duration"] - (segment["end"] - segment["start"])) > 1e-6
                or window["end_frame"] != round(render["duration"] * render["fps"])):
            raise ValueError("Whiteboard source, clock, request or implementation binding changed")
        return payload

    def media_loader(job, recipe, component, payload):
        check_dependencies()
        brief = wrapper.validate_brief(payload)
        assets = [ReferenceProcessMedia(media_ref=a["media_ref"], job_path=a["job_path"], sha256=a["sha256"])
                  for a in brief["assets"]]
        provenance = brief["provenance"]
        return tuple(assets + [ReferenceProcessMedia(media_ref="provenance", job_path=provenance["record_path"],
                                                    sha256=provenance["record_sha256"])])

    argv = ("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--output", "{output_path}",
            "--media-manifest", "{media_manifest_fd}", "--upstream", str(upstream),
            "--engine-root", str(engine), "--engine-python", str(native_python),
            "--engine-python-sha256", hashes["engine_python"], "--ffmpeg", str(ffmpeg),
            "--ffprobe", str(ffprobe), "--ffmpeg-sha256", hashes["ffmpeg"], "--ffprobe-sha256", hashes["ffprobe"])
    return ReferenceProcessAdapter(
        adapter_id="whiteboard-svg-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter",
        dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION,
        primary_renderer="Whiteboard", renderer_version="0.1.0", artifact_media_type="video",
        launcher=python, launcher_sha256=hashes["python"], brief_loader=guarded_loader,
        media_loader=media_loader, self_contained_wrapper=True, timeout_seconds=300,
        argv_template=argv, qualification_registry_path=None, qualification_registry_sha256=None)


def create_binding(adapter, brief_bytes, reference_sample):
    wrapper = _wrapper()
    brief = wrapper.validate_brief(brief_bytes)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint != ENTRY
            or adapter.entrypoint_sha256 != _sha(SKILL / ENTRY)):
        raise ValueError("Whiteboard adapter identity changed")
    sample = Path(reference_sample).resolve(strict=True)
    identity = adapter.entrypoint_sha256 + wrapper.UPSTREAM_SHA256 + wrapper.ENGINE_SHA256
    return {
        "template_origin": "custom_fallback", "template_id": "whiteboard-svg-blocks", "template_version": VERSION,
        "verification_id": hashlib.sha256(identity.encode()).hexdigest(), "adaptation_level": "structural",
        "source_entrypoint": ENTRY, "source_sha256": adapter.entrypoint_sha256, "sample_sha256": _sha(sample),
        "semantic_families": [brief["template_request"]["semantic_family"]],
        "capacity": {"min_units": brief["template_request"]["information_units"],
                     "max_units": brief["template_request"]["information_units"]},
        "producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
        "producer_version": VERSION, "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version, "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None,
                              "template_request": brief["template_request"]},
    }


def create_artifact_probe(ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    ffprobe = _file(ffprobe_executable)
    pinned = _sha(ffprobe)

    def probe(path, media_type, contract):
        if _sha(ffprobe) != pinned or media_type != "video" or contract.get("alpha") is not False:
            raise ValueError("Whiteboard probe contract failed")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
                                pass_fds=inherited, capture_output=True, text=True, check=True, timeout=20)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if len(streams) != 1 or streams[0].get("codec_type") != "video":
            raise ValueError("Whiteboard output must be one silent video stream")
        stream = streams[0]
        rotations = [float(item["rotation"]) for item in stream.get("side_data_list", []) if "rotation" in item]
        rotations.append(float(stream.get("tags", {}).get("rotate", 0)))
        if ((stream.get("width"), stream.get("height"), stream.get("sample_aspect_ratio"),
             stream.get("codec_name"), stream.get("pix_fmt"), Fraction(stream.get("r_frame_rate", "0/1")),
             Fraction(stream.get("avg_frame_rate", "0/1")))
                != (1080, 1920, "1:1", "h264", "yuv420p", contract["fps"], contract["fps"])
                or any(rotations) or "mp4" not in data.get("format", {}).get("format_name", "").split(",")):
            raise ValueError("Whiteboard media contract failed")
        return {"media_type": "video", "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
                "alpha": False, "width": 1080, "height": 1920, "fps": float(Fraction(stream["r_frame_rate"])),
                "frame_count": int(stream.get("nb_read_frames", stream.get("nb_frames", 0))),
                "duration": float(stream.get("duration", 0))}

    return ArtifactProbe(probe_id="whiteboard-ffprobe", probe_version=VERSION, probe=probe)


if __name__ == "__main__":
    import argparse
    import shutil
    import sys

    parser = argparse.ArgumentParser(description="Read-only Whiteboard binding probe; does not generate media.")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    project = args.project_root.resolve(strict=True)
    sys.path.insert(0, str(project))
    vendor = project / "skill-development/vendor"
    engine = vendor / "whiteboard-video-engine"
    adapter = create_adapter(vendor / "codex-whiteboard-video-skill", engine, sys.executable,
                             engine / ".venv/bin/python", shutil.which("ffmpeg"), shutil.which("ffprobe"), lambda *_: b"")
    print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
                      "producer_version": VERSION, "adapter_identity": {"adapter_type": type(adapter).__name__,
                      "approved_executor": adapter.approved_executor, "primary_renderer": adapter.primary_renderer}}, sort_keys=True))

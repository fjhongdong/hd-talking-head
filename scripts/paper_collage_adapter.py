"""Adapter for the paper-collage fallback renderer."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_paper_collage.py"
DEPENDENCY_ID = "paper-collage-ad"
VERSION = "1.0.0"
UPSTREAM_SHA256 = "fa1dbdc9676ff5e69f63a5dd012401cfcda3317ef15581d52515ad5a5dd18e98"


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _wrapper_validator():
    path = SKILL / ENTRY
    spec = importlib.util.spec_from_file_location("paper_collage_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_brief


def _file(value, label, executable=True):
    path = Path(value).resolve(strict=True)
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"{label} is not a usable file")
    return path


def create_adapter(upstream_root, python_executable, node_executable,
                   ffmpeg_executable, ffprobe_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia

    root = Path(upstream_root).resolve(strict=True)
    python = _file(python_executable, "python_executable")
    node = _file(node_executable, "node_executable")
    ffmpeg = _file(ffmpeg_executable, "ffmpeg_executable")
    ffprobe = _file(ffprobe_executable, "ffprobe_executable")
    entry = _file(SKILL / ENTRY, "paper collage wrapper", executable=False)
    upstream = (root / "scripts/layer-animate.mjs").resolve(strict=True)
    if _sha(upstream) != UPSTREAM_SHA256:
        raise ValueError("layer-animate.mjs hash does not match the pinned upstream")
    hashes = {"python": _sha(python), "node": _sha(node), "ffmpeg": _sha(ffmpeg), "ffprobe": _sha(ffprobe)}
    validate = _wrapper_validator()

    def check_deps():
        if _sha(entry) != entry_sha or _sha(upstream) != UPSTREAM_SHA256:
            raise ValueError("paper collage source changed after adapter creation")
        for name, path in (("python", python), ("node", node), ("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            if _sha(path) != hashes[name]:
                raise ValueError(f"{name} dependency changed after adapter creation")

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary

        check_deps()
        payload = brief_loader(job, recipe, component)
        if type(payload) is not bytes:
            raise ValueError("brief_loader must return bytes")
        brief = validate(payload)
        source = brief["source_binding"]
        plan = visual_canary.load_approved_visual_plan(job)
        segments = [segment for segment in plan["segments"] if segment["segment_id"] == recipe["segment_id"]]
        if len(segments) != 1 or segments[0]["shot_recipe"] != json.loads(json.dumps(recipe)):
            raise ValueError("Paper recipe is not the current approved segment")
        segment = segments[0]
        record = visual_canary.approved_aroll_record(job, plan)
        expected = {"aroll_sha256": record["sha256"], "segment_id": segment["segment_id"],
                    "start": segment["start"], "end": segment["end"]}
        manifest = brief["manifest"]
        window = component["render_window"]
        if (source != expected or component["template_origin"] != "custom_fallback"
                or component["source_sha256"] != entry_sha
                or component["artifact_contract"]["alpha"] is not False
                or any(recipe["canvas"][key] != manifest[key] for key in ("width", "height", "fps"))
                or brief["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or window["start_frame"] != 0
                or abs(manifest["duration"] - (segment["end"] - segment["start"])) > 1e-6
                or window["end_frame"] != round(manifest["duration"] * manifest["fps"])):
            raise ValueError("Paper source, clock, template request or implementation binding changed")
        return payload

    def guarded_media_loader(job, recipe, component, payload):
        check_deps()
        brief = validate(payload)
        images = [ReferenceProcessMedia(media_ref=a["media_ref"], job_path=a["job_path"], sha256=a["sha256"])
                  for a in brief["assets"]]
        records = {(a["provenance"]["record_path"], a["provenance"]["record_sha256"]) for a in brief["assets"]}
        sources = [ReferenceProcessMedia(media_ref=f"provenance-{index}", job_path=path, sha256=digest)
                   for index, (path, digest) in enumerate(sorted(records))]
        if set(a.media_ref for a in images) & set(a.media_ref for a in sources):
            raise ValueError("image refs overlap reserved provenance refs")
        return tuple(images + sources)

    entry_sha = _sha(entry)
    argv = ("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--output", "{output_path}",
            "--media-manifest", "{media_manifest_fd}", "--upstream", str(upstream), "--node", str(node),
            "--ffmpeg", str(ffmpeg), "--ffprobe", str(ffprobe), "--node-sha256", hashes["node"],
            "--ffmpeg-sha256", hashes["ffmpeg"], "--ffprobe-sha256", hashes["ffprobe"])
    return ReferenceProcessAdapter(
        adapter_id="paper-collage-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter",
        dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION,
        primary_renderer="PaperCollage", renderer_version="1.1.0", artifact_media_type="video",
        launcher=python, launcher_sha256=hashes["python"], brief_loader=guarded_loader,
        media_loader=guarded_media_loader, self_contained_wrapper=True, timeout_seconds=300,
        argv_template=argv, qualification_registry_path=None, qualification_registry_sha256=None)


def create_binding(adapter, brief_bytes, reference_sample):
    brief = _wrapper_validator()(brief_bytes)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint != ENTRY:
        raise ValueError("adapter identity mismatch")
    sample = Path(reference_sample).resolve(strict=True)
    return {
        "template_origin": "custom_fallback", "template_id": "paper-collage-layer-animation", "template_version": VERSION,
        "verification_id": hashlib.sha256((_sha(SKILL / ENTRY) + UPSTREAM_SHA256).encode()).hexdigest(),
        "adaptation_level": "structural", "source_entrypoint": ENTRY,
        "source_sha256": _sha(SKILL / ENTRY), "sample_sha256": _sha(sample),
        "semantic_families": [brief["template_request"]["semantic_family"]],
        "capacity": {"min_units": brief["template_request"]["information_units"],
                     "max_units": brief["template_request"]["information_units"]}, "producer_type": "dependency",
        "dependency_id": adapter.dependency_id, "entrypoint": adapter.entrypoint,
        "producer_version": adapter.producer_version, "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version, "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None,
                              "template_request": brief["template_request"]},
    }


def create_artifact_probe(ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe
    ffprobe = _file(ffprobe_executable, "ffprobe_executable")
    pinned = _sha(ffprobe)

    def probe(path, media_type, contract):
        if _sha(ffprobe) != pinned or media_type != "video" or contract.get("alpha") is not False:
            raise ValueError("paper collage probe contract failed")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)], pass_fds=inherited, capture_output=True, text=True, check=False, timeout=20)
        if result.returncode: raise ValueError("ffprobe failed")
        data = json.loads(result.stdout); streams = data.get("streams", [])
        if len(streams) != 1 or streams[0].get("codec_type") != "video": raise ValueError("expected one video stream")
        s = streams[0]; fps = Fraction(s.get("r_frame_rate", "0/1"))
        rotations = [float(item["rotation"]) for item in s.get("side_data_list", []) if "rotation" in item]
        rotations.append(float(s.get("tags", {}).get("rotate", 0)))
        if ((s.get("width"), s.get("height"), s.get("sample_aspect_ratio"), s.get("codec_name"), s.get("pix_fmt"), fps, Fraction(s.get("avg_frame_rate", "0/1")))
                != (1080, 1920, "1:1", "h264", "yuv420p", contract["fps"], contract["fps"])
                or any(rotations) or "mp4" not in data.get("format", {}).get("format_name", "").split(",")):
            raise ValueError("paper collage media contract failed")
        return {"media_type": "video", "container": "mp4", "codec": "h264", "pixel_format": "yuv420p", "alpha": False, "width": 1080, "height": 1920, "fps": float(fps), "frame_count": int(s.get("nb_read_frames", s.get("nb_frames", 0))), "duration": float(s.get("duration", 0))}
    return ArtifactProbe(probe_id="paper-collage-ffprobe", probe_version=VERSION, probe=probe)


if __name__ == "__main__":
    import argparse
    import shutil
    import sys

    parser = argparse.ArgumentParser(description="Read-only Paper dependency binding probe; does not render or generate.")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    project = args.project_root.resolve(strict=True)
    sys.path.insert(0, str(project))
    upstream = project / "skill-development/vendor/paper-collage-ad-codex"
    if not (upstream / "SKILL.md").is_file():
        raise ValueError("project-local Paper Skill is missing")
    for command in ("node", "ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        if not executable:
            raise ValueError(f"missing {command}")
        subprocess.run([executable, "--version" if command == "node" else "-version"],
                       check=True, capture_output=True, timeout=10)
    adapter = create_adapter(upstream, sys.executable, shutil.which("node"), shutil.which("ffmpeg"),
                             shutil.which("ffprobe"), lambda *_: b"")
    print(json.dumps({"schema_version": 1, "dependency_id": adapter.dependency_id,
                      "entrypoint": adapter.entrypoint, "producer_version": adapter.producer_version,
                      "adapter_identity": {"adapter_type": type(adapter).__name__,
                                           "approved_executor": adapter.approved_executor,
                                           "primary_renderer": adapter.primary_renderer}}, sort_keys=True))

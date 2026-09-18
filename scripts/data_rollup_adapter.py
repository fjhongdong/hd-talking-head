"""Bind the shipped native DataRollup template to the formal HD executor.

Dependencies/paths are explicit per-task configuration; nothing installs or calls
a hosted provider here. Import from a host with the edit.hd runtime on sys.path.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/render_data_rollup.cjs"
VERSION = "1.0.0"
DEFAULT_REGISTRY = "references/verified-template-registry.json"
PROVENANCE = (
    "template_origin", "template_id", "template_version", "verification_id",
    "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
    "semantic_families", "capacity",
)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _registry_path(value):
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("registry_path must be a POSIX path inside the Skill")
    resolved = (SKILL / relative).resolve(strict=True)
    if SKILL.resolve() not in resolved.parents:
        raise ValueError("registry_path escapes the Skill")
    return resolved


def _validate(node, payload):
    if type(payload) is not bytes or len(payload) > 4 * 1024 * 1024:
        raise ValueError("brief must be at most 4 MiB of UTF-8 JSON bytes")
    result = subprocess.run([str(node), str(SKILL / ENTRY), "--validate"], input=payload,
                            capture_output=True, timeout=10, check=False, cwd="/")
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[:2000])
    return json.loads(result.stdout)


def create_adapter(*, runtime_root, node_executable, browser_executable, brief_loader,
                   registry_path=DEFAULT_REGISTRY):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter

    runtime = Path(runtime_root).resolve(strict=True)
    node = Path(node_executable).resolve(strict=True)
    browser = Path(browser_executable).resolve(strict=True)
    registry = _registry_path(registry_path)
    for executable in (node, browser):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"Missing executable dependency: {executable}")
    versions = [json.loads((runtime / "node_modules" / pkg / "package.json").read_text())["version"]
                for pkg in ("remotion", "@remotion/renderer", "@remotion/bundler")]
    if len(set(versions)) != 1:
        raise ValueError("Remotion, renderer and bundler versions must match")

    def guarded_loader(job, recipe, component):
        payload = brief_loader(job, recipe, component)
        checked = _validate(node, payload)
        # Compare plain JSON because executor freezes nested arrays into tuples.
        request = json.loads(json.dumps(component["invocation_record"]["template_request"]))
        if checked["template_request"] != request:
            raise ValueError("Actual brief differs from the frozen template_request")
        canvas = checked["canvas"]
        window = component["render_window"]
        if (canvas["duration_in_frames"] != window["end_frame"] - window["start_frame"]
                or any(canvas[k] != recipe["canvas"][k] for k in ("width", "height", "fps"))
                or component["artifact_contract"]["alpha"]):
            raise ValueError("Actual brief differs from the approved opaque render window/canvas")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="native-data-rollup-v1", dependency_id="html-video",
        approved_executor="reference_adapter", dependency_root=SKILL,
        entrypoint=ENTRY, entrypoint_sha256=_sha(SKILL / ENTRY), producer_version=VERSION,
        primary_renderer="Remotion", renderer_version=versions[0], artifact_media_type="video",
        launcher=node, launcher_sha256=_sha(node), self_contained_wrapper=True,
        brief_loader=guarded_loader, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
                       "--output", "{output_path}", "--skill-root", str(SKILL),
                       "--runtime-root", str(runtime), "--browser", str(browser),
                       "--registry-path", registry_path,
                       "--registry-sha256", _sha(registry),
                       "--renderer-version", versions[0]),
        qualification_registry_path=(
            None if registry_path == DEFAULT_REGISTRY else registry_path
        ),
        qualification_registry_sha256=(
            None if registry_path == DEFAULT_REGISTRY else _sha(registry)
        ),
    )


def create_binding(adapter, brief_bytes, *, registry_path=DEFAULT_REGISTRY):
    """Build provenance/input binding, not an approval or an execution receipt."""
    checked = _validate(adapter.launcher, brief_bytes)
    registry = json.loads(_registry_path(registry_path).read_text())
    template = next(t for t in registry["templates"] if t["template_id"] == "html-video/frame-data-rollup")
    return {
        **{key: template[key] for key in PROVENANCE},
        "producer_type": "dependency", "dependency_id": adapter.dependency_id,
        "entrypoint": adapter.entrypoint, "producer_version": adapter.producer_version,
        "primary_renderer": adapter.primary_renderer, "renderer_version": adapter.renderer_version,
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": ["node", adapter.entrypoint], "status": "planned", "exit_code": None,
                              "template_request": checked["template_request"]},
    }


def create_artifact_probe(*, ffprobe_executable):
    """Probe the executor's inherited descriptor; never fabricate media metadata."""
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    executable = Path(ffprobe_executable).resolve(strict=True)

    def probe(path, media_type, contract):
        if media_type != "video" or contract["alpha"]:
            raise ValueError("DataRollup probe accepts only opaque video")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run(
            [str(executable), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            pass_fds=inherited, capture_output=True, text=True, timeout=20, check=False,
        )
        if result.returncode:
            raise ValueError(f"ffprobe failed: {result.stderr[:1000]}")
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        if len(streams) != 1 or streams[0]["codec_type"] != "video":
            raise ValueError("Expected one video stream and no audio")
        s = streams[0]
        rotation = [float(d["rotation"]) for d in s.get("side_data_list", []) if "rotation" in d]
        rotation.append(float(s.get("tags", {}).get("rotate", 0)))
        fps = Fraction(s["r_frame_rate"])
        if (s["width"] != 1080 or s["height"] != 1920 or fps != 24
                or Fraction(s["avg_frame_rate"]) != fps
                or s.get("sample_aspect_ratio") != "1:1" or s.get("display_aspect_ratio") != "9:16"
                or any(r != 0 for r in rotation) or s["codec_name"] != "h264"
                or s["pix_fmt"] != "yuv420p" or "mp4" not in payload["format"]["format_name"].split(",")):
            observed = {k: s.get(k) for k in ("width", "height", "r_frame_rate", "avg_frame_rate",
                                             "sample_aspect_ratio", "display_aspect_ratio", "codec_name", "pix_fmt")}
            raise ValueError(f"Expected native 1080x1920, SAR 1:1, 24fps H.264/yuv420p MP4; observed {observed}")
        return {"media_type": "video", "container": "mp4", "codec": s["codec_name"],
                "pixel_format": s["pix_fmt"], "alpha": False, "width": s["width"], "height": s["height"],
                "fps": float(fps), "frame_count": int(s["nb_frames"]), "duration": float(s["duration"])}

    return ArtifactProbe(probe_id="native-data-rollup-ffprobe", probe_version=VERSION, probe=probe)

#!/usr/bin/env python3
"""Frozen-media bridge to Paper Collage's unmodified layer animator.

This wrapper stages inputs and checks output; animation belongs to the upstream
Skill. Background and final frames are full-canvas; native cropped cutouts keep
their pixel dimensions and manifest coordinates. It adds neither audio nor presenters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tempfile
from fractions import Fraction

UPSTREAM_SHA256 = "fa1dbdc9676ff5e69f63a5dd012401cfcda3317ef15581d52515ad5a5dd18e98"
HASH = re.compile(r"[0-9a-f]{64}")
REF = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _number(value, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError("missing Job-relative asset path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("asset path must stay inside the Job")


def validate_brief(payload: bytes) -> dict:
    if type(payload) is not bytes or not 0 < len(payload) <= 4 * 1024 * 1024:
        raise ValueError("brief must be nonempty JSON bytes, at most 4 MiB")
    brief = json.loads(payload)
    if (type(brief) is not dict or set(brief) != {
            "schema_version", "source_binding", "template_request", "manifest", "assets"
    } or brief["schema_version"] != 1):
        raise ValueError("invalid Paper brief schema")
    source = brief["source_binding"]
    if (type(source) is not dict or set(source) != {"aroll_sha256", "segment_id", "start", "end"}
            or not HASH.fullmatch(source.get("aroll_sha256", ""))
            or not REF.fullmatch(source.get("segment_id", ""))
            or not 0 <= _number(source["start"], "start") < _number(source["end"], "end")):
        raise ValueError("invalid source clock binding")
    request = brief["template_request"]
    if (type(request) is not dict or set(request) != {
            "semantic_family", "information_units", "numeric_values", "numeric_scale"
    } or not isinstance(request["semantic_family"], str) or not request["semantic_family"]
            or type(request["information_units"]) is not int or request["information_units"] < 1
            or request["numeric_values"] != [] or request["numeric_scale"] != "not_applicable"):
        raise ValueError("Paper imagery does not implement quantitative chart scaling")
    manifest = brief["manifest"]
    if type(manifest) is not dict or set(manifest) != {
            "width", "height", "fps", "duration", "crf", "steps", "finalHold", "fadeDuration",
            "background", "finalFrame", "layers"}:
        raise ValueError("invalid upstream layer manifest")
    if (manifest["width"] != 1080 or manifest["height"] != 1920
            or type(manifest["fps"]) is not int or not 1 <= manifest["fps"] <= 60
            or type(manifest["steps"]) is not int or manifest["steps"] < 1
            or type(manifest["crf"]) is not int or not 0 <= manifest["crf"] <= 51):
        raise ValueError("invalid native portrait canvas or animation settings")
    duration = _number(manifest["duration"], "duration")
    frames = duration * manifest["fps"]
    if not 0 < duration <= 60 or abs(frames - round(frames)) > 1e-6:
        raise ValueError("duration must be a positive exact frame window, at most 60 seconds")
    hold = _number(manifest["finalHold"], "finalHold")
    fade = _number(manifest["fadeDuration"], "fadeDuration")
    if not 0 < fade <= hold <= duration:
        raise ValueError("final fade and hold must fit inside the scene")
    if not isinstance(manifest["layers"], list) or not 1 <= len(manifest["layers"]) <= 16:
        raise ValueError("Paper requires one to sixteen real moving layers")
    refs = [manifest["background"], manifest["finalFrame"]]
    for layer in manifest["layers"]:
        if (type(layer) is not dict or set(layer) != {"image", "from", "x", "y", "startAt", "travel"}
                or layer["from"] not in {"left", "right", "top", "bottom", "none"}):
            raise ValueError("invalid layer parameters")
        for key in ("x", "y", "startAt", "travel"):
            _number(layer[key], key)
        if layer["travel"] <= 0:
            raise ValueError("layer travel must be positive; negative startAt is permitted")
        refs.append(layer["image"])
    assets = brief["assets"]
    if not isinstance(assets, list) or not assets:
        raise ValueError("missing image provenance")
    names = []
    for asset in assets:
        if type(asset) is not dict or set(asset) != {"media_ref", "job_path", "sha256", "geometry", "provenance"}:
            raise ValueError("invalid asset binding")
        if (not REF.fullmatch(asset["media_ref"]) or not HASH.fullmatch(asset["sha256"])
                or type(asset["geometry"]) is not str
                or asset["geometry"] not in {"full_canvas", "native_cutout"}
                or (asset["media_ref"] in refs[:2] and asset["geometry"] != "full_canvas")):
            raise ValueError("invalid image identity")
        _relative(asset["job_path"])
        provenance = asset["provenance"]
        if (type(provenance) is not dict or set(provenance) != {"kind", "tool", "record_path", "record_sha256"}
                or provenance["kind"] not in {"ai_generated", "local_material", "official_material"}
                or not isinstance(provenance["tool"], str) or not provenance["tool"]
                or not HASH.fullmatch(provenance["record_sha256"])):
            raise ValueError("missing original image source record")
        _relative(provenance["record_path"])
        names.append(asset["media_ref"])
    if len(names) != len(set(names)) or set(names) != set(refs):
        raise ValueError("every image must have exactly one asset binding")
    source_records = {(a["provenance"]["record_path"], a["provenance"]["record_sha256"]) for a in assets}
    if len(assets) + len(source_records) > 8:
        raise ValueError("Paper inputs exceed the executor's eight frozen-media slots")
    return brief


def _run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, timeout=240, **kwargs)


def render(args) -> dict:
    payload = Path(args.brief).read_bytes()
    brief = validate_brief(payload)
    source = Path(args.upstream).read_bytes()
    if sha(source) != UPSTREAM_SHA256:
        raise ValueError("Paper upstream entrypoint changed")
    for name in ("node", "ffmpeg", "ffprobe"):
        if sha(Path(getattr(args, name)).read_bytes()) != getattr(args, name + "_sha256"):
            raise ValueError(f"{name} dependency changed")
    frozen = json.loads(Path(args.media_manifest).read_bytes())
    if frozen.get("schema_version") != "reference-process-media/v1" or frozen.get("brief_sha256") != sha(payload):
        raise ValueError("frozen media belongs to a different brief")
    records = {item["media_ref"]: item for item in frozen["media"]}
    if len(records) != len(frozen["media"]):
        raise ValueError("duplicate frozen media")
    verified = {}
    for ref, record in records.items():
        data = Path(f"/dev/fd/{record['fd']}").read_bytes()
        if len(data) != record["byte_length"] or sha(data) != record["sha256"]:
            raise ValueError("frozen media hash mismatch")
        verified[ref] = data
    hashes = {sha(data) for data in verified.values()}
    manifest = brief["manifest"]
    original_sizes = {}
    with tempfile.TemporaryDirectory(prefix="hd-paper-") as directory:
        temp = Path(directory)
        binary = temp / "bin"
        binary.mkdir()
        for name in ("ffmpeg", "ffprobe"):
            (binary / name).symlink_to(getattr(args, name))
        entry = temp / "layer-animate.mjs"
        entry.write_bytes(source)  # Execute the exact bytes checked above.
        normalized = {}
        opaque = {manifest["background"], manifest["finalFrame"]}
        for index, asset in enumerate(brief["assets"]):
            ref = asset["media_ref"]
            data = verified.get(ref, b"")
            if sha(data) != asset["sha256"] or asset["provenance"]["record_sha256"] not in hashes:
                raise ValueError("image or its source record is not frozen")
            if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
                raise ValueError("Paper layers must be PNG files")
            width, height = struct.unpack(">II", data[16:24])
            full_canvas = asset["geometry"] == "full_canvas"
            if not width or not height or (full_canvas and abs(width / height - 9 / 16) > .002) or (
                    not full_canvas and (width > 1080 or height > 1920)):
                raise ValueError("background/final need 9:16; cropped cutouts must fit the canvas")
            original_sizes[ref] = {"width": width, "height": height, "sha256": sha(data)}
            original = temp / f"original-{index}.png"
            original.write_bytes(data)
            target = temp / f"layer-{index}.png"
            if full_canvas:
                filters = ("format=rgba" if (width, height) == (1080, 1920)
                           else "scale=1080:1920:flags=lanczos,setsar=1,format=rgba")
                _run([args.ffmpeg, "-v", "error", "-i", str(original), "-vf",
                      filters, "-frames:v", "1", str(target)])
            else:
                target.write_bytes(data)
            check_width, check_height = (1080, 1920) if full_canvas else (width, height)
            alpha = _run([args.ffmpeg, "-v", "error", "-i", str(target), "-vf", "alphaextract",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]).stdout
            if len(alpha) != check_width * check_height or (ref in opaque and min(alpha) != 255) or (
                    ref not in opaque and not min(alpha) == 0 < max(alpha)):
                raise ValueError("background/final must be opaque; cutouts need real transparency")
            normalized[ref] = str(target)
        manifest["background"] = normalized[manifest["background"]]
        manifest["finalFrame"] = normalized[manifest["finalFrame"]]
        for layer in manifest["layers"]:
            layer["image"] = normalized[layer["image"]]
        manifest_path = temp / "layers.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output = temp / "scene.mp4"
        result = _run([args.node, str(entry), "--manifest", str(manifest_path), "--output", str(output)],
                      env={**os.environ, "PATH": str(binary) + os.pathsep + "/usr/bin:/bin"})
        streams = json.loads(_run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)]).stdout)["streams"]
        if len(streams) != 1:
            raise ValueError("Paper output must not contain audio")
        video = streams[0]
        if video.get("sample_aspect_ratio") != "1:1":
            square_output = temp / "scene-square.mp4"
            _run([args.ffmpeg, "-v", "error", "-i", str(output), "-map", "0:v:0",
                  "-c:v", "copy", "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1",
                  str(square_output)])
            output = square_output
            streams = json.loads(_run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)]).stdout)["streams"]
            if len(streams) != 1:
                raise ValueError("Paper metadata normalization changed stream count")
            video = streams[0]
        frames = round(manifest["duration"] * manifest["fps"])
        if (video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p"
                or (video.get("width"), video.get("height")) != (1080, 1920)
                or video.get("sample_aspect_ratio") != "1:1"
                or Fraction(video["avg_frame_rate"]) != manifest["fps"]
                or int(video["nb_frames"]) != frames
                or abs(float(video["duration"]) - manifest["duration"]) > .00001):
            raise ValueError("upstream output differs from the exact silent portrait frame window")
        output_bytes = output.read_bytes()
        destination = Path(args.output)
        if destination.parent == Path("/dev/fd"):
            with destination.open("wb") as handle:
                handle.write(output_bytes)
        else:
            with destination.open("xb") as handle:
                handle.write(output_bytes)
        return {"upstream_sha256": sha(source), "brief_sha256": sha(payload),
                "exit_code": result.returncode, "output_sha256": sha(output_bytes),
                "frames": frames, "original_images": original_sizes,
                "normalization": "full-canvas images scale to 1080x1920 when needed; cropped cutouts keep native pixels and coordinates; H.264 SAR marked 1:1 without re-encoding; not native image generation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("brief", "output", "media-manifest", "upstream", "node", "ffmpeg", "ffprobe",
                   "node-sha256", "ffmpeg-sha256", "ffprobe-sha256"):
        parser.add_argument("--" + option, required=True)
    print(json.dumps(render(parser.parse_args()), ensure_ascii=False))

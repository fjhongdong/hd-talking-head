#!/usr/bin/env python3
"""Frozen-media bridge to the vendored Whiteboard SVG renderer."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import re
from fractions import Fraction

UPSTREAM_SHA256 = "523424e0b69fe74da8d6a7dc31c178a56cc52fad8d82b3f0607b767fa0bd417e"
ENGINE_SHA256 = "db1a4ef3a6592973cd38b7572abad7c41c0fdb1bb99b07e34a6ce79de23ca857"
HASH = re.compile(r"[0-9a-f]{64}")
REF = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")

# Executed by the existing project venv, with -I, for both probing and rendering.
# Engine code is checked in place; only the brief and media are FD-frozen.
BOOTSTRAP = r'''
import hashlib, importlib.metadata as metadata, json, runpy, sys
from pathlib import Path
import whiteboard_skill
import whiteboard_skill.cli
from PIL import Image
request = json.loads(sys.argv[1])
root = Path(request['engine_root']).resolve()
base = root / 'src/whiteboard_skill'
if (Path(whiteboard_skill.__file__).resolve() != base / '__init__.py'
        or Path(whiteboard_skill.cli.__file__).resolve() != base / 'cli.py'
        or Path(sys.prefix).resolve() != root / '.venv'):
    raise ValueError('Whiteboard interpreter or module import location changed')
digest = lambda value: hashlib.sha256(value).hexdigest()
files = {p.relative_to(base).as_posix(): digest(p.read_bytes()) for p in sorted(base.rglob('*'))
         if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
if digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()) != request['engine_sha256']:
    raise ValueError('Whiteboard engine source tree changed')
upstream = Path(request['upstream'])
if digest(upstream.read_bytes()) != request['upstream_sha256']:
    raise ValueError('Whiteboard upstream entrypoint changed')
versions = {name: metadata.version(name) for name in ('Pillow', 'numpy', 'pydantic', 'whiteboard-video-engine')}
if versions != {'Pillow': '12.3.0', 'numpy': '2.5.3', 'pydantic': '2.13.5', 'whiteboard-video-engine': '0.1.0'}:
    raise ValueError('Whiteboard dependencies differ from the tested runtime')
if sys.version_info[:2] != (3, 12):
    raise ValueError('Whiteboard requires the tested Python 3.12 environment')
info = {'upstream_sha256': request['upstream_sha256'], 'engine_sha256': request['engine_sha256'],
        'engine_python': sys.executable, 'python_version': sys.version.split()[0],
        'module_file': str(base / '__init__.py'), 'dependencies': versions}
if 'argv' not in request:
    print(json.dumps(info))
else:
    with Image.open(request['source_png']) as image:
        image.load()
        extrema = image.convert('RGB').getextrema()
        if (image.size != (1080, 1920) or image.convert('RGBA').getextrema()[3] != (255, 255)
                or min(pair[0] for pair in extrema) >= 240
                or all(low == high for low, high in extrema)):
            raise ValueError('registered source must be opaque, nonblank native 1080x1920')
    sys.argv = [str(upstream), *request['argv']]
    runpy.run_path(str(upstream), run_name='__main__')
'''


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _num(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Job-relative path required")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("path must stay inside the Job")


def _svg(data: bytes):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("invalid SVG") from exc
    allowed = {"svg", "g", "path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in allowed:
            raise ValueError("SVG contains unsupported element")
        for key, value in node.attrib.items():
            local = key.rsplit("}", 1)[-1]
            if local == "transform":
                raise ValueError("SVG transforms are not allowed")
            if local in {"href", "src"} or "url(" in value.lower() or "@import" in value.lower():
                raise ValueError("SVG external references are not allowed")
            if tag == "path" and key.rsplit("}", 1)[-1] == "d" and re.search(r"[Aa]", value):
                raise ValueError("SVG arc commands are not allowed")
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("SVG root required")
    viewbox = root.attrib.get("viewBox", "").replace(",", " ").split()
    if (len(viewbox) != 4 or tuple(float(x) for x in viewbox) != (0, 0, 1080, 1920)
            or root.get("width") != "1080" or root.get("height") != "1920"):
        raise ValueError("SVG canvas must be 1080x1920")


def validate_brief(payload: bytes) -> dict:
    if type(payload) is not bytes or not 0 < len(payload) <= 4 * 1024 * 1024:
        raise ValueError("brief must be nonempty JSON bytes, at most 4 MiB")
    brief = json.loads(payload)
    keys = {"schema_version", "source_binding", "template_request", "render", "assets", "provenance"}
    if type(brief) is not dict or set(brief) != keys or brief["schema_version"] != 1:
        raise ValueError("invalid Whiteboard brief schema")
    source = brief["source_binding"]
    if (type(source) is not dict or set(source) != {"aroll_sha256", "segment_id", "start", "end"}
            or not HASH.fullmatch(source.get("aroll_sha256", "")) or not REF.fullmatch(source.get("segment_id", ""))
            or not 0 <= _num(source["start"], "start") < _num(source["end"], "end")):
        raise ValueError("invalid source clock binding")
    request = brief["template_request"]
    if (type(request) is not dict or set(request) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or not isinstance(request["semantic_family"], str) or not request["semantic_family"]
            or type(request["information_units"]) is not int or request["information_units"] < 1
            or request["numeric_values"] != [] or request["numeric_scale"] != "not_applicable"):
        raise ValueError("invalid Whiteboard template request")
    render = brief["render"]
    if (type(render) is not dict or set(render) != {"width", "height", "fps", "duration", "line_thickness", "tail_hold", "draw_blocks"}
            or render["width"] != 1080 or render["height"] != 1920 or type(render["fps"]) is not int or not 1 <= render["fps"] <= 60
            or type(render["line_thickness"]) is not int or not 1 <= render["line_thickness"] <= 16
            or type(render["draw_blocks"]) is not int or not 1 <= render["draw_blocks"] <= 16):
        raise ValueError("invalid native portrait render settings")
    duration = _num(render["duration"], "duration")
    if not 0 < duration <= 60 or abs(duration * render["fps"] - round(duration * render["fps"])) > 1e-6:
        raise ValueError("duration must be a positive exact frame window, at most 60 seconds")
    if not 0 <= _num(render["tail_hold"], "tail_hold") < duration:
        raise ValueError("tail_hold must fit inside duration")
    assets = brief["assets"]
    if type(assets) is not list or len(assets) not in (2, 3):
        raise ValueError("registered svg/source and an optional initial context are required")
    refs = set()
    for asset in assets:
        if type(asset) is not dict or set(asset) != {"media_ref", "job_path", "sha256"}:
            raise ValueError("invalid asset binding")
        if asset["media_ref"] not in {"svg", "source", "context"} or asset["media_ref"] in refs or not HASH.fullmatch(asset["sha256"]):
            raise ValueError("invalid asset identity")
        _relative(asset["job_path"])
        refs.add(asset["media_ref"])
    if refs not in ({"svg", "source"}, {"svg", "source", "context"}):
        raise ValueError("svg and source assets are both required")
    provenance = brief["provenance"]
    if (type(provenance) is not dict or set(provenance) != {"record_path", "record_sha256"}
            or not HASH.fullmatch(provenance["record_sha256"])):
        raise ValueError("invalid provenance record")
    _relative(provenance["record_path"])
    return brief


def _run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, timeout=300, **kwargs)


def _runtime_request(upstream, engine_root):
    return {"upstream": str(Path(upstream).resolve()), "engine_root": str(Path(engine_root).resolve()),
            "upstream_sha256": UPSTREAM_SHA256, "engine_sha256": ENGINE_SHA256}


def check_runtime(upstream, engine_root, engine_python):
    if sha(Path(upstream).read_bytes()) != UPSTREAM_SHA256:
        raise ValueError("Whiteboard upstream entrypoint changed")
    result = subprocess.run([str(engine_python), "-I", "-c", BOOTSTRAP,
                             json.dumps(_runtime_request(upstream, engine_root))], check=True,
                            capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    return json.loads(result.stdout)


def _pixel_clock_hash(ffmpeg, path):
    # Exclude container headers, retain each decoded frame's PTS, duration and pixels.
    result = _run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0", "-an",
                   "-pix_fmt", "yuv420p", "-f", "framemd5", "-"])
    rows = [row for row in result.stdout.splitlines() if row and not row.startswith(b"#")]
    return {"frames": len(rows), "sha256": sha(b"\n".join(rows))}


def render(args) -> dict:
    payload = Path(args.brief).read_bytes(); brief = validate_brief(payload)
    runtime = check_runtime(args.upstream, args.engine_root, args.engine_python)
    for name in ("engine_python", "ffmpeg", "ffprobe"):
        if sha(Path(getattr(args, name)).read_bytes()) != getattr(args, name + "_sha256"):
            raise ValueError(f"{name} dependency changed")
    frozen = json.loads(Path(args.media_manifest).read_bytes())
    if frozen.get("schema_version") != "reference-process-media/v1" or frozen.get("brief_sha256") != sha(payload):
        raise ValueError("frozen media belongs to a different brief")
    records = {item["media_ref"]: item for item in frozen.get("media", [])}
    expected_refs = {a['media_ref'] for a in brief['assets']} | {'provenance'}
    if set(records) != expected_refs or len(frozen["media"]) != len(expected_refs):
        raise ValueError("frozen media must contain svg, source and provenance")
    data = {}
    for ref, record in records.items():
        blob = Path(f"/dev/fd/{record['fd']}").read_bytes()
        if len(blob) != record["byte_length"] or sha(blob) != record["sha256"]:
            raise ValueError("frozen media hash mismatch")
        data[ref] = blob
    byref = {a["media_ref"]: a for a in brief["assets"]}
    if any(sha(data[r]) != byref[r]["sha256"] for r in byref):
        raise ValueError("asset hash mismatch")
    if sha(data["provenance"]) != brief["provenance"]["record_sha256"]:
        raise ValueError("provenance record hash mismatch")
    record = json.loads(data["provenance"])
    if (type(record) is not dict or not isinstance(record.get("tool"), str) or not record["tool"]
            or record.get("assets", {}).get("svg", {}).get("sha256") != byref["svg"]["sha256"]
            or record.get("assets", {}).get("source", {}).get("sha256") != byref["source"]["sha256"]
            or record.get("canvas") != {"width": 1080, "height": 1920}
            or not isinstance(record.get("method"), str) or not record["method"]
            or record.get("engine_sha256") != ENGINE_SHA256):
        raise ValueError("provenance does not identify both frozen assets")
    _svg(data["svg"])
    if data["source"][:8] != b"\x89PNG\r\n\x1a\n" or len(data["source"]) < 24:
        raise ValueError("source must be a native PNG")
    import struct
    if struct.unpack(">II", data["source"][16:24]) != (1080, 1920):
        raise ValueError("source must be 1080x1920")
    if 'context' in data:
        if (data['context'][:8] != b'\x89PNG\r\n\x1a\n'
                or struct.unpack('>II', data['context'][16:24]) != (1080, 1920)
                or record.get('assets', {}).get('context', {}).get('sha256') != byref['context']['sha256']):
            raise ValueError('initial context must be a registered native portrait PNG')
    with tempfile.TemporaryDirectory(prefix="hd-whiteboard-") as d:
        temp = Path(d); svg = temp / "source.svg"; png = temp / "source.png"; native = temp / "native.mp4"; target = temp / "target.mp4"
        svg.write_bytes(data["svg"]); png.write_bytes(data["source"])
        r = brief["render"]
        argv = ["render-image", str(svg), "-o", str(native), "--width", "1080", "--height", "1920", "--fps", str(r["fps"]), "--duration", str(r["duration"]), "--animation-preset", "block-speedpaint", "--line-reveal", "stroke", "--line-thickness", str(r["line_thickness"]), "--hand", "none", "--tail-color", str(r["tail_hold"]), "--max-draw-blocks", str(r["draw_blocks"]), "--draw-blocks", str(r["draw_blocks"]), "--block-overlap", "0", "--block-order", "source", "--block-fill-style", "clean", "--no-lineart-snap", "--source-image", str(png), "--source-fit", "exact"]
        env = {"PATH": str(temp / "bin") + os.pathsep + "/usr/bin:/bin"}
        (temp / "bin").mkdir(); (temp / "bin" / "ffmpeg").symlink_to(args.ffmpeg); (temp / "bin" / "ffprobe").symlink_to(args.ffprobe)
        # One isolated interpreter verifies the editable package, then executes
        # the exact upstream wrapper; this prevents probing one installation and
        # rendering through another.
        request = {**_runtime_request(args.upstream, args.engine_root), "argv": argv, "source_png": str(png)}
        result = subprocess.run([str(args.engine_python), "-I", "-c", BOOTSTRAP, json.dumps(request)],
                                check=True, capture_output=True, timeout=240, env=env, cwd=temp)
        native_streams = json.loads(_run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(native)]).stdout)["streams"]
        if len(native_streams) != 1 or native_streams[0].get("codec_type") != "video":
            raise ValueError("native Whiteboard output contains unexpected streams")
        if 'context' in data:
            # A visible current-topic base prevents an empty stage while the
            # upstream engine draws relations. Future-result labels stay in its
            # registered source image and are not shown on this initial base.
            context_png = temp / 'context.png'; context_png.write_bytes(data['context'])
            composed = temp / 'with-context.mp4'
            _run([args.ffmpeg, '-v', 'error', '-loop', '1', '-framerate', str(r['fps']),
                  '-i', str(context_png), '-i', str(native), '-filter_complex',
                  '[0:v]format=gbrp[context];[1:v]format=gbrp[drawing];[context][drawing]blend=all_mode=multiply:shortest=1,format=yuv420p[v]', '-map', '[v]',
                  '-frames:v', str(round(r['duration']*r['fps'])), '-an', '-c:v', 'libx264',
                  '-crf', '18', '-threads', '1', '-pix_fmt', 'yuv420p', str(composed)], env=env)
            native = composed
        _run([args.ffmpeg, "-v", "error", "-i", str(native), "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1", "-an", str(target)], env=env)
        streams = json.loads(_run([args.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)], env=env).stdout)
        video = [s for s in streams["streams"] if s.get("codec_type") == "video"]
        if len(video) != 1 or len(streams["streams"]) != 1:
            raise ValueError("Whiteboard output must contain video only")
        v = video[0]; frames = round(r["duration"] * r["fps"])
        if (v.get("codec_name"), v.get("pix_fmt"), v.get("width"), v.get("height"), v.get("sample_aspect_ratio"), int(v.get("nb_frames", -1))) != ("h264", "yuv420p", 1080, 1920, "1:1", frames):
            raise ValueError("native output differs from exact silent portrait frame window")
        if (Fraction(v["r_frame_rate"]) != r["fps"] or Fraction(v["avg_frame_rate"]) != r["fps"]
                or abs(float(v["duration"]) - r["duration"]) > .00001):
            raise ValueError("Whiteboard output clock differs from the brief")
        pixel_clock = _pixel_clock_hash(args.ffmpeg, native)
        if pixel_clock["frames"] != frames or pixel_clock != _pixel_clock_hash(args.ffmpeg, target):
            raise ValueError("SAR normalization changed decoded pixels or frame timing")
        output = target.read_bytes(); dest = Path(args.output)
        if dest.parent == Path("/dev/fd"):
            dest.write_bytes(output)
        else:
            with dest.open("xb") as handle: handle.write(output)
        return {**runtime, "brief_sha256": sha(payload), "upstream_argv": [args.upstream, *argv],
                "exit_code": result.returncode, "output_sha256": sha(output), "frames": frames,
                "initial_context": 'context' in data,
                "normalization": "H.264 SAR 1:1 metadata only after optional explicit context composition; no resize",
                "decoded_pixel_clock": pixel_clock}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("brief", "output", "media-manifest", "upstream", "engine-root", "engine-python", "engine-python-sha256", "ffmpeg", "ffprobe", "ffmpeg-sha256", "ffprobe-sha256"):
        parser.add_argument("--" + option, required=True)
    print(json.dumps(render(parser.parse_args()), ensure_ascii=False))

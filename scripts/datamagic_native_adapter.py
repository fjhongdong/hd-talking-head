"""Bind the unchanged DataMagic PortraitRankedReveal composition to a six-second shot."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

if __file__ == "<stdin>":
    _bootstrap = argparse.ArgumentParser(add_help=False)
    _bootstrap.add_argument("--skill-root", type=Path, required=True)
    SKILL = _bootstrap.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    from package_paths import PACKAGE_ROOT as SKILL
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "scripts"))

from adapter_kit import (ffprobe_json, find_tool, identity_from_digests,
                         sha256_file as sha, validate_source_binding)

ENTRY = "scripts/datamagic_native_adapter.py"
DEPENDENCY_ID = "datamagic"
SOURCE_PIN = "3a66365b6dcab798efc76baf54a3039d0b273f2c"
ROUTE = "PortraitRankedReveal"
TEMPLATE_ID = "datamagic/portrait-ranked-reveal"
FAMILY = "numeric_comparison"
VERSION = "1.0.0"
RENDERER_VERSION = "4.0.531"
COMPOSITION = {"width": 1080, "height": 1920, "fps": 24, "frames": 144}
ARTIFACT_CONTRACT = {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
SECONDS = COMPOSITION["frames"] / COMPOSITION["fps"]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _number(value):
    return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max


def _text(value, limit, *, optional=False):
    return (type(value) is str and (optional or bool(value.strip()))
            and len(value.encode("utf-16-le", errors="surrogatepass")) <= limit * 2)


def validate_brief(payload):
    brief = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    if (type(brief) is not dict
            or set(brief) != {"schema_version", "source_binding", "composition", "template_request", "props"}
            or type(brief["schema_version"]) is not int or brief["schema_version"] != 1):
        raise ValueError("Invalid DataMagic brief")
    source = brief["source_binding"]
    validate_source_binding(source, "Invalid DataMagic source clock")
    composition = brief["composition"]
    if (type(composition) is not dict or composition != COMPOSITION
            or any(type(value) is not int for value in composition.values())
            or abs((source["end"] - source["start"]) * 24 - 144) > 1e-6):
        raise ValueError("DataMagic requires a six-second 1080×1920 window at 24 fps")

    props = brief["props"]
    text_limits = {"title": 24, "question": 48, "metricLabel": 16, "unit": 6, "source": 56, "takeaway": 48}
    if (type(props) is not dict or set(props) != {*text_limits, "maximum", "rows"}
            or any(not _text(props[key], limit) for key, limit in text_limits.items())
            or not _number(props["maximum"]) or props["maximum"] <= 0):
        raise ValueError("Invalid DataMagic text or common scale; use the native fonts and data fields")
    rows = props["rows"]
    if type(rows) is not list or len(rows) != 2:
        raise ValueError("DataMagic currently supports two ranked entries")
    required = {"id", "label", "value", "at", "caption"}
    for row in rows:
        if (type(row) is not dict or set(row) - {"color"} != required
                or type(row["id"]) is not str or not row["id"].strip()
                or not _text(row["label"], 12) or not _text(row["caption"], 40, optional=True)
                or not _number(row["value"]) or not 0 <= row["value"] <= props["maximum"]
                or not _number(row["at"]) or not 1.5 <= row["at"] <= SECONDS - 2.8
                or ("color" in row and (type(row["color"]) is not str
                                        or not re.fullmatch(r"#[0-9a-fA-F]{6}", row["color"])))):
            raise ValueError("Invalid DataMagic row; use a native data row without an image reference")
    first, second = sorted(rows, key=lambda row: row["at"])
    if (first["id"] == second["id"] or second["at"] - first["at"] < 0.8
            or first["value"] > second["value"]):
        raise ValueError("DataMagic requires unique rows revealed low to high at least 0.8 seconds apart")

    request = brief["template_request"]
    if (type(request) is not dict
            or request != {"semantic_family": FAMILY, "information_units": 2,
                           "numeric_values": [row["value"] for row in rows], "numeric_scale": "linear"}
            or type(request["information_units"]) is not int
            or not all(_number(value) for value in request["numeric_values"])):
        raise ValueError("DataMagic rows differ from the bound numeric comparison")
    return brief


def check_runtime(project_root, executables=None):
    from native_result_reuse import source_unchanged
    from prepare_sources import bundled_source_revision

    project = Path(project_root).resolve(strict=True)
    source = project / "vendor/DataMagic"
    if not source.is_dir() or source.resolve() != source:
        raise ValueError("DataMagic needs the bundled project-local source")

    def verify_source(_inventory):
        if bundled_source_revision(project, source) != SOURCE_PIN:
            raise ValueError("DataMagic source differs from its reviewed revision")

    source_unchanged(project, DEPENDENCY_ID, source, verify_source,
                     records=(project / "archives/sources/index.json",))
    cards = source / "cards"
    modules = cards / "node_modules"
    cli = modules / ".bin/remotion"
    expected_cli = modules / "@remotion/cli/remotion-cli.js"
    if not cli.is_file() or cli.resolve() != expected_cli.resolve():
        raise ValueError("DataMagic needs its existing native Remotion CLI from cards/package-lock.json")
    metadata = [modules / name / "package.json" for name in
                ("remotion", "@remotion/cli", "@remotion/bundler", "@remotion/renderer")]
    if any(not path.is_file() or json.loads(path.read_bytes()).get("version") != RENDERER_VERSION
           for path in metadata):
        raise ValueError(f"DataMagic requires the locked Remotion {RENDERER_VERSION} runtime")

    requested = executables or {}
    tools = {}
    for name, candidates in {"node": ("node",), "ffmpeg": ("ffmpeg",), "ffprobe": ("ffprobe",),
                             "browser": (CHROME, "google-chrome", "google-chrome-stable")}.items():
        tool = find_tool(requested[name]) if requested.get(name) else find_tool(*candidates)
        if tool is None:
            raise ValueError(f"DataMagic requires an existing {name} executable")
        tools[name] = str(tool.resolve(strict=True))
    node_version = subprocess.check_output([tools["node"], "--version"], text=True, timeout=10).strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+", node_version)
    if not match or tuple(map(int, match.groups())) < (20, 10):
        raise ValueError("DataMagic requires Node >=20.10")
    identity = identity_from_digests([*tools.values(), cli, cards / "package-lock.json", *metadata],
                                    (SOURCE_PIN, RENDERER_VERSION))
    return {**tools, "cli": str(cli), "cards": str(cards), "identity": identity}


def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter

    project = Path(project_root).resolve(strict=True)
    python = Path(python_executable).resolve(strict=True)
    runtime, entry_sha = check_runtime(project), sha(SKILL / ENTRY)

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary

        payload = brief_loader(job, recipe, component)
        brief = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(item for item in plan["segments"] if item["segment_id"] == recipe["segment_id"])
        source = {"aroll_sha256": plan["edited_aroll_sha256"], "segment_id": segment["segment_id"],
                  "start": segment["start"], "end": segment["end"]}
        window = component["render_window"]
        request = json.loads(json.dumps(component["invocation_record"]["template_request"]))
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"] or brief["source_binding"] != source
                or brief["template_request"] != request or component["template_id"] != TEMPLATE_ID
                or component["source_sha256"] != entry_sha or component["artifact_contract"] != ARTIFACT_CONTRACT
                or recipe["composition"]["family"] not in {"single_full_frame", "evidence_with_data_overlay"}
                or component["layer_role"] != "base" or window["layout_slot"] != "full_frame"
                or (window["start_frame"], window["end_frame"]) != (0, 144)):
            raise ValueError("DataMagic no longer matches the approved six-second full-frame shot")
        if sha(SKILL / ENTRY) != entry_sha or check_runtime(project) != runtime:
            raise ValueError("DataMagic adapter or runtime changed")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="datamagic-native-ranked-reveal-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="Remotion",
        renderer_version=RENDERER_VERSION, artifact_media_type="video", launcher=python,
        launcher_sha256=sha(python), brief_loader=guard, media_loader=None,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}", "{entrypoint}", "--skill-root", str(SKILL), "--project-root", str(project),
                       "--brief", "{brief_path}", "--output", "{output_path}",
                       "--node", runtime["node"], "--ffmpeg", runtime["ffmpeg"], "--ffprobe", runtime["ffprobe"],
                       "--browser", runtime["browser"], "--runtime-identity", runtime["identity"]))


def create_binding(adapter, payload, reference_sample):
    brief = validate_brief(payload)
    entry_sha = sha(SKILL / ENTRY)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != entry_sha
            or adapter.renderer_version != RENDERER_VERSION):
        raise ValueError("DataMagic adapter identity changed")
    digest = hashlib.sha256(payload).hexdigest()
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
            "producer_version": VERSION, "primary_renderer": "Remotion", "renderer_version": RENDERER_VERSION,
            "template_origin": "custom_fallback", "template_id": TEMPLATE_ID, "template_version": VERSION,
            "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": entry_sha,
            "sample_sha256": sha(reference_sample), "semantic_families": [FAMILY],
            "capacity": {"min_units": 2, "max_units": 2}, "brief_sha256": digest,
            "verification_id": hashlib.sha256((entry_sha + digest).encode()).hexdigest(),
            "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None,
                                  "template_request": brief["template_request"]}}


def _probe_stream(ffprobe, path):
    data = ffprobe_json(ffprobe, path)
    streams = data.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("DataMagic must produce one silent video stream")
    video = streams[0]
    rotations = [float(item["rotation"]) for item in video.get("side_data_list", []) if "rotation" in item]
    rotations.append(float(video.get("tags", {}).get("rotate", 0)))
    if ((video.get("codec_name"), video.get("width"), video.get("height"), video.get("sample_aspect_ratio"),
         Fraction(video.get("r_frame_rate", "0")), Fraction(video.get("avg_frame_rate", "0")),
         int(video.get("nb_read_frames", 0))) != ("h264", 1080, 1920, "1:1", 24, 24, 144)
            or not math.isclose(float(video.get("duration", 0)), SECONDS, abs_tol=1e-6)
            or any(rotations) or "mp4" not in data.get("format", {}).get("format_name", "").split(",")):
        raise ValueError("DataMagic output must be a six-second 1080×1920 MP4 at 24 fps")
    return video


def _check_limited(video):
    if (video.get("pix_fmt"), video.get("color_range")) != ("yuv420p", "tv"):
        raise ValueError("DataMagic output must use limited-range yuv420p")


def create_artifact_probe(ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    ffprobe = Path(ffprobe_executable).resolve(strict=True)
    pinned = sha(ffprobe)

    def probe(path, media_type, contract):
        if sha(ffprobe) != pinned or media_type != "video" or contract != ARTIFACT_CONTRACT:
            raise ValueError("DataMagic media probe contract failed")
        _check_limited(_probe_stream(ffprobe, path))
        return {"media_type": "video", "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
                **ARTIFACT_CONTRACT, "fps": 24.0, "frame_count": 144, "duration": SECONDS}

    return ArtifactProbe(probe_id="datamagic-ffprobe", probe_version=VERSION, probe=probe)


def render(args):
    payload = Path(args.brief).read_bytes()
    brief = validate_brief(payload)
    executables = {name: getattr(args, name) for name in ("node", "ffmpeg", "ffprobe", "browser")}
    runtime = check_runtime(args.project_root, executables)
    if runtime["identity"] != args.runtime_identity:
        raise ValueError("Bound DataMagic runtime changed")
    parent = Path(args.project_root) / "runtime/datamagic-renders"
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="native-", dir=parent))
    props_path = work / "props.json"
    native, normalized = work / "native.mp4", work / "output.mp4"
    report = {"status": "running", "source_pin": SOURCE_PIN, "composition": ROUTE,
              "renderer_version": RENDERER_VERSION, "brief_sha256": hashlib.sha256(payload).hexdigest(),
              "commands": []}
    path = os.pathsep.join(dict.fromkeys([str(Path(runtime[name]).parent) for name in
                                        ("node", "ffmpeg", "ffprobe")] + ["/usr/bin", "/bin"]))
    environment = {**os.environ, "PATH": path}

    def run(argv, *, timeout):
        record = {"argv": argv, "exit_code": None}
        report["commands"].append(record)
        with (work / f"command-{len(report['commands'])}.log").open("wb") as log:
            result = subprocess.run(argv, cwd=runtime["cards"], env=environment, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, check=False, timeout=timeout)
        record["exit_code"] = result.returncode
        result.check_returncode()

    try:
        props_path.write_text(json.dumps(brief["props"], ensure_ascii=False), encoding="utf-8")
        run([runtime["node"], runtime["cli"], "render", "src/index.ts", "ShotCraft-" + ROUTE, str(native),
             f"--props={props_path}", "--fps=24", "--duration=144", "--muted", "--codec=h264", "--crf=18",
             "--pixel-format=yuv420p", "--concurrency=1", "--bundle-cache=false",
             f"--browser-executable={runtime['browser']}"], timeout=240)
        stream = _probe_stream(runtime["ffprobe"], native)
        output = native
        if (stream.get("pix_fmt"), stream.get("color_range")) in {("yuvj420p", "pc"), ("yuv420p", "pc")}:
            # Verify silence before converting pixels. Map every stream and preserve the native clock.
            run([runtime["ffmpeg"], "-v", "error", "-nostdin", "-n", "-i", str(native), "-map", "0",
                 "-vf", "scale=in_range=full:out_range=limited", "-fps_mode", "passthrough", "-c:v", "libx264",
                 "-crf", "18", "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart",
                 str(normalized)], timeout=35)
            output = normalized
            stream = _probe_stream(runtime["ffprobe"], output)
        _check_limited(stream)
        if check_runtime(args.project_root, executables) != runtime:
            raise ValueError("DataMagic runtime changed during rendering")
        shutil.copyfile(output, args.output)
        report.update(status="completed", frames=144, output_sha256=sha(output))
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise RuntimeError(f"DataMagic render stopped. See {work / 'invocation.json'}") from error
    finally:
        (work / "invocation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**report, "evidence_path": str(work / "invocation.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, default=SKILL)
    parser.add_argument("--probe", action="store_true")
    for name in ("brief", "output", "node", "ffmpeg", "ffprobe", "browser", "runtime-identity"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.probe:
        check_runtime(args.project_root, {"browser": args.browser})
        print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
                          "producer_version": VERSION, "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
                          "approved_executor": "reference_adapter", "primary_renderer": "Remotion"}}))
    else:
        if not all(getattr(args, name) for name in ("brief", "output", "node", "ffmpeg", "ffprobe", "runtime_identity")):
            parser.error("render requires --brief, --output, --node, --ffmpeg, --ffprobe and --runtime-identity")
        print(json.dumps(render(args), ensure_ascii=False))

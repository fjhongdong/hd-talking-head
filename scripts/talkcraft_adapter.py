"""Bind the pinned TalkCraft runtime without granting pending cards production use."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from fractions import Fraction
from pathlib import Path


ENTRY = "edit/hd/integrations/talkcraft/runtime/render.mjs"
REGISTRY = "edit/hd/integrations/talkcraft/runtime/card-registry.json"
RUNTIME = "edit/hd/integrations/talkcraft/runtime"
DEPENDENCY_ID = "hd-talking-head-talkcraft"
ADAPTER_VERSION = "1.1.0"
RENDERER_VERSION = "4.0.520"
TOOLS = frozenset(("node", "playwright", "browser", "ffmpeg", "ffprobe"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(root: Path, relative: str, *, directory: bool = False) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise ValueError("TalkCraft path is not project-relative")
    current = root
    for index, part in enumerate(path.parts):
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise ValueError("TalkCraft runtime path is unavailable") from exc
        final = index == len(path.parts) - 1
        expected = stat.S_ISDIR(metadata.st_mode) if final and directory else (
            stat.S_ISREG(metadata.st_mode) if final else stat.S_ISDIR(metadata.st_mode)
        )
        if not expected or stat.S_ISLNK(metadata.st_mode):
            raise ValueError("TalkCraft runtime path contains a symlink")
    return current


def _snapshot(path: Path, *, maximum: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
                raise ValueError("TalkCraft identity snapshot is invalid")
            payload = source.read(maximum + 1)
            after = os.fstat(source.fileno())
        visible = os.lstat(path)
    except OSError as exc:
        raise ValueError("TalkCraft identity snapshot is unavailable") from exc
    stamp = lambda value: (
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )
    if len(payload) != before.st_size or stamp(before) != stamp(after) or stamp(before) != stamp(visible):
        raise ValueError("TalkCraft identity changed while reading")
    return payload


def _strict_json(payload: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        payload,
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


def create_adapter(
    *,
    project_root,
    tools,
    tool_hashes,
    brief_loader,
    runtime_contracts,
):
    from edit.hd.tools.broll_component_executor import (
        ReferenceProcessAdapter,
        ReferenceProcessMedia,
    )
    from edit.hd.tools.runtime_contracts import normalize_contracts, verify_contracts
    from edit.hd.tools.talkcraft_contract import validate_production_brief

    supplied_root = Path(project_root)
    root = supplied_root.resolve(strict=True)
    if not supplied_root.is_absolute() or supplied_root != root or not stat.S_ISDIR(os.lstat(root).st_mode):
        raise ValueError("TalkCraft project root must be canonical and nonsymlinked")
    entrypoint = _inside(root, ENTRY)
    registry = _inside(root, REGISTRY)
    runtime = _inside(root, RUNTIME, directory=True)
    if set(tools) != TOOLS or set(tool_hashes) != TOOLS or not callable(brief_loader):
        raise ValueError("TalkCraft dependency contract is incomplete")
    paths = {key: Path(value).resolve(strict=True) for key, value in tools.items()}
    hashes = dict(tool_hashes)
    contracts = normalize_contracts(runtime_contracts)
    for key, contract in contracts.items():
        if contract["path"] != str(paths[key]):
            raise ValueError("TalkCraft runtime path mismatch: " + key)
        if key in ("node", "ffmpeg", "ffprobe") and (
            contract["sha256"] != hashes[key]
            or contract.get("library_discovery") != "mach_o_static_v1"
        ):
            raise ValueError("TalkCraft runtime file contract mismatch: " + key)
    encoded_contracts = json.dumps(
        contracts, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(encoded_contracts.encode("utf-8")) > 65536:
        raise ValueError("TalkCraft runtime contract is too large")
    entrypoint_bytes = _snapshot(entrypoint, maximum=1024 * 1024)
    registry_bytes = _snapshot(registry, maximum=4 * 1024 * 1024)
    manifest = _inside(root, RUNTIME + "/closure-manifest.json")
    manifest_bytes = _snapshot(manifest, maximum=4 * 1024 * 1024)
    entrypoint_sha256 = hashlib.sha256(entrypoint_bytes).hexdigest()
    registry_sha256 = hashlib.sha256(registry_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    bootstrap = entrypoint_bytes.decode("utf-8")
    match = re.search(r'EXPECTED_MANIFEST_SHA256 = "([0-9a-f]{64})"', bootstrap)
    if match is None or match.group(1) != manifest_sha256:
        raise ValueError("TalkCraft closure manifest is not pinned by the entrypoint")

    def check_dependencies():
        current_entrypoint = _inside(root, ENTRY)
        current_registry = _inside(root, REGISTRY)
        current_runtime = _inside(root, RUNTIME, directory=True)
        current_manifest = _inside(root, RUNTIME + "/closure-manifest.json")
        if current_runtime != runtime or current_entrypoint != entrypoint or current_registry != registry:
            raise ValueError("TalkCraft runtime path identity changed")
        if (
            hashlib.sha256(_snapshot(current_entrypoint, maximum=1024 * 1024)).hexdigest()
            != entrypoint_sha256
            or hashlib.sha256(_snapshot(current_registry, maximum=4 * 1024 * 1024)).hexdigest()
            != registry_sha256
        ):
            raise ValueError("TalkCraft entrypoint or registry changed")
        if hashlib.sha256(_snapshot(current_manifest, maximum=4 * 1024 * 1024)).hexdigest() != manifest_sha256:
            raise ValueError("TalkCraft closure manifest changed")
        for key, path in paths.items():
            if (
                not path.is_file()
                or (key != "playwright" and not os.access(path, os.X_OK))
                or _sha(path) != hashes[key]
            ):
                raise ValueError("TalkCraft dependency identity mismatch: " + key)
        verify_contracts(contracts)

    check_dependencies()

    def guarded_loader(job, recipe, component):
        check_dependencies()
        payload = brief_loader(job, recipe, component)
        if type(payload) is not bytes:
            raise ValueError("TalkCraft brief loader must return bytes")
        checked = validate_production_brief(
            _strict_json(payload), registry_path=registry
        )
        plain_recipe = json.loads(json.dumps(recipe))
        plain_component = json.loads(json.dumps(component))
        target = checked["execution_target"]
        scope = checked["frame_scope"]
        render = checked["render"]
        window = plain_component.get("render_window")
        contract = plain_component.get("artifact_contract")
        window_frames = (
            window["end_frame"] - window["start_frame"]
            if type(window) is dict
            and type(window.get("start_frame")) is int
            and type(window.get("end_frame")) is int
            else None
        )
        if (
            plain_recipe.get("canvas") != checked["canvas"]
            or target.get("kind") != "component"
            or target.get("segment_id") != plain_recipe.get("segment_id")
            or target.get("component_id") != plain_component.get("component_id")
            or render.get("renderer") != "Remotion"
            or window_frames != render.get("duration_frames")
            or scope["global_end_frame"] - scope["global_start_frame"]
            != render.get("duration_frames")
            or type(contract) is not dict
            or any(contract.get(key) != checked["canvas"][key] for key in ("width", "height", "fps"))
            or contract.get("alpha") != render.get("alpha")
        ):
            raise ValueError("TalkCraft brief differs from the approved component")
        check_dependencies()
        return payload

    def guarded_media_loader(job, recipe, component, payload):
        check_dependencies()
        if type(payload) is not bytes:
            raise ValueError("TalkCraft brief loader must return bytes")
        checked = validate_production_brief(
            _strict_json(payload), registry_path=registry
        )
        media = checked["media"]
        if len(media) > 8:
            raise ValueError("TalkCraft production brief has too many media inputs")
        return tuple(
            ReferenceProcessMedia(
                media_ref=f"media-{index}",
                job_path=item["job_path"],
                sha256=item["sha256"],
            )
            for index, item in enumerate(media)
        )

    argv = (
        "{launcher}",
        "--input-type=module",
        "{entrypoint}",
        "--brief",
        "{brief_path}",
        "--output",
        "{output_path}",
        "--media-manifest",
        "{media_manifest_fd}",
        "--runtime-root",
        str(runtime),
        "--browser",
        str(paths["browser"]),
    )
    expanded = list(argv)
    for key in ("node", "playwright", "ffmpeg", "ffprobe"):
        expanded.extend(("--" + key, str(paths[key])))
    expanded.extend(("--runtime-contracts", encoded_contracts))
    return ReferenceProcessAdapter(
        adapter_id="talkcraft-reference-v1",
        dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter",
        dependency_root=root,
        entrypoint=ENTRY,
        entrypoint_sha256=entrypoint_sha256,
        producer_version=ADAPTER_VERSION,
        primary_renderer="Remotion",
        renderer_version=RENDERER_VERSION,
        artifact_media_type="video",
        launcher=paths["node"],
        launcher_sha256=hashes["node"],
        argv_template=tuple(expanded),
        brief_loader=guarded_loader,
        media_loader=guarded_media_loader,
        self_contained_wrapper=True,
        timeout_seconds=300,
        runtime_contracts=contracts,
        qualification_registry_path=REGISTRY,
        qualification_registry_sha256=registry_sha256,
        request_only_values=(str(runtime),),
    )


def create_artifact_probe(*, ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    executable = Path(ffprobe_executable).resolve(strict=True)

    def probe(path, media_type, contract):
        if media_type != "video":
            raise ValueError("TalkCraft probe accepts video artifacts only")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run(
            [
                str(executable), "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(path),
            ],
            pass_fds=inherited,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise ValueError("TalkCraft ffprobe failed: " + result.stderr[:1000])
        payload = json.loads(result.stdout)
        streams = payload.get("streams")
        if type(streams) is not list or len(streams) != 1 or streams[0].get("codec_type") != "video":
            raise ValueError("TalkCraft output must contain one video stream and no audio")
        stream = streams[0]
        fps = Fraction(stream["r_frame_rate"])
        alpha = contract["alpha"]
        format_names = payload["format"]["format_name"].split(",")
        expected_codec = "prores" if alpha else "h264"
        expected_container = "mov" if alpha else "mp4"
        pixel_format = stream.get("pix_fmt", "")
        if (
            stream.get("width") != 1080
            or stream.get("height") != 1920
            or fps != 24
            or Fraction(stream["avg_frame_rate"]) != fps
            or stream.get("codec_name") != expected_codec
            or expected_container not in format_names
            or (alpha and not pixel_format.startswith("yuva444p"))
            or (not alpha and pixel_format != "yuv420p")
        ):
            raise ValueError("TalkCraft output differs from its approved media contract")
        return {
            "media_type": "video",
            "container": expected_container,
            "codec": stream["codec_name"],
            "pixel_format": pixel_format,
            "alpha": alpha,
            "width": stream["width"],
            "height": stream["height"],
            "fps": float(fps),
            "frame_count": int(stream["nb_frames"]),
            "duration": float(stream["duration"]),
        }

    return ArtifactProbe(
        probe_id="talkcraft-ffprobe-v1",
        probe_version=ADAPTER_VERSION,
        probe=probe,
    )

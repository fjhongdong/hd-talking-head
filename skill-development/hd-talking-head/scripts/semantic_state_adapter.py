"""Bind the frozen SemanticState bundle to approved content and runtime identities."""
from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
import stat
import tempfile


SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/semantic_state_renderer_bundle.py"
DEPENDENCY_ID = "hd-talking-head-semantic-state"
VERSION = "1.0.0"
DEFAULT_REGISTRY = "references/verified-template-registry.json"
FAMILIES = ("replacement", "threshold", "delay", "hierarchy", "feedback")
TEMPLATES = {family: "hd-talking-head/semantic-state-" + family for family in FAMILIES}
PROVENANCE = (
    "template_origin", "template_id", "template_version", "verification_id",
    "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
    "semantic_families", "capacity",
)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(value, label, *, executable):
    path = Path(value).resolve(strict=True)
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(label + " is not an approved file")
    return path


def _read_snapshot(path, label, *, executable, maximum):
    """Read one regular-file identity; callers hash and consume these same bytes."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_size <= 0
                    or before.st_size > maximum or (executable and not before.st_mode & 0o111)):
                raise ValueError(label + " snapshot is invalid")
            data = source.read(maximum + 1)
            after = os.fstat(source.fileno())
        visible = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(label + " snapshot is unavailable") from exc
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                           value.st_mtime_ns, value.st_ctime_ns)
    if len(data) != before.st_size or len(data) > maximum or stamp(before) != stamp(after) or stamp(before) != stamp(visible):
        raise ValueError(label + " changed while reading")
    return data


def _registry_file(relative):
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or value.as_posix() != relative:
        raise ValueError("registry path must be inside the Skill")
    result = (SKILL / value).resolve(strict=True)
    if SKILL.resolve() not in result.parents:
        raise ValueError("registry path escapes the Skill")
    return result


def _registry_template(template_id, registry_path, registry_sha256):
    if template_id not in TEMPLATES.values():
        raise ValueError("unknown SemanticState template")
    path = _registry_file(registry_path)
    data = _read_snapshot(path, "registry", executable=False, maximum=1024 * 1024)
    if (type(registry_sha256) is not str or len(registry_sha256) != 64
            or hashlib.sha256(data).hexdigest() != registry_sha256):
        raise ValueError("registry identity mismatch")
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("registry contains duplicate keys")
            result[key] = value
        return result
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                             parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("registry is unreadable") from exc
    if type(payload) is not dict:
        raise ValueError("registry must contain an object")
    templates = payload.get("templates")
    matches = [item for item in templates or [] if type(item) is dict and item.get("template_id") == template_id]
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1 or len(matches) != 1:
        raise ValueError("SemanticState template is not unique in registry")
    item = matches[0]
    if (any(key not in item for key in PROVENANCE)
            or item.get("source_entrypoint") != ENTRY
            or item.get("source_sha256") != _sha(SKILL / ENTRY)):
        raise ValueError("SemanticState registry provenance is incomplete")
    return item


def create_adapter(*, template_id, python_executable, node_executable, playwright_module,
                   browser_executable, ffmpeg_executable, ffprobe_executable,
                   runtime_contracts, brief_loader, registry_path=DEFAULT_REGISTRY,
                   registry_sha256):
    """Create a pinned adapter; this never registers or approves the template."""
    from edit.hd.tools.semantic_state_adapter import create_adapter as runtime_adapter

    _registry_template(template_id, registry_path, registry_sha256)
    tools = {
        "python": _regular_file(python_executable, "python", executable=True),
        "node": _regular_file(node_executable, "node", executable=True),
        "playwright": _regular_file(playwright_module, "playwright", executable=False),
        "browser": _regular_file(browser_executable, "browser", executable=True),
        "ffmpeg": _regular_file(ffmpeg_executable, "ffmpeg", executable=True),
        "ffprobe": _regular_file(ffprobe_executable, "ffprobe", executable=True),
    }
    hashes = {name: _sha(path) for name, path in tools.items()}
    return runtime_adapter(
        dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=_sha(SKILL / ENTRY),
        tools=tools, tool_hashes=hashes, brief_loader=brief_loader,
        runtime_contracts=runtime_contracts,
        qualification_registry_path=None if registry_path == DEFAULT_REGISTRY else registry_path,
        qualification_registry_sha256=None if registry_path == DEFAULT_REGISTRY else registry_sha256,
    )


def create_binding(adapter, job, brief_bytes, *, registry_path=DEFAULT_REGISTRY,
                   registry_sha256):
    """Bind one exact brief to a current approved content-analysis state."""
    from edit.hd.tools.semantic_state_binding import bind_brief

    if (getattr(adapter, "dependency_id", None) != DEPENDENCY_ID
            or getattr(adapter, "entrypoint", None) != ENTRY
            or getattr(adapter, "primary_renderer", None) != "SemanticState"
            or getattr(adapter, "renderer_version", None) != VERSION):
        raise ValueError("adapter does not have the approved SemanticState identity")
    contracts = getattr(adapter, "runtime_contracts", None)
    node = contracts.get("node") if type(contracts) is dict else None
    if type(node) is not dict:
        raise ValueError("SemanticState node contract missing")
    try:
        family = json.loads(brief_bytes)["motion"]["family"]
        template_id = TEMPLATES[family]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("SemanticState brief family is invalid") from exc
    report = bind_brief(job, brief_bytes, node_executable=Path(node.get("path", "")),
                        node_sha256=node.get("sha256"), template_id=template_id)
    template_id = report["template_id"]
    template = _registry_template(template_id, registry_path, registry_sha256)
    if report.get("brief_sha256") != hashlib.sha256(brief_bytes).hexdigest():
        raise ValueError("SemanticState binding returned another brief identity")
    return {
        **{key: template[key] for key in PROVENANCE},
        "producer_type": "dependency", "dependency_id": adapter.dependency_id,
        "entrypoint": adapter.entrypoint, "producer_version": adapter.producer_version,
        "primary_renderer": adapter.primary_renderer, "renderer_version": adapter.renderer_version,
        "brief_sha256": report["brief_sha256"],
        "invocation_record": {
            "argv": [str(adapter.launcher), adapter.entrypoint], "status": "planned", "exit_code": None,
            "template_request": report["template_request"], "semantic_motion": report["semantic_motion"],
        },
    }


def create_artifact_probe(*, ffprobe_executable):
    """Create the strict opaque 9:16 SemanticState MP4 probe."""
    import subprocess
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    executable = _regular_file(ffprobe_executable, "ffprobe", executable=True)
    executable_bytes = _read_snapshot(executable, "ffprobe", executable=True, maximum=256 * 1024 * 1024)
    identity = hashlib.sha256(executable_bytes).hexdigest()

    def probe(path, media_type, contract):
        if (hashlib.sha256(_read_snapshot(executable, "ffprobe", executable=True,
                                          maximum=256 * 1024 * 1024)).hexdigest() != identity
                or media_type != "video" or contract.get("alpha") is not False):
            raise ValueError("SemanticState probe identity or media type changed")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        with tempfile.TemporaryDirectory(prefix="hd-semantic-ffprobe-") as directory:
            snapshot = Path(directory) / "ffprobe"
            descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
            try:
                view = memoryview(executable_bytes)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            result = subprocess.run([str(snapshot), "-v", "error", "-count_frames", "-show_streams",
                "-show_format", "-of", "json", str(path)], pass_fds=inherited,
                capture_output=True, text=True, timeout=20, check=False)
        if hashlib.sha256(_read_snapshot(executable, "ffprobe", executable=True,
                                         maximum=256 * 1024 * 1024)).hexdigest() != identity:
            raise ValueError("SemanticState ffprobe changed during probe")
        if result.returncode:
            raise ValueError("SemanticState ffprobe failed")
        payload = json.loads(result.stdout)
        streams = payload.get("streams")
        if type(streams) is not list or len(streams) != 1 or streams[0].get("codec_type") != "video":
            raise ValueError("SemanticState output requires one video stream")
        stream = streams[0]
        rotation = [item.get("rotation", 0) for item in stream.get("side_data_list", [])]
        rotation.append(stream.get("tags", {}).get("rotate", 0))
        fps = Fraction(stream.get("r_frame_rate", "0/1"))
        if (stream.get("width") != 1080 or stream.get("height") != 1920
                or fps != 24 or Fraction(stream.get("avg_frame_rate", "0/1")) != fps
                or stream.get("sample_aspect_ratio") != "1:1" or stream.get("codec_name") != "h264"
                or stream.get("pix_fmt") != "yuv420p" or any(float(value) != 0 for value in rotation)
                or "mp4" not in payload.get("format", {}).get("format_name", "").split(",")):
            raise ValueError("SemanticState output media contract failed")
        return {"media_type": "video", "container": "mp4", "codec": "h264",
                "pixel_format": "yuv420p", "alpha": False, "width": 1080, "height": 1920,
                "fps": 24.0, "frame_count": int(stream.get("nb_read_frames", stream.get("nb_frames", 0))),
                "duration": float(stream["duration"])}

    return ArtifactProbe(probe_id="native-semantic-state-ffprobe", probe_version=VERSION, probe=probe)

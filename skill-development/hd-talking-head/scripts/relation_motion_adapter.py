"""Bind the frozen RelationMotion bundle to the HD reference executor.

This module can use a qualification registry, but it never registers or
approves a template.  The caller must provide a Job whose content analysis is
currently approved.
"""
from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping


SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/relation_motion_renderer_bundle.py"
DEPENDENCY_ID = "hd-talking-head-relation-motion"
TEMPLATE_ID = "hd-talking-head/relation-motion"
VERSION = "1.0.0"
DEFAULT_REGISTRY = "references/verified-template-registry.json"
PROVENANCE = (
    "template_origin", "template_id", "template_version", "verification_id",
    "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
    "semantic_families", "capacity",
)
_ROOT_KEYS = {"schema_version", "canvas", "motion", "title", "source_ids", "hub_id"}
_CANVAS_KEYS = {"width", "height", "fps", "duration_in_frames"}
_SUBJECT_KEYS = {"id", "label", "initial_state", "final_state", "preserve"}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _registry_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("registry_path must be a POSIX path inside the Skill")
    resolved = (SKILL / relative).resolve(strict=True)
    if SKILL.resolve() not in resolved.parents:
        raise ValueError("registry_path escapes the Skill")
    return resolved


def _regular_file(value: object, label: str, *, executable: bool) -> Path:
    path = Path(value).resolve(strict=True)
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"{label} must be a regular executable file" if executable else f"{label} must be a regular file")
    return path


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("brief contains duplicate JSON keys")
        result[key] = value
    return result


def _text(value: object, label: str, maximum: int = 200) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} is invalid")
    return value


def _parse_brief(payload: bytes) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > 4 * 1024 * 1024:
        raise ValueError("brief must be nonempty UTF-8 JSON bytes of at most 4 MiB")
    try:
        brief = json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("brief must be valid UTF-8 JSON") from exc
    if type(brief) is not dict or set(brief) != _ROOT_KEYS or brief["schema_version"] != 1:
        raise ValueError("brief must contain exactly the six RelationMotion fields")
    canvas = brief["canvas"]
    if type(canvas) is not dict or set(canvas) != _CANVAS_KEYS:
        raise ValueError("brief canvas fields are invalid")
    if any(
        type(canvas.get(key)) is not int or canvas[key] != expected
        for key, expected in (("width", 1080), ("height", 1920), ("fps", 24))
    ):
        raise ValueError("brief canvas must be 1080x1920 at 24 fps")
    duration = canvas["duration_in_frames"]
    if type(duration) is not int or not 48 <= duration <= 240:
        raise ValueError("brief duration must be 48..240 frames")
    _text(brief["title"], "brief title", 12)
    source_ids = brief["source_ids"]
    if (
        type(source_ids) is not list
        or not 2 <= len(source_ids) <= 4
        or any(type(value) is not str or not value.strip() for value in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ValueError("brief source_ids must contain 2..4 unique ids")
    hub_id = _text(brief["hub_id"], "brief hub_id", 80)
    if hub_id in source_ids:
        raise ValueError("brief hub_id must differ from source_ids")
    motion = brief["motion"]
    if type(motion) is not dict or motion.get("family") != "relation":
        raise ValueError("brief motion must use the relation family")
    if motion.get("duration_frames") != duration:
        raise ValueError("brief motion duration differs from canvas")
    subjects = motion.get("subjects")
    if type(subjects) is not list or len(subjects) != len(source_ids) + 1:
        raise ValueError("brief subjects must be source_ids plus hub_id")
    identities: list[str] = []
    for subject in subjects:
        if type(subject) is not dict or set(subject) != _SUBJECT_KEYS:
            raise ValueError("brief subject fields are invalid")
        identity = _text(subject["id"], "subject id", 80)
        _text(subject["label"], "subject label", 4 if identity == hub_id else 8)
        if subject["preserve"] is not False:
            raise ValueError("relation subjects cannot be preserved")
        identities.append(identity)
    if len(set(identities)) != len(identities) or set(identities) != set(source_ids) | {hub_id}:
        raise ValueError("brief subjects differ from source_ids and hub_id")
    actions = motion.get("actions")
    expected_operations = ("reveal_sources", "draw_connections", "reveal_hub")
    expected_subjects = (set(source_ids), set(source_ids) | {hub_id}, {hub_id})
    if type(actions) is not list or len(actions) != 3:
        raise ValueError("relation motion must contain three actions")
    for index, action in enumerate(actions):
        if (
            type(action) is not dict
            or action.get("operation") != expected_operations[index]
            or type(action.get("subject_ids")) is not list
            or len(action["subject_ids"]) != len(expected_subjects[index])
            or set(action["subject_ids"]) != expected_subjects[index]
        ):
            raise ValueError("relation action subjects or order are invalid")
    return brief


def _approved_report(job: object, brief: Mapping[str, Any]) -> dict[str, Any]:
    from edit.hd.tools import semantic_motion

    try:
        report = semantic_motion.plan_motion_for_job(job, brief["motion"])
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        raise ValueError("RelationMotion requires a current approved content analysis") from exc
    if report.get("execution_status") != "planning_only" or report.get("plan") != brief["motion"]:
        raise ValueError("approved semantic motion differs from the brief")
    return report


def _registry_template(registry_path: str, registry_sha256: str) -> dict[str, Any]:
    registry = _registry_path(registry_path)
    if type(registry_sha256) is not str or len(registry_sha256) != 64 or _sha(registry) != registry_sha256:
        raise ValueError("registry hash mismatch")
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("registry is unreadable") from exc
    if type(payload) is not dict:
        raise ValueError("registry must contain a JSON object")
    templates = payload.get("templates")
    matches = [item for item in templates or [] if type(item) is dict and item.get("template_id") == TEMPLATE_ID]
    if payload.get("schema_version") != 1 or len(matches) != 1:
        raise ValueError("RelationMotion is not uniquely present in the selected registry")
    template = matches[0]
    if any(key not in template for key in PROVENANCE):
        raise ValueError("RelationMotion registry provenance is incomplete")
    return template


def create_adapter(
    *, python_executable, node_executable, playwright_module, browser_executable,
    ffmpeg_executable, ffprobe_executable, brief_loader,
    registry_path: str = DEFAULT_REGISTRY, registry_sha256: str,
):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter

    if not callable(brief_loader):
        raise ValueError("brief_loader must be callable")
    entry = _regular_file(SKILL / ENTRY, "frozen RelationMotion entrypoint", executable=False)
    dependencies = {
        "python": _regular_file(python_executable, "python_executable", executable=True),
        "node": _regular_file(node_executable, "node_executable", executable=True),
        "playwright": _regular_file(playwright_module, "playwright_module", executable=False),
        "browser": _regular_file(browser_executable, "browser_executable", executable=True),
        "ffmpeg": _regular_file(ffmpeg_executable, "ffmpeg_executable", executable=True),
        "ffprobe": _regular_file(ffprobe_executable, "ffprobe_executable", executable=True),
    }
    dependency_hashes = {name: _sha(path) for name, path in dependencies.items()}
    _registry_template(registry_path, registry_sha256)

    def guarded_loader(job, recipe, component):
        for name, path in dependencies.items():
            if _sha(path) != dependency_hashes[name]:
                raise ValueError(f"{name} dependency changed after adapter creation")
        payload = brief_loader(job, recipe, component)
        # Keep the callback on the executor's immutable envelope. Normalize only
        # afterwards: a loader must not rewrite the values being validated.
        recipe = json.loads(json.dumps(recipe))
        component = json.loads(json.dumps(component))
        brief = _parse_brief(payload)
        report = _approved_report(job, brief)
        invocation = component.get("invocation_record")
        if type(invocation) is not dict or invocation.get("semantic_motion") != report:
            raise ValueError("component semantic_motion differs from current approval")
        request = invocation.get("template_request")
        expected_request = {
            "semantic_family": "relation", "information_units": len(brief["source_ids"]),
            "numeric_values": [], "numeric_scale": "not_applicable",
        }
        canvas = brief["canvas"]
        window = component.get("render_window")
        contract = component.get("artifact_contract")
        if request != expected_request:
            raise ValueError("component template_request differs from the RelationMotion brief")
        if (
            type(recipe) is not dict
            or recipe.get("canvas") != {key: canvas[key] for key in ("width", "height", "fps")}
            or type(window) is not dict
            or type(window.get("start_frame")) is not int
            or type(window.get("end_frame")) is not int
            or window["end_frame"] - window["start_frame"] != canvas["duration_in_frames"]
            or type(contract) is not dict
            or any(contract.get(key) != value for key, value in (
                ("width", 1080), ("height", 1920),
                ("fps", 24), ("alpha", False),
            ))
        ):
            raise ValueError("brief differs from the approved opaque render window or canvas")
        return payload

    return ReferenceProcessAdapter(
        adapter_id="native-relation-motion-v1",
        dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter",
        dependency_root=SKILL,
        entrypoint=ENTRY,
        entrypoint_sha256=_sha(entry),
        producer_version=VERSION,
        primary_renderer="RelationMotion",
        renderer_version=VERSION,
        artifact_media_type="video",
        launcher=dependencies["python"],
        launcher_sha256=dependency_hashes["python"],
        brief_loader=guarded_loader,
        self_contained_wrapper=True,
        timeout_seconds=300,
        argv_template=(
            "{launcher}", "{entrypoint}", "--brief", "{brief_path}",
            "--output", "{output_path}", "--node", str(dependencies["node"]),
            "--playwright", str(dependencies["playwright"]),
            "--browser", str(dependencies["browser"]),
            "--ffmpeg", str(dependencies["ffmpeg"]),
            "--ffprobe", str(dependencies["ffprobe"]),
        ),
        qualification_registry_path=(
            None if registry_path == DEFAULT_REGISTRY else registry_path
        ),
        qualification_registry_sha256=(
            None if registry_path == DEFAULT_REGISTRY else registry_sha256
        ),
    )


def create_binding(
    adapter, job, brief_bytes: bytes, *,
    registry_path: str = DEFAULT_REGISTRY, registry_sha256: str,
) -> dict[str, object]:
    """Create a planned binding from a currently approved Job and exact brief."""
    if (
        getattr(adapter, "dependency_id", None) != DEPENDENCY_ID
        or getattr(adapter, "entrypoint", None) != ENTRY
        or getattr(adapter, "primary_renderer", None) != "RelationMotion"
        or getattr(adapter, "renderer_version", None) != VERSION
    ):
        raise ValueError("adapter does not have the approved RelationMotion identity")
    brief = _parse_brief(brief_bytes)
    report = _approved_report(job, brief)
    template = _registry_template(registry_path, registry_sha256)
    return {
        **{key: template[key] for key in PROVENANCE},
        "producer_type": "dependency",
        "dependency_id": adapter.dependency_id,
        "entrypoint": adapter.entrypoint,
        "producer_version": adapter.producer_version,
        "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version,
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {
            "argv": [str(adapter.launcher), adapter.entrypoint],
            "status": "planned",
            "exit_code": None,
            "template_request": {
                "semantic_family": "relation",
                "information_units": len(brief["source_ids"]),
                "numeric_values": [],
                "numeric_scale": "not_applicable",
            },
            "semantic_motion": report,
        },
    }


def create_artifact_probe(*, ffprobe_executable):
    """Create a strict native RelationMotion MP4 probe."""
    import subprocess
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    executable = _regular_file(ffprobe_executable, "ffprobe_executable", executable=True)
    executable_sha = _sha(executable)

    def probe(path, media_type, contract):
        if _sha(executable) != executable_sha:
            raise ValueError("ffprobe dependency changed after probe creation")
        if media_type != "video" or contract.get("alpha") is not False:
            raise ValueError("RelationMotion probe accepts only opaque video")
        inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
        result = subprocess.run(
            [str(executable), "-v", "error", "-count_frames", "-show_streams",
             "-show_format", "-of", "json", str(path)],
            pass_fds=inherited, capture_output=True, text=True, timeout=20, check=False,
        )
        if result.returncode:
            raise ValueError("RelationMotion ffprobe failed")
        payload = json.loads(result.stdout)
        streams = payload.get("streams")
        if type(streams) is not list or len(streams) != 1 or streams[0].get("codec_type") != "video":
            raise ValueError("RelationMotion output must contain one video stream")
        stream = streams[0]
        rotation = [item.get("rotation", 0) for item in stream.get("side_data_list", [])]
        rotation.append(stream.get("tags", {}).get("rotate", 0))
        fps = Fraction(stream.get("r_frame_rate", "0/1"))
        if (
            stream.get("width") != 1080 or stream.get("height") != 1920
            or fps != 24 or Fraction(stream.get("avg_frame_rate", "0/1")) != fps
            or stream.get("sample_aspect_ratio") != "1:1"
            or stream.get("codec_name") != "h264" or stream.get("pix_fmt") != "yuv420p"
            or any(float(value) != 0 for value in rotation)
            or "mp4" not in payload.get("format", {}).get("format_name", "").split(",")
        ):
            raise ValueError("RelationMotion output media contract failed")
        frames = int(stream.get("nb_read_frames", stream.get("nb_frames", 0)))
        return {
            "media_type": "video", "container": "mp4", "codec": "h264",
            "pixel_format": "yuv420p", "alpha": False, "width": 1080,
            "height": 1920, "fps": 24.0, "frame_count": frames,
            "duration": float(stream["duration"]),
        }

    return ArtifactProbe(
        probe_id="native-relation-motion-ffprobe",
        probe_version=VERSION,
        probe=probe,
    )

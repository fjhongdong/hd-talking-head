#!/usr/bin/env python3
"""Verify the integrity and 9:16 QA evidence of approved B-roll templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, List, Optional


class RegistryError(RuntimeError):
    """Raised when a verified-template record violates the contract."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROBE_TIMEOUT_SECONDS = 20
_TEMPLATE_FIELDS = {
    "template_origin",
    "template_id",
    "template_version",
    "verification_id",
    "adaptation_level",
    "upstream",
    "source_entrypoint",
    "source_sha256",
    "source_files",
    "sample_path",
    "sample_sha256",
    "semantic_families",
    "capacity",
    "artifact_contract",
    "render_contract",
    "visual_qa",
    "execution_qa",
}
_OPTIONAL_TEMPLATE_FIELDS = {"action_sequence_qa"}
_VERIFIED_ORIGINS = {"verified_third_party", "verified_local_canonical"}
_LOCAL_UPSTREAM = {
    "project": "hd-talking-head-local-canonical",
    "repository": ".",
}
_PROCESS_COMPOSITIONS = {"process-relations", "timeline-progression"}
_VISUAL_CHECKS = {
    "no_clipping",
    "no_overlap",
    "no_placeholder_copy",
    "balanced_layout",
    "decorations_anchored",
    "no_exit_jump",
}
PROVENANCE_FIELDS = frozenset({
    "template_origin", "template_id", "template_version", "verification_id",
    "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
    "semantic_families", "capacity",
})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{field} must be a non-empty string")
    return value


def _hash(value: object, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise RegistryError(f"{field} must be a lowercase SHA-256")
    return text


def _relative_asset(skill_root: Path, value: object, field: str) -> Path:
    text = _text(value, field)
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != text:
        raise RegistryError(f"{field} must be a job-safe POSIX path relative to the Skill")
    candidate = skill_root / relative
    cursor = skill_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RegistryError(f"{field} must not use symbolic links")
    resolved = candidate.resolve()
    if skill_root.resolve() not in resolved.parents:
        raise RegistryError(f"{field} escapes the Skill root")
    if not resolved.is_file():
        raise RegistryError(f"{field} does not exist: {text}")
    return resolved


def _exact_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise RegistryError(f"{label} fields must be exactly {sorted(fields)}")
    return value


def _verification_id(template: dict[str, Any]) -> str:
    payload = {key: value for key, value in template.items() if key != "verification_id"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _probe_video(path: Path) -> dict[str, Any]:
    try:
        process = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,"
                "sample_aspect_ratio,display_aspect_ratio,nb_frames,duration:"
                "stream_side_data=rotation:stream_tags=rotate:format=duration",
                "-of", "json", str(path),
            ],
            check=False, capture_output=True, text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RegistryError(f"ffprobe timed out after {_PROBE_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise RegistryError(f"ffprobe could not start: {exc}") from exc
    if process.returncode != 0:
        raise RegistryError(f"ffprobe failed for sample_path: {process.stderr.strip()[:1000]}")
    try:
        payload = json.loads(process.stdout)
        stream = payload["streams"][0]
        # Audio padding can outlast the last visible video frame.
        duration = float(stream["duration"] if "duration" in stream else payload["format"]["duration"])
        fps = float(Fraction(stream["r_frame_rate"]))
        average_fps = float(Fraction(stream["avg_frame_rate"]))
        sar = Fraction(stream["sample_aspect_ratio"].replace(":", "/"))
        dar = Fraction(stream["display_aspect_ratio"].replace(":", "/"))
        rotations = [float(item["rotation"]) for item in stream.get("side_data_list", [])
                     if "rotation" in item]
        if "rotate" in stream.get("tags", {}):
            rotations.append(float(stream["tags"]["rotate"]))
    except (KeyError, IndexError, TypeError, ValueError, AttributeError,
            ZeroDivisionError, OverflowError) as exc:
        raise RegistryError("sample_path has no readable video stream") from exc
    if not all(math.isfinite(n) and n > 0 for n in (duration, fps, average_fps)):
        raise RegistryError("sample fps and duration must be finite positive numbers")
    if type(stream.get("width")) is not int or type(stream.get("height")) is not int:
        raise RegistryError("sample dimensions must be integers")
    if (stream["width"], stream["height"]) != (1080, 1920) or sar != 1 or dar != Fraction(9, 16):
        raise RegistryError("sample must be native 1080x1920 with SAR 1:1 and DAR 9:16")
    if any(not math.isfinite(rotation) or rotation != 0 for rotation in rotations):
        raise RegistryError("sample must have zero display rotation for native 9:16 playback")
    if abs(fps - average_fps) > 0.001:
        raise RegistryError("sample average fps differs from nominal fps")
    raw_frames = stream.get("nb_frames")
    frame_count = int(raw_frames) if isinstance(raw_frames, str) and raw_frames.isdecimal() else None
    return {
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": fps,
        "duration": duration,
        "sar": "1:1",
        "dar": "9:16",
        "rotation": 0,
        "frame_count": frame_count,
    }


def verify_production_video(path: Path, *, expected_frames: int) -> dict[str, Any]:
    """Check this render's timing; historical registry QA is not current QA."""
    if type(expected_frames) is not int or expected_frames <= 0:
        raise RegistryError("expected_frames must be a positive integer")
    probe = _probe_video(path)
    if abs(probe["fps"] - 24) > 0.001:
        raise RegistryError("production video must be 24fps, not a historical sample")
    if probe["frame_count"] != expected_frames:
        raise RegistryError("production frame_count does not match the approved render window")
    if abs(probe["duration"] - expected_frames / 24) > 1 / 24:
        raise RegistryError("production duration does not match the approved render window")
    return probe


def _proof_asset(root: Path, reference: object, label: str) -> Path:
    ref = _exact_object(reference, {"path", "sha256"}, label)
    path = _relative_asset(root, ref["path"], label + ".path")
    if _sha256(path) != _hash(ref["sha256"], label + ".sha256"):
        raise RegistryError(f"{label} attachment hash mismatch")
    return path


def _proof_json(root: Path, reference: object, label: str) -> dict[str, Any]:
    path = _proof_asset(root, reference, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"{label} must contain readable JSON") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"{label} must contain a JSON object")
    return value


def _relation_template_request(brief: dict[str, Any]) -> dict[str, Any]:
    """Derive routing metadata; full motion/geometry validation remains separate."""
    if set(brief) != {"schema_version", "canvas", "motion", "title", "source_ids", "hub_id"}:
        raise RegistryError("relation brief must have exactly six fields")
    sources, hub, motion = brief["source_ids"], brief["hub_id"], brief["motion"]
    if (type(sources) is not list or not 2 <= len(sources) <= 4
            or any(type(value) is not str or not value for value in sources)
            or len(set(sources)) != len(sources) or type(hub) is not str
            or not hub or hub in sources or type(motion) is not dict
            or motion.get("family") != "relation"):
        raise RegistryError("relation brief sources/hub/family mismatch")
    subjects = motion.get("subjects")
    if (type(subjects) is not list or len(subjects) != len(sources) + 1
            or any(type(subject) is not dict or type(subject.get("id")) is not str for subject in subjects)
            or {subject["id"] for subject in subjects} != set(sources) | {hub}):
        raise RegistryError("relation brief subjects mismatch")
    return {"semantic_family": "relation", "information_units": len(sources),
            "numeric_values": [], "numeric_scale": "not_applicable"}


def _semantic_state_template_request(brief: dict[str, Any], family: str) -> dict[str, Any]:
    """Derive content counts only; renderer role/geometry validation is separate."""
    if (type(brief) is not dict
            or set(brief) != {"schema_version", "canvas", "motion", "title", "roles"}
            or type(brief.get("roles")) is not dict):
        raise RegistryError("semantic brief fields are invalid")
    motion = brief["motion"]
    if (family not in ("replacement", "threshold", "delay", "hierarchy", "feedback")
            or type(motion) is not dict or motion.get("family") != family):
        raise RegistryError("semantic brief family differs from template")
    subjects = motion.get("subjects")
    if (type(subjects) is not list or not 2 <= len(subjects) <= 4
            or any(type(subject) is not dict or type(subject.get("id")) is not str
                   or not subject["id"].strip() for subject in subjects)
            or len({subject["id"] for subject in subjects}) != len(subjects)):
        raise RegistryError("semantic brief subjects are invalid")
    return {"semantic_family": family, "information_units": len(subjects),
            "numeric_values": [], "numeric_scale": "not_applicable"}


def _proof_content(brief: dict[str, Any], pointer: str, *, relation: bool = False) -> object:
    # Qualification briefs keep content under props.data, separate from style
    # and duration. Changing a background alone is not a content-binding test.
    if relation:
        if pointer not in ("/title", "/motion/source_text", "/motion/subjects"):
            raise RegistryError("relation content_paths must address title or motion content")
    elif not isinstance(pointer, str) or not pointer.startswith("/props/data/"):
        raise RegistryError("execution_qa.content_paths must address props.data")
    value: object = brief
    for raw in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", raw):
            raise RegistryError("execution_qa.content_paths contains an invalid JSON pointer")
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise RegistryError("execution_qa.content_paths does not resolve to actual content")
        value = value[key]
    return value


def _decoded_frame_hashes(path: Path, indices: Optional[List[int]] = None) -> List[str]:
    """Decode RGB pixels, without resizing, so a PNG must match its video frame."""
    command = ["ffmpeg", "-v", "error", "-xerror", "-threads", "1",
               "-filter_threads", "1", "-noautorotate", "-i", str(path),
               "-map", "0:v:0", "-an"]
    if indices is not None:
        command += ["-vf", "select=" + "+".join(f"eq(n\\,{n})" for n in indices),
                    "-fps_mode", "vfr"]
    count = len(indices) if indices is not None else 1
    command += ["-frames:v", str(count), "-pix_fmt", "rgb24", "-threads", "1",
                "-f", "framehash", "-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=_PROBE_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RegistryError(f"execution_qa.frame_evidence decoder unavailable: {exc}") from exc
    lines = result.stdout.splitlines()
    if result.returncode != 0 or "#dimensions 0: 1080x1920" not in lines:
        raise RegistryError("execution_qa.frame_evidence must decode at native 1080x1920")
    hashes = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 6 or fields[4] != "6220800" or not _SHA256.fullmatch(fields[5]):
            raise RegistryError("execution_qa.frame_evidence has unreadable RGB frame hashes")
        hashes.append(fields[5])
    if len(hashes) != count:
        raise RegistryError("execution_qa.frame_evidence has missing decoded frames")
    return hashes


def _verify_registry_invocation(evidence: dict[str, Any], reference: dict[str, Any], *, relation: bool) -> None:
    argv = evidence.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(s, str) and s for s in argv):
        raise RegistryError("receipt invocation argv is invalid")
    if relation:
        # The native bundle consumes the brief, not a registry CLI flag. The
        # executor records its validated candidate identity in the receipt.
        if type(evidence.get("qualification_registry")) is not dict or evidence["qualification_registry"] != reference:
            raise RegistryError("receipt invocation does not bind source_registry")
    elif (argv.count("--registry-sha256") != 1
          or argv.index("--registry-sha256") + 1 >= len(argv)
          or argv[argv.index("--registry-sha256") + 1] != reference["sha256"]):
        raise RegistryError("receipt invocation does not bind source_registry")


def _is_relation_template(item: dict[str, Any]) -> bool:
    return (
        item.get("template_origin") == "verified_local_canonical"
        and item.get("template_id") == "hd-talking-head/relation-motion"
        and item.get("source_entrypoint") == "scripts/relation_motion_renderer_bundle.py"
        and item.get("upstream", {}).get("project") == "hd-talking-head-relation-motion"
        and item.get("render_contract", {}).get("engine") == "RelationMotion"
        and item.get("render_contract", {}).get("composition_id") == "relation-motion"
    )


def _is_semantic_state_template(item: dict[str, Any]) -> bool:
    families = ("replacement", "threshold", "delay", "hierarchy", "feedback")
    return (
        item.get("template_origin") == "verified_local_canonical"
        and item.get("source_entrypoint") == "scripts/semantic_state_renderer_bundle.py"
        and item.get("upstream", {}).get("project") == "hd-talking-head-semantic-state"
        and item.get("render_contract", {}).get("engine") == "SemanticState"
        and any(item.get("template_id") == "hd-talking-head/semantic-state-" + family
                and item.get("render_contract", {}).get("composition_id") == "semantic-state-" + family
                for family in families)
    )


def _verify_published_execution(receipt: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    """Check a single-component qualification export without accessing old tools."""
    if type(receipt) is not dict or type(recipe) is not dict:
        raise RegistryError("published_execution receipt/recipe must be objects")
    exported = _exact_object(receipt.get("published_execution"), {
        "schema_version", "state", "input_sha256", "recipe_sha256", "segment_id",
        "component_id", "strategy_revision", "kind", "adapter_binding",
        "output_job_path", "output_sha256", "byte_count", "artifact_sha256",
    }, "published_execution")
    artifact = receipt.get("artifact")
    if type(artifact) is not dict:
        raise RegistryError("published_execution artifact missing")
    for key in ("component_id", "kind", "segment_id", "job_path"):
        _text(artifact.get(key), "artifact." + key)
    for key in ("input_sha256", "output_sha256"):
        _hash(artifact.get(key), "artifact." + key)
    if type(artifact.get("byte_count")) is not int or artifact["byte_count"] <= 0:
        raise RegistryError("artifact.byte_count must be a positive integer")
    path = artifact["job_path"]
    if (path.startswith("/") or "\\" in path or "\x00" in path
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise RegistryError("artifact.job_path must be a canonical job-relative path")
    components = recipe.get("components")
    if (type(components) is not list or len(components) != 1
            or type(components[0]) is not dict
            or components[0].get("component_id") != artifact["component_id"]
            or components[0].get("kind") != artifact["kind"]
            or artifact["segment_id"] != recipe.get("segment_id")):
        raise RegistryError("published_execution artifact differs from recipe component")
    def digest(value: object) -> str:
        try:
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        except (TypeError, ValueError) as exc:
            raise RegistryError("published_execution contains invalid JSON") from exc
    expected = {
        "schema_version": 1, "state": "published",
        "recipe_sha256": digest(recipe), "artifact_sha256": digest(artifact),
        "input_sha256": digest({"recipe": recipe, "component_id": artifact.get("component_id")}),
        "segment_id": recipe.get("segment_id"), "strategy_revision": recipe.get("strategy_revision"),
        "component_id": artifact.get("component_id"), "kind": artifact.get("kind"),
        "output_job_path": artifact.get("job_path"), "output_sha256": artifact.get("output_sha256"),
        "byte_count": artifact.get("byte_count"),
    }
    if (type(exported["schema_version"]) is not int
            or any(type(exported[key]) is not type(value) or exported[key] != value
                   for key, value in expected.items())
            or exported["input_sha256"] != artifact.get("input_sha256")):
        raise RegistryError("published_execution differs from recipe or artifact")
    binding = exported["adapter_binding"]
    if type(binding) is not dict or binding.get("adapter_type") != "reference_process":
        raise RegistryError("published_execution requires reference binding")
    evidence = artifact.get("invocation_evidence")
    if type(evidence) is not dict:
        raise RegistryError("published_execution invocation evidence missing")
    identity_fields = {
        "adapter_id": "adapter_id", "dependency_id": "dependency_id",
        "approved_executor": "approved_executor", "entrypoint": "approved_entrypoint",
        "entrypoint_sha256": "entrypoint_sha256", "launcher_sha256": "launcher_sha256",
        "producer_version": "producer_version", "primary_renderer": "primary_renderer",
        "renderer_version": "renderer_version", "probe_id": "probe_id", "probe_version": "probe_version",
    }
    for key, evidence_key in identity_fields.items():
        value = _text(binding.get(key), "adapter_binding." + key)
        if key.endswith("sha256"):
            _hash(value, "adapter_binding." + key)
        if evidence.get(evidence_key) != value:
            raise RegistryError("published_execution binding differs from invocation: " + key)
    registry = _exact_object(binding.get("qualification_registry"), {"path", "sha256"},
                             "adapter_binding.qualification_registry")
    _text(registry["path"], "adapter_binding.qualification_registry.path")
    _hash(registry["sha256"], "adapter_binding.qualification_registry.sha256")
    if evidence.get("qualification_registry") != registry:
        raise RegistryError("published_execution registry differs from invocation")
    template, argv = binding.get("argv_template"), evidence.get("argv")
    _hash(binding.get("argv_template_sha256"), "adapter_binding.argv_template_sha256")
    if (type(template) is not list or not template or type(argv) is not list
            or len(template) != len(argv)):
        raise RegistryError("published_execution argv shape mismatch")
    roles = []
    tokens = {"launcher": "$LAUNCHER", "entrypoint": "$DEPENDENCY/" + binding["entrypoint"],
              "brief": "$JOB/brief.json"}
    for index, raw in enumerate(template):
        item = _exact_object(raw, {"index", "role", "value"}, "argv_template item")
        role = item["role"]
        if (type(item["index"]) is not int or item["index"] != index
                or type(role) is not str or role not in {*tokens, "output", "literal"}):
            raise RegistryError("published_execution argv template invalid")
        actual = _text(argv[index], "invocation.argv")
        roles.append(role)
        if role == "literal":
            if actual != _text(item["value"], "argv_template.value"):
                raise RegistryError("published_execution literal argv mismatch")
        elif item["value"] is not None:
            raise RegistryError("published_execution token value must be null")
        elif role == "output":
            if (not actual.startswith("$JOB/") or "\\" in actual or "\x00" in actual
                    or any(part in ("", ".", "..") for part in actual[5:].split("/"))):
                raise RegistryError("published_execution output argv invalid")
        elif actual != tokens[role]:
            raise RegistryError("published_execution token argv mismatch")
    if any(roles.count(role) != 1 for role in (*tokens, "output")):
        raise RegistryError("published_execution requires unique argv tokens")
    if (binding["dependency_id"] == "hd-talking-head-semantic-state"
            or "runtime_contracts" in binding or "runtime_contracts" in evidence):
        _verify_runtime_contract_binding(binding, evidence)
    return binding


def _normalize_historical_runtime_contracts(value: object) -> dict[str, Any]:
    """Validate recorded runtime identities without reading their historical paths."""
    names = {"node", "playwright", "browser", "ffmpeg", "ffprobe"}
    if type(value) is not dict or set(value) != names:
        raise RegistryError("runtime contracts require exactly five tools")

    def path(raw: object, field: str) -> Path:
        text = _text(raw, field)
        result = Path(text)
        if ("\x00" in text or not result.is_absolute() or ".." in result.parts
                or str(result) != text):
            raise RegistryError(field + " must be a canonical absolute path")
        return result

    for name, raw in value.items():
        if type(raw) is not dict:
            raise RegistryError("runtime contract must be an object: " + name)
        tree = name in {"playwright", "browser"}
        fields = {"kind", "path", "version", "roots" if tree else "sha256"}
        if not tree and "libraries" in raw:
            fields.add("libraries")
        if not tree and "library_discovery" in raw:
            fields.add("library_discovery")
        if set(raw) != fields or raw.get("kind") != ("directory_tree" if tree else "file_snapshot"):
            raise RegistryError("runtime contract fields or kind invalid: " + name)
        entry = path(raw["path"], "runtime." + name + ".path")
        version = _text(raw["version"], "runtime." + name + ".version")
        if len(version) > 128 or any(ord(char) < 32 for char in version):
            raise RegistryError("runtime version invalid: " + name)
        if tree:
            roots = raw["roots"]
            if type(roots) is not list or not 1 <= len(roots) <= 16:
                raise RegistryError("runtime roots invalid: " + name)
            paths = []
            for root in roots:
                root = _exact_object(root, {"path", "sha256"}, "runtime root")
                paths.append(path(root["path"], "runtime root path"))
                _hash(root["sha256"], "runtime root sha256")
            if len(set(paths)) != len(paths) or not any(root in entry.parents for root in paths):
                raise RegistryError("runtime roots do not contain entry: " + name)
            continue
        _hash(raw["sha256"], "runtime." + name + ".sha256")
        libraries = raw.get("libraries", [])
        if type(libraries) is not list or len(libraries) > 512:
            raise RegistryError("runtime libraries invalid: " + name)
        discovery = raw.get("library_discovery")
        if discovery is not None and (discovery != "mach_o_static_v1" or "libraries" not in raw):
            raise RegistryError("runtime library discovery invalid: " + name)
        paths, aliases = {entry}, set()
        for library in libraries:
            if type(library) is not dict:
                raise RegistryError("runtime library must be an object")
            allowed = {"path", "sha256", "load_paths"} if "load_paths" in library else {"path", "sha256"}
            library = _exact_object(library, allowed, "runtime library")
            library_path = path(library["path"], "runtime library path")
            if library_path in paths:
                raise RegistryError("duplicate runtime library path")
            paths.add(library_path)
            _hash(library["sha256"], "runtime library sha256")
            if discovery is not None and "load_paths" not in library:
                raise RegistryError("discovered runtime library requires load paths")
            if "load_paths" in library:
                load_paths = library["load_paths"]
                if type(load_paths) is not list or not 1 <= len(load_paths) <= 512:
                    raise RegistryError("runtime library load paths invalid")
                for alias in load_paths:
                    alias_path = path(alias, "runtime library load path")
                    if alias_path in aliases:
                        raise RegistryError("duplicate runtime library load path")
                    aliases.add(alias_path)
                    if len(aliases) > 512:
                        raise RegistryError("runtime library load path limit exceeded")
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _verify_runtime_contract_binding(binding: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    recorded = _normalize_historical_runtime_contracts(binding.get("runtime_contracts"))
    if any(recorded[name].get("library_discovery") != "mach_o_static_v1"
           or "libraries" not in recorded[name] for name in ("node", "ffmpeg", "ffprobe")):
        raise RegistryError("semantic runtime requires static library discovery")
    if _normalize_historical_runtime_contracts(evidence.get("runtime_contracts")) != recorded:
        raise RegistryError("runtime contracts differ from invocation")
    argv = evidence.get("argv")
    flag = "--runtime-contracts"
    if type(argv) is not list or argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv):
        raise RegistryError("runtime contracts argv missing")
    raw = argv[argv.index(flag) + 1]
    if type(raw) is not str or len(raw.encode("utf-8")) > 65536:
        raise RegistryError("runtime contracts argv invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, item in items:
            if key in result:
                raise RegistryError("runtime contracts argv has duplicate keys")
            result[key] = item
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except RegistryError:
        raise
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RegistryError("runtime contracts argv is not strict JSON") from exc
    if _normalize_historical_runtime_contracts(parsed) != recorded:
        raise RegistryError("runtime contracts argv differs from binding")
    return recorded


def _verify_execution_pair(root: Path, item: dict[str, Any]) -> None:
    relation = _is_relation_template(item)
    semantic = _is_semantic_state_template(item)
    qa = _exact_object(item["execution_qa"], {
        "status", "reviewed_at", "reviewer", "content_paths", "source_registry", "cases",
    }, "execution_qa")
    if qa["status"] != "reviewed":
        raise RegistryError("execution_qa must be reviewed, not pending")
    for key in ("reviewed_at", "reviewer"):
        _text(qa[key], "execution_qa." + key)
    paths = qa["content_paths"]
    if (not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths)
            or len(set(paths)) != len(paths)):
        raise RegistryError("execution_qa.content_paths must be unique and nonempty")
    cases = qa["cases"]
    if not isinstance(cases, list) or len(cases) != 2:
        raise RegistryError("execution_qa requires exactly two distinct input/output cases")

    # Preserve the exact registry used by the real process. Adding evidence
    # changes today's verification_id; it must not rewrite historical receipts.
    snapshot = _proof_json(root, qa["source_registry"], "execution_qa.source_registry")
    templates = snapshot.get("templates")
    if type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1 or not isinstance(templates, list):
        raise RegistryError("execution_qa.source_registry has an invalid schema")
    matches = [t for t in templates if isinstance(t, dict) and t.get("template_id") == item["template_id"]]
    native_fields = (PROVENANCE_FIELDS - {"verification_id"}) | {"upstream", "source_files", "render_contract"}
    if (len(matches) != 1 or matches[0].get("verification_id") != _verification_id(matches[0])
            or any(matches[0].get(k) != item[k] for k in native_fields)):
        raise RegistryError("execution_qa.source_registry differs from the native template identity")
    previous = matches[0]
    brief_hashes, output_hashes, stable_hashes, invocation_ids = set(), set(), set(), set()
    contents = []
    for index, raw in enumerate(cases):
        label = f"execution_qa.cases[{index}]"
        case = _exact_object(raw, {"brief", "recipe", "receipt", "sample", "frame_evidence"}, label)
        brief = _proof_json(root, case["brief"], label + ".brief")
        recipe = _proof_json(root, case["recipe"], label + ".recipe")
        receipt = _proof_json(root, case["receipt"], label + ".receipt")
        sample = _proof_asset(root, case["sample"], label + ".sample")
        contents.append([_proof_content(brief, pointer, relation=relation or semantic) for pointer in paths])
        brief_hashes.add(case["brief"]["sha256"])
        output_hashes.add(case["sample"]["sha256"])
        canvas = brief["canvas"]
        frames = canvas["duration_in_frames"]
        if (type(brief.get("schema_version")) is not int or brief["schema_version"] != 1
                or any(type(canvas.get(k)) is not int or canvas[k] != v for k, v in
                       (("width", 1080), ("height", 1920), ("fps", 24)))
                or recipe.get("schema_version") != 2 or recipe.get("mode") != "single"
                or recipe["canvas"] != {"width": 1080, "height": 1920, "fps": 24}
                or len(recipe["components"]) != 1):
            raise RegistryError(label + ".brief/recipe canvas or single-component schema mismatch")
        component = recipe["components"][0]
        expected_request = _relation_template_request(brief) if relation else brief.get("template_request")
        if semantic:
            family = item["template_id"].removeprefix("hd-talking-head/semantic-state-")
            expected_request = _semantic_state_template_request(brief, family)
        renderer = _text(component.get("primary_renderer"), label + ".recipe.primary_renderer")
        if (any(component.get(k) != previous[k] for k in PROVENANCE_FIELDS)
                or renderer.lower() != item["render_contract"]["engine"].lower()
                or component.get("kind") != "code_generated"
                or component.get("brief_sha256") != case["brief"]["sha256"]
                or component["invocation_record"].get("template_request") != expected_request):
            raise RegistryError(label + ".recipe source/renderer/request differs from the brief or template")
        window = component["render_window"]
        if (type(window.get("start_frame")) is not int or type(window.get("end_frame")) is not int
                or window["end_frame"] - window["start_frame"] != frames):
            raise RegistryError(label + ".recipe frame window differs from the brief")
        artifact = receipt["artifact"]
        evidence = artifact["invocation_evidence"]
        input_hash = hashlib.sha256(json.dumps(
            {"recipe": recipe, "component_id": component["component_id"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if (artifact.get("status") != "success" or artifact.get("kind") != "code_generated"
                or artifact.get("component_id") != component["component_id"]
                or artifact.get("segment_id") != recipe["segment_id"]
                or artifact.get("input_sha256") != input_hash
                or artifact.get("strategy_revision") != recipe["strategy_revision"]
                or artifact.get("artifact_contract") != component["artifact_contract"]
                or artifact.get("render_window") != window
                or artifact.get("output_sha256") != case["sample"]["sha256"]
                or artifact.get("byte_count") != sample.stat().st_size
                or artifact["qa"].get("passed") is not True):
            raise RegistryError(label + ".receipt artifact does not match the recipe/output")
        expected = {
            "approved_entrypoint": component["entrypoint"], "producer_version": component["producer_version"],
            "dependency_id": component["dependency_id"], "primary_renderer": renderer,
            "renderer_version": component["renderer_version"], "brief_sha256": case["brief"]["sha256"],
            "output_sha256": case["sample"]["sha256"], "output_job_path": artifact["job_path"],
            "approved_executor": component["executor"], "kind": "code_generated",
        }
        if (any(evidence.get(k) != v for k, v in expected.items())
                or evidence.get("invocation_type") != "reference_process"
                or type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0
                or type(evidence.get("pid")) is not int or evidence["pid"] <= 0
                or evidence.get("timed_out") is not False
                or evidence.get("unresolved_process_group") is not False):
            raise RegistryError(label + ".receipt invocation failed, unfinished or identity mismatch")
        invocation_ids.add(_text(evidence.get("invocation_id"), label + ".receipt.invocation_id"))
        if semantic:
            binding = _verify_published_execution(receipt, recipe)
            if binding["qualification_registry"] != qa["source_registry"]:
                raise RegistryError(label + ".published execution does not bind source_registry")
        _proof_asset(root, {"path": evidence["approved_entrypoint"], "sha256": evidence["entrypoint_sha256"]}, label + ".entrypoint")
        _verify_registry_invocation(evidence, qa["source_registry"], relation=relation or semantic)
        probe = verify_production_video(sample, expected_frames=frames)
        reported = artifact["media_probe"]
        if (any(reported.get(k) != probe[k] for k in ("width", "height", "fps", "frame_count", "codec"))
                or type(reported.get("duration")) not in (int, float)
                or not math.isfinite(reported["duration"])
                or abs(reported["duration"] - probe["duration"]) > 1 / 24):
            raise RegistryError(label + ".receipt media_probe differs from actual video")
        evidence_frames = case["frame_evidence"]
        if not isinstance(evidence_frames, list) or len(evidence_frames) != 3:
            raise RegistryError(label + ".frame_evidence requires three states")
        times = {}
        decoded = {}
        for frame in evidence_frames:
            frame = _exact_object(frame, {"role", "timestamp_sec", "path", "sha256"}, label + ".frame_evidence")
            role, time = frame["role"], frame["timestamp_sec"]
            if (role not in ("entry", "stable", "exit") or role in times
                    or type(time) not in (int, float) or not 0 <= time < probe["duration"]):
                raise RegistryError(label + ".frame_evidence role or timestamp is invalid")
            if abs(time * 24 - round(time * 24)) > 0.000001:
                raise RegistryError(label + ".frame_evidence timestamp must be on a frame boundary")
            times[role] = time
            path = _proof_asset(root, {"path": frame["path"], "sha256": frame["sha256"]}, label + ".frame_evidence")
            with path.open("rb") as image_file:
                if image_file.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RegistryError(label + ".frame_evidence must be an actual PNG")
            decoded[role] = _decoded_frame_hashes(path)[0]
            if role == "stable":
                stable_hashes.add(decoded[role])
        if not times["entry"] < times["stable"] < times["exit"]:
            raise RegistryError(label + ".frame_evidence must follow entry < stable < exit")
        roles = ("entry", "stable", "exit")
        indices = [round(times[role] * 24) for role in roles]
        if _decoded_frame_hashes(sample, indices) != [decoded[role] for role in roles]:
            raise RegistryError(label + ".frame_evidence pixels differ from the sample at recorded times")
    if any(a == b for a, b in zip(*contents)):
        raise RegistryError("execution_qa.content_paths must each vary between actual input cases")
    if any(len(values) != 2 for values in (brief_hashes, output_hashes, stable_hashes, invocation_ids)):
        raise RegistryError("execution_qa requires distinct briefs, sample outputs, stable frames and invocation IDs")


def _verify_template(
    skill_root: Path,
    template: object,
    *,
    require_execution: bool = True,
) -> dict[str, Any]:
    fields = _TEMPLATE_FIELDS if require_execution else _TEMPLATE_FIELDS - {"execution_qa"}
    if not isinstance(template, dict):
        raise RegistryError(f"template fields must be exactly {sorted(fields)}")
    extras = set(template) - fields
    if extras - _OPTIONAL_TEMPLATE_FIELDS:
        raise RegistryError(f"template fields must be exactly {sorted(fields)}")
    item = _exact_object(template, fields | extras, "template")
    template_id = _text(item["template_id"], "template_id")
    origin = item["template_origin"]
    if origin not in _VERIFIED_ORIGINS:
        raise RegistryError(
            "template_origin must be verified_third_party or verified_local_canonical"
        )
    if item["adaptation_level"] not in {"tokens_only", "content_reflow", "structural"}:
        raise RegistryError(
            "adaptation_level must be tokens_only, content_reflow, or structural"
        )
    if origin == "verified_third_party" and item["adaptation_level"] == "structural":
        raise RegistryError(
            "adaptation_level structural cannot claim verified_third_party"
        )
    _text(item["template_version"], "template_version")
    verification_id = _hash(item["verification_id"], "verification_id")
    if verification_id != _verification_id(item):
        raise RegistryError("verification_id does not match the canonical template record")

    upstream = _exact_object(
        item["upstream"], {"project", "repository", "commit"}, "upstream"
    )
    _text(upstream["project"], "upstream.project")
    _text(upstream["repository"], "upstream.repository")
    _text(upstream["commit"], "upstream.commit")
    local_upstream = (
        {"project": "hd-talking-head-relation-motion", "repository": "."}
        if _is_relation_template(item) else _LOCAL_UPSTREAM
    )
    if _is_semantic_state_template(item):
        local_upstream = {"project": "hd-talking-head-semantic-state", "repository": "."}
    if origin == "verified_local_canonical" and any(
        upstream[key] != expected for key, expected in local_upstream.items()
    ):
        raise RegistryError(
            "local canonical upstream.project/repository must identify the main Skill"
        )

    source_path = _relative_asset(
        skill_root, item["source_entrypoint"], "source_entrypoint"
    )
    source_hash = _hash(item["source_sha256"], "source_sha256")
    if _sha256(source_path) != source_hash:
        raise RegistryError("source_sha256 does not match source_entrypoint")
    source_files = item["source_files"]
    if not isinstance(source_files, list) or not source_files:
        raise RegistryError("source_files must be a non-empty list")
    seen_source_paths: set[str] = set()
    for index, source in enumerate(source_files):
        record = _exact_object(source, {"path", "sha256"}, f"source_files[{index}]")
        source_name = _text(record["path"], f"source_files[{index}].path")
        if source_name in seen_source_paths:
            raise RegistryError("source_files paths must be unique")
        seen_source_paths.add(source_name)
        path = _relative_asset(skill_root, source_name, f"source_files[{index}].path")
        expected = _hash(record["sha256"], f"source_files[{index}].sha256")
        if _sha256(path) != expected:
            raise RegistryError(f"source_files[{index}].sha256 does not match")
    if item["source_entrypoint"] not in seen_source_paths:
        raise RegistryError("source_files must include source_entrypoint")

    sample_path = _relative_asset(skill_root, item["sample_path"], "sample_path")
    sample_hash = _hash(item["sample_sha256"], "sample_sha256")
    if _sha256(sample_path) != sample_hash:
        raise RegistryError("sample_sha256 does not match sample_path")

    families = item["semantic_families"]
    if (
        not isinstance(families, list)
        or not families
        or not all(isinstance(value, str) and value.strip() for value in families)
        or len(set(families)) != len(families)
    ):
        raise RegistryError("semantic_families must be a unique non-empty string list")
    capacity = _exact_object(
        item["capacity"], {"min_units", "max_units"}, "capacity"
    )
    if (
        isinstance(capacity["min_units"], bool)
        or isinstance(capacity["max_units"], bool)
        or not isinstance(capacity["min_units"], int)
        or not isinstance(capacity["max_units"], int)
        or capacity["min_units"] <= 0
        or capacity["min_units"] > capacity["max_units"]
    ):
        raise RegistryError(
            "capacity must be positive integers with min_units <= max_units"
        )

    artifact = _exact_object(
        item["artifact_contract"],
        {"width", "height", "fps", "duration_min_sec", "duration_max_sec", "codec"},
        "artifact_contract",
    )
    if type(artifact["width"]) is not int or type(artifact["height"]) is not int or (
        artifact["width"], artifact["height"]
    ) != (1080, 1920):
        raise RegistryError("artifact_contract must be native 1080x1920")
    for field in ("fps", "duration_min_sec", "duration_max_sec"):
        value = artifact[field]
        if type(value) not in {int, float} or not 0 < value <= sys.float_info.max:
            raise RegistryError(f"artifact_contract.{field} must be finite and positive")
    if (
        artifact["duration_min_sec"] > artifact["duration_max_sec"]
    ):
        raise RegistryError("artifact_contract duration range is invalid")
    _text(artifact["codec"], "artifact_contract.codec")
    probe = _probe_video(sample_path)
    if probe["width"] != 1080 or probe["height"] != 1920:
        raise RegistryError("sample_path is not native 1080x1920")
    if probe["codec"] != artifact["codec"]:
        raise RegistryError("sample codec does not match artifact_contract")
    if abs(probe["fps"] - float(artifact["fps"])) > 0.001:
        raise RegistryError("sample fps does not match artifact_contract")
    if not artifact["duration_min_sec"] <= probe["duration"] <= artifact["duration_max_sec"]:
        raise RegistryError("sample duration is outside artifact_contract")

    render = _exact_object(
        item["render_contract"],
        {"engine", "composition_id", "exit_policy"},
        "render_contract",
    )
    _text(render["engine"], "render_contract.engine")
    _text(render["composition_id"], "render_contract.composition_id")
    if render["exit_policy"] not in {"template", "external_compositor"}:
        raise RegistryError("render_contract.exit_policy is invalid")

    action_qa = item.get("action_sequence_qa")
    if render["composition_id"] in _PROCESS_COMPOSITIONS and action_qa is None:
        raise RegistryError("process template requires action_sequence_qa")
    if action_qa is not None:
        action = _exact_object(
            action_qa,
            {"status", "reviewed_at", "reviewer", "events"},
            "action_sequence_qa",
        )
        if action["status"] != "approved":
            raise RegistryError("action_sequence_qa.status must be approved")
        _text(action["reviewed_at"], "action_sequence_qa.reviewed_at")
        _text(action["reviewer"], "action_sequence_qa.reviewer")
        events = action["events"]
        if not isinstance(events, list) or len(events) < 3:
            raise RegistryError("action_sequence_qa.events requires at least three events")
        seen_events: set[str] = set()
        previous_time = -1.0
        for index, raw_event in enumerate(events):
            event = _exact_object(
                raw_event, {"event", "timestamp_sec", "path", "sha256"},
                f"action_sequence_qa.events[{index}]",
            )
            event_name = _text(event["event"], f"action_sequence_qa.events[{index}].event")
            timestamp = event["timestamp_sec"]
            if (
                event_name in seen_events
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or not previous_time < timestamp < probe["duration"]
            ):
                raise RegistryError("action_sequence_qa events must be unique and time ordered")
            seen_events.add(event_name)
            previous_time = float(timestamp)
            _proof_asset(
                skill_root, {"path": event["path"], "sha256": event["sha256"]},
                f"action_sequence_qa.events[{index}]",
            )

    qa = _exact_object(
        item["visual_qa"],
        {"status", "reviewed_at", "reviewer", "frame_evidence", "checks"},
        "visual_qa",
    )
    if qa["status"] != "approved":
        raise RegistryError("visual_qa.status must be approved")
    _text(qa["reviewed_at"], "visual_qa.reviewed_at")
    _text(qa["reviewer"], "visual_qa.reviewer")
    checks = _exact_object(qa["checks"], _VISUAL_CHECKS, "visual_qa.checks")
    if any(value is not True for value in checks.values()):
        raise RegistryError("all visual_qa.checks must be true")
    evidence = qa["frame_evidence"]
    if not isinstance(evidence, list) or len(evidence) != 3:
        raise RegistryError("visual_qa.frame_evidence must contain entry, stable, and exit")
    roles: set[str] = set()
    times: dict[str, float] = {}
    for index, frame in enumerate(evidence):
        record = _exact_object(
            frame, {"role", "timestamp_sec", "path", "sha256"},
            f"visual_qa.frame_evidence[{index}]",
        )
        role = _text(record["role"], f"visual_qa.frame_evidence[{index}].role")
        roles.add(role)
        if not isinstance(record["timestamp_sec"], (int, float)) or isinstance(
            record["timestamp_sec"], bool
        ) or not 0 <= record["timestamp_sec"] < probe["duration"]:
            raise RegistryError(f"visual_qa.frame_evidence[{index}].timestamp_sec is invalid")
        times[role] = record["timestamp_sec"]
        frame_path = _relative_asset(
            skill_root, record["path"], f"visual_qa.frame_evidence[{index}].path"
        )
        expected = _hash(
            record["sha256"], f"visual_qa.frame_evidence[{index}].sha256"
        )
        if _sha256(frame_path) != expected:
            raise RegistryError(f"visual_qa.frame_evidence[{index}].sha256 does not match")
    if roles != {"entry", "stable", "exit"}:
        raise RegistryError("visual_qa.frame_evidence roles must be entry, stable, and exit")
    if not times["entry"] < times["stable"] < times["exit"]:
        raise RegistryError("visual_qa.frame_evidence must follow entry < stable < exit")
    if require_execution:
        try:
            _verify_execution_pair(skill_root, item)
        except (KeyError, TypeError, ValueError, OSError, AttributeError, IndexError) as exc:
            raise RegistryError(f"execution_qa malformed proof: {exc}") from exc
    return item


def verify_registry(registry_path: Path) -> dict[str, Any]:
    skill_root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    verified: list[dict[str, Any]] = []
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"verified": [], "verified_count": 0, "failures": [str(exc)]}
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "templates"}:
        return {
            "verified": [],
            "verified_count": 0,
            "failures": ["registry fields must be exactly schema_version and templates"],
        }
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or not isinstance(payload["templates"], list):
        return {
            "verified": [],
            "verified_count": 0,
            "failures": ["registry schema_version must be 1 and templates must be a list"],
        }
    seen_ids: set[str] = set()
    for index, template in enumerate(payload["templates"]):
        try:
            item = _verify_template(skill_root, template)
            if item["template_id"] in seen_ids:
                raise RegistryError("template_id must be unique")
            seen_ids.add(item["template_id"])
            verified.append(item)
        except RegistryError as exc:
            failures.append(f"templates[{index}]: {exc}")
    return {
        "verified": verified,
        "verified_count": len(verified),
        "failures": failures,
    }


def verify_registered_binding(binding: dict[str, Any]) -> dict[str, Any]:
    """Resolve provenance only from this package's registry and real assets."""
    root = Path(__file__).resolve().parents[1]
    report = verify_registry(root / "references/verified-template-registry.json")
    if report["failures"]:
        raise RegistryError("registered template verification failed: " + "; ".join(report["failures"]))
    matches = [item for item in report["verified"] if all(
        key in binding and binding[key] == item[key] for key in PROVENANCE_FIELDS
    )]
    if len(matches) != 1:
        raise RegistryError("binding does not match a registered template; do not self-certify provenance")
    return matches[0]


def verify_candidate_binding(
    binding: dict[str, Any],
    registry_relative_path: str,
    registry_sha256: str,
) -> dict[str, Any]:
    """Bind an immutable prequalification snapshot without granting production status."""
    root = Path(__file__).resolve().parents[1]
    relative = Path(registry_relative_path)
    if (
        relative.parts[:2] != ("assets", "verified-templates")
        or relative.parts[-2:] != ("qualification", "source-registry.json")
    ):
        raise RegistryError("candidate registry must be a qualification/source-registry.json asset")
    path = _relative_asset(root, registry_relative_path, "candidate registry")
    try:
        snapshot = path.read_bytes()
    except OSError as exc:
        raise RegistryError(f"candidate registry is unreadable: {exc}") from exc
    if hashlib.sha256(snapshot).hexdigest() != _hash(registry_sha256, "candidate registry sha256"):
        raise RegistryError("candidate registry hash mismatch")
    try:
        # Parse the bytes whose identity was checked, not a second path read.
        payload = json.loads(snapshot)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"candidate registry is unreadable: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "templates"}
        or payload["schema_version"] != 1
        or not isinstance(payload["templates"], list)
        or len(payload["templates"]) != 1
    ):
        raise RegistryError("candidate registry must contain exactly one schema-v1 template")
    candidate = _verify_template(root, payload["templates"][0], require_execution=False)
    if not all(key in binding and binding[key] == candidate[key] for key in PROVENANCE_FIELDS):
        raise RegistryError("binding differs from the immutable candidate snapshot")
    return candidate


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--registry", type=Path,
        default=Path(__file__).resolve().parents[1] / "references/verified-template-registry.json",
    )
    mode.add_argument("--production-video", type=Path)
    parser.add_argument("--expected-frames", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.production_video:
        if args.expected_frames is None:
            parser.error("--production-video requires --expected-frames")
        try:
            probe = verify_production_video(args.production_video.resolve(), expected_frames=args.expected_frames)
            report = {"scope": "production_media", "status": "pass", "probe": probe, "failures": []}
        except RegistryError as exc:
            report = {"scope": "production_media", "status": "fail", "failures": [str(exc)]}
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "pass" else 1
    if args.expected_frames is not None:
        parser.error("--expected-frames requires --production-video")
    report = verify_registry(args.registry.resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"verified={report['verified_count']} failures={len(report['failures'])}"
        )
        for failure in report["failures"]:
            print(f"- {failure}")
    return 0 if not report["failures"] and report["verified_count"] else 1


if __name__ == "__main__":
    sys.exit(main())

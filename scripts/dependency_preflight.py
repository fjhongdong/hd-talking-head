#!/usr/bin/env python3
"""Check talking-head workflow dependencies and record runtime status."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class PreflightError(RuntimeError):
    """Raised when the dependency manifest is invalid."""


SUCCESS_STATUSES = {"available", "connected", "callable", "bound"}
MISSING_STATUSES = {
    "configured",
    "missing",
    "unavailable",
    "version_too_old",
    "version_unverified",
    "wrong_type",
    "entrypoint_missing",
    "entrypoint_mismatch",
    "smoke_failed",
    "adapter_missing",
    "binding_missing",
    "binding_probe_failed",
    "binding_probe_mismatch",
    "binding_probe_unregistered",
    "connection_missing",
}

_SELECTION_LEVELS = {"connected", "callable", "bound"}
_ADAPTER_IDENTITY_FIELDS = {
    "adapter_type",
    "approved_executor",
    "primary_renderer",
}
_BINDING_PROBE_FIELDS = {
    "entrypoint",
    "producer_version",
    "adapter_identity",
    "command",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read dependency manifest: {path}") from exc
    if payload.get("schema_version") not in {1, 2, 3}:
        raise PreflightError("dependency manifest schema_version must be 1, 2, or 3")
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list):
        raise PreflightError("dependency manifest dependencies must be a list")
    seen: set[str] = set()
    for item in dependencies:
        if not isinstance(item, dict):
            raise PreflightError("each dependency must be an object")
        dependency_id = item.get("id")
        if not isinstance(dependency_id, str) or not dependency_id:
            raise PreflightError("each dependency needs a non-empty id")
        if dependency_id in seen:
            raise PreflightError(f"duplicate dependency id: {dependency_id}")
        seen.add(dependency_id)
        if item.get("kind") not in {
            "command",
            "project_path",
            "reference_path",
            "skill",
            "environment_any",
            "availability_any",
        }:
            raise PreflightError(f"unsupported dependency kind: {item.get('kind')}")
        if "target" not in item:
            raise PreflightError(f"dependency has no target: {dependency_id}")
        if item.get("required_level", "installed") not in {"installed", *_SELECTION_LEVELS}:
            raise PreflightError(f"invalid required_level: {dependency_id}")
        if "config_selection" in item and (
            item["config_selection"] != "reference_asr" or dependency_id != "reference-asr"
            or item["kind"] != "project_path" or item["target"] != "edit/hd/tools/reference_asr.py"
            or item.get("required_level") != "callable" or item.get("selection") is not None
        ):
            raise PreflightError(f"invalid config_selection: {dependency_id}")
        if "api" in item and (not isinstance(item["api"], list) or not item["api"]
                             or any(not isinstance(name, str) or not name.isidentifier() for name in item["api"])):
            raise PreflightError(f"invalid runner API: {dependency_id}")
        if item.get("kind") == "availability_any":
            _availability_alternatives(item)
        stages = item.get("stages")
        if stages is not None and (
            not isinstance(stages, list)
            or not stages
            or not all(isinstance(value, str) and value for value in stages)
        ):
            raise PreflightError(f"stages must be a non-empty string list: {dependency_id}")
        capabilities = item.get("capabilities")
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or not all(isinstance(value, str) and value for value in capabilities)
        ):
            raise PreflightError(f"capabilities must be a string list: {dependency_id}")
        entrypoints = item.get("entrypoints")
        if entrypoints is not None and not isinstance(entrypoints, list):
            raise PreflightError(f"entrypoints must be a list: {dependency_id}")
        bindings = item.get("bindings")
        if bindings is not None and not isinstance(bindings, list):
            raise PreflightError(f"bindings must be a list: {dependency_id}")
        binding_probes = item.get("binding_probes")
        if binding_probes is not None:
            probe_specs = _binding_probe_specs(item)
            registered_entrypoints = {
                value if isinstance(value, str) else value.get("path")
                for value in (entrypoints or [])
                if isinstance(value, str)
                or (
                    isinstance(value, dict)
                    and isinstance(value.get("path"), str)
                )
            }
            if any(
                spec["entrypoint"] not in registered_entrypoints
                for spec in probe_specs
            ):
                raise PreflightError(
                    f"binding probe entrypoint is not registered: {dependency_id}"
                )
        adapter = item.get("adapter")
        if adapter is not None:
            _validate_project_check(adapter, dependency_id, label="adapter")
        selection = item.get("selection")
        if selection is not None:
            if not isinstance(selection, dict) or set(selection) != {
                "component_kind",
                "binding_field",
                "equals",
                "required_level",
            }:
                raise PreflightError(f"selection fields are invalid: {dependency_id}")
            if not all(
                isinstance(selection[field], str) and selection[field]
                for field in ("component_kind", "binding_field", "equals")
            ) or selection["required_level"] not in _SELECTION_LEVELS:
                raise PreflightError(f"selection values are invalid: {dependency_id}")
            if selection["component_kind"] == "code_generated":
                valid_selection = (
                    selection["binding_field"] == "dependency_id"
                    and selection["required_level"] in {"callable", "bound"}
                    and item["kind"] != "environment_any"
                )
            elif selection["component_kind"] == "external_stock":
                valid_selection = (
                    selection["binding_field"] == "provider"
                    and selection["required_level"] == "connected"
                    and selection["equals"] != "*"
                    and item["kind"] == "environment_any"
                )
            elif selection["component_kind"] == "official_material":
                valid_selection = (
                    selection["binding_field"] == "media_type"
                    and selection["equals"] == "video"
                    and selection["required_level"] == "callable"
                    and item["kind"] == "availability_any"
                )
            elif selection["component_kind"] == "official_material":
                valid_selection = (
                    selection["binding_field"] == "media_type"
                    and selection["equals"] == "video"
                    and selection["required_level"] == "callable"
                    and item["kind"] == "availability_any"
                )
            else:
                valid_selection = False
            if not valid_selection:
                raise PreflightError(f"selection values are invalid: {dependency_id}")
    return payload


def _availability_alternatives(item: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives = item.get("target")
    if not isinstance(alternatives, list) or not alternatives:
        raise PreflightError(f"availability_any target must be a non-empty list: {item['id']}")
    checked: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for alternative in alternatives:
        if not isinstance(alternative, dict) or set(alternative) != {"id", "kind", "target"}:
            raise PreflightError(f"availability alternative fields are invalid: {item['id']}")
        alternative_id = alternative.get("id")
        kind = alternative.get("kind")
        if (
            not isinstance(alternative_id, str)
            or not alternative_id
            or alternative_id in identifiers
            or kind not in {"command", "python_module", "environment_any", "skill"}
        ):
            raise PreflightError(f"availability alternative values are invalid: {item['id']}")
        identifiers.add(alternative_id)
        checked.append(dict(alternative))
    return checked


def _availability_alternatives(item: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives = item.get("target")
    if not isinstance(alternatives, list) or not alternatives:
        raise PreflightError(f"availability_any target must be a non-empty list: {item['id']}")
    checked: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for alternative in alternatives:
        if not isinstance(alternative, dict) or set(alternative) != {"id", "kind", "target"}:
            raise PreflightError(f"availability alternative fields are invalid: {item['id']}")
        alternative_id = alternative.get("id")
        kind = alternative.get("kind")
        if (
            not isinstance(alternative_id, str)
            or not alternative_id
            or alternative_id in identifiers
            or kind not in {"command", "python_module", "environment_any", "skill"}
        ):
            raise PreflightError(f"availability alternative values are invalid: {item['id']}")
        identifiers.add(alternative_id)
        checked.append(dict(alternative))
    return checked


def _validate_project_check(
    value: object, dependency_id: str, *, label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"target", "contains_all"}:
        raise PreflightError(f"{label} fields are invalid: {dependency_id}")
    target = value.get("target")
    contains = value.get("contains_all")
    if (
        not isinstance(target, str)
        or not target
        or not isinstance(contains, list)
        or not contains
        or not all(isinstance(token, str) and token for token in contains)
    ):
        raise PreflightError(f"{label} values are invalid: {dependency_id}")
    return dict(value)


def _binding_probe_specs(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_specs = item.get("binding_probes", [])
    if not isinstance(raw_specs, list):
        raise PreflightError(f"binding_probes must be a list: {item['id']}")
    specs: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for raw in raw_specs:
        if not isinstance(raw, dict) or not _BINDING_PROBE_FIELDS.issubset(raw):
            raise PreflightError(f"binding probe fields are invalid: {item['id']}")
        if set(raw) - (_BINDING_PROBE_FIELDS | {"timeout_seconds"}):
            raise PreflightError(f"binding probe fields are invalid: {item['id']}")
        entrypoint = raw.get("entrypoint")
        version = raw.get("producer_version")
        command = raw.get("command")
        identity = raw.get("adapter_identity")
        timeout = raw.get("timeout_seconds", 15)
        if (
            not isinstance(entrypoint, str)
            or not entrypoint
            or not isinstance(version, str)
            or not version
            or not isinstance(command, list)
            or not command
            or not all(isinstance(value, str) and value for value in command)
            or not isinstance(identity, dict)
            or set(identity) != _ADAPTER_IDENTITY_FIELDS
            or not all(isinstance(value, str) and value for value in identity.values())
            or type(timeout) is not int
            or timeout < 1
            or timeout > 30
        ):
            raise PreflightError(f"binding probe values are invalid: {item['id']}")
        registered = (entrypoint, version)
        if registered in identities:
            raise PreflightError(f"duplicate binding probe: {item['id']}")
        identities.add(registered)
        specs.append(dict(raw))
    return specs


def _assert_project_modules(project_root: Path) -> None:
    for name, module in tuple(sys.modules.items()):
        if name != "edit" and not name.startswith("edit."):
            continue
        filename = getattr(module, "__file__", None)
        paths = [filename] if filename else getattr(module, "__path__", ())
        if any(not Path(path).resolve().is_relative_to(project_root.resolve() / "edit") for path in paths):
            raise PreflightError("cached module origin differs from selected project; use a fresh Python process")


def _contract_validators(project_root: Path) -> tuple[Any, Any]:
    _assert_project_modules(project_root)
    root_text = str(project_root)
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        visual_plan_module = importlib.import_module("edit.hd.tools.visual_plan")
        visual_strategy_module = importlib.import_module("edit.hd.tools.visual_strategy")
        _assert_project_modules(project_root)
    except Exception as exc:
        raise PreflightError("visual plan contract validators are unavailable") from exc
    finally:
        if inserted:
            sys.path.remove(root_text)
    validate_plan = getattr(visual_plan_module, "validate_visual_plan", None)
    validate_recipe = getattr(visual_strategy_module, "validate_shot_recipe_v2", None)
    if not callable(validate_plan) or not callable(validate_recipe):
        raise PreflightError("visual plan contract validators are unavailable")
    return validate_plan, validate_recipe


def _load_recipe_bindings(
    visual_plan_path: Path | None,
    project_root: Path,
) -> list[dict[str, str]]:
    if visual_plan_path is None:
        return []
    resolved = visual_plan_path.expanduser().resolve()
    try:
        visual_plan = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read visual plan: {resolved}") from exc
    validate_plan, validate_recipe = _contract_validators(project_root)
    try:
        checked_plan = validate_plan(visual_plan)
        segments = checked_plan["segments"]
        checked_recipes = [
            validate_recipe(segment["shot_recipe"])
            for segment in segments
        ]
    except Exception as exc:
        raise PreflightError(f"visual plan contract validation failed: {exc}") from exc

    bindings: list[dict[str, str]] = []
    for recipe in checked_recipes:
        for component in recipe["components"]:
            kind = component.get("kind")
            if kind == "code_generated":
                fields = {
                    "component_kind": kind,
                    "dependency_id": component.get("dependency_id"),
                    "entrypoint": component.get("entrypoint"),
                    "producer_version": component.get("producer_version"),
                    "executor": component.get("executor"),
                    "primary_renderer": component.get("primary_renderer"),
                }
                bindings.append(fields)
            elif kind == "external_stock":
                bindings.append({
                    "component_kind": kind,
                    "provider": component["provider"],
                })
            elif kind == "official_material":
                bindings.append({
                    "component_kind": kind,
                    "media_type": component["media_type"],
                    "source_id": component["source_id"],
                    "snapshot_path": component["snapshot_path"],
                    "sha256": component["sha256"],
                    "publisher": component["publisher"],
                    "source_url": component["source_url"],
                })
            elif kind == "official_material":
                bindings.append({
                    "component_kind": kind,
                    "media_type": component["media_type"],
                    "source_id": component["source_id"],
                })
    return bindings


def _selected_recipe_binding(
    item: dict[str, Any], recipe_bindings: list[dict[str, str]],
) -> dict[str, str] | None:
    selection = item.get("selection")
    if not isinstance(selection, dict):
        return None
    matches = [
        binding
        for binding in recipe_bindings
        if binding.get("component_kind") == selection["component_kind"]
        and not (item["id"] == "official-video-acquisition" and binding.get("local_media_verified") is True)
        and (
            binding.get(selection["binding_field"]) == selection["equals"]
            or (
                selection["equals"] == "*"
                and isinstance(binding.get(selection["binding_field"]), str)
            )
        )
    ]
    if not matches:
        return None
    if selection["equals"] == "*":
        return {
            "component_kind": selection["component_kind"],
            selection["binding_field"]: "*",
        }
    identities = {
        (
            binding.get("entrypoint"),
            binding.get("producer_version"),
            binding.get("executor"),
            binding.get("primary_renderer"),
        )
        for binding in matches
    }
    if len(identities) != 1:
        raise PreflightError(
            f"selected recipe bindings disagree: {item['id']}"
        )
    return dict(matches[0])


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _check_command(item: dict[str, Any]) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, str) or not target:
        raise PreflightError(f"command target must be a string: {item['id']}")
    resolved = sys.executable if item["id"] == "python-runtime" else shutil.which(target)
    if resolved is None:
        return {"status": "missing"}

    result: dict[str, Any] = {"status": "available", "resolved_path": resolved}
    version_args = item.get("version_args")
    minimum = item.get("min_version")
    if version_args is None and minimum is None:
        return result
    if version_args is None:
        version_args = ["--version"]
    if not isinstance(version_args, list) or not all(
        isinstance(value, str) for value in version_args
    ):
        raise PreflightError(f"version_args must be a string list: {item['id']}")
    try:
        completed = subprocess.run(
            [resolved, *version_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "resolved_path": resolved}
    version_text = (completed.stdout or completed.stderr).splitlines()
    version = version_text[0].strip() if version_text else "unknown"
    result["version"] = version
    if completed.returncode != 0:
        result["status"] = "unavailable"
        return result
    if minimum is not None:
        if not isinstance(minimum, str):
            raise PreflightError(f"min_version must be a string: {item['id']}")
        found_tuple = _version_tuple(version)
        minimum_tuple = _version_tuple(minimum)
        if found_tuple is None or minimum_tuple is None:
            result["status"] = "version_unverified"
        else:
            width = max(len(found_tuple), len(minimum_tuple))
            found_tuple += (0,) * (width - len(found_tuple))
            minimum_tuple += (0,) * (width - len(minimum_tuple))
            if found_tuple < minimum_tuple:
                result["status"] = "version_too_old"
    return result


def _resolve_inside(root: Path, relative: str, dependency_id: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise PreflightError(f"path target must be relative: {dependency_id}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PreflightError(f"path target escapes its root: {dependency_id}") from exc
    return resolved


def _check_path(item: dict[str, Any], root: Path) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, str):
        raise PreflightError(f"path target must be a string: {item['id']}")
    path = _resolve_inside(root, target, item["id"])
    if not path.exists():
        return {"status": "missing", "expected_path": str(path)}
    expected = item.get("path_type", "any")
    if expected == "file" and not path.is_file():
        return {"status": "wrong_type", "resolved_path": str(path)}
    if expected == "directory" and not path.is_dir():
        return {"status": "wrong_type", "resolved_path": str(path)}
    result = {"status": "available", "resolved_path": str(path)}
    if item.get("api"):
        result.update(_check_project_api(item, root))
    return result


def _check_project_api(item: dict[str, Any], root: Path) -> dict[str, Any]:
    target = _resolve_inside(root, item["target"], item["id"])
    module_name = Path(item["target"]).with_suffix("").as_posix().replace("/", ".")
    program = (
        "import importlib,json,pathlib,sys; sys.path.insert(0,sys.argv[1]); "
        "m=importlib.import_module(sys.argv[2]); "
        "assert pathlib.Path(m.__file__).resolve()==pathlib.Path(sys.argv[3]); "
        "assert all(callable(getattr(m,n,None)) for n in json.loads(sys.argv[4])); "
        "print('api-ready')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", program, str(root), module_name, str(target), json.dumps(item["api"])],
            capture_output=True, text=True, check=False, timeout=20, cwd=str(root),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "smoke_failed", "api": item["api"]}
    return {"status": "callable" if result.returncode == 0 and result.stdout.strip() == "api-ready" else "smoke_failed",
            "api": item["api"], "python_executable": sys.executable}


def _check_skill(item: dict[str, Any], roots: Iterable[Path]) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, str) or not target:
        raise PreflightError(f"skill target must be a string: {item['id']}")
    checked: list[str] = []
    for root in roots:
        candidate = (root / target).expanduser().resolve()
        checked.append(str(candidate))
        if candidate.is_dir() and (candidate / "SKILL.md").is_file():
            return {"status": "available", "resolved_path": str(candidate)}
    return {"status": "missing", "searched_paths": checked}


def _check_environment_any(item: dict[str, Any]) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, list) or not target or not all(
        isinstance(name, str) and name for name in target
    ):
        raise PreflightError(f"environment_any target must be a string list: {item['id']}")
    values = {name: os.environ.get(name, "").strip() for name in target}
    configured = any(value.lower() not in {"", "0", "false", "no", "off"} for value in values.values())
    # A host capability flag is an explicit declaration; a credential string is
    # only configuration and never proof that the provider authenticated it.
    declared = any(name.endswith(("_AVAILABLE", "_CONNECTED")) and value.lower() in {"1", "true", "yes"}
                   for name, value in values.items())
    return {
        "status": "connected" if declared else "configured" if configured else "missing",
        "configured": configured, "connected": declared,
        "connection_evidence": "host_declaration" if declared else "unverified",
        "connection_value_recorded": False,
    }


def _check_python_module(item: dict[str, Any]) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, str) or not target:
        raise PreflightError(f"python_module target must be a string: {item['id']}")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import importlib,sys; importlib.import_module(sys.argv[1])", target],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "smoke_failed", "module": target}
    return {"status": "callable" if result.returncode == 0 else "missing",
            "module": target, "python_executable": sys.executable}


def _check_availability_any(
    item: dict[str, Any],
    skill_roots: Iterable[Path],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for alternative in _availability_alternatives(item):
        probe = {"id": alternative["id"], "target": alternative["target"]}
        if alternative["kind"] == "command":
            checked = _check_command(probe)
        elif alternative["kind"] == "python_module":
            checked = _check_python_module(probe)
        elif alternative["kind"] == "environment_any":
            checked = _check_environment_any(probe)
        else:
            checked = _check_skill(probe, skill_roots)
        record = {
            "id": alternative["id"],
            "kind": alternative["kind"],
            **checked,
        }
        records.append(record)
        if checked["status"] in SUCCESS_STATUSES:
            return {
                "status": "callable",
                "selected_alternative": alternative["id"],
                "alternatives": records,
            }
    return {"status": "missing", "alternatives": records}


def _check_python_module(item: dict[str, Any]) -> dict[str, Any]:
    target = item["target"]
    if not isinstance(target, str) or not target:
        raise PreflightError(f"python_module target must be a string: {item['id']}")
    try:
        spec = importlib.util.find_spec(target)
    except (ImportError, ModuleNotFoundError, ValueError):
        spec = None
    if spec is None:
        return {"status": "missing"}
    return {
        "status": "available",
        "module": target,
        "resolved_path": spec.origin,
    }


def _check_availability_any(
    item: dict[str, Any],
    skill_roots: Iterable[Path],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for alternative in _availability_alternatives(item):
        probe = {"id": alternative["id"], "target": alternative["target"]}
        if alternative["kind"] == "command":
            checked = _check_command(probe)
        elif alternative["kind"] == "python_module":
            checked = _check_python_module(probe)
        elif alternative["kind"] == "environment_any":
            checked = _check_environment_any(probe)
        else:
            checked = _check_skill(probe, skill_roots)
        record = {
            "id": alternative["id"],
            "kind": alternative["kind"],
            **checked,
        }
        records.append(record)
        if checked["status"] in SUCCESS_STATUSES:
            return {
                "status": "callable",
                "selected_alternative": alternative["id"],
                "alternatives": records,
            }
    return {"status": "missing", "alternatives": records}


def _stages(item: dict[str, Any]) -> list[str]:
    configured = item.get("stages")
    if isinstance(configured, list):
        return list(configured)
    stage = item.get("stage", "job-start")
    if not isinstance(stage, str) or not stage:
        raise PreflightError(f"stage must be a string: {item['id']}")
    return [stage]


def _entrypoint_specs(item: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for raw in item.get("entrypoints", []):
        if isinstance(raw, str) and raw:
            specs.append({"path": raw})
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str) or not raw["path"]:
            raise PreflightError(f"invalid entrypoint: {item['id']}")
        smoke = raw.get("smoke")
        if smoke is not None and (
            not isinstance(smoke, list)
            or not smoke
            or not all(isinstance(value, str) and value for value in smoke)
        ):
            raise PreflightError(f"entrypoint smoke must be a string list: {item['id']}")
        specs.append(dict(raw))
    return specs


def _check_entrypoints(
    item: dict[str, Any], dependency_root: Path,
) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    for spec in _entrypoint_specs(item):
        entrypoint = _resolve_inside(dependency_root, spec["path"], item["id"])
        record: dict[str, Any] = {"path": spec["path"], "resolved_path": str(entrypoint)}
        if not entrypoint.exists():
            record["status"] = "missing"
            checked.append(record)
            return {"status": "entrypoint_missing", "entrypoints": checked}
        record["path_type"] = "directory" if entrypoint.is_dir() else "file"
        smoke = spec.get("smoke")
        if smoke is not None:
            replacements = {
                "{python}": sys.executable,
                "{root}": str(dependency_root),
                "{entrypoint}": str(entrypoint),
            }
            command = [replacements.get(token, token) for token in smoke]
            timeout = spec.get("timeout_seconds", 15)
            if type(timeout) is not int or timeout < 1 or timeout > 30:
                raise PreflightError(f"invalid smoke timeout: {item['id']}")
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(dependency_root),
                )
            except (OSError, subprocess.TimeoutExpired):
                record["status"] = "failed"
                checked.append(record)
                return {"status": "smoke_failed", "entrypoints": checked}
            record["returncode"] = completed.returncode
            if completed.returncode != 0:
                record["status"] = "failed"
                checked.append(record)
                return {"status": "smoke_failed", "entrypoints": checked}
        record["status"] = "callable" if smoke else "discovered"
        checked.append(record)
    return {"status": "callable" if checked and all(r["status"] == "callable" for r in checked) else "available",
            "entrypoints": checked}


def _check_bindings(item: dict[str, Any], project_root: Path) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    for raw in item.get("bindings", []):
        if not isinstance(raw, dict):
            raise PreflightError(f"invalid binding: {item['id']}")
        stage = raw.get("stage")
        target = raw.get("target")
        contains = raw.get("contains_all", [])
        if (
            not isinstance(stage, str)
            or not stage
            or not isinstance(target, str)
            or not target
            or not isinstance(contains, list)
            or not all(isinstance(value, str) and value for value in contains)
        ):
            raise PreflightError(f"invalid binding: {item['id']}")
        path = _resolve_inside(project_root, target, item["id"])
        record: dict[str, Any] = {
            "stage": stage,
            "target": target,
            "resolved_path": str(path),
        }
        if not path.is_file():
            record["status"] = "missing"
            checked.append(record)
            return {"status": "binding_missing", "bindings": checked}
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            record["status"] = "missing"
            checked.append(record)
            return {"status": "binding_missing", "bindings": checked}
        missing_tokens = [token for token in contains if token not in source]
        if missing_tokens:
            record["status"] = "missing"
            record["missing_token_count"] = len(missing_tokens)
            checked.append(record)
            return {"status": "binding_missing", "bindings": checked}
        if not raw.get("api") or _check_project_api({"id": item["id"], "target": target, "api": raw["api"]}, project_root)["status"] != "callable":
            record["status"] = "missing"
            checked.append(record)
            return {"status": "binding_missing", "bindings": checked}
        record["status"] = "bound"
        checked.append(record)
    return {"status": "bound", "bindings": checked}


def _check_adapter(item: dict[str, Any], project_root: Path) -> dict[str, Any]:
    raw = _validate_project_check(item.get("adapter"), item["id"], label="adapter")
    path = _resolve_inside(project_root, raw["target"], item["id"])
    record: dict[str, Any] = {
        "target": raw["target"],
        "resolved_path": str(path),
    }
    if not path.is_file():
        record["status"] = "missing"
        return {"status": "adapter_missing", "adapter": record}
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        record["status"] = "missing"
        return {"status": "adapter_missing", "adapter": record}
    missing_tokens = [token for token in raw["contains_all"] if token not in source]
    if missing_tokens:
        record["status"] = "missing"
        record["missing_token_count"] = len(missing_tokens)
        return {"status": "adapter_missing", "adapter": record}
    record["status"] = "callable"
    return {"status": "callable", "adapter": record}


def _probe_command(
    spec: dict[str, Any],
    *,
    project_root: Path,
    reference_root: Path,
    dependency_root: Path,
    dependency_id: str,
    entrypoint: str,
    producer_version: str,
) -> list[str]:
    replacements = {
        "{python}": str(Path(sys.executable)),
        "{preflight}": str(Path(__file__).resolve()),
        "{project_root}": str(project_root),
        "{reference_root}": str(reference_root),
        "{dependency_root}": str(dependency_root),
        "{dependency_id}": dependency_id,
        "{entrypoint}": entrypoint,
        "{producer_version}": producer_version,
    }
    command: list[str] = []
    for raw in spec["command"]:
        value = raw
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        if re.search(r"\{[a-z_]+\}", value):
            raise PreflightError(
                f"binding probe placeholder is invalid: {dependency_id}"
            )
        command.append(value)
    return command


def _check_binding_probe(
    item: dict[str, Any],
    selected_binding: dict[str, str],
    *,
    project_root: Path,
    reference_root: Path,
    dependency_root: Path,
) -> dict[str, Any]:
    entrypoint = selected_binding["entrypoint"]
    producer_version = selected_binding["producer_version"]
    matching = [
        spec
        for spec in _binding_probe_specs(item)
        if spec["entrypoint"] == entrypoint
        and spec["producer_version"] == producer_version
    ]
    if len(matching) != 1:
        return {"status": "binding_probe_unregistered"}
    spec = matching[0]
    identity = spec["adapter_identity"]
    if (
        identity["approved_executor"] != selected_binding["executor"]
        or identity["primary_renderer"] != selected_binding["primary_renderer"]
    ):
        return {"status": "binding_probe_mismatch"}
    command = _probe_command(
        spec,
        project_root=project_root,
        reference_root=reference_root,
        dependency_root=dependency_root,
        dependency_id=selected_binding["dependency_id"],
        entrypoint=entrypoint,
        producer_version=producer_version,
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=spec.get("timeout_seconds", 15),
            cwd=str(project_root),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "binding_probe_failed"}
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 65536:
        return {"status": "binding_probe_failed"}
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return {"status": "binding_probe_failed"}
    expected = {
        "schema_version": 1,
        "dependency_id": selected_binding["dependency_id"],
        "entrypoint": entrypoint,
        "producer_version": producer_version,
        "adapter_identity": identity,
    }
    if payload != expected:
        return {"status": "binding_probe_mismatch"}
    return {
        "status": "bound",
        "adapter_identity": dict(identity),
        "binding_probe": {"status": "bound"},
    }


def _git_head(root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        raise PreflightError("binding probe cannot read the dependency version")
    try:
        completed = subprocess.run(
            [git, "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(
            "binding probe cannot read the dependency version"
        ) from exc
    version = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", version) is None:
        raise PreflightError("binding probe cannot read the dependency version")
    return version


def _project_binding_identity(
    project_root: Path,
    dependency_id: str,
) -> dict[str, str]:
    _assert_project_modules(project_root)
    root_text = str(project_root)
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        module = importlib.import_module("edit.hd.tools.broll_component_executor")
        _assert_project_modules(project_root)
    except Exception as exc:
        raise PreflightError("binding probe cannot load the project adapter") from exc
    finally:
        if inserted:
            sys.path.remove(root_text)
    contracts = getattr(module, "_DEPENDENCY_CONTRACTS", None)
    contract = contracts.get(dependency_id) if isinstance(contracts, dict) else None
    if (
        not isinstance(contract, tuple)
        or len(contract) != 2
        or not all(isinstance(value, str) and value for value in contract)
    ):
        raise PreflightError("binding probe found no registered adapter")
    adapter_kind, primary_renderer = contract
    if adapter_kind == "reference_adapter":
        class_name = "ReferenceProcessAdapter"
        runner_name = "_run_reference_process"
        required_fields = {
            "adapter_id", "dependency_id", "approved_executor", "dependency_root",
            "entrypoint", "entrypoint_sha256", "producer_version", "primary_renderer",
            "renderer_version", "artifact_media_type", "launcher", "launcher_sha256",
            "argv_template", "brief_loader", "self_contained_wrapper",
        }
    elif adapter_kind == "skill_invocation":
        class_name = "SkillInvocationAdapter"
        runner_name = "_run_skill_invocation"
        required_fields = {
            "adapter_id", "dependency_id", "approved_executor", "entrypoint",
            "producer_version", "primary_renderer", "renderer_version",
            "artifact_media_type", "brief_loader", "invoker",
        }
    else:
        raise PreflightError("binding probe found an unsupported adapter kind")
    adapter_class = getattr(module, class_name, None)
    if not isinstance(adapter_class, type) or not dataclasses.is_dataclass(adapter_class):
        raise PreflightError("binding probe found no executable adapter")
    field_names = {field.name for field in dataclasses.fields(adapter_class)}
    if not required_fields.issubset(field_names) or not all(
        callable(getattr(module, name, None))
        for name in ("_validate_code_adapter", "execute_component", runner_name)
    ):
        raise PreflightError("binding probe found no executable adapter")
    return {
        "adapter_type": class_name,
        "approved_executor": adapter_kind,
        "primary_renderer": primary_renderer,
    }


def _emit_project_binding_probe(args: argparse.Namespace) -> int:
    project_root = args.project_root.expanduser().resolve()
    dependency_root = args.dependency_root.expanduser().resolve()
    entrypoint = _resolve_inside(
        dependency_root, args.entrypoint, args.dependency_id
    )
    if not entrypoint.is_file():
        raise PreflightError("binding probe entrypoint is unavailable")
    producer_version = args.producer_version or _git_head(dependency_root)
    runtime_values = (
        args.runtime_root,
        args.runtime_revision,
        args.renderer_version,
    )
    if args.dependency_id in {"hyperframes", "hd-talking-head-local-canonical"}:
        if any(value is None for value in runtime_values):
            raise PreflightError("HyperFrames binding probe requires its pinned runtime")
        try:
            runtime_root = args.runtime_root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise PreflightError("HyperFrames runtime is unavailable") from exc
        if not runtime_root.is_dir() or _git_head(runtime_root) != args.runtime_revision:
            raise PreflightError("HyperFrames runtime revision differs from the approved binding")
        package_path = _resolve_inside(
            runtime_root, "packages/cli/package.json", args.dependency_id
        )
        cli_path = _resolve_inside(
            runtime_root, "packages/cli/src/cli.ts", args.dependency_id
        )
        tsx_path = _resolve_inside(
            runtime_root, "node_modules/tsx/dist/cli.mjs", args.dependency_id
        )
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PreflightError("HyperFrames runtime package is unreadable") from exc
        if (
            not cli_path.is_file()
            or not tsx_path.is_file()
            or package.get("name") != "@hyperframes/cli"
            or package.get("version") != args.renderer_version
        ):
            raise PreflightError("HyperFrames runtime is incomplete or has drifted")
    elif any(value is not None for value in runtime_values):
        raise PreflightError(
            "runtime binding fields are only supported for HyperFrames-backed adapters"
        )
    payload = {
        "schema_version": 1,
        "dependency_id": args.dependency_id,
        "entrypoint": args.entrypoint,
        "producer_version": producer_version,
        "adapter_identity": _project_binding_identity(
            project_root, args.dependency_id
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _default_skill_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("HD_SKILL_ROOTS")
    if configured:
        roots.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    roots.extend(
        [
            Path("~/.agents/skills").expanduser(),
            Path("~/.codex/skills").expanduser(),
            Path("~/.claude/skills").expanduser(),
        ]
    )
    return roots


def _deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _install_plan(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        if result["status"] in SUCCESS_STATUSES:
            continue
        install = result.get("install")
        if not isinstance(install, dict):
            continue
        group_id = install.get("group") or result["id"]
        group = groups.setdefault(
            str(group_id),
            {
                "group": str(group_id),
                "dependency_ids": [],
                "method": install.get("method"),
                "package": install.get("package"),
                "source": install.get("source"),
                "destination": install.get("destination"),
                "approval_required": bool(install.get("approval_required", True)),
                "account_connection_required": bool(
                    install.get("account_connection_required", False)
                ),
                "repair_required": result["status"] != "missing",
            },
        )
        group["dependency_ids"].append(result["id"])
    return list(groups.values())


def _verify_local_official_video(binding: dict, job_dir: Path) -> bool:
    if (not binding.get("publisher") or not isinstance(binding.get("source_url"), str)
            or not binding["source_url"].startswith(("https://", "http://"))):
        raise PreflightError("official video source record is incomplete")
    path = _resolve_inside(job_dir, binding["snapshot_path"], binding["source_id"])
    original = job_dir / binding["snapshot_path"]
    if path != original or original.is_symlink():
        raise PreflightError("official video media path must not traverse symlinks")
    if not path.exists():
        return False
    if not path.is_file() or _sha256(path) != binding["sha256"]:
        raise PreflightError("official video media changed; keep the approved source binding")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        probe = json.loads(result.stdout)
        stream = probe["streams"][0]
        duration = float(probe["format"]["duration"])
        valid = (result.returncode == 0 and stream["codec_type"] == "video"
                 and stream["width"] > 0 and stream["height"] > 0
                 and math.isfinite(duration) and duration > 0)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError):
        valid = False
    if not valid:
        raise PreflightError("official video media probe failed; acquisition is not a replacement for invalid bytes")
    return True


def _job_report_identity(project_root: Path, context_path: Path | None) -> dict:
    identity: dict[str, Any] = {"python_executable": sys.executable, "runtime": None,
                              "job_context": None, "provider_config_sha256": None}
    if (project_root / "edit/hd/tools/startup.py").is_file():
        program = ("import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                   "from edit.hd.tools.startup import runtime_identity; "
                   "print(json.dumps(runtime_identity(Path(sys.argv[1]))))")
        try:
            result = subprocess.run([sys.executable, "-c", program, str(project_root)],
                                    capture_output=True, text=True, check=False, timeout=20)
            if result.returncode != 0:
                raise PreflightError("selected project runtime cannot be loaded")
            identity["runtime"] = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise PreflightError("selected project runtime identity cannot be checked") from exc
    if context_path is not None:
        try:
            if context_path.is_symlink():
                raise ValueError("symlink")
            context = json.loads(context_path.read_text(encoding="utf-8"))
            workspace = context_path.resolve().parent
            if (context.get("project_root") != str(project_root)
                    or context.get("workspace") != str(workspace)
                    or context.get("runtime") != identity["runtime"]):
                raise ValueError("runtime/context mismatch")
            job = workspace / "edit/hd/jobs" / context["job_id"]
            if str(job) != context["job_dir"] or not job.resolve().is_relative_to(workspace):
                raise ValueError("Job mismatch")
            config = job / "manifests/provider-config.json"
            if config.is_symlink() or not config.is_file():
                raise ValueError("provider config missing")
            config_bytes = config.read_bytes()
            config_data = json.loads(config_bytes)
            if not isinstance(config_data, dict):
                raise ValueError("provider config must be an object")
            identity.update(job_context={"job_id": context["job_id"], "workspace": str(workspace)},
                            provider_config_sha256=hashlib.sha256(config_bytes).hexdigest(),
                            reference_asr_selection=config_data.get("reference_asr"))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise PreflightError("Job context/runtime/provider config is missing or changed") from exc
    return identity


def _check_reference_asr(project_root: Path, identity: dict[str, Any]) -> dict[str, Any]:
    """Run the selected project's local help probe, not inference or approval."""
    job = identity["job_context"]
    job_dir = Path(job["workspace"]) / "edit/hd/jobs" / job["job_id"]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "edit.hd.tools.reference_asr", "--job", str(job_dir)],
            cwd=project_root, capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "smoke_failed", "detail": "selected reference ASR probe could not run"}
    try:
        if result.returncode == 3:
            raise PreflightError("reference ASR configuration is invalid")
        if result.returncode != 0:
            return {"status": "smoke_failed", "detail": "selected reference ASR probe failed"}
        probe = json.loads(result.stdout)
        selected = identity["reference_asr_selection"]
        if (not isinstance(probe, dict) or not isinstance(selected, dict)
                or any(probe.get(k) != v for k, v in selected.items())
                or probe.get("provider_config_sha256") != identity["provider_config_sha256"]
                or probe.get("callable") is not True or probe.get("model_load_verified") is not False):
            raise ValueError("probe identity mismatch")
        if _sha256(job_dir / "manifests/provider-config.json") != identity["provider_config_sha256"]:
            raise ValueError("config changed")
        return {"status": "callable", "reference_asr_probe": probe}
    except (OSError, ValueError, TypeError) as exc:
        raise PreflightError("reference ASR probe could not be verified") from exc


def build_report(
    manifest_path: Path,
    project_root: Path,
    reference_root: Path,
    skill_roots: Iterable[Path],
    visual_plan_path: Path | None = None,
    job_context_path: Path | None = None,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    identity = _job_report_identity(project_root, job_context_path)
    roots = _deduplicate_paths(skill_roots)
    resolved_visual_plan = (
        visual_plan_path.expanduser().resolve() if visual_plan_path is not None else None
    )
    recipe_bindings = _load_recipe_bindings(resolved_visual_plan, project_root)
    local_official_media = []
    if identity["job_context"]:
        job = identity["job_context"]
        job_dir = Path(job["workspace"]) / "edit/hd/jobs" / job["job_id"]
        for binding in recipe_bindings:
            if binding["component_kind"] == "official_material" and binding["media_type"] == "video":
                binding["local_media_verified"] = _verify_local_official_video(binding, job_dir)
                if binding["local_media_verified"]:
                    local_official_media.append({"source_id": binding["source_id"],
                                                 "snapshot_path": binding["snapshot_path"],
                                                 "sha256": binding["sha256"]})
    results: list[dict[str, Any]] = []
    for item in manifest["dependencies"]:
        selection = item.get("selection")
        selected_binding = _selected_recipe_binding(item, recipe_bindings)
        config_selected = (item.get("config_selection") == "reference_asr"
                           and identity.get("reference_asr_selection") is not None)
        selected = bool(item.get("required", False)) or selected_binding is not None or config_selected
        conditional_code_selected = (
            selected_binding is not None
            and isinstance(selection, dict)
            and selection["component_kind"] == "code_generated"
        )
        exact_code_selected = (
            conditional_code_selected
            and selection["equals"] != "*"
        )
        kind = item["kind"]
        if kind == "command":
            checked = _check_command(item)
        elif kind == "project_path":
            checked = _check_path(item, project_root)
        elif kind == "reference_path":
            checked = _check_path(item, reference_root)
        elif kind == "skill":
            checked = _check_skill(item, roots)
        elif kind == "availability_any":
            checked = _check_availability_any(item, roots)
        else:
            checked = _check_environment_any(item)
        if config_selected:
            checked = _check_reference_asr(project_root, identity)
        base_status = checked["status"]
        availability_level = "installed" if base_status in SUCCESS_STATUSES else "missing"
        connected = kind != "environment_any" or base_status == "connected"
        callable_status = (kind in {"command", "availability_any"} and base_status in SUCCESS_STATUSES) or base_status == "callable"
        if callable_status:
            availability_level = "callable"
        if kind == "availability_any" and callable_status:
            availability_level = "callable"
        bound = False
        selected_entrypoint = (
            selected_binding.get("entrypoint")
            if isinstance(selected_binding, dict)
            else None
        )
        selected_version = (
            selected_binding.get("producer_version")
            if isinstance(selected_binding, dict)
            else None
        )
        if exact_code_selected and not item.get("entrypoints"):
            checked["status"] = "entrypoint_mismatch"
        elif base_status in SUCCESS_STATUSES and item.get("entrypoints"):
            entrypoint_specs = _entrypoint_specs(item)
            registered_entrypoints = {spec["path"] for spec in entrypoint_specs}
            if (
                selected_entrypoint is not None
                and selected_entrypoint not in registered_entrypoints
            ):
                checked["status"] = "entrypoint_mismatch"
            else:
                resolved_path = checked.get("resolved_path")
                if not isinstance(resolved_path, str):
                    raise PreflightError(
                        f"entrypoints require a resolved path: {item['id']}"
                    )
                entrypoint_check = _check_entrypoints(item, Path(resolved_path))
                checked.update(entrypoint_check)
                if entrypoint_check["status"] == "callable":
                    selected_entrypoint_has_smoke = any(
                        spec["path"] == selected_entrypoint and spec.get("smoke")
                        for spec in entrypoint_specs
                    )
                    if not exact_code_selected and (
                        not conditional_code_selected or selected_entrypoint_has_smoke
                    ):
                        availability_level = "callable"
                        callable_status = True
        if (
            checked["status"] in SUCCESS_STATUSES
            and item.get("adapter")
            and not exact_code_selected
        ):
            adapter_check = _check_adapter(item, project_root)
            checked.update(adapter_check)
            if adapter_check["status"] == "callable":
                availability_level = "callable"
                callable_status = True
        if (
            checked["status"] in SUCCESS_STATUSES
            and item.get("bindings")
            and not exact_code_selected
            and callable_status
        ):
            binding_check = _check_bindings(item, project_root)
            checked.update(binding_check)
            if binding_check["status"] == "bound":
                availability_level = "bound"
                bound = True
                callable_status = True
        if exact_code_selected and checked["status"] in SUCCESS_STATUSES:
            resolved_path = checked.get("resolved_path")
            if not isinstance(resolved_path, str):
                raise PreflightError(
                    f"binding probe requires a resolved path: {item['id']}"
                )
            probe_check = _check_binding_probe(
                item,
                selected_binding,
                project_root=project_root,
                reference_root=reference_root,
                dependency_root=Path(resolved_path),
            )
            checked.update(probe_check)
            if probe_check["status"] == "bound":
                availability_level = "bound"
                callable_status = True
                bound = True
        if selected:
            required_level = selection["required_level"] if selected_binding is not None and isinstance(selection, dict) else item.get("required_level", "installed")
            if required_level == "connected" and not connected:
                checked["status"] = "connection_missing"
            elif required_level in {"callable", "bound"} and not callable_status:
                if checked["status"] in SUCCESS_STATUSES:
                    checked["status"] = "adapter_missing"
            elif required_level == "bound" and not bound:
                if checked["status"] in SUCCESS_STATUSES:
                    checked["status"] = "binding_missing"
        result = {
            "id": item["id"],
            "kind": kind,
            "required": selected,
            "static_required": bool(item.get("required", False)),
            "selected": selected,
            "connected": connected,
            "callable": callable_status,
            "bound": bound,
            "entrypoint": selected_entrypoint,
            "version": selected_version or checked.get("version"),
            "stage": _stages(item)[0],
            "stages": _stages(item),
            "status": checked.pop("status"),
            "availability_level": availability_level,
            "capabilities": list(item.get("capabilities", [])),
            **checked,
        }
        if isinstance(item.get("install"), dict):
            result["install"] = item["install"]
        results.append(result)

    required_missing = sum(
        result["required"] and result["status"] in MISSING_STATUSES for result in results
    )
    optional_missing = sum(
        not result["required"] and result["status"] in MISSING_STATUSES for result in results
    )
    if required_missing:
        status = "blocked_missing_required"
    elif optional_missing:
        status = "ready_with_optional_gaps"
    else:
        status = "ready"
    capability_coverage: dict[str, dict[str, Any]] = {}
    stage_bindings: list[dict[str, Any]] = []
    for result in results:
        for capability in result["capabilities"]:
            capability_coverage[capability] = {
                "dependency_id": result["id"],
                "status": result["status"],
                "availability_level": result["availability_level"],
                "stages": result["stages"],
            }
        for binding in result.get("bindings", []):
            stage_bindings.append({
                "dependency_id": result["id"],
                "stage": binding["stage"],
                "target": binding["target"],
                "status": binding["status"],
            })
    return {
        "schema_version": 3,
        "manifest_schema_version": manifest["schema_version"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **identity,
        "local_official_media": local_official_media,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "project_root": str(project_root),
        "reference_root": str(reference_root),
        "skill_roots": [str(path) for path in roots],
        "visual_plan": (
            {
                "path": str(resolved_visual_plan),
                "sha256": _sha256(resolved_visual_plan),
            }
            if resolved_visual_plan is not None
            else None
        ),
        "summary": {
            "status": status,
            "dependency_count": len(results),
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        },
        "dependencies": results,
        "capability_coverage": capability_coverage,
        "stage_bindings": stage_bindings,
        "install_plan": _install_plan(results),
        "dynamic_checks": manifest.get("dynamic_checks", []),
        "connection_values_recorded": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--skill-root", action="append", default=[], type=Path)
    parser.add_argument("--visual-plan", type=Path)
    parser.add_argument("--job-context", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def _binding_probe_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report the installed code adapter binding identity."
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--dependency-id", required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--producer-version")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--runtime-revision")
    parser.add_argument("--renderer-version")
    return parser


def main() -> int:
    if sys.argv[1:2] == ["probe-code-binding"]:
        try:
            return _emit_project_binding_probe(
                _binding_probe_parser().parse_args(sys.argv[2:])
            )
        except PreflightError as exc:
            print(f"binding probe stopped: {exc}", file=sys.stderr)
            return 3
    args = _parser().parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    project_root = args.project_root.expanduser().resolve()
    reference_root = (
        args.reference_root.expanduser().resolve()
        if args.reference_root
        else project_root / "参考项目" / "B-roll开源方案"
    )
    try:
        report = build_report(
            manifest_path,
            project_root,
            reference_root,
            [*args.skill_root, *_default_skill_roots()],
            args.visual_plan,
            args.job_context,
        )
    except PreflightError as exc:
        print(f"dependency preflight error: {exc}", file=sys.stderr)
        return 3
    if args.output:
        _atomic_write_json(args.output.expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report["summary"]["required_missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

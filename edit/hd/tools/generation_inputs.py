"""Bind approved local references to the selected channel's actual upload result."""
from __future__ import annotations

import copy
import base64
import hashlib
import secrets
from pathlib import Path

from . import contract_artifacts as artifacts


def validate_binding(binding):
    if not isinstance(binding, dict) or binding.get("reference_mode") not in {"local_path", "upload"}:
        raise ValueError("generation channel must declare reference_mode")
    if binding["reference_mode"] == "upload":
        upload = binding.get("upload")
        if (not isinstance(upload, dict) or not isinstance(upload.get("tool"), str) or not upload["tool"]
                or not isinstance(upload.get("arguments"), dict)
                or not isinstance(upload.get("result_path"), list) or not upload["result_path"]
                or any(not isinstance(key, (str, int)) for key in upload["result_path"])):
            raise ValueError("upload binding needs its real tool, arguments and result_path")
        def has_input(value):
            if isinstance(value, dict):
                return value in ({"$input": "path"}, {"$input": "base64"}) or any(has_input(v) for v in value.values())
            return isinstance(value, list) and any(has_input(v) for v in value)
        if not has_input(upload["arguments"]):
            raise ValueError("upload arguments must reference the actual input file")
    return binding


def _binding(job_dir, purpose):
    path = Path(job_dir) / "manifests/generation-channels.json"
    if not path.is_file():
        raise ValueError("generation channel input binding is missing")
    return validate_binding(artifacts.read_json_artifact(path).get(purpose))


def _replace(value, replacements):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    return value


def _references(job_dir, request):
    strings = set()
    def visit(value):
        if isinstance(value, str):
            strings.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(request["arguments"])
    refs = []
    for ref in request["input_files"]:
        path = Path(job_dir) / ref["path"]
        if str(path) not in strings:
            continue
        if artifacts.sha256_file(path) != ref["sha256"] or path.stat().st_size != ref["bytes"]:
            raise ValueError("generation reference changed before upload")
        refs.append((str(path), ref))
    return refs


def _state(job_dir, request, binding):
    # The request has already passed queue validation; reuse its file-safe digest.
    key = artifacts.sha256_json(request)
    path = Path(job_dir) / "manifests/generation-inputs" / (key + ".json")
    identity = {"request_sha256": key, "binding_sha256": artifacts.sha256_json(binding)}
    state = artifacts.read_json_artifact(path) if path.is_file() else {**identity, "uploads": {}}
    if any(state.get(key) != value for key, value in identity.items()):
        raise ValueError("generation input binding changed after preparation")
    return path, state


def next_action(job_dir, request):
    """Issue each upload once; following calls wait for the original result."""
    binding = _binding(job_dir, request["purpose"])
    if binding["reference_mode"] == "local_path":
        return None
    path, state = _state(job_dir, request, binding)
    for local, ref in _references(job_dir, request):
        key = artifacts.sha256_json(ref)
        saved = state["uploads"].get(key)
        if saved is not None:
            if saved.get("reference"):
                continue
            return {"action": "blocked", "status": "input_upload_pending", "request_id": request["id"],
                    "binding_id": key, "next": "回传已发出的原 upload action 与真实结果后继续。"}
        def arguments(value):
            if isinstance(value, dict):
                if value == {"$input": "path"}:
                    return local
                if value == {"$input": "filename"}:
                    return Path(local).name
                if value == {"$input": "base64"}:
                    data = Path(local).read_bytes()
                    if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
                        raise ValueError("generation reference changed before upload")
                    return base64.b64encode(data).decode("ascii")
                return {key: arguments(item) for key, item in value.items()}
            if isinstance(value, list):
                return [arguments(item) for item in value]
            return value
        upload = binding["upload"]
        action = {"action": "upload", "purpose": request["purpose"], "request_id": request["id"],
                  "binding_id": key, "claim_token": secrets.token_urlsafe(24),
                  "tool": upload["tool"], "arguments": arguments(upload["arguments"])}
        state["uploads"][key] = {"source": ref, "action": action}
        path.parent.mkdir(parents=True, exist_ok=True)
        artifacts.write_json_artifact(path, state)
        return action
    return None


def record_result(job_dir, request, action, response):
    binding = _binding(job_dir, request["purpose"])
    path, state = _state(job_dir, request, binding)
    saved = state["uploads"].get(action.get("binding_id"))
    # run_stage adds a step_id for the host; it is not part of the upload call.
    actual = {key: value for key, value in action.items() if key != "step_id"}
    if not saved or saved["action"] != actual:
        raise ValueError("upload result must identify its original action")
    value = response.get("structuredContent", response) if isinstance(response, dict) else response
    try:
        for key in binding["upload"]["result_path"]:
            value = value[key]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("upload response has no configured remote media reference") from exc
    if not isinstance(value, str) or not value.strip():
        raise ValueError("upload result must contain a real URL or asset ID")
    if saved.get("reference") and saved["reference"] != value:
        raise ValueError("upload result conflicts with the recorded reference")
    saved.update(reference=value, response=copy.deepcopy(response))
    artifacts.write_json_artifact(path, state)
    return {"request_id": request["id"], "status": "input_bound", "binding_id": action["binding_id"]}


def resolve_request(job_dir, request):
    """Materialize submission arguments without changing the approved request."""
    binding = _binding(job_dir, request["purpose"])
    result = copy.deepcopy(request)
    if binding["reference_mode"] == "local_path":
        return result
    _, state = _state(job_dir, request, binding)
    replacements = {}
    for local, ref in _references(job_dir, request):
        saved = state["uploads"].get(artifacts.sha256_json(ref), {})
        if not saved.get("reference"):
            raise ValueError("upload the approved reference before submitting generation")
        replacements[local] = saved["reference"]
    result["arguments"] = _replace(result["arguments"], replacements)
    return result


def evidence(job_dir, request):
    binding = _binding(job_dir, request["purpose"])
    if binding["reference_mode"] == "local_path":
        return []
    path, _ = _state(job_dir, request, binding)
    return ([{"path": str(path), "sha256": artifacts.sha256_file(path), "bytes": path.stat().st_size}]
            if path.is_file() else [])

"""Bind approved local references to the selected channel's actual upload result."""
from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import re
import secrets
from pathlib import Path

from . import contract_artifacts as artifacts

_LOVART_UPLOAD = "mcp__lovart__upload_asset"
_LOVART_BODY_LIMIT = 4 * 1024 * 1024
_LOVART_ENVELOPE_RESERVE = 64 * 1024


def _upload_body_bytes(arguments):
    # Count the actual JSON arguments, including base64, names and project ID.
    # Leave room for the MCP/HTTP envelope instead of treating PNG size as body size.
    return len(json.dumps(arguments, ensure_ascii=True, separators=(",", ":")).encode("utf-8")) + _LOVART_ENVELOPE_RESERVE


def _source_bytes(local, ref):
    data = Path(local).read_bytes()
    if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise ValueError("generation reference changed before upload")
    return data


def _generated_png(job_dir, local, ref):
    queue_path = Path(job_dir) / "manifests/generation-queue.json"
    if not queue_path.is_file():
        return False
    for item in artifacts.read_json_artifact(queue_path).get("items", {}).values():
        if item.get("status") != "completed" or item.get("request", {}).get("purpose") != "image":
            continue
        for output in item.get("completion_response", item.get("response", {})).get("artifacts", []):
            path = Path(output.get("path", ""))
            path = path if path.is_absolute() else Path(job_dir) / path
            if (output.get("type") == "image" and path == Path(local)
                    and output.get("sha256") == ref["sha256"] and output.get("bytes") == ref["bytes"]):
                return True
    return False


def _color_chunks(data):
    result, offset = {}, 8
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        if offset + length + 12 > len(data):
            raise ValueError("PNG chunk is incomplete")
        if kind in {b"cHRM", b"gAMA", b"sRGB", b"sBIT", b"cICP", b"pHYs"}:
            result[kind] = data[offset + 8:offset + 8 + length]
        offset += length + 12
        if kind == b"IEND":
            break
    return result


def _same_png_pixels(source, encoded):
    from PIL import Image
    with Image.open(io.BytesIO(source)) as before, Image.open(io.BytesIO(encoded)) as after:
        before.load()
        after.load()
        if (before.format != "PNG" or before.mode not in {"RGB", "RGBA"} or source[24] != 8
                or after.format != "PNG" or encoded[24] != 8
                or getattr(before, "n_frames", 1) != 1 or getattr(after, "n_frames", 1) != 1
                or before.mode != after.mode or before.size != after.size
                or before.tobytes() != after.tobytes()
                or before.convert("RGBA").tobytes() != after.convert("RGBA").tobytes()
                or before.info.get("icc_profile") != after.info.get("icc_profile")
                or before.getexif().get(274, 1) != after.getexif().get(274, 1)
                or _color_chunks(source) != _color_chunks(encoded)):
            raise ValueError("lossless PNG transport must preserve decoded pixels and color identity")
        return {"mode": before.mode, "size": list(before.size),
                "pixel_sha256": hashlib.sha256(before.tobytes()).hexdigest()}


def _lossless_png(data):
    from PIL import Image, PngImagePlugin
    with Image.open(io.BytesIO(data)) as image:
        if (image.format != "PNG" or image.mode not in {"RGB", "RGBA"} or data[24] != 8
                or getattr(image, "n_frames", 1) != 1):
            raise ValueError("lossless upload preparation requires a static 8-bit RGB/RGBA PNG")
        image.load()
        metadata = PngImagePlugin.PngInfo()
        for kind, value in _color_chunks(data).items():
            if kind != b"pHYs":
                metadata.add(kind, value)
        options = {key: image.info[key] for key in ("icc_profile", "exif", "transparency", "dpi") if key in image.info}
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True, compress_level=9, pnginfo=metadata, **options)
        encoded = output.getvalue()
    return encoded, _same_png_pixels(data, encoded)


def _upload_arguments(upload, local, data, filename):
    def build(value):
        if isinstance(value, dict):
            if value == {"$input": "path"}: return str(local)
            if value == {"$input": "filename"}: return filename
            if value == {"$input": "base64"}: return base64.b64encode(data).decode("ascii")
            return {key: build(item) for key, item in value.items()}
        if isinstance(value, list): return [build(item) for item in value]
        return value
    return build(upload["arguments"])


def _prepare_upload(job_dir, state_path, upload, local, ref, rejected=None):
    data = _source_bytes(local, ref)
    arguments = _upload_arguments(upload, local, data, Path(local).name)
    if upload["tool"] != _LOVART_UPLOAD or (rejected is None and _upload_body_bytes(arguments) <= _LOVART_BODY_LIMIT):
        return arguments, None
    if Path(local).suffix.lower() != ".png" or not _generated_png(job_dir, local, ref):
        raise ValueError("Lovart upload exceeds its JSON body limit; only this Job's completed generated PNG may be re-encoded losslessly")
    encoded, pixels = _lossless_png(data)
    digest = hashlib.sha256(encoded).hexdigest()
    target = state_path.parent / ("transport-" + digest + ".png")
    arguments = _upload_arguments(upload, target, encoded, Path(local).name)
    if _upload_body_bytes(arguments) > _LOVART_BODY_LIMIT:
        raise ValueError("lossless PNG transport still exceeds the Lovart JSON body limit; stop without resizing or lossy conversion")
    if rejected is not None and _upload_body_bytes(arguments) >= _upload_body_bytes(rejected):
        raise ValueError("rejected upload has no smaller lossless payload; inspect the original failure before retrying")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.resolve() != target.parent.absolute() or target.is_symlink():
        raise ValueError("upload transport must remain in the existing Job cache")
    try:
        with target.open("xb") as handle: handle.write(encoded)
    except FileExistsError:
        if target.read_bytes() != encoded:
            raise ValueError("existing lossless upload transport changed")
    return arguments, {"path": str(target.relative_to(job_dir)), "sha256": digest, "bytes": len(encoded),
                       "source_sha256": ref["sha256"], "method": "png-lossless-reencode", **pixels}


def _verify_transport(job_dir, ref, transport):
    relative = Path(transport["path"])
    if relative.is_absolute() or ".." in relative.parts or transport["source_sha256"] != ref["sha256"]:
        raise ValueError("lossless upload transport source changed")
    path = Path(job_dir) / relative
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("lossless upload transport path changed")
    encoded = _source_bytes(path, transport)
    pixels = _same_png_pixels(_source_bytes(Path(job_dir) / ref["path"], ref), encoded)
    if any(transport.get(key) != value for key, value in pixels.items()):
        raise ValueError("lossless upload transport pixel identity changed")


def _known_lovart_413(action, response):
    if action.get("tool") != _LOVART_UPLOAD or not isinstance(response, dict) or response.get("isError") is not True:
        return False
    text = "\n".join(item.get("text", "") for item in response.get("content", []) if item.get("type") == "text")
    return bool(re.search(r"HTTP\s+413\b", text) and re.search(r"request body exceeds\s+4194304\s+bytes", text))


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
            if not saved.get("rejected_body_limit"):
                return {"action": "blocked", "status": "input_upload_pending", "request_id": request["id"],
                        "binding_id": key, "next": "回传已发出的原 upload action 与真实结果后继续。"}
        upload = binding["upload"]
        arguments, transport = _prepare_upload(job_dir, path, upload, local, ref,
            rejected=saved["action"]["arguments"] if saved else None)
        action = {"action": "upload", "purpose": request["purpose"], "request_id": request["id"],
                  "binding_id": key, "claim_token": secrets.token_urlsafe(24),
                  "tool": upload["tool"], "arguments": arguments}
        saved = saved or {"source": ref}
        saved.update(action=action)
        saved.pop("rejected_body_limit", None)
        if transport is not None: saved["transport"] = transport
        state["uploads"][key] = saved
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
        if saved and {"action": actual, "response": response} in saved.get("rejected_uploads", []):
            return {"request_id": request["id"], "status": "input_upload_rejected_413", "binding_id": action["binding_id"]}
        raise ValueError("upload result must identify its original action")
    if _known_lovart_413(action, response):
        if saved.get("reference"):
            raise ValueError("upload failure conflicts with its recorded reference")
        failure = {"action": copy.deepcopy(actual), "response": copy.deepcopy(response)}
        history = saved.setdefault("rejected_uploads", [])
        if failure not in history: history.append(failure)
        saved["rejected_body_limit"] = True
        artifacts.write_json_artifact(path, state)
        return {"request_id": request["id"], "status": "input_upload_rejected_413", "binding_id": action["binding_id"]}
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
    if saved.get("transport"):
        _verify_transport(job_dir, saved["source"], saved["transport"])
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
        if saved.get("transport"):
            _verify_transport(job_dir, ref, saved["transport"])
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

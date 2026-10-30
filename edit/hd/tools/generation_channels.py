"""Expose actual selected host tools and persist their real media results."""
from __future__ import annotations
import copy
import shutil
import time
import urllib.request
from pathlib import Path
from . import startup, generation_queue, generation_model, generation_inputs, contract_artifacts as artifacts

def _job(value):
    if hasattr(value, "job_dir"):
        return value
    from . import state
    return state.load_job(Path(value))

def selected_channel(job, purpose):
    job = _job(job)
    config_path, _ = startup._config(job)
    config = startup._read(config_path, "provider config")
    selected = [p for p in config["providers"] if p["purpose"] == purpose]
    if len(selected) != 1 or selected[0]["connection_status"] != "verified":
        raise startup.WorkflowError("no verified " + purpose + " generation channel")
    return selected[0]

def prepare_request(job, purpose, arguments, *, request_id, input_files=None):
    job = _job(job)
    channel = selected_channel(job, purpose)
    return {"id": request_id, "purpose": purpose, "tool": channel["endpoint_id"],
            "arguments": generation_model.prepare_arguments(job.job_dir, channel, arguments),
            "input_files": list(input_files or [])}

def _query_binding(job, item):
    path = job.job_dir / "manifests/generation-channels.json"
    bindings = artifacts.read_json_artifact(path) if path.is_file() else {}
    query = bindings.get(item["request"]["purpose"], {}).get("query")
    if query is None and item["request"]["tool"] == "mcp__lovart__generate_video":
        query = {"tool": "mcp__lovart__get_task_status", "task_ids_parameter": "task_ids",
                 "arguments": {"project_id": item["request"]["arguments"]["project_id"]}}
    return query

def next_action(job, request_id, *, account_limit=None):
    job = _job(job)
    queue = generation_queue.status(job.job_dir)
    item = queue["items"].get(request_id)
    if item and item["status"] == "ready" and not queue["paused"]:
        _, _, config = generation_queue._approved(job.job_dir)
        generation_queue._request(job.job_dir, item["request"], config)
        upload = generation_inputs.next_action(job.job_dir, item["request"])
        if upload is not None:
            return upload
    result = generation_queue.claim(job.job_dir, request_id, account_limit)
    if result.get("action") == "blocked" and result.get("status") in {"pending", "unknown"}:
        item = generation_queue.status(job.job_dir)["items"][request_id]
        ids = item.get("task_ids", [])
        if not ids:
            return {"action": "blocked", "status": "generation_result_unknown",
                    "request_id": request_id, "next": "核对原提交结果；不要重新提交。"}
        if item.get("next_poll_at", 0) > time.time():
            return {"action": "wait", "request_id": request_id, "next_poll_at": item["next_poll_at"]}
        query = _query_binding(job, item)
        if not isinstance(query, dict) or not query.get("tool"):
            return {"action": "blocked", "status": "missing_query_channel", "request_id": request_id}
        args = {**query.get("arguments", {}), query.get("task_ids_parameter", "task_ids"): ids}
        return {"action": "query", "purpose": item["request"]["purpose"],
                "tool": query["tool"], "arguments": args, "task_ids": ids,
                "request_id": request_id, "claim_token": item["claim_token"]}
    if result.get("action") != "generate":
        return result
    item = generation_queue.status(job.job_dir)["items"][request_id]
    return {"action": "submit", "purpose": item["request"]["purpose"],
            "tool": result["tool"], "arguments": result["arguments"],
            "claim_token": result["claim_token"], "request_id": request_id}

def record_result(job, action, response, *, queried_task_ids=None):
    job = _job(job)
    if not isinstance(action, dict) or not action.get("request_id") or not action.get("claim_token"):
        raise ValueError("record_result requires the original concrete host action")
    item = generation_queue.status(job.job_dir)["items"].get(action["request_id"], {})
    if action.get("action") == "upload":
        if item.get("status") != "ready":
            raise ValueError("reference upload belongs to a pending generation request")
        return generation_inputs.record_result(job.job_dir, item["request"], action, response)
    raw = response.get("structuredContent", response) if isinstance(response, dict) else response
    if not isinstance(raw, dict):
        raise ValueError("record the real structured provider response")
    if item.get("claim_token") != action["claim_token"]:
        raise ValueError("generation result does not identify its original claim")
    payload = copy.deepcopy(raw)
    identity = item["channel_identity"]
    if payload.get("provider", identity["provider"]) != identity["provider"]:
        raise ValueError("generation result provider differs from the submitted channel")
    if payload.get("model", identity["model"]) != identity["model"]:
        raise ValueError("generation result model differs from the submitted model")
    payload["provider"] = identity["provider"]
    payload["model"] = identity["model"]
    if payload.get("status") == "completed":
        outputs = payload.get("artifacts")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError("completed generation needs actual output media")
        saved = []
        directory = job.job_dir / "generated-media" / action["request_id"]
        directory.mkdir(parents=True, exist_ok=True)
        for index, output in enumerate(outputs):
            if output.get("type") != item["request"]["purpose"]:
                raise ValueError("generated media type differs from the selected channel")
            if ("source" in output) != ("processing" in output):
                raise ValueError("prepared media requires both original source and processing description")
            source = Path(output["path"]) if output.get("path") else None
            if source is not None and not source.is_absolute():
                source = job.job_dir / source
            suffix = source.suffix if source is not None else (".png" if output["type"] == "image" else ".mp4")
            target = directory / (str(index) + suffix)
            if source is not None:
                if source.resolve() != target.resolve():
                    if target.exists():
                        if artifacts.sha256_file(target) != artifacts.sha256_file(source):
                            raise ValueError("a different result already exists for this generation")
                    else:
                        shutil.copyfile(source, target)
            else:
                url = output.get("url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    raise ValueError("generation output needs a real local path or media URL")
                if not target.exists():
                    temporary = target.with_suffix(target.suffix + ".part")
                    request = urllib.request.Request(url, headers={
                        'User-Agent': 'HD-Talking-Head/1.0 (authorized artifact retrieval)'})
                    with urllib.request.urlopen(request, timeout=120) as incoming, temporary.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    temporary.rename(target)
            media = {"type": output["type"], "path": str(target),
                     "bytes": target.stat().st_size, "sha256": artifacts.sha256_file(target)}
            if output.get("source") is not None:
                original = Path(output["source"]["path"])
                if not original.is_absolute():
                    original = job.job_dir / original
                processing = output.get("processing")
                if not isinstance(processing, str) or not processing.strip():
                    raise ValueError("prepared media must describe its actual processing")
                original_target = directory / ("source-" + str(index) + original.suffix)
                if original.resolve() != original_target.resolve():
                    if original_target.exists():
                        if artifacts.sha256_file(original_target) != artifacts.sha256_file(original):
                            raise ValueError("a different original media file is already recorded")
                    else:
                        shutil.copyfile(original, original_target)
                media.update(source={"path": str(original_target), "sha256": artifacts.sha256_file(original_target),
                                     "bytes": original_target.stat().st_size}, processing=processing)
            saved.append(media)
        payload["artifacts"] = saved
    if queried_task_ids is None and action.get("action") == "query":
        queried_task_ids = action.get("task_ids")
    result = generation_queue.record(job.job_dir, action["request_id"], action["claim_token"],
                                     payload, queried_task_ids=queried_task_ids)
    # This is the host's normalized response, not necessarily the provider payload.
    evidence = job.job_dir / "generated-media" / action["request_id"]
    evidence.mkdir(parents=True, exist_ok=True)
    response_name = "query-response-" + artifacts.sha256_json(raw)[:16] + ".json" if action.get("action") == "query" else "submission-response.json"
    path = evidence / response_name
    if not path.exists():
        artifacts.write_json_artifact(path, raw)
    if raw.get("provider_response") is not None:
        artifacts.write_json_artifact(evidence / ("provider-" + response_name), raw["provider_response"])
    return {**result, "artifacts": payload.get("artifacts", [])}

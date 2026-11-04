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

def prepare_cover_request(job, arguments, *, request_id):
    """Bind the approved person and composition references for this cover call."""
    from . import cover_direction, state
    job = _job(job)
    cover_direction.load_approved_cover_direction(job)
    approved = job.stages["cover_direction"]["artifacts"]
    frozen = {}
    for record in approved:
        if (record["path"] in frozen
                or state._artifact_record(job, job.job_dir / record["path"]) != record):
            raise ValueError("approved cover direction artifact changed")
        frozen[record["path"]] = record
    required = ("03-cover-direction/person-reference.png", "03-cover-direction/direction-preview.png")
    if not {"03-cover-direction/cover-direction.json", *required}.issubset(frozen):
        raise ValueError("approved cover direction needs its direction record and person/preview images")
    if generation_inputs._binding(job.job_dir, "image")["reference_mode"] != "local_path":
        raise ValueError("cover generation requires a local_path multi-reference channel")
    if selected_channel(job, "image").get("reference_images") is False:
        raise ValueError("selected image channel does not support reference images")
    if not isinstance(arguments, dict) or "num_last_images_to_include" in arguments:
        raise ValueError("cover generation requires explicit frozen local reference paths")
    references = arguments.get("referenced_image_paths", [])
    references = [] if references is None else references
    if not isinstance(references, list) or any(not isinstance(value, str) or not value for value in references):
        raise ValueError("cover reference paths must be a list of local paths")
    approved_inputs = {job.job_dir / name: frozen[name] for name in required}
    paths = []
    for value in references:
        path = Path(value)
        path = path if path.is_absolute() else job.job_dir / path
        paths.append(path)
    paths.extend(path for path in approved_inputs if path not in paths)
    inputs = [copy.deepcopy(approved_inputs[path]) if path in approved_inputs
              else state._artifact_record(job, path) for path in paths]
    args = copy.deepcopy(arguments)
    args["referenced_image_paths"] = [str(path) for path in paths]
    request = prepare_request(job, "image", args, request_id=request_id, input_files=inputs)
    generation_queue._inputs(job.job_dir, request)
    return request

def _query_binding(job, item):
    path = job.job_dir / "manifests/generation-channels.json"
    bindings = artifacts.read_json_artifact(path) if path.is_file() else {}
    query = bindings.get(item["request"]["purpose"], {}).get("query")
    if query is None and item["request"]["tool"] == "mcp__lovart__generate_video":
        query = {"tool": "mcp__lovart__get_task_status", "task_ids_parameter": "task_ids",
                 "arguments": {"project_id": item["request"]["arguments"]["project_id"]}}
    if (isinstance(query, dict) and query.get("tool") == "mcp__lovart__get_task_status"
            and item["request"]["tool"] == "mcp__lovart__generate_video"):
        query = copy.deepcopy(query)
        project = item["request"]["arguments"].get("project_id")
        args = query.setdefault("arguments", {})
        if (not isinstance(project, str) or not project or not isinstance(args, dict)
                or args.get("project_id", project) != project
                or query.get("task_ids_parameter", "task_ids") == "project_id"):
            raise ValueError("Lovart query project_id conflicts with the approved video request")
        args["project_id"] = project
    return query

def next_action(job, request_id, *, account_limit=None):
    job = _job(job)
    with generation_queue._locked(job.job_dir) as (j, queue_path, queue):
        item = queue["items"].get(request_id)
        if item and item["status"] == "ready" and not queue["paused"]:
            jid, digest, config = generation_queue._approved(j)
            identity = generation_queue._request(j, item["request"], config)
            if (jid != queue["job_id"] or digest != item["config_sha256"]
                    or identity != item.get("channel_identity")):
                raise ValueError("generation configuration changed before reference upload")
            generation_queue.validate_submission_authorization(j, queue, request_id)
            artifacts.write_json_artifact(queue_path, queue)
            upload = generation_inputs.next_action(j, item["request"])
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

def _waiting_action(job, request_id, item):
    status = item['status']
    if status not in {'pending', 'unknown'}:
        return {'action': 'blocked', 'status': status, 'id': request_id}
    ids = item.get('task_ids', [])
    if not ids:
        return {'action': 'blocked', 'status': 'generation_result_unknown',
                'request_id': request_id, 'next': '核对原提交结果；不要重新提交。'}
    if item.get('next_poll_at', 0) > time.time():
        return {'action': 'wait', 'request_id': request_id, 'next_poll_at': item['next_poll_at']}
    query = _query_binding(job, item)
    if not isinstance(query, dict) or not query.get('tool'):
        return {'action': 'blocked', 'status': 'missing_query_channel', 'request_id': request_id}
    return {'action': 'query', 'purpose': item['request']['purpose'], 'tool': query['tool'],
            'arguments': {**query.get('arguments', {}), query.get('task_ids_parameter', 'task_ids'): ids},
            'task_ids': ids, 'request_id': request_id, 'claim_token': item['claim_token']}


def issue_actions(job, candidates, response, *, account_limit=None):
    """Publish only prebuilt actions; preserve every issued action on later I/O failure."""
    job = _job(job)
    errors = response.setdefault('errors', [])
    ready = []
    def failed(candidate, error):
        errors.append({key: candidate[key] for key in ('segment_id', 'component_id', 'step_id', 'request_id')
                       if key in candidate} | {'error': str(error)})
    for candidate in candidates:
        if candidate.get('action') != 'issue_generation':
            response['actions'].append(candidate)
            continue
        try:
            request = candidate.get('request')
            if request is not None:
                plan = {'requests': [request]}
                generation_queue.add_authorized(job.job_dir, plan, candidate['authorization'], artifacts.sha256_json(plan))
            ready.append(candidate)
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            failed(candidate, error)
    authorizations = [candidate['authorization'] for candidate in candidates
                      if candidate.get('action') == 'issue_generation' and candidate.get('authorization')]
    if not ready and not authorizations:
        return response
    with generation_queue._locked(job.job_dir) as (root, queue_path, queue):
        needs_approval = any(queue['items'].get(c['request_id'], {}).get('status') == 'ready' for c in ready)
        approved = generation_queue._approved(root) if needs_approval else None
        # Configuration and global authorization are checked before any token is published.
        if authorizations:
            from . import state, visual_confirmation
            current = visual_confirmation.validate_visual_authorization(state.load_job(root))
            if any(authorization.get('source') != current['artifact'] for authorization in authorizations):
                raise ValueError('visual authorization changed before action issuance')
        if approved is not None:
            jid, digest, config = approved
            for candidate in ready:
                item = queue['items'].get(candidate['request_id'], {})
                if item.get('status') == 'ready' and (jid != queue['job_id'] or item.get('config_sha256') != digest):
                    raise ValueError('generation configuration changed before action issuance')
        planned, uploads, submitted = [], [], []
        for candidate in ready:
            rid = candidate['request_id']
            try:
                update, is_submission = None, False
                item = queue['items'][rid]
                if item['status'] in {'failed', 'moderated'}:
                    raise ValueError('generation is ' + item['status'] + '; inspect the original result, do not resubmit')
                if item['status'] != 'ready':
                    action = _waiting_action(job, rid, item)
                else:
                    identity = generation_queue._request(root, item['request'], config)
                    if identity != item.get('channel_identity'):
                        raise ValueError('generation channel identity changed before action issuance')
                    generation_queue.validate_submission_authorization(root, queue, rid)
                    action, update = ((None, None) if queue['paused'] else
                                      generation_inputs.prepare_next_action(root, item['request']))
                    if action is None:
                        claimed = generation_queue._claim_locked(root, queue, rid, *approved, account_limit)
                        action = ({'action': 'submit', 'purpose': item['request']['purpose'],
                                   'tool': claimed['tool'], 'arguments': claimed['arguments'],
                                   'claim_token': claimed['claim_token'], 'request_id': rid}
                                  if claimed['action'] == 'generate' else claimed)
                        is_submission = claimed['action'] == 'generate'
                # Upload state stores the unadorned tool action; parent metadata
                # belongs only to the returned copy used by record_result.
                action = {**action, 'step_id': candidate['step_id']}
                if is_submission:
                    submitted.append(action)
                elif update is not None:
                    uploads.append((action, update, candidate))
                planned.append(action)
            except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
                failed(candidate, error)
        # No later business check or response construction may discard issued tokens.
        artifacts.canonical_json_bytes({**response, 'actions': [*response['actions'], *planned]})
        upload_ids = {id(action) for action, _, _ in uploads}
        submitted_ids = {id(action) for action in submitted}
        response['actions'].extend(action for action in planned
                                   if id(action) not in upload_ids | submitted_ids)
        for action, update, candidate in uploads:
            try:
                artifacts.write_json_artifact(*update)
            except (ValueError, OSError, RuntimeError) as error:
                # A publication can fail after replace; return its original action only
                # when the exact token is already present, never mint a replacement.
                try:
                    persisted = artifacts.read_json_artifact(update[0]) == update[1]
                except (ValueError, OSError):
                    persisted = False
                if persisted:
                    response['actions'].append(action)
                failed(candidate, error)
            else:
                response['actions'].append(action)
        if submitted or uploads or needs_approval:
            try:
                artifacts.write_json_artifact(queue_path, queue)
            except (ValueError, OSError, RuntimeError) as error:
                try:
                    saved = artifacts.read_json_artifact(queue_path)
                    persisted = all(saved['items'][a['request_id']].get('claim_token') == a['claim_token']
                                    for a in submitted)
                except (ValueError, OSError, KeyError):
                    persisted = False
                if persisted:
                    response['actions'].extend(submitted)
                errors.append({'error': str(error), 'scope': 'generation_queue'})
            else:
                response['actions'].extend(submitted)
    return response


def record_result(job, action, response, *, queried_task_ids=None):
    job = _job(job)
    if not isinstance(action, dict) or not action.get("request_id") or not action.get("claim_token"):
        raise ValueError("record_result requires the original concrete host action")
    if action.get("action") == "upload":
        with generation_queue._locked(job.job_dir) as (j, _, queue):
            item = queue["items"].get(action["request_id"], {})
            if item.get("status") != "ready":
                raise ValueError("reference upload belongs to a pending generation request")
            return generation_inputs.record_result(j, item["request"], action, response)
    item = generation_queue.status(job.job_dir)["items"].get(action["request_id"], {})
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


def replace_unsent_upload(job, action, evidence):
    job = _job(job)
    if not isinstance(action, dict) or not action.get("request_id"):
        raise ValueError("replacement requires the original concrete action")
    with generation_queue._locked(job.job_dir) as (j, _, queue):
        item = queue["items"].get(action["request_id"], {})
        if item.get("status") != "ready" or queue["paused"]:
            raise ValueError("replacement requires an unpaused ready request")
        jid, digest, config = generation_queue._approved(j)
        identity = generation_queue._request(j, item["request"], config)
        if jid != queue["job_id"] or digest != item["config_sha256"] or identity != item["channel_identity"]:
            raise ValueError("replacement requires the original approved generation identity")
        generation_queue.validate_submission_authorization(j, queue, action["request_id"])
        return generation_inputs.replace_unsent_lovart_upload(j, item["request"], action, evidence)

"""Durable admission for host generation tools; this module never generates media."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import secrets
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import contract_artifacts as artifacts, startup, state, generation_model

ACTIVE = {"submitting", "pending", "unknown"}
TERMINAL = {"completed", "failed", "moderated"}


class GenerationQueueError(ValueError):
    pass


def _regular(path):
    if path.resolve() != path.absolute():
        raise GenerationQueueError("queue paths cannot contain symlinks")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise GenerationQueueError("queue files must be regular single-link files")


def _json_safe(value):
    if isinstance(value, dict):
        if any(str(k).lower() in {"api_key", "apikey", "password", "credentials", "access_token", "authorization"} for k in value):
            raise GenerationQueueError("credentials cannot enter generation records")
        for v in value.values():
            _json_safe(v)
    elif isinstance(value, list):
        for v in value:
            _json_safe(v)
    elif isinstance(value, str) and value.startswith("data:"):
        raise GenerationQueueError("save media files, not base64, in generation records")
    if len(artifacts.canonical_json_bytes(value)) > 200_000:
        raise GenerationQueueError("generation record is too large")


def _directory(job):
    path = Path(job).expanduser().absolute()
    if path.resolve() != path or not (path / "manifests").is_dir():
        raise GenerationQueueError("use an existing, local Job directory")
    if (path / "manifests").resolve() != path / "manifests":
        raise GenerationQueueError("manifests cannot be a symlink")
    return path


@contextmanager
def _locked(job):
    j = _directory(job)
    path = j / "manifests/generation-queue.json"
    lock = j / "manifests/generation-queue.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise GenerationQueueError("invalid generation queue lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.path.lexists(path):
            _regular(path)
            q = artifacts.read_json_artifact(path)
            if (q.get("schema_version") != 1 or q.get("job_dir") != str(j)
                    or not isinstance(q.get("items"), dict)):
                raise GenerationQueueError("invalid generation queue")
            for item in q["items"].values():
                if item.get("status") not in ACTIVE | TERMINAL | {"ready"}:
                    raise GenerationQueueError("invalid generation status")
                if item.get("fingerprint") != _fingerprint(item["request"]):
                    raise GenerationQueueError("generation request changed")
        else:
            q = {"schema_version": 1, "job_dir": str(j), "job_id": None,
                 "max_concurrency": None, "paused": False, "items": {}}
        yield j, path, q
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _approved(j):
    job = state.load_job(j)
    if not (job.root / "job-context.json").is_file():
        raise GenerationQueueError("generation requires a Skill-managed Job")
    startup.require_startup(job)
    path, digest = startup._config(job)
    raw = path.read_bytes()
    approval = artifacts.read_json_artifact(j / "manifests/setup-approval.json")
    if hashlib.sha256(raw).hexdigest() != digest or approval.get("provider_config_sha256") != digest:
        raise GenerationQueueError("configuration or its approval changed")
    config = json.loads(raw)
    if artifacts.sha256_file(path) != digest:
        raise GenerationQueueError("configuration changed during read")
    if not config["generation_enabled"]:
        raise GenerationQueueError("generation is disabled")
    return job.job_id, digest, config


def _inputs(j, request):
    for ref in request["input_files"]:
        if set(ref) != {"path", "sha256", "bytes"} or type(ref["bytes"]) is not int:
            raise GenerationQueueError("invalid input identity")
        path = j / ref["path"]
        if not path.absolute().is_relative_to(j) or Path(ref["path"]).is_absolute():
            raise GenerationQueueError("generation inputs must belong to this Job")
        _regular(path)
        if path.stat().st_size != ref["bytes"] or artifacts.sha256_file(path) != ref["sha256"]:
            raise GenerationQueueError("generation input changed")
    declared = {str((j / ref["path"]).absolute()) for ref in request["input_files"]}
    if any(str(p) not in declared for p in request["arguments"].get("referenced_image_paths", []) or []):
        raise GenerationQueueError("reference images need frozen local input identities")


def _request(j, req, config):
    if (not isinstance(req, dict) or set(req) != {"id", "purpose", "tool", "arguments", "input_files"}
            or not isinstance(req["id"], str) or not req["id"].strip()
            or req["purpose"] not in {"image", "video"}
            or not isinstance(req["arguments"], dict) or not isinstance(req["input_files"], list)):
        raise GenerationQueueError("one request must identify one supported image/video call")
    _json_safe(req)
    providers = [p for p in config["providers"] if p["purpose"] == req["purpose"]]
    if (len(providers) != 1 or providers[0]["endpoint_id"] != req["tool"]
            or providers[0]["connection_status"] != "verified"
            or providers[0]["quota_status"] == "unavailable"):
        raise GenerationQueueError("generation tool differs from confirmed provider")
    try:
        identity = generation_model.request_identity(j, req, config)
    except ValueError as exc:
        raise GenerationQueueError(str(exc)) from exc
    args = req["arguments"]
    if req["purpose"] == "video" and (providers[0].get("provider") == "Lovart" or req["tool"] == "mcp__lovart__generate_video"):
        if not isinstance(args.get("project_id"), str) or not args["project_id"]:
            raise GenerationQueueError("Lovart requires one real project_id")
    if "num_last_images_to_include" in args:
        raise GenerationQueueError("queued image references must use frozen local paths")
    _inputs(j, req)
    return identity


def _fingerprint(req):
    return artifacts.sha256_json({k: v for k, v in req.items() if k != "id"})


def _add(job, plan, user_confirmation, expected_plan_sha256, authorization=None):
    """Capture the host's real permission for this exact ready-to-call batch."""
    if (not isinstance(plan, dict) or set(plan) != {"requests"}
            or not isinstance(plan["requests"], list) or not plan["requests"]
            or artifacts.sha256_json(plan) != expected_plan_sha256
            or (user_confirmation is not None and (not isinstance(user_confirmation, str) or not user_confirmation.strip()))):
        raise GenerationQueueError("capture real permission and the exact approved plan hash")
    with _locked(job) as (j, path, q):
        jid, config_sha, config = _approved(j)
        if q["job_id"] not in {None, jid}:
            raise GenerationQueueError("queue belongs to another Job")
        requests = plan["requests"]
        identities = {req["id"]: _request(j, req, config) for req in requests}
        if len({r["id"] for r in requests}) != len(requests):
            raise GenerationQueueError("duplicate request id")
        projects = {x["request"]["arguments"]["project_id"] for x in q["items"].values()
                    if x["request"]["purpose"] == "video" and x["request"]["tool"] == "mcp__lovart__generate_video"
                    and isinstance(x["request"]["arguments"].get("project_id"), str)}
        projects.update(r["arguments"]["project_id"] for r in requests
                        if r["purpose"] == "video" and r["tool"] == "mcp__lovart__generate_video"
                        and isinstance(r["arguments"].get("project_id"), str))
        if len(projects) > 1:
            raise GenerationQueueError("all Lovart calls in this Job must use one project")
        fingerprints = {item["fingerprint"] for item in q["items"].values()}
        for req in requests:
            rid, fp = req["id"], _fingerprint(req)
            if rid in q["items"] and q["items"][rid]["request"] != req:
                raise GenerationQueueError("request id already has different content")
            if rid not in q["items"] and fp in fingerprints:
                raise GenerationQueueError("same call already registered under another id; reuse it")
            fingerprints.add(fp)
        for req in requests:
            rid = req["id"]
            if rid not in q["items"]:
                q["items"][rid] = {"request": req, "fingerprint": _fingerprint(req), "status": "ready",
                                    "channel_identity": identities[rid]}
            if q["items"][rid]["status"] == "ready" and "retry_of" not in q["items"][rid]:
                q["items"][rid].update(config_sha256=config_sha, approved_plan_sha256=expected_plan_sha256,
                                      **({"user_confirmation": user_confirmation} if user_confirmation is not None else {}),
                                      **({"authorization": authorization} if authorization is not None else {}))
        q.update(job_id=jid, max_concurrency=config["max_concurrency"])
        artifacts.write_json_artifact(path, q)
        return {"ids": [r["id"] for r in requests], "max_concurrency": q["max_concurrency"]}


def add(job, plan, user_confirmation, expected_plan_sha256):
    if not isinstance(user_confirmation, str) or not user_confirmation.strip():
        raise GenerationQueueError("capture explicit setup confirmation")
    return _add(job, plan, user_confirmation, expected_plan_sha256)


def add_authorized(job, plan, authorization, expected_plan_sha256):
    """Register an already-confirmed visual plan without copying its prose approval."""
    if not isinstance(authorization, dict) or set(authorization) != {"source", "steps"}:
        raise GenerationQueueError("generation authorization needs source and step bindings")
    source = authorization["source"]
    steps = authorization["steps"]
    if (not isinstance(source, dict) or not isinstance(source.get("path"), str)
            or not isinstance(source.get("sha256"), str) or not isinstance(steps, dict)):
        raise GenerationQueueError("invalid visual authorization descriptor")
    if set(steps) != {r.get("id") for r in plan.get("requests", [])}:
        raise GenerationQueueError("authorization must identify every request exactly once")
    for rid, step in steps.items():
        if not isinstance(step, str) or not step.strip():
            raise GenerationQueueError("authorization step ids must be non-empty")
    try:
        from . import visual_confirmation
        for request in plan["requests"]:
            visual_confirmation.validate_generation_request(state.load_job(_directory(job)), authorization, request)
    except Exception as exc:
        if isinstance(exc, (GenerationQueueError, state.WorkflowError)):
            raise
        raise GenerationQueueError("visual authorization could not be validated") from exc
    authorization_ref = {"source": source, "steps": steps}
    return _add(job, plan, None, expected_plan_sha256, authorization=authorization_ref)


def _retry_plan(q, request_id):
    item = q["items"].get(request_id)
    if item is None or item["status"] != "failed":
        raise GenerationQueueError("retry requires an exact, definitively failed request")
    response = item.get("response", {})
    source = item.get("response_source", {})
    ids = item.get("task_ids", [])
    if (response.get("status") != "failed" or response.get("artifacts")
            or len(ids) > 1 or artifacts.sha256_json(response) != item.get("response_sha256")
            or not (source.get("kind") == "submission"
                    or source == {"kind": "query", "task_ids": ids} and len(ids) == 1)):
        raise GenerationQueueError("failure needs the exact submission or one-task query evidence")
    return {"job_id": q["job_id"], "from_id": request_id,
            "failure_response_sha256": item["response_sha256"],
            "request_fingerprint": item["fingerprint"], "config_sha256": item["config_sha256"],
            "input_files": item["request"]["input_files"], "count": 1}


def _retry_gate(j, q, item):
    jid, digest, config = _approved(j)
    if jid != q["job_id"] or digest != item["config_sha256"]:
        raise GenerationQueueError("retry configuration changed; replan instead")
    _request(j, item["request"], config)


def prepare_retry(job, request_id):
    """Freeze one failed attempt for a new human decision; submit nothing."""
    with _locked(job) as (j, _, q):
        plan = _retry_plan(q, request_id)
        if any(x.get("retry_of") == request_id for x in q["items"].values()):
            raise GenerationQueueError("request already has a retry; inspect that exact successor")
        item = q["items"][request_id]
        _retry_gate(j, q, item)
        return {"plan": plan, "plan_sha256": artifacts.sha256_json(plan),
                "request": item["request"], "plan_request_id": item.get("plan_request_id", request_id)}


def retry(job, plan, user_confirmation, expected_plan_sha256):
    """Consume permission for exactly one successor, never reset the predecessor."""
    if (not isinstance(plan, dict) or set(plan) != {"job_id", "from_id", "failure_response_sha256",
                                                   "request_fingerprint", "config_sha256", "input_files", "count"}
            or type(plan["count"]) is not int or plan["count"] != 1
            or not isinstance(plan["from_id"], str) or not plan["from_id"]
            or artifacts.sha256_json(plan) != expected_plan_sha256
            or not isinstance(user_confirmation, str) or not user_confirmation.strip()):
        raise GenerationQueueError("capture new permission for the exact frozen retry plan")
    _json_safe(plan)
    with _locked(job) as (j, path, q):
        existing = [(rid, x) for rid, x in q["items"].items() if x.get("retry_of") == plan["from_id"]]
        if existing:
            rid, item = existing[0]
            if len(existing) != 1 or item.get("retry_plan") != plan:
                raise GenerationQueueError("failed request already has a different retry")
            return {"id": rid, "retry_of": plan["from_id"],
                    "plan_request_id": item["plan_request_id"], "idempotent": True}
        if _retry_plan(q, plan["from_id"]) != plan:
            raise GenerationQueueError("retry snapshot changed; obtain a new decision")
        parent = q["items"][plan["from_id"]]
        _retry_gate(j, q, parent)
        rid = "retry-" + expected_plan_sha256
        if rid in q["items"]:
            raise GenerationQueueError("retry id already registered")
        request = json.loads(json.dumps(parent["request"]))
        request["id"] = rid
        root_id = parent.get("plan_request_id", plan["from_id"])
        q["items"][rid] = {"request": request, "fingerprint": parent["fingerprint"], "status": "ready",
                           "retry_of": plan["from_id"], "plan_request_id": root_id, "retry_plan": plan,
                           "channel_identity": parent["channel_identity"],
                           "config_sha256": parent["config_sha256"], "approved_plan_sha256": expected_plan_sha256,
                           "user_confirmation": user_confirmation}
        artifacts.write_json_artifact(path, q)
        return {"id": rid, "retry_of": plan["from_id"], "plan_request_id": root_id, "idempotent": False}


def _validate_followup_image_evidence(job, parent, plan, approved):
    """Bind a human-observed Paper sample failure to the approved image and clock."""
    from . import visual_confirmation as visual
    proof = plan.get('followup_evidence')
    names = {'brief', 'crop_provenance', 'render_evidence', 'media_manifest', 'review', 'preview'}
    if not isinstance(proof, dict) or set(proof) != names:
        raise GenerationQueueError('follow-up image edit requires complete sample evidence')
    root = Path(job.job_dir)
    try:
        paths = {key: visual._exact(root, proof[key]) for key in names}
        brief = artifacts.read_json_artifact(paths['brief'])
        review = artifacts.read_json_artifact(paths['review'])
        render = artifacts.read_json_artifact(paths['render_evidence'])
        manifest = artifacts.read_json_artifact(paths['media_manifest'])
        outputs = parent['completion_response']['artifacts']
        if len(outputs) != 1 or outputs[0].get('type') != 'image':
            raise GenerationQueueError('follow-up needs one completed original image')
        image = Path(outputs[0]['path'])
        if not image.is_absolute(): image = root / image
        original = visual._record(root, image)
        if (original['sha256'], original['bytes']) != (outputs[0]['sha256'], outputs[0]['bytes']):
            raise GenerationQueueError('follow-up original image changed')
        _, proposal = visual._validate_source(root, parent['authorization']['source'], job_id=job.job_id)
        director = artifacts.read_json_artifact(visual._exact(root, proposal['inputs']['director']))
        step = approved['step']
        segment = next(s for s in director['segments'] if s['segment_id'] == step['segment_id'])
        if (step.get('purpose') != 'image' or segment['bindings'][step['component_id']].get('dependency_id') != 'paper-collage-hyperframes'):
            raise GenerationQueueError('follow-up sample is not the approved Paper image row')
        arroll = [r for r in job.stages['edit_structure']['artifacts']
                  if r['path'] == '06-edit-structure/edited-aroll.mp4']
        if job.stages['edit_structure']['status'] != 'approved' or len(arroll) != 1:
            raise GenerationQueueError('follow-up needs the approved speech clock')
        visual._exact(root, arroll[0])
        expected = {'aroll_sha256': arroll[0]['sha256'], 'segment_id': step['segment_id'],
                    'start': segment['start'], 'end': segment['end']}
        frames = round((segment['end'] - segment['start']) * 24)
        if (brief.get('source_binding') != expected or brief.get('upstream_route') != 'paper-collage-ad/hyperframes'
                or brief.get('composition') != {'width': 1080, 'height': 1920, 'fps': 24, 'frames': frames, 'alpha': False}):
            raise GenerationQueueError('follow-up sample differs from the approved row or clock')
        from . import segment_render
        if not segment_render._probe_matches(segment_render._default_probe(paths['preview']), frames):
            raise GenerationQueueError('follow-up preview is not the actual approved-clock video')
        if original['sha256'] not in visual._paper_crop_sources(root, brief, proof['crop_provenance'], [original]):
            raise GenerationQueueError('follow-up sample does not consume the approved image')
        expected_media = {x['media_ref']: x for x in [brief['entry'], *brief['assets']]}
        rows = manifest.get('media')
        if (manifest.get('schema_version') != 'reference-process-media/v1'
                or manifest.get('brief_sha256') != proof['brief']['sha256'] or not isinstance(rows, list)
                or len(rows) != len(expected_media) or {x.get('media_ref') for x in rows} != set(expected_media)):
            raise GenerationQueueError('follow-up sample input manifest differs from its brief')
        for row in rows:
            source = expected_media[row['media_ref']]
            actual = visual._record(root, visual._path(root, source['job_path']))
            if (row.get('sha256'), row.get('byte_length')) != (actual['sha256'], actual['bytes']) or actual['sha256'] != source['sha256']:
                raise GenerationQueueError('follow-up sample input changed')
        if (render.get('exit_code') != 0 or render.get('external_requests') != 0
                or render.get('upstream_route') != brief['upstream_route'] or render.get('frames') != frames
                or render.get('output_sha256') != proof['preview']['sha256']
                or review.get('status') != 'needs_revision' or review.get('preview') != proof['preview']
                or plan['issue'] not in review.get('observations', [])
                or not isinstance(review.get('method'), str) or not review['method'].strip()
                or not isinstance(review.get('inspected_times_seconds'), list) or not review['inspected_times_seconds']
                or any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t < frames / 24
                       for t in review['inspected_times_seconds'])):
            raise GenerationQueueError('follow-up sample or human observation does not match')
    except (KeyError, TypeError, OSError, StopIteration) as exc:
        raise GenerationQueueError('follow-up sample evidence is invalid') from exc


def edit_completed_image(job, plan, user_confirmation, expected_plan_sha256):
    """Register one explicitly approved edit of an unusable completed visual image."""
    if (not isinstance(plan, dict) or set(plan) not in ({"from_id", "request", "issue", "count"},
                                                       {"from_id", "request", "issue", "count", "followup_evidence"})
            or not isinstance(plan["from_id"], str) or not plan["from_id"]
            or not isinstance(plan["issue"], str) or not plan["issue"].strip()
            or type(plan["count"]) is not int or plan["count"] != 1
            or not isinstance(user_confirmation, str) or not user_confirmation.strip()
            or artifacts.sha256_json(plan) != expected_plan_sha256):
        raise GenerationQueueError("image edit needs one exact plan, observed issue and explicit permission")
    _json_safe(plan)
    snapshot = status(job)
    parent = snapshot["items"].get(plan["from_id"])
    if not parent or parent.get("status") != "completed" or parent["request"]["purpose"] != "image":
        raise GenerationQueueError("image edit requires a completed visual image")
    if 'followup_evidence' not in plan and parent.get("completion_response", {}).get("conclusion") != plan["issue"]:
        raise GenerationQueueError("image edit issue must match the original recorded visual review")
    from . import visual_confirmation
    actual_job = state.load_job(Path(job))
    approved = visual_confirmation.validate_generation_request(actual_job, parent.get("authorization", {}), parent["request"])
    with _locked(job) as (j, path, q):
        if q["items"].get(plan["from_id"]) != parent:
            raise GenerationQueueError("original image changed before edit registration")
        if 'followup_evidence' in plan:
            _validate_followup_image_evidence(actual_job, parent, plan, approved)
        existing = [(rid, item) for rid, item in q["items"].items() if item.get("retry_of") == plan["from_id"]]
        if existing:
            rid, item = existing[0]
            if (len(existing) != 1 or item.get("image_edit_plan") != plan
                    or item.get("user_confirmation") != user_confirmation):
                raise GenerationQueueError("original image already has a different successor")
            return {"id": rid, "plan_request_id": item["plan_request_id"], "idempotent": True}
        jid, digest, config = _approved(j)
        if jid != q["job_id"] or digest != parent["config_sha256"]:
            raise GenerationQueueError("image edit configuration changed")
        outputs = parent.get("completion_response", {}).get("artifacts", [])
        if len(outputs) != 1 or outputs[0].get("type") != "image":
            raise GenerationQueueError("image edit requires exactly one original image")
        output = outputs[0]
        source = Path(output["path"])
        if not source.is_absolute(): source = j / source
        try:
            relative = source.relative_to(j).as_posix()
        except ValueError as exc:
            raise GenerationQueueError("original image must belong to this Job") from exc
        ref = {"path": relative, "sha256": output["sha256"], "bytes": output["bytes"]}
        request = plan["request"]
        if (not isinstance(request, dict) or request.get("purpose") != "image"
                or request.get("tool") != parent["request"]["tool"]
                or request.get("input_files") != [ref]
                or request.get("arguments", {}).get("referenced_image_paths") != [str(source)]):
            raise GenerationQueueError("image edit must use the exact original image and approved channel")
        identity = _request(j, request, config)
        if identity != parent["channel_identity"]:
            raise GenerationQueueError("image edit channel identity changed")
        rid, fingerprint = request["id"], _fingerprint(request)
        if rid in q["items"] or any(x["fingerprint"] == fingerprint for x in q["items"].values()):
            raise GenerationQueueError("image edit request is already registered")
        root_id = parent.get("plan_request_id", plan["from_id"])
        q["items"][rid] = {"request": request, "fingerprint": fingerprint, "status": "ready",
                           "retry_of": plan["from_id"], "plan_request_id": root_id,
                           "image_edit_plan": plan, "channel_identity": identity,
                           "config_sha256": digest, "approved_plan_sha256": expected_plan_sha256,
                           "user_confirmation": user_confirmation}
        artifacts.write_json_artifact(path, q)
        return {"id": rid, "plan_request_id": root_id, "idempotent": False}


def claim(job, request_id, account_limit=None):
    with _locked(job) as (j, path, q):
        item = q["items"].get(request_id)
        if item is None:
            raise GenerationQueueError("unknown request")
        if item["status"] != "ready":
            return {"action": "blocked", "status": item["status"], "id": request_id}
        jid, digest, config = _approved(j)
        if jid != q["job_id"] or item["config_sha256"] != digest:
            raise GenerationQueueError("configuration changed; obtain approval before new submissions")
        identity = _request(j, item["request"], config)
        if identity != item.get("channel_identity"):
            raise GenerationQueueError("generation channel identity changed; obtain approval before new submissions")
        edit_plan = item.get('image_edit_plan')
        if isinstance(edit_plan, dict) and 'followup_evidence' in edit_plan:
            parent = q['items'].get(item.get('retry_of'))
            if (not parent or parent.get('status') != 'completed'
                    or edit_plan.get('from_id') != item.get('retry_of')
                    or edit_plan.get('request') != item['request']
                    or artifacts.sha256_json(edit_plan) != item.get('approved_plan_sha256')
                    or not isinstance(item.get('user_confirmation'), str) or not item['user_confirmation'].strip()):
                raise GenerationQueueError('follow-up edit authorization changed')
            from . import visual_confirmation
            actual_job = state.load_job(j)
            approved = visual_confirmation.validate_generation_request(actual_job, parent['authorization'], parent['request'], queue=q)
            _validate_followup_image_evidence(actual_job, parent, edit_plan, approved)
        active = [x for x in q["items"].values() if x["status"] in ACTIVE]
        if q["paused"] or len(active) >= config["max_concurrency"]:
            return {"action": "wait", "id": request_id}
        if item["request"]["purpose"] == "video" and item["request"]["tool"] == "mcp__lovart__generate_video":
            if type(account_limit) is not int or account_limit < 1:
                raise GenerationQueueError("read the selected video channel quota before claiming generation")
            if sum(x["request"]["purpose"] == "video" for x in active) >= account_limit:
                return {"action": "wait", "id": request_id}
        from . import generation_inputs
        submitted_request = generation_inputs.resolve_request(j, item["request"])
        if not isinstance(submitted_request, dict) or submitted_request.get("tool") != item["request"]["tool"]:
            raise GenerationQueueError("resolved generation request is invalid")
        token = secrets.token_urlsafe(24)
        item.update(status="submitting", claim_token=token, claimed_at=time.time(),
                    submitted_request=submitted_request)
        q["max_concurrency"] = config["max_concurrency"]
        artifacts.write_json_artifact(path, q)
        return {"action": "generate", "id": request_id, "plan_request_id": item.get("plan_request_id", request_id),
                "claim_token": token,
                "tool": submitted_request["tool"], "arguments": submitted_request["arguments"]}


def record(job, request_id, claim_token, response, queried_task_ids=None):
    _json_safe(response)
    if not isinstance(response, dict):
        raise GenerationQueueError("record the actual tool response")
    payload = response.get("structuredContent", response)
    if not isinstance(payload, dict):
        raise GenerationQueueError("tool response needs structured data")
    with _locked(job) as (_, path, q):
        item = q["items"].get(request_id)
        if item is None or item.get("claim_token") != claim_token:
            raise GenerationQueueError("claim token mismatch")
        digest = artifacts.sha256_json(payload)
        if digest == item.get("response_sha256"):
            return {"id": request_id, "status": item["status"], "idempotent": True}
        if item["status"] in TERMINAL:
            raise GenerationQueueError("conflicting terminal response")
        query_ids = queried_task_ids or []
        if (not isinstance(query_ids, list) or len(set(query_ids)) != len(query_ids)
                or any(not isinstance(v, str) or not v for v in query_ids)):
            raise GenerationQueueError("invalid queried task ids")
        if item.get("task_ids") and set(query_ids) != set(item["task_ids"]):
            raise GenerationQueueError("query result must identify this request's exact task ids")
        result_status = payload.get("status", "unknown")
        if result_status not in {"pending", "unknown", "not_found"} | TERMINAL:
            result_status = "unknown"
        project = item["request"]["arguments"].get("project_id")
        if payload.get("project_id", project) != project:
            raise GenerationQueueError("response project differs from request")
        ids = payload.get("task_ids", []) or []
        if not isinstance(ids, list) or any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
            raise GenerationQueueError("invalid task ids")
        if item.get("task_ids") and ids and set(ids) != set(item["task_ids"]):
            raise GenerationQueueError("task identity changed")
        if query_ids and not item.get("task_ids") and set(ids) != set(query_ids):
            raise GenerationQueueError("recovered query must identify its actual task ids")
        if any(set(ids).intersection(other.get("task_ids", [])) for rid, other in q["items"].items() if rid != request_id):
            raise GenerationQueueError("task ids already belong to a different request")
        if item["request"]["purpose"] == "image" and ids and item["request"]["tool"] == "image_gen.imagegen":
            raise GenerationQueueError("selected synchronous image channel does not use task queries")
        media = payload.get("artifacts")
        if result_status == "completed":
            if (not isinstance(media, list) or not media
                    or any(not isinstance(a, dict) or a.get("type") != item["request"]["purpose"]
                           or not (a.get("url") or a.get("path")) for a in media)):
                raise GenerationQueueError("completion requires actual media references")
        if result_status == "pending" and not ids:
            result_status = "unknown"
        if result_status == "not_found" or (result_status == "failed"
                and (len(item.get("task_ids") or ids) > 1 or media)):
            result_status = "unknown"
        delay = payload.get("poll_after_seconds", 30)
        if type(delay) not in {int, float} or not math.isfinite(delay) or delay <= 0:
            raise GenerationQueueError("invalid polling delay")
        item.setdefault("submission_response", payload)
        if result_status == "completed":
            item["completion_response"] = payload
        source = {"kind": "query", "task_ids": sorted(query_ids)} if query_ids else {"kind": "submission"}
        item.update(status=result_status, response=payload, response_sha256=digest, response_source=source,
                    recorded_at=time.time(), poll_after_seconds=delay,
                    next_poll_at=time.time() + delay)
        if ids:
            item["task_ids"] = ids
        error = payload.get("error") or {}
        if error.get("code") == "CONCURRENCY_LIMIT":
            q["paused"] = True
        artifacts.write_json_artifact(path, q)
        return {"id": request_id, "status": result_status, "idempotent": False}


def status(job):
    with _locked(job) as (_, _, q):
        return q


def resume(job, user_confirmation):
    """Capture explicit permission to resume ready calls, never retry failed ones."""
    if not isinstance(user_confirmation, str) or not user_confirmation.strip():
        raise GenerationQueueError("resuming after a rate limit requires explicit permission")
    with _locked(job) as (j, path, q):
        jid, _, _ = _approved(j)
        if jid != q["job_id"]:
            raise GenerationQueueError("queue belongs to another Job")
        q.update(paused=False, resume_confirmation=user_confirmation)
        artifacts.write_json_artifact(path, q)
        return {"paused": False}


def poll(job, now=None):
    now = time.time() if now is None else now
    with _locked(job) as (j, path, q):
        from . import generation_channels
        from types import SimpleNamespace
        groups = {}
        for rid, item in q["items"].items():
            if (item["status"] in {"pending", "unknown"} and item.get("task_ids")
                    and item.get("response", {}).get("status") not in {"not_found", "failed"}
                    and item["next_poll_at"] <= now):
                project = item["request"]["arguments"].get("project_id")
                query = generation_channels._query_binding(SimpleNamespace(job_dir=j), item)
                if not query:
                    raise GenerationQueueError("pending generation requires its confirmed query tool")
                key = artifacts.sha256_json(query)
                group = groups.setdefault(key, {"project_id": project, "tool": query["tool"],
                    "arguments": query.get("arguments", {}), "task_ids_parameter": query.get("task_ids_parameter", "task_ids"),
                    "task_ids": [], "requests": {}})
                group["task_ids"].extend(item["task_ids"])
                group["requests"][rid] = {"claim_token": item["claim_token"], "task_ids": item["task_ids"]}
                item["next_poll_at"] = now + item["poll_after_seconds"]
        if groups:
            artifacts.write_json_artifact(path, q)
        return {"action": "query" if groups else "wait", "groups": list(groups.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("add")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--user-confirmation", required=True)
    p.add_argument("--expected-plan-sha256", required=True)
    p = commands.add_parser("prepare-retry")
    p.add_argument("--id", required=True)
    p = commands.add_parser("retry")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--user-confirmation", required=True)
    p.add_argument("--expected-plan-sha256", required=True)
    p = commands.add_parser("claim")
    p.add_argument("--id", required=True)
    p.add_argument("--account-limit", type=int)
    p = commands.add_parser("record")
    p.add_argument("--id", required=True)
    p.add_argument("--claim-token", required=True)
    p.add_argument("--response", type=Path, required=True)
    p.add_argument("--queried-task-id", action="append", default=[])
    commands.add_parser("poll")
    commands.add_parser("status")
    p = commands.add_parser("resume")
    p.add_argument("--user-confirmation", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            out = add(args.job, artifacts.read_json_artifact(args.plan), args.user_confirmation, args.expected_plan_sha256)
        elif args.command == "prepare-retry":
            out = prepare_retry(args.job, args.id)
        elif args.command == "retry":
            out = retry(args.job, artifacts.read_json_artifact(args.plan), args.user_confirmation, args.expected_plan_sha256)
        elif args.command == "claim":
            out = claim(args.job, args.id, args.account_limit)
        elif args.command == "record":
            out = record(args.job, args.id, args.claim_token, artifacts.read_json_artifact(args.response), args.queried_task_id)
        elif args.command == "poll":
            out = poll(args.job)
        elif args.command == "resume":
            out = resume(args.job, args.user_confirmation)
        else:
            out = status(args.job)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except (GenerationQueueError, state.WorkflowError, artifacts.ContractArtifactError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"generation queue stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

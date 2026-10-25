"""Consume a completed host image/video generation record.

The provider call is owned by the host.  This module only freezes the returned
record, checks the referenced bytes and exposes the normal component adapter.
"""
from __future__ import annotations

import hashlib, json, math, os, re, shutil, subprocess
from contextlib import contextmanager
from pathlib import Path
from edit.hd.tools.broll_component_executor import AdapterResult, KindAdapter, _plain_json

_HEX = re.compile(r"[0-9a-f]{64}\Z")
EXECUTOR = "generated_media"

def _validate_observation_and_source(record: dict) -> None:
    brief = record.get("semantic_brief")
    observed = brief.get("observed_scene") if isinstance(brief, dict) else None
    if not isinstance(observed, str) or not observed.strip():
        raise ValueError("generated media semantic brief requires observed scene evidence")
    source = record.get("source_binding")
    if not isinstance(source, dict) or set(source) != {"aroll_sha256", "start", "end"}:
        raise ValueError("generated media source binding is invalid")
    if (not isinstance(source["aroll_sha256"], str) or not _HEX.fullmatch(source["aroll_sha256"])
            or isinstance(source["start"], bool) or not isinstance(source["start"], (int, float))
            or isinstance(source["end"], bool) or not isinstance(source["end"], (int, float))
            or not math.isfinite(source["start"]) or not math.isfinite(source["end"])
            or source["start"] < 0 or source["end"] <= source["start"]):
        raise ValueError("generated media source binding clock or A-roll hash is invalid")

def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def validate_record(record: dict, job) -> dict:
    if not isinstance(record, dict) or record.get("schema_version") not in (1, 2):
        raise ValueError("generated media record schema is invalid")
    if record.get("status") != "completed" or record.get("job_id") != job.job_id:
        raise ValueError("generated media record is not a completed record for this Job")
    for key in ("segment_id", "component_id", "provider", "model", "endpoint_id", "generation_id", "prompt_sha256"):
        if not isinstance(record.get(key), str) or not record[key]: raise ValueError(f"generated media record missing {key}")
    if not _HEX.fullmatch(record["prompt_sha256"]): raise ValueError("generated media prompt hash is invalid")
    media = record.get("media")
    if not isinstance(media, dict) or set(media) != {"job_path", "sha256", "byte_count", "media_type"}:
        raise ValueError("generated media evidence is invalid")
    path = str(media["job_path"])
    if not path or path.startswith("/") or "\\" in path or any(p in {"", ".", ".."} for p in path.split("/")):
        raise ValueError("generated media path must be Job-relative")
    if not _HEX.fullmatch(str(media["sha256"])) or not isinstance(media["byte_count"], int) or media["byte_count"] <= 0:
        raise ValueError("generated media identity is invalid")
    if media["media_type"] not in {"image", "video"}: raise ValueError("generated media type is invalid")
    for key in ("generation", "qa", "semantic_brief"):
        if not isinstance(record.get(key), dict): raise ValueError(f"generated media {key} evidence is missing")
    if record["qa"].get("passed") is not True or not record["qa"].get("observed_scene"):
        raise ValueError("generated media requires host QA and observed scene evidence")
    _validate_observation_and_source(record)
    return json.loads(_canonical(record))

def record_from_completed_output(*, job_id, segment_id, component_id, provider, model,
                                 endpoint_id, generation_id, prompt_sha256, media,
                                 generation, qa, semantic_brief):
    """Normalize one queue completion; requires observed host QA, never fabricates it."""
    if not isinstance(qa, dict) or qa.get("passed") is not True or not qa.get("observed_scene"):
        raise ValueError("queue completion must include passed host QA and observed_scene")
    return {"schema_version": 1, "status": "completed", "job_id": job_id,
            "segment_id": segment_id, "component_id": component_id,
            "provider": provider, "model": model, "endpoint_id": endpoint_id,
            "generation_id": generation_id, "prompt_sha256": prompt_sha256,
            "media": media, "generation": generation, "qa": qa,
            "semantic_brief": semantic_brief}

def record_from_queue(job, request_id, *, segment_id, component_id, source_binding,
                      qa, semantic_brief, ffprobe_executable, output_index=0):
    """Bind the actual queue output and observed content to one speech window."""
    from edit.hd.tools import generation_queue, generation_inputs, contract_artifacts as artifacts
    item = generation_queue.status(job.job_dir)["items"][request_id]
    if item["status"] != "completed":
        raise ValueError("generation has not completed")
    original_id = item.get("plan_request_id", request_id)
    original = generation_queue.status(job.job_dir)["items"][original_id]
    authorization = original.get("authorization")
    if authorization:
        from edit.hd.tools import visual_confirmation
        checked = visual_confirmation.validate_generation_request(job, authorization, original["request"])
        if (checked["step"]["segment_id"], checked["step"]["component_id"]) != (segment_id, component_id):
            raise ValueError("completed generation belongs to another approved visual row")
    output = item["completion_response"]["artifacts"][output_index]
    path = Path(output["path"])
    if not path.is_absolute():
        path = job.job_dir / path
    if output["type"] == "image":
        from PIL import Image
        with Image.open(path) as picture:
            width, height = picture.size
    else:
        result = subprocess.run([str(ffprobe_executable), "-v", "error", "-show_streams", "-of", "json", str(path)],
                                capture_output=True, text=True, check=True, timeout=30)
        streams = json.loads(result.stdout)["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        if video["codec_name"] != "h264" or video["pix_fmt"] != "yuv420p" or video["r_frame_rate"] not in {"24/1", "48/2"} or any(s["codec_type"] == "audio" for s in streams):
            raise ValueError("prepare actual silent H264/yuv420p 24fps media before binding")
        width, height = video["width"], video["height"]
    identity = item.get("channel_identity")
    if not isinstance(identity, dict):
        raise ValueError("completed generation has no frozen channel identity")
    record = record_from_completed_output(job_id=job.job_id, segment_id=segment_id, component_id=component_id,
        provider=identity["provider"], model=identity["model"], endpoint_id=identity["endpoint_id"],
        generation_id=request_id, prompt_sha256=artifacts.sha256_json(
            item["submitted_request"]["arguments"]),
        media={"job_path": path.relative_to(job.job_dir).as_posix(), "sha256": _sha(path),
               "byte_count": path.stat().st_size, "media_type": output["type"]},
        generation={"approved_plan": item.get("authorization") or item.get("approved_plan_sha256"),
                    "request_id": request_id, "task_ids": item.get("task_ids", []),
                    "channel_identity": identity,
                    "input_bindings": generation_inputs.evidence(job.job_dir, item["request"]),
                    **({"source_media": output["source"], "processing": output["processing"]}
                       if output.get("source") else {}),
                    "submitted_request": item["submitted_request"]},
        qa=qa, semantic_brief=semantic_brief)
    record["source_binding"] = source_binding
    record["source_dimensions"] = {"width": width, "height": height}
    prepare_binding(record)
    return validate_record(record, job)

def prepare_binding(record: dict, *, execution_mode="reuse_completed_generated_media") -> dict:
    if not isinstance(record, dict) or record.get("status") != "completed":
        raise ValueError("generated media binding requires a completed record")
    _validate_observation_and_source(record)
    media = record.get("media")
    if not isinstance(media, dict) or not media.get("sha256") or media.get("media_type") not in {"image", "video"}:
        raise ValueError("generated media binding requires real media identity")
    dimensions = record.get("source_dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != {"width", "height"} or (dimensions["width"], dimensions["height"]) not in {(720, 1280), (1080, 1920)}:
        raise ValueError("generated media needs its actual supported portrait dimensions")
    return {"execution_mode": execution_mode, "provider": record["provider"], "model": record["model"],
            "endpoint_id": record["endpoint_id"], "generation_id": record["generation_id"],
            "prompt_sha256": record["prompt_sha256"], "sha256": record["media"]["sha256"],
            "source_dimensions": dimensions}

def create_job_adapter(job, records):
    """Build a dispatcher from explicit completed_record descriptors.

    ``records`` may be a mapping keyed by (segment_id, component_id), or a
    sequence of full records. No Job-folder scanning is performed.
    """
    if isinstance(records, dict):
        values = list(records.values())
    elif isinstance(records, (list, tuple)):
        values = list(records)
    else:
        raise ValueError("generated media records must be an explicit list or mapping")
    adapters = {}
    for record in values:
        checked = validate_record(record, job)
        key = (checked["segment_id"], checked["component_id"])
        if key in adapters: raise ValueError("duplicate generated media target")
        adapters[key] = create_adapter(job, checked)
    return adapters

def load_semantic_brief(record: dict) -> dict:
    return json.loads(_canonical(record["semantic_brief"]))

@contextmanager
def _pinned_media(source, media):
    from edit.hd.tools import transcribe
    try:
        pinned = transcribe._pin_local_media(source, expected_sha256=media['sha256'],
                                            expected_bytes=media['byte_count'])
        try:
            yield pinned
            transcribe._verify_pinned(pinned)
        finally:
            if not transcribe._close_descriptor(pinned.descriptor):
                raise ValueError('generated media descriptor cleanup failed')
    except (OSError, transcribe.TranscriptionError) as error:
        raise ValueError('generated media path or bytes do not match the completion record') from error

def create_adapter(job, record: dict):
    bound = validate_record(record, job)
    media = bound["media"]
    source = Path(job.job_dir) / media["job_path"]
    with _pinned_media(source, media):
        pass
    record_hash = hashlib.sha256(_canonical(bound)).hexdigest()
    expected = prepare_binding(bound)
    def invoke(context):
        if (context.job_id, context.segment_id, context.component_id) != (job.job_id, bound["segment_id"], bound["component_id"]):
            raise ValueError("generated media target binding mismatch")
        if context.component.get("kind") != "ai_generated" or any(
                context.component.get(key) != value for key, value in expected.items()
                if key not in {"execution_mode", "media_type", "source_dimensions"}):
            raise ValueError("generated media generation identity mismatch")
        from edit.hd.tools import visual_canary
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(item for item in plan['segments'] if item['segment_id'] == context.segment_id)
        arroll = visual_canary.approved_aroll_record(job, plan)
        if (bound['source_binding'] != {'aroll_sha256': arroll['sha256'],
                'start': segment['start'], 'end': segment['end']}
                or _plain_json(context.recipe) != segment['shot_recipe']):
            raise ValueError('generated media approved source window mismatch')
        with _pinned_media(source, media) as pinned:
            with os.fdopen(os.dup(pinned.descriptor), 'rb') as src, context.staging_path.open('wb') as dst:
                shutil.copyfileobj(src, dst)
        return AdapterResult(invocation_evidence={"record_sha256": record_hash, "provider_request_reused": True,
            "external_requests": 0, "generation_id": bound["generation_id"], "provider": bound["provider"]},
            qa={"passed": True, "checks": ["completed generation record and media identity matched"]})
    return KindAdapter(kind="ai_generated", approved_executor=EXECUTOR, adapter_id="generated-media-v1",
        adapter_version=record_hash, artifact_media_type=media["media_type"], invoke=invoke,
        provider=bound["provider"], model=bound["model"], endpoint_id=bound["endpoint_id"])

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

def _queue_media(job, request_id, output_index=0):
    from edit.hd.tools import generation_queue
    item = generation_queue.status(job.job_dir)["items"][request_id]
    if item.get("status") != "completed":
        raise ValueError("composition base requires a completed generation")
    output = item["completion_response"]["artifacts"][output_index]
    path = Path(output["path"])
    if not path.is_absolute():
        path = job.job_dir / path
    if path.resolve() != path.absolute() or not path.is_relative_to(job.job_dir):
        raise ValueError("composition base must be the original Job-local output")
    media = {"job_path": path.relative_to(job.job_dir).as_posix(), "sha256": output["sha256"],
             "byte_count": output["bytes"], "media_type": output["type"]}
    if media["media_type"] != "video":
        raise ValueError("composition base normalization accepts video only")
    with _pinned_media(path, media):
        pass
    return media

def _validate_base_queue_identity(job, record):
    from edit.hd.tools import generation_queue, contract_artifacts as artifacts
    generation = record['generation']
    queue = generation_queue.status(job.job_dir)['items']
    item = queue[generation['request_id']]
    original_id = item.get('plan_request_id', generation['request_id'])
    original = queue[original_id]
    expected = {'request_id': record['generation_id'], 'task_ids': item.get('task_ids', []),
                'channel_identity': item['channel_identity'], 'submitted_request': item['submitted_request']}
    if original.get('authorization'):
        expected.update(approved_plan=original['authorization'], approved_request_id=original_id,
                        approved_request=original['request'])
    if (any(generation.get(key) != value for key, value in expected.items())
            or any(record[key] != item['channel_identity'][key] for key in ('provider', 'model', 'endpoint_id'))
            or record['prompt_sha256'] != artifacts.sha256_json(item['submitted_request']['arguments'])):
        raise ValueError('composition base generation identity differs from the completed queue')

def _base_probe(path, ffprobe):
    from lovart_existing_video_adapter import _metadata_probe
    inherited = (int(path.name),) if path.parent == Path('/dev/fd') else ()
    result = subprocess.run([str(ffprobe), '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                            pass_fds=inherited, capture_output=True, text=True, check=True, timeout=30)
    streams = json.loads(result.stdout)['streams']
    if len(streams) != 1 or streams[0].get('codec_type') != 'video':
        raise ValueError('composition base needs one silent video stream')
    stream = streams[0]
    if stream.get('sample_aspect_ratio') not in (None, '1:1'):
        raise ValueError('composition base cannot repair a non-square SAR')
    # The existing probe also checks codec, both frame rates, rotation and MP4.
    probe = _metadata_probe(ffprobe, path, {'width': stream['width'], 'height': stream['height'],
                                          'sar': stream.get('sample_aspect_ratio')})
    if abs(probe['duration'] - probe['frames'] / 24) > 1e-6:
        raise ValueError('composition base frame clock differs')
    return json.loads(_canonical(probe))

def _base_pixels(path, ffmpeg, crop=None):
    command = [str(ffmpeg), '-v', 'error', '-i', str(path), '-map', '0:v:0']
    if crop is not None:
        command += ['-vf', 'crop=' + ':'.join(str(v) for v in crop)]
    command += ['-f', 'framemd5', '-']
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
    rows = [line.strip() for line in result.stdout.splitlines() if line and not line.startswith('#')]
    if not rows:
        raise ValueError('composition base has no decoded pixels')
    return rows

def _base_transform(probe):
    width, height = probe['width'], probe['height']
    for target_width, target_height in ((720, 1280), (1080, 1920)):
        dx, dy = target_width - width, target_height - height
        if (min(dx, dy) < 0 or width % 2 or height % 2
                or dx / target_width + dy / target_height > .005):
            continue
        left, top = dx // 4 * 2, dy // 4 * 2
        padding = {'left': left, 'right': dx - left, 'top': top, 'bottom': dy - top}
        if max(padding.values()) <= 4:
            return {'width': target_width, 'height': target_height, 'padding': padding,
                    'codec': 'libx264' if dx or dy else 'copy', 'sar': '1:1'}
    raise ValueError('composition base exceeds the approved tiny portrait rounding allowance')

def _base_normalization_command(source, output, transform, ffmpeg):
    command = [str(ffmpeg), '-hide_banner', '-nostdin', '-v', 'error',
               '-i', str(source), '-map', '0:v:0', '-an']
    pad = transform['padding']
    if transform['codec'] == 'copy':
        command += ['-c:v', 'copy', '-bsf:v', 'h264_metadata=sample_aspect_ratio=1/1']
    else:
        graph = (f"pad={transform['width']}:{transform['height']}:{pad['left']}:{pad['top']},"
                 f"fillborders=left={pad['left']}:right={pad['right']}:top={pad['top']}:bottom={pad['bottom']}:mode=smear,setsar=1")
        command += ['-vf', graph, '-c:v', 'libx264', '-qp', '0', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough']
    return command + ['-video_track_timescale', '24', '-n', str(output)]

def _verify_base_normalization(job, normalization, ffprobe, ffmpeg):
    required = {'schema_version', 'source', 'output', 'source_probe', 'output_probe',
                'transform', 'frame_md5_sha256', 'command'}
    if (not isinstance(normalization, dict) or set(normalization) != required
            or normalization['schema_version'] != 1):
        raise ValueError('composition base normalization evidence is invalid')
    source, output = normalization['source'], normalization['output']
    for media in (source, output):
        if (not isinstance(media, dict) or set(media) != {'job_path', 'sha256', 'byte_count', 'media_type'}
                or media.get('media_type') != 'video'):
            raise ValueError('composition base normalization media evidence is invalid')
        path = Path(job.job_dir) / media['job_path']
        if path.resolve() != path.absolute() or not path.is_relative_to(job.job_dir):
            raise ValueError('composition base normalization path is outside Job')
        with _pinned_media(path, media):
            pass
    source_path, output_path = (Path(job.job_dir) / media['job_path'] for media in (source, output))
    before, after = _base_probe(source_path, ffprobe), _base_probe(output_path, ffprobe)
    transform = _base_transform(before)
    command = normalization['command']
    if (before != normalization['source_probe'] or after != normalization['output_probe']
            or transform != normalization['transform'] or after['sar'] != '1:1'
            or not isinstance(command, list) or not command
            or command[1:] != _base_normalization_command(source_path, output_path, transform, ffmpeg)[1:]
            or (after['width'], after['height']) != (transform['width'], transform['height'])
            or any(before[key] != after[key] for key in ('fps', 'frames', 'duration', 'color'))):
        raise ValueError('composition base normalization changed geometry, color or frame clock')
    pad = transform['padding']
    crop = [before['width'], before['height'], pad['left'], pad['top']]
    rows = _base_pixels(source_path, ffmpeg)
    if (rows != _base_pixels(output_path, ffmpeg, crop)
            or hashlib.sha256('\n'.join(rows).encode()).hexdigest() != normalization['frame_md5_sha256']):
        raise ValueError('composition base normalization changed original pixels or timestamps')
    # Check the padding pixels too, by reproducing only the approved transform.
    if any(pad.values()):
        graph = (f"pad={transform['width']}:{transform['height']}:{pad['left']}:{pad['top']},"
                 f"fillborders=left={pad['left']}:right={pad['right']}:top={pad['top']}:bottom={pad['bottom']}:mode=smear,setsar=1")
        result = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(source_path),
                                 '-vf', graph, '-f', 'framemd5', '-'],
                                capture_output=True, text=True, check=True, timeout=60)
        expected = [line.strip() for line in result.stdout.splitlines() if line and not line.startswith('#')]
        if expected != _base_pixels(output_path, ffmpeg):
            raise ValueError('composition base padding is not the original nearest edge pixels')
    for media in (source, output):
        with _pinned_media(Path(job.job_dir) / media['job_path'], media):
            pass

def normalize_composition_base(job, request_id, *, output_path, ffprobe_executable,
                               ffmpeg_executable, output_index=0):
    """Create a lossless, separately recorded format derivative; never touch the queue."""
    source = _queue_media(job, request_id, output_index)
    source_path = Path(job.job_dir) / source['job_path']
    output = Path(output_path)
    if not output.is_absolute():
        output = Path(job.job_dir) / output
    if (output.resolve() != output.absolute() or not output.is_relative_to(job.job_dir)
            or output.exists() or output.suffix != '.mp4'):
        raise ValueError('composition base normalization requires a new Job-local MP4')
    before = _base_probe(source_path, ffprobe_executable)
    transform = _base_transform(before)
    if transform['codec'] == 'copy' and before['sar'] == '1:1':
        raise ValueError('composition base already meets the native contract; use the original')
    output.parent.mkdir(parents=True, exist_ok=True)
    command = _base_normalization_command(source_path, output, transform, ffmpeg_executable)
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    evidence = {'schema_version': 1, 'source': source,
                'output': {'job_path': output.relative_to(job.job_dir).as_posix(),
                           'sha256': _sha(output), 'byte_count': output.stat().st_size, 'media_type': 'video'},
                'source_probe': before, 'output_probe': _base_probe(output, ffprobe_executable),
                'transform': transform, 'command': command,
                'frame_md5_sha256': hashlib.sha256('\n'.join(_base_pixels(source_path, ffmpeg_executable)).encode()).hexdigest()}
    _verify_base_normalization(job, evidence, ffprobe_executable, ffmpeg_executable)
    return evidence

def _composition_base_scope(record):
    scope = record.get('composition_base')
    if scope is None:
        if record.get('qa', {}).get('scope') == 'composition_base' or 'normalization' in record:
            raise ValueError('composition base scope is missing')
        return
    if (not isinstance(scope, dict) or set(scope) != {'source_qa', 'action_component_id'}
            or not isinstance(scope['action_component_id'], str) or not scope['action_component_id'].strip()
            or scope['action_component_id'] == record['component_id']
            or not isinstance(scope['source_qa'], dict) or scope['source_qa'].get('passed') is not False
            or not isinstance(scope['source_qa'].get('observed_scene'), str)
            or not scope['source_qa']['observed_scene'].strip()
            or record.get('qa', {}).get('scope') != 'composition_base'
            or record['media']['media_type'] != 'video'):
        raise ValueError('composition base requires explicit failed original-effect QA and separate base QA')

def validate_composition_base(record, recipe):
    """A limited-use base cannot be consumed as a standalone successful effect."""
    _composition_base_scope(record)
    if 'composition_base' not in record:
        return
    from edit.hd.tools import visual_strategy
    recipe = visual_strategy.validate_shot_recipe_v2(_plain_json(recipe))
    by_id = {c['component_id']: c for c in recipe['components']}
    base = by_id.get(record['component_id'], {})
    action_id = record['composition_base']['action_component_id']
    action = by_id.get(action_id, {})
    if (recipe['mode'] != 'hybrid' or recipe['composition']['family'] != 'evidence_with_data_overlay'
            or base.get('kind') != 'ai_generated' or base.get('layer_role') != 'base'
            or base.get('semantic_role') == 'evidence' or action.get('kind') != 'code_generated'
            or action.get('layer_role') != 'annotation' or action.get('semantic_role') == 'evidence'
            or action.get('producer_type') != 'dependency' or action.get('artifact_contract', {}).get('alpha') is not True
            or not any(d['component_id'] == action_id and record['component_id'] in d['depends_on']
                       for d in recipe['composition']['component_dependencies'])):
        raise ValueError('composition base requires an approved non-evidence hybrid with its independent native alpha action')

def _approved_generation_request(job, generation, record):
    """Re-check a queue result against its frozen visual proposal when present."""
    authorization = generation.get("approved_plan")
    request = generation.get("approved_request")
    if authorization is None and request is None:
        return
    if not isinstance(authorization, dict) or not isinstance(request, dict):
        raise ValueError("generated media approved request evidence is incomplete")
    from edit.hd.tools import broll_skill_selection, generation_channels, contract_artifacts
    identity = broll_skill_selection.approved_creative_identity(job, generation,
        segment_id=record["segment_id"], component_id=record["component_id"])
    provider = generation_channels.selected_channel(job, request["purpose"])
    if any(record.get(k) != provider[k] for k in ("provider", "model", "endpoint_id")):
        raise ValueError("completed generation provider differs from its approved service")
    submitted = generation.get("submitted_request")
    if (not isinstance(submitted, dict)
            or record["prompt_sha256"] != contract_artifacts.sha256_json(submitted.get("arguments"))):
        raise ValueError("completed generation prompt differs from its submitted request")
    return identity

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
    approved_request_id = record["generation"].get("approved_request_id")
    if approved_request_id is not None and (not isinstance(approved_request_id, str) or not approved_request_id):
        raise ValueError("generated media approved request identity is invalid")
    if ("approved_plan" in record["generation"] or "approved_request" in record["generation"]):
        _approved_generation_request(job, record["generation"], record)
    if record["qa"].get("passed") is not True or not record["qa"].get("observed_scene"):
        raise ValueError("generated media requires host QA and observed scene evidence")
    _composition_base_scope(record)
    if 'composition_base' in record:
        generation = record['generation']
        _validate_base_queue_identity(job, record)
        original = _queue_media(job, generation['request_id'], generation.get('output_index', 0))
        normalization = record.get('normalization')
        if normalization is not None:
            if (not isinstance(normalization, dict)
                    or normalization.get('source') != original or normalization.get('output') != record['media']
                    or normalization.get('output_probe', {}).get('sar') != '1:1'
                    or {key: normalization['output_probe'].get(key) for key in ('width', 'height')} != record['source_dimensions']):
                raise ValueError('composition base derivative differs from its original queue media')
        elif record['media'] != original:
            raise ValueError('composition base differs from its original queue media')
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
                      qa, semantic_brief, ffprobe_executable, output_index=0,
                      composition_base=None, normalization=None, ffmpeg_executable=None):
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
    if normalization is not None:
        if composition_base is None or ffmpeg_executable is None:
            raise ValueError('normalization requires scoped composition base use and actual FFmpeg verification')
        if normalization.get('source') != _queue_media(job, request_id, output_index):
            raise ValueError('normalization does not belong to the original queue output')
        _verify_base_normalization(job, normalization, ffprobe_executable, ffmpeg_executable)
        path = Path(job.job_dir) / normalization['output']['job_path']
    elif composition_base is not None:
        measured = _base_probe(path, ffprobe_executable)
        if (measured['width'], measured['height']) not in {(720, 1280), (1080, 1920)} or measured['sar'] != '1:1':
            raise ValueError('composition base requires a separately verified normalization first')
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
        try:
            frames, duration = int(video["nb_frames"]), float(video["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("generated video needs a measured frame count and duration before binding") from exc
        if frames <= 0 or not math.isfinite(duration) or abs(duration - frames / 24) > 1e-6:
            raise ValueError("generated video frame clock differs; stream-copy remux to video_track_timescale=24 before binding")
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
        generation={**({"approved_plan": authorization,
                       "approved_request_id": original_id,
                       "approved_request": original["request"]} if authorization else {}),
                    "request_id": request_id, "task_ids": item.get("task_ids", []),
                    "channel_identity": identity,
                    "input_bindings": generation_inputs.evidence(job.job_dir, item["request"]),
                    **({"source_media": output["source"], "processing": output["processing"]}
                       if output.get("source") else {}),
                    "submitted_request": item["submitted_request"]},
        qa=qa, semantic_brief=semantic_brief)
    record["source_binding"] = source_binding
    record["source_dimensions"] = {"width": width, "height": height}
    if composition_base is not None:
        record['composition_base'] = composition_base
        record['generation']['output_index'] = output_index
        if normalization is not None:
            record['normalization'] = normalization
    prepare_binding(record)
    return validate_record(record, job)

def prepare_binding(record: dict, *, execution_mode="reuse_completed_generated_media") -> dict:
    if not isinstance(record, dict) or record.get("status") != "completed":
        raise ValueError("generated media binding requires a completed record")
    _validate_observation_and_source(record)
    _composition_base_scope(record)
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
    if 'normalization' in bound:
        ffprobe, ffmpeg = shutil.which('ffprobe'), shutil.which('ffmpeg')
        if not ffprobe or not ffmpeg:
            raise ValueError('composition base normalization needs actual FFprobe and FFmpeg')
        _verify_base_normalization(job, bound['normalization'], ffprobe, ffmpeg)
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
        _approved_generation_request(job, bound["generation"], bound)
        segment = next(item for item in plan['segments'] if item['segment_id'] == context.segment_id)
        arroll = visual_canary.approved_aroll_record(job, plan)
        if (bound['source_binding'] != {'aroll_sha256': arroll['sha256'],
                'start': segment['start'], 'end': segment['end']}
                or _plain_json(context.recipe) != segment['shot_recipe']):
            raise ValueError('generated media approved source window mismatch')
        validate_composition_base(bound, context.recipe)
        if 'composition_base' in bound:
            # Recheck the immutable provider output as well as the derivative.
            validate_record(bound, job)
        with _pinned_media(source, media) as pinned:
            with os.fdopen(os.dup(pinned.descriptor), 'rb') as src, context.staging_path.open('wb') as dst:
                shutil.copyfileobj(src, dst)
        return AdapterResult(invocation_evidence={"record_sha256": record_hash, "provider_request_reused": True,
            "external_requests": 0, "generation_id": bound["generation_id"], "provider": bound["provider"],
            **({'composition_base': bound['composition_base'],
                'normalization_sha256': hashlib.sha256(_canonical(bound.get('normalization'))).hexdigest()}
               if 'composition_base' in bound else {})},
            qa={"passed": True, "checks": ["completed generation record and media identity matched"]})
    return KindAdapter(kind="ai_generated", approved_executor=EXECUTOR, adapter_id="generated-media-v1",
        adapter_version=record_hash, artifact_media_type=media["media_type"], invoke=invoke,
        provider=bound["provider"], model=bound["model"], endpoint_id=bound["endpoint_id"])

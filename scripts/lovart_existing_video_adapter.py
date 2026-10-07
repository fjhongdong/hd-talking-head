"""Replay one completed Lovart video through the existing component executor.

No networking or media modification; preparation and probing only inspect bytes.
Safe snapshots intentionally depend on the current project runtime's private
helpers; incompatible runtimes fail closed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path, PurePosixPath

from edit.hd.tools import broll_media, segment_render, visual_canary
from edit.hd.tools.broll_component_executor import AdapterResult, ArtifactProbe, KindAdapter

PROVIDER = "Lovart"
ENDPOINT_ID = "mcp__lovart__generate_video"
EXECUTOR = "lovart_existing_video"
VERSION = "1.6.0"


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _record_copy(record):
    fields = {"schema_version", "job_id", "segment_id", "component_id",
              "source_binding", "media", "generation", "qa"}
    optional = {"derived_media", "normalization_approval"}
    if type(record) is not dict or set(record) not in (fields, fields | optional) or type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("invalid Lovart record")
    for key in ("job_id", "segment_id", "component_id"):
        if type(record[key]) is not str or not record[key]:
            raise ValueError("invalid target identity")
    for key in ("media", "generation", "qa") + tuple(sorted(optional & set(record))):
        ref = record[key]
        if type(ref) is not dict or set(ref) != {"job_path", "sha256", "byte_count"}:
            raise ValueError("invalid evidence file reference")
        name = ref["job_path"]
        if type(name) is not str or not name or "\\" in name or any(p in {"", ".", ".."} for p in name.split("/")) or PurePosixPath(name).is_absolute():
            raise ValueError("evidence must be a canonical Job-relative path")
        if type(ref["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) or type(ref["byte_count"]) is not int or ref["byte_count"] <= 0:
            raise ValueError("invalid evidence identity")
    source = record["source_binding"]
    if type(source) is not dict or set(source) != {"aroll_sha256", "start", "end"}:
        raise ValueError("invalid source binding")
    if type(source["aroll_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", source["aroll_sha256"]):
        raise ValueError("invalid A-roll hash")
    if any(type(source[k]) not in (int, float) or not math.isfinite(source[k]) for k in ("start", "end")) or not 0 <= source["start"] < source["end"]:
        raise ValueError("invalid source window")
    return json.loads(_canonical(record))


def _snapshot(pinned, ref, destination):
    segment_render._snapshot_job_file(pinned, ref["job_path"], ref["sha256"],
                                      ref["byte_count"], destination,
                                      label="Lovart existing result")


def _framemd5(ffmpeg, path, start_frame=0, end_frame=None):
    args = [str(ffmpeg), "-v", "error", "-i", str(path), "-map", "0:v:0"]
    if start_frame or end_frame is not None:
        if end_frame is None or not (0 <= start_frame < end_frame):
            raise ValueError("invalid framemd5 frame window")
        args += ["-vf", f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS"]
    args += ["-f", "framemd5", "-"]
    result = subprocess.run(args,
                            capture_output=True, text=True, check=True, timeout=60)
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.startswith("#")]
    if not rows:
        raise ValueError("metadata normalization has no decoded frames")
    return rows


def normalize_metadata_only_sar(source, output, ffmpeg_executable):
    """Create the approved no-reencode SAR derivative; never scales or filters."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError("metadata normalization requires a new output path")
    subprocess.run([str(ffmpeg_executable), "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
                    "-map", "0:v:0", "-an", "-c:v", "copy",
                    "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1", "-n", str(output)],
                   check=True, timeout=60)


def normalize_lossless_source_window(source, output, start_frame, end_frame, ffmpeg_executable):
    """Derive a local lossless source window without scaling, interpolation or audio."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists() or not (0 <= start_frame < end_frame):
        raise ValueError("lossless source-window normalization requires a new valid output path")
    subprocess.run([str(ffmpeg_executable), "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
                    "-map", "0:v:0", "-an", "-vf", f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS,setsar=1",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-n", str(output)],
                   check=True, timeout=120)


def _metadata_probe(ffprobe, path, expected):
    result = subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=20)
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("metadata normalization requires one silent video stream")
    stream = streams[0]
    fps = Fraction(stream.get("r_frame_rate", "0/1"))
    rotation = [float(item["rotation"]) for item in stream.get("side_data_list", []) if "rotation" in item]
    rotation.append(float(stream.get("tags", {}).get("rotate", 0)))
    if ((stream.get("width"), stream.get("height"), stream.get("codec_name"), stream.get("pix_fmt"), fps,
         Fraction(stream.get("avg_frame_rate", "0/1"))) !=
            (expected["width"], expected["height"], "h264", "yuv420p", 24, 24)
            or any(rotation) or "mp4" not in info.get("format", {}).get("format_name", "").split(",")):
        raise ValueError("metadata normalization media contract failed")
    frames = int(stream.get("nb_read_frames", stream.get("nb_frames", 0)))
    duration = float(stream.get("duration", 0))
    if frames <= 0 or duration <= 0:
        raise ValueError("metadata normalization has no decodable duration")
    sar = stream.get("sample_aspect_ratio")
    if sar != expected["sar"]:
        raise ValueError("metadata normalization SAR mismatch")
    return {"width": stream["width"], "height": stream["height"], "fps": 24,
            "frames": frames, "duration": duration, "sar": sar,
            "color": tuple(stream.get(key) for key in ("color_range", "color_space", "color_transfer", "color_primaries", "chroma_location"))}


def _approved_output(pinned, bound, qa, task, temporary, ffprobe=None, ffmpeg=None):
    """Accept only the exact derivative in a separately approved padding record."""
    native = qa["native_video"]
    provenance = {"native_sha256": native["sha256"],
                  "native_dimensions": [native["width"], native["height"]],
                  "accepted_with_padding_exception": False}
    if "derived_media" not in bound:
        return native["sha256"], provenance
    path = temporary / "padding-approval.json"
    _snapshot(pinned, bound["normalization_approval"], path)
    approval = json.loads(path.read_bytes())
    if approval.get("approval_type") == "lossless_source_window_normalization":
        source_window = approval.get("source_frames_half_open")
        output_window = approval.get("output_frames_half_open")
        if (type(source_window) is not list or len(source_window) != 2
                or type(output_window) is not list or len(output_window) != 2
                or any(type(frame) is not int for frame in source_window + output_window)
                or type(approval.get("source_frame_count")) is not int
                or not 0 <= source_window[0] < source_window[1] <= approval["source_frame_count"]
                or source_window != qa["source_clock"]["provider_frames_half_open"]):
            raise ValueError("lossless source-window selection changed")
        required = ("schema_version", "status", "approval_type", "host_qa", "generation_id",
                    "source_sha256", "output_sha256", "source_dimensions", "output_dimensions",
                    "source_frame_count", "output_frame_count", "fps", "source_frames_half_open",
                    "output_frames_half_open", "transform", "source_sar", "output_sar",
                    "frame_md5_sha256", "applies_to_other_assets")
        if (set(approval) != set(required) or approval["schema_version"] != 1 or approval["status"] != "approved"
                or not isinstance(approval["host_qa"], str) or not approval["host_qa"].strip()
                or approval["generation_id"] != task or approval["source_sha256"] != native["sha256"]
                or approval["output_sha256"] != bound["derived_media"]["sha256"] or approval["source_sar"] is not None
                or approval["output_sar"] != "1:1" or approval["fps"] != 24
                or approval["source_dimensions"] != approval["output_dimensions"]
                or approval["source_dimensions"] != [native["width"], native["height"]]
                or approval["source_dimensions"] not in ([720, 1280], [1080, 1920])
                or type(approval["source_frame_count"]) is not int or type(approval["output_frame_count"]) is not int
                or approval["output_frame_count"] != approval["output_frames_half_open"][1] - approval["output_frames_half_open"][0]
                or approval["output_frames_half_open"] != [0, approval["output_frame_count"]]
                or not re.fullmatch(r"[0-9a-f]{64}", approval["frame_md5_sha256"])
                or approval["transform"].get("codec") != "libx264" or approval["transform"].get("qp") != 0
                or approval["transform"].get("source_frames_half_open") != approval["source_frames_half_open"]
                or approval["transform"].get("sar") != "1:1" or approval["applies_to_other_assets"] is not False):
            raise ValueError("lossless source-window approval mismatch")
        if ffprobe is not None and ffmpeg is not None:
            source_path, output_path = temporary / "native.mp4", temporary / "derived.mp4"
            _snapshot(pinned, bound["media"], source_path)
            _snapshot(pinned, bound["derived_media"], output_path)
            source = _metadata_probe(ffprobe, source_path, {"width": approval["source_dimensions"][0], "height": approval["source_dimensions"][1], "sar": None})
            derived = _metadata_probe(ffprobe, output_path, {"width": approval["output_dimensions"][0], "height": approval["output_dimensions"][1], "sar": "1:1"})
            start, end = approval["source_frames_half_open"]
            if end - start != derived["frames"] or source["frames"] != approval["source_frame_count"] or source["fps"] != derived["fps"] or source["color"] != derived["color"]:
                raise ValueError("lossless source-window geometry or timing mismatch")
            source_rows = _framemd5(ffmpeg, source_path, start, end)
            rows = _framemd5(ffmpeg, output_path)
            if source_rows != rows or hashlib.sha256("\n".join(rows).encode()).hexdigest() != approval["frame_md5_sha256"]:
                raise ValueError("lossless source-window pixel evidence mismatch")
        provenance.update(lossless_source_window_normalization=True, accepted_with_lossless_window=True,
                          approval_sha256=bound["normalization_approval"]["sha256"], output_frames=approval["output_frame_count"],
                          full_actual_frames=approval["output_frame_count"], transform=approval["transform"])
        return bound["derived_media"]["sha256"], provenance
    if approval.get("approval_type") == "metadata_only_sar_normalization":
        required = ("schema_version", "status", "approval_type", "host_qa", "generation_id",
                    "source_sha256", "output_sha256", "source_dimensions", "output_dimensions",
                    "source_frame_count", "output_frame_count", "fps", "source_frames_half_open",
                    "transform", "source_sar", "output_sar", "frame_md5_sha256", "applies_to_other_assets")
        if (set(approval) != set(required) or approval["schema_version"] != 1 or approval["status"] != "approved"
                or not isinstance(approval["host_qa"], str) or not approval["host_qa"].strip()
                or approval["generation_id"] != task or approval["source_sha256"] != native["sha256"]
                or approval["output_sha256"] != bound["derived_media"]["sha256"]
                or approval["source_sar"] is not None or approval["output_sar"] != "1:1"
                or approval["fps"] != 24
                or approval["source_dimensions"] != approval["output_dimensions"]
                or approval["source_dimensions"] != [native["width"], native["height"]]
                or approval["source_dimensions"] not in ([720, 1280], [1080, 1920])
                or type(approval["source_frame_count"]) is not int or approval["source_frame_count"] <= 0
                or approval["output_frame_count"] != approval["source_frame_count"]
                or approval["source_frames_half_open"] != [0, approval["source_frame_count"]]
                or not re.fullmatch(r"[0-9a-f]{64}", approval["frame_md5_sha256"])
                or approval["transform"] != {"codec": "copy", "filter": None, "sar": "1:1"}
                or approval["applies_to_other_assets"] is not False):
            raise ValueError("metadata normalization approval mismatch")
        full_frames = approval["output_frame_count"]
        derived_frames = full_frames
        if ffprobe is not None and ffmpeg is not None:
            source_path, output_path = temporary / "native.mp4", temporary / "derived.mp4"
            _snapshot(pinned, bound["media"], source_path)
            _snapshot(pinned, bound["derived_media"], output_path)
            source = _metadata_probe(ffprobe, source_path, {"width": approval["source_dimensions"][0], "height": approval["source_dimensions"][1], "sar": None})
            derived = _metadata_probe(ffprobe, output_path, {"width": approval["output_dimensions"][0], "height": approval["output_dimensions"][1], "sar": "1:1"})
            if (source["sar"] is not None or source["width"] != derived["width"] or source["height"] != derived["height"]
                    or source["fps"] != derived["fps"] or source["frames"] != derived["frames"]
                    or abs(source["duration"] - derived["duration"]) > 1e-6 or source["color"] != derived["color"]):
                raise ValueError("metadata normalization changed media timing or geometry")
            source_rows, derived_rows = _framemd5(ffmpeg, source_path), _framemd5(ffmpeg, output_path)
            if source_rows != derived_rows or hashlib.sha256("\n".join(source_rows).encode()).hexdigest() != approval["frame_md5_sha256"]:
                raise ValueError("metadata normalization changed decoded pixels or timestamps")
            if approval["source_frame_count"] != source["frames"] or approval["output_frame_count"] != derived["frames"] or approval["source_frames_half_open"] != [0, source["frames"]]:
                raise ValueError("metadata normalization frame evidence mismatch")
            derived_frames = derived["frames"]
        provenance.update(metadata_only_sar_normalization=True, accepted_with_metadata_only=True,
                          approval_sha256=bound["normalization_approval"]["sha256"], output_frames=derived_frames,
                          transform=approval["transform"], full_actual_frames=derived_frames)
        return bound["derived_media"]["sha256"], provenance
    scene = qa["scene"]
    if approval.get("approval_type") == "single_asset_reviewed_margin_cleanup":
        transform = approval.get("transform")
        allowed = [
            {"crop": [0, 0, 1080, 1800], "pad_bottom": 120,
             "color": "0xf7f9f8", "scale": False, "sar": "1:1"},
            {"crop": [0, 0, 1080, 1920], "pad_bottom": 0,
             "color": "0xf7f9f8", "scale": False, "sar": "1:1"},
        ]
        expected = {
            "schema_version": 1, "status": "approved",
            "approval_type": "single_asset_reviewed_margin_cleanup",
            "generation_id": task, "source_sha256": native["sha256"],
            "output_sha256": bound["derived_media"]["sha256"],
            "approved_preview_sha256": qa["composition"]["sha256"],
            "source_dimensions": [1080, 1920], "output_dimensions": [1080, 1920],
            "source_frame_count": native["frames"], "output_frame_count": scene["frames"],
            "source_frames_half_open": [0, scene["frames"]], "fps": 24,
            "transform": transform, "applies_to_other_assets": False,
        }
        if (transform not in allowed
                or _canonical({k: approval.get(k) for k in expected}) != _canonical(expected)
                or provenance["native_dimensions"] != [1080, 1920]
                or [scene["width"], scene["height"]] != [1080, 1920]
                or native["fps"] != 24 or scene["fps"] != 24
                or scene["sha256"] != bound["derived_media"]["sha256"]
                or type(scene["frames"]) is not int or not 0 < scene["frames"] <= native["frames"]
                or scene["provider_frames_half_open"] != expected["source_frames_half_open"]
                or qa["user_confirmation"]["preview_sha256"] != approval["approved_preview_sha256"]
                or any(type(approval.get(k)) is not str or not approval[k].strip()
                       for k in ("user_confirmation", "confirmation_context"))):
            raise ValueError("margin cleanup does not match this exact reviewed asset and preview")
        provenance.update(accepted_with_margin_cleanup=True,
                          approval_sha256=bound["normalization_approval"]["sha256"],
                          output_frames=scene["frames"], transform=transform,
                          provider_frames_half_open=expected["source_frames_half_open"])
        return scene["sha256"], provenance
    expected = {
        "schema_version": 1, "status": "approved",
        "approval_type": "single_asset_padding_exception", "generation_id": task,
        "source_sha256": native["sha256"], "output_sha256": bound["derived_media"]["sha256"],
        "approved_preview_sha256": qa["composition"]["sha256"],
        "source_dimensions": [1080, 1916], "output_dimensions": [1080, 1920],
        "source_frame_count": native["frames"], "output_frame_count": scene["frames"],
        "source_frames_half_open": [0, scene["frames"]], "fps": native["fps"],
        "transform": {"top": 2, "bottom": 2, "left": 0, "right": 0,
                      "color": "white", "scale": False, "crop": False},
        "applies_to_other_assets": False,
    }
    if type(approval) is not dict or _canonical({k: approval.get(k) for k in expected}) != _canonical(expected):
        raise ValueError("padding approval does not match this exact asset and preview")
    if any(type(approval.get(k)) is not str or not approval[k].strip() for k in ("user_confirmation", "confirmation_context")):
        raise ValueError("padding exception requires explicit user confirmation")
    if (provenance["native_dimensions"] != [1080, 1916]
            or [scene["width"], scene["height"]] != [1080, 1920]
            or scene["sha256"] != bound["derived_media"]["sha256"]
            or scene["fps"] != native["fps"]
            or type(scene["frames"]) is not int or not 0 < scene["frames"] <= native["frames"]
            or scene["provider_frames_half_open"] != expected["source_frames_half_open"]
            or qa["user_confirmation"]["preview_sha256"] != approval["approved_preview_sha256"]):
        raise ValueError("padding derivative chain does not match the reviewed preview")
    provenance.update(accepted_with_padding_exception=True,
                      approval_sha256=bound["normalization_approval"]["sha256"],
                      output_frames=scene["frames"], transform=expected["transform"],
                      provider_frames_half_open=expected["source_frames_half_open"])
    return scene["sha256"], provenance


def _read_evidence(pinned, bound, temporary, ffprobe=None, ffmpeg=None):
    values = []
    for key in ("generation", "qa"):
        path = temporary / f"{key}.json"
        _snapshot(pinned, bound[key], path)
        values.append(json.loads(path.read_bytes()))
    generation, qa = values
    if type(generation) is not dict or type(qa) is not dict:
        raise ValueError("evidence must be JSON objects")
    request = generation["request"]
    submission = generation["submission_response"]
    completion = generation["completion_response"]
    observed = qa["generation"]
    if generation.get("status") != "completed" or completion.get("status") != "completed":
        raise ValueError("Lovart generation is not completed")
    model, project, task, artifact_id = (observed[k] for k in ("model", "project_id", "task_id", "artifact_id"))
    if any(type(value) is not str or not value for value in (model, project, task, artifact_id)):
        raise ValueError("missing Lovart generation identity")
    if observed.get("provider") != PROVIDER or any(r.get("model") != model or r.get("project_id") != project for r in (request, submission, completion)):
        raise ValueError("Lovart provider/model/project mismatch")
    if submission.get("task_ids") != [task]:
        raise ValueError("expected one bound Lovart task")
    artifacts = [a for a in completion["artifacts"] if a.get("id") == artifact_id]
    native = qa["native_video"]
    if len(artifacts) != 1 or artifacts[0].get("type") != "video" or any(artifacts[0].get(k) != native[k] for k in ("width", "height")):
        raise ValueError("Lovart artifact identity mismatch")
    if native["sha256"] != bound["media"]["sha256"] or qa["source_clock"]["cut_sha256"] != bound["source_binding"]["aroll_sha256"]:
        raise ValueError("Lovart native media or A-roll identity mismatch")
    prompt = request["prompt"]
    if type(prompt) is not str or not prompt:
        raise ValueError("missing actual request prompt")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if observed.get("request_prompt_sha256") != prompt_hash:
        raise ValueError("actual request prompt identity mismatch")
    output_sha, provenance = _approved_output(pinned, bound, qa, task, temporary, ffprobe, ffmpeg)
    return {"provider": PROVIDER, "model": model, "endpoint_id": ENDPOINT_ID,
            "prompt_sha256": prompt_hash, "generation_id": task,
            "sha256": output_sha}, {"project_id": project, "artifact_id": artifact_id, **provenance}, qa


def _evidence(pinned, bound, temporary, ffprobe=None, ffmpeg=None):
    try:
        return _read_evidence(pinned, bound, temporary, ffprobe, ffmpeg)
    except (KeyError, TypeError, AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Lovart generation/QA evidence is incomplete or malformed") from error


def _probe_actual_media(ffprobe, pinned, path, contract):
    """Read and validate the bytes that will actually be handed to the executor."""
    if (_sha(ffprobe) != pinned or (contract.get("width"), contract.get("height")) not in {(720, 1280), (1080, 1920)}
            or contract.get("fps") != 24 or contract.get("alpha") is not False):
        raise ValueError("Lovart video probe contract failed")
    inherited = (int(path.name),) if path.parent == Path("/dev/fd") else ()
    result = subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format",
                             "-of", "json", str(path)], pass_fds=inherited, capture_output=True,
                            text=True, timeout=20)
    if result.returncode:
        raise ValueError("Lovart video ffprobe failed")
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("Lovart source must contain one silent video stream")
    stream = streams[0]
    fps = Fraction(stream.get("r_frame_rate", "0/1"))
    rotation = [float(item["rotation"]) for item in stream.get("side_data_list", []) if "rotation" in item]
    rotation.append(float(stream.get("tags", {}).get("rotate", 0)))
    if ((stream.get("width"), stream.get("height"), stream.get("sample_aspect_ratio"), stream.get("codec_name"),
         stream.get("pix_fmt"), fps, Fraction(stream.get("avg_frame_rate", "0/1")))
            != (contract["width"], contract["height"], "1:1", "h264", "yuv420p", 24, 24)
            or any(rotation) or "mp4" not in info.get("format", {}).get("format_name", "").split(",")):
        raise ValueError("Lovart source media does not match the approved contract")
    frames = int(stream.get("nb_read_frames", stream.get("nb_frames", 0)))
    duration = float(stream.get("duration", 0))
    if frames <= 0 or duration <= 0:
        raise ValueError("Lovart source has no decodable duration")
    return {"media_type": "video", "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
            "alpha": False, "width": stream["width"], "height": stream["height"], "fps": float(fps),
            "frame_count": frames, "duration": duration}


def prepare_existing_binding(job, record, ffprobe_executable):
    """Validate a completed result and return compiler-only reuse bindings."""
    bound = _record_copy(record)
    if bound["job_id"] != job.job_id:
        raise ValueError("Lovart record belongs to another Job")
    ffprobe = Path(ffprobe_executable).resolve(strict=True)
    pinned_ffprobe = _sha(ffprobe)
    pinned = broll_media._PinnedJob.open(job)
    try:
        with tempfile.TemporaryDirectory(prefix="lovart-prepare-") as directory:
            temporary = Path(directory)
            ffmpeg_path = shutil.which("ffmpeg") if "derived_media" in bound else None
            expected, metadata, _qa = _evidence(pinned, bound, temporary, ffprobe, Path(ffmpeg_path) if ffmpeg_path else None)
            ref = bound.get("derived_media", bound["media"])
            snapshot = temporary / "prepared.mp4"
            _snapshot(pinned, ref, snapshot)
            dimensions = tuple(metadata.get("native_dimensions", ()))
            if "derived_media" in bound and (metadata.get("metadata_only_sar_normalization") or metadata.get("lossless_source_window_normalization")):
                dimensions = tuple(metadata.get("native_dimensions", ()))
            elif "derived_media" in bound:
                dimensions = (1080, 1920)
            if dimensions not in {(720, 1280), (1080, 1920)}:
                raise ValueError("Lovart source dimensions are not reusable")
            media_probe = _probe_actual_media(ffprobe, pinned_ffprobe, snapshot,
                                               {"width": dimensions[0], "height": dimensions[1], "fps": 24, "alpha": False})
            if _sha(snapshot) != expected["sha256"]:
                raise ValueError("Lovart prepared media identity mismatch")
            pinned.verify_visible()
    finally:
        pinned.close()
    return {**expected, "execution_mode": "reuse_completed_lovart_video",
            "source_dimensions": {"width": media_probe["width"], "height": media_probe["height"]}}


def create_adapter(job, record):
    """Bind one component to native evidence and an optional approved derivative."""
    bound = _record_copy(record)
    job_dir = Path(job.job_dir)
    if bound["job_id"] != job.job_id:
        raise ValueError("Lovart record belongs to another Job")
    pinned = broll_media._PinnedJob.open(job)
    try:
        with tempfile.TemporaryDirectory(prefix="lovart-existing-") as directory:
            expected, metadata, _qa = _evidence(pinned, bound, Path(directory))
        pinned.verify_visible()
    finally:
        pinned.close()
    record_hash = hashlib.sha256(_canonical(bound)).hexdigest()
    implementations = {str(path): _sha(path) for path in (
        Path(__file__), Path(broll_media.__file__), Path(segment_render.__file__))}
    identity = hashlib.sha256(_canonical({"record": record_hash, "implementation": implementations})).hexdigest()

    def invoke(context):
        if (context.job_id, context.segment_id, context.component_id, context.job_dir) != (bound["job_id"], bound["segment_id"], bound["component_id"], job_dir):
            raise ValueError("Lovart target binding mismatch")
        if any(_sha(path) != digest for path, digest in implementations.items()):
            raise ValueError("bound Lovart reuse implementation changed")
        component = context.component
        if component["kind"] != "ai_generated" or any(component.get(k) != v for k, v in expected.items()):
            raise ValueError("Lovart component generation identity mismatch")
        plan = visual_canary.load_approved_visual_plan(job)
        segments = [s for s in plan["segments"] if s["segment_id"] == bound["segment_id"]]
        if len(segments) != 1 or segments[0]["shot_recipe"] != json.loads(_canonical(context.recipe)):
            raise ValueError("Lovart recipe is not the current approved segment")
        segment = segments[0]
        arroll = visual_canary.approved_aroll_record(job, plan)
        if bound["source_binding"] != {"aroll_sha256": arroll["sha256"], "start": segment["start"], "end": segment["end"]}:
            raise ValueError("Lovart source window changed")
        pinned = broll_media._PinnedJob.open(job)
        try:
            with tempfile.TemporaryDirectory(prefix="lovart-existing-") as directory:
                temporary = Path(directory)
                actual, _metadata, qa = _evidence(pinned, bound, temporary)
                if actual != expected:
                    raise ValueError("Lovart generation evidence changed")
                fps = context.recipe["canvas"]["fps"]
                if qa["source_clock"]["broll_frames_half_open"] != [round(segment["start"] * fps), round(segment["end"] * fps)]:
                    raise ValueError("Lovart source-clock window mismatch")
                snapshot = temporary / "native.mp4"
                _snapshot(pinned, bound["media"], snapshot)
                if "derived_media" in bound:
                    window = component["render_window"]
                    if metadata.get("metadata_only_sar_normalization"):
                        if not (0 <= window["start_frame"] < window["end_frame"] <= metadata["full_actual_frames"]):
                            raise ValueError("metadata-normalized derivative frame window is out of bounds")
                    elif window["start_frame"] != 0 or window["end_frame"] != metadata["output_frames"]:
                        raise ValueError("approved derivative frame window changed")
                    snapshot = temporary / "approved-scene.mp4"
                    _snapshot(pinned, bound["derived_media"], snapshot)
                pinned.verify_visible()
                # KindAdapter receives an already-open executor-owned /dev/fd/N.
                # Snapshot securely first; never use O_EXCL on that descriptor.
                with snapshot.open("rb") as source, context.staging_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        finally:
            pinned.close()
        return AdapterResult(
            invocation_evidence={"record_sha256": record_hash, "provider_request_reused": True,
                                 "external_requests": 0, "task_id": expected["generation_id"], **metadata},
            qa={"passed": True, "checks": ["generation and source-clock identity matched",
                                             "approved input bytes reused without further media processing"]})

    return KindAdapter(kind="ai_generated", approved_executor=EXECUTOR,
                       adapter_id="lovart-existing-video-v1", adapter_version=f"{VERSION}-{identity}",
                       artifact_media_type="video", invoke=invoke, provider=PROVIDER,
                       model=expected["model"], endpoint_id=ENDPOINT_ID)


def create_artifact_probe(ffprobe_executable):
    """Verify an actual silent portrait source at 720p or native 1080p."""
    ffprobe = Path(ffprobe_executable).resolve(strict=True)
    pinned = _sha(ffprobe)

    def probe(path, media_type, contract):
        if media_type != "video":
            raise ValueError("Lovart video probe contract failed")
        return _probe_actual_media(ffprobe, pinned, path, contract)

    identity = hashlib.sha256(_canonical({"implementation": _sha(Path(__file__)),
                                         "ffprobe": pinned})).hexdigest()
    return ArtifactProbe(probe_id="lovart-existing-portrait-mp4",
                         probe_version=f"{VERSION}-{identity}", probe=probe)

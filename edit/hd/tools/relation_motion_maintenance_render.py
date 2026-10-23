"""Strict media contract for relation-motion maintenance candidates."""
from __future__ import annotations
import math
import json, subprocess, hashlib, os
import signal
from pathlib import Path

def build_approved_relation_brief(*args, **kwargs):
    """Load Job-only dependencies only when the maintenance bridge is requested."""
    from .relation_motion_maintenance import build_approved_relation_brief as build
    return build(*args, **kwargs)

class RelationMotionRenderError(ValueError):
    pass

def _fail(message):
    raise RelationMotionRenderError(message)

def _run_checked(command, *, timeout, input=None):
    """Use a private session, or explicitly inherit a frozen executor's group."""
    parent_group = os.environ.get("HD_RELATION_PARENT_GROUP")
    if parent_group is not None and parent_group != str(os.getpgrp()):
        _fail("supervised parent group does not match current process")
    private_session = parent_group is None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=private_session,
        )
    except OSError as exc:
        raise RelationMotionRenderError("process could not start") from exc
    try:
        try:
            stdout, stderr = process.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RelationMotionRenderError("process timed out") from exc
        if process.returncode:
            _fail(f"process failed ({process.returncode}): {stderr[-2000:]}")
        if private_session:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                _fail("process left running descendants")
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        try:
            if private_session:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RelationMotionRenderError("process cleanup timed out") from exc

def _finite(value, label):
    if isinstance(value, bool): _fail(f"{label} must be finite")
    try: result = float(value)
    except (TypeError, ValueError, OverflowError): _fail(f"{label} must be finite")
    if not math.isfinite(result): _fail(f"{label} must be finite")
    return result

def validate_relation_media_probe(probe: dict, duration_frames: int) -> None:
    if type(duration_frames) is not int or not 48 <= duration_frames <= 240: _fail("duration_frames must be integer 48..240")
    if type(probe) is not dict or type(probe.get("streams")) is not list or type(probe.get("format")) is not dict: _fail("probe shape is invalid")
    streams = probe["streams"]
    if len(streams) != 1 or type(streams[0]) is not dict: _fail("probe must contain exactly one stream")
    stream = streams[0]
    if any(stream.get(key) != value for key, value in (("codec_type", "video"), ("codec_name", "h264"), ("width", 1080), ("height", 1920), ("pix_fmt", "yuv420p"), ("r_frame_rate", "24/1"), ("avg_frame_rate", "24/1"), ("sample_aspect_ratio", "1:1"))): _fail("video stream contract failed")
    raw_frames = stream.get("nb_read_frames")
    if isinstance(raw_frames, bool) or not (type(raw_frames) is int or (type(raw_frames) is str and raw_frames.isdecimal())): _fail("nb_read_frames is invalid")
    frames = raw_frames if type(raw_frames) is int else int(raw_frames)
    if frames != duration_frames: _fail("frame count mismatch")
    if abs(_finite(stream.get("duration"), "stream.duration") - duration_frames / 24) > 1e-5: _fail("stream duration mismatch")
    if abs(_finite(probe["format"].get("duration"), "format.duration") - duration_frames / 24) > 1e-5: _fail("format duration mismatch")
    tags = stream.get("tags", {})
    if not isinstance(tags, dict): _fail("tags shape is invalid")
    if tags.get("rotate", "0") not in ("0", 0): _fail("rotation must be zero")
    side_data = stream.get("side_data_list", [])
    if not isinstance(side_data, list) or any(not isinstance(item, dict) for item in side_data): _fail("side_data_list shape is invalid")
    if any(_finite(item.get("rotation"), "rotation") != 0 for item in side_data if "rotation" in item): _fail("rotation must be zero")

def _new_output_path(output_dir):
    out = Path(output_dir)
    if any(part.is_symlink() for part in (out, *out.parents)):
        _fail("output path contains symlink")
    if not out.is_absolute() or out.exists(): _fail("output_dir must be absolute and new")
    return out.resolve()


def _canonical_brief(brief):
    if type(brief) is not dict or set(brief) != {"schema_version", "canvas", "motion", "title", "source_ids", "hub_id"}:
        _fail("brief root fields invalid")
    return json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_relation_brief_artifact(*, brief, output_dir, node_executable,
                                   playwright_module, browser_executable,
                                   ffmpeg_executable, ffprobe_executable):
    """One shared media pipeline. This function does not know about Job approval."""
    try:
        out = _new_output_path(output_dir)
        canonical = _canonical_brief(brief)
        capture_script = Path(__file__).with_name("relation_motion_capture.cjs")
        renderer = Path(__file__).with_name("relation_motion_renderer.cjs")
        capture_sha_before = _file_sha(capture_script)
        renderer_sha_before = _file_sha(renderer)
        html = _run_checked([str(node_executable), str(renderer), "--html"], input=canonical.decode(), timeout=10).stdout
        out.mkdir(parents=True)
        (out / "brief.json").write_bytes(canonical)
        (out / "page.html").write_text(html, encoding="utf-8")
        frames = out / "frames"; duration = brief["canvas"]["duration_in_frames"]
        _run_checked([str(node_executable), str(Path(__file__).with_name("relation_motion_capture.cjs")), "--html", str(out/"page.html"), "--output", str(frames), "--duration", str(duration), "--playwright", str(playwright_module), "--browser", str(browser_executable)], timeout=180)
        names = {p.name for p in frames.iterdir()}; expected = {f"frame-{i:06d}.png" for i in range(duration)} | {"boundary.png"}
        if names != expected or any(p.is_symlink() or not p.is_file() for p in frames.iterdir()): _fail("capture frame set invalid")
        video = out / "candidate.mp4"
        _run_checked([str(ffmpeg_executable), "-v", "error", "-n", "-framerate", "24", "-i", str(frames/"frame-%06d.png"), "-vf", "setsar=1", "-frames:v", str(duration), "-threads", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], timeout=180)
        video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
        probe = json.loads(_run_checked([str(ffprobe_executable), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)], timeout=30).stdout); validate_relation_media_probe(probe, duration)
        _run_checked([str(ffmpeg_executable), "-v", "error", "-nostdin", "-xerror", "-threads", "1", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"], timeout=180)
        if capture_sha_before != _file_sha(capture_script): _fail("capture script changed")
        if renderer_sha_before != _file_sha(renderer): _fail("renderer changed")
        if video_sha != _file_sha(video): _fail("media changed during validation")
        return {
            "brief_sha256": hashlib.sha256(canonical).hexdigest(),
            "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
            "renderer_sha256": renderer_sha_before,
            "capture_script_sha256": capture_sha_before,
            "mp4_sha256": video_sha, "candidate_path": str(video), "media_probe": probe,
        }
    except Exception as exc:
        if isinstance(exc, RelationMotionRenderError): raise
        raise RelationMotionRenderError(str(exc)) from exc


def render_relation_motion_maintenance(*, job_dir, draft, title, source_ids, hub_id,
                                      output_dir, node_executable, playwright_module,
                                      browser_executable, ffmpeg_executable, ffprobe_executable):
    """Bind the shared media pipeline to freshly approved maintenance content."""
    try:
        out = _new_output_path(output_dir)
        job = Path(job_dir).resolve(strict=True)
        if os.path.commonpath([str(out), str(job)]) == str(job): _fail("output_dir must be outside Job")
        bundle = build_approved_relation_brief(job, draft, title, source_ids, hub_id, node_executable)
        if hashlib.sha256(_canonical_brief(bundle["brief"])).hexdigest() != bundle["brief_sha256"]:
            _fail("brief hash mismatch")
        artifact = render_relation_brief_artifact(
            brief=bundle["brief"], output_dir=out, node_executable=node_executable,
            playwright_module=playwright_module, browser_executable=browser_executable,
            ffmpeg_executable=ffmpeg_executable, ffprobe_executable=ffprobe_executable,
        )
        final = build_approved_relation_brief(job, draft, title, source_ids, hub_id, node_executable)
        if final != bundle or artifact["renderer_sha256"] != bundle["renderer_sha256"]:
            _fail("approved identity drifted")
        if artifact["mp4_sha256"] != _file_sha(artifact["candidate_path"]):
            _fail("media changed during validation")
        if artifact["capture_script_sha256"] != _file_sha(Path(__file__).with_name("relation_motion_capture.cjs")):
            _fail("capture script changed")
        receipt = {
            "status": "maintenance_only", "purpose": "visual_qa_candidate", "formal_eligibility": False,
            **{key: value for key, value in artifact.items() if key.endswith("_sha256")},
            "workflow_sha256": bundle["workflow_sha256"],
            "content_analysis_sha256": bundle["content_analysis_sha256"],
        }
        (out/"maintenance-receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        return receipt
    except Exception as exc:
        if isinstance(exc, RelationMotionRenderError): raise
        raise RelationMotionRenderError(str(exc)) from exc

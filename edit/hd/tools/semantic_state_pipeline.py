"""Shared semantic-state media execution; callers own staging and approval."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess

from .relation_motion_maintenance_render import validate_relation_media_probe


def _run(command, *, timeout, input=None):
    """Keep subprocesses in the supervisor group or an owned private group."""
    group = os.environ.get("HD_RELATION_PARENT_GROUP")
    if group is not None and group != str(os.getpgrp()):
        raise ValueError("supervised parent group mismatch")
    private = group is None
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=private)
    try:
        try:
            stdout, stderr = process.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("semantic render process timed out") from exc
        if process.returncode:
            raise ValueError(f"semantic render process failed: {stderr[-2000:]}")
        if private:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError("semantic render left running descendants")
        return stdout
    finally:
        try:
            if private:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def render_semantic_artifact(*, brief, output_dir, node_executable, playwright_module,
                            browser_executable, ffmpeg_executable, ffprobe_executable):
    """Render all five families identically; no Job mutation or approval receipt."""
    out = Path(output_dir)
    if not out.is_absolute() or out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("output must be absolute, new and without symlinks")
    if type(brief) is not dict or set(brief) != {"schema_version", "canvas", "title", "motion", "roles"}:
        raise ValueError("semantic brief root fields invalid")
    canonical = json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(canonical.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("semantic brief exceeds 4 MiB")
    renderer = Path(__file__).with_name("semantic_state_renderer.cjs")
    capture = Path(__file__).with_name("semantic_state_capture.cjs")
    identities = {"renderer_sha256": _sha(renderer), "capture_script_sha256": _sha(capture)}
    html = _run([str(node_executable), str(renderer), "--html"], input=canonical, timeout=10)
    duration = brief["canvas"]["duration_in_frames"]
    out.mkdir()
    (out / "brief.json").write_text(canonical, encoding="utf-8")
    (out / "page.html").write_text(html, encoding="utf-8")
    frames = out / "frames"
    _run([str(node_executable), str(capture), "--output", str(frames),
          "--playwright", str(playwright_module), "--browser", str(browser_executable)],
         input=canonical, timeout=180)
    expected = {f"frame-{index:06d}.png" for index in range(duration)} | {"boundary.png"}
    files = list(frames.iterdir())
    if {p.name for p in files} != expected or any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("semantic capture frame set invalid")
    candidate = out / "candidate.mp4"
    _run([str(ffmpeg_executable), "-v", "error", "-n", "-framerate", "24", "-i",
          str(frames / "frame-%06d.png"), "-vf", "setsar=1", "-frames:v", str(duration),
          "-threads", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(candidate)], timeout=180)
    media_sha = _sha(candidate)
    probe = json.loads(_run([str(ffprobe_executable), "-v", "error", "-count_frames",
        "-show_streams", "-show_format", "-of", "json", str(candidate)], timeout=30))
    validate_relation_media_probe(probe, duration)
    _run([str(ffmpeg_executable), "-v", "error", "-nostdin", "-xerror", "-threads", "1",
          "-i", str(candidate), "-map", "0:v:0", "-f", "null", "-"], timeout=180)
    if identities != {"renderer_sha256": _sha(renderer), "capture_script_sha256": _sha(capture)}:
        raise ValueError("semantic renderer identity changed")
    if media_sha != _sha(candidate):
        raise ValueError("semantic media changed during validation")
    return {**identities, "brief_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "html_sha256": hashlib.sha256(html.encode()).hexdigest(), "mp4_sha256": media_sha,
            "candidate_path": str(candidate), "media_probe": probe}

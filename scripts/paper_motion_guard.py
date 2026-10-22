"""Fail-closed ffmpeg freeze detection for paper-collage outputs."""
import json
import re
import subprocess
from pathlib import Path


_START = re.compile(r"freeze_start:\s*([0-9.]+)")
_END = re.compile(r"freeze_end:\s*([0-9.]+)")


def check(path, ffmpeg, ffprobe, *, minimum=3.0):
    """Return freeze evidence, or raise before an artifact can be published."""
    path = Path(path)
    try:
        probe = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True, timeout=60)
        duration = float(probe.stdout.strip())
        if duration <= 0:
            raise ValueError("motion guard requires a positive duration")
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-v", "info", "-i", str(path),
             "-vf", f"freezedetect=n=0.001:d={minimum}", "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=240)
        log = result.stderr
        if result.returncode:
            raise ValueError("freeze detection ffmpeg failed")
        starts = [float(x) for x in _START.findall(log)]
        ends = [float(x) for x in _END.findall(log)]
        freezes = []
        for index, start in enumerate(starts):
            end = ends[index] if index < len(ends) else duration
            if end - start >= minimum:
                freezes.append({"start": start, "end": end, "duration": end - start})
        evidence = {"method": "ffmpeg-freezedetect", "threshold": 0.001,
                    "minimum_seconds": minimum, "duration": duration, "freezes": freezes}
        if freezes:
            raise ValueError("paper output contains a continuous freeze >= 3 seconds: " + json.dumps(evidence))
        return evidence
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("paper output contains"):
            raise
        raise ValueError("motion guard failed closed: " + str(exc)) from exc

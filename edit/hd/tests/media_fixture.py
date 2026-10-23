"""Small, real media fixtures for the HD workflow tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


FFMPEG_TIMEOUT_SECONDS = 90


def make_av_fixture(directory: Path, name: str = "fixture.mp4") -> Path:
    """Create a three-second portrait H.264/AAC source."""
    target = directory / name
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=0x24304a:s=1080x1920:r=24:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(target),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        check=True,
    )
    return target


def make_video_only_fixture(directory: Path, name: str = "video-only.mp4") -> Path:
    target = directory / name
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=24:d=3",
            "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(target),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        check=True,
    )
    return target


def assert_complete_decode(path: Path) -> None:
    for media_type in ("v:0", "a:0"):
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-xerror", "-i", str(path), "-map", f"0:{media_type}",
                "-f", "null", "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=True,
        )

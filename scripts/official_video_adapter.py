"""Connect a reviewed official snapshot to the parent component executor.

Acquisition remains owned by video-download. This adapter only preserves its
encoded video and drops native audio before the parent's silent-video probe.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import shutil
from pathlib import Path


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_adapter(ffmpeg_executable):
    from edit.hd.tools.broll_component_executor import AdapterResult, KindAdapter

    executable = Path(ffmpeg_executable).resolve(strict=True)
    executable_sha = _sha(executable)

    def invoke(context):
        if (context.source_path is None
                or context.source_sha256 != context.component["sha256"]
                or _sha(context.source_path) != context.source_sha256):
            raise ValueError("Official material has no unchanged approved snapshot")
        if _sha(executable) != executable_sha:
            raise ValueError("Official video normalization runtime changed")
        inherited = (int(context.source_path.name),) if context.source_path.parent == Path("/dev/fd") else ()
        with tempfile.TemporaryDirectory(prefix="official-video-stream-") as directory:
            silent = Path(directory) / "silent.mp4"
            subprocess.run([str(executable), "-v", "error", "-nostdin", "-y",
                "-i", str(context.source_path), "-map", "0:v:0", "-an",
                "-c:v", "copy", "-movflags", "+faststart", str(silent)],
                pass_fds=inherited, capture_output=True, check=True, timeout=60)
            with silent.open("rb") as video, context.staging_path.open("wb") as target:
                shutil.copyfileobj(video, target)
        return AdapterResult(
            invocation_evidence={"source_id": context.component["source_id"],
                "source_sha256": context.source_sha256,
                "upstream": "video-download and video-use", "external_requests": 0},
            qa={"passed": True, "checks": ["encoded video preserved; native audio removed"]})

    return KindAdapter(kind="official_material", approved_executor="official-media",
        adapter_id="official-video-snapshot", artifact_media_type="video",
        adapter_version="1.0-" + hashlib.sha256((_sha(__file__) + executable_sha).encode()).hexdigest(),
        invoke=invoke)

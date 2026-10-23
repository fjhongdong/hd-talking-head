"""Local reference-ASR capability checks; a probe is never user authorization."""

from __future__ import annotations

import re
import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import argparse
import sys
import copy
from contextlib import contextmanager
from typing import Any

from . import transcribe
from .state import JobState, WorkflowError, load_job


@contextmanager
def _approved_material_request(job_dir: Path, material_id: str, *, language: str):
    """Hold exact local inputs; consumers must recheck before returning/publishing."""
    from . import startup, user_materials

    if not isinstance(material_id, str) or re.fullmatch(r"material-[0-9]{4,}", material_id) is None:
        raise ValueError("invalid material ID")
    if not isinstance(language, str) or re.fullmatch(r"[a-z]{2,3}", language) is None:
        raise ValueError("explicit whisper language code is required")
    job = load_job(Path(job_dir))
    startup.require_startup(job)
    probe = probe_configured_runtime(job)
    if probe is None:
        raise WorkflowError("reference ASR was not selected for this Job")

    def require_probe():
        report = startup._read(job.job_dir / "manifests/dependency-preflight.json", "reference ASR preflight")
        records = [item for item in report.get("dependencies", []) if item.get("id") == "reference-asr"]
        if (len(records) != 1 or records[0].get("reference_asr_probe") != probe
                or startup._config(job)[1] != probe["provider_config_sha256"]):
            raise WorkflowError("reference ASR runtime differs from current preflight")

    require_probe()
    material = copy.deepcopy(user_materials.require_active_material(job.root, material_id))
    if material.get("media_type") not in {"video", "audio"}:
        raise ValueError("reference ASR requires indexed audio or video")
    relative = Path(material["imported_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("reference source must remain inside the workspace")
    pins = []
    try:
        pins.append(transcribe._pin_local_media(job.root / relative, expected_sha256=material["sha256"],
                                               expected_bytes=material["size_bytes"]))
        for key in ("executable", "model_file"):
            record = probe[key]
            pins.append(transcribe._pin_local_media(Path(record["path"]), expected_sha256=record["sha256"],
                                                   expected_bytes=record["bytes"]))

        def recheck():
            startup.require_startup(load_job(job.job_dir))
            require_probe()
            if user_materials.require_active_material(job.root, material_id) != material:
                raise WorkflowError("reference material changed during transcription")
            for item in pins:
                transcribe._verify_pinned(item)

        identity = {"version": 1, "material": material, "language": language,
                    "runtime": probe, "implementation": "reference-asr-local-v1"}
        recheck()
        yield identity, pins, recheck
    finally:
        if not transcribe._close_pinned_inputs(pins):
            raise WorkflowError("reference ASR input cleanup failed")


@contextmanager
def _executable_snapshot(executable):
    """macOS cannot exec /dev/fd; copy pinned bytes into a private directory."""
    with tempfile.TemporaryDirectory(prefix="hd-reference-asr-engine-") as directory:
        root = Path(directory).resolve()
        (root / "bin").mkdir()
        snapshot = root / "bin" / executable.path.name
        checksum = hashlib.sha256()
        os.lseek(executable.descriptor, 0, os.SEEK_SET)
        with snapshot.open("xb") as stream:
            while chunk := os.read(executable.descriptor, 65536):
                stream.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest() != executable.sha256:
            raise transcribe.TranscriptionError("reference ASR executable changed")
        snapshot.chmod(0o500)
        # Installed @loader_path dependencies are retained, not sandboxed.
        libraries = executable.path.parent.parent / "lib"
        if libraries.is_dir():
            (root / "lib").symlink_to(libraries, target_is_directory=True)
        yield snapshot


def _recognize_pinned_reference(source, executable, model, *, language: str) -> dict[str, Any]:
    """Internal execution core; caller must hold current Job approval and pins."""
    if not isinstance(language, str) or re.fullmatch(r"[a-z]{2,3}", language) is None:
        raise ValueError("explicit whisper language code is required")
    from .reference_transcripts import _checked_cues

    for item in (source, executable, model):
        transcribe._verify_pinned(item)
    with tempfile.TemporaryDirectory(prefix="hd-reference-asr-work-") as directory:
        root = Path(directory).resolve()
        wav, raw = root / "audio.wav", root / "whisper.json"
        transcribe._extract_pcm16k_pinned(source, wav)
        with _executable_snapshot(executable) as snapshot:
            words = transcribe.transcribe_words(
                transcribe.WhisperRuntime(snapshot, model.path), wav, raw,
                model_input=model, language=language,
            )
        cues = _checked_cues([{"text": word.text, "start": word.start, "end": word.end}
                              for word in words])
        for item in (source, executable, model):
            transcribe._verify_pinned(item)
        return {"cues": cues, "raw_output_sha256": transcribe._sha256(raw)}


def probe_configured_runtime(job: JobState) -> dict[str, Any] | None:
    """Pre-approval probe of the explicitly selected capability, not an enablement."""
    from . import startup

    path, digest = startup._config(job)
    pinned = transcribe._pin_local_media(path, expected_sha256=digest)
    try:
        config = json.loads(transcribe._read_descriptor_text(pinned.descriptor),
                            object_pairs_hook=transcribe._strict_object,
                            parse_constant=transcribe._reject_nonfinite)
        transcribe._verify_pinned(pinned)
        selected = config.get("reference_asr")
        result = None if selected is None else probe_local_runtime(selected["model"])
        if startup._config(job) != (path, digest):
            raise startup.WorkflowError("reference ASR configuration changed during probe")
        transcribe._verify_pinned(pinned)
        if result is not None:
            result = {**result, "provider_config_sha256": digest}
        return result
    finally:
        if not transcribe._close_descriptor(pinned.descriptor):
            raise startup.WorkflowError("reference ASR config probe cleanup failed")


def probe_local_runtime(model_id: str) -> dict[str, Any]:
    """Identify local files and run help only; do not load a model or user media."""
    if not isinstance(model_id, str) or re.fullmatch(r"ggml-[a-z0-9][a-z0-9.-]*", model_id) is None:
        raise transcribe.TranscriptionError("invalid reference ASR model identifier")
    runtime = transcribe.discover_runtime()
    if runtime.model.name != model_id + ".bin":
        raise transcribe.TranscriptionError("reference ASR model differs from selected model")
    pinned = []
    try:
        executable = transcribe._pin_local_media(runtime.executable)
        pinned.append(executable)
        model = transcribe._pin_local_media(runtime.model)
        pinned.append(model)
        try:
            with _executable_snapshot(executable) as snapshot:
                result = subprocess.run(
                    [str(snapshot), "--help"], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15, check=False,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise transcribe.TranscriptionError("reference ASR command probe failed") from exc
        if result.returncode != 0:
            raise transcribe.TranscriptionError("reference ASR command probe failed")
        for item in pinned:
            transcribe._verify_pinned(item)
        return {
            "version": 1, "provider": "whisper.cpp", "model": model_id,
            "execution": "local", "upload_policy": "forbidden",
            "callable": True, "model_load_verified": False,
            "executable": {"path": str(executable.path), "sha256": executable.sha256, "bytes": executable.size},
            "model_file": {"path": str(model.path), "sha256": model.sha256, "bytes": model.size},
        }
    finally:
        if not transcribe._close_pinned_inputs(pinned):
            raise transcribe.TranscriptionError("reference ASR probe cleanup failed")


def main(argv: list[str] | None = None) -> int:
    """Fresh-process preflight bridge; never confirms setup or transcribes media."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not args.job.is_absolute():
            raise ValueError("absolute Job path required")
        report = probe_configured_runtime(load_job(args.job))
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        return 0
    except (WorkflowError, ValueError) as exc:
        print(f"reference ASR probe failed: {type(exc).__name__}", file=sys.stderr)
        return 3
    except (transcribe.TranscriptionError, OSError) as exc:
        print(f"reference ASR probe failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

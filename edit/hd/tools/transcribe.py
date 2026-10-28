"""Local-only whisper.cpp adapter for the HD talking-head workflow."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import unicodedata
import wave
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from .inspect_inputs import (
    GenerationRecoveryError,
    InspectionError,
    _GenerationEntry,
    _discard_unpublished,
    _digest_descriptor,
    _move_owned,
    _media_profile,
    _new_generation,
    _publish_generation,
    _unlink_owned,
    _write_report,
)
from .state import JobState, block, mark_ready, require_runnable


SUBPROCESS_TIMEOUT_SECONDS = 300
RUNTIME_REQUIRED_REASON = (
    "需要一次性安装 whisper.cpp，并下载 ggml-large-v3-turbo.bin 模型后重试"
)
_CONTROL_TOKEN = re.compile(r"^\[_.*\]$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WHISPER_TIMESTAMP_QUANTUM_MS = Decimal(10)


class TranscriptionError(RuntimeError):
    """A safe local-transcription failure."""


@dataclass(frozen=True)
class WhisperRuntime:
    executable: Path
    model: Path


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _PinnedInput:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int


@dataclass(frozen=True)
class _PinnedOutput:
    path: Path
    descriptor: int
    device: int
    inode: int


def _fail(message: str = "local transcription failed") -> TranscriptionError:
    return TranscriptionError(message)


def _absolute(path: Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise _fail("local whisper runtime is unavailable")
    return value


def _regular_single_link(path: Path, *, executable: bool = False) -> Path:
    path = _absolute(path)
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _fail("local whisper runtime is unavailable")
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
            raise _fail("local whisper runtime is unavailable")
        if executable and not os.access(path, os.X_OK):
            raise _fail("local whisper runtime is unavailable")
    except (OSError, ValueError) as exc:
        raise _fail("local whisper runtime is unavailable") from exc
    return path


def discover_runtime() -> WhisperRuntime:
    """Discover a complete local runtime without silently mixing sources."""
    executable_env = os.environ.get("HD_WHISPER_CLI")
    model_env = os.environ.get("HD_WHISPER_MODEL")
    if executable_env is not None or model_env is not None:
        if not executable_env or not model_env:
            raise _fail("local whisper runtime is unavailable")
        return WhisperRuntime(
            _regular_single_link(Path(executable_env), executable=True),
            _regular_single_link(Path(model_env)),
        )

    discovered = shutil.which("whisper-cli")
    if discovered is None:
        raise _fail("local whisper runtime is unavailable")
    try:
        executable = Path(discovered).resolve(strict=True)
    except OSError as exc:
        raise _fail("local whisper runtime is unavailable") from exc
    return WhisperRuntime(
        _regular_single_link(executable, executable=True),
        _regular_single_link(
            Path.home() / ".cache/hd-talking-head/models/ggml-large-v3-turbo.bin"
        ),
    )


def _descriptor_sha256(descriptor: int) -> tuple[str, int]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        raise _fail() from None
    return digest.hexdigest(), size


def _close_descriptor(descriptor: int) -> bool:
    """Close a pinned descriptor despite one injected pre/post-close failure."""
    for _attempt in range(2):
        try:
            os.close(descriptor)
            return True
        except BaseException:
            try:
                os.fstat(descriptor)
            except OSError as check:
                if check.errno == errno.EBADF:
                    return True
    return False


def _pin_local_media(
    path: Path, *, expected_sha256: str | None = None, expected_bytes: int | None = None,
) -> _PinnedInput:
    path = _absolute(path)
    current = Path(path.anchor)
    descriptor: int | None = None
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _fail()
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise _fail()
        sha256, size = _descriptor_sha256(descriptor)
        if (
            (expected_sha256 is not None and sha256 != expected_sha256)
            or (expected_bytes is not None and size != expected_bytes)
        ):
            raise _fail()
        pinned = _PinnedInput(
            path, descriptor, opened.st_dev, opened.st_ino, sha256, size,
        )
        _verify_pinned(pinned)
        descriptor = None
        return pinned
    except (OSError, ValueError, KeyboardInterrupt):
        raise _fail() from None
    finally:
        if descriptor is not None and not _close_descriptor(descriptor):
            raise _fail() from None


def _verify_pinned(pinned: _PinnedInput) -> None:
    try:
        opened = os.fstat(pinned.descriptor)
        named = os.lstat(pinned.path)
        sha256, size = _descriptor_sha256(pinned.descriptor)
    except BaseException:
        raise _fail() from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or opened.st_nlink != 1
        or named.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (pinned.device, pinned.inode)
        or (named.st_dev, named.st_ino) != (pinned.device, pinned.inode)
        or sha256 != pinned.sha256
        or size != pinned.size
    ):
        raise _fail()


def _validate_local_media(path: Path) -> Path:
    pinned = _pin_local_media(path)
    if not _close_descriptor(pinned.descriptor):
        raise _fail() from None
    return pinned.path


def _pin_job_input(job: JobState, key: str) -> _PinnedInput:
    try:
        record = job.inputs[key]
        if type(record) is not dict or set(record) != {"path", "sha256", "bytes"}:
            raise _fail()
        relative = record["path"]
        sha256 = record["sha256"]
        size = record["bytes"]
        if (
            not isinstance(relative, str)
            or not relative
            or "\x00" in relative
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or type(size) is not int
            or size < 0
        ):
            raise _fail()
        path = job.root.joinpath(*relative.split("/"))
    except (KeyError, TypeError, ValueError):
        raise _fail() from None
    return _pin_local_media(path, expected_sha256=sha256, expected_bytes=size)


def _ensure_output_directory(directory: Path) -> None:
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    current = Path(directory.anchor)
    try:
        for part in directory.parts[1:]:
            current /= part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise _fail()
        if not stat.S_ISDIR(os.lstat(directory).st_mode):
            raise _fail()
    except (OSError, ValueError) as exc:
        raise _fail() from exc


def _run(
    command: list[str], *, pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=pass_fds,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise _fail() from None
    if result.returncode != 0:
        raise _fail()
    return result


def _validate_wav(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            if (
                handle.getnchannels() != 1
                or handle.getframerate() != 16000
                or handle.getsampwidth() != 2
                or handle.getcomptype() != "NONE"
                or handle.getnframes() <= 0
            ):
                raise _fail("invalid local transcription audio")
            duration = handle.getnframes() / handle.getframerate()
    except (OSError, EOFError, wave.Error) as exc:
        raise _fail("invalid local transcription audio") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise _fail("invalid local transcription audio")
    return duration


def _fsync_file(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except BaseException:
        raise _fail() from None
    failure: BaseException | None = None
    try:
        os.fsync(descriptor)
    except BaseException as exc:
        failure = exc
    if failure is not None or not _close_descriptor(descriptor):
        raise _fail() from None


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except BaseException:
        raise _fail() from None
    failure: BaseException | None = None
    try:
        os.fsync(descriptor)
    except BaseException as exc:
        failure = exc
    if failure is not None or not _close_descriptor(descriptor):
        raise _fail() from None


def _create_pinned_output(path: Path) -> _PinnedOutput:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(path), os.O_RDWR | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise _fail()
        return _PinnedOutput(path, descriptor, opened.st_dev, opened.st_ino)
    except BaseException as failure:
        if descriptor is not None:
            _close_descriptor(descriptor)
        _raise_public_failure(failure)


def _output_matches(output: _PinnedOutput, path: Path) -> bool:
    try:
        opened = os.fstat(output.descriptor)
        named = os.lstat(path)
    except BaseException:
        return False
    return (
        stat.S_ISREG(opened.st_mode)
        and stat.S_ISREG(named.st_mode)
        and opened.st_nlink == 1
        and named.st_nlink == 1
        and (opened.st_dev, opened.st_ino) == (output.device, output.inode)
        and (named.st_dev, named.st_ino) == (output.device, output.inode)
    )


def _cleanup_pinned_output(output: _PinnedOutput, paths: tuple[Path, ...]) -> bool:
    failed = False
    directories: set[Path] = set()
    for path in paths:
        directories.add(path.parent)
        if not _output_matches(output, path):
            continue
        quarantine = path.parent / (
            f".{path.name}.cleanup.{secrets.token_hex(16)}.stage"
        )
        try:
            sha256, size = _digest_descriptor(output.descriptor)
            record = _GenerationEntry(output.device, output.inode, sha256, size)
            quarantine.mkdir(mode=0o700)
            _move_owned(path, quarantine / path.name, record)
            _unlink_owned(quarantine / path.name, record)
            os.rmdir(quarantine)
        except BaseException:
            failed = True
            try:
                os.rmdir(quarantine)
            except BaseException:
                pass
    if not _close_descriptor(output.descriptor):
        failed = True
    for directory in directories:
        try:
            _fsync_directory(directory)
        except BaseException:
            failed = True
    return not failed


def _close_pinned_output(output: _PinnedOutput) -> bool:
    return _close_descriptor(output.descriptor)


def _raise_public_failure(failure: BaseException) -> None:
    if isinstance(failure, TranscriptionError):
        raise _fail(str(failure)) from None
    if isinstance(failure, (OSError, KeyboardInterrupt)):
        raise _fail() from None
    raise failure


def _extract_pcm16k_pinned(video: _PinnedInput, wav: Path) -> None:
    wav = _absolute(wav)
    _ensure_output_directory(wav.parent)
    if wav.exists() or wav.is_symlink():
        raise _fail()
    partial = wav.parent / f".{wav.name}.{secrets.token_hex(16)}.partial"
    output = _create_pinned_output(partial)
    try:
        _verify_pinned(video)
        os.lseek(video.descriptor, 0, os.SEEK_SET)
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror",
            "-y", "-i", f"/dev/fd/{video.descriptor}", "-map", "0:a:0", "-vn", "-ac", "1",
            "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", str(partial),
        ], pass_fds=(video.descriptor,))
        _verify_pinned(video)
        if not _output_matches(output, partial):
            raise _fail()
        _validate_wav(partial)
        os.fsync(output.descriptor)
        os.replace(partial, wav)
        if not _output_matches(output, wav):
            raise _fail()
        _fsync_directory(wav.parent)
        _validate_wav(wav)
    except BaseException as failure:
        _cleanup_pinned_output(output, (partial, wav))
        _raise_public_failure(failure)
    if not _close_pinned_output(output):
        raise _fail() from None


def extract_pcm16k(video: Path, wav: Path) -> None:
    """Decode the complete source audio to mono 16 kHz PCM s16le WAV."""
    pinned = _pin_local_media(video)
    failure: BaseException | None = None
    try:
        _extract_pcm16k_pinned(pinned, wav)
    except BaseException as exc:
        failure = exc
    closed = _close_descriptor(pinned.descriptor)
    if failure is not None:
        raise failure
    if not closed:
        raise _fail() from None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _positive_report_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _fail("invalid inspect report")
    try:
        number = float(value)
    except OverflowError:
        raise _fail("invalid inspect report") from None
    if not math.isfinite(number) or number <= 0:
        raise _fail("invalid inspect report")
    return number


def _inspect_report_record(job: JobState) -> dict[str, Any]:
    inspect = job.stages.get("inspect")
    if type(inspect) is not dict or inspect.get("status") != "approved":
        raise _fail("invalid inspect report")
    artifacts = inspect.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != 1:
        raise _fail("invalid inspect report")
    record = artifacts[0]
    if (
        type(record) is not dict
        or set(record) != {"path", "sha256", "bytes"}
        or record.get("path") != "01-inspect/report.json"
        or not isinstance(record.get("sha256"), str)
        or _SHA256_RE.fullmatch(record["sha256"]) is None
        or isinstance(record.get("bytes"), bool)
        or not isinstance(record.get("bytes"), int)
        or record["bytes"] <= 0
    ):
        raise _fail("invalid inspect report")
    return record


def _inspect_audio_duration(
    job: JobState, pinned: _PinnedInput, record: dict[str, Any],
) -> float:
    try:
        if pinned.size != record["bytes"]:
            raise _fail("invalid inspect report")
        _verify_pinned(pinned)
        payload = json.loads(
            _read_descriptor_text(pinned.descriptor),
            object_pairs_hook=_strict_object,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
        )
        if type(payload) is not dict or set(payload) != {
            "version", "streams", "video", "audio", "script",
        }:
            raise _fail("invalid inspect report")
        video = payload["video"]
        audio = payload["audio"]
        script = payload["script"]
        streams = payload["streams"]
        if (
            payload["version"] != 1
            or type(payload["version"]) is not int
            or type(streams) is not dict
            or set(streams) != {"video", "audio"}
            or any(type(streams[key]) is not int or streams[key] != 1 for key in streams)
            or type(video) is not dict
            or set(video) != {
                "path", "sha256", "bytes", "codec", "duration",
                "fps", "width", "height", "sample_aspect_ratio",
                "display_aspect_ratio",
            }
            or type(audio) is not dict
            or set(audio) != {
                "codec", "duration", "sample_rate", "channels",
            }
            or type(script) is not dict
            or set(script) != {"path", "sha256", "bytes"}
        ):
            raise _fail("invalid inspect report")
        if (
            any(
                type(video[key]) is not type(job.inputs.get("video", {}).get(key))
                or video[key] != job.inputs.get("video", {}).get(key)
                for key in ("path", "sha256", "bytes")
            )
            or any(
                type(script[key]) is not type(job.inputs.get("script", {}).get(key))
                or script[key] != job.inputs.get("script", {}).get(key)
                for key in ("path", "sha256", "bytes")
            )
            or not isinstance(video["codec"], str)
            or not video["codec"]
            or not isinstance(audio["codec"], str)
            or not audio["codec"]
            or not isinstance(video["sample_aspect_ratio"], str)
            or not video["sample_aspect_ratio"]
            or not isinstance(video["display_aspect_ratio"], str)
            or not video["display_aspect_ratio"]
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (
                    video["width"], video["height"],
                    audio["sample_rate"], audio["channels"],
                )
            )
        ):
            raise _fail("invalid inspect report")
        _positive_report_number(video["duration"])
        _positive_report_number(video["fps"])
        duration = _positive_report_number(audio["duration"])
        _verify_pinned(pinned)
        return duration
    except (
        json.JSONDecodeError, InvalidOperation, KeyError, TranscriptionError,
        TypeError, ValueError, OverflowError,
    ):
        raise _fail("invalid inspect report") from None


def _milliseconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise _fail("invalid whisper word timestamps")
    if isinstance(value, Decimal) and not value.is_finite():
        raise _fail("invalid whisper word timestamps")
    try:
        result = float(value)
    except OverflowError:
        raise _fail("invalid whisper word timestamps") from None
    if not math.isfinite(result) or result < 0:
        raise _fail("invalid whisper word timestamps")
    return result / 1000.0


def parse_words_json(source: str, *, media_duration: float) -> list[Word]:
    """Strictly parse whisper.cpp full JSON into ordered word-like tokens."""
    if isinstance(media_duration, bool) or not isinstance(media_duration, (int, float)):
        raise _fail("invalid transcription media duration")
    boundary = float(media_duration)
    if not math.isfinite(boundary) or boundary <= 0:
        raise _fail("invalid transcription media duration")
    try:
        payload = json.loads(
            source,
            object_pairs_hook=_strict_object,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, InvalidOperation, TypeError, ValueError):
        raise _fail("invalid whisper JSON") from None
    if type(payload) is not dict or type(payload.get("transcription")) is not list:
        raise _fail("invalid whisper JSON")

    words: list[Word] = []
    boundary_ms = Decimal(str(boundary)) * 1000
    boundary_token_ms = (
        boundary_ms / _WHISPER_TIMESTAMP_QUANTUM_MS
    ).to_integral_value(rounding=ROUND_HALF_UP) * _WHISPER_TIMESTAMP_QUANTUM_MS
    previous_start_ms: int | Decimal = 0
    previous_end_ms: int | Decimal = 0
    pending_text: list[str] = []
    pending_start_ms: int | float | Decimal | None = None
    tail_started = False
    for segment in payload["transcription"]:
        if type(segment) is not dict or type(segment.get("tokens")) is not list:
            raise _fail("invalid whisper JSON")
        for token in segment["tokens"]:
            if type(token) is not dict or not isinstance(token.get("text"), str):
                raise _fail("invalid whisper JSON")
            text = token["text"].strip()
            if _CONTROL_TOKEN.fullmatch(text):
                continue
            offsets = token.get("offsets")
            if type(offsets) is not dict or set(offsets) != {"from", "to"}:
                raise _fail("invalid whisper word timestamps")
            start_ms = offsets["from"]
            end_ms = offsets["to"]
            start = _milliseconds(start_ms)
            end = _milliseconds(end_ms)
            if (
                start_ms > end_ms
                or start_ms < previous_start_ms
                or end_ms < previous_end_ms
            ):
                raise _fail("invalid whisper word timestamps")
            if tail_started:
                if not text and start_ms != end_ms:
                    raise _fail("empty whisper word")
                previous_start_ms, previous_end_ms = start_ms, end_ms
                continue
            if not text:
                if end_ms > boundary_ms + 50:
                    raise _fail("invalid whisper word timestamps")
                if start_ms == end_ms:
                    previous_start_ms, previous_end_ms = start_ms, end_ms
                    continue
                raise _fail("empty whisper word")
            if start >= end:
                if start_ms == end_ms == boundary_token_ms:
                    if pending_text:
                        raise _fail("invalid whisper word timestamps")
                    previous_start_ms, previous_end_ms = start_ms, end_ms
                    continue
                if start_ms != end_ms:
                    raise _fail("invalid whisper word timestamps")
                if pending_start_ms is None:
                    pending_start_ms = start_ms
                elif start_ms != pending_start_ms:
                    raise _fail("invalid whisper word timestamps")
                pending_text.append(text)
                previous_start_ms, previous_end_ms = start_ms, end_ms
                continue
            if start_ms >= boundary_ms:
                if (
                    start_ms > boundary_ms + 50
                    or not words
                    or pending_text
                ):
                    raise _fail("invalid whisper word timestamps")
                tail_started = True
                previous_start_ms, previous_end_ms = start_ms, end_ms
                continue
            if end_ms > boundary_ms + 50:
                raise _fail("invalid whisper word timestamps")
            if pending_text:
                if pending_start_ms is None or start_ms < pending_start_ms:
                    raise _fail("invalid whisper word timestamps")
                text = "".join(pending_text) + text
                start = _milliseconds(pending_start_ms)
                pending_text.clear()
                pending_start_ms = None
            clipped_end = min(end, boundary)
            if start >= clipped_end:
                raise _fail("invalid whisper word timestamps")
            words.append(Word(text, start, clipped_end))
            previous_start_ms, previous_end_ms = start_ms, end_ms
    if pending_text:
        raise _fail("invalid whisper word timestamps")
    if not words:
        raise _fail("whisper produced no words")
    return words


def transcribe_words(
    runtime: WhisperRuntime, wav: Path, output_json: Path,
    *, model_input: _PinnedInput | None = None,
    source_media_duration: float | None = None,
    language: str = "zh",
    raw_output_callback: Callable[[bytes], None] | None = None,
) -> list[Word]:
    """Run whisper.cpp once in the explicit engine language; never translate.

    Existing A-roll callers retain Chinese. Reference callers must supply their
    selected engine code; no locale normalization or automatic language fallback.
    The installed engine remains responsible for supported-code validation.
    An explicit callback can retain verified native bytes before word parsing.
    """
    if not isinstance(language, str) or re.fullmatch(r"[a-z]{2,3}", language) is None:
        raise _fail("explicit whisper language code is required")
    owned_model: _PinnedInput | None = None
    wav_input: _PinnedInput | None = None
    result: list[Word] | None = None
    failure: BaseException | None = None
    generated: Path | None = None
    generated_output: _PinnedOutput | None = None
    try:
        executable = _regular_single_link(runtime.executable, executable=True)
        if model_input is None:
            owned_model = _pin_local_media(_regular_single_link(runtime.model))
            model_input = owned_model
        elif model_input.path != _absolute(runtime.model):
            raise _fail("local whisper runtime changed")
        _verify_pinned(model_input)
        wav_input = _pin_local_media(wav)
        os.lseek(wav_input.descriptor, 0, os.SEEK_SET)
        duration = _validate_wav(Path(f"/dev/fd/{wav_input.descriptor}"))
        parse_duration = duration
        if source_media_duration is not None:
            if (
                isinstance(source_media_duration, bool)
                or not isinstance(source_media_duration, (int, float))
            ):
                raise _fail("invalid transcription media duration")
            parse_duration = float(source_media_duration)
            if (
                not math.isfinite(parse_duration)
                or parse_duration <= 0
                or parse_duration > duration
            ):
                raise _fail("invalid transcription media duration")
        output_json = _absolute(output_json)
        _ensure_output_directory(output_json.parent)
        if output_json.suffix != ".json" or output_json.exists() or output_json.is_symlink():
            raise _fail()
        stem = output_json.parent / f".{output_json.stem}-{secrets.token_hex(16)}"
        generated = Path(str(stem) + ".json")
        generated_output = _create_pinned_output(generated)
        os.lseek(model_input.descriptor, 0, os.SEEK_SET)
        os.lseek(wav_input.descriptor, 0, os.SEEK_SET)
        _run([
            str(executable), "-m", f"/dev/fd/{model_input.descriptor}",
            "-f", f"/dev/fd/{wav_input.descriptor}",
            "-l", language, "-ojf", "-of", str(stem),
        ], pass_fds=(model_input.descriptor, wav_input.descriptor))
        _verify_pinned(model_input)
        _verify_pinned(wav_input)
        if not _output_matches(generated_output, generated):
            raise _fail("invalid whisper JSON")
        if raw_output_callback is not None:
            os.lseek(generated_output.descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(generated_output.descriptor), "rb") as stream:
                raw_source = stream.read()
            if raw_source:
                raw_output_callback(raw_source)
            _verify_pinned(model_input)
            _verify_pinned(wav_input)
            if not _output_matches(generated_output, generated):
                raise _fail("invalid whisper JSON")
        source = _read_descriptor_text(generated_output.descriptor)
        words = parse_words_json(source, media_duration=parse_duration)
        os.fsync(generated_output.descriptor)
        os.replace(generated, output_json)
        if not _output_matches(generated_output, output_json):
            raise _fail()
        _fsync_directory(output_json.parent)
        result = words
    except BaseException as exc:
        failure = exc
        if generated_output is not None and generated is not None:
            _cleanup_pinned_output(generated_output, (generated, output_json))
            generated_output = None
    closed = True
    for pinned in (wav_input, owned_model):
        if pinned is not None and not _close_descriptor(pinned.descriptor):
            closed = False
    if generated_output is not None and not _close_pinned_output(generated_output):
        closed = False
    if failure is not None:
        _raise_public_failure(failure)
    if not closed or result is None:
        raise _fail() from None
    return result


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return "".join(character for character in normalized if character.isalnum())


def script_coverage(script: str, words: list[Word]) -> float:
    """Return deterministic ordered-character coverage of the supplied script."""
    if not isinstance(script, str):
        raise _fail("invalid script text")
    expected = _normalize_text(script)
    if not expected:
        raise _fail("invalid script text")
    if not isinstance(words, list) or not words or any(not isinstance(word, Word) for word in words):
        raise _fail("invalid transcript words")
    previous_start = 0.0
    previous_end = 0.0
    for word in words:
        if not isinstance(word.text, str) or not word.text.strip():
            raise _fail("invalid transcript words")
        if (
            isinstance(word.start, bool)
            or isinstance(word.end, bool)
            or not isinstance(word.start, (int, float))
            or not isinstance(word.end, (int, float))
            or not math.isfinite(float(word.start))
            or not math.isfinite(float(word.end))
            or word.start < 0
            or word.start >= word.end
            or word.start < previous_start
            or word.end < previous_end
        ):
            raise _fail("invalid transcript words")
        previous_start, previous_end = float(word.start), float(word.end)
    actual = _normalize_text("".join(word.text for word in words))
    if not actual:
        raise _fail("invalid transcript words")
    matched = sum(
        block.size for block in SequenceMatcher(None, expected, actual, autojunk=False).get_matching_blocks()
    )
    coverage = matched / len(expected)
    if not math.isfinite(coverage) or not 0.0 <= coverage <= 1.0:
        raise _fail("invalid transcript coverage")
    return round(coverage, 6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_descriptor_text(descriptor: int) -> str:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return b"".join(chunks).decode("utf-8", errors="strict")
    except (OSError, UnicodeError):
        raise _fail("invalid script text") from None


def _read_pinned_script(pinned: _PinnedInput) -> str:
    _verify_pinned(pinned)
    source = _read_descriptor_text(pinned.descriptor)
    if not source.strip():
        raise _fail("invalid script text")
    _verify_pinned(pinned)
    return source


def _close_pinned_inputs(pinned_inputs: list[_PinnedInput]) -> bool:
    closed = True
    for pinned in reversed(pinned_inputs):
        if not _close_descriptor(pinned.descriptor):
            closed = False
    return closed


def _safe_model_sha(path: Path) -> str:
    try:
        model = _regular_single_link(path)
        return _sha256(model)
    except (OSError, TranscriptionError, ValueError):
        raise _fail("local whisper runtime changed") from None


def transcribe_job(
    job: JobState,
    *,
    video_use_result: Path | None = None,
    invocation: dict | None = None,
) -> Path | None:
    """Transcribe one approved inspection job or block on missing runtime."""
    if job.version == 2:
        from . import speech_edit_v2

        if video_use_result is None or invocation is None:
            raise speech_edit_v2.SpeechEditV2Error("video-use result and invocation evidence are required")
        return speech_edit_v2.prepare_transcription(
            job, video_use_result=video_use_result, invocation=invocation,
        )
    require_runnable(job, "speech_cleanup")
    try:
        runtime = discover_runtime()
    except TranscriptionError:
        block(job, "speech_cleanup", RUNTIME_REQUIRED_REASON, ai_attempts=0)
        return None
    except KeyboardInterrupt:
        raise _fail() from None

    pinned_inputs: list[_PinnedInput] = []
    result: Path | None = None
    failure: BaseException | None = None
    try:
        video = _pin_job_input(job, "video")
        pinned_inputs.append(video)
        script_input = _pin_job_input(job, "script")
        pinned_inputs.append(script_input)
        script = _read_pinned_script(script_input)
        inspect_record = _inspect_report_record(job)
        inspect_input = _pin_local_media(
            job.job_dir / inspect_record["path"],
            expected_sha256=inspect_record["sha256"],
            expected_bytes=inspect_record["bytes"],
        )
        pinned_inputs.append(inspect_input)
        source_media_duration = _inspect_audio_duration(
            job, inspect_input, inspect_record,
        )
        try:
            _verify_pinned(video)
            current_audio_duration = _media_profile(video)["audio"]["duration"]
            _verify_pinned(video)
        except InspectionError:
            raise _fail("invalid inspect report") from None
        if current_audio_duration != source_media_duration:
            raise _fail("invalid inspect report")
        model_sha256 = _safe_model_sha(runtime.model)
        model_input = _pin_local_media(
            runtime.model, expected_sha256=model_sha256,
        )
        pinned_inputs.append(model_input)
        expected_names = ("speech-16k.wav", "whisper.json", "report.json")
        generation = _new_generation(
            job.job_dir, "02-speech-cleanup", expected_names,
        )
        wav = generation / "speech-16k.wav"
        raw_json = generation / "whisper.json"
        report = generation / "report.json"
        try:
            _extract_pcm16k_pinned(video, wav)
            words = transcribe_words(
                runtime, wav, raw_json, model_input=model_input,
                source_media_duration=source_media_duration,
            )
            _verify_pinned(model_input)
            _verify_pinned(video)
            _verify_pinned(script_input)
            _verify_pinned(inspect_input)
            coverage = script_coverage(script, words)
            payload = {
                "version": 1,
                "runtime": {
                    "engine": "whisper.cpp",
                    "model_sha256": model_sha256,
                },
                "script": {
                    "sha256": script_input.sha256,
                    "bytes": script_input.size,
                    "coverage": coverage,
                },
                "transcript": {
                    "word_count": len(words),
                    "first": words[0].start,
                    "last": words[-1].end,
                    "words": [
                        {"text": word.text, "start": word.start, "end": word.end}
                        for word in words
                    ],
                },
            }
            _write_report(report, payload)
        except BaseException as primary:
            try:
                _discard_unpublished(generation)
            except BaseException:
                pass
            raise primary
        target = _publish_generation(
            job, "speech_cleanup", generation, "02-speech-cleanup",
            expected_names,
            lambda artifacts: mark_ready(job, "speech_cleanup", artifacts),
        )
        result = target / "report.json"
    except BaseException as exc:
        failure = exc

    closed = _close_pinned_inputs(pinned_inputs)
    if failure is not None:
        if isinstance(failure, GenerationRecoveryError):
            raise TranscriptionError(str(failure)) from None
        _raise_public_failure(failure)
    if not closed:
        raise _fail() from None
    return result

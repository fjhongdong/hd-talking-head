"""Strictly inspect and bind the source material for an HD workflow job."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import material_usage
from .state import JobState, mark_ready, require_runnable


SUBPROCESS_TIMEOUT_SECONDS = 120
_DURATION_TAG_RE = re.compile(
    r"^(?P<hours>[0-9]+):(?P<minutes>[0-5][0-9]):"
    r"(?P<seconds>[0-5][0-9](?:\.[0-9]+)?)$"
)


class InspectionError(RuntimeError):
    """A safe input-inspection failure."""


class GenerationRecoveryError(InspectionError):
    """A generation is safe, but automatic cleanup could not be completed."""


@dataclass
class _PinnedInput:
    path: Path
    descriptor: int
    device: int
    inode: int
    sha256: str
    size: int


@dataclass(frozen=True)
class _GenerationEntry:
    device: int
    inode: int
    sha256: str
    size: int


def _fail() -> InspectionError:
    return InspectionError("input inspection failed")


def _absolute(path: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else Path.cwd() / value


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _fail()
    except (OSError, ValueError) as exc:
        raise _fail() from exc


def _digest_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise _fail() from exc
    return digest.hexdigest(), size


def _pin_regular(path: Path) -> _PinnedInput:
    path = _absolute(path)
    _reject_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
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
        sha256, size = _digest_descriptor(descriptor)
        return _PinnedInput(
            path, descriptor, opened.st_dev, opened.st_ino, sha256, size,
        )
    except BaseException:
        if "descriptor" in locals():
            _close_descriptor(descriptor)
        raise


def _verify_pin(pinned: _PinnedInput) -> None:
    _reject_symlink_components(pinned.path)
    try:
        opened = os.fstat(pinned.descriptor)
        named = os.lstat(pinned.path)
    except OSError as exc:
        raise _fail() from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or opened.st_nlink != 1
        or named.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (pinned.device, pinned.inode)
        or (named.st_dev, named.st_ino) != (pinned.device, pinned.inode)
        or _digest_descriptor(pinned.descriptor) != (pinned.sha256, pinned.size)
    ):
        raise _fail()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def parse_probe_json(source: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            source, object_pairs_hook=_strict_object, parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _fail() from exc
    if type(payload) is not dict or set(payload) != {"streams", "format"}:
        raise _fail()
    if type(payload["streams"]) is not list or type(payload["format"]) is not dict:
        raise _fail()
    return payload


def _run_media(command: list[str], descriptor: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
            pass_fds=(descriptor,),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _fail() from exc
    if result.returncode != 0:
        raise _fail()
    return result.stdout


def _positive_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise _fail()
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise _fail() from exc
    if not math.isfinite(result) or result <= 0:
        raise _fail()
    return result


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        raise _fail()
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _fail() from exc
    if result <= 0 or str(result) != str(value):
        raise _fail()
    return result


def _fps(value: Any) -> float | int:
    if not isinstance(value, str) or value.count("/") != 1:
        raise _fail()
    numerator, denominator = value.split("/")
    rate = _positive_int(numerator) / _positive_int(denominator)
    if not math.isfinite(rate) or rate <= 0:
        raise _fail()
    return int(rate) if rate.is_integer() else rate


def _aspect_ratio(value: Any) -> tuple[int, int] | None:
    if value in (None, "N/A", "0:1"):
        return None
    if not isinstance(value, str) or value.count(":") != 1:
        raise _fail()
    numerator, denominator = value.split(":")
    left = _positive_int(numerator)
    right = _positive_int(denominator)
    divisor = math.gcd(left, right)
    return left // divisor, right // divisor


def _aspect_ratio_text(parts: tuple[int, int]) -> str:
    return f"{parts[0]}:{parts[1]}"


def _stream_duration(stream: dict[str, Any]) -> float:
    if "duration" in stream:
        return _positive_float(stream["duration"])
    if "duration_ts" in stream and "time_base" in stream:
        duration = _positive_int(stream.get("duration_ts")) * _fps(
            stream.get("time_base"),
        )
        return _positive_float(duration)
    tags = stream.get("tags")
    tagged = tags.get("DURATION") if type(tags) is dict else None
    match = _DURATION_TAG_RE.fullmatch(tagged) if isinstance(tagged, str) else None
    if match is None:
        raise _fail()
    duration = (
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + float(match.group("seconds"))
    )
    return _positive_float(duration)


def _media_profile(pinned: _PinnedInput) -> dict[str, Any]:
    descriptor_path = f"/dev/fd/{pinned.descriptor}"
    output = _run_media(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", descriptor_path,
        ],
        pinned.descriptor,
    )
    try:
        payload = parse_probe_json(output.decode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise _fail() from exc
    streams = payload["streams"]
    video_streams = [item for item in streams if type(item) is dict and item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if type(item) is dict and item.get("codec_type") == "audio"]
    if len(streams) != 2 or len(video_streams) != 1 or len(audio_streams) != 1:
        raise _fail()
    video = video_streams[0]
    audio = audio_streams[0]
    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    fps = _fps(video.get("r_frame_rate"))
    sample_aspect_ratio = _aspect_ratio(video.get("sample_aspect_ratio")) or (1, 1)
    display_aspect_ratio = _aspect_ratio(video.get("display_aspect_ratio"))
    if display_aspect_ratio is None:
        display_width = width * sample_aspect_ratio[0]
        display_height = height * sample_aspect_ratio[1]
        divisor = math.gcd(display_width, display_height)
        display_aspect_ratio = (
            display_width // divisor,
            display_height // divisor,
        )
    sample_rate = _positive_int(audio.get("sample_rate"))
    channels = _positive_int(audio.get("channels"))
    _positive_float(payload["format"].get("duration"))
    video_duration = _stream_duration(video)
    audio_duration = _stream_duration(audio)
    for kind, stream in (("v:0", video), ("a:0", audio)):
        if not isinstance(stream.get("codec_name"), str) or not stream["codec_name"]:
            raise _fail()
        _run_media(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-xerror", "-i", descriptor_path, "-map", f"0:{kind}",
                "-f", "null", "-",
            ],
            pinned.descriptor,
        )
    return {
        "streams": {"video": 1, "audio": 1},
        "video": {
            "codec": video["codec_name"], "width": width, "height": height,
            "sample_aspect_ratio": _aspect_ratio_text(sample_aspect_ratio),
            "display_aspect_ratio": _aspect_ratio_text(display_aspect_ratio),
            "fps": fps, "duration": video_duration,
        },
        "audio": {
            "codec": audio["codec_name"], "sample_rate": sample_rate,
            "channels": channels, "duration": audio_duration,
        },
    }


def _read_script(pinned: _PinnedInput) -> str:
    try:
        os.lseek(pinned.descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(pinned.descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        source = b"".join(chunks).decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise _fail() from exc
    if not source.strip():
        raise _fail()
    return source


def inspect_inputs(video: Path, script: Path) -> dict[str, Any]:
    """Validate, fully decode, and freeze one source video/script pair."""
    pins: list[_PinnedInput] = []
    report: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        video_pin = _pin_regular(video)
        pins.append(video_pin)
        script_pin = _pin_regular(script)
        pins.append(script_pin)
        _read_script(script_pin)
        profile = _media_profile(video_pin)
        _verify_pin(video_pin)
        _verify_pin(script_pin)
        profile["version"] = 1
        profile["video"].update(
            path=str(video_pin.path), sha256=video_pin.sha256, bytes=video_pin.size,
        )
        profile["script"] = {
            "path": str(script_pin.path), "sha256": script_pin.sha256,
            "bytes": script_pin.size,
        }
        report = profile
    except BaseException as exc:
        failure = exc
    close_failure = _close_pinned_inputs(tuple(reversed(pins)))
    if failure is not None:
        if isinstance(failure, InspectionError):
            raise InspectionError(str(failure)) from None
        raise _fail() from None
    if close_failure is not None or report is None:
        raise _fail() from None
    return report


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(
            str(directory),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except BaseException:
        raise _generation_error() from None
    failure: BaseException | None = None
    try:
        os.fsync(descriptor)
    except BaseException as exc:
        failure = exc
    close_failure = _close_descriptor(descriptor)
    if failure is not None or close_failure is not None:
        raise _generation_error() from None


def _generation_error() -> GenerationRecoveryError:
    return GenerationRecoveryError(
        "generation cleanup failed; manual recovery is required"
    )


def _descriptor_is_closed(descriptor: int) -> bool:
    try:
        os.fstat(descriptor)
    except OSError as exc:
        return exc.errno == errno.EBADF
    return False


def _close_descriptor(descriptor: int) -> BaseException | None:
    first_error: BaseException | None = None
    try:
        os.close(descriptor)
    except BaseException as exc:
        first_error = exc
        if not _descriptor_is_closed(descriptor):
            try:
                os.close(descriptor)
            except BaseException:
                pass
    return first_error


def _close_pinned_inputs(pins: tuple[_PinnedInput, ...]) -> BaseException | None:
    first_error: BaseException | None = None
    for pinned in pins:
        close_failure = _close_descriptor(pinned.descriptor)
        if first_error is None and close_failure is not None:
            first_error = close_failure
    return first_error


def _snapshot_file(path: Path) -> _GenerationEntry:
    descriptor: int | None = None
    failure: BaseException | None = None
    record: _GenerationEntry | None = None
    try:
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
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
            raise _generation_error()
        sha256, size = _digest_descriptor(descriptor)
        record = _GenerationEntry(opened.st_dev, opened.st_ino, sha256, size)
    except BaseException as exc:
        failure = exc
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if close_failure is not None:
        raise _generation_error() from None
    if failure is not None:
        if isinstance(failure, GenerationRecoveryError):
            raise failure
        raise _generation_error() from None
    if record is None:
        raise _generation_error()
    return record


def _unlink_owned(path: Path, expected: _GenerationEntry) -> None:
    descriptor: int | None = None
    failure: BaseException | None = None
    try:
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        sha256, size = _digest_descriptor(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (expected.device, expected.inode)
            or (named.st_dev, named.st_ino) != (expected.device, expected.inode)
            or sha256 != expected.sha256
            or size != expected.size
        ):
            raise _generation_error()
        try:
            os.unlink(path)
        except BaseException:
            try:
                os.lstat(path)
            except FileNotFoundError:
                pass
            else:
                raise
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (expected.device, expected.inode)
            or after.st_nlink != 0
        ):
            raise _generation_error()
        try:
            os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise _generation_error()
    except BaseException as exc:
        failure = exc
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if failure is not None or close_failure is not None:
        raise _generation_error() from None


def _copy_owned_reference(
    source_descriptor: int, recovery: Path, expected: _GenerationEntry,
) -> bool:
    descriptor: int | None = None
    identity: tuple[int, int] | None = None
    candidate_record: _GenerationEntry | None = None
    failure: BaseException | None = None
    try:
        descriptor = os.open(
            str(recovery), os.O_RDWR | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        opened = os.fstat(descriptor)
        named = os.lstat(recovery)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise _generation_error()
        identity = (opened.st_dev, opened.st_ino)
        os.lseek(source_descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short owned-reference write")
                view = view[written:]
        os.fsync(descriptor)
    except BaseException as exc:
        failure = exc
    if descriptor is not None and identity is not None:
        try:
            opened = os.fstat(descriptor)
            sha256, size = _digest_descriptor(descriptor)
            if (opened.st_dev, opened.st_ino) == identity:
                candidate_record = _GenerationEntry(
                    opened.st_dev, opened.st_ino, sha256, size,
                )
        except BaseException:
            candidate_record = None
    if failure is not None and candidate_record is not None:
        _discard_reference_candidate(recovery, candidate_record)
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if failure is not None:
        return False
    if candidate_record is None:
        return False
    if (
        close_failure is not None and descriptor is not None
        and not _descriptor_is_closed(descriptor)
    ):
        _discard_reference_candidate(recovery, candidate_record)
        return False
    try:
        recovery_record = _snapshot_file(recovery)
        if (
            recovery_record != candidate_record
            or recovery_record.device != identity[0]
            or recovery_record.inode != identity[1]
            or recovery_record.sha256 != expected.sha256
            or recovery_record.size != expected.size
        ):
            return False
        _fsync_directory(recovery.parent)
    except BaseException:
        _discard_reference_candidate(recovery, candidate_record)
        return False
    return True


def _discard_reference_candidate(
    candidate: Path, expected: _GenerationEntry,
) -> None:
    quarantine = candidate.parent / (
        f".{candidate.name}.cleanup.{secrets.token_hex(16)}.stage"
    )
    try:
        named = os.lstat(candidate)
        if (
            not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or (named.st_dev, named.st_ino) != (expected.device, expected.inode)
        ):
            return
        quarantine.mkdir(mode=0o700)
        moved = quarantine / candidate.name
        os.replace(candidate, moved)
        if _snapshot_file(moved) != expected:
            return
        _unlink_owned(moved, expected)
        os.rmdir(quarantine)
        _fsync_directory(candidate.parent)
    except BaseException:
        return


def _write_owned_reference(
    source_descriptor: int, source: Path, expected: _GenerationEntry,
) -> None:
    retained: Path | None = None
    for _attempt in range(3):
        candidate = source.parent / (
            f".{source.name}.owned.{secrets.token_hex(16)}."
            f"{expected.sha256}.{expected.size}.retained"
        )
        if _copy_owned_reference(source_descriptor, candidate, expected):
            retained = candidate
            break
    if retained is None:
        raise _generation_error() from None

    try:
        os.lstat(source)
    except FileNotFoundError:
        _copy_owned_reference(source_descriptor, source, expected)
    except OSError:
        pass


def _move_owned(
    source: Path, destination: Path, expected: _GenerationEntry,
) -> None:
    descriptor: int | None = None
    failure: BaseException | None = None
    completed = False
    try:
        descriptor = os.open(
            str(source), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(source)
        sha256, size = _digest_descriptor(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (expected.device, expected.inode)
            or (named.st_dev, named.st_ino) != (expected.device, expected.inode)
            or sha256 != expected.sha256
            or size != expected.size
        ):
            raise _generation_error()
        try:
            os.lstat(destination)
        except FileNotFoundError:
            pass
        else:
            raise _generation_error()
        try:
            os.replace(source, destination)
        except BaseException:
            pass
        try:
            os.lstat(source)
        except FileNotFoundError:
            source_absent = True
        else:
            source_absent = False
        try:
            destination_record = _snapshot_file(destination)
        except GenerationRecoveryError:
            destination_record = None
        completed = source_absent and destination_record == expected
        if not completed:
            try:
                source_record = _snapshot_file(source)
            except GenerationRecoveryError:
                source_record = None
            if source_record != expected:
                _write_owned_reference(descriptor, source, expected)
            raise _generation_error()
    except BaseException as exc:
        failure = exc
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if close_failure is not None:
        raise _generation_error() from None
    if failure is not None:
        raise _generation_error() from None
    if not completed:
        raise _generation_error()


def _snapshot_generation(
    directory: Path, expected_names: tuple[str, ...], *, allow_partial: bool = False,
) -> dict[str, _GenerationEntry]:
    try:
        directory_info = os.lstat(directory)
        if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
            raise _generation_error()
        actual_names = set(os.listdir(directory))
    except (OSError, ValueError) as exc:
        raise _generation_error() from exc
    expected = set(expected_names)
    if (allow_partial and not actual_names.issubset(expected)) or (
        not allow_partial and actual_names != expected
    ):
        raise _generation_error()
    records: dict[str, _GenerationEntry] = {}
    for name in expected_names:
        if name not in actual_names:
            continue
        candidate = directory / name
        records[name] = _snapshot_file(candidate)
    return records


def _verify_generation(
    directory: Path, records: dict[str, _GenerationEntry], *, allow_partial: bool = False,
) -> None:
    current = _snapshot_generation(
        directory, tuple(records), allow_partial=allow_partial,
    )
    if allow_partial:
        for name, entry in current.items():
            if entry != records[name]:
                raise _generation_error()
    elif current != records:
        raise _generation_error()


def _generation_state(
    directory: Path, records: dict[str, _GenerationEntry] | None,
) -> str:
    try:
        os.lstat(directory)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    if records is None:
        return "unknown"
    try:
        current = _snapshot_generation(directory, tuple(records), allow_partial=True)
    except GenerationRecoveryError:
        return "unknown"
    if current == records:
        return "complete"
    if all(entry == records[name] for name, entry in current.items()):
        return "partial"
    return "unknown"


def _records_payload(records: dict[str, _GenerationEntry] | None) -> Any:
    if records is None:
        return None
    return {
        name: {
            "device": entry.device, "inode": entry.inode,
            "sha256": entry.sha256, "bytes": entry.size,
        }
        for name, entry in sorted(records.items())
    }


def _records_from_payload(value: Any, expected_names: tuple[str, ...]) -> dict[str, _GenerationEntry] | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != set(expected_names):
        raise _generation_error()
    records: dict[str, _GenerationEntry] = {}
    for name in expected_names:
        entry = value[name]
        if type(entry) is not dict or set(entry) != {
            "device", "inode", "sha256", "bytes",
        }:
            raise _generation_error()
        if (
            type(entry["device"]) is not int or entry["device"] < 0
            or type(entry["inode"]) is not int or entry["inode"] < 0
            or type(entry["sha256"]) is not str
            or len(entry["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in entry["sha256"])
            or type(entry["bytes"]) is not int or entry["bytes"] < 0
        ):
            raise _generation_error()
        records[name] = _GenerationEntry(
            entry["device"], entry["inode"], entry["sha256"], entry["bytes"],
        )
    return records


def _marker_path(job_dir: Path, target_name: str) -> Path:
    return job_dir / f".{target_name}.generation-recovery.json"


def _write_marker(
    marker: Path, payload: dict[str, Any],
) -> _GenerationEntry:
    data = (
        json.dumps(payload, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    identity: tuple[int, int] | None = None
    record: _GenerationEntry | None = None
    failure: BaseException | None = None
    try:
        descriptor = os.open(
            str(marker), os.O_RDWR | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        opened = os.fstat(descriptor)
        identity = (opened.st_dev, opened.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short generation marker write")
            view = view[written:]
        os.fsync(descriptor)
        named = os.lstat(marker)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or identity != (named.st_dev, named.st_ino)
        ):
            raise _generation_error()
        sha256, size = _digest_descriptor(descriptor)
        record = _GenerationEntry(opened.st_dev, opened.st_ino, sha256, size)
        _fsync_directory(marker.parent)
    except BaseException as exc:
        failure = exc
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if failure is not None or close_failure is not None:
        if record is not None:
            try:
                _cleanup_marker(marker, record)
            except GenerationRecoveryError:
                pass
        raise _generation_error() from None
    if record is None:
        raise _generation_error()
    return record


def _commit_marker(
    marker: Path, expected: _GenerationEntry,
) -> _GenerationEntry:
    if _snapshot_file(marker) != expected:
        raise _generation_error()
    descriptor: int | None = None
    record: _GenerationEntry | None = None
    failure: BaseException | None = None
    try:
        descriptor = os.open(
            str(marker), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        named = os.lstat(marker)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (expected.device, expected.inode)
            or (named.st_dev, named.st_ino) != (expected.device, expected.inode)
        ):
            raise _generation_error()
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        source = b"".join(chunks)
        if hashlib.sha256(source).hexdigest() != expected.sha256:
            raise _generation_error()
        needle = b'"phase": 0'
        if source.count(needle) != 1:
            raise _generation_error()
        offset = source.index(needle) + len(needle) - 1
        if os.pwrite(descriptor, b"1", offset) != 1:
            raise OSError("short generation marker update")
        os.fsync(descriptor)
        sha256, size = _digest_descriptor(descriptor)
        record = _GenerationEntry(opened.st_dev, opened.st_ino, sha256, size)
        _fsync_directory(marker.parent)
    except BaseException as exc:
        failure = exc
    close_failure = (
        _close_descriptor(descriptor) if descriptor is not None else None
    )
    if failure is not None or close_failure is not None or record is None:
        raise _generation_error() from None
    return record


def _read_marker(marker: Path, target_name: str, expected_names: tuple[str, ...]) -> tuple[int, Path, Path | None, dict[str, _GenerationEntry], dict[str, _GenerationEntry] | None, _GenerationEntry]:
    marker_record = _snapshot_file(marker)
    try:
        source_bytes = marker.read_bytes()
        if (
            hashlib.sha256(source_bytes).hexdigest() != marker_record.sha256
            or len(source_bytes) != marker_record.size
            or _snapshot_file(marker) != marker_record
        ):
            raise _generation_error()
        source = source_bytes.decode("utf-8", errors="strict")
        payload = json.loads(
            source, object_pairs_hook=_strict_object, parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise _generation_error() from None
    if type(payload) is not dict or set(payload) != {
        "version", "phase", "target", "stage", "backup", "new", "old",
    }:
        raise _generation_error()
    if (
        type(payload["version"]) is not int or payload["version"] != 1
        or type(payload["phase"]) is not int or payload["phase"] not in {0, 1}
        or type(payload["target"]) is not str or payload["target"] != target_name
    ):
        raise _generation_error()
    token_prefix = f".{target_name}.generation."
    stage_name = payload["stage"]
    backup_name = payload["backup"]
    if (
        type(stage_name) is not str
        or not stage_name.startswith(token_prefix)
        or not stage_name.endswith(".stage")
        or "/" in stage_name
    ):
        raise _generation_error()
    token = stage_name[len(token_prefix):-len(".stage")]
    if (
        len(token) != 32
        or any(character not in "0123456789abcdef" for character in token)
    ):
        raise _generation_error()
    if backup_name is not None and backup_name != f"{token_prefix}{token}.backup":
        raise _generation_error()
    new_records = _records_from_payload(payload["new"], expected_names)
    old_records = _records_from_payload(payload["old"], expected_names)
    if new_records is None or ((backup_name is None) != (old_records is None)):
        raise _generation_error()
    return (
        payload["phase"], marker.parent / stage_name,
        marker.parent / backup_name if backup_name is not None else None,
        new_records, old_records, marker_record,
    )


def _cleanup_generation(
    directory: Path, records: dict[str, _GenerationEntry],
) -> None:
    state = _generation_state(directory, records)
    if state == "absent":
        return
    if state not in {"complete", "partial"}:
        raise _generation_error()
    failed = False
    for name in records:
        candidate = directory / name
        quarantine = directory.parent / (
            f"{directory.name}.cleanup.{secrets.token_hex(16)}.stage"
        )
        quarantine_created = False
        try:
            os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError:
            failed = True
            continue
        try:
            current = _snapshot_generation(directory, tuple(records), allow_partial=True)
            if name not in current or current[name] != records[name]:
                failed = True
                continue
            quarantine.mkdir(mode=0o700)
            quarantine_created = True
            _move_owned(candidate, quarantine / name, records[name])
            moved = _snapshot_generation(quarantine, (name,))
            if moved[name] != records[name]:
                if not candidate.exists() and not candidate.is_symlink():
                    os.replace(quarantine / name, candidate)
                failed = True
                continue
            try:
                _unlink_owned(quarantine / name, records[name])
            except GenerationRecoveryError:
                try:
                    remaining = _snapshot_generation(quarantine, (name,))
                    if (
                        remaining[name] == records[name]
                        and not candidate.exists()
                        and not candidate.is_symlink()
                    ):
                        os.replace(quarantine / name, candidate)
                except GenerationRecoveryError:
                    pass
                failed = True
        except BaseException:
            try:
                os.lstat(candidate)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            failed = True
        finally:
            if quarantine_created:
                try:
                    os.rmdir(quarantine)
                except FileNotFoundError:
                    pass
                except OSError:
                    failed = True
            try:
                _fsync_directory(directory.parent)
            except BaseException:
                failed = True
    try:
        os.rmdir(directory)
    except FileNotFoundError:
        pass
    except OSError:
        failed = True
    try:
        _fsync_directory(directory.parent)
    except BaseException:
        failed = True
    if failed:
        raise _generation_error() from None


def _cleanup_marker(marker: Path, expected: _GenerationEntry) -> None:
    quarantine = marker.parent / (
        f"{marker.name}.cleanup.{secrets.token_hex(16)}.stage"
    )
    quarantine_created = False
    failed = False
    try:
        if _snapshot_file(marker) != expected:
            raise _generation_error()
        quarantine.mkdir(mode=0o700)
        quarantine_created = True
        _move_owned(marker, quarantine / marker.name, expected)
        if _snapshot_file(quarantine / marker.name) != expected:
            if not marker.exists() and not marker.is_symlink():
                os.replace(quarantine / marker.name, marker)
            raise _generation_error()
        try:
            _unlink_owned(quarantine / marker.name, expected)
        except GenerationRecoveryError:
            try:
                if (
                    _snapshot_file(quarantine / marker.name) == expected
                    and not marker.exists()
                    and not marker.is_symlink()
                ):
                    os.replace(quarantine / marker.name, marker)
            except GenerationRecoveryError:
                pass
            raise
    except BaseException:
        failed = True
    finally:
        if quarantine_created:
            try:
                os.rmdir(quarantine)
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
    try:
        _fsync_directory(marker.parent)
    except BaseException:
        failed = True
    if failed:
        raise _generation_error() from None


def _restore_generation(
    target: Path, stage: Path, backup: Path | None,
    new_records: dict[str, _GenerationEntry],
    old_records: dict[str, _GenerationEntry] | None,
) -> None:
    target_state = _generation_state(target, new_records)
    stage_state = _generation_state(stage, new_records)
    backup_state = _generation_state(backup, old_records) if backup is not None else "absent"
    old_target_state = _generation_state(target, old_records)
    try:
        if target_state == "complete":
            if stage_state != "absent":
                raise _generation_error()
            try:
                os.replace(target, stage)
            except BaseException:
                if _generation_state(stage, new_records) != "complete":
                    raise
        elif target_state not in {"absent"} and old_target_state != "complete":
            raise _generation_error()

        if old_records is not None:
            if old_target_state != "complete":
                if backup is None or backup_state != "complete":
                    raise _generation_error()
                try:
                    os.replace(backup, target)
                except BaseException:
                    if _generation_state(target, old_records) != "complete":
                        raise
            _verify_generation(target, old_records)
        elif _generation_state(target, new_records) != "absent":
            raise _generation_error()
        _fsync_directory(target.parent)
    except BaseException:
        raise _generation_error() from None


def _recover_generation(
    job_dir: Path, target_name: str, expected_names: tuple[str, ...],
) -> None:
    marker = _marker_path(job_dir, target_name)
    try:
        os.lstat(marker)
    except FileNotFoundError:
        return
    except OSError:
        raise _generation_error() from None
    phase, stage, backup, new_records, old_records, marker_record = _read_marker(
        marker, target_name, expected_names,
    )
    target = job_dir / target_name
    if phase == 0:
        _restore_generation(target, stage, backup, new_records, old_records)
    else:
        _verify_generation(target, new_records)
        if _generation_state(stage, new_records) != "absent":
            raise _generation_error()
    cleanup_failure = False
    cleanup_entries = (
        ((stage, new_records), (backup, old_records))
        if phase == 0 else ((backup, old_records),)
    )
    for directory, records in cleanup_entries:
        if directory is None or records is None:
            continue
        try:
            _cleanup_generation(directory, records)
        except GenerationRecoveryError:
            cleanup_failure = True
    if cleanup_failure:
        raise _generation_error() from None
    _cleanup_marker(marker, marker_record)


def _new_generation(
    job_dir: Path, target_name: str, expected_names: tuple[str, ...],
) -> Path:
    _recover_generation(job_dir, target_name, expected_names)
    token = secrets.token_hex(16)
    stage = job_dir / f".{target_name}.generation.{token}.stage"
    created = False
    try:
        stage.mkdir(mode=0o700)
        created = True
        _fsync_directory(job_dir)
    except BaseException:
        if created:
            try:
                os.rmdir(stage)
            except OSError:
                pass
        raise _generation_error() from None
    return stage


def _discard_unpublished(directory: Path) -> None:
    try:
        names = tuple(os.listdir(directory))
    except FileNotFoundError:
        return
    except OSError:
        raise _generation_error() from None
    try:
        records = _snapshot_generation(directory, names)
        _cleanup_generation(directory, records)
    except GenerationRecoveryError:
        raise


def _publish_generation(
    job: JobState, stage_id: str, stage: Path, target_name: str,
    expected_names: tuple[str, ...], ready: Callable[[list[Path]], None],
) -> Path:
    target = job.job_dir / target_name
    new_records = _snapshot_generation(stage, expected_names)
    try:
        old_records = _snapshot_generation(target, expected_names)
    except GenerationRecoveryError:
        try:
            os.lstat(target)
        except FileNotFoundError:
            old_records = None
        else:
            stage_state = job.stages[stage_id]
            if not (
                stage_state["status"] in {"pending", "needs_revision"}
                and stage_state["artifacts"] == []
                and stage_state["lineage"] == []
            ):
                raise
            # The workspace initializer creates empty stage directories. Only
            # an actually empty, regular directory is safe to replace here.
            _snapshot_generation(target, ())
            try:
                target.rmdir()
                _fsync_directory(job.job_dir)
            except OSError as exc:
                raise _generation_error() from exc
            old_records = None
    token = stage.name.removesuffix(".stage").rsplit(".", 1)[-1]
    backup = (
        job.job_dir / f".{target_name}.generation.{token}.backup"
        if old_records is not None else None
    )
    marker = _marker_path(job.job_dir, target_name)
    marker_payload = {
        "version": 1, "phase": 0, "target": target_name, "stage": stage.name,
        "backup": backup.name if backup is not None else None,
        "new": _records_payload(new_records), "old": _records_payload(old_records),
    }
    failure: BaseException | None = None
    marker_record: _GenerationEntry | None = None
    try:
        marker_record = _write_marker(marker, marker_payload)
        if backup is not None:
            try:
                os.replace(target, backup)
            except BaseException:
                if _generation_state(backup, old_records) != "complete":
                    raise
            _verify_generation(backup, old_records)
        try:
            os.replace(stage, target)
        except BaseException:
            if _generation_state(target, new_records) != "complete":
                raise
        _verify_generation(target, new_records)
        _fsync_directory(job.job_dir)
        ready([target / name for name in expected_names])
    except BaseException as exc:
        failure = exc

    if failure is not None and job.stages[stage_id]["status"] != "ready_for_review":
        try:
            _restore_generation(target, stage, backup, new_records, old_records)
        except GenerationRecoveryError:
            raise _generation_error() from None
        cleanup_failure = False
        for directory, records in ((stage, new_records), (backup, old_records)):
            if directory is None or records is None:
                continue
            try:
                _cleanup_generation(directory, records)
            except GenerationRecoveryError:
                cleanup_failure = True
        if cleanup_failure:
            raise _generation_error() from None
        if marker_record is not None:
            _cleanup_marker(marker, marker_record)
        if isinstance(failure, (OSError, KeyboardInterrupt)):
            raise _generation_error() from None
        raise failure

    if marker_record is None:
        raise _generation_error()
    marker_record = _commit_marker(marker, marker_record)

    cleanup_failure = False
    if backup is not None and old_records is not None:
        try:
            _cleanup_generation(backup, old_records)
        except GenerationRecoveryError:
            cleanup_failure = True
    if cleanup_failure:
        raise _generation_error() from None
    try:
        _cleanup_marker(marker, marker_record)
    except GenerationRecoveryError:
        cleanup_failure = True
    if cleanup_failure:
        raise _generation_error() from None
    if failure is not None:
        if isinstance(failure, (OSError, KeyboardInterrupt)):
            raise _generation_error() from None
        raise failure
    return target


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    directory = path.parent
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if not stat.S_ISDIR(os.lstat(directory).st_mode):
            raise _fail()
    if path.exists() or path.is_symlink():
        raise _fail()
    stage = directory / f".report.{secrets.token_hex(16)}.stage"
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    stage_record: _GenerationEntry | None = None
    try:
        descriptor = os.open(
            str(stage), os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise _fail()
            view = view[written:]
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        sha256, size = _digest_descriptor(descriptor)
        stage_record = _GenerationEntry(opened.st_dev, opened.st_ino, sha256, size)
        os.close(descriptor)
        descriptor = None
        os.replace(stage, path)
        _fsync_directory(directory)
    except BaseException as failure:
        if descriptor is not None and stage_record is None:
            try:
                opened = os.fstat(descriptor)
                sha256, size = _digest_descriptor(descriptor)
                stage_record = _GenerationEntry(
                    opened.st_dev, opened.st_ino, sha256, size,
                )
            except BaseException:
                pass
        if stage_record is not None:
            for candidate in (stage, path):
                quarantine = directory / (
                    f".{stage.name}.cleanup.{secrets.token_hex(16)}.stage"
                )
                try:
                    os.lstat(candidate)
                    quarantine.mkdir(mode=0o700)
                    _move_owned(candidate, quarantine / stage.name, stage_record)
                    _unlink_owned(quarantine / stage.name, stage_record)
                    os.rmdir(quarantine)
                    break
                except BaseException:
                    try:
                        os.rmdir(quarantine)
                    except BaseException:
                        pass
        if descriptor is not None:
            _close_descriptor(descriptor)
        try:
            _fsync_directory(directory)
        except BaseException:
            pass
        if isinstance(failure, InspectionError):
            raise failure
        if isinstance(failure, (OSError, KeyboardInterrupt)):
            raise _fail() from None
        raise failure


def inspect_job(job: JobState) -> Path:
    """Inspect a job, publish its report, and submit it for human review."""
    require_runnable(job, "inspect")
    video = job.root / job.inputs["video"]["path"]
    script = job.root / job.inputs["script"]["path"]
    report = inspect_inputs(video, script)
    report["video"]["path"] = job.inputs["video"]["path"]
    report["script"]["path"] = job.inputs["script"]["path"]
    artifact_names = ("report.json",)
    expected_names = (
        (*artifact_names, "material-usage.json") if job.version == 2 else artifact_names
    )
    stage = _new_generation(job.job_dir, "01-inspect", expected_names)
    try:
        _write_report(stage / "report.json", report)
        if job.version == 2:
            material_usage.write_staged_receipt(
                job,
                "inspect",
                stage,
                job.job_dir / "01-inspect",
                artifact_names,
                producer="edit.hd.tools.inspect_inputs",
                producer_version="1",
                stage_input_records=material_usage.current_stage_input_records(
                    job, "inspect"
                ),
                references=[],
            )
    except BaseException as failure:
        try:
            _discard_unpublished(stage)
        except GenerationRecoveryError:
            raise _generation_error() from None
        raise failure
    target = _publish_generation(
        job, "inspect", stage, "01-inspect", expected_names,
        lambda artifacts: mark_ready(job, "inspect", artifacts),
    )
    return target / "report.json"

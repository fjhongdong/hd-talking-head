"""Read-only reference-caption parsing and lookup; never edits the A-roll timeline."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid
import fcntl
from typing import Any, TypedDict

REFERENCE_REPORT_LIMIT = 16 * 1024 * 1024


def _validate_asr_report(report, identity):
    keys = set(identity) | {"cues", "raw_output_sha256", "method", "precision", "source_approval"}
    if (not isinstance(report, dict) or set(report) != keys
            or any(report.get(k) != v for k, v in identity.items())
            or report.get("method") != "local_whisper_cpp" or not isinstance(report.get("precision"), str)
            or report.get("precision") not in {"word", "segment"}
            or report.get("source_approval") != "not_asserted"
            or not isinstance(report.get("raw_output_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", report["raw_output_sha256"]) is None):
        raise ValueError("reference transcript cache identity is invalid")
    _checked_cues(report["cues"])


class CaptionCue(TypedDict):
    start: float
    end: float
    text: str


class SearchHit(CaptionCue):
    precision: str
    precise_cut_eligible: bool


def _open_reference_directory(job, material_id, *, create=True):
    target = job.job_dir.absolute() / "cache" / "reference-transcripts" / material_id
    directory = os.open(target.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(target.parts[1:]):
            if create and index >= len(target.parts) - 4:
                try:
                    os.mkdir(part, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory, target
    except BaseException:
        os.close(directory)
        raise


def _read_reference_bytes(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("invalid reference cache file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("reference cache exceeds limit")
    return data, hashlib.sha256(data).hexdigest()


def _read_reference_json(directory, name, limit):
    from . import contract_artifacts

    data, digest = _read_reference_bytes(directory, name, limit)
    return json.loads(data, object_pairs_hook=contract_artifacts._strict_object,
                      parse_constant=contract_artifacts._reject_nonfinite), digest


def _save_raw_reference(job, material_id, identity, key, data, recheck):
    recheck()
    saved = _publish_reference_report(job, material_id, data)
    recheck()
    _publish_reference_report(job, material_id,
                              {**identity, "raw_output_sha256": saved["sha256"]},
                              filename="raw-request-" + key + ".json")
    recheck()


def _read_raw_reference(directory, key, identity):
    binding, _ = _read_reference_json(directory, "raw-request-" + key + ".json", REFERENCE_REPORT_LIMIT)
    if (not isinstance(binding, dict) or set(binding) != set(identity) | {"raw_output_sha256"}
            or any(binding.get(k) != v for k, v in identity.items())
            or not isinstance(binding.get("raw_output_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", binding["raw_output_sha256"]) is None):
        raise ValueError("raw reference request identity is invalid")
    digest = binding["raw_output_sha256"]
    try:
        _, actual = _read_reference_bytes(directory, digest + ".json", REFERENCE_REPORT_LIMIT)
    except FileNotFoundError as exc:
        raise ValueError("raw reference output is missing") from exc
    if actual != digest:
        raise ValueError("raw reference output checksum differs")
    return digest


def cache_reference_transcript(job_dir: Path, material_id: str, *, tracks: list[dict[str, Any]], language: str) -> dict[str, str]:
    """Prefer explicit captions; otherwise single-flight the approved local ASR."""
    from . import state, reference_asr

    if not isinstance(tracks, list):
        raise ValueError("explicit caption tracks list required")
    if tracks:
        return cache_material_captions(job_dir, material_id, tracks=tracks, language=language)
    job = state.load_job(Path(job_dir))
    with reference_asr._approved_material_request(job_dir, material_id, language=language) as request:
        identity, pins, recheck = request
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                        allow_nan=False).encode("utf-8")).hexdigest()
        directory, target = _open_reference_directory(job, material_id)
        lock = None
        try:
            lock_name = "request-" + key + ".lock"
            lock_flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            try:
                lock = os.open(lock_name, lock_flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            except FileExistsError:
                lock = os.open(lock_name, lock_flags, dir_fd=directory)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("invalid reference request lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            recheck()
            pointer_name = "request-" + key + ".json"
            try:
                pointer, _ = _read_reference_json(directory, pointer_name, 4096)
                found = True
            except FileNotFoundError:
                pointer = None
                found = False
            if found:
                report, digest = _read_asr_report(directory, pointer, key, identity)
                recheck()
                return {"path": str(target / (digest + ".json")), "sha256": digest}
            try:
                raw_digest = _read_raw_reference(directory, key, identity)
            except FileNotFoundError:
                raw_digest = None
            if raw_digest is not None:
                recheck()
                raise ValueError(f"saved native reference result requires explicit import_saved_reference_segments: "
                                 f"{target / (raw_digest + '.json')} (SHA-256 {raw_digest})")
            recognition = reference_asr._recognize_pinned_reference(
                *pins, language=language,
                raw_output_callback=lambda data: _save_raw_reference(job, material_id, identity, key, data, recheck),
            )
            report = {**identity, **recognition, "method": "local_whisper_cpp", "precision": "word",
                      "source_approval": "not_asserted"}
            _validate_asr_report(report, identity)
            recheck()
            if _read_raw_reference(directory, key, identity) != report["raw_output_sha256"]:
                raise ValueError("reference transcript raw output differs")
            saved = _publish_reference_report(job, material_id, report)
            recheck()
            _publish_reference_report(job, material_id, {"version": 1, "request_sha256": key,
                                      "report_sha256": saved["sha256"]}, filename=pointer_name)
            recheck()
            return saved
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)


def import_saved_reference_segments(
    job_dir: Path, material_id: str, *, raw_result: Path, expected_sha256: str, language: str,
) -> dict[str, str]:
    """Explicitly import saved native segments; never run or retry recognition."""
    from . import state, reference_asr, contract_artifacts, transcribe

    if not isinstance(raw_result, Path) or not raw_result.is_absolute():
        raise ValueError("raw reference result must be an absolute path")
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("invalid raw reference result checksum")
    job = state.load_job(Path(job_dir))
    if ".." in raw_result.parts or job.job_dir.absolute() not in raw_result.parents:
        raise ValueError("raw reference result must be inside the current Job")

    with reference_asr._approved_material_request(job_dir, material_id, language=language) as request:
        identity, pins, recheck = request
        raw_pin = transcribe._pin_local_media(raw_result, expected_sha256=expected_sha256)
        try:
            if raw_pin.size > REFERENCE_REPORT_LIMIT:
                raise ValueError("raw reference result exceeds limit")

            def recheck_inputs():
                recheck()
                transcribe._verify_pinned(raw_pin)

            payload = json.loads(
                transcribe._read_descriptor_text(raw_pin.descriptor),
                object_pairs_hook=contract_artifacts._strict_object,
                parse_constant=contract_artifacts._reject_nonfinite,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
                raise ValueError("invalid raw reference result")
            if payload["result"].get("language") != language:
                raise ValueError("raw reference result language differs")
            segments = payload.get("transcription")
            if not isinstance(segments, list) or not segments:
                raise ValueError("raw reference result has no transcription segments")
            cues = []
            for segment in segments:
                if not isinstance(segment, dict):
                    raise ValueError("invalid raw reference segment")
                offsets, text = segment.get("offsets"), segment.get("text")
                if (not isinstance(offsets, dict) or set(offsets) != {"from", "to"}
                        or type(offsets["from"]) is not int or type(offsets["to"]) is not int
                        or offsets["from"] < 0 or offsets["to"] <= offsets["from"]
                        or not isinstance(text, str) or not text.strip()):
                    raise ValueError("invalid raw reference segment")
                cues.append({"start": offsets["from"] / 1000, "end": offsets["to"] / 1000, "text": text})
            _checked_cues(cues)
            duration = float(transcribe._run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 f"/dev/fd/{pins[0].descriptor}"],
                pass_fds=(pins[0].descriptor,),
            ).stdout.decode("ascii").strip())
            if not math.isfinite(duration) or duration <= 0 or any(cue["end"] > duration for cue in cues):
                raise ValueError("reference segment exceeds source audio duration")
            recheck_inputs()

            key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                            allow_nan=False).encode("utf-8")).hexdigest()
            directory, target = _open_reference_directory(job, material_id)
            lock = None
            try:
                lock_name = "request-" + key + ".lock"
                lock_flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
                try:
                    lock = os.open(lock_name, lock_flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
                except FileExistsError:
                    lock = os.open(lock_name, lock_flags, dir_fd=directory)
                info = os.fstat(lock)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("invalid reference request lock")
                fcntl.flock(lock, fcntl.LOCK_EX)
                recheck_inputs()
                pointer_name = "request-" + key + ".json"
                try:
                    pointer, _ = _read_reference_json(directory, pointer_name, 4096)
                    found = True
                except FileNotFoundError:
                    found = False
                if found:
                    existing, digest = _read_asr_report(directory, pointer, key, identity)
                    if (existing["precision"] != "segment"
                            or existing["raw_output_sha256"] != expected_sha256
                            or existing["cues"] != cues):
                        raise ValueError("existing reference cache conflicts with imported result")
                    recheck_inputs()
                    return {"path": str(target / (digest + ".json")), "sha256": digest}
                _save_raw_reference(job, material_id, identity, key,
                                    transcribe._read_descriptor_text(raw_pin.descriptor).encode("utf-8"),
                                    recheck_inputs)
                report = {**identity, "cues": cues, "raw_output_sha256": expected_sha256,
                          "method": "local_whisper_cpp", "precision": "segment",
                          "source_approval": "not_asserted"}
                _validate_asr_report(report, identity)
                saved = _publish_reference_report(job, material_id, report)
                recheck_inputs()
                _publish_reference_report(job, material_id, {"version": 1, "request_sha256": key,
                                          "report_sha256": saved["sha256"]}, filename=pointer_name)
                recheck_inputs()
                return saved
            finally:
                if lock is not None:
                    os.close(lock)
                os.close(directory)
        finally:
            if not transcribe._close_descriptor(raw_pin.descriptor):
                raise ValueError("raw reference result cleanup failed")


def _read_asr_report(directory, pointer, key, identity):
    if (not isinstance(pointer, dict) or set(pointer) != {"version", "request_sha256", "report_sha256"}
            or type(pointer["version"]) is not int or pointer["version"] != 1
            or pointer["request_sha256"] != key or not isinstance(pointer["report_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", pointer["report_sha256"]) is None):
        raise ValueError("reference request cache identity is invalid")
    digest = pointer["report_sha256"]
    report, actual = _read_reference_json(directory, digest + ".json", REFERENCE_REPORT_LIMIT)
    if actual != digest:
        raise ValueError("reference transcript cache identity is invalid")
    _validate_asr_report(report, identity)
    if _read_raw_reference(directory, key, identity) != report["raw_output_sha256"]:
        raise ValueError("reference transcript raw output differs")
    return report, digest


def read_reference_transcript(job_dir: Path, material_id: str, *, tracks: list[dict[str, Any]], language: str):
    """Read current captions or an existing approved-runtime ASR cache; never infer."""
    from . import state, startup, reference_asr

    if not isinstance(tracks, list):
        raise ValueError("explicit caption tracks list required")
    job = state.load_job(Path(job_dir))
    if tracks:
        startup.require_startup(job)
        report = read_material_captions(job.root, material_id, tracks=tracks, language=language)
        startup.require_startup(state.load_job(Path(job_dir)))
        return report
    with reference_asr._approved_material_request(job_dir, material_id, language=language) as request:
        identity, _, recheck = request
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                        allow_nan=False).encode("utf-8")).hexdigest()
        directory, _ = _open_reference_directory(job, material_id, create=False)
        try:
            pointer, _ = _read_reference_json(directory, "request-" + key + ".json", 4096)
            report, _ = _read_asr_report(directory, pointer, key, identity)
            recheck()
            return report
        finally:
            os.close(directory)


def cache_material_captions(
    job_dir: Path, material_id: str, *, tracks: list[dict[str, Any]], language: str,
) -> dict[str, str]:
    """Persist a freshly validated report, partitioned by material and content."""
    from . import state, startup

    if not isinstance(material_id, str) or re.fullmatch(r"material-[0-9]{4,}", material_id) is None:
        raise ValueError("invalid material ID")
    job = state.load_job(Path(job_dir))
    startup.require_startup(job)
    report = read_material_captions(job.root, material_id, tracks=tracks, language=language)
    return _publish_reference_report(job, material_id, report)


def _publish_reference_report(job, material_id, report, *, filename=None):
    if filename is not None and re.fullmatch(r"(?:raw-)?request-[0-9a-f]{64}\.json", filename) is None:
        raise ValueError("invalid reference pointer filename")
    directory, target_dir = _open_reference_directory(job, material_id)
    temporary = None
    try:
        candidate_name = "." + uuid.uuid4().hex + ".tmp"
        fd = os.open(candidate_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        temporary = candidate_name
        checksum = hashlib.sha256()
        raw = isinstance(report, bytes)
        written = 0 if raw else 1  # Include the terminating newline for reports.
        limit = 4096 if filename is not None and not filename.startswith("raw-") else REFERENCE_REPORT_LIMIT
        with os.fdopen(fd, "wb") as stream:
            encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False)
            pieces = (report,) if raw else encoder.iterencode(report)
            for piece in pieces:
                for offset in range(0, len(piece), 16384):
                    chunk = piece[offset:offset + 16384]
                    if not raw:
                        chunk = chunk.encode("utf-8")
                    written += len(chunk)
                    if written > limit:
                        raise ValueError("reference cache exceeds limit")
                    stream.write(chunk)
                    checksum.update(chunk)
            if not raw:
                stream.write(b"\n")
                checksum.update(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        digest = checksum.hexdigest()
        name = filename or digest + ".json"
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("reference cache conflicts with validated content")
                candidate_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(candidate_fd, "rb") as candidate:
                    while True:
                        chunk = candidate.read(65536)
                        if stream.read(65536) != chunk:
                            raise ValueError("reference cache conflicts with validated content")
                        if not chunk:
                            break
        return {"path": str(target_dir / name), "sha256": digest}
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def read_track_selection(path: Path) -> list[dict[str, Any]]:
    from . import contract_artifacts

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("track selection must be a regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("track selection exceeds 64 KiB")
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=contract_artifacts._strict_object,
                             parse_constant=contract_artifacts._reject_nonfinite)
        if not isinstance(payload, dict) or set(payload) != {"tracks"} or not isinstance(payload["tracks"], list):
            raise ValueError("reference selection requires a tracks list")
        return payload["tracks"]
    finally:
        os.close(descriptor)


def _open_caption(workspace: Path, relative: Path) -> int:
    """Open every directory component without following symlinks."""
    absolute = workspace.resolve() / relative
    directory = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    finally:
        os.close(directory)


def read_material_captions(
    workspace: Path, material_id: str, *, tracks: list[dict[str, Any]], language: str,
) -> dict[str, Any]:
    """Read explicitly associated indexed captions; association is not source approval.

    The caller supplies the reviewed media-to-caption association. Both IDs are
    resolved through the canonical active-material index, never by filename.
    This performs no writes, uploads or speech recognition.
    """
    from . import user_materials

    workspace = Path(workspace)
    selected = select_caption_track(tracks, language=language)
    if set(selected) != {"language", "material_id", "format"}:
        raise ValueError("caption association requires language, material_id and format")
    if any(not isinstance(selected[key], str) or not selected[key].strip() for key in selected):
        raise ValueError("caption association values must be nonempty strings")
    if selected["format"] not in {"srt", "vtt"}:
        raise ValueError("unsupported caption format")
    media = copy.deepcopy(user_materials.require_active_material(workspace, material_id))
    caption = copy.deepcopy(user_materials.require_active_material(workspace, selected["material_id"]))
    relative = Path(caption["imported_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("caption must be inside the workspace")
    path = workspace / relative
    if path.resolve() != workspace.resolve() / relative:
        raise ValueError("caption symlink is not a stable input")
    descriptor = _open_caption(workspace, relative)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise ValueError("caption file is not a bounded regular input")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        if len(data) != caption["size_bytes"] or hashlib.sha256(data).hexdigest() != caption["sha256"]:
            raise ValueError("caption bytes differ from the indexed material")
        cues = parse_caption_text(data.decode("utf-8"), format=selected["format"])
        if not os.path.samestat(info, path.stat()):
            raise ValueError("caption file was replaced during read")
        if (user_materials.require_active_material(workspace, material_id) != media or
                user_materials.require_active_material(workspace, selected["material_id"]) != caption):
            raise ValueError("reference material changed during read")
    finally:
        os.close(descriptor)
    return {"version": 1, "material": media, "caption_material": caption,
            "language": language, "method": "existing_captions", "precision": "segment",
            "source_approval": "not_asserted", "cues": cues}


def _timestamp(value: str, *, format: str) -> float:
    separator = "," if format == "srt" else "."
    pattern = r"(\d{2,}):(\d{2}):(\d{2})" + re.escape(separator) + r"(\d{3})"
    if format == "vtt" and value.count(":") == 1:
        value = "00:" + value
    match = re.fullmatch(pattern, value)
    if match is None:
        raise ValueError("invalid caption timestamp")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError("invalid caption timestamp")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _checked_cues(cues: list[CaptionCue]) -> list[CaptionCue]:
    if not isinstance(cues, list) or not cues:
        raise ValueError("reference captions are empty")
    previous_start = -1
    for cue in cues:
        if not isinstance(cue, dict) or set(cue) != {"start", "end", "text"}:
            raise ValueError("invalid reference cue")
        start, end = cue["start"], cue["end"]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)):
            raise ValueError("invalid reference cue time")
        if start < 0 or start < previous_start or end <= start:
            raise ValueError("invalid reference cue interval")
        if not isinstance(cue["text"], str) or not cue["text"].strip():
            raise ValueError("empty reference cue text")
        previous_start = start
    return cues


def parse_caption_text(text: str, *, format: str) -> list[CaptionCue]:
    """Parse SRT or ordinary WebVTT cues, preserving repetitions and overlaps.

    Unsupported metadata/timestamp mappings fail explicitly; no clock conversion
    or HTML rendering is performed. Caption markup remains literal source text.
    """
    if not isinstance(text, str) or format not in {"srt", "vtt"}:
        raise ValueError("unsupported caption input")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n[ \t]*\n", normalized)
    if format == "vtt":
        if not blocks or blocks[0] != "WEBVTT":
            raise ValueError("unsupported WebVTT header or timestamp mapping")
        blocks = blocks[1:]
    cues: list[CaptionCue] = []
    for block in blocks:
        lines = block.splitlines()
        if format == "vtt" and lines and (lines[0] == "NOTE" or lines[0].startswith("NOTE ")):
            continue
        if lines and "-->" not in lines[0]:
            if format == "srt" and not lines[0].isdigit():
                raise ValueError("invalid SRT cue identifier")
            lines = lines[1:]
        if len(lines) < 2:
            raise ValueError("incomplete caption cue")
        timing = re.fullmatch(r"(\S+)\s+-->\s+(\S+)(?:[ \t]+(.*))?", lines[0])
        if timing is None or (format == "srt" and timing[3]):
            raise ValueError("invalid caption timing line")
        cues.append({"start": _timestamp(timing[1], format=format),
                     "end": _timestamp(timing[2], format=format),
                     "text": "\n".join(lines[1:])})
    return copy.deepcopy(_checked_cues(cues))


def select_caption_track(tracks: list[dict[str, Any]], *, language: str) -> dict[str, Any]:
    """Require an exact, unique language selection, never directory-order fallback."""
    if not isinstance(language, str) or not language.strip() or not isinstance(tracks, list):
        raise ValueError("explicit caption language required")
    if any(not isinstance(track, dict) for track in tracks):
        raise ValueError("invalid caption track")
    matches = [track for track in tracks if track.get("language") == language]
    if len(matches) != 1:
        raise ValueError("caption language is unavailable or ambiguous")
    return copy.deepcopy(matches[0])


def search_cues(cues: list[CaptionCue], query: str, *, precision: str) -> list[SearchHit]:
    """Literal case-insensitive lookup, not semantic retrieval or a cut approval."""
    _checked_cues(cues)
    if precision not in {"whole", "segment", "word"}:
        raise ValueError("unknown reference time precision")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("nonempty search query required")
    return [{**copy.deepcopy(cue), "precision": precision, "precise_cut_eligible": False}
            for cue in cues if query.casefold() in cue["text"].casefold()]

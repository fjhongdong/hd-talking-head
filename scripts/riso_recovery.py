"""Keep a verified native source available across interrupted Riso exports."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time


class RecoveryBlocked(RuntimeError):
    """An old attempt could not yet be proven safe to replace."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def input_scope(input_sha, job_dir):
    if input_sha is None:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", input_sha) or not job_dir:
        raise ValueError("Invalid Riso recovery scope")
    job = Path(job_dir).resolve(strict=True)
    info = job.stat()
    return {"job": str(job), "job_identity": [info.st_dev, info.st_ino], "input_sha256": input_sha}


def checkpoint_path(parent, input_sha, job_dir, runtime, brief_sha, entry_sha):
    scope = input_scope(input_sha, job_dir)
    if scope is None:
        return None
    key = hashlib.sha256(canonical({
        "schema": 1, **scope, "brief_sha256": brief_sha,
        "entrypoint_sha256": entry_sha, "runtime_identity": runtime["identity"],
        "implementation_identity": runtime["implementation_identity"],
    })).hexdigest()
    return parent / "checkpoints" / f"{key}.json"


def acquire_claim(parent, input_sha, job_dir, deadline):
    scope = input_scope(input_sha, job_dir)
    if scope is None:
        return None, None
    directory = parent / "claims"
    directory.mkdir(mode=0o700, exist_ok=True)
    key = hashlib.sha256(canonical(scope)).hexdigest()
    descriptor = os.open(directory / f"{key}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor, directory / f"{key}.pending"
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RecoveryBlocked("同一输入的上一次 Riso 调用仍在运行或收尾，本次没有重渲。")
                time.sleep(0.05)
    except BaseException:
        os.close(descriptor)
        raise


def write_state(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_state(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        payload = stream.read(4097)
    if len(payload) > 4096:
        raise ValueError("Riso ownership record is oversized")
    value = json.loads(payload)
    if type(value) is not dict:
        raise ValueError("Riso ownership record has the wrong shape")
    return value


def media_identity(path, *, durable=False):
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError("Invalid Riso native recovery file")
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(source.fileno())
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise ValueError("Riso native recovery file changed while being verified")
        if durable:
            os.fsync(source.fileno())
    return digest.hexdigest(), before.st_size


def load_checkpoint(checkpoint, parent, composition, expected_frames):
    if checkpoint is None:
        return None
    try:
        descriptor = os.open(checkpoint, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as receipt:
        payload = receipt.read(4097)
    if len(payload) > 4096:
        raise ValueError("Riso native recovery receipt is oversized")
    record = json.loads(payload)
    if (type(record) is not dict or set(record) != {"key", "work", "native_source"}
            or record["key"] != checkpoint.stem or type(record["work"]) is not str
            or not re.fullmatch(r"native-[a-zA-Z0-9_-]+", record["work"])):
        raise ValueError("Riso native recovery receipt changed")
    source = record["native_source"]
    if (type(source) is not dict or set(source) != {"invocation_id", "sha256", "bytes", "frames", "input_range"}
            or type(source["invocation_id"]) is not str
            or not re.fullmatch(r"process-[0-9a-f]{32}", source["invocation_id"])
            or type(source["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            or type(source["bytes"]) is not int or source["bytes"] <= 0
            or type(source["frames"]) is not int or source["frames"] != expected_frames
            or source["input_range"] not in {"full", "limited"}):
        raise ValueError("Invalid Riso native recovery source")
    media = parent / record["work"] / "project" / "renders" / f"{composition}.mp4"
    if media.resolve(strict=True) != media or media_identity(media) != (source["sha256"], source["bytes"]):
        raise ValueError("Riso native recovery video changed")
    return media, source


def save_checkpoint(checkpoint, work, source):
    if checkpoint is None:
        return
    checkpoint.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".native-", dir=checkpoint.parent)
    try:
        with os.fdopen(descriptor, "wb") as receipt:
            receipt.write(canonical({"key": checkpoint.stem, "work": work.name, "native_source": source}))
            receipt.flush()
            os.fsync(receipt.fileno())
        # The executor's component lock serializes same-input attempts. An
        # unexpected second writer still cannot replace the first receipt.
        os.link(temporary, checkpoint)
        fd = os.open(checkpoint.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.unlink(temporary)

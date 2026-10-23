"""Execute exact validator snapshots with bounded output and owned process cleanup."""
import hashlib
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import tempfile
import time


def _snapshot(source, destination, expected):
    if type(expected) is not str or len(expected) != 64:
        raise ValueError("validator identity is required")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as incoming, destination.open("xb") as outgoing:
        if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
            raise ValueError("validator source must be regular")
        digest = hashlib.sha256()
        for block in iter(lambda: incoming.read(65536), b""):
            digest.update(block)
            outgoing.write(block)
    if digest.hexdigest() != expected:
        raise ValueError("validator identity mismatch")
    destination.chmod(0o500)


def validate_bytes(payload, *, node_executable, node_sha256, renderer, renderer_sha256):
    """Hashes are caller-approved identities, not proof of a vendor or user approval."""
    if type(payload) is not bytes or len(payload) > 256 * 1024:
        raise ValueError("validator input limit exceeded")
    with tempfile.TemporaryDirectory(prefix="semantic-validator-") as directory:
        root = Path(directory)
        node, script = root / "node", root / "renderer.cjs"
        _snapshot(node_executable, node, node_sha256)
        _snapshot(renderer, script, renderer_sha256)
        with tempfile.TemporaryFile() as incoming:
            incoming.write(payload)
            incoming.seek(0)
            process = subprocess.Popen([str(node), str(script), "--validate"], stdin=incoming,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                outputs = {process.stdout: bytearray(), process.stderr: bytearray()}
                total = 0
                deadline = time.monotonic() + 10
                with selectors.DefaultSelector() as selector:
                    for stream in outputs:
                        selector.register(stream, selectors.EVENT_READ)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ValueError("validator timed out")
                        for key, _ in selector.select(remaining):
                            block = os.read(key.fileobj.fileno(), 65536)
                            total += len(block)
                            if total > 1024 * 1024:
                                raise ValueError("validator output limit exceeded")
                            if block:
                                outputs[key.fileobj].extend(block)
                            else:
                                selector.unregister(key.fileobj)
                try:
                    code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as exc:
                    raise ValueError("validator timed out") from exc
                if code:
                    raise ValueError("validator failed: " + outputs[process.stderr][-1000:].decode("utf-8", errors="replace"))
                return bytes(outputs[process.stdout])
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()

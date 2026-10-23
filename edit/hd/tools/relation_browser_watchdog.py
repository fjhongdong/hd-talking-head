"""Supervise detached relation-render browser groups for one bundle lifetime."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time


_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_PROOF = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REQUEST_BYTES = 4096
_HANDSHAKE_SECONDS = 5.0


def _process_start_identity(pid: int) -> str | None:
    """Return a stable-enough local identity used to avoid PID-reuse kills."""
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        fields = proc_stat.read_text(encoding="utf-8").split()
        if len(fields) > 21:
            return "proc:" + fields[21]
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            check=False, capture_output=True, text=True, timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return "ps:" + value if result.returncode == 0 and value else None


def _session_leader(pid: int, pgid: int) -> bool:
    try:
        return pid > 1 and pgid == pid and os.getpgid(pid) == pid and os.getsid(pid) == pid
    except (OSError, ProcessLookupError):
        return False


def _ensure_independent_session() -> None:
    pid = os.getpid()
    if os.getsid(0) != pid:
        os.setsid()
    if os.getsid(0) != pid or os.getpgrp() != pid:
        raise RuntimeError("watchdog must be an independent session leader")


def _validate_parent(value: str) -> Path:
    parent = Path(value)
    if not parent.is_absolute() or any(item.is_symlink() for item in (parent, *parent.parents)):
        raise ValueError("staging parent must be an absolute non-symlink path")
    parent = parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("staging parent must be a directory")
    return parent


def _expected_proof(token: str, purpose: str, pid: int, nonce: str) -> str:
    message = f"{purpose}:{pid}:{nonce}".encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def _peer_pid(client: socket.socket) -> int:
    """Read the connected Unix peer PID from the kernel, or refuse the platform."""
    if hasattr(socket, "SO_PEERCRED"):
        credentials = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        if len(credentials) != 12:
            raise OSError("invalid Unix peer credentials")
        return struct.unpack("3i", credentials)[0]
    if hasattr(os, "uname") and os.uname().sysname == "Darwin":
        credentials = client.getsockopt(0, 2, struct.calcsize("i"))
        if len(credentials) != struct.calcsize("i"):
            raise OSError("invalid Unix peer credentials")
        return struct.unpack("i", credentials)[0]
    raise RuntimeError("Unix peer PID credentials are unsupported")


def _group_states(pgid: int) -> list[str]:
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,pgid=,stat="],
            check=False, capture_output=True, text=True, timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["unknown"]
    states = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[1].isdecimal() and int(fields[1]) == pgid:
            states.append(fields[2])
    return states


def _group_has_live_members(pgid: int) -> bool:
    return any(not state.startswith("Z") for state in _group_states(pgid))


def _terminate_registered(groups: dict[int, str]) -> None:
    signaled = []
    failures = []
    for pid, identity in tuple(groups.items()):
        current_identity = _process_start_identity(pid)
        if current_identity is not None and current_identity != identity:
            if _group_has_live_members(pid):
                failures.append(f"browser group identity changed: {pid}")
            continue
        if current_identity is None and not _group_states(pid):
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
            signaled.append(pid)
        except ProcessLookupError:
            pass
        except OSError as exc:
            failures.append(f"browser group kill failed: {pid}: {exc}")
    deadline = time.monotonic() + 3.0
    while signaled and time.monotonic() < deadline:
        signaled = [pid for pid in signaled if _group_has_live_members(pid)]
        if signaled:
            time.sleep(0.02)
    if signaled:
        failures.append(f"browser groups did not terminate: {signaled}")
    if failures:
        raise RuntimeError("; ".join(failures))


def _cleanup_paths(*paths: Path) -> None:
    failures = []
    for path in paths:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures.append(f"{path}: {exc}")
        if path.exists():
            failures.append(f"{path}: still exists")
    if failures:
        raise RuntimeError("cleanup failed: " + "; ".join(failures))


def supervise(heartbeat_fd: int, parent: Path) -> int:
    _ensure_independent_session()
    os.set_inheritable(heartbeat_fd, False)
    os.set_blocking(heartbeat_fd, False)
    root = Path(tempfile.mkdtemp(prefix="relation-browser-", dir=parent))
    control_root = Path(tempfile.mkdtemp(prefix="rbw-"))
    socket_path = control_root / "watchdog.sock"
    token = secrets.token_hex(32)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    selector = selectors.DefaultSelector()
    clients: dict[socket.socket, tuple[bytearray, float, int]] = {}
    registered: dict[int, str] = {}
    nonces: set[str] = set()
    try:
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        listener.listen()
        listener.setblocking(False)
        selector.register(heartbeat_fd, selectors.EVENT_READ, "heartbeat")
        selector.register(listener, selectors.EVENT_READ, "listener")
        print(json.dumps({
            "root": str(root), "socket": str(socket_path), "token": token,
        }, separators=(",", ":")), flush=True)

        aborting = False
        while not aborting:
            now = time.monotonic()
            for client, (_, deadline, _) in tuple(clients.items()):
                if now >= deadline:
                    selector.unregister(client)
                    client.close()
                    clients.pop(client, None)
            for key, _ in selector.select(0.1):
                if key.data == "heartbeat":
                    try:
                        alive = os.read(heartbeat_fd, 4096)
                    except BlockingIOError:
                        alive = b"alive"
                    if not alive:
                        aborting = True
                        break
                if key.data == "listener":
                    try:
                        client, _ = listener.accept()
                    except BlockingIOError:
                        continue
                    client.setblocking(False)
                    clients[client] = (
                        bytearray(), time.monotonic() + _HANDSHAKE_SECONDS,
                        _peer_pid(client),
                    )
                    selector.register(client, selectors.EVENT_READ, "client")
                    continue
                if key.data != "client":
                    continue
                client = key.fileobj
                buffer, deadline, peer_pid = clients[client]
                try:
                    chunk = client.recv(_MAX_REQUEST_BYTES + 1 - len(buffer))
                except BlockingIOError:
                    continue
                if chunk:
                    buffer.extend(chunk)
                if not chunk or len(buffer) > _MAX_REQUEST_BYTES or b"\n" in buffer:
                    selector.unregister(client)
                    clients.pop(client, None)
                    try:
                        if not chunk or len(buffer) > _MAX_REQUEST_BYTES:
                            raise ValueError("invalid handshake length")
                        line, trailing = bytes(buffer).split(b"\n", 1)
                        request = json.loads(line)
                        if trailing or type(request) is not dict or set(request) != {"pid", "pgid", "nonce", "proof"}:
                            raise ValueError("invalid handshake shape")
                        pid, pgid = request["pid"], request["pgid"]
                        nonce, proof = request["nonce"], request["proof"]
                        if (type(pid) is not int or type(pgid) is not int
                                or type(nonce) is not str or _NONCE.fullmatch(nonce) is None
                                or nonce in nonces or type(proof) is not str
                                or _PROOF.fullmatch(proof) is None
                                or pid != peer_pid
                                or not hmac.compare_digest(
                                    proof, _expected_proof(token, "register", pid, nonce)
                                ) or not _session_leader(pid, pgid)):
                            raise ValueError("invalid browser registration")
                        identity = _process_start_identity(pid)
                        if identity is None:
                            raise ValueError("browser identity unavailable")
                        registered[pid] = identity
                        nonces.add(nonce)
                        reply = {
                            "ack": pid,
                            "proof": _expected_proof(token, "ack", pid, nonce),
                        }
                        client.sendall((json.dumps(reply, separators=(",", ":")) + "\n").encode())
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass
                    finally:
                        client.close()
        return 0
    finally:
        for client in tuple(clients):
            try:
                selector.unregister(client)
            except (KeyError, ValueError):
                pass
            client.close()
        failures = []
        try:
            _terminate_registered(registered)
        except RuntimeError as exc:
            failures.append(str(exc))
        try:
            selector.close()
        finally:
            listener.close()
            try:
                os.close(heartbeat_fd)
            except OSError:
                pass
            try:
                _cleanup_paths(root, control_root)
            except RuntimeError as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("; ".join(failures))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heartbeat-fd", required=True, type=int)
    parser.add_argument("--parent", required=True)
    args = parser.parse_args(argv)
    try:
        return supervise(args.heartbeat_fd, _validate_parent(args.parent))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"relation browser watchdog failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

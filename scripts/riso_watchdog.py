"""Invocation-scoped Riso browser supervision and interrupted-attempt cleanup."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

from riso_chrome_launcher import process_identity
from riso_recovery import RecoveryBlocked, read_state, write_state


CLEANUP_SECONDS = 6
SLOT = re.compile(r"command-[1-9][0-9]?|(?:qa|render)-(?:command|browser|ffmpeg|ffprobe)")


def inherited_owner_fd(value):
    if value is None:
        return None
    if not value.isascii() or not value.isdecimal() or int(value) < 3:
        raise ValueError("Invalid Riso executor lifetime descriptor")
    descriptor = int(value)
    if (not stat.S_ISFIFO(os.fstat(descriptor).st_mode)
            or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
        raise ValueError("Riso executor lifetime descriptor is not a read-only pipe")
    os.set_inheritable(descriptor, False)
    return descriptor


def actor_path(work, slot):
    return work / f"{slot}.actor.json"


def file_identity(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("Invalid Riso phase log ownership")
    return [metadata.st_dev, metadata.st_ino]


def still_owned(actor):
    if (type(actor.get("pid")) is not int or actor["pid"] <= 1
            or type(actor.get("group")) is not int or actor["group"] <= 1
            or type(actor.get("started")) is not str
            or any(type(actor.get(key)) is not str or not Path(actor[key]).is_absolute()
                   for key in ("launcher", "command"))):
        raise ValueError("Invalid Riso process registration")
    current = process_identity(actor["pid"])
    if current is None or current["started"] != actor["started"]:
        return False
    if (current["uid"] != os.getuid() or current["group"] != actor["group"]
            or current["command"] not in (actor["launcher"], actor["command"])):
        raise RuntimeError("Riso process ownership could not be confirmed")
    return True


def signal_process(pid, sig):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def stop_actor(actor, deadline):
    term_at = None
    killed = False
    while still_owned(actor):
        now = time.monotonic()
        if now >= deadline:
            raise TimeoutError("Riso process did not exit")
        if term_at is None:
            signal_process(actor["pid"], signal.SIGTERM)
            term_at = now
        elif not killed and now >= term_at + 0.2:
            signal_process(actor["pid"], signal.SIGKILL)
            killed = True
        time.sleep(0.05)


def log_writers(log_path, log_identity, deadline, only_pid=None):
    if file_identity(log_path) != log_identity:
        raise RuntimeError("Riso phase log changed before Crashpad cleanup")
    command = ["/usr/sbin/lsof", "-nP", "-a", "-d", "2", "-Fpa"]
    if only_pid is not None:
        command.extend(("-p", str(only_pid)))
    result = subprocess.run(
        [*command, "--", str(log_path)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=max(0, deadline - time.monotonic()),
    )
    if result.returncode not in (0, 1) or result.stderr or file_identity(log_path) != log_identity:
        raise RuntimeError("Could not verify the Riso Crashpad log writer")
    pid = None
    for field in result.stdout.splitlines():
        if field.startswith("p"):
            pid = int(field[1:])
        elif field in {"aw", "au"} and pid is not None:
            yield pid


def settle_crashpad(log_path, log_identity, executable, deadline):
    signaled = {}
    empty_scan = False
    while time.monotonic() < deadline:
        candidates = False
        for pid in log_writers(log_path, log_identity, deadline):
            owner = process_identity(pid)
            if not owner or owner["uid"] != os.getuid() or owner["command"] != executable:
                continue
            candidates = True
            if owner["ppid"] != 1:
                continue
            key = (pid, owner["started"])
            now = time.monotonic()
            sig = None
            if key not in signaled:
                sig = signal.SIGTERM
            elif signaled[key] is not None and now >= signaled[key] + 0.2:
                sig = signal.SIGKILL
            if (sig is not None and pid in log_writers(log_path, log_identity, deadline, pid)
                    and process_identity(pid) == owner):
                signal_process(pid, sig)
                signaled[key] = now if sig == signal.SIGTERM else None
        if not candidates and empty_scan:
            return sorted({pid for pid, _ in signaled})
        empty_scan = not candidates
        time.sleep(0.05)
    raise TimeoutError("Riso Crashpad cleanup reached its deadline")


def settle_browser(work, phase, runtime, deadline, group=None):
    registration = actor_path(work, f"{phase}-browser")
    try:
        actor = read_state(registration)
    except FileNotFoundError:
        # The launcher cannot start Chrome without a durable registration.
        return []
    if actor.get("command") != runtime["browser"] or (group is not None and actor.get("group") != group):
        raise ValueError("Riso browser executable changed")
    stop_actor(actor, deadline)
    settled = settle_crashpad(work / f"{phase}.chrome.log", actor["log"], runtime["crashpad"], deadline)
    registration.unlink()
    return settled


def group_members(group, deadline):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid="], capture_output=True, text=True, check=True,
        timeout=max(0, deadline - time.monotonic()),
    )
    members = {}
    for row in result.stdout.splitlines():
        pid, pgid = map(int, row.split())
        if pgid != group:
            continue
        identity = process_identity(pid)
        if identity and identity["group"] == group:
            members[pid] = identity["started"]
    return members


def stop_group(work, config, deadline):
    if not config["group_owned"]:
        return
    adapter = config["adapter"]
    group = adapter["pid"]
    records = [adapter, *(read_state(path) for path in work.glob("*.actor.json"))]
    if any(record.get("group") != group for record in records):
        raise ValueError("Riso process groups did not match their registration")
    verified = {record["pid"]: record["started"] for record in records if still_owned(record)}
    term_at = None
    killed = False
    while time.monotonic() < deadline:
        members = group_members(group, deadline)
        if not members:
            return
        anchors = {pid: stamp for pid, stamp in members.items() if verified.get(pid) == stamp}
        if not anchors or not any(
            (identity := process_identity(pid)) and identity["group"] == group and identity["started"] == stamp
            for pid, stamp in anchors.items()
        ):
            # A launcher killed before registration cannot pass ACK and may
            # still be exiting. Never signal a group without a live anchor.
            time.sleep(0.05)
            continue
        verified.update(members)
        now = time.monotonic()
        try:
            if term_at is None:
                os.killpg(group, signal.SIGTERM)
                term_at = now
            elif not killed and now >= term_at + 0.2:
                os.killpg(group, signal.SIGKILL)
                killed = True
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise TimeoutError("Riso process group cleanup reached its deadline")


def settle_work(work, config, deadline):
    runtime = config["runtime"]
    group = config["adapter"]["group"]
    for registration in sorted(work.glob("*.actor.json")):
        slot = registration.name.removesuffix(".actor.json")
        if not SLOT.fullmatch(slot):
            raise ValueError("Unrecognized Riso process registration")
        if not slot.endswith("-browser"):
            actor = read_state(registration)
            if (actor.get("command") not in (runtime["node"], runtime["ffmpeg"], runtime["ffprobe"])
                    or actor.get("group") != group):
                raise ValueError("Riso native command registration changed")
            stop_actor(actor, deadline)
            registration.unlink()
    for phase in ("qa", "render"):
        settle_browser(work, phase, runtime, deadline, group)


def recover_pending(pending, parent, deadline):
    if pending is None:
        return
    try:
        record = read_state(pending)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as error:
        raise RecoveryBlocked("无法核对上一次 Riso 调用的归属，本次没有重渲。") from error
    try:
        if type(record.get("work")) is not str or not re.fullmatch(r"native-[a-zA-Z0-9_-]+", record["work"]):
            raise ValueError("Invalid Riso work ownership")
        work = parent / record["work"]
        if work.resolve(strict=True) != work:
            raise ValueError("Riso work ownership changed")
        config = read_state(work / "watchdog.json")
        if config["invocation_id"] != record["invocation_id"]:
            raise ValueError("Riso invocation identity changed")
        if still_owned(config["adapter"]):
            raise RuntimeError("Riso adapter is still active")
        stop_group(work, config, deadline)
        settle_work(work, config, deadline)
        pending.unlink()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise RecoveryBlocked("上一次 Riso 调用未能安全收尾，本次没有重渲。") from error


def register_actor(client, work, config):
    client.settimeout(0.5)
    # Darwin LOCAL_PEERPID verifies the sender independently of its payload.
    pid = struct.unpack("i", client.getsockopt(0, 2, struct.calcsize("i")))[0]
    with client.makefile("rb") as request:
        raw = request.readline(2048)
    if not raw.endswith(b"\n"):
        raise ValueError("Invalid Riso registration length")
    data = json.loads(raw)
    slot, command = data["slot"], data["command"]
    worker = config["adapter"]
    runtime = config["runtime"]
    actor = process_identity(pid)
    if (not SLOT.fullmatch(slot) or not actor or actor["uid"] != os.getuid()
            or actor["group"] != worker["group"] or actor["command"] != worker["command"]):
        raise ValueError("Invalid Riso registration peer")
    if slot.endswith(("-browser", "-ffmpeg", "-ffprobe")):
        phase, role = slot.split("-")
        native = read_state(actor_path(work, f"{phase}-command"))
        if (actor["ppid"] != native["pid"] or not still_owned(native)
                or command != runtime[role]):
            raise ValueError("Invalid Riso browser or encoder registration")
        if (file_identity(work / f"{phase}.chrome.log") if role == "browser" else None) != data["log"]:
            raise ValueError("Invalid Riso phase log identity")
    elif (actor["ppid"] != worker["pid"] or not still_owned(worker)
          or command not in (runtime["node"], runtime["ffmpeg"], runtime["ffprobe"]) or data["log"] is not None):
        raise ValueError("Invalid Riso command registration")
    destination = actor_path(work, slot)
    if destination.exists():
        raise ValueError("Riso process registered twice")
    write_state(destination, {"pid": pid, "group": actor["group"], "started": actor["started"],
                              "launcher": actor["command"], "command": command, "log": data["log"]})
    client.sendall(b"ready")


def supervise(work, listener, control, owner_fd, pending):
    config = read_state(work / "watchdog.json")
    with selectors.DefaultSelector() as selector:
        selector.register(control, selectors.EVENT_READ, "worker")
        selector.register(listener, selectors.EVENT_READ, "listener")
        if owner_fd is not None:
            selector.register(owner_fd, selectors.EVENT_READ, "owner")
        control.sendall(b"R")
        while True:
            events = {key.data for key, _ in selector.select()}
            if "owner" in events:
                reason = "owner"
                break
            if "worker" in events:
                reason = "finish" if control.recv(1) == b"F" else "worker"
                break
            if "listener" in events:
                with listener.accept()[0] as client:
                    try:
                        register_actor(client, work, config)
                    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
                        print(str(error), file=sys.stderr, flush=True)
        listener.close()
        deadline = time.monotonic() + CLEANUP_SECONDS
        if reason != "finish":
            stop_group(work, config, deadline)
            if reason == "owner":
                stop_actor(config["adapter"], deadline)
        settle_work(work, config, deadline)
        if pending is not None:
            pending.unlink()
        if reason == "finish":
            control.sendall(b"C")


class Watchdog:
    def __init__(self, process, control, socket_path):
        self.process = process
        self.control = control
        self.socket_path = socket_path

    def finish(self):
        try:
            self.control.settimeout(CLEANUP_SECONDS + 1)
            self.control.sendall(b"F")
            if self.control.recv(1) != b"C" or self.process.wait(timeout=1) != 0:
                raise RecoveryBlocked("Riso 监护未确认本次浏览器已经退出。")
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RecoveryBlocked("Riso 监护未确认本次浏览器已经退出。") from error
        finally:
            self.control.close()


def start_watchdog(work, runtime, invocation_id, pending, owner_fd, claim_fd):
    adapter = process_identity(os.getpid())
    config = {"invocation_id": invocation_id,
              "group_owned": adapter["group"] == os.getpid() == os.getsid(0),
              "adapter": {"pid": os.getpid(), "group": adapter["group"], "started": adapter["started"],
                          "launcher": adapter["command"], "command": adapter["command"]},
              "runtime": {key: runtime[key] for key in ("browser", "crashpad", "node", "ffmpeg", "ffprobe")}}
    write_state(work / "watchdog.json", config)
    if pending is not None:
        write_state(pending, {"work": work.name, "invocation_id": invocation_id})
    socket_dir = Path(tempfile.mkdtemp(prefix="riso-w-", dir="/tmp"))
    socket_path = socket_dir / "control"
    with (socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener,
          (work / "watchdog.log").open("ab") as diagnostics):
        listener.bind(str(socket_path))
        listener.listen()
        control, worker = socket.socketpair()
        process = None
        try:
            descriptors = [listener.fileno(), worker.fileno()]
            descriptors.extend(fd for fd in (owner_fd, claim_fd) if fd is not None)
            process = subprocess.Popen(
                [sys.executable, __file__, str(work), str(socket_path), str(listener.fileno()), str(worker.fileno()),
                 str(owner_fd if owner_fd is not None else -1), str(pending or "-")],
                stdin=subprocess.DEVNULL, stdout=diagnostics, stderr=diagnostics,
                start_new_session=True, pass_fds=descriptors,
            )
            worker.close()
            control.settimeout(2)
            if control.recv(1) != b"R":
                raise RecoveryBlocked("Riso 浏览器监护未启动，本次没有启动浏览器。")
            return Watchdog(process, control, socket_path)
        except BaseException as error:
            control.close()
            worker.close()
            if process is None:
                socket_path.unlink(missing_ok=True)
                socket_dir.rmdir()
            if isinstance(error, (OSError, subprocess.SubprocessError)):
                raise RecoveryBlocked("Riso 浏览器监护未启动，本次没有启动浏览器。") from error
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("socket_path", type=Path)
    parser.add_argument("listener", type=int)
    parser.add_argument("control", type=int)
    parser.add_argument("owner", type=int)
    parser.add_argument("pending")
    args = parser.parse_args()
    try:
        with socket.socket(fileno=args.listener) as listener, socket.socket(fileno=args.control) as control:
            supervise(args.work, listener, control, args.owner if args.owner >= 0 else None,
                      Path(args.pending) if args.pending != "-" else None)
    finally:
        args.socket_path.unlink(missing_ok=True)
        try:
            args.socket_path.parent.rmdir()
        except FileNotFoundError:
            pass

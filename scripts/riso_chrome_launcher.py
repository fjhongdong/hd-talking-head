"""Keep the native Node startup pipe out of Chrome and all of its helpers."""
import ctypes
import errno
import http.client
import json
import os
from pathlib import Path
import re
import socket
import sys
import time


STARTUP_SECONDS = 20
DEVTOOLS_PATH = re.compile(r"/devtools/browser/[A-Za-z0-9-]+")


class ProcessInfo(ctypes.Structure):
    # Darwin's proc_bsdinfo, returned by PROC_PIDTBSDINFO.
    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("exit_status", ctypes.c_uint32),
        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("credentials", ctypes.c_uint32 * 6), ("command_names", ctypes.c_char * 48),
        ("open_files", ctypes.c_uint32), ("group", ctypes.c_uint32),
        ("terminal", ctypes.c_uint32 * 4),
        ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64),
    ]


def process_identity(pid, _timeout=None):
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)

    def info():
        data = ProcessInfo()
        size = libproc.proc_pidinfo(pid, 3, ctypes.c_uint64(0), ctypes.byref(data), ctypes.sizeof(data))
        if size == 0 and ctypes.get_errno() == errno.ESRCH:
            return None
        if size != ctypes.sizeof(data) or data.pid != pid:
            raise OSError(ctypes.get_errno(), "Cannot verify Riso process identity")
        return None if data.status == 5 else data  # SZOMB cannot do further work.

    before = info()
    if before is None:
        return None
    binary = ctypes.create_string_buffer(4096)
    if libproc.proc_pidpath(pid, binary, len(binary)) <= 0:
        if ctypes.get_errno() == errno.ESRCH:
            return None
        raise OSError(ctypes.get_errno(), "Cannot verify Riso executable identity")
    after = info()
    if after is None or (before.start_seconds, before.start_microseconds) != (after.start_seconds, after.start_microseconds):
        return None
    return {"ppid": after.ppid, "uid": after.uid, "group": after.group,
            "started": f"{after.start_seconds}.{after.start_microseconds:06d}",
            "command": os.fsdecode(binary.value)}


def register(slot, command, deadline, log_identity=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(max(0, min(2, deadline - time.monotonic())))
        channel.connect(os.environ["RISO_WATCHDOG_SOCKET"])
        channel.sendall(json.dumps({"slot": slot, "command": command, "log": log_identity}).encode() + b"\n")
        if channel.recv(32) != b"ready":
            raise RuntimeError("Riso watchdog did not accept process registration")


def devtools_endpoint(profile, deadline):
    try:
        with (profile / "DevToolsActivePort").open() as ready:
            fields = ready.read(512).splitlines()
    except FileNotFoundError:
        return None
    if (len(fields) != 2 or not re.fullmatch(r"[0-9]{1,5}", fields[0])
            or not 0 < int(fields[0]) < 65536 or not DEVTOOLS_PATH.fullmatch(fields[1])):
        return None
    port = int(fields[0])
    for host, literal in (("127.0.0.1", "127.0.0.1"), ("::1", "[::1]")):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection = http.client.HTTPConnection(host, port, timeout=min(0.1, remaining))
        try:
            connection.request("GET", "/json/version")
            response = connection.getresponse()
            expected = f"ws://{literal}:{port}{fields[1]}"
            if response.status == 200:
                data = json.loads(response.read(8192))
                if type(data) is dict and data.get("webSocketDebuggerUrl") == expected:
                    return expected
        except (OSError, ValueError, http.client.HTTPException):
            continue
        finally:
            connection.close()
    return None


def relay_startup(profile, owner_pid, deadline):
    os.set_blocking(2, False)
    while time.monotonic() < deadline:
        endpoint = devtools_endpoint(profile, deadline)
        if endpoint:
            os.write(2, f"DevTools listening on {endpoint}\n".encode())
            return
        try:
            os.kill(owner_pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.025)
    os.write(2, b"Riso Chrome startup did not publish a matching loopback DevTools endpoint\n")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--guard-tool":
        tool = sys.argv[2]
        command = os.environ["RISO_" + tool.upper()]
        phase = os.environ["RISO_WATCHDOG_PHASE"].removesuffix("-browser")
        register(f"{phase}-{tool}", command, float(os.environ["RISO_WORK_DEADLINE"]))
        os.execv(command, [command, *sys.argv[3:]])
    if len(sys.argv) > 2 and sys.argv[1] == "--guard-command":
        command = sys.argv[2]
        register(os.environ["RISO_WATCHDOG_COMMAND"], command, float(os.environ["RISO_WORK_DEADLINE"]))
        os.execv(command, sys.argv[2:])
    deadline = min(time.monotonic() + STARTUP_SECONDS, float(os.environ["RISO_WORK_DEADLINE"]))
    log_path = Path(os.environ["RISO_CHROME_LOG"])
    browser = os.environ["RISO_CHROME_BINARY"]
    profiles = [Path(arg.partition("=")[2]).resolve(strict=True) for arg in sys.argv[1:]
                if arg.startswith("--user-data-dir=")]
    if len(profiles) != 1 or profiles[0].parent != Path(os.environ["TMPDIR"]).resolve(strict=True):
        raise ValueError("Riso Chrome requires this invocation's private profile")
    owner_pid = os.getpid()
    log_fd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    logfile = os.fstat(log_fd)
    register(os.environ["RISO_WATCHDOG_PHASE"], browser, deadline, [logfile.st_dev, logfile.st_ino])
    relay = os.fork()
    if relay == 0:
        # Reap the intermediate child before exec. The short-lived relay cannot
        # leave a zombie attached to Chrome, and stays in the invocation group.
        if os.fork() != 0:
            os._exit(0)
        os.close(log_fd)
        try:
            relay_startup(profiles[0], owner_pid, deadline)
        except OSError:
            pass
        finally:
            os._exit(0)
    _, status = os.waitpid(relay, 0)
    if status:
        raise RuntimeError("Riso Chrome startup relay failed")

    # Chrome retains the PID observed by upstream's ChildProcess. In particular,
    # its SIGKILL still targets Chrome. Only the startup relay holds Node's pipe.
    null_fd = os.open(os.devnull, os.O_RDWR)
    os.dup2(null_fd, 0)
    os.dup2(null_fd, 1)
    os.dup2(log_fd, 2)
    os.close(null_fd)
    os.close(log_fd)
    os.execv(browser, [browser, *sys.argv[1:]])


if __name__ == "__main__":
    main()

"""Keep the native Node startup pipe out of Chrome and all of its helpers."""
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


STARTUP_SECONDS = 20
DEVTOOLS_PATH = re.compile(r"/devtools/browser/[A-Za-z0-9-]+")


def process_identity(pid, timeout):
    result = subprocess.run(
        ["/bin/ps", "-ww", "-p", str(pid), "-o", "ppid=,uid=,pgid=,state=,lstart=,comm="],
        env={**os.environ, "LC_ALL": "C"}, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode == 1 and not result.stdout and not result.stderr:
        return None
    result.check_returncode()
    fields = result.stdout.split(maxsplit=9)
    if len(fields) != 10:
        raise ValueError("Cannot verify the Riso browser process identity")
    if "Z" in fields[3]:
        return None
    return {"ppid": int(fields[0]), "uid": int(fields[1]), "group": int(fields[2]),
            "started": " ".join(fields[4:9]), "command": fields[9].strip()}


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
    deadline = min(time.monotonic() + STARTUP_SECONDS, float(os.environ["RISO_WORK_DEADLINE"]))
    log_path = Path(os.environ["RISO_CHROME_LOG"])
    browser = os.environ["RISO_CHROME_BINARY"]
    profiles = [Path(arg.partition("=")[2]).resolve(strict=True) for arg in sys.argv[1:]
                if arg.startswith("--user-data-dir=")]
    if len(profiles) != 1 or profiles[0].parent != Path(os.environ["TMPDIR"]).resolve(strict=True):
        raise ValueError("Riso Chrome requires this invocation's private profile")
    owner_pid = os.getpid()
    identity = process_identity(owner_pid, timeout=1)
    if identity is None:
        raise RuntimeError("Could not record the Riso Chrome process")
    log_fd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    owner = log_path.with_suffix(".owner.json")
    temporary = owner.with_suffix(".tmp")
    with temporary.open("x") as data:
        json.dump({"pid": owner_pid, "started": identity["started"], "group": identity["group"],
                   "launcher": identity["command"]}, data)
    os.replace(temporary, owner)
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

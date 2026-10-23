"""Build one frozen stdin entrypoint from the shared renderer's exact source bytes.

This builder does not register templates or issue execution/approval receipts.
External browser/media runtime paths remain explicit dependencies.
"""
from __future__ import annotations

import base64
import argparse
import os
from pathlib import Path
import tempfile


SOURCES = (
    "relation_motion_cli.py", "relation_motion_maintenance_render.py",
    "relation_motion_renderer.cjs", "relation_motion_capture.cjs",
    "relation_browser_watchdog.py", "relation_browser_shim.py",
)

BOOTSTRAP = r'''
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time

READY_TIMEOUT = 5
STOP_TIMEOUT = 8

def descriptor(value):
    if not re.fullmatch(r"/dev/fd/[0-9]+", value):
        raise ValueError("expected an inherited /dev/fd descriptor")
    number = int(value.rsplit("/", 1)[1])
    if number < 3 or not stat.S_ISREG(os.fstat(number).st_mode):
        raise ValueError("descriptor must refer to a regular file")
    return number

def publish(candidate, target):
    if os.fstat(target).st_size != 0:
        raise ValueError("output descriptor changed during render")
    try:
        with candidate.open("rb") as rendered, os.fdopen(os.dup(target), "wb") as destination:
            destination.seek(0)
            shutil.copyfileobj(rendered, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        # Catchable failures roll back our staging bytes. SIGKILL still requires
        # the outer executor's transaction rollback; this is not atomic publish.
        os.ftruncate(target, 0)
        os.lseek(target, 0, os.SEEK_SET)
        raise

def rollback(target):
    if target is None:
        return
    os.ftruncate(target, 0)
    os.lseek(target, 0, os.SEEK_SET)

def read_ready(process):
    selector = selectors.DefaultSelector()
    payload = bytearray()
    deadline = time.monotonic() + READY_TIMEOUT
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        while b"\n" not in payload:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("browser watchdog ready timed out")
            if not selector.select(remaining):
                raise TimeoutError("browser watchdog ready timed out")
            block = os.read(process.stdout.fileno(), 4096 - len(payload))
            if not block:
                raise ValueError("browser watchdog exited before ready")
            payload.extend(block)
            if len(payload) >= 4096:
                raise ValueError("browser watchdog ready response too large")
        line, trailing = bytes(payload).split(b"\n", 1)
        if trailing:
            raise ValueError("browser watchdog emitted unexpected stdout")
        ready = json.loads(line)
        if (type(ready) is not dict or set(ready) != {"root", "socket", "token"}
                or any(type(ready[key]) is not str or not ready[key]
                       for key in ("root", "socket", "token"))):
            raise ValueError("browser watchdog ready response is invalid")
        root = Path(ready["root"]).resolve(strict=True)
        if not root.is_dir() or not Path(ready["socket"]).is_socket():
            raise ValueError("browser watchdog resources are invalid")
        ready["root"] = str(root)
        return ready
    finally:
        selector.close()

def start_watchdog(parent):
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, False)
    source = base64.b64decode(FROZEN_SOURCES["relation_browser_watchdog.py"], validate=True)
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-", "--heartbeat-fd", str(read_fd),
             "--parent", str(parent)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            pass_fds=(read_fd,), start_new_session=True,
        )
        os.close(read_fd)
        read_fd = -1
        process.stdin.write(source)
        process.stdin.close()
        process.stdin = None
        return process, write_fd, read_ready(process)
    except BaseException:
        if read_fd >= 0:
            os.close(read_fd)
        os.close(write_fd)
        if process is not None:
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)
            except OSError:
                process.kill()
        raise

def stop_watchdog(process, heartbeat):
    close_error = None
    try:
        os.close(heartbeat)
    except OSError as error:
        close_error = error
    try:
        stdout, stderr = process.communicate(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate(timeout=2)
        raise RuntimeError("browser watchdog cleanup timed out") from error
    if close_error is not None or process.returncode or stdout:
        detail = stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError("browser watchdog cleanup failed: " + detail) from close_error

def main():
    parser = argparse.ArgumentParser(description="Frozen relation renderer")
    for name in ("brief", "output", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    target = None
    rollback_target = None
    watchdog = None
    heartbeat = -1
    try:
        source, target = descriptor(args.brief), descriptor(args.output)
        source_stat, target_stat = os.fstat(source), os.fstat(target)
        if ((source_stat.st_dev, source_stat.st_ino) == (target_stat.st_dev, target_stat.st_ino)
                or target_stat.st_size != 0 or source_stat.st_size > 4 * 1024 * 1024
                or fcntl.fcntl(target, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY):
            raise ValueError("invalid input/output descriptors")
        rollback_target = target
        parent = Path(tempfile.gettempdir()).resolve(strict=True)
        watchdog, heartbeat, ready = start_watchdog(parent)
        root = Path(ready["root"])
        tools = root / "edit" / "hd" / "tools"
        tools.mkdir(parents=True)
        for name, encoded in FROZEN_SOURCES.items():
            data = base64.b64decode(encoded, validate=True)
            path = tools / name
            if name == "relation_browser_shim.py":
                _, body = data.split(b"\n", 1)
                data = b"#!" + os.fsencode(sys.executable) + b"\n" + body
            path.write_bytes(data)
        shim = tools / "relation_browser_shim.py"
        shim.chmod(0o700)
        brief = root / "brief.json"
        brief.write_bytes(os.pread(source, source_stat.st_size, 0))
        output = root / "candidate.mp4"
        command = [sys.executable, str(tools / "relation_motion_cli.py"),
                   "--brief", str(brief), "--output", str(output)]
        for name in ("node", "playwright", "ffmpeg", "ffprobe"):
            command.extend(["--" + name, getattr(args, name)])
        command.extend(["--browser", str(shim)])
        environment = dict(
            os.environ,
            HD_BROWSER_SOCKET=ready["socket"],
            HD_BROWSER_TOKEN=ready["token"],
            HD_BROWSER_REAL=args.browser,
            HD_RELATION_PARENT_GROUP=str(os.getpgrp()),
        )
        result = subprocess.run(command, check=False, env=environment)
        if result.returncode:
            raise ValueError("relation renderer failed")
        publish(output, target)
        active, active_heartbeat = watchdog, heartbeat
        watchdog, heartbeat = None, -1
        stop_watchdog(active, active_heartbeat)
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        cleanup_error = None
        if watchdog is not None:
            try:
                stop_watchdog(watchdog, heartbeat)
            except (OSError, RuntimeError) as failure:
                cleanup_error = failure
        try:
            rollback(rollback_target)
        except OSError as failure:
            cleanup_error = cleanup_error or failure
        if cleanup_error is not None:
            error = RuntimeError(str(error) + "; " + str(cleanup_error))
        print("frozen relation render failed: " + str(error), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_bundle() -> bytes:
    """Embed source bytes, never resolve project modules at execution time."""
    root = Path(__file__).resolve().parent
    before = {name: (root / name).read_bytes() for name in SOURCES}
    after = {name: (root / name).read_bytes() for name in SOURCES}
    if before != after:
        raise ValueError("renderer sources changed during bundle build")
    sources = {name: base64.b64encode(data).decode("ascii")
               for name, data in before.items()}
    return ("FROZEN_SOURCES = " + repr(sources) + "\n" + BOOTSTRAP).encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = build_bundle()
        # Publish only complete bytes; link is exclusive and never replaces an
        # existing release entrypoint. This does not update the release manifest.
        with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix='.relation-bundle-') as staged:
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())
            os.link(staged.name, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'bundle build failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

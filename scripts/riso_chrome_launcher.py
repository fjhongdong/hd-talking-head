"""Keep the native Node startup pipe out of Chrome and all of its helpers."""
import os
import re
import sys
import time


DEVTOOLS_LINE = re.compile(
    rb"^DevTools listening on ws://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})"
    rb"/devtools/browser/[A-Za-z0-9-]+\r?\n",
    re.MULTILINE,
)


def relay_startup(log_path):
    deadline = time.monotonic() + 15
    os.set_blocking(2, False)
    with open(log_path, "rb", buffering=0) as log:
        while time.monotonic() < deadline:
            size = log.seek(0, os.SEEK_END)
            log.seek(max(0, size - 65536))
            line = DEVTOOLS_LINE.search(log.read(65536))
            if line and 0 < int(line[1]) < 65536:
                os.write(2, line[0])
                return
            time.sleep(0.025)
    os.write(2, b"Riso Chrome startup did not emit a loopback DevTools endpoint\n")


def main():
    log_path = os.environ["RISO_CHROME_LOG"]
    browser = os.environ["RISO_CHROME_BINARY"]
    log_fd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    relay = os.fork()
    if relay == 0:
        # Reap the intermediate child before exec. The short-lived relay cannot
        # leave a zombie attached to Chrome, and stays in the invocation group.
        if os.fork() != 0:
            os._exit(0)
        os.close(log_fd)
        try:
            relay_startup(log_path)
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

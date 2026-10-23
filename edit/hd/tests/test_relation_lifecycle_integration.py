"""Exercise the real watchdog and exec shim together, without a browser."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1] / 'tools'


class LifecycleIntegrationTests(unittest.TestCase):
    def test_registered_exec_is_killed_and_workspace_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            read_fd, write_fd = os.pipe()
            watchdog = subprocess.Popen([
                sys.executable, str(TOOLS / 'relation_browser_watchdog.py'),
                '--heartbeat-fd', str(read_fd), '--parent', str(Path(temporary).resolve())],
                pass_fds=(read_fd,), start_new_session=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            os.close(read_fd)
            child = None
            try:
                self.assertTrue(select.select([watchdog.stdout], [], [], 5)[0], 'watchdog readiness timeout')
                ready = json.loads(watchdog.stdout.readline())
                environment = dict(os.environ, HD_BROWSER_SOCKET=ready['socket'],
                                   HD_BROWSER_TOKEN=ready['token'], HD_BROWSER_REAL=sys.executable)
                child = subprocess.Popen([
                    sys.executable, str(TOOLS / 'relation_browser_shim.py'), '-c',
                    'import os,time; print(os.getpid(),flush=True); time.sleep(30)'],
                    env=environment, start_new_session=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'exec readiness timeout')
                self.assertEqual(child.stdout.readline().strip(), str(child.pid))
                self.assertTrue(Path(ready['root']).is_dir())
                os.close(write_fd)
                write_fd = None
                out, err = watchdog.communicate(timeout=8)
                self.assertEqual(watchdog.returncode, 0, err)
                self.assertEqual(child.wait(timeout=5), -9)
                self.assertFalse(Path(ready['root']).exists())
                self.assertFalse(Path(ready['socket']).exists())
            finally:
                if write_fd is not None:
                    os.close(write_fd)
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=5)
                try:
                    watchdog.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    watchdog.kill()
                    watchdog.communicate(timeout=5)

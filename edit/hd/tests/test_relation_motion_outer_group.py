"""Real outer-kill regression for ordinary renderer subprocesses (not Chromium)."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class OuterGroupTests(unittest.TestCase):
    def test_outer_kill_reaches_supervised_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child.pid"
            child_code = (
                "import os,time; from pathlib import Path; "
                f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
            )
            parent_code = (
                "import os,sys; "
                "os.environ['HD_RELATION_PARENT_GROUP']=str(os.getpgrp()); "
                "from edit.hd.tools.relation_motion_maintenance_render import _run_checked; "
                f"_run_checked([sys.executable,'-c',{child_code!r}],timeout=60)"
            )
            parent = subprocess.Popen([sys.executable, "-c", parent_code],
                                      start_new_session=True, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            child = None
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), "tool did not start")
                child = int(marker.read_text())
                self.assertEqual(os.getpgid(child), parent.pid)
                os.killpg(parent.pid, signal.SIGKILL)
                parent.wait(timeout=5)
                for _ in range(100):
                    state = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(child)],
                                           capture_output=True, text=True, timeout=2).stdout.strip()
                    if not state or state.startswith("Z"):
                        break
                    time.sleep(.02)
                self.assertTrue(not state or state.startswith("Z"), state)
            finally:
                if child:
                    try: os.kill(child, signal.SIGKILL)
                    except ProcessLookupError: pass
                if parent.poll() is None:
                    os.killpg(parent.pid, signal.SIGKILL)
                    parent.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

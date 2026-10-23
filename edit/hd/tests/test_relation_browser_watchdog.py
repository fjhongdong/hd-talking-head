import json
import hashlib
import hmac
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


WATCHDOG = Path(__file__).resolve().parents[1] / "tools/relation_browser_watchdog.py"


class RelationBrowserWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name).resolve()
        self.read_fd, self.write_fd = os.pipe()
        self.process = subprocess.Popen(
            [sys.executable, str(WATCHDOG), "--heartbeat-fd", str(self.read_fd),
             "--parent", str(self.parent)],
            pass_fds=(self.read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        os.close(self.read_fd)
        self.read_fd = -1
        line = self.process.stdout.readline()
        if not line:
            self.fail(self.process.stderr.read())
        self.ready = json.loads(line)
        self.root = Path(self.ready["root"])
        self.socket_path = self.ready["socket"]
        self.token = self.ready["token"]

    def request(self, pid, pgid, nonce="a" * 32):
        proof = hmac.new(
            self.token.encode(), f"register:{pid}:{nonce}".encode(), hashlib.sha256,
        ).hexdigest()
        return {"pid": pid, "pgid": pgid, "nonce": nonce, "proof": proof}

    def tearDown(self):
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, 9)
            self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()

    def close_heartbeat(self):
        os.close(self.write_fd)
        self.write_fd = -1

    @staticmethod
    def kill_if_alive(pid):
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass

    def wait_for_exit(self):
        self.assertEqual(self.process.wait(timeout=5), 0, self.process.stderr.read())

    def test_ready_root_is_owned_and_removed_on_heartbeat_eof(self):
        self.assertEqual(set(self.ready), {"root", "socket", "token"})
        self.assertTrue(self.root.is_dir())
        self.assertTrue(Path(self.socket_path).is_socket())
        self.close_heartbeat()
        self.wait_for_exit()
        self.assertFalse(self.root.exists())

    def test_registered_detached_group_is_killed_before_staging_cleanup(self):
        marker = self.parent / "ack.json"
        client = (
            "import hashlib,hmac,json,os,socket,sys,time; "
            "s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); "
            "nonce=sys.argv[4]; pid=os.getpid(); "
            "proof=hmac.new(sys.argv[2].encode(),f'register:{pid}:{nonce}'.encode(),hashlib.sha256).hexdigest(); "
            "s.sendall((json.dumps({'pid':pid,'pgid':os.getpgrp(),'nonce':nonce,'proof':proof})+'\\n').encode()); "
            "reply=s.recv(4096); open(sys.argv[3],'wb').write(reply); time.sleep(30)"
        )
        browser = subprocess.Popen(
            [sys.executable, "-c", client, self.socket_path, self.token, str(marker), "b" * 32],
            start_new_session=True,
        )
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists())
        reply = json.loads(marker.read_text())
        self.assertEqual(set(reply), {"ack", "proof"})
        self.assertEqual(reply["ack"], browser.pid)
        expected = hmac.new(
            self.token.encode(), f"ack:{browser.pid}:{'b' * 32}".encode(), hashlib.sha256,
        ).hexdigest()
        self.assertEqual(reply["proof"], expected)
        (self.root / "render.partial").write_bytes(b"partial")
        self.close_heartbeat()
        self.wait_for_exit()
        browser.wait(timeout=5)
        self.assertEqual(browser.returncode, -9)
        self.assertFalse(self.root.exists())

    def test_invalid_pid_group_is_not_acknowledged(self):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(self.socket_path)
            client.sendall((json.dumps(self.request(
                os.getpid(), os.getpgrp() + 100000,
            )) + "\n").encode())
            self.assertEqual(client.recv(4096), b"")
        self.close_heartbeat()
        self.wait_for_exit()

    def test_authenticated_client_cannot_register_another_process(self):
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(victim.wait, timeout=5)
        self.addCleanup(self.kill_if_alive, victim.pid)
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(self.socket_path)
            client.sendall((json.dumps(self.request(victim.pid, victim.pid)) + "\n").encode())
            self.assertEqual(client.recv(4096), b"")
        self.assertIsNone(victim.poll())


    def test_partial_handshake_does_not_block_heartbeat_eof(self):
        client = socket.socket(socket.AF_UNIX)
        client.connect(self.socket_path)
        client.sendall(b'{"pid":')
        self.close_heartbeat()
        self.wait_for_exit()
        client.close()
        self.assertFalse(self.root.exists())

    def test_bad_hmac_is_not_acknowledged(self):
        request = self.request(os.getpid(), os.getpgrp())
        request["proof"] = "0" * 64
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(self.socket_path)
            client.sendall((json.dumps(request) + "\n").encode())
            self.assertEqual(client.recv(4096), b"")

    def test_sigkill_of_sole_heartbeat_owner_triggers_cleanup(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            pass_fds=(self.write_fd,), start_new_session=True,
        )
        self.close_heartbeat()
        time.sleep(0.05)
        self.assertIsNone(self.process.poll())
        os.killpg(holder.pid, 9)
        holder.wait(timeout=5)
        self.wait_for_exit()
        self.assertFalse(self.root.exists())

    def test_group_is_killed_after_registered_leader_exits(self):
        marker = self.parent / "descendant.pid"
        leader_code = (
            "import hashlib,hmac,json,os,socket,sys,time; "
            "s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); "
            "nonce='c'*32; pid=os.getpid(); proof=hmac.new(sys.argv[2].encode(),"
            "f'register:{pid}:{nonce}'.encode(),hashlib.sha256).hexdigest(); "
            "s.sendall((json.dumps({'pid':pid,'pgid':os.getpgrp(),'nonce':nonce,'proof':proof})+'\\n').encode()); "
            "reply=json.loads(s.recv(4096)); "
            "child=os.fork(); "
            "open(sys.argv[3],'w').write(str(child)) if child else None; "
            "time.sleep(30) if child == 0 else None"
        )
        leader = subprocess.Popen(
            [sys.executable, "-c", leader_code, self.socket_path, self.token, str(marker)],
            start_new_session=True,
        )
        leader.wait(timeout=5)
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists())
        descendant = int(marker.read_text())
        self.addCleanup(self.kill_if_alive, descendant)
        self.close_heartbeat()
        self.wait_for_exit()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(descendant)],
                capture_output=True, text=True,
            ).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        self.assertTrue(not state or state.startswith("Z"), state)

    def test_cleanup_failure_is_not_silently_accepted(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("relation_watchdog_unit", WATCHDOG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module.shutil, "rmtree", side_effect=OSError("denied")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                module._cleanup_paths(self.root)
        with (mock.patch.object(module, "supervise", side_effect=RuntimeError("cleanup failed")),
              mock.patch.object(module.os.sys, "stderr", io.StringIO())):
            self.assertEqual(module.main([
                "--heartbeat-fd", "0", "--parent", str(self.parent),
            ]), 1)

    def test_one_group_kill_failure_does_not_skip_later_groups(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("relation_watchdog_cleanup", WATCHDOG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        groups = {101: "first", 202: "second"}
        with (mock.patch.object(module, "_process_start_identity", side_effect=["first", "second"]),
              mock.patch.object(module, "_group_has_live_members", return_value=False),
              mock.patch.object(module.os, "killpg", side_effect=[OSError("denied"), None]) as killpg):
            with self.assertRaisesRegex(RuntimeError, "browser group kill failed: 101"):
                module._terminate_registered(groups)
        self.assertEqual(killpg.call_args_list, [
            mock.call(101, module.signal.SIGKILL),
            mock.call(202, module.signal.SIGKILL),
        ])


if __name__ == "__main__":
    unittest.main()

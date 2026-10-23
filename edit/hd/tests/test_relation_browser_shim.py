"""Real socket handshake tests; no browser is launched by these tests."""
import json
import hashlib
import hmac
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


SHIM = Path(__file__).resolve().parents[1] / 'tools/relation_browser_shim.py'


class BrowserShimTests(unittest.TestCase):
    def test_non_session_leader_is_rejected_before_connect(self):
        result = subprocess.run([sys.executable, str(SHIM)],
                                env=dict(os.environ, HD_BROWSER_SOCKET='/unused',
                                         HD_BROWSER_TOKEN='test-token',
                                         HD_BROWSER_REAL=sys.executable),
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must own its session and process group', result.stderr)

    def test_disconnect_or_silent_supervisor_never_executes(self):
        for disconnect in (True, False):
            with self.subTest(disconnect=disconnect), tempfile.TemporaryDirectory() as tmp:
                address = str(Path(tmp) / 's')
                with socket.socket(socket.AF_UNIX) as server:
                    server.bind(address)
                    server.listen(1)
                    server.settimeout(5)
                    env = dict(os.environ, HD_BROWSER_SOCKET=address,
                               HD_BROWSER_TOKEN='test-token', HD_BROWSER_REAL=sys.executable)
                    child = subprocess.Popen([sys.executable, str(SHIM), '-c',
                                              "print('MUST NOT EXECUTE')"],
                                             env=env, start_new_session=True,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    connection = None
                    try:
                        connection = server.accept()[0]
                        connection.settimeout(5)
                        connection.recv(4096)
                        if disconnect:
                            connection.close()
                        out, err = child.communicate(timeout=5)
                        self.assertNotEqual(child.returncode, 0)
                        self.assertEqual(out, '')
                        self.assertIn('browser lifecycle refused', err)
                    finally:
                        if connection is not None:
                            connection.close()
                        if child.poll() is None:
                            child.kill()
                        child.communicate(timeout=5)

    def test_missing_supervisor_fails_closed(self):
        result = subprocess.run([sys.executable, str(SHIM)],
                                capture_output=True, text=True, timeout=5,
                                start_new_session=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('browser lifecycle refused', result.stderr)

    def test_ack_is_required_and_preserves_pid(self):
        for accept in (False, True, 'malformed', 'oversized'):
            with self.subTest(accept=accept), tempfile.TemporaryDirectory() as tmp:
                address = str(Path(tmp) / 's')
                with socket.socket(socket.AF_UNIX) as server:
                    server.bind(address)
                    server.listen(1)
                    server.settimeout(5)
                    env = dict(os.environ, HD_BROWSER_SOCKET=address,
                               HD_BROWSER_TOKEN='test-token', HD_BROWSER_REAL=sys.executable)
                    child = subprocess.Popen([sys.executable, str(SHIM), '-c',
                                              "import os,json; print(os.getpid()); print(json.dumps({k:v for k,v in os.environ.items() if k.startswith('HD_BROWSER_')}))"],
                                             env=env, start_new_session=True,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        with server.accept()[0] as connection:
                            connection.settimeout(5)
                            request = json.loads(connection.recv(4096))
                            self.assertEqual(request['pid'], child.pid)
                            self.assertEqual(request['pgid'], child.pid)
                            self.assertNotIn('token', request)
                            nonce = request['nonce']
                            proof = lambda message: hmac.new(b'test-token', message.encode(), hashlib.sha256).hexdigest()
                            self.assertEqual(request['proof'], proof(f'register:{child.pid}:{nonce}'))
                            if accept == 'malformed':
                                reply = b'not-json\n'
                            elif accept == 'oversized':
                                reply = b'x' * 4096
                            else:
                                reply = (json.dumps({'ack': child.pid,
                                    'proof': proof(f'ack:{child.pid}:{nonce}') if accept else 'wrong'})+'\n').encode()
                            connection.sendall(reply)
                        out, err = child.communicate(timeout=5)
                        if accept is True:
                            self.assertEqual(child.returncode, 0, err)
                            self.assertEqual(out.splitlines(), [str(child.pid), '{}'])
                        else:
                            self.assertNotEqual(child.returncode, 0)
                            self.assertEqual(out, '')
                    finally:
                        if child.poll() is None:
                            child.kill()
                        child.communicate(timeout=5)

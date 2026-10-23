#!/usr/bin/env python3
"""Browser exec gate. A supervisor must register this group before acknowledging.

Not wired into the bundle until the supervisor and lifecycle tests are complete.
Playwright creates the private session before executing this entrypoint.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
import socket
import sys
import time


def main():
    try:
        address = os.environ['HD_BROWSER_SOCKET']
        token = os.environ['HD_BROWSER_TOKEN']
        executable = os.environ['HD_BROWSER_REAL']
        pid = os.getpid()
        if not token or not os.path.isabs(executable):
            raise ValueError('invalid supervisor configuration')
        if os.getpgid(0) != pid or os.getsid(0) != pid:
            raise ValueError('browser shim must own its session and process group')
        deadline = time.monotonic() + 3
        nonce = secrets.token_hex(16)
        def proof(message):
            return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(max(.001, deadline - time.monotonic()))
            connection.connect(address)
            connection.sendall((json.dumps({'pid': pid, 'pgid': pid, 'nonce': nonce,
                'proof': proof(f'register:{pid}:{nonce}')}) + '\n').encode())
            response = bytearray()
            while b'\n' not in response:
                connection.settimeout(max(.001, deadline - time.monotonic()))
                if time.monotonic() >= deadline:
                    raise TimeoutError('supervisor acknowledgement timed out')
                block = connection.recv(4096 - len(response))
                if not block:
                    raise ValueError('supervisor closed without acknowledgement')
                response.extend(block)
                if len(response) >= 4096:
                    raise ValueError('supervisor response too large')
            acknowledgement = json.loads(response)
            if (not isinstance(acknowledgement, dict)
                    or set(acknowledgement) != {'ack', 'proof'}
                    or acknowledgement['ack'] != pid
                    or not isinstance(acknowledgement['proof'], str)
                    or not hmac.compare_digest(acknowledgement['proof'], proof(f'ack:{pid}:{nonce}'))):
                raise ValueError('supervisor acknowledgement mismatch')
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('HD_BROWSER_')}
        os.execve(executable, [executable, *sys.argv[1:]], environment)
    except (OSError, ValueError, KeyError) as error:
        print('browser lifecycle refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

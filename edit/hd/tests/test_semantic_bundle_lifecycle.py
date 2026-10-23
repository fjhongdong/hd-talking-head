"""Envelope failure injection; real media execution is tested separately."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from edit.hd.tools.runtime_contracts import normalize_contracts
from edit.hd.tools.semantic_state_bundle import build_bundle
from edit.hd.tests import test_runtime_contracts as runtime_fixtures


class SemanticBundleLifecycleTests(unittest.TestCase):
    def test_verification_failures_do_not_publish_and_commands_use_snapshots(self):
        for failure in (None, "pre", "post", "renderer", "argument", "marker"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                owned = root / "owned"
                owned.mkdir()
                events, calls = [], []
                contracts = runtime_fixtures.RuntimeTreeTests().contracts()
                for key in ("node", "ffmpeg", "ffprobe"):
                    contracts[key].update(libraries=[], library_discovery="mach_o_static_v1")
                support = types.ModuleType("semantic_bundle_test_support")
                support.normalize_contracts = normalize_contracts

                def verify(value):
                    stage = "pre" if "pre" not in events else "post"
                    events.append(stage)
                    if failure == stage:
                        raise ValueError("injected " + stage)
                    return value

                def snapshot(source, destination, sha):
                    calls.append((source, destination, sha))
                    destination.write_bytes(b"snapshot")

                def start(_):
                    events.append("start")
                    return object(), 123, {"root": str(owned), "socket": "test", "token": "test"}

                def publish(candidate, target):
                    events.append("publish")
                    os.write(target, candidate.read_bytes())

                support.verify_contracts = verify
                support._snapshot = snapshot
                support.descriptor = lambda text: int(text.rsplit("/", 1)[1])
                support.start_watchdog = start
                support.stop_watchdog = lambda *_: events.append("stop")
                support.publish = publish
                support.rollback = lambda fd: os.ftruncate(fd, 0) if fd is not None else None
                namespace = {"__name__": "bundle_test"}
                exec(compile(build_bundle(), "bundle.py", "exec"), namespace)
                namespace["BROWSER_SUPPORT"] = "from semantic_bundle_test_support import *"
                namespace["FROZEN_SOURCES"]["runtime_contracts.py"] = base64.b64encode(
                    b"from semantic_bundle_test_support import normalize_contracts, verify_contracts").decode()
                namespace["FROZEN_SOURCES"]["semantic_validator.py"] = base64.b64encode(
                    b"from semantic_bundle_test_support import _snapshot").decode()

                def render(command, **kwargs):
                    events.append("render")
                    for key in ("node", "ffmpeg", "ffprobe"):
                        self.assertEqual(command[command.index("--" + key) + 1], str(owned / key))
                    self.assertEqual(command[command.index("--playwright") + 1], contracts["playwright"]["path"])
                    self.assertEqual(kwargs["env"]["HD_BROWSER_REAL"], contracts["browser"]["path"])
                    (owned / "candidate.mp4").write_bytes(b"candidate")
                    return types.SimpleNamespace(returncode=1 if failure == "renderer" else 0)

                incoming_path, outgoing_path = root / "in", root / "out"
                incoming_path.write_bytes(b"{}")
                with incoming_path.open("rb") as incoming, outgoing_path.open("w+b") as outgoing:
                    argv = ["bundle", "--brief", f"/dev/fd/{incoming.fileno()}", "--output", f"/dev/fd/{outgoing.fileno()}"]
                    for key in contracts:
                        argv.extend(["--" + key, "/wrong" if failure == "argument" and key == "node" else contracts[key]["path"]])
                    if failure == "marker":
                        del contracts["node"]["library_discovery"]
                    argv.extend(["--runtime-contracts", json.dumps(contracts)])
                    with patch.dict(sys.modules, {support.__name__: support}), patch.object(sys, "argv", argv), \
                         patch.object(namespace["subprocess"], "run", side_effect=render), contextlib.redirect_stderr(io.StringIO()):
                        code = namespace["semantic_main"]()
                    outgoing.seek(0)
                    self.assertEqual(outgoing.read(), b"candidate" if failure is None else b"")
                self.assertEqual(code, 0 if failure is None else 1)
                if failure in ("pre", "argument", "marker"):
                    self.assertNotIn("start", events)
                    self.assertNotIn("render", events)
                else:
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(events[-1], "stop")
                if failure is None:
                    self.assertEqual(events, ["pre", "start", "render", "post", "publish", "stop"])
                else:
                    self.assertNotIn("publish", events)

"""Frozen entrypoint tests: no production approval or renderer registration."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"


class RelationBundleTests(unittest.TestCase):
    def test_builder_cli_writes_exact_bundle_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle.py'
            command = [sys.executable, str(TOOLS / 'relation_motion_bundle.py'), '--output', str(output)]
            first = subprocess.run(command, cwd='/', capture_output=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(output.is_file(), 'builder CLI must publish a frozen bundle')
            self.assertEqual(output.read_bytes(), self.builder().build_bundle())
            output.write_bytes(b'preserve-existing')
            second = subprocess.run(command, cwd='/', capture_output=True, timeout=10)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), b'preserve-existing')
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def builder(self):
        path = TOOLS / "relation_motion_bundle.py"
        self.assertTrue(path.exists(), "frozen bundle builder is required")
        spec = importlib.util.spec_from_file_location("relation_bundle", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_bundle_is_deterministic_and_runs_from_stdin_outside_project(self):
        builder = self.builder()
        self.assertEqual(set(builder.SOURCES), {
            "relation_motion_cli.py", "relation_motion_maintenance_render.py",
            "relation_motion_renderer.cjs", "relation_motion_capture.cjs",
            "relation_browser_watchdog.py", "relation_browser_shim.py",
        })
        payload = builder.build_bundle()
        self.assertEqual(payload, builder.build_bundle())
        result = subprocess.run([sys.executable, "-", "--help"], input=payload,
                                cwd="/", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--brief", result.stdout)

    def test_failed_frozen_render_preserves_empty_output(self):
        payload = self.builder().build_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "brief.json").write_text("{}")
            with (root / "brief.json").open("rb") as source, (root / "out.mp4").open("w+b") as output:
                result = subprocess.run([
                    sys.executable, "-", "--brief", f"/dev/fd/{source.fileno()}",
                    "--output", f"/dev/fd/{output.fileno()}",
                    "--node", "/missing-node", "--playwright", "/missing-playwright",
                    "--browser", "/missing-browser", "--ffmpeg", "/missing-ffmpeg",
                    "--ffprobe", "/missing-ffprobe",
                ], input=payload, cwd="/", capture_output=True,
                    env={**os.environ, "TMPDIR": str(root)},
                    pass_fds=(source.fileno(), output.fileno()), timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / "out.mp4").stat().st_size, 0)
                self.assertNotIn(b"ModuleNotFoundError", result.stderr)
                self.assertNotIn(b"IndexError", result.stderr)
                self.assertFalse(list(root.glob("relation-browser-*")))
                self.assertFalse(list(root.glob("rbw-*")))

    def test_rejected_fd_contract_never_changes_existing_bytes(self):
        payload = self.builder().build_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_path = root / "brief.json"
            source_path.write_text("{}", encoding="utf-8")
            target_path = root / "existing.mp4"
            target_path.write_bytes(b"keep-target")
            with source_path.open("rb") as source, target_path.open("r+b") as target:
                result = subprocess.run([
                    sys.executable, "-", "--brief", f"/dev/fd/{source.fileno()}",
                    "--output", f"/dev/fd/{target.fileno()}", "--node", "/node",
                    "--playwright", "/playwright", "--browser", "/browser",
                    "--ffmpeg", "/ffmpeg", "--ffprobe", "/ffprobe",
                ], input=payload, capture_output=True,
                    pass_fds=(source.fileno(), target.fileno()), timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target_path.read_bytes(), b"keep-target")

            same_path = root / "same.json"
            same_path.write_bytes(b'{"same":true}')
            with same_path.open("r+b") as same:
                descriptor = f"/dev/fd/{same.fileno()}"
                result = subprocess.run([
                    sys.executable, "-", "--brief", descriptor, "--output", descriptor,
                    "--node", "/node", "--playwright", "/playwright",
                    "--browser", "/browser", "--ffmpeg", "/ffmpeg",
                    "--ffprobe", "/ffprobe",
                ], input=payload, capture_output=True,
                    pass_fds=(same.fileno(),), timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(same_path.read_bytes(), b'{"same":true}')

    def test_source_change_during_bundle_build_is_rejected(self):
        builder = self.builder()
        original = Path.read_bytes
        calls = {}
        def changed(path):
            calls[path.name] = calls.get(path.name, 0) + 1
            data = original(path)
            if path.name == builder.SOURCES[0] and calls[path.name] > 1:
                return data + b"\n# changed"
            return data
        with mock.patch.object(Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                builder.build_bundle()

    def test_publication_copy_and_fsync_failure_roll_back_empty_target(self):
        namespace = {"__name__": "frozen_test"}
        exec(self.builder().build_bundle(), namespace)
        self.assertIn("publish", namespace)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate.mp4"
            candidate.write_bytes(b"verified-media")
            for operation in ("copy", "fsync"):
                with (root / "out.mp4").open("w+b") as output:
                    def partial(source, destination, **kwargs):
                        destination.write(b"partial")
                        destination.flush()
                        raise OSError("copy failed")
                    patch = (mock.patch.object(namespace["shutil"], "copyfileobj", side_effect=partial)
                             if operation == "copy" else
                             mock.patch.object(namespace["os"], "fsync", side_effect=OSError("fsync failed")))
                    with patch, self.assertRaises(OSError):
                        namespace["publish"](candidate, output.fileno())
                    self.assertEqual((root / "out.mp4").stat().st_size, 0)

    def test_sigkill_of_bundle_closes_unique_heartbeat_and_cleans_staging(self):
        from edit.hd.tests.test_relation_motion_renderer import brief
        payload = self.builder().build_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            brief_path = root / "brief.json"
            brief_path.write_text(json.dumps(brief(2)), encoding="utf-8")
            output_path = root / "out.mp4"
            sleeper = root / "node"
            started = root / "node-started"
            sleeper.write_text(
                f"#!{sys.executable}\nfrom pathlib import Path\nimport time\n"
                f"Path({str(started)!r}).write_text('started')\ntime.sleep(30)\n",
                encoding="utf-8",
            )
            sleeper.chmod(0o700)
            for name in ("playwright", "browser", "ffmpeg", "ffprobe"):
                path = root / name
                path.write_bytes(b"placeholder")
            with brief_path.open("rb") as source, output_path.open("w+b") as output:
                process = subprocess.Popen([
                    sys.executable, "-", "--brief", f"/dev/fd/{source.fileno()}",
                    "--output", f"/dev/fd/{output.fileno()}",
                    "--node", str(sleeper), "--playwright", str(root / "playwright"),
                    "--browser", str(root / "browser"), "--ffmpeg", str(root / "ffmpeg"),
                    "--ffprobe", str(root / "ffprobe"),
                ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/", env={**os.environ, "TMPDIR": str(root)},
                    pass_fds=(source.fileno(), output.fileno()), start_new_session=True)
                process.stdin.write(payload)
                process.stdin.close()
                deadline = time.monotonic() + 5
                while (not list(root.glob("relation-browser-*")) or not started.exists()) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(list(root.glob("relation-browser-*")))
                self.assertTrue(started.exists())
                os.killpg(process.pid, 9)
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
                deadline = time.monotonic() + 5
                while (list(root.glob("relation-browser-*")) or list(root.glob("rbw-*"))) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(list(root.glob("relation-browser-*")))
                self.assertFalse(list(root.glob("rbw-*")))
                self.assertEqual(output_path.stat().st_size, 0)

    def test_watchdog_cleanup_failure_rolls_back_published_target(self):
        namespace = {"__name__": "frozen_test"}
        exec(self.builder().build_bundle(), namespace)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_path = root / "brief.json"
            source_path.write_text("{}", encoding="utf-8")
            target_path = root / "out.mp4"
            stage = root / "watchdog-root"
            stage.mkdir()
            def render(command, **kwargs):
                self.assertEqual(kwargs["env"]["HD_RELATION_PARENT_GROUP"], str(os.getpgrp()))
                Path(command[command.index("--output") + 1]).write_bytes(b"rendered")
                return SimpleNamespace(returncode=0)
            argv = [
                "bundle", "--brief", "", "--output", "", "--node", "/node",
                "--playwright", "/playwright", "--browser", "/browser",
                "--ffmpeg", "/ffmpeg", "--ffprobe", "/ffprobe",
            ]
            with source_path.open("rb") as source, target_path.open("w+b") as target:
                argv[2] = f"/dev/fd/{source.fileno()}"
                argv[4] = f"/dev/fd/{target.fileno()}"
                namespace["start_watchdog"] = mock.Mock(return_value=(object(), 99, {
                    "root": str(stage), "socket": str(root / "socket"), "token": "secret",
                }))
                namespace["stop_watchdog"] = mock.Mock(side_effect=RuntimeError("cleanup failed"))
                with (mock.patch.object(namespace["sys"], "argv", argv),
                      mock.patch.object(namespace["subprocess"], "run", side_effect=render),
                      mock.patch.object(namespace["os"], "fsync"),
                      mock.patch.object(namespace["sys"], "stderr", io.StringIO())):
                    self.assertEqual(namespace["main"](), 1)
            self.assertEqual(target_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

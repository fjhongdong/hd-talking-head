"""Riso brief, process isolation, and format contracts without user Jobs."""
import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location("riso_native_adapter", SKILL / "scripts/riso_native_adapter.py")
riso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(riso)
import riso_watchdog as guard


def number_brief():
    return {"schema_version": 1,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-riso-test", "start": 0, "end": 5},
            "composition": {"id": "riso-test", "width": 1080, "height": 1920, "fps": 24, "frames": 120},
            "template_request": {"semantic_family": "numeric_emphasis", "information_units": 1, "numeric_values": [12], "numeric_scale": "linear"},
            "template": "number", "assets": [],
            "data": {"palette": "pal-blue", "mast": ["验证 · 非真实数据", "原生模板"], "duration": 5,
                     "number": 12, "prefix": "", "suffix": "", "comma": False, "unit": "项测试",
                     "say": "公开[内容槽]"}}


def title_brief():
    value = number_brief()
    value.update(template="title", template_request={"semantic_family": "section_heading",
                 "information_units": 1, "numeric_values": [], "numeric_scale": "not_applicable"})
    value["data"] = {"palette": "pal-blue", "mast": ["主题", "原生模板"], "duration": 5,
                     "flood": False, "index": "01", "kicker": "", "title": "开放疑问", "sub": ""}
    return value


class RisoNativeAdapterTest(unittest.TestCase):
    def test_detached_chrome_helper_cannot_keep_node_alive(self):
        # Reproduce Chrome's inherited stderr without depending on Crashpad timing.
        with tempfile.TemporaryDirectory(prefix="riso-fd-test-") as directory:
            root = Path(directory)
            fake = root / "fake-chrome"
            fake.write_text('#!/bin/sh\nexec "$TEST_PYTHON" "$TEST_BROWSER" "$@"\n')
            fake.chmod(0o700)
            program = root / "fake_chrome.py"
            program.write_text(r"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import time

directory = Path(os.environ["TEST_WORK"])
if os.fork() == 0:
    os.setsid()
    (directory / "helper-ready").write_text(str(os.getpid()))
    deadline = time.monotonic() + 20
    while not (directory / "release-helper").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    (directory / "helper-done").touch()
    os._exit(0)

while not (directory / "helper-ready").exists():
    time.sleep(0.01)

class DevTools(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"webSocketDebuggerUrl": endpoint}).encode())

server = HTTPServer(("127.0.0.1", 0), DevTools)
port = server.server_port
endpoint = f"ws://127.0.0.1:{port}/devtools/browser/test"
profile = Path(sys.argv[1].split("=", 1)[1])
(profile / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/test")
print(f"DevTools listening on {endpoint}", file=sys.stderr, flush=True)
print("x" * 65536, file=sys.stderr, flush=True)
server.serve_forever()
""")
            node = """
const { spawn } = require('node:child_process');
const { mkdtempSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const profile = mkdtempSync(join(process.env.TMPDIR, 'profile-'));
const chrome = spawn(process.env.CHROME, ['--user-data-dir=' + profile], { stdio: ['ignore', 'ignore', 'pipe'] });
chrome.stderr.on('data', chunk => {
  if (chunk.includes('DevTools listening on ')) chrome.kill('SIGTERM');
});
chrome.on('exit', (code, signal) => {
  if (signal !== 'SIGTERM') process.exitCode = 1;
  else writeFileSync(join(process.env.TEST_WORK, 'browser-exited'), '');
});
"""
            def wait_for(path, seconds):
                deadline = time.monotonic() + seconds
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                return path.exists()

            for isolated in (False, True):
                with self.subTest(isolated=isolated):
                    work = root / ("isolated" if isolated else "direct")
                    work.mkdir()
                    env = {**os.environ, "CHROME": str(fake), "TEST_WORK": str(work), "TMPDIR": str(work),
                           "TEST_PYTHON": sys.executable, "TEST_BROWSER": str(program)}
                    node_path = str(Path(shutil.which("node")).resolve())
                    command = [node_path, "-e", node]
                    watcher = None
                    if isolated:
                        runtime = {"browser": str(fake), "crashpad": "/bin/true", "node": node_path,
                                   "ffmpeg": "/bin/true", "ffprobe": "/bin/true",
                                   "chrome_launcher_sha256": riso.sha(SKILL / riso.CHROME_LAUNCHER)}
                        watcher = guard.start_watchdog(work, runtime, "isolation-test", None, None, None)
                        env.update(riso.chrome_environment(work, runtime), RISO_CHROME_LOG=str(work / "render.chrome.log"),
                                   RISO_WORK_DEADLINE=str(time.monotonic() + 15), RISO_WATCHDOG_PHASE="render-browser",
                                   RISO_WATCHDOG_SOCKET=str(watcher.socket_path), RISO_WATCHDOG_COMMAND="render-command")
                        command = [sys.executable, env["RISO_CHROME_RELAY"], "--guard-command", *command]
                    try:
                        with subprocess.Popen(command, env=env, start_new_session=not isolated) as process:
                            try:
                                self.assertTrue(wait_for(work / "browser-exited", 8), "browser never reached its exit event")
                                if isolated:
                                    self.assertEqual(process.wait(timeout=3), 0)
                                else:
                                    with self.assertRaises(subprocess.TimeoutExpired):
                                        process.wait(timeout=0.2)
                                os.kill(int((work / "helper-ready").read_text()), 0)
                                self.assertFalse((work / "helper-done").exists())
                            finally:
                                if process.poll() is None:
                                    if isolated:
                                        process.kill()
                                    else:
                                        guard.signal_process(-process.pid, signal.SIGKILL)
                                (work / "release-helper").touch()
                                wait_for(work / "helper-done", 2)
                    finally:
                        if watcher is not None:
                            watcher.finish()

    def test_crashpad_cleanup_only_signals_the_owned_log_writer(self):
        path = Path("/private/riso/render.chrome.log")
        executable = "/Applications/Google Chrome.app/Helpers/chrome_crashpad_handler"
        expected = {"ppid": 1, "uid": os.getuid(), "started": "original", "command": executable}
        signals = []
        clock = [0.0]

        def command(argv, **_):
            self.assertEqual(argv[0], "/usr/sbin/lsof")
            self.assertEqual(argv[-1], str(path))
            self.assertEqual(argv[3:5], ["-d", "2"])
            output = "p102\naw\np103\nar\n"
            if (101, signal.SIGKILL) not in signals:
                output += "p101\naw\n"
            if (101, signal.SIGTERM) in signals and (104, signal.SIGTERM) not in signals:
                output += "p104\naw\n"
            return subprocess.CompletedProcess(argv, 0, output, "")

        def identity(pid):
            return {**expected, "command": executable + "-unrelated"} if pid == 102 else expected

        def sleep(seconds):
            clock[0] += seconds

        with (patch.object(guard.subprocess, "run", side_effect=command),
              patch.object(guard, "file_identity", return_value=[1, 2]),
              patch.object(guard, "process_identity", side_effect=identity),
              patch.object(guard.os, "kill", side_effect=lambda pid, sig: signals.append((pid, sig))),
              patch.object(guard.time, "monotonic", side_effect=lambda: clock[0]),
              patch.object(guard.time, "sleep", side_effect=sleep)):
            self.assertEqual(guard.settle_crashpad(path, [1, 2], executable, 3), [101, 104])
        self.assertCountEqual(signals, [(101, signal.SIGTERM), (104, signal.SIGTERM), (101, signal.SIGKILL)])

    def test_abnormal_browser_exit_cleanup_stops_only_the_registered_process(self):
        with tempfile.TemporaryDirectory(prefix="riso-cleanup-test-") as directory:
            log = Path(directory) / "render.chrome.log"
            command = [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(20)"]
            with (subprocess.Popen(command, start_new_session=True, stdout=subprocess.PIPE) as owner,
                  subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL) as other):
                try:
                    self.assertEqual(owner.stdout.readline(), b"ready\n")
                    identity = guard.process_identity(owner.pid)
                    guard.stop_actor({"pid": owner.pid, "started": identity["started"], "group": identity["group"],
                                      "launcher": identity["command"], "command": identity["command"]},
                                     time.monotonic() + 2)
                    self.assertEqual(owner.wait(timeout=1), -signal.SIGTERM)
                    self.assertIsNone(other.poll())
                finally:
                    if owner.poll() is None:
                        owner.kill()
                    if other.poll() is None:
                        other.kill()

    def test_watchdog_finishes_after_either_owner_dies_and_recovers_after_both_are_killed(self):
        fixture = r'''
import json, os, subprocess, sys, time
from pathlib import Path
import riso_chrome_launcher as launcher
import riso_watchdog as guard
from riso_recovery import acquire_claim, write_state

mode, raw_root = sys.argv[1:3]
root = Path(raw_root)
work = root / "native-fixture"
python = launcher.process_identity(os.getpid())["command"]
if mode == "worker":
    claim, pending = acquire_claim(root, "a" * 64, root, time.monotonic() + 2)
    work.mkdir()
    runtime = {"node": python, "browser": python, "crashpad": "/bin/sleep",
               "ffmpeg": "/bin/sleep", "ffprobe": "/bin/sleep"}
    watcher = guard.start_watchdog(work, runtime, "fixture", pending, int(sys.argv[3]), claim)
    env = {**os.environ, "RISO_WATCHDOG_SOCKET": str(watcher.socket_path)}
    native = subprocess.Popen([sys.executable, __file__, "native", raw_root], env=env)
    write_state(root / "worker.json", {"watchdog": watcher.process.pid, "native": native.pid})
elif mode == "native":
    launcher.register("render-command", python, time.monotonic() + 2)
    nested = subprocess.Popen(["/bin/sleep", "30"])
    browser = subprocess.Popen([sys.executable, __file__, "browser", raw_root])
    write_state(root / "native.json", {"nested": nested.pid, "browser": browser.pid})
else:
    log = work / "render.chrome.log"
    fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    launcher.register("render-browser", python, time.monotonic() + 2, guard.file_identity(log))
    helper = subprocess.Popen(["/bin/sleep", "30"], stderr=fd, start_new_session=True)
    os.close(fd)
    write_state(root / "browser.json", {"helper": helper.pid})
time.sleep(30)
'''
        with tempfile.TemporaryDirectory(prefix="riso-watchdog-test-") as directory:
            root = Path(directory).resolve()
            script = root / "fixture.py"
            script.write_text(fixture)
            env = {**os.environ, "PYTHONPATH": str(SKILL / "scripts"), "PYTHONDONTWRITEBYTECODE": "1"}
            for mode in ("owner", "worker", "both"):
                with self.subTest(mode=mode):
                    attempt = root / mode
                    attempt.mkdir()
                    read_fd, write_fd = os.pipe()
                    process = subprocess.Popen(
                        [sys.executable, str(script), "worker", str(attempt), str(read_fd)],
                        env=env, start_new_session=True, pass_fds=(read_fd,),
                    )
                    os.close(read_fd)
                    observed = {}
                    try:
                        deadline = time.monotonic() + 8
                        for name in ("worker", "native", "browser"):
                            record = attempt / f"{name}.json"
                            while not record.exists() and time.monotonic() < deadline:
                                time.sleep(0.02)
                            observed.update(guard.read_state(record))
                        with self.assertRaisesRegex(guard.RecoveryBlocked, "没有重渲"):
                            riso.acquire_claim(attempt, "a" * 64, attempt, time.monotonic() + 0.1)
                        if mode == "owner":
                            os.close(write_fd)
                            write_fd = None
                        else:
                            if mode == "both":
                                os.kill(observed["watchdog"], signal.SIGKILL)
                            process.kill()
                        process.wait(timeout=8)
                        claim, pending = riso.acquire_claim(attempt, "a" * 64, attempt, time.monotonic() + 8)
                        try:
                            self.assertEqual(pending.exists(), mode == "both")
                            guard.recover_pending(pending, attempt, time.monotonic() + 6)
                            self.assertFalse(pending.exists())
                            for pid in observed.values():
                                self.assertIsNone(guard.process_identity(pid), f"test actor {pid} was not reaped")
                        finally:
                            os.close(claim)
                    finally:
                        if write_fd is not None:
                            os.close(write_fd)
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=2)

    def test_adapter_stops_waiting_when_its_owner_or_watchdog_is_gone(self):
        read_fd, write_fd = os.pipe()
        with (subprocess.Popen(["/bin/sleep", "20"]) as command,
              subprocess.Popen(["/bin/sleep", "20"]) as monitor):
            try:
                monitor.kill()
                monitor.wait(timeout=2)
                with self.assertRaisesRegex(guard.RecoveryBlocked, "监护异常退出"):
                    riso.wait_for_command(command, time.monotonic() + 2, read_fd, SimpleNamespace(process=monitor))
                os.close(write_fd)
                write_fd = None
                with self.assertRaisesRegex(guard.RecoveryBlocked, "父执行器已退出"):
                    riso.wait_for_command(command, time.monotonic() + 2, read_fd, None)
            finally:
                os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)
                command.kill()

    def test_native_frame_count_matches_binary64_renderer_at_half_boundaries(self):
        for duration, frames in ((74 / 24, 93), (74 / 24 - 1e-9, 92), (98 / 24, 122), (202 / 24, 252)):
            with self.subTest(duration=duration):
                actual = subprocess.check_output(["node", "-p", f"Math.round({duration!r} * 30)"], text=True)
                self.assertEqual(int(actual), frames)
                native = {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1",
                          "nb_read_frames": str(frames), "color_range": "pc"}
                run = Mock(return_value=json.dumps({"streams": [native]}))
                self.assertEqual(riso.probe_native({"ffprobe": "ffprobe"}, "native", duration, run), "full")
                self.assertIn("-count_frames", run.call_args.args[0])
                self.assertTrue(run.call_args.kwargs["quiet"])
                native["nb_read_frames"] = str(frames + 1)
                run.return_value = json.dumps({"streams": [native]})
                with self.assertRaisesRegex(ValueError, "Native Riso output changed"):
                    riso.probe_native({"ffprobe": "ffprobe"}, "native", duration, run)

    def test_normalize_mp4_keeps_exact_parent_duration_at_98_frames(self):
        runtime = {key: shutil.which(key) for key in ("ffmpeg", "ffprobe")}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "native.mp4"
            target = Path(directory) / "normalized.mp4"

            def run(argv):
                return subprocess.check_output(argv, text=True, timeout=30)

            run([runtime["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "color=s=1080x1920:r=30",
                 "-t", "4.067", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast",
                 "-bf", "2", "-pix_fmt", "yuv420p", "-colorspace", "bt470bg", "-color_range", "pc",
                 "-movflags", "+faststart", str(source)])
            result = riso.normalize_output(runtime, source, target, 98, "full", run)
            self.assertEqual(result["frames"], 98)

    def test_title_public_text_slots(self):
        for changes in ({"index": "UI"}, {"mast": ["", ""]},
                        {"title": "比朋友还懂你\n是好事吗？"},
                        {"index": "AI", "mast": ["", ""],
                         "title": "比朋友还懂你\n是好事吗？"}):
            value = title_brief()
            value["data"].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(riso.validate_brief(value), value)
        for index in ("XR", "R2", "7"):
            value = title_brief()
            value["data"]["index"] = index
            with self.subTest(index=index):
                riso.validate_brief(value)
        for key, replacement in (("index", "ABC"), ("index", "<b>"),
                                 ("title", "第一行\n第二行\n第三行"),
                                 ("title", "一二三四五六七\n第二行"),
                                 ("mast", ["", "<script>"])):
            value = title_brief()
            value["data"][key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                riso.validate_brief(value)

    def test_formal_recipe_guard_and_format_only_artifact(self):
        from edit.hd.tools import visual_plan, visual_canary, broll_component_executor
        from edit.hd.tests.test_broll_capability_router import (
            _load_router, _visual_intent, _visual_strategy, _strategy_component, avatar_fixture)
        from edit.hd.tests.test_broll_component_executor import _Job

        value = number_brief()
        payload = json.dumps(value, ensure_ascii=False).encode()
        runtime = riso.check_runtime(ROOT)
        directory = tempfile.TemporaryDirectory(prefix="riso-format-only-")
        self.addCleanup(directory.cleanup)
        sample = Path(directory.name) / "format-only-24fps.mp4"
        wrong_rate = Path(directory.name) / "format-only-30fps.mp4"
        # Plain frames test the media contract, not native Riso visuals or qualification.
        for path, fps, frames in ((sample, 24, 120), (wrong_rate, 30, 150)):
            subprocess.run(
                [runtime["ffmpeg"], "-v", "error", "-nostdin", "-n", "-f", "lavfi",
                 "-i", f"color=c=black:s=1080x1920:r={fps}", "-frames:v", str(frames),
                 "-vf", "setsar=1", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", "-pix_fmt", "yuv420p", str(path)],
                check=True, capture_output=True, timeout=60,
            )
        adapter = riso.create_adapter(ROOT, sys.executable, lambda *_: payload)
        binding = riso.create_binding(adapter, payload, sample)
        strategy = _visual_strategy([_strategy_component("scene", "code_generated", layout_slot="full_frame")])
        strategy["segment_id"] = value["source_binding"]["segment_id"]
        strategy["composition"]["avatar"] = avatar_fixture(frames=120)
        context = {"intent": _visual_intent(strategy["segment_id"]), "bindings": {"scene": binding},
                   "candidate_snapshots": {}, "segment_frames": 120}
        visual_plan._prevalidate_draft_bindings(strategy, context["bindings"], 1, 120)
        router = _load_router()
        recipe = router.compile_strategy(strategy, context)
        component = recipe["components"][0]
        contract = {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
        self.assertEqual(component["artifact_contract"], contract)
        self.assertEqual(component["executor"], "reference_adapter")
        self.assertEqual(component["template_id"], "eian-riso-broll/number")
        self.assertIs(broll_component_executor._validate_code_adapter(adapter, component), adapter)
        # Only the approval lookup is synthetic; the compiled recipe and guard are real.
        plan = {"edited_aroll_sha256": value["source_binding"]["aroll_sha256"], "segments": [{
            "segment_id": strategy["segment_id"], "start": 0, "end": 5, "shot_recipe": recipe}]}
        with patch.object(visual_canary, "load_approved_visual_plan", return_value=plan):
            self.assertEqual(adapter.brief_loader(None, recipe, component), payload)
            bad_component = copy.deepcopy(component)
            bad_component["artifact_contract"]["alpha"] = True
            with self.assertRaises(ValueError):
                adapter.brief_loader(None, recipe, bad_component)

        # Probe actual encoded format fixtures without invoking the native renderer.
        probe = riso.create_artifact_probe(runtime["ffprobe"])
        media = probe.probe(sample, "video", component["artifact_contract"])
        self.assertEqual(media["frame_count"], 120)
        self.assertEqual(media["duration"], 5.0)
        with self.assertRaisesRegex(ValueError, "media contract failed"):
            probe.probe(wrong_rate, "video", component["artifact_contract"])
        self.assertEqual(router.riso_output_contract(strategy["components"][0],
                         {"family": "evidence_with_data_overlay"}), contract)

        # Exercise the official component entry with a format fixture standing
        # in for the native render. Only approval of the fixture adapter is synthetic.
        reference = Path(directory.name).resolve() / "reference"
        entrypoint = reference / adapter.entrypoint
        entrypoint.parent.mkdir(parents=True)
        origin = "process-" + "a" * 32
        entrypoint.write_text(
            "from pathlib import Path\nimport fcntl, hashlib, json, os, select, stat, sys\n"
            "assert len(os.environ['BROLL_COMPONENT_INPUT_SHA256']) == 64\n"
            "owner = int(os.environ['BROLL_OWNER_LIFETIME_FD'])\n"
            "assert stat.S_ISFIFO(os.fstat(owner).st_mode)\n"
            "assert fcntl.fcntl(owner, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY\n"
            "assert not select.select([owner], [], [], 0)[0]\n"
            f"Path(sys.argv[-1]).write_bytes(Path({str(sample)!r}).read_bytes())\n"
            "brief = Path(sys.argv[sys.argv.index('--brief') + 1]).read_bytes()\n"
            "print(json.dumps({'status': 'completed', 'invocation_id': os.environ['BROLL_INVOCATION_ID'], "
            "'brief_sha256': hashlib.sha256(brief).hexdigest(), 'native_reused': True, "
            f"'native_source': {{'invocation_id': {origin!r}, 'sha256': 'b' * 64, "
            "'bytes': 123, 'frames': 150, 'input_range': 'full'}}))\n"
        )
        fixture = replace(adapter, dependency_root=reference, entrypoint_sha256=riso.sha(entrypoint),
                          brief_loader=lambda *_: payload)
        argv = list(fixture.argv_template)
        argv[argv.index("--runtime-identity") + 1] = "0" * 64
        updated = replace(fixture, argv_template=tuple(argv))
        job = _Job(Path(directory.name).resolve())
        request = broll_component_executor.ComponentExecutionRequest(recipe, component["component_id"])
        adapters = {"code_generated": {riso.DEPENDENCY_ID: fixture}, "artifact_probe": probe}
        with patch.object(broll_component_executor, "_validate_code_adapter", side_effect=lambda bound, _: bound):
            first = broll_component_executor.execute_component(job, request, adapters=adapters)
            original = broll_component_executor.export_published_execution_binding(job, request, adapters=adapters)
            adapters["code_generated"][riso.DEPENDENCY_ID] = updated
            with patch.object(broll_component_executor, "_freeze_process_binding",
                              side_effect=AssertionError("published replay tried to start the renderer")):
                self.assertEqual(broll_component_executor.execute_component(job, request, adapters=adapters), first)
                self.assertEqual(broll_component_executor.export_published_execution_binding(job, request, adapters=adapters), original)
                argv[argv.index("--implementation-identity") + 1] = "1" * 64
                adapters["code_generated"][riso.DEPENDENCY_ID] = replace(updated, argv_template=tuple(argv))
                with self.assertRaises(broll_component_executor.BrollComponentExecutionError):
                    broll_component_executor.execute_component(job, request, adapters=adapters)
                adapters["code_generated"][riso.DEPENDENCY_ID] = updated
                (job.job_dir / first.job_path).write_bytes(b"tampered published fixture")
                with self.assertRaises(broll_component_executor.BrollComponentExecutionError):
                    broll_component_executor.execute_component(job, request, adapters=adapters)
        self.assertEqual(first.invocation_evidence["native_source"]["invocation_id"], origin)

        for field, replacement in (("layer_role", "overlay"), ("layout_slot", "main"),
                                   ("family", "aroll_with_overlay"), ("family", "no_broll")):
            bad = copy.deepcopy(strategy)
            target = bad["composition"] if field == "family" else bad["components"][0]
            target[field] = replacement
            with self.subTest(field=field, value=replacement):
                with self.assertRaisesRegex(router.RouterError, "Riso requires"):
                    router.riso_output_contract(bad["components"][0], bad["composition"])
                with self.assertRaisesRegex(visual_plan.VisualPlanError, "Riso requires"):
                    visual_plan._prevalidate_draft_bindings(bad, context["bindings"], 1, 120)
                with self.assertRaises(ValueError):
                    router.compile_strategy(bad, context)
                bad_recipe, bad_component = copy.deepcopy(recipe), copy.deepcopy(component)
                if field == "family":
                    bad_recipe["composition"][field] = replacement
                elif field == "layout_slot":
                    bad_component["render_window"][field] = replacement
                else:
                    bad_component[field] = replacement
                with self.assertRaisesRegex(ValueError, "Riso requires"):
                    adapter.brief_loader(None, bad_recipe, bad_component)

    def test_native_checkpoint_revalidates_bytes_and_scope(self):
        with tempfile.TemporaryDirectory(prefix="riso-checkpoint-test-") as directory:
            parent = Path(directory).resolve()
            work = parent / "native-original"
            native = work / "project" / "renders" / "original.mp4"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"strictly checked fixture")
            runtime = {"identity": "1" * 64, "implementation_identity": "2" * 64}
            checkpoint = riso.checkpoint_path(parent, "3" * 64, parent, runtime, "4" * 64, "5" * 64)
            self.assertIsNone(riso.load_checkpoint(checkpoint, parent, "original", 122))
            source = {"invocation_id": "process-" + "a" * 32, "frames": 122,
                      "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                      "bytes": native.stat().st_size, "input_range": "full"}
            riso.save_checkpoint(checkpoint, work, source)
            self.assertEqual(riso.load_checkpoint(checkpoint, parent, "original", 122), (native, source))
            different = riso.checkpoint_path(parent, "6" * 64, parent, runtime, "4" * 64, "5" * 64)
            self.assertIsNone(riso.load_checkpoint(different, parent, "original", 122))
            native.write_bytes(b"changed native bytes")
            with self.assertRaisesRegex(ValueError, "recovery video changed"):
                riso.load_checkpoint(checkpoint, parent, "original", 122)

    def test_native_slots_and_discovery(self):
        from edit.hd.tools import motion_capabilities as motion
        value = number_brief()
        riso.validate_brief(json.dumps(value))
        for key, replacement in (("number", 12.5), ("duration", 4), ("say", "<script>"), ("palette", "custom")):
            bad = copy.deepcopy(value)
            bad["data"][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                riso.validate_brief(bad)
        bad = copy.deepcopy(value)
        bad["template_request"]["numeric_values"] = [13]
        with self.assertRaisesRegex(ValueError, "contradicts"):
            riso.validate_brief(bad)
        catalog = motion.load_catalog(ROOT)
        rows = [row for row in catalog if row.get("dependency_id") == riso.DEPENDENCY_ID]
        self.assertEqual({row["source_route"] for row in rows}, set(riso.FAMILIES))
        self.assertTrue(all(row["status"] == "supported" and row["capability"]["uses"] == ["broll"] for row in rows))
        row = next(row for row in rows if row["source_route"] == "number")
        self.assertEqual(motion._native_input_check(ROOT, row, value)["status"], "pass")
        # Native public fields do not grant transparency, code or a screenshot placeholder.
        bad = copy.deepcopy(value)
        bad["composition"]["alpha"] = True
        with self.assertRaises(ValueError):
            riso.validate_brief(bad)


if __name__ == "__main__":
    unittest.main()

"""Riso brief, process isolation, and format contracts without user Jobs."""
import copy
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
import unittest
from unittest.mock import Mock, patch

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location("riso_native_adapter", SKILL / "scripts/riso_native_adapter.py")
riso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(riso)


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
            fake.write_text('#!/bin/sh\nexec "$TEST_PYTHON" "$TEST_BROWSER"\n')
            fake.chmod(0o700)
            program = root / "fake_chrome.py"
            program.write_text("""
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
print("DevTools listening on ws://127.0.0.1:12345/devtools/browser/test", file=sys.stderr, flush=True)
time.sleep(20)
""")
            node = """
const { spawn } = require('node:child_process');
const { writeFileSync } = require('node:fs');
const { join } = require('node:path');
const chrome = spawn(process.env.CHROME, [], { stdio: ['ignore', 'ignore', 'pipe'] });
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
                    env = {**os.environ, "CHROME": str(fake), "TEST_WORK": str(work),
                           "TEST_PYTHON": sys.executable, "TEST_BROWSER": str(program)}
                    if isolated:
                        runtime = {"browser": str(fake), "chrome_launcher_sha256": riso.sha(SKILL / riso.CHROME_LAUNCHER)}
                        env.update(riso.chrome_environment(work, runtime), RISO_CHROME_LOG=str(work / "chrome.log"))
                    command = [shutil.which("node"), "-e", node]
                    with subprocess.Popen(command, env=env, start_new_session=True) as process:
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
                                try:
                                    os.killpg(process.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                            (work / "release-helper").touch()
                            wait_for(work / "helper-done", 2)

    def test_crashpad_cleanup_only_signals_the_owned_log_writer(self):
        path = Path("/private/riso/render.chrome.log")
        executable = "/Applications/Google Chrome.app/Helpers/chrome_crashpad_handler"
        expected = f"1 {os.getuid()} Tue Nov 10 08:07:16 2026 {executable}"
        signals = []

        def command(argv, **_):
            if argv[0] == "/usr/sbin/lsof":
                self.assertEqual(argv[-1], str(path))
                self.assertEqual(argv[3:5], ["-d", "2"])
                output = "p101\naw\np102\naw\np103\nar\np104\naw\n"
            else:
                pid = int(argv[3])
                output = {
                    101: "" if (101, signal.SIGKILL) in signals else expected,
                    102: expected + "-unrelated",
                    103: expected,
                    104: expected.replace("08:07:16", "08:07:17") if (104, signal.SIGTERM) in signals else expected,
                }[pid]
            return subprocess.CompletedProcess(argv, 0, output, "")

        with (patch.object(riso.subprocess, "run", side_effect=command),
              patch.object(riso.os, "kill", side_effect=lambda pid, sig: signals.append((pid, sig))),
              patch.object(riso.time, "sleep")):
            self.assertEqual(riso.settle_crashpad(path, executable), [101, 104])
        self.assertCountEqual(signals, [(101, signal.SIGTERM), (104, signal.SIGTERM), (101, signal.SIGKILL)])

    def test_native_frame_ties_round_up_like_the_renderer(self):
        native = {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1",
                  "nb_read_frames": "93", "color_range": "pc"}
        output = {"width": 1080, "height": 1920, "avg_frame_rate": "24/1", "sample_aspect_ratio": "1:1",
                  "nb_frames": "74", "pix_fmt": "yuv420p", "color_range": "tv", "duration": "3.083333"}
        run = Mock(side_effect=[json.dumps({"streams": [native]}), "", json.dumps({"streams": [output]})])
        exported = riso.normalize_output({"ffprobe": "ffprobe", "ffmpeg": "ffmpeg"}, "native", "output", 74, run)
        self.assertEqual(exported["frames"], 74)
        self.assertIn("-count_frames", run.call_args_list[0].args[0])
        self.assertTrue(run.call_args_list[0].kwargs["quiet"])

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

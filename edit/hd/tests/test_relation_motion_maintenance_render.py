import unittest, tempfile, json, hashlib, sys, subprocess
from unittest import mock
from pathlib import Path
from edit.hd.tests.test_relation_motion_renderer import brief
from edit.hd.tools.relation_motion_maintenance_render import render_relation_motion_maintenance
import copy
from edit.hd.tools.relation_motion_maintenance_render import validate_relation_media_probe, RelationMotionRenderError

def probe():
    return {"streams":[{"codec_type":"video","codec_name":"h264","width":1080,"height":1920,"pix_fmt":"yuv420p","r_frame_rate":"24/1","avg_frame_rate":"24/1","nb_read_frames":"120","sample_aspect_ratio":"1:1","duration":"5.0","tags":{"rotate":"0"},"side_data_list":[{"rotation":0}]}],"format":{"duration":"5.0"}}

class ProbeTests(unittest.TestCase):
    def test_valid_probe(self): validate_relation_media_probe(probe(), 120)
    def test_bad_shapes_and_stream_contracts_reject(self):
        for change in (lambda p: p.update(streams=[]), lambda p: p["streams"].append({}), lambda p: p["streams"][0].update(codec_name="vp9"), lambda p: p["streams"][0].update(width=1), lambda p: p["streams"][0].update(nb_read_frames="119"), lambda p: p["streams"][0].update(tags={"rotate":"1"}), lambda p: p["streams"][0].update(side_data_list=[{"rotation":1}])):
            value = probe(); change(value)
            with self.assertRaises(RelationMotionRenderError): validate_relation_media_probe(value, 120)
    def test_duration_is_strict_and_finite(self):
        for duration in (True, 47, 241, 120.0):
            with self.assertRaises(RelationMotionRenderError): validate_relation_media_probe(probe(), duration)
        value = probe(); value["format"]["duration"] = "nan"
        with self.assertRaises(RelationMotionRenderError): validate_relation_media_probe(value, 120)
    def test_fractional_probe_duration_and_strict_frame_count(self):
        value = probe(); value["streams"][0]["nb_read_frames"] = "121"; value["streams"][0]["duration"] = "5.041667"; value["format"]["duration"] = "5.041667"
        validate_relation_media_probe(value, 121)
        for bad in (120.9, True, "120.9", "inf"):
            value = probe(); value["streams"][0]["nb_read_frames"] = bad
            with self.assertRaises(RelationMotionRenderError): validate_relation_media_probe(value, 120)
    def test_optional_probe_sections_have_controlled_shape_errors(self):
        for key, bad in (("tags", None), ("tags", []), ("side_data_list", None), ("side_data_list", [None]), ("side_data_list", [123])):
            value = probe(); value["streams"][0][key] = bad
            with self.assertRaises(RelationMotionRenderError): validate_relation_media_probe(value, 120)

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = self.root / "job"
        self.job.mkdir()
        self.out = self.root / "candidate"
        value = brief(2)
        self.bundle = {
            "brief": value,
            "brief_sha256": hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "renderer_sha256": hashlib.sha256((Path(__file__).parents[1] / "tools/relation_motion_renderer.cjs").read_bytes()).hexdigest(),
            "workflow_sha256": "b" * 64,
            "content_analysis_sha256": "c" * 64,
        }
        self.calls = []
        self.fail_stage = None
        self.missing_frame = False
        self.mutate_video = False
        target = "edit.hd.tools.relation_motion_maintenance_render"
        self.bridge = mock.patch(target + ".build_approved_relation_brief", return_value=self.bundle).start()
        self.process = mock.patch(target + "._run_checked", side_effect=self.run_process, create=True).start()
        self.addCleanup(mock.patch.stopall)

    def run_process(self, cmd, **kwargs):
        if "--html" == cmd[-1]:
            stage = "html"
        elif "--output" in cmd:
            stage = "capture"
        elif "-show_streams" in cmd:
            stage = "probe"
        elif cmd[-3:] == ["-f", "null", "-"]:
            stage = "decode"
        else:
            stage = "encode"
        self.calls.append(stage)
        if stage == self.fail_stage:
            raise RuntimeError(stage + " failed")
        if stage == "capture":
            frames = Path(cmd[cmd.index("--output") + 1])
            self.assertFalse(frames.exists())
            frames.mkdir()
            for i in range(119 if self.missing_frame else 120):
                (frames / f"frame-{i:06d}.png").write_bytes(b"png")
            (frames / "boundary.png").write_bytes(b"png")
        if stage == "encode":
            self.assertIn("-n", cmd)
            self.assertIn("setsar=1", cmd)
            Path(cmd[-1]).write_bytes(b"mp4")
        if stage == "decode" and self.mutate_video:
            (self.out / "candidate.mp4").write_bytes(b"changed")
        return mock.Mock(stdout=json.dumps(probe()) if stage == "probe" else "<html></html>", returncode=0)

    def render(self):
        return render_relation_motion_maintenance(
            job_dir=self.job, draft={}, title="x", source_ids=["a", "b"], hub_id="h",
            output_dir=self.out, node_executable="node", playwright_module="pw",
            browser_executable="browser", ffmpeg_executable="ffmpeg", ffprobe_executable="ffprobe",
        )

    def assert_failure(self, message):
        with self.assertRaisesRegex(RelationMotionRenderError, message):
            self.render()
        self.assertFalse((self.out / "maintenance-receipt.json").exists())

    def test_happy_path(self):
        result = self.render()
        self.assertEqual(self.calls, ["html", "capture", "encode", "probe", "decode"])
        self.assertEqual(self.bridge.call_count, 2)
        self.assertFalse(result["formal_eligibility"])
        self.assertEqual(json.loads((self.out / "maintenance-receipt.json").read_text()), result)

    def test_low_level_renderer_has_no_job_or_approval_side_effects(self):
        from edit.hd.tools import relation_motion_maintenance_render as module
        self.assertTrue(hasattr(module, "render_relation_brief_artifact"))
        artifact = module.render_relation_brief_artifact(
            brief=self.bundle["brief"], output_dir=self.out,
            node_executable="node", playwright_module="pw", browser_executable="browser",
            ffmpeg_executable="ffmpeg", ffprobe_executable="ffprobe",
        )
        self.bridge.assert_not_called()
        self.assertFalse((self.out / "maintenance-receipt.json").exists())
        self.assertEqual(Path(artifact["candidate_path"]).read_bytes(), b"mp4")
        self.assertNotIn("formal_eligibility", artifact)
        self.assertNotIn("workflow_sha256", artifact)

    def test_capture_failure_stops_before_encode(self):
        self.fail_stage = "capture"
        self.assert_failure("capture failed")
        self.assertEqual(self.calls, ["html", "capture"])

    def test_bad_brief_hash_stops_before_processes(self):
        self.bundle["brief_sha256"] = "bad"
        self.assert_failure("brief hash mismatch")
        self.assertEqual(self.calls, [])

    def test_missing_frame_stops_before_encode(self):
        self.missing_frame = True
        self.assert_failure("capture frame set invalid")
        self.assertEqual(self.calls, ["html", "capture"])

    def test_second_bridge_drift_rejects_receipt(self):
        altered = dict(self.bundle, workflow_sha256="changed")
        self.bridge.side_effect = [self.bundle, altered]
        self.assert_failure("approved identity drifted")
        self.assertEqual(self.calls[-1], "decode")

    def test_decode_failure_rejects_receipt(self):
        self.fail_stage = "decode"
        self.assert_failure("decode failed")
        self.assertEqual(self.calls[-1], "decode")

    def test_video_changed_during_validation_rejects_receipt(self):
        self.mutate_video = True
        self.assert_failure("media changed")

    def test_decode_is_strict_and_single_threaded(self):
        self.render()
        command = self.process.call_args_list[-1].args[0]
        for flag in ("-xerror", "-nostdin", "-threads", "-map"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("-threads") + 1], "1")

    def test_indirect_symlink_ancestor_rejected(self):
        real = self.root / "real"
        (real / "sub").mkdir(parents=True)
        link = self.root / "link"
        link.symlink_to(real, target_is_directory=True)
        self.out = link / "sub" / "candidate"
        self.assert_failure("symlink")
        self.assertEqual(self.calls, [])

    def test_dangling_output_symlink_rejected(self):
        self.out.symlink_to(self.root / "missing")
        self.assert_failure("symlink")
        self.assertEqual(self.calls, [])


class ProcessTests(unittest.TestCase):
    def test_runner_success_and_nonzero(self):
        from edit.hd.tools import relation_motion_maintenance_render as module
        self.assertTrue(hasattr(module, "_run_checked"))
        result = module._run_checked([sys.executable, "-c", "print('ok')"], timeout=5)
        self.assertEqual(result.stdout.strip(), "ok")
        with self.assertRaisesRegex(RelationMotionRenderError, "process failed"):
            module._run_checked([sys.executable, "-c", "raise SystemExit(2)"], timeout=5)

    def test_runner_timeout_is_controlled(self):
        from edit.hd.tools import relation_motion_maintenance_render as module
        self.assertTrue(hasattr(module, "_run_checked"))
        with self.assertRaisesRegex(RelationMotionRenderError, "timed out"):
            module._run_checked([sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.1)

    def test_timeout_terminates_descendant(self):
        from edit.hd.tools import relation_motion_maintenance_render as module
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-pid"
            script = (
                "import subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
                "open(sys.argv[1],'w').write(str(child.pid)); time.sleep(20)"
            )
            with self.assertRaisesRegex(RelationMotionRenderError, "timed out"):
                module._run_checked([sys.executable, "-c", script, str(marker)], timeout=0.5)
            self.assertTrue(marker.exists())
            result = subprocess.run(["ps", "-o", "stat=", "-p", marker.read_text()], capture_output=True, text=True)
            self.assertTrue(not result.stdout.strip() or result.stdout.strip().startswith("Z"), result.stdout)

"""Synthetic geometry, not detected landmarks or a human approval."""
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


def avatar_fixture(frames=24, source_sha256="d" * 64, *, x=180, y=400, size=720):
    def point(u, v):
        return [x + u * size, y + v * size]
    landmarks = {
        "head_top": point(.5, .08),
        "face_box": [x + .28 * size, y + .18 * size, .44 * size, .34 * size],
        "chin": point(.5, .54), "neck": point(.5, .63),
        "shoulders": [point(.12, .76), point(.88, .76)],
    }
    return {
        "profile": {"schema_version": 1, "framing": "head-shoulders",
                    "source_sha256": source_sha256, "diameter": 256,
                    "border_width": 8, "border_color": "#FFFFFF"},
        "position": {"x": 768, "y": 1400},
        "crop": {"size": size, "anchors": [
            {"frame": frame, "x": x, "y": y, "landmarks": copy.deepcopy(landmarks)}
            for frame in (0, frames // 2, frames - 1)
        ]},
    }


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/avatar_profile.py"
    spec = importlib.util.spec_from_file_location("skill_avatar_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AvatarProfileTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_center_left_right_calibrations_roundtrip_without_mutating_input(self):
        for x in (0, 180, 360):
            value = avatar_fixture(x=x)
            original = copy.deepcopy(value)
            checked = self.module.validate_avatar(value, frames=24)
            self.assertEqual(checked, original)
            checked["profile"]["diameter"] = 200
            self.assertEqual(value, original)

    def test_rejects_missing_head_only_shoulder_clipped_and_wrong_headroom(self):
        invalid = [None, {}]
        for label in ("face", "shoulder", "head", "chin", "neck"):
            value = avatar_fixture()
            landmarks = value["crop"]["anchors"][1]["landmarks"]
            if label == "face":
                landmarks["face_box"][2] = 600
            elif label == "shoulder":
                landmarks["shoulders"] = [[266.4, 1090], [813.6, 1090]]
            elif label == "head":
                landmarks["head_top"][1] = 400
            elif label == "chin":
                landmarks["chin"][1] = 399
            else:
                del landmarks["neck"]
            invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module.validate_avatar(value, frames=24)

    def test_tilted_shoulders_do_not_require_the_neck_above_both_shoulders(self):
        value = avatar_fixture()
        for anchor in value["crop"]["anchors"]:
            anchor["landmarks"]["shoulders"][1][1] = anchor["y"] + .60 * value["crop"]["size"]
        self.assertEqual(self.module.validate_avatar(value, frames=24), value)

    def test_rejects_invalid_geometry_clock_and_numeric_types(self):
        for branch, key, bad in (
            ("profile", "diameter", True), ("profile", "border_width", -1),
            ("profile", "border_color", "white;null"),
            ("position", "x", -1), ("position", "y", 1500),
            ("crop", "size", 1082), ("crop", "size", float("nan")),
            ("profile", "source_sha256", ""),
        ):
            value = avatar_fixture()
            value[branch][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                self.module.validate_avatar(value, frames=24)
        for frame in (22, True, float("inf")):
            value = avatar_fixture()
            value["crop"]["anchors"][-1]["frame"] = frame
            with self.assertRaises(ValueError):
                self.module.validate_avatar(value, frames=24)
        value = avatar_fixture()
        value["crop"]["anchors"].pop(1)
        with self.assertRaises(ValueError):
            self.module.validate_avatar(value, frames=24)

    def test_plan_shares_profile_but_not_placement_or_crop(self):
        def segment(avatar, start):
            return {"start": start, "end": start + 1,
                    "visual_strategy": {"composition": {
                        "presenter_mode": "bottom_window", "avatar": avatar}}}
        a, b = avatar_fixture(x=0), avatar_fixture(x=360)
        b["position"]["x"] = 40
        segments = [segment(a, 0), segment(b, 1)]
        self.module.validate_plan_avatars(segments, source_sha256="d" * 64)
        for field, bad in (("diameter", 220), ("source_sha256", "e" * 64)):
            changed = copy.deepcopy(segments)
            changed[1]["visual_strategy"]["composition"]["avatar"]["profile"][field] = bad
            with self.assertRaises(ValueError):
                self.module.validate_plan_avatars(changed, source_sha256="d" * 64)

    def test_hidden_cannot_keep_unused_avatar_and_missing_bottom_is_rejected(self):
        for composition in ({"presenter_mode": "bottom_window"},
                            {"presenter_mode": "hidden", "avatar": avatar_fixture()}):
            with self.assertRaises(ValueError):
                self.module.validate_plan_avatars([
                    {"start": 0, "end": 1, "visual_strategy": {"composition": composition}}
                ])

    def test_filter_uses_calibrated_crop_and_circle_not_historical_constants(self):
        value = avatar_fixture(x=0)
        graph = ";".join(self.module.filter_chain(value, frames=24))
        self.assertIn("crop=", graph)
        self.assertIn("scale=256:256", graph)
        self.assertIn("hypot", graph)
        self.assertNotIn("960:960:60:480", graph)
        self.assertNotIn("pad=360:540", graph)
        self.assertTrue(graph.endswith("[presenter]"))

    def test_moving_crop_interpolates_position_on_local_frame_clock(self):
        value = avatar_fixture(x=0)
        for anchor, new_x in zip(value["crop"]["anchors"], (0, 180, 360)):
            delta = new_x - anchor["x"]
            anchor["x"] = new_x
            landmarks = anchor["landmarks"]
            for key in ("head_top", "chin", "neck", "face_box"):
                landmarks[key][0] += delta
            for point in landmarks["shoulders"]:
                point[0] += delta
        self.module.validate_avatar(value, frames=24)
        self.assertEqual(self.module.crop_at(value, 6), (720, 90.0, 400.0))
        self.assertEqual(self.module.crop_at(value, 23), (720, 360.0, 400.0))
        graph = ";".join(self.module.filter_chain(value, frames=24))
        self.assertIn("(n-", graph)
        self.assertIn("setpts=PTS-STARTPTS", graph)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for native boundary check")
    def test_native_dense_anchors_and_odd_diameter_preserve_output_extent(self):
        value = avatar_fixture(frames=128)
        value["profile"]["diameter"] = 255
        prototype = value["crop"]["anchors"][0]
        value["crop"]["anchors"] = [{**copy.deepcopy(prototype), "frame": n} for n in range(128)]
        graph = ";".join(self.module.filter_chain(value, frames=128))
        result = subprocess.run([
            shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-filter_complex_threads", "1",
            "-f", "lavfi", "-i", "color=red:s=1080x1920:r=24:d=6", "-filter_complex", graph,
            "-map", "[presenter]", "-frames:v", "1", "-threads", "1", "-pix_fmt", "rgba",
            "-f", "rawvideo", "pipe:1",
        ], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-3000:])
        self.assertEqual(len(result.stdout), (255 + 16) ** 2 * 4)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for native geometry check")
    def test_native_wrong_source_dimensions_fail_instead_of_reframing(self):
        graph = ";".join(self.module.filter_chain(avatar_fixture(), frames=24))
        result = subprocess.run([
            shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-filter_complex_threads", "1",
            "-f", "lavfi", "-i", "color=red:s=1080x1080:r=24:d=1", "-filter_complex", graph,
            "-map", "[presenter]", "-frames:v", "1", "-threads", "1", "-f", "null", "-",
        ], capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    def test_integration_layout_accepts_nondefault_profile_extents(self):
        path = Path(__file__).with_name("render_avatar_integration.py")
        spec = importlib.util.spec_from_file_location("avatar_integration_qa", path)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        for diameter, border in ((256, 8), (320, 8), (256, 24), (255, 7)):
            for left in (False, True):
                value = avatar_fixture()
                value["profile"].update(diameter=diameter, border_width=border)
                value["position"] = harness.qa_position(value["profile"], left=left)
                self.module.validate_avatar(value, frames=24)

    def test_integration_rejects_wrong_portrait_size_before_creating_outputs(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "wrong.png"
            Image.new("RGB", (1080, 1080)).save(frame)
            value = avatar_fixture(frames=48, source_sha256=hashlib.sha256(frame.read_bytes()).hexdigest())
            calibration = root / "calibration.json"
            calibration.write_text(json.dumps(value))
            output = root / "output"
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("render_avatar_integration.py")),
                "--project-root", str(Path.cwd()), "--portrait-frame", str(frame),
                "--calibration-json", str(calibration), "--output", str(output),
                "--ffmpeg", "must-not-run", "--ffprobe", "must-not-run",
            ], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("portrait must be 1080x1920", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

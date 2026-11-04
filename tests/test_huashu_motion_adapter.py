"""Checks the real Huashu input seam without rendering or provider calls."""
import importlib.util
import base64
import json
import hashlib
import mimetypes
import os
from pathlib import Path
import socketserver
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("huashu_test", ROOT / "scripts/huashu_motion_adapter.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def brief():
    return {"schema_version": 1, "dependency_id": h.DEPENDENCY_ID,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-test", "start": 1, "end": 5},
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 96},
        "template_request": {"semantic_family": "process_flow", "information_units": 1,
            "numeric_values": [], "numeric_scale": "not_applicable"},
        "props": {"data": {"grammar": "y1_kurzgesagt", "data": {"center": "检索", "flow": True},
            "safe": {"top": 80, "bottom": 600}, "cues": [{"kind": "point", "at": .5, "text": "索引"}]}},
        "assets": []}


def native_task_brief(template="scene", alpha=False):
    """Schema-2 technical contract input; this does not approve or run a Job."""
    return {"schema_version": 2, "dependency_id": "huashu-art-motion", "job_id": "huashu-contract-fixture",
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-fixture", "start": 0, "end": 4},
        "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 96}, "alpha": alpha,
        "canvas_transport": "identity", "template_id": template, "native_options": [],
        "semantic_goal": "原生接入技术验证", "transcript": "仅用于技术验证",
        "task_source": {"semantic_row_id": "technical-fixture", "quote": "仅用于技术验证",
            "semantic": "原生接入技术验证", "required_change": "验证真实原生输入契约", "component_brief": "技术验证，不代表用户验收"},
        "template_request": {"semantic_family": "technical_fixture", "information_units": 1,
            "numeric_values": [], "numeric_scale": "not_applicable"},
        "word_anchors": [{"text": "仅用于技术验证", "start": 0, "end": 4}],
        "speech": {"job_path": "inputs/fixture.wav", "sha256": "b" * 64, "byte_count": 1},
        "materials": [], "authorization": {"paid_generation": False, "purpose": "technical_contract_fixture"},
        "project_directory": "native-projects/huashu-fixture", "result_record_path": "native-inputs/huashu-fixture/result.json"}


class HuashuInputTests(unittest.TestCase):
    def test_common_schema2_uses_original_huashu_catalog_options_and_alpha(self):
        import motion_native_skill_adapter as native
        for template, alpha in (("grammar-t1-3b1b", True), ("style-25-ghibli", False)):
            b = native_task_brief(template, alpha)
            native.validate_brief(json.dumps(b))
            self.assertEqual(native._template(b), ROOT / "vendor/huashu-art-motion")
        b = native_task_brief("grammar-y1-kurzgesagt")
        b["native_options"] = ["style-17-ink"]
        native.validate_brief(json.dumps(b))
        native._template(b)
        b["native_options"] = ["invented-style"]
        with self.assertRaisesRegex(ValueError, "options"):
            native._template(b)
        with self.assertRaisesRegex(ValueError, "alpha paths"):
            native.validate_brief(json.dumps(native_task_brief("scene", True)))

    def test_huashu_production_exclusions_apply_to_primary_options_and_usage(self):
        import motion_native_skill_adapter as native
        excluded = ("scene", "style-55-dunhuang", "style-37-rick-morty")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "spec.json"
            spec.write_text('{"grammar":"t1_3b1b"}')
            ref = native.descriptor(root, spec)
            call = {"project_files": [ref]}
            for template in excluded:
                with self.subTest(template=template):
                    with self.assertRaisesRegex(ValueError, "qualified portrait"):
                        native._template(native_task_brief(template))
                    b = native_task_brief("grammar-t1-3b1b")
                    b["native_options"] = [template]
                    with self.assertRaisesRegex(ValueError, "qualified portrait"):
                        native._template(b)
                    b["native_options"] = []
                    usage = [{"card_id": card, "variant": None, "purpose": "实际原生生产路线",
                              "implementation_refs": [ref]} for card in (b["template_id"], template)]
                    with self.assertRaisesRegex(ValueError, "qualified portrait"):
                        native._validate_native_usage(root, b, call, usage)

    def test_common_huashu_usage_binds_actual_authored_input(self):
        import motion_native_skill_adapter as native
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = root / "native-projects/fixture/spec.json"
            spec.parent.mkdir(parents=True)
            spec.write_text('{"grammar":"t1_3b1b","theme":"wood","finish":"film"}')
            ref = native.descriptor(root, spec)
            call = {"project_files": [ref]}
            b = native_task_brief("grammar-t1-3b1b", True)
            usage = [{"card_id": b["template_id"], "variant": None, "purpose": "技术样片原生输入",
                      "implementation_refs": [ref]}]
            self.assertEqual(native._validate_native_usage(root, b, call, usage), usage)
            spec.write_text('{"grammar":"t1_3b1b","theme":"ink"}')
            with self.assertRaisesRegex(ValueError, "changed"):
                native._validate_native_usage(root, b, call, usage)

    def test_full_native_catalog_preserves_research_status_and_real_routes(self):
        catalog = h.native_templates(ROOT)
        grammars = [row for row in catalog.values() if row["route"] == "grammar"]
        styles = [row for row in catalog.values() if "style" in row]
        self.assertEqual(len(grammars), 8)
        self.assertEqual(len(styles), 53)
        self.assertEqual(sum(row["state"] == "research" for row in styles), 17)
        self.assertFalse(catalog["scene"]["alpha"])
        self.assertTrue(catalog["grammar-t1-3b1b"]["alpha"])
        self.assertEqual(catalog["style-25-ghibli"]["state"], "native_recipe")

    def test_full_native_scene_and_alpha_use_original_engine_and_untrimmed_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / "native-projects/current"
            project.mkdir(parents=True)
            engine = h.prepare_native_project(project, ROOT)
            (project / "out").mkdir()
            (engine / "eras.js").write_text("window.ERAS=[{id:'current',dur:4}];")
            b = {"template_id": "scene", "alpha": False,
                "project_directory": "native-projects/current",
                "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 96}}
            runtime = {"tools": {"python": sys.executable}}
            native = ROOT / "vendor/huashu-art-motion"
            argv = [sys.executable, "engine/render.py", "--width", "1080", "--height", "1920",
                    "--fps", "24", "--to", "4", "--out", "out/scene.mp4"]
            self.assertEqual(h.native_render_command(root, b, argv, runtime, native)[2], project / "out/scene.mp4")
            b.update(template_id="grammar-t1-3b1b", alpha=True)
            spec = {"grammar": "t1_3b1b", "duration": 4, "fps": 24, "width": 1080, "height": 1920,
                    "alpha": True, "theme": "wood", "finish": "film", "data": {},
                    "cues": [{"at": 0, "kind": "point", "text": "每次前进一步"}]}
            payload = json.dumps(spec, ensure_ascii=False).encode()
            (project / "spec.json").write_bytes(payload)
            argv = [sys.executable, "engine/render.py", "--spec", "spec.json", "--alpha", "--out", "out/alpha.mov"]
            self.assertEqual(h.native_render_command(root, b, argv, runtime, native)[2], project / "out/alpha.mov")
            self.assertEqual((project / "spec.json").read_bytes(), payload)
            with self.assertRaisesRegex(ValueError, "actual native alpha"):
                h.native_render_command(root, b, [a for a in argv if a != "--alpha"], runtime, native)
            (engine / "render.py").write_text("# replacement renderer")
            with self.assertRaisesRegex(ValueError, "engine source changed"):
                h.native_render_command(root, b, argv, runtime, native)

    def test_native_child_argv_path_queue_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = root / "native_entry.py"
            spec = root / "spec.json"
            output = root / "output.json"
            entry.write_text(
                "import json, pathlib, socketserver, sys\n"
                "pathlib.Path(sys.argv[4]).write_text(json.dumps({\n"
                "'argv': sys.argv, 'path0': sys.path[0],\n"
                "'queue': socketserver.TCPServer.request_queue_size\n"
                "}))\n"
                "raise SystemExit(17)\n",
                encoding="utf-8",
            )
            spec.write_text("{}", encoding="utf-8")
            parent_queue = socketserver.TCPServer.request_queue_size
            argv = h.native_render_argv(sys.executable, entry, spec, output)
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                subprocess.run(argv, check=True, capture_output=True, text=True)
            self.assertEqual(caught.exception.returncode, 17)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["argv"], [str(entry.resolve()), "--spec", str(spec), "--out", str(output)])
            self.assertEqual(report["path0"], str(entry.resolve().parent))
            self.assertEqual(report["queue"], 64)
            self.assertEqual(socketserver.TCPServer.request_queue_size, parent_queue)

    def test_frozen_svg_and_png_keep_media_type_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "native"
            target.mkdir()
            svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2"/></svg>'
            png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1sAAAAASUVORK5CYII=")
            assets, records, descriptors = [], {}, []
            try:
                for ref, suffix, data in (("excerpt", ".svg", svg), ("photo", ".png", png)):
                    source = root / (ref + suffix)
                    source.write_bytes(data)
                    descriptor = os.open(source, os.O_RDONLY)
                    descriptors.append(descriptor)
                    digest = hashlib.sha256(data).hexdigest()
                    assets.append({"media_ref": ref, "job_path": "inputs/" + source.name, "sha256": digest})
                    records[ref] = {"fd": descriptor, "sha256": digest, "byte_length": len(data)}
                paths = h.materialize_frozen_media(target, assets, records)
                self.assertEqual(mimetypes.guess_type(paths["excerpt"])[0], "image/svg+xml")
                self.assertEqual(mimetypes.guess_type(paths["photo"])[0], "image/png")
                self.assertEqual(Path(paths["excerpt"]).read_bytes(), svg)
                self.assertEqual(Path(paths["photo"]).read_bytes(), png)
                records["excerpt"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "media bytes differ"):
                    h.materialize_frozen_media(target, assets, records)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)

    def test_odd_frame_native_output_has_exact_24fps_duration(self):
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / "native.mp4", Path(temp) / "normalized.mp4"
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=white:s=1080x1920:r=24", "-frames:v", "209", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-video_track_timescale", "12288", "-movie_timescale", "1000", str(source)],
                check=True, capture_output=True, timeout=30)
            h.normalize_native_output(source, output, ffmpeg=ffmpeg, ffprobe=ffprobe,
                                      expected_frames=209)
            stream = json.loads(subprocess.check_output([ffprobe, "-v", "error",
                "-show_streams", "-of", "json", str(output)], timeout=30))["streams"][0]
            self.assertEqual(stream["nb_frames"], "209")
            self.assertEqual(stream["avg_frame_rate"], "24/1")
            self.assertEqual(stream["time_base"], "1/24")
            self.assertLessEqual(abs(float(stream["duration"]) - 209 / 24), 1e-6)

    def test_native_point_and_unique_frame_clock(self):
        b = brief()
        native = h.native_spec(b)
        self.assertEqual(native["cues"], b["props"]["data"]["cues"])
        self.assertEqual((native["width"], native["height"], native["fps"], native["duration"]), (1080, 1920, 24, 4))
        self.assertFalse(native["alpha"])
        self.assertEqual(h.local_cue_frame(60, 48), .5)

    def test_rejects_the_original_wrong_cue_names(self):
        for kind in ("photo", "caption", "line", "label", "number"):
            b = brief()
            b["props"]["data"]["cues"][0]["kind"] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                h.validate_brief(b)

    def test_rejects_self_certification_and_second_clock(self):
        for section, key, value in (("source_binding", "status", "verified_third_party"),
                                    ("canvas", "duration", 4)):
            b = brief()
            b[section][key] = value
            with self.subTest(section=section), self.assertRaises(ValueError):
                h.validate_brief(b)
        b = brief()
        b["props"]["data"]["duration"] = 4
        with self.assertRaises(ValueError):
            h.validate_brief(b)

    def test_rejects_misaligned_clock_missing_target_and_unbound_image(self):
        cases = []
        b = brief(); b["canvas"]["duration_in_frames"] = 95; cases.append(b)
        b = brief(); b["props"]["data"]["cues"][0]["at"] = .51; cases.append(b)
        b = brief(); b["props"]["data"]["cues"][0] = {"at": 1, "kind": "highlight", "data": {"index": 0}}; cases.append(b)
        b = brief(); b["props"]["data"]["cues"][0]["image"] = "/tmp/unbound.png"; cases.append(b)
        for b in cases:
            with self.subTest(b=b), self.assertRaises(ValueError):
                h.validate_brief(b)


if __name__ == "__main__":
    unittest.main()

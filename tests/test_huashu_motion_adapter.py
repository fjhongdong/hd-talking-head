"""Checks the real Huashu input seam without rendering or provider calls."""
import importlib.util
import json
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
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


class HuashuInputTests(unittest.TestCase):
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

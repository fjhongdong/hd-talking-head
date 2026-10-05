import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "skill-development/hd-talking-head/scripts/adu_motion_adapter.py"
spec = importlib.util.spec_from_file_location("adu_motion_adapter", MODULE_PATH)
adu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adu)


class AduMotionAdapterTest(unittest.TestCase):
    def native_inputs(self):
        manifest = json.loads((ROOT / "skill-development/vendor/adu-motion-video/packs/classic-performance/1.0.0/manifest.json").read_bytes())
        return next(s for s in manifest["scenes"] if s["id"] == "decompose-and-consolidate")["inputExample"]

    def test_native_choreography_prepares_actual_frozen_browser_files(self):
        digest = hashlib.sha256(b"aroll").hexdigest()
        inputs = self.native_inputs()
        # This is a compiler fixture using source-time-compatible anchors, not
        # a claim that a synthetic voice was accepted as a real video sample.
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "scene"
            prepared = adu.prepare_scene(
                source_binding={"aroll_sha256": digest, "segment_id": "seg-adu", "start": 0, "end": 18},
                frames=432, cues=[{"id": "concept", "at": 2.233}, {"id": "decompose", "at": 5.666}, {"id": "result", "at": 14.2}],
                inputs=inputs, source_text="编译夹具，不作为真实口播验收。",
                branches=[part["label"] for part in inputs["parts"]], result=inputs["result"]["conclusion"],
                part_cues=[6.1, 7.6, 8.8], project_root=ROOT, output_dir=output)
            self.assertEqual(prepared["timed_scene"]["fps"], 60)
            self.assertEqual(prepared["composition"]["frames"], 432)
            self.assertEqual(len(prepared["project"]["files"]), 7)
            self.assertIn("window.ADU_TEXTS=", (output / "config.js").read_text())
            self.assertIn("window.MACRO_PLAN=", (output / "config.js").read_text())
            self.assertNotIn("camAt(", (output / "scenes.js").read_text())
            self.assertNotIn("scale(.5625)", (output / "style.css").read_text())
            self.assertTrue((output / "macro_runtime.js").is_file())
            brief = {"schema_version": 1, "dependency_id": adu.DEPENDENCY_ID,
                "source_binding": prepared["source_binding"],
                "template_request": {"semantic_family": adu.SEMANTIC_FAMILY, "information_units": 3,
                    "numeric_values": [], "numeric_scale": "not_applicable"},
                "composition": {"id": prepared["scene_id"], **prepared["composition"]},
                "files": [{"media_ref": name.replace(".", "-"), "job_path": "scene/" + name,
                    "scene_path": name, "sha256": adu.sha(output / name)} for name in sorted(adu.SCENE_FILES)],
                "workflow_media_ref": "workflow-json"}
            adu.validate_brief(json.dumps(brief))
            adu.validate_workflow(brief, output, ROOT / "skill-development/vendor/adu-motion-video")
            (output / "config.js").write_text((output / "config.js").read_text().replace('"fps": 24', '"fps": 30', 1))
            with self.assertRaisesRegex(ValueError, "native text bindings changed"):
                adu.validate_workflow(brief, output, ROOT / "skill-development/vendor/adu-motion-video")
            brief["template_request"]["numeric_values"] = None
            with self.assertRaisesRegex(ValueError, "Invalid numeric request"):
                adu.validate_brief(json.dumps(brief))

    def test_real_word_anchors_are_rejected_before_source_generation(self):
        inputs = self.native_inputs()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must-not-exist"
            kwargs = dict(source_binding={"aroll_sha256": "a" * 64, "segment_id": "seg-adu", "start": 315.2916666666667, "end": 333.2916666666667},
                frames=432, cues=[{"id": "concept", "at": 318.8716666666667}, {"id": "decompose", "at": 321.625}, {"id": "result", "at": 330.1666666666667}],
                inputs=inputs, source_text="时码拒绝检查，不是合格的读书口播。",
                branches=[part["label"] for part in inputs["parts"]], result=inputs["result"]["conclusion"],
                part_cues=[321.625, 325.005, 327.325], project_root=ROOT, output_dir=output)
            with self.assertRaisesRegex(ValueError, "word anchor conflicts"):
                adu.prepare_scene(**kwargs)
            self.assertFalse(output.exists())
            kwargs["frames"] = 120
            with self.assertRaisesRegex(ValueError, "14.7 seconds"):
                adu.prepare_scene(**kwargs)


if __name__ == "__main__":
    unittest.main()

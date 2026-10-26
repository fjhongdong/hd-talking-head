import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PROJECT))
import compose_visual_plan as compose
import run_stage
from edit.hd.tools import visual_plan


class ComposeVisualPlanTests(unittest.TestCase):
    def test_word_cut_times_use_corrected_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            (job / "05-speech-cleanup").mkdir()
            (job / "06-edit-structure").mkdir()
            original = [{"text": "语", "start": 1.0, "end": 1.25}]
            corrected = [{"text": "宇", "start": 1.0, "end": 1.25}]
            (job / "05-speech-cleanup/report.json").write_text(json.dumps({
                "transcript": {"words": original}}))
            (job / "05-speech-cleanup/word-transcript.json").write_text(json.dumps({
                "version": 1, "words": corrected}))
            (job / "06-edit-structure/timeline-map.json").write_text(json.dumps({
                "segments": [{"source_start": 0.8, "source_end": 1.5,
                              "timeline_start": 0.0, "timeline_end": 0.7}]}))
            words = compose._word_cut_times(job)
            self.assertEqual(words[0]["text"], "宇")
            self.assertAlmostEqual(words[0]["cut"], 0.2)
            self.assertAlmostEqual(words[0]["cut_end"], 0.45)

    def test_quantize_rejects_zero_frame_window(self):
        with self.assertRaises(ValueError):
            compose.quantize_windows([{"index": 0, "wa": 0.0, "wb": 0.001}], 0.02)

    def test_quantize_clamps_to_neighbour(self):
        result = compose.quantize_windows([
            {"index": 0, "wa": 0.10, "wb": 0.30},
            {"index": 1, "wa": 0.40, "wb": 0.70},
        ], 1.0)
        self.assertGreaterEqual(result[0]["qe"], result[0]["qs"] + 1 / 24 - 1e-9)
        self.assertLessEqual(result[0]["qe"], result[1]["qs"] + 1e-9)

    def test_calibration_uses_exact_three_decimal_window_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "avatar-calibration.json"
            path.write_text(json.dumps({"10.000,12.000": {"profile": "near"},
                                        "10.100,12.100": {"profile": "exact"}}))
            loaded = compose.load_calibration(path)
            self.assertEqual(loaded[compose.calibration_key(10.1, 12.1)]["profile"], "exact")
            self.assertNotEqual(compose.calibration_key(10.1, 12.1),
                                compose.calibration_key(10.0, 12.0))
            self.assertNotIn(compose.calibration_key(10.2, 12.2), loaded)

    def test_calibration_rejects_duplicate_normalized_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "avatar-calibration.json"
            path.write_text(json.dumps({"10.1,12.1": {}, "10.100,12.100": {}}))
            with self.assertRaises(SystemExit):
                compose.load_calibration(path)

    def test_visual_text_output_is_pending_draft_contract(self):
        items = [{"id": "i1", "source_text": "支持多人协作"}]
        draft_entry = compose.visual_text_draft_entry(
            "永久保存", items, ["i1"], "seg-001")
        self.assertIsNone(draft_entry["source_ref"])
        self.assertEqual(draft_entry["review_status"], "pending")
        self.assertNotIn("reason", draft_entry)
        draft = {"schema_version": 1, "status": "pending_review",
                 "content_analysis_sha256": "hash",
                 "entries": [draft_entry]}
        analysis = {"analysis_sha256": "hash", "analysis": {
            "thesis": "支持多人协作", "items": items}}
        segments = [{"segment_id": "seg-001", "visible_text": ["永久保存"],
                     "content_item_ids": ["i1"]}]
        with self.assertRaises(visual_plan.VisualPlanError):
            visual_plan._validate_reviewed_visual_text(
                draft, analysis_record=analysis, segments=segments)

        reviewed = {"content_analysis_sha256": "hash", "entries": [{
            "segment_id": "seg-001", "text": "一起协作", "source_ref": "item:i1",
            "source_quote": "支持多人协作", "reason": "将多人协作改写为日常说法，未添加保存能力"}]}
        segments[0]["visible_text"] = ["一起协作"]
        self.assertEqual(len(visual_plan._validate_reviewed_visual_text(
            reviewed, analysis_record=analysis, segments=segments)), 1)

    def test_existing_native_inputs_are_left_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = root / "job"
            root_inputs = job / "native-inputs"
            root_inputs.mkdir(parents=True)
            old = root_inputs / "old-draft"
            old.mkdir()
            marker = old / "brief.json"
            marker.write_text(json.dumps({"kept": True}))
            (job / "05-speech-cleanup").mkdir(parents=True)
            (job / "06-edit-structure").mkdir()
            (job / "02-content-analysis").mkdir()
            (job / "workflow.json").write_text(json.dumps({"title": "t"}))
            (job / "06-edit-structure/edited-aroll.mp4").write_bytes(b"a")
            (job / "06-edit-structure/timeline-map.json").write_text(json.dumps({
                "output_duration": 4.0,
                "segments": [{"timeline_start": 0, "timeline_end": 4,
                              "source_start": 0, "source_end": 4}],
            }))
            (job / "02-content-analysis/content-analysis.json").write_text(json.dumps({
                "analysis_sha256": "x", "analysis": {"items": [{
                    "id": "i1", "source_text": "hello"
                }]}
            }))
            ctx = root / "ctx.json"
            ctx.write_text(json.dumps({"job_dir": str(job)}))
            beats = root / "beats.json"
            beats.write_text(json.dumps([{
                "kind": "overlay", "route": "notification-stack",
                "anchors": [0, 0], "content_item_ids": ["i1"],
                "labels": ["hello"], "statement": "hello", "reason": "test"
            }]))
            words = [{"text": "hello", "cut": 0.2, "cut_end": 3.3}]
            fake_riso = type("Riso", (), {"MIN_SECONDS": {},})
            fake_hyper = type("Hyper", (), {
                "create_adapter": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")))
            })
            with mock.patch.object(compose, "_word_cut_times", return_value=words), \
                 mock.patch.object(run_stage, "verify_skill_package"), \
                 mock.patch.object(compose, "_module", side_effect=lambda name: fake_riso if name == "riso_native_adapter" else fake_hyper), \
                 mock.patch.object(sys, "argv", ["compose_visual_plan.py", "--job-context", str(ctx), "--beats", str(beats), "--project-root", str(root)]):
                with self.assertRaises(RuntimeError):
                    compose.main()
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()

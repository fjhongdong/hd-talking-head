import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PROJECT))
import compose_visual_plan as compose
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

    def test_retired_cli_stops_before_job_io_or_adapter_imports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            marker = root / "existing-input.json"
            marker.write_text('{"kept": true}')
            with mock.patch.object(Path, "open", side_effect=AssertionError("unexpected Job IO")) as path_io, \
                 mock.patch("builtins.open", side_effect=AssertionError("unexpected file IO")) as file_io, \
                 mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected directory creation")) as mkdir, \
                 mock.patch("builtins.__import__", side_effect=AssertionError("unexpected adapter import")) as imports, \
                 mock.patch.object(sys, "argv", ["compose_visual_plan.py", "--job-context", str(root / "missing-context.json"),
                                                "--beats", str(root / "missing-beats.json"), "--project-root", str(root)]):
                with self.assertRaises(SystemExit) as stopped:
                    compose.main()
                path_io.assert_not_called()
                file_io.assert_not_called()
                mkdir.assert_not_called()
                imports.assert_not_called()
            self.assertIn("CLI 已停用", str(stopped.exception))
            self.assertIn("select_motion_capabilities.py match", str(stopped.exception))
            self.assertIn("select_broll_skills.py assign/check", str(stopped.exception))
            self.assertEqual(marker.read_text(), '{"kept": true}')
            self.assertEqual(list(root.iterdir()), [marker])


if __name__ == "__main__":
    unittest.main()

import unittest
from edit.hd.tools.semantic_visual_plan import validate_semantic_lists, SemanticVisualPlanError

class SemanticVisualPlanTests(unittest.TestCase):
    def setUp(self):
        self.director = {"segments": [{"segment_id":"s1", "visual_strategy":{"composition":{"family":"aroll_with_overlay"}, "components":[{"component_id":"o1","layer_role":"annotation"}]}}, {"segment_id":"s2", "visual_strategy":{"composition":{"family":"broll"}, "components":[{"component_id":"b1","layer_role":"subject"}]}}]}
    def test_separate_counts_and_mapping(self):
        t = {"semantic_lists":{"overlay":[{"row_id":"o","start_word":0,"end_word":1,"quote":"甲","semantic":"强调","visual_task":"标注","components":[{"segment_id":"s1","component_id":"o1"}]}],"broll":[{"row_id":"b","start_word":1,"end_word":2,"quote":"乙","semantic":"展示","visual_task":"画面","components":[{"segment_id":"s2","component_id":"b1"}]}]}}
        self.director["segments"][0].update(start=0, end=1)
        self.director["segments"][1].update(start=1, end=2)
        result = validate_semantic_lists(t, self.director,
            [{"text":"甲", "start":0, "end":1}, {"text":"乙", "start":1, "end":2}])
        self.assertEqual((result["overlay_count"], result["broll_count"]), (1, 1))
    def test_type_mismatch_and_orphan_rejected(self):
        row = {"row_id":"x","start_word":0,"end_word":1,"quote":"甲","semantic":"x","visual_task":"x","components":[{"segment_id":"s2","component_id":"b1"}]}
        with self.assertRaises(SemanticVisualPlanError):
            validate_semantic_lists({"semantic_lists":{"overlay":[row],"broll":[]}}, self.director)
        row["components"] = [{"segment_id":"missing","component_id":"x"}]
        with self.assertRaises(SemanticVisualPlanError):
            validate_semantic_lists({"semantic_lists":{"overlay":[row],"broll":[]}}, self.director)

    def test_one_logical_item_keeps_its_number_after_physical_split(self):
        import copy
        from edit.hd.tools.visual_confirmation import number_visual_rows, _validate_numbering
        split = copy.deepcopy(self.director["segments"][0])
        split["segment_id"] = "s3"
        self.director["segments"].append(split)
        overlay = {"row_id": "logical-overlay", "start_word": 0, "end_word": 1,
            "quote": "甲", "semantic": "强调", "visual_task": "说明重点", "components": [
                {"segment_id": sid, "component_id": "o1"} for sid in ("s1", "s3")]}
        broll = {"row_id": "logical-broll", "start_word": 1, "end_word": 2,
            "quote": "乙", "semantic": "展示", "visual_task": "演示动作",
            "components": [{"segment_id": "s2", "component_id": "b1"}]}
        report = validate_semantic_lists({"semantic_lists": {"overlay": [overlay], "broll": [broll]}}, self.director)
        self.assertEqual((report["overlay_count"], report["broll_count"]), (1, 1))
        rows = [{"row_id": f"{sid}:{cid}", "semantic_row_id": row["row_id"]}
                for (sid, cid), row in report["component_rows"].items()]
        numbered = number_visual_rows(rows)
        frozen = {row["semantic_row_id"]: row["number"] for row in numbered}
        _validate_numbering(frozen)
        reread = number_visual_rows(list(reversed(rows)), frozen)
        self.assertEqual({row["row_id"]: row["number"] for row in reread},
                         {row["row_id"]: row["number"] for row in numbered})

    def test_an_unmapped_overlay_cannot_hide_behind_broll_coverage(self):
        broll = {"row_id": "b", "start_word": 0, "end_word": 1, "quote": "甲",
            "semantic": "展示", "visual_task": "演示",
            "components": [{"segment_id": "s2", "component_id": "b1"}]}
        with self.assertRaisesRegex(SemanticVisualPlanError, "every visual component"):
            validate_semantic_lists({"semantic_lists": {"overlay": [], "broll": [broll]}}, self.director)

    def test_approved_word_window_rejects_cutoff_and_late_entry(self):
        import copy
        row = {"row_id": "knowledge", "start_word": 0, "end_word": 1,
            "quote": "知识", "semantic": "知识负担", "visual_task": "表现受阻",
            "components": [{"segment_id": "s1", "component_id": "o1"}]}
        treatment = {"semantic_lists": {"overlay": [row], "broll": []}}
        words = [{"text": "知识", "start": 7.067, "end": 7.487}]
        for start, end in ((4.167, 7.167), (7.2, 7.5)):
            director = {"segments": [copy.deepcopy(self.director["segments"][0])]}
            director["segments"][0].update(start=start, end=end)
            with self.subTest(start=start, end=end), self.assertRaisesRegex(
                    SemanticVisualPlanError, "knowledge.*word span"):
                validate_semantic_lists(treatment, director, words)

    def test_one_logical_item_requires_its_words_across_split_windows(self):
        import copy
        first = copy.deepcopy(self.director["segments"][0])
        first.update(start=0.0, end=1.0)
        second = copy.deepcopy(first)
        second.update(segment_id="s3", start=1.0, end=2.0)
        row = {"row_id": "shared", "start_word": 0, "end_word": 2,
            "quote": "甲乙", "semantic": "连续变化", "visual_task": "延续同一对象",
            "components": [{"segment_id": sid, "component_id": "o1"} for sid in ("s1", "s3")]}
        treatment = {"semantic_lists": {"overlay": [row], "broll": []}}
        words = [{"text": "甲", "start": 0.1, "end": 0.9},
                 {"text": "乙", "start": 1.1, "end": 1.9}]
        director = {"segments": [first, second]}
        self.assertEqual(validate_semantic_lists(treatment, director, words)["overlay_count"], 1)
        second["start"] = 1.3
        with self.assertRaisesRegex(SemanticVisualPlanError, "shared.*word span"):
            validate_semantic_lists(treatment, director, words)

    def test_silence_gap_does_not_erase_logical_identity_or_relax_a_beat(self):
        import copy
        from edit.hd.tools.visual_confirmation import _validate_beat_sheet, VisualConfirmationError
        first = copy.deepcopy(self.director["segments"][0])
        first.update(start=0, end=1)
        second = copy.deepcopy(first)
        second.update(segment_id="s3", start=2, end=3)
        refs = [{"segment_id": sid, "component_id": "o1"} for sid in ("s1", "s3")]
        treatment = {"semantic_lists": {"overlay": [{"row_id":"shared", "start_word":0,
            "end_word":2, "quote":"甲乙", "semantic":"同一关系", "visual_task":"两次出现",
            "components":refs}], "broll":[]}, "beat_sheet":[{"start_word":0, "end_word":2,
            "quote":"甲乙", "decision":"overlay", "visual":"要求整句连续", "components":refs,
            "merge_reason":"连续呈现同一对象"}]}
        director = {"segments":[first, second]}
        words = [{"text":"甲", "start":0.1, "end":0.9}, {"text":"乙", "start":2.1, "end":2.9}]
        self.assertEqual(validate_semantic_lists(treatment, director, words)["overlay_count"], 1)
        with self.assertRaisesRegex(VisualConfirmationError, "word span"):
            _validate_beat_sheet(treatment, director, words)

    def test_clock_values_and_one_frame_tolerance(self):
        from edit.hd.tools.semantic_visual_plan import require_interval_coverage
        require_interval_coverage([(1/24, 2-1/24)], 0, 2, label="edge")
        for window in ((float("nan"),2), (0,float("inf")), (True,2), (2,1), (0.1,2)):
            with self.subTest(window=window), self.assertRaises(SemanticVisualPlanError):
                require_interval_coverage([window], 0, 2, label="edge")

if __name__ == "__main__":
    unittest.main()

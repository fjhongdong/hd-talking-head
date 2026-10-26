import unittest
from edit.hd.tools.semantic_visual_plan import validate_semantic_lists, SemanticVisualPlanError

class SemanticVisualPlanTests(unittest.TestCase):
    def setUp(self):
        self.director = {"segments": [{"segment_id":"s1", "visual_strategy":{"composition":{"family":"aroll_with_overlay"}, "components":[{"component_id":"o1","layer_role":"annotation"}]}}, {"segment_id":"s2", "visual_strategy":{"composition":{"family":"broll"}, "components":[{"component_id":"b1","layer_role":"subject"}]}}]}
    def test_separate_counts_and_mapping(self):
        t = {"semantic_lists":{"overlay":[{"row_id":"o","start_word":0,"end_word":1,"quote":"甲","semantic":"强调","visual_task":"标注","components":[{"segment_id":"s1","component_id":"o1"}]}],"broll":[{"row_id":"b","start_word":1,"end_word":2,"quote":"乙","semantic":"展示","visual_task":"画面","components":[{"segment_id":"s2","component_id":"b1"}]}]}}
        result = validate_semantic_lists(t, self.director, [{"text":"甲"},{"text":"乙"}])
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

if __name__ == "__main__":
    unittest.main()

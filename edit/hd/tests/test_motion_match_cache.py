"""Real catalog retrieval is cached, including after semantic coverage additions."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from edit.hd.tools import motion_capabilities as motion, motion_match_cache as cache

ROOT = Path(__file__).resolve().parents[3]


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        self.add_item("overlay", "并列要点", ["并列", "要点", "累积", "列表"])
        self.add_item("broll", "比较两种方案", ["对比", "前后", "方案"])

    def add_item(self, use, text, tags):
        index = len(self.director["segments"])
        sid = f"s{index}"
        self.director["segments"].append({"segment_id": sid,
            "visual_strategy": {"composition": {"family": "aroll_with_overlay" if use == "overlay" else "single_full_frame"},
                "components": [{"component_id": "c", "kind": "code_generated",
                                "layer_role": "annotation" if use == "overlay" else "base"}]}})
        self.treatment["semantic_lists"][use].append({"row_id": f"r{index}",
            "start_word": index, "end_word": index + 1, "quote": text,
            "semantic": text, "visual_task": text, "components": [{"segment_id": sid, "component_id": "c"}]})
        self.treatment["motion_queries"].append({"segment_id": sid, "component_id": "c", "tags": tags})

    def test_unchanged_and_new_items_match_only_once(self):
        before = copy.deepcopy(self.treatment)
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            first = cache.match_once(ROOT, self.director, self.treatment)
            self.assertEqual(search.call_count, 2)
            self.assertEqual(self.treatment, before)
            self.treatment = first
            self.add_item("overlay", "步骤提示", ["流程", "连线", "步骤"])
            updated = cache.match_once(ROOT, self.director, self.treatment)
            self.assertEqual(search.call_count, 3)
            self.assertEqual(updated["motion_matches"]["r0"], first["motion_matches"]["r0"])
            cache.validate_matches(ROOT, self.director, updated)
            self.assertEqual(search.call_count, 3)

    def test_split_keeps_one_semantic_item_and_reuses_matching(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        part = copy.deepcopy(self.director["segments"][0])
        part["segment_id"] = "split"
        self.director["segments"].append(part)
        first["semantic_lists"]["overlay"][0]["components"].append({"segment_id": "split", "component_id": "c"})
        first["motion_queries"].append({"segment_id": "split", "component_id": "c", "tags": first["motion_queries"][0]["tags"]})
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 0)
            context = cache.validate_matches(ROOT, self.director, updated)
        self.assertEqual(context[("split", "c")]["row_id"], "r0")

    def test_changed_semantics_update_only_that_item(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        first["semantic_lists"]["overlay"][0]["visual_task"] = "重新说明同一组并列要点"
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 1)
        self.assertEqual(updated["motion_matches"]["r1"], first["motion_matches"]["r1"])

    def test_corrupt_or_stale_caches_are_not_silently_accepted(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        self.assertTrue(first["motion_matches"]["r0"]["matches"])
        for case in ("absent", "catalog", "query", "duplicate", "evidence"):
            altered = copy.deepcopy(first)
            if case == "absent":
                altered.pop("motion_matches")
            elif case == "catalog":
                altered["motion_matches"]["r0"]["catalog_sha256"] = "0" * 64
            elif case == "query":
                altered["motion_queries"].pop()
            elif case == "duplicate":
                matches = altered["motion_matches"]["r0"]["matches"]
                matches.append(copy.deepcopy(matches[0]))
            else:
                altered["motion_matches"]["r0"]["matches"][0]["retrieval_score"] += 1
            with self.subTest(case=case), self.assertRaises(ValueError):
                cache.validate_matches(ROOT, self.director, altered)

    def test_every_matched_candidate_requires_a_concrete_review(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, first)
        first["skill_selection"] = {"beats": [], "overlay_beats": []}
        for (sid, cid), item in context.items():
            beat = {"segment_id": sid, "component_id": cid, "semantic_row_id": item["row_id"],
                "candidates": [{"candidate_id": match["candidate"]["candidate_id"],
                    "fit": "equivalent" if match["candidate"]["status"] == "supported" else "needs_adapter",
                    "reason": "缓存与选择入口测试，实际内容另经原生输入检查"}
                    for match in item["matches"]]}
            first["skill_selection"]["overlay_beats" if item["semantic"]["type"] == "贴片" else "beats"].append(beat)
        cache.validate_reviews(ROOT, self.director, first)
        first["skill_selection"]["overlay_beats"][0]["candidates"].pop()
        with self.assertRaisesRegex(ValueError, "every cached match"):
            cache.validate_reviews(ROOT, self.director, first)


if __name__ == "__main__":
    unittest.main()

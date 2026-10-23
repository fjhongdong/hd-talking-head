from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from edit.hd.tools import talkcraft_matcher, visual_plan


class TalkCraftMatcherTests(unittest.TestCase):
    def test_locked_index_covers_all_qualified_cards(self) -> None:
        catalog = talkcraft_matcher.load_card_catalog()
        self.assertEqual(len(catalog), 108)
        self.assertEqual(len({card["card_id"] for card in catalog}), 108)
        self.assertTrue(all(card["production"]["status"] == "qualified" for card in catalog))

    def test_speech_semantics_produce_distinct_stable_matches(self) -> None:
        timeline = talkcraft_matcher.match_cards(
            "这三年产品从第一版升级到第四版，我们按时间看看每一步发生了什么",
            semantic_family="timeline",
            semantic_goals=["版本演进"],
            keywords=["时间线"],
            information_units=4,
            target_role="scene",
            available_media=["image"],
        )
        repeated = talkcraft_matcher.match_cards(
            "这三年产品从第一版升级到第四版，我们按时间看看每一步发生了什么",
            semantic_family="timeline",
            semantic_goals=["版本演进"],
            keywords=["时间线"],
            information_units=4,
            target_role="scene",
            available_media=["image"],
        )
        transition = talkcraft_matcher.match_cards(
            "接下来进入第二章，我们换一个话题",
            semantic_family="transition",
            semantic_goals=["章节切换"],
            keywords=["第二章"],
            target_role="transition",
        )
        self.assertEqual(timeline, repeated)
        self.assertEqual(timeline["catalog_size"], 108)
        self.assertIn(timeline["matches"][0]["card_id"], {"timeline-photo-strip", "step-timeline-vertical"})
        self.assertEqual(transition["matches"][0]["card_id"], "chapter-progress-list")
        self.assertNotEqual(timeline["matches"][0]["card_id"], transition["matches"][0]["card_id"])

    def test_required_media_and_presenter_are_hard_gates(self) -> None:
        without_images = talkcraft_matcher.match_cards(
            "四个年份沿时间线逐个展示产品版本",
            semantic_family="timeline",
            keywords=["时间线", "照片"],
            information_units=4,
            target_role="scene",
        )
        with_images = talkcraft_matcher.match_cards(
            "四个年份沿时间线逐个展示产品版本",
            semantic_family="timeline",
            keywords=["时间线", "照片"],
            information_units=4,
            target_role="scene",
            available_media=["image"],
        )
        self.assertNotIn("timeline-photo-strip", [item["card_id"] for item in without_images["matches"]])
        self.assertEqual(with_images["matches"][0]["card_id"], "timeline-photo-strip")
        presenter = talkcraft_matcher.match_cards(
            "人物留在画面里，旁边并列展示三个方法",
            semantic_family="presenter_interaction",
            keywords=["人物", "并列"],
            information_units=3,
            target_role="scene",
            available_media=["presenter", "image"],
            presenter_required=True,
        )
        self.assertTrue(all("presenter" in item["allowed_media"] for item in presenter["matches"]))

    def test_selected_card_builds_a_valid_existing_router_binding(self) -> None:
        result = talkcraft_matcher.match_cards(
            "不是工具越多越好，而是流程越清晰越好",
            semantic_family="comparison",
            keywords=["不是", "而是", "对照"],
            information_units=2,
            target_role="overlay",
        )
        binding = talkcraft_matcher.build_binding(result, brief_sha256="a" * 64)
        router = visual_plan._load_router_module()
        router.validate_template_binding(binding)
        router.validate_invocation_evidence(binding)
        self.assertTrue(binding["template_id"].startswith("hd-talking-head/talkcraft/"))
        self.assertEqual(binding["dependency_id"], "hd-talking-head-talkcraft")

    def test_stale_or_tampered_index_is_rejected(self) -> None:
        source = talkcraft_matcher.DEFAULT_SEMANTIC_INDEX
        value = json.loads(source.read_text(encoding="utf-8"))
        value["cards"][0]["reference_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(talkcraft_matcher.TalkCraftMatchError):
                talkcraft_matcher.load_card_catalog(index_path=path)

    def test_binding_rejects_tampered_match_identity(self) -> None:
        result = talkcraft_matcher.match_cards(
            "两个方案放在一起对比",
            semantic_family="comparison",
            target_role="scene",
        )
        result["semantic_index_sha256"] = "0" * 64
        with self.assertRaises(talkcraft_matcher.TalkCraftMatchError):
            talkcraft_matcher.build_binding(result, brief_sha256="a" * 64)


if __name__ == "__main__":
    unittest.main()

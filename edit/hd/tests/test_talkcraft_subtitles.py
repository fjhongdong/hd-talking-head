from __future__ import annotations

import unittest
from unittest.mock import patch

from edit.hd.tools import subtitles_v2, talkcraft_subtitles


class TalkCraftSubtitleAdapterTests(unittest.TestCase):
    def test_cue_input_preserves_multi_character_word_timing_and_utf16_offsets(self) -> None:
        cue = {"id": "cue-001", "start": 1.0, "end": 2.0, "text": "A😀你", "emphasis_words": ["😀你"]}
        words = [
            {"text": "A😀", "start": 0.8, "end": 1.4},
            {"text": "你", "start": 1.35, "end": 1.8},
        ]
        result = talkcraft_subtitles.cue_input(cue, words)
        self.assertEqual([(item["start"], item["end"]) for item in result["words"]], [(1.0, 1.4), (1.35, 1.8)])
        self.assertEqual([(item["text_start"], item["text_end"]) for item in result["words"]], [(0, 3), (3, 4)])
        self.assertEqual(result["emphasis"], {"text_start": 1, "text_end": 4, "start": 1.0, "end": 1.8})

    def test_renderer_binding_rejects_missing_or_tampered_renderer(self) -> None:
        plan = {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 24}, "cues": []}
        renderer_input = talkcraft_subtitles.renderer_input(plan, [])
        identity = {"id": "renderer"}
        payload = {"schema_version": 4, "render_plan": plan, "renderer_input": renderer_input, "renderer": identity}
        with patch.object(talkcraft_subtitles, "identity", return_value=identity):
            talkcraft_subtitles.validate_binding(payload)
            for changed in (dict(payload, schema_version=3), dict(payload, renderer={"id": "tampered"})):
                with self.assertRaises(talkcraft_subtitles.TalkCraftSubtitleError):
                    talkcraft_subtitles.validate_binding(changed)

    def test_four_approved_emphasis_cues_are_allowed(self) -> None:
        terms = ("认知", "流程", "效率", "价值")
        plan = {"cues": [
            {"segment_id": "s", "start": index * 20.0, "text": term, "emphasis_words": [term]}
            for index, term in enumerate(terms)
        ]}
        segments = [{"segment_id": "s", "shot_recipe": {"mode": "none"}, "content_item_ids": ["i"]}]
        subtitles_v2.validate_emphasis(plan, {"i": terms}, segments)


if __name__ == "__main__":
    unittest.main()

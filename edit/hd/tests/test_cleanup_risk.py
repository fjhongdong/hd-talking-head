"""Rule hints must help review without becoming automatic edit decisions."""

import copy
import json
import unittest

from edit.hd.tools.edit_timeline import EditTimelineError, build_cleanup_proposal
from edit.hd.tools import edit_timeline


def proposal_inputs(texts, actions, *, gap=0.0):
    words = [
        {"text": text, "start": round(i * (0.4 + gap), 6),
         "end": round(i * (0.4 + gap) + 0.4, 6)}
        for i, text in enumerate(texts)
    ]
    segments = [
        {"action": action, "word_start": i, "word_end": i + 1,
         "source_start": word["start"], "source_end": word["end"],
         "original_sentence": word["text"],
         "cleaned_sentence": word["text"] if action == "keep" else "",
         "reason": "人工提出的删改候选",
         "breathing_padding": {"before": 0.0, "after": 0.0}}
        for i, (word, action) in enumerate(zip(words, actions))
    ]
    return words, {"version": 1, "segments": segments}, words[-1]["end"] + 0.2


class CleanupRiskTests(unittest.TestCase):
    def report(self, texts, actions, **kwargs):
        words, plan, duration = proposal_inputs(texts, actions, **kwargs)
        before = copy.deepcopy((words, plan))
        result = build_cleanup_proposal(
            "".join(texts), words, plan, media_duration=duration
        )
        self.assertEqual((words, plan), before)
        self.assertIn("risk_assessment", result["diff_summary"])
        report = result["diff_summary"]["risk_assessment"]
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["method"], "conservative_rules_v1")
        self.assertIs(report["advisory_only"], True)
        self.assertIs(report["requires_audio_review"], True)
        self.assertEqual(report, json.loads(json.dumps(report, allow_nan=False)))
        return report

    def test_adjacent_partial_prefix_has_low_hint_and_exact_keep_reference(self):
        candidate = self.report(["分", "分享"], ["delete", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "low")
        self.assertEqual(candidate["deleted_text"], "分")
        self.assertEqual(candidate["source_start"], 0.0)
        self.assertEqual(candidate["source_end"], 0.4)
        self.assertEqual(candidate["keep_ref"], {"word_start": 1, "word_end": 2})
        self.assertEqual(candidate["audition_range"]["source_start"], 0.0)

    def test_protected_terms_override_shortness_and_repetition(self):
        for text, continuation in [
            ("不", "不是"), ("没", "没有"), ("仅", "仅仅"),
            ("大约", "大约四十年"), ("40", "40年"), ("四十", "四十年"),
            ("如果", "如果成立"), ("因为", "因为流程"),
        ]:
            with self.subTest(text=text):
                candidate = self.report([text, continuation], ["delete", "keep"])["candidates"][0]
                self.assertEqual(candidate["risk"], "high")
                self.assertTrue(candidate["protected_matches"])

    def test_protected_phrase_split_across_tokens_is_found(self):
        candidate = self.report(["大", "约", "需要", "四十年"],
                                ["keep", "delete", "keep", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "high")
        self.assertTrue(any(m["text"] == "大约" for m in candidate["protected_matches"]))

    def test_complete_sentence_is_high(self):
        candidate = self.report(["这件事很重要。", "接着讲"], ["delete", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "high")
        self.assertIn("sentence_or_long_deletion", candidate["rules"])

    def test_unknown_short_phrase_is_not_safe_by_length(self):
        candidate = self.report(["关键", "经验"], ["delete", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "review")

    def test_same_opening_different_end_is_not_mechanical_repeat(self):
        candidate = self.report(["学会使用", "学会判断"], ["delete", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "review")

    def test_exact_repeat_may_be_emphasis(self):
        candidate = self.report(["很好", "很好"], ["delete", "keep"])["candidates"][0]
        self.assertEqual(candidate["risk"], "review")

    def test_distant_prefix_is_not_low(self):
        candidate = self.report(["分", "分享"], ["delete", "keep"], gap=4)["candidates"][0]
        self.assertEqual(candidate["risk"], "review")

    def test_no_deletions_has_empty_report(self):
        report = self.report(["分享", "经验"], ["keep", "keep"])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["counts"], {"high": 0, "review": 0, "low": 0})

    def test_retained_interrupted_restart_is_reported_and_delete_clears_it(self):
        words = [
            {"text": "总", "start": 0.0, "end": 0.2},
            {"text": "感觉-- ", "start": 0.2, "end": 0.4},
            {"text": "总", "start": 1.0, "end": 1.2},
            {"text": "觉得，", "start": 1.2, "end": 1.4},
            {"text": "总", "start": 2.5, "end": 2.7},
            {"text": "觉得", "start": 2.7, "end": 2.9},
            {"text": "买", "start": 2.9, "end": 3.1},
        ]
        plan = {"version": 1, "segments": [{
            "action": "keep", "word_start": 0, "word_end": 7,
            "source_start": 0.0, "source_end": 3.1,
            "original_sentence": "".join(w["text"] for w in words),
            "cleaned_sentence": "".join(w["text"] for w in words),
            "reason": "保留原句", "breathing_padding": {"before": 0.0, "after": 0.0},
        }]}
        found = edit_timeline.assess_cleanup_risk(words, plan, media_duration=4.0)["retained_repetitions"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "retained_repetition")
        self.assertEqual((found[0]["word_start"], found[0]["word_end"]), (0, 7))
        plan["segments"][0]["action"] = "delete"
        plan["segments"][0]["cleaned_sentence"] = ""
        self.assertEqual(edit_timeline.assess_cleanup_risk(words, plan, media_duration=4.0)["retained_repetitions"], [])

    def test_retained_repetition_handles_punctuation_inside_one_asr_word(self):
        words = [
            {"text": "总觉得，总觉得买", "start": 0.0, "end": 1.0},
        ]
        plan = {"version": 1, "segments": [{
            "action": "keep", "word_start": 0, "word_end": 1,
            "source_start": 0.0, "source_end": 1.0,
            "original_sentence": words[0]["text"], "cleaned_sentence": words[0]["text"],
            "reason": "保留原句", "breathing_padding": {"before": 0.0, "after": 0.0},
        }]}
        found = edit_timeline.assess_cleanup_risk(words, plan, media_duration=2.0)["retained_repetitions"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["word_start"], 0)

    def test_non_adjacent_normal_repeat_is_not_reported(self):
        words = [
            {"text": "总觉得。", "start": 0.0, "end": 0.2},
            {"text": "先说别的。", "start": 1.0, "end": 1.2},
            {"text": "总觉得。", "start": 2.0, "end": 2.2},
        ]
        plan = {"version": 1, "segments": [{
            "action": "keep", "word_start": 0, "word_end": 3,
            "source_start": 0.0, "source_end": 2.2,
            "original_sentence": "".join(w["text"] for w in words),
            "cleaned_sentence": "".join(w["text"] for w in words),
            "reason": "保留原句", "breathing_padding": {"before": 0.0, "after": 0.0},
        }]}
        self.assertEqual(edit_timeline.assess_cleanup_risk(words, plan, media_duration=3.0)["retained_repetitions"], [])

    def test_short_parallel_opening_requires_listening_despite_asr_final_difference(self):
        report = self.report(["自己点，", "自己填。"], ["keep", "keep"])
        found = report["retained_repetitions"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["evidence"], "shared_short_opening_requires_audio_review")
        self.assertEqual((found[0]["word_start"], found[0]["word_end"]), (0, 2))
        deleted = self.report(["自己点，", "自己填。"], ["delete", "keep"])
        self.assertEqual(deleted["retained_repetitions"], [])

    def test_adjacent_long_complete_sentence_repeat_is_reported(self):
        sentence = "这是一段超过十四个字但完整重复的句子内容"
        words = [
            {"text": sentence + "。", "start": 0.0, "end": 1.0},
            {"text": sentence + "。", "start": 1.5, "end": 2.5},
        ]
        plan = {"version": 1, "segments": [{
            "action": "keep", "word_start": 0, "word_end": 2,
            "source_start": 0.0, "source_end": 2.5,
            "original_sentence": "".join(w["text"] for w in words),
            "cleaned_sentence": "".join(w["text"] for w in words),
            "reason": "保留原句", "breathing_padding": {"before": 0.0, "after": 0.0},
        }]}
        found = edit_timeline.assess_cleanup_risk(words, plan, media_duration=3.0)["retained_repetitions"]
        self.assertEqual(len(found), 1)

    def test_correction_reader_accepts_new_diff_without_accepting_unknown_fields(self):
        words, plan, duration = proposal_inputs(["分享", "经验"], ["keep", "keep"])
        result = build_cleanup_proposal("分享经验", words, plan, media_duration=duration)
        self.assertEqual(edit_timeline._correction_audit_runs(result["diff_summary"]), [])
        with self.assertRaises(EditTimelineError):
            edit_timeline._correction_audit_runs({**result["diff_summary"], "unexpected": True})

    def test_partly_cut_following_word_cannot_prove_safe_restart(self):
        words, plan, duration = proposal_inputs(["分", "分享", "经验"], ["delete", "keep", "keep"])
        plan.update(version=2, reviewed_cut_ranges=[{
            "source_start": 0.42, "source_end": 0.6,
            "reason": "另外一个人工切点", "evidence": "试听",
        }])
        result = build_cleanup_proposal("分分享经验", words, plan, media_duration=duration)
        candidate = result["diff_summary"]["risk_assessment"]["candidates"][0]
        self.assertEqual(candidate["risk"], "review")
        self.assertIsNone(candidate["keep_ref"])

    def test_time_cut_does_not_claim_whole_word_was_deleted(self):
        words, plan, duration = proposal_inputs(["分享", "经验"], ["keep", "keep"])
        plan.update(version=2, reviewed_cut_ranges=[{
            "source_start": 0.08, "source_end": 0.15,
            "reason": "词内重复音", "evidence": "用户核听确认范围",
        }])
        result = build_cleanup_proposal("分享经验", words, plan, media_duration=duration)
        self.assertIn("risk_assessment", result["diff_summary"])
        candidate = result["diff_summary"]["risk_assessment"]["candidates"][0]
        self.assertEqual(candidate["kind"], "reviewed_time_cut")
        self.assertIsNone(candidate["deleted_text"])
        self.assertEqual(candidate["affected_text"], "分享")
        self.assertEqual(candidate["risk"], "review")
        self.assertEqual(candidate["evidence"], "用户核听确认范围")
        self.assertIn("partial_word_cut", candidate["rules"])

    def test_gap_cut_has_no_invented_word_binding(self):
        words, plan, duration = proposal_inputs(["分享", "经验"], ["keep", "keep"], gap=0.4)
        plan.update(version=2, reviewed_cut_ranges=[{
            "source_start": 0.5, "source_end": 0.6,
            "reason": "停顿", "evidence": "试听范围",
        }])
        result = build_cleanup_proposal("分享经验", words, plan, media_duration=duration)
        self.assertIn("risk_assessment", result["diff_summary"])
        candidate = result["diff_summary"]["risk_assessment"]["candidates"][0]
        self.assertIsNone(candidate["word_start"])
        self.assertIsNone(candidate["word_end"])
        self.assertEqual(candidate["affected_text"], "")
        self.assertEqual(candidate["risk"], "review")

    def test_rejects_source_words_outside_media_even_when_all_kept(self):
        words, plan, _ = proposal_inputs(["分享", "经验"], ["keep", "keep"])
        with self.assertRaises(EditTimelineError):
            build_cleanup_proposal("分享经验", words, plan, media_duration=0.2)

    def test_nonfinite_or_outside_cut_rejected(self):
        for start, end in [(0.1, float("nan")), (0.1, 99), (-1, 0.1)]:
            words, plan, duration = proposal_inputs(["分享", "经验"], ["keep", "keep"])
            plan.update(version=2, reviewed_cut_ranges=[{
                "source_start": start, "source_end": end, "reason": "检查", "evidence": "检查",
            }])
            with self.subTest(start=start, end=end), self.assertRaises(EditTimelineError):
                build_cleanup_proposal("分享经验", words, plan, media_duration=duration)


if __name__ == "__main__":
    unittest.main()

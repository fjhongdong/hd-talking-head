import copy
import unittest


class TerminologyReviewTests(unittest.TestCase):
    def test_history_latin_token_boundaries_match_source_policy(self):
        from edit.hd.tools.terminology_review import _history_text
        self.assertEqual(_history_text(["Open", "AI"]), "Open AI")
        self.assertEqual(_history_text(["斯坦", "福"]), "斯坦福")
        self.assertEqual(_history_text(["OpenAI"]), "OpenAI")

    def test_history_preserves_conflicting_contextual_alternatives_as_doubts(self):
        from edit.hd.tools.terminology_review import build_report_with_history
        summary = {"version": 1, "original_script": "原文", "cleaned_script": "原文",
                   "deleted_words": [], "deleted_word_count": 0,
                   "transcript_corrections": {"version": 1, "runs": [{
                       "source": {"path": "05-speech-cleanup/word-transcript.json", "sha256": "a" * 64, "bytes": 1},
                       "manifest": {"path": "correction.json", "sha256": "b" * 64, "bytes": 1},
                       "changes": [{"word_start": i, "word_end": i + 1, "before": ["旧词"], "after": [target], "reason": "本处核听"}
                                   for i, target in enumerate(["甲词", "乙词"])]}]}}
        before = copy.deepcopy(summary)
        result = build_report_with_history([{"text": "旧词", "start": 8, "end": 9}], approved_terms=[], summary=summary)
        self.assertEqual([d["expected"] for d in result["doubts"]], ["甲词", "乙词"])
        self.assertEqual(result["doubts"][1]["history_reference"]["change_index"], 1)
        self.assertEqual(result["doubts"][0]["reason"], "historical_correction_possible_recurrence")
        self.assertEqual(summary, before)
        self.assertFalse(result["automatic_replacement"])

    def test_bound_report_recomputes_from_approved_content_identity(self):
        from edit.hd.tools.terminology_review import build_bound_report, validate_bound_report
        content = {
            "analysis_sha256": "c" * 64,
            "analysis": {
                "items": [{"keywords": ["OpenAI", "斯坦福"]}],
                "claims": [{"entities": ["Databricks"], "numbers": ["40年"]}],
            },
        }
        words = [{"text": "openai", "start": 1, "end": 2}]
        summary = {"version": 1, "original_script": "OpenAI", "cleaned_script": "OpenAI",
                   "deleted_words": [], "deleted_word_count": 0}

        value = build_bound_report(words, content_record=content, summary=summary)
        self.assertEqual(
            value["approved_terms"], ["OpenAI", "斯坦福", "Databricks", "40年"],
        )
        self.assertEqual(value["report"]["doubts"][0]["observed"], "openai")
        self.assertEqual(validate_bound_report(
            value, words=words, content_record=content, summary=summary,
        ), value)

        changed = copy.deepcopy(value)
        changed["content_analysis_sha256"] = "d" * 64
        with self.assertRaises(ValueError):
            validate_bound_report(
                changed, words=words, content_record=content, summary=summary,
            )

    def test_existing_correction_history_accepts_both_workflow_paths(self):
        from edit.hd.tools.edit_timeline import _correction_audit_runs
        for prefix in ("02", "05"):
            summary = {"version": 1, "original_script": "原文", "cleaned_script": "原文",
                       "deleted_words": [], "deleted_word_count": 0,
                       "transcript_corrections": {"version": 1, "runs": [{
                           "source": {"path": prefix + "-speech-cleanup/word-transcript.json", "sha256": "a" * 64, "bytes": 1},
                           "manifest": {"path": "correction.json", "sha256": "b" * 64, "bytes": 1},
                           "changes": [{"word_start": 0, "word_end": 1, "before": ["斯坦副"], "after": ["斯坦福"], "reason": "核听确认"}]}]}}
            self.assertEqual(len(_correction_audit_runs(summary)), 1)

    def analyze(self, words, terms, corrections=()):
        from edit.hd.tools.terminology_review import build_report
        return build_report(words, approved_terms=terms, corrections=corrections)

    def test_case_variant_and_explicit_correction_keep_source_times(self):
        words = [{"text": "openai", "start": 1, "end": 2},
                 {"text": "斯坦", "start": 3, "end": 4},
                 {"text": "副", "start": 4, "end": 5}]
        before = copy.deepcopy(words)
        report = self.analyze(words, ["OpenAI", "斯坦福"], [{"from": "斯坦副", "to": "斯坦福"}])
        self.assertEqual(words, before)
        self.assertEqual([x["observed"] for x in report["doubts"]], ["openai", "斯坦副"])
        self.assertEqual(report["doubts"][1]["word_indices"], [1, 2])
        self.assertEqual(report["doubts"][1]["source_range"], [3, 5])
        self.assertFalse(report["automatic_replacement"])

    def test_same_text_at_different_times_is_not_deduplicated(self):
        words = [{"text": "ai", "start": i, "end": i + .5} for i in (1, 5)]
        self.assertEqual(len(self.analyze(words, ["AI"])["doubts"]), 2)

    def test_exact_terms_substrings_and_unapproved_similarity_are_not_errors(self):
        words = [{"text": "AI stair 斯坦夫", "start": 0, "end": 1}]
        self.assertEqual(self.analyze(words, ["AI", "斯坦福"])["doubts"], [])

    def test_invalid_time_and_conflicting_corrections_fail(self):
        for start in (float("nan"), True, -1):
            with self.assertRaises(ValueError):
                self.analyze([{"text": "ai", "start": start, "end": 2}], ["AI"])
        with self.assertRaises(ValueError):
            self.analyze([], ["AI"], [{"from": "x", "to": "AI"}, {"from": "x", "to": "AGI"}])

    def test_conflicting_approved_spellings_and_correction_fail(self):
        for terms, corrections in [(["OpenAI", "OPENAI"], []),
                                   (["OpenAI"], [{"from": "openai", "to": "Other"}]),
                                   (["OpenAI"], [{"from": "wrong", "to": "OPENAI"}])]:
            with self.assertRaises(ValueError):
                self.analyze([], terms, corrections)

    def test_long_silence_is_not_joined_into_one_term(self):
        words = [{"text": "斯坦", "start": 1, "end": 2}, {"text": "副", "start": 100, "end": 101}]
        corrections = [{"from": "斯坦副", "to": "斯坦福"}]
        self.assertEqual(self.analyze(words, ["斯坦福"], corrections)["doubts"], [])
        words[1].update(start=2.1, end=3)
        self.assertEqual(len(self.analyze(words, ["斯坦福"], corrections)["doubts"]), 1)


if __name__ == "__main__":
    unittest.main()

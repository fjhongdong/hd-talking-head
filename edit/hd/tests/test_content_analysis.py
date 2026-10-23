from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from edit.hd.tools import content_analysis, state


SCRIPT = "学了AI却用不好。不是能力没到，是标准变了。真正重要的是把AI用进真实工作流。"
SOURCE_TEXT = "不是能力没到，是标准变了"
SOURCE_START = SCRIPT.index(SOURCE_TEXT)
SOURCE_END = SOURCE_START + len(SOURCE_TEXT)

VALID_ANALYSIS = {
    "thesis": "真正重要的是把AI用进真实工作流。",
    "hook": "学了AI却用不好。",
    "sections": [
        {"id": "s1", "title": "判断标准变化", "source_span": [0, SOURCE_END]}
    ],
    "items": [
        {
            "id": "idea-01",
            "source_text": SOURCE_TEXT,
            "source_span": [SOURCE_START, SOURCE_END],
            "priority": "critical",
            "keywords": ["能力", "标准变了"],
            "semantic_type": "contrast",
            "evidence_status": "supported",
            "broll_priority": "high",
        }
    ],
    "claims": [],
}


class ContentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.video = self.root / "source.mp4"
        self.script = self.root / "script.md"
        self.video.write_bytes(b"video")
        self.script.write_text(SCRIPT, encoding="utf-8")
        self.job = state.create_job(
            self.root, self.video, self.script, profile="full-v2"
        )
        report = self.job.job_dir / "01-inspect" / "report.json"
        report.parent.mkdir(parents=True)
        report.write_text("{}\n", encoding="utf-8")
        state.mark_ready(self.job, "inspect", [report])
        state.approve(self.job, "inspect")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_binds_script_and_writes_one_review_package(self) -> None:
        record = content_analysis.prepare_content_analysis(
            self.job, VALID_ANALYSIS
        )

        self.assertEqual(record["script_sha256"], self.job.inputs["script"]["sha256"])
        output = self.job.job_dir / "02-content-analysis"
        self.assertTrue((output / "content-analysis.json").is_file())
        self.assertTrue((output / "review.md").is_file())
        self.assertTrue((output / "material-usage.json").is_file())
        self.assertIn(
            "02-content-analysis/material-usage.json",
            {item["path"] for item in self.job.stages["content_analysis"]["artifacts"]},
        )
        self.assertEqual(
            self.job.stages["content_analysis"]["status"], "ready_for_review"
        )

    def test_source_span_text_and_keywords_must_match_original_script(self) -> None:
        for mutation, message in (
            (("source_span", [0, 2]), "source_text"),
            (("source_text", "改写后的句子"), "source_text"),
            (("keywords", ["原文没有的词"]), "keyword"),
        ):
            with self.subTest(field=mutation[0]):
                invalid = copy.deepcopy(VALID_ANALYSIS)
                invalid["items"][0][mutation[0]] = mutation[1]
                with self.assertRaisesRegex(
                    content_analysis.ContentAnalysisError, message
                ):
                    content_analysis.prepare_content_analysis(self.job, invalid)

    def test_unsupported_item_cannot_be_high_priority_or_high_broll(self) -> None:
        invalid = copy.deepcopy(VALID_ANALYSIS)
        invalid["items"][0]["evidence_status"] = "unsupported"

        with self.assertRaisesRegex(
            content_analysis.ContentAnalysisError, "unsupported"
        ):
            content_analysis.prepare_content_analysis(self.job, invalid)

    def test_load_approved_rejects_ready_for_review(self) -> None:
        content_analysis.prepare_content_analysis(self.job, VALID_ANALYSIS)

        with self.assertRaisesRegex(
            content_analysis.ContentAnalysisError, "approved"
        ):
            content_analysis.load_approved_content_analysis(self.job)

    def test_approved_revision_reuses_the_same_semantic_record(self) -> None:
        first = content_analysis.prepare_content_analysis(self.job, VALID_ANALYSIS)
        state.approve(self.job, "content_analysis")

        loaded = content_analysis.load_approved_content_analysis(self.job)

        self.assertEqual(loaded["analysis_sha256"], first["analysis_sha256"])
        self.assertEqual(
            len(
                list(
                    (self.job.job_dir / "02-content-analysis").glob(
                        "content-analysis*.json"
                    )
                )
            ),
            1,
        )

    def test_needs_user_decision_remains_visible_in_review(self) -> None:
        analysis = copy.deepcopy(VALID_ANALYSIS)
        analysis["items"][0]["priority"] = "medium"
        analysis["items"][0]["broll_priority"] = "medium"
        analysis["items"][0]["evidence_status"] = "needs_user_decision"

        content_analysis.prepare_content_analysis(self.job, analysis)

        review = (
            self.job.job_dir / "02-content-analysis" / "review.md"
        ).read_text(encoding="utf-8")
        self.assertIn("待用户决定", review)
        self.assertIn(SOURCE_TEXT, review)


if __name__ == "__main__":
    unittest.main()

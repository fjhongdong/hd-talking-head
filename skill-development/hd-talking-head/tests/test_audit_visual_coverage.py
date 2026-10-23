"""Audit math and overlay-window contracts on synthetic plans; no media."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
import audit_visual_coverage as audit_module


def segment(sid, start, end, family, *, rationale="", items=(), intent=None):
    row = {
        "segment_id": sid, "start": start, "end": end,
        "visual_strategy": {"mode": "none", "composition": {"family": family},
                            "rationale": rationale},
        "content_item_ids": list(items),
    }
    if intent is not None:
        row["visual_intent"] = {"statement": intent}
    return row


def visual_plan():
    return {
        "duration": 60.0,
        "segments": [
            segment("seg-a", 0.0, 10.0, "no_broll"),
            segment("seg-b", 10.0, 25.0, "wise-motion"),
            segment("seg-c", 25.0, 35.0, "aroll_with_overlay",
                    intent="对比两种做法"),
            segment("seg-d", 35.0, 60.0, "no_broll", items=["item-1"]),
        ],
    }


def subtitle_plan():
    return {"render_plan": {"cues": [
        {"start": 0.0, "end": 5.0, "text": "第一句", "emphasis_words": []},
        {"start": 5.0, "end": 9.5, "text": "关键结论", "emphasis_words": ["关键"]},
        {"start": 26.0, "end": 30.0, "text": "贴片台词", "emphasis_words": []},
    ]}}


class AuditVisualCoverageTests(unittest.TestCase):
    def test_runtime_and_cli_share_ratio_floor(self):
        from edit.hd.tools import visual_coverage
        for seconds, should_block in ((9, True), (11, False)):
            rows = []
            for index in range(5):
                start = index * 20
                rows += [segment(f"b{index}", start, start + seconds, "single_full_frame"),
                         segment(f"a{index}", start + seconds, start + 20, "no_broll")]
            plan = {"duration": 100.0, "segments": rows}
            note = {"broll_ratio_note": "ordinary note cannot waive the floor"}
            runtime = visual_coverage.require_density(plan, treatment=note)
            cli = audit_module.audit(plan, {"render_plan": {"cues": []}}, 20,
                                     require_density=True, treatment=note)
            self.assertEqual(runtime["blocking_issues"], cli["blocking_issues"])
            self.assertEqual(bool(runtime["blocking_issues"]), should_block)

    def test_one_visualized_item_does_not_cover_another(self):
        plan = {"duration": 20.0, "segments": [
            segment("a", 0, 11, "single_full_frame", items=["i1"]),
            segment("b", 11, 20, "no_broll", items=[]),
        ]}
        analysis = {"analysis": {"items": [
            {"id": "i1", "priority": "high"}, {"id": "i2", "priority": "high"},
        ]}}
        report = audit_module.audit(plan, {"render_plan": {"cues": []}}, 20,
                                    content_analysis=analysis)
        self.assertEqual([item["id"] for item in report["needs_review_items"]], ["i2"])

    def test_window_and_global_math(self):
        report = audit_module.audit(visual_plan(), subtitle_plan(), 20.0)
        self.assertEqual(report["duration"], 60.0)
        self.assertEqual(report["broll_count"], 1)
        self.assertEqual(report["broll_seconds"], 15.0)
        self.assertEqual(report["broll_percent"], 25.0)
        self.assertEqual(report["first_broll_start"], 10.0)
        self.assertEqual(report["overlay_count"], 1)
        # 最长无 B-roll 区间:25-60(贴片不算 B-roll,不断开间隔)
        self.assertEqual(report["longest_without_broll_seconds"], 35.0)
        self.assertEqual(report["longest_without_broll_interval"],
                         {"start": 25.0, "end": 60.0})
        self.assertEqual(report["highlight_count"], 1)
        self.assertEqual(len(report["windows"]), 3)
        second = report["windows"][1]
        self.assertEqual(second["broll_ids"], ["seg-b"])
        self.assertEqual(second["overlay_ids"], ["seg-c"])
        self.assertEqual(second["pure_aroll_seconds"], 5.0)  # seg-d 35-40 落在本窗
        self.assertEqual(report["overlay_speech"][0]["spoken_text"], "贴片台词")

    def test_pure_aroll_seconds_only_counts_no_broll(self):
        report = audit_module.audit(visual_plan(), subtitle_plan(), 20.0)
        third = report["windows"][2]
        self.assertAlmostEqual(third["pure_aroll_seconds"], 20.0)

    def test_needs_review_lists_unvisualized_high_priority_items(self):
        analysis = {"analysis": {"items": [
            {"id": "item-1", "priority": "high", "source_text": "重要论点"},
            {"id": "item-2", "priority": "low", "source_text": "次要"},
        ]}}
        report = audit_module.audit(visual_plan(), subtitle_plan(), 20.0,
                                    content_analysis=analysis)
        ids = [item["id"] for item in report["needs_review_items"]]
        self.assertIn("item-1", ids)
        self.assertNotIn("item-2", ids)
        self.assertNotIn("needs_review_items", audit_module.audit(
            visual_plan(), subtitle_plan(), 20.0))

    def test_require_overlays_blocks_when_absent(self):
        plan = visual_plan()
        plan["segments"] = [row for row in plan["segments"]
                            if row["visual_strategy"]["composition"]["family"] != "aroll_with_overlay"]
        report = audit_module.audit(plan, subtitle_plan(), 20.0, require_overlays=True)
        self.assertTrue(report["blocking_issues"])

    def test_overlay_window_requires_continuous_aroll(self):
        plan = visual_plan()
        selected = audit_module.require_aroll_window(plan, 0.0, 10.0)
        self.assertEqual(selected, ["seg-a"])
        with self.assertRaisesRegex(ValueError, "replace B-roll"):
            audit_module.require_aroll_window(plan, 10.0, 20.0)
        gapped = visual_plan()
        gapped["segments"][0]["end"] = 8.0
        del gapped["segments"][1]
        with self.assertRaisesRegex(ValueError, "uncovered interval"):
            audit_module.require_aroll_window(gapped, 0.0, 30.0)

    def test_cli_exit_code_follows_blocking_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "visual.json").write_text(json.dumps(visual_plan()), encoding="utf-8")
            (root / "subs.json").write_text(json.dumps(subtitle_plan()), encoding="utf-8")
            stripped = visual_plan()
            stripped["segments"] = [row for row in stripped["segments"]
                                    if row["visual_strategy"]["composition"]["family"] != "aroll_with_overlay"]
            (root / "no-overlay.json").write_text(json.dumps(stripped), encoding="utf-8")
            ok = subprocess.run([sys.executable, str(_env.SKILL / "scripts/audit_visual_coverage.py"),
                                 "--visual-plan", str(root / "visual.json"),
                                 "--subtitle-plan", str(root / "subs.json")],
                                capture_output=True, text=True, check=False)
            blocked = subprocess.run([sys.executable, str(_env.SKILL / "scripts/audit_visual_coverage.py"),
                                      "--visual-plan", str(root / "no-overlay.json"),
                                      "--subtitle-plan", str(root / "subs.json"),
                                      "--require-overlays", "--content-analysis", str(root / "no-overlay.json")],
                                      capture_output=True, text=True, check=False)
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(blocked.returncode, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import os
from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import subtitles, subtitles_v2, talkcraft_subtitles


def _record(name: str) -> dict[str, object]:
    return {"path": name, "sha256": "a" * 64, "bytes": 1}


class FormalSubtitleContractTests(unittest.TestCase):
    def test_subtitle_inventory_has_no_thumbnail_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "10-subtitles"
            target.mkdir()
            names = {"subtitle-plan.json", "subtitles.webm", "subtitles.srt"}
            for name in names:
                (target / name).write_bytes(b"inventory fixture")
            self.assertEqual(
                {Path(record["path"]).name for record in subtitles_v2._snapshot(target)},
                names,
            )
            (target / "contact-sheet.png").write_bytes(b"obsolete thumbnail")
            with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                subtitles_v2._snapshot(target)

    @unittest.skipUnless(os.environ.get("HD_SUBTITLE_MEDIA_TEST") == "1", "explicit serial media test")
    def test_published_media_retains_report_and_rejects_history_drift(self):
        # Real media/readback; upstream approval loading is a fixture, not a full Job.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "10-subtitles"
            target.mkdir()
            summary = root / "05-speech-cleanup" / "diff-summary.json"
            summary.parent.mkdir()
            summary.write_text(json.dumps({"version": 1, "original_script": "原文",
                                           "cleaned_script": "原文", "deleted_words": [],
                                           "deleted_word_count": 0}))
            job = SimpleNamespace(job_id="maintenance", job_dir=root, stages={
                "speech_cleanup": {"status": "approved", "artifacts": [subtitles_v2._record(summary, root)]},
                "subtitles": {"status": "ready_for_review", "artifacts": []},
            })
            report = subtitles_v2._build_terminology_review(
                job, [{"text": "openai", "start": 0.2, "end": 0.8}], {"term": ["OpenAI"]})
            self.assertEqual(report["doubts"][0]["expected"], "OpenAI")
            renderer_cues = []
            plan = subtitles_v2.build_render_plan(records=self.records, words=self.words,
                timeline=self.timeline, visual_plan=self.visual_plan,
                keyword_index=self.keywords, renderer_cues=renderer_cues)
            renderer_input = talkcraft_subtitles.renderer_input(plan, renderer_cues)
            wrapper = subtitles_v2._wrapper(job, "a" * 64, "b" * 64, plan,
                                             terminology_report=report,
                                             renderer_input=renderer_input)
            (target / "subtitle-plan.json").write_text(json.dumps(wrapper))
            webm = target / "subtitles.webm"
            with webm.open("w+b") as media:
                talkcraft_subtitles.render(renderer_input, media.fileno())
            (target / "subtitles.srt").write_bytes(subtitles._srt_bytes(plan["cues"]))
            job.stages["subtitles"]["artifacts"] = subtitles_v2._snapshot(target)
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            with mock.patch.object(subtitles_v2.content_analysis, "load_approved_content_analysis",
                                   return_value={"analysis_sha256": "a" * 64}), \
                 mock.patch.object(subtitles_v2, "approved_keyword_index", return_value=self.keywords), \
                 mock.patch.object(subtitles_v2, "_load_inputs",
                                   return_value=({"version": 1, "words": self.words},
                                                 {**self.timeline, "render_adapter": "native-ffmpeg-no-cut"},
                                                 {**self.visual_plan, "visual_plan_sha256": "b" * 64}, self.records)):
                self.assertEqual(subtitles_v2._validate_published(job), webm)
                self.assertEqual(subtitles_v2._validate_published(job), webm)
                summary.write_text("{}")
                with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                    subtitles_v2._validate_published(job)
            self.assertEqual(before, {path.name: path.read_bytes() for path in target.iterdir()})

    def test_review_reads_verified_report_and_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(subtitles_v2.state, "load_job") as reload_job:
            root = Path(directory)
            target = root / "10-subtitles" / "subtitle-plan.json"
            target.parent.mkdir()
            job = SimpleNamespace(version=2, job_id="maintenance", revision=7, job_dir=root,
                                  stages={"subtitles": {"status": "ready_for_review", "artifacts": []}})
            reload_job.return_value = job
            payload = subtitles_v2._wrapper(job, "a" * 64, "b" * 64, {})
            target.write_text(json.dumps(payload))
            job.stages["subtitles"]["artifacts"] = [subtitles_v2._record(target, root)]
            before = target.read_bytes()
            result = subtitles_v2.review_subtitles(job)
            self.assertEqual(result["revision"], 7)
            self.assertEqual(result["terminology_status"], "legacy_report_unavailable")
            self.assertEqual(target.read_bytes(), before)
            reader = subtitles_v2.contract_artifacts.read_json_artifact
            def withdraw_after_read(path):
                value = reader(path)
                job.stages["subtitles"]["status"] = "needs_revision"
                return value
            with mock.patch.object(subtitles_v2.contract_artifacts, "read_json_artifact", side_effect=withdraw_after_read):
                with self.assertRaisesRegex(subtitles_v2.SubtitlesV2Error, "workflow changed"):
                    subtitles_v2.review_subtitles(job)
            job.stages["subtitles"]["status"] = "ready_for_review"
            target.write_text("{}")
            with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                subtitles_v2.review_subtitles(job)

    def test_review_command_loads_current_job_without_approving(self):
        from edit.hd.tools import cli
        import contextlib
        import io
        output = io.StringIO()
        job = SimpleNamespace()
        with mock.patch.object(cli, "load_job", return_value=job) as load, \
             mock.patch.object(subtitles_v2, "review_subtitles", return_value={"stage": "subtitles"}, create=True) as review, \
             mock.patch.object(cli, "approve") as approve, contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["review-subtitles", "--job", "/job"]), 0)
        load.assert_called_once_with(Path("/job"))
        review.assert_called_once_with(job)
        approve.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {"stage": "subtitles"})

    def test_current_wrapper_cannot_omit_terminology_even_with_new_hash(self):
        payload = subtitles_v2._wrapper(SimpleNamespace(job_id="maintenance"), "a" * 64, "b" * 64,
                                       {}, terminology_report={"history_binding": {}})
        del payload["terminology_review"]
        from edit.hd.tools import contract_artifacts
        payload["subtitle_plan_sha256"] = contract_artifacts.sha256_json(
            {k: v for k, v in payload.items() if k != "subtitle_plan_sha256"})
        with self.assertRaises(subtitles_v2.SubtitlesV2Error):
            subtitles_v2._validate_terminology_binding(SimpleNamespace(), payload)

    def test_history_binding_refuses_changed_or_unapproved_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "05-speech-cleanup" / "diff-summary.json"
            source.parent.mkdir()
            source.write_text(json.dumps({"version": 1, "original_script": "原文", "cleaned_script": "原文",
                                          "deleted_words": [], "deleted_word_count": 0}))
            record = subtitles_v2._record(source, root)
            job = SimpleNamespace(job_dir=root, stages={"speech_cleanup": {"status": "approved", "artifacts": [record]}})
            report = subtitles_v2._build_terminology_review(job, self.words, self.keywords)
            self.assertEqual(report["history_binding"], record)
            subtitles_v2._validate_terminology_binding(job, {"terminology_review": report})
            source.write_text("{}")
            with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                subtitles_v2._validate_terminology_binding(job, {"terminology_review": report})
            job.stages["speech_cleanup"]["status"] = "needs_revision"
            with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                subtitles_v2._build_terminology_review(job, self.words, self.keywords)
            # Historical wrappers without this optional report are not rewritten.
            subtitles_v2._validate_terminology_binding(job, {})

    def test_prepare_uses_approved_source_for_terminology_and_wraps_failures(self):
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                job = SimpleNamespace(version=2, job_id="maintenance", job_dir=Path(directory),
                                      stages={"subtitles": {"status": "pending"}})
                stack.enter_context(mock.patch.object(subtitles_v2, "_load_transaction", return_value=None))
                stack.enter_context(mock.patch.object(subtitles_v2.state, "require_runnable"))
                stack.enter_context(mock.patch.object(subtitles_v2.content_analysis, "load_approved_content_analysis",
                                                     return_value={"analysis_sha256": "a" * 64}))
                stack.enter_context(mock.patch.object(subtitles_v2, "approved_keyword_index", return_value=self.keywords))
                stack.enter_context(mock.patch.object(subtitles_v2, "_corrected_phrases", return_value=[]))
                stack.enter_context(mock.patch.object(subtitles_v2, "_load_inputs",
                                                     return_value=({}, {}, {"visual_plan_sha256": "b" * 64}, self.records)))
                stack.enter_context(mock.patch.object(subtitles_v2.subtitles, "_validate_words", return_value=self.words))
                stack.enter_context(mock.patch.object(subtitles_v2.subtitles, "_validate_timeline", return_value=self.timeline))
                stack.enter_context(mock.patch.object(subtitles_v2, "build_render_plan", return_value={
                    "canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 96},
                    "cues": [], "source_bindings": self.records,
                    "layout_counts": {"emphasis": 0, "statement": 0, "source": 0, "action": 0},
                }))
                report = {"version": 1, "automatic_replacement": False, "doubts": []}
                check = stack.enter_context(mock.patch.object(subtitles_v2, "_build_terminology_review",
                                                             return_value=report,
                                                             side_effect=ValueError("conflicting spelling") if fails else None))
                class StopBeforeEncoding(Exception):
                    pass
                writer = stack.enter_context(mock.patch.object(subtitles_v2.contract_artifacts, "write_json_artifact",
                                                              side_effect=StopBeforeEncoding))
                expected = subtitles_v2.SubtitlesV2Error if fails else StopBeforeEncoding
                with self.assertRaises(expected) as raised:
                    subtitles_v2._prepare_subtitles_v2_locked(job)
                check.assert_called_once_with(job, self.words, self.keywords)
                if fails:
                    writer.assert_not_called()
                    self.assertIsInstance(raised.exception.__cause__, ValueError)
                    self.assertEqual(list(Path(directory).iterdir()), [])
                else:
                    self.assertEqual(writer.call_args.args[0].name, "subtitle-plan.json")
                    self.assertEqual(writer.call_args.args[1]["terminology_review"], report)

    def test_talkcraft_renderer_failure_does_not_publish_or_replace_old_output(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                target = root / "10-subtitles"
                target.mkdir()
                job = SimpleNamespace(version=2, job_id="maintenance", job_dir=root,
                                      stages={"subtitles": {"status": "pending"}},
                                      revision=1, expected_sha256="w", expected_bytes=1)
                stack.enter_context(mock.patch.object(talkcraft_subtitles, "identity", return_value={"id": "test"}))
                # A complete prior generation with a different renderer input
                # must be preserved when the new render fails.
                old_payload = subtitles_v2._wrapper(
                    job, "old-analysis", "old-visual", {}, renderer_input={"old": True}
                )
                (target / "subtitle-plan.json").write_text(json.dumps(old_payload))
                old = target / "subtitles.webm"
                old.write_bytes(b"old-webm")
                (target / "subtitles.srt").write_text("")
                (target / "material-usage.json").write_text("{}")
                job.stages["subtitles"]["lineage"] = subtitles_v2._snapshot(target, identity=True)
                if not corrupt:
                    for record in job.stages["subtitles"]["lineage"]:
                        record["device"] += 1
                        record["parent_device"] += 1
                if corrupt:
                    old.write_bytes(b"changed-media")
                before = {path.name: path.read_bytes() for path in target.iterdir()}
                stack.enter_context(mock.patch.object(subtitles_v2, "_load_transaction", return_value=None))
                stack.enter_context(mock.patch.object(subtitles_v2.state, "require_runnable"))
                stack.enter_context(mock.patch.object(subtitles_v2.content_analysis, "load_approved_content_analysis", return_value={"analysis_sha256": "a"}))
                stack.enter_context(mock.patch.object(subtitles_v2, "approved_keyword_index", return_value=self.keywords))
                stack.enter_context(mock.patch.object(subtitles_v2, "_corrected_phrases", return_value=[]))
                stack.enter_context(mock.patch.object(subtitles_v2, "_build_terminology_review", return_value=None))
                stack.enter_context(mock.patch.object(subtitles_v2, "_load_inputs", return_value=({}, {}, {"visual_plan_sha256": "b"}, self.records)))
                stack.enter_context(mock.patch.object(subtitles_v2.subtitles, "_validate_words", return_value=self.words))
                stack.enter_context(mock.patch.object(subtitles_v2.subtitles, "_validate_timeline", return_value=self.timeline))
                plan = {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 96}, "cues": [], "source_bindings": self.records, "layout_counts": {"emphasis": 0, "statement": 0, "source": 0, "action": 0}}
                stack.enter_context(mock.patch.object(subtitles_v2, "build_render_plan", return_value=plan))
                render = stack.enter_context(mock.patch.object(talkcraft_subtitles, "render", side_effect=talkcraft_subtitles.TalkCraftSubtitleError("renderer failed")))
                expected = subtitles_v2.SubtitlesV2Error if corrupt else talkcraft_subtitles.TalkCraftSubtitleError
                with self.assertRaises(expected):
                    subtitles_v2._prepare_subtitles_v2_locked(job)
                self.assertEqual(render.call_count, 0 if corrupt else 1)
                self.assertEqual(before, {path.name: path.read_bytes() for path in target.iterdir()})
                self.assertEqual(list(root.glob(".10-subtitles.stage-*")), [])

    def test_fixed_baseline_rejects_same_content_inode_replacement_before_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "10-subtitles"; target.mkdir()
            job = SimpleNamespace(version=2, job_id="maintenance", job_dir=root,
                                  stages={"subtitles": {"status": "pending"}},
                                  revision=1, expected_sha256="w", expected_bytes=1)
            old_payload = subtitles_v2._wrapper(job, "old-analysis", "old-visual", {}, renderer_input={"old": True})
            (target / "subtitle-plan.json").write_text(json.dumps(old_payload)); old = target / "subtitles.webm"; old.write_bytes(b"old-webm")
            (target / "subtitles.srt").write_text(""); (target / "material-usage.json").write_text("{}")
            job.stages["subtitles"]["lineage"] = subtitles_v2._snapshot(target, identity=True)
            patches = [
                mock.patch.object(talkcraft_subtitles, "identity", return_value={"id": "test"}),
                mock.patch.object(subtitles_v2, "_load_transaction", return_value=None),
                mock.patch.object(subtitles_v2.state, "require_runnable"),
                mock.patch.object(subtitles_v2.content_analysis, "load_approved_content_analysis", return_value={"analysis_sha256": "a"}),
                mock.patch.object(subtitles_v2, "approved_keyword_index", return_value=self.keywords),
                mock.patch.object(subtitles_v2, "_corrected_phrases", return_value=[]),
                mock.patch.object(subtitles_v2, "_build_terminology_review", return_value=None),
                mock.patch.object(subtitles_v2, "_load_inputs", return_value=({}, {}, {"visual_plan_sha256": "b"}, self.records)),
                mock.patch.object(subtitles_v2.subtitles, "_validate_words", return_value=self.words),
                mock.patch.object(subtitles_v2.subtitles, "_validate_timeline", return_value=self.timeline),
                mock.patch.object(subtitles_v2, "build_render_plan", return_value={"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 96}, "cues": [], "source_bindings": self.records, "layout_counts": {"emphasis": 0, "statement": 0, "source": 0, "action": 0}}),
                mock.patch.object(talkcraft_subtitles, "render", side_effect=talkcraft_subtitles.TalkCraftSubtitleError("renderer failed")),
            ]
            with ExitStack() as stack:
                render = [stack.enter_context(p) for p in patches][-1]
                def replace_same_content(*args, **kwargs):
                    replacement = target / "replacement.tmp"
                    replacement.write_bytes(old.read_bytes())
                    previous_inode = old.stat().st_ino
                    os.replace(replacement, old)
                    self.assertNotEqual(previous_inode, old.stat().st_ino)
                stack.enter_context(mock.patch.object(subtitles_v2.contract_artifacts, "write_json_artifact", side_effect=replace_same_content))
                with self.assertRaisesRegex(subtitles_v2.SubtitlesV2Error, "previous subtitle generation changed"):
                    subtitles_v2._prepare_subtitles_v2_locked(job)
                render.assert_not_called()
                self.assertFalse(list(root.glob(".10-subtitles.stage-*")))

    def test_terminology_report_is_in_existing_hashed_review_payload(self):
        report = {"version": 1, "automatic_replacement": False, "doubts": []}
        payload = subtitles_v2._wrapper(SimpleNamespace(job_id="maintenance"), "a" * 64,
                                       "b" * 64, {}, terminology_report=report)
        self.assertEqual(payload["terminology_review"], report)
        from edit.hd.tools import contract_artifacts
        base = {k: v for k, v in payload.items() if k != "subtitle_plan_sha256"}
        self.assertEqual(payload["subtitle_plan_sha256"], contract_artifacts.sha256_json(base))

    def setUp(self) -> None:
        text = "真正淘汰你的不是AI模型而是不会使用AI的人"
        self.words = [
            {"text": glyph, "start": 0.05 + index * 0.15, "end": 0.17 + index * 0.15}
            for index, glyph in enumerate(text)
        ]
        self.timeline = {
            "version": 1,
            "source_duration": 4.0,
            "output_duration": 4.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "segments": [{
                "source_start": 0.0,
                "source_end": 4.0,
                "timeline_start": 0.0,
                "timeline_end": 4.0,
            }],
        }
        self.visual_plan = {
            "duration": 4.0,
            "segments": [
                {
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": 2.0,
                    "content_item_ids": ["idea-01"],
                    "shot_recipe": {"mode": "none"},
                },
                {
                    "segment_id": "seg-002",
                    "start": 2.0,
                    "end": 4.0,
                    "content_item_ids": ["idea-02"],
                    "shot_recipe": {"mode": "single", "composition": {"avatar": {
                        "position": {"x": 735, "y": 1390}, "profile": {"diameter": 284, "border_width": 0},
                    }}},
                },
            ],
        }
        self.keywords = {
            "idea-01": ("AI模型", "真正淘汰"),
            "idea-02": ("不会使用AI",),
        }
        self.records = {
            "word_transcript": _record("05-speech-cleanup/word-transcript.json"),
            "timeline_map": _record("06-edit-structure/timeline-map.json"),
            "edited_aroll": _record("06-edit-structure/edited-aroll.mp4"),
            "visual_plan": _record("07-visual-direction/visual-plan.json"),
            "asset_manifest": _record("09-visual-assets/asset-manifest.json"),
            "visual_track": _record("09-visual-assets/visual-track.mp4"),
        }

    def _plan(self):
        return subtitles_v2.build_render_plan(
            records=self.records,
            words=self.words,
            timeline=self.timeline,
            visual_plan=self.visual_plan,
            keyword_index=self.keywords,
        )

    def test_long_keyword_and_spaced_date_keep_real_word_boundaries(self):
        words = [
            {"text": text, "start": 0.1 + index * 0.4, "end": 0.4 + index * 0.4}
            for index, text in enumerate(("10", "月", "28", "日", "开源，", "Ling-", "3.1-flash-1019。"))
        ]
        visual = {"duration": 4.0, "segments": [{
            "segment_id": "seg-001", "start": 0.0, "end": 4.0,
            "content_item_ids": ["idea-01"],
            "shot_recipe": {"mode": "single", "composition": {"avatar": {
                "position": {"x": 672, "y": 1372},
                "profile": {"diameter": 320, "border_width": 4},
            }}},
        }]}
        plan = subtitles_v2.build_render_plan(
            records=self.records, words=words, timeline=self.timeline,
            visual_plan=visual,
            keyword_index={"idea-01": ("10 月 28 日", "Ling-3.1-flash-1019")},
        )
        texts = [cue["text"] for cue in plan["cues"]]
        self.assertTrue(any("10月28日" in text for text in texts))
        self.assertIn("Ling-3.1-flash-1019。", texts)
        self.assertEqual("".join(texts), "10月28日开源，Ling-3.1-flash-1019。")

    def test_long_keyword_that_cannot_fit_is_rejected(self):
        words = [{"text": "L" * 80, "start": 0.1, "end": 1.0}]
        visual = {"duration": 4.0, "segments": [{
            "segment_id": "seg-001", "start": 0.0, "end": 4.0,
            "content_item_ids": ["idea-01"], "shot_recipe": {"mode": "none"},
        }]}
        with self.assertRaises((subtitles_v2.SubtitlesV2Error, subtitles.SubtitleError)):
            subtitles_v2.build_render_plan(records=self.records, words=words,
                timeline=self.timeline, visual_plan=visual,
                keyword_index={"idea-01": ("L" * 80,)})

    def test_aroll_and_broll_share_one_timed_subtitle_track(self) -> None:
        renderer_cues = []
        plan = subtitles_v2.build_render_plan(
            records=self.records, words=self.words,
            timeline=self.timeline, visual_plan=self.visual_plan,
            keyword_index=self.keywords, renderer_cues=renderer_cues,
        )

        self.assertTrue(plan["cues"])
        self.assertEqual({cue["segment_id"] for cue in plan["cues"]}, {"seg-001", "seg-002"})
        self.assertEqual([cue["id"] for cue in plan["cues"]], [cue["cue_id"] for cue in renderer_cues])
        for cue in plan["cues"]:
            self.assertLessEqual(len(cue["emphasis_words"]), 1)
            segment = next(item for item in self.visual_plan["segments"] if item["segment_id"] == cue["segment_id"])
            allowed = set(self.keywords[segment["content_item_ids"][0]])
            self.assertTrue(set(cue["emphasis_words"]) <= allowed)
            self.assertLessEqual(len(cue["text"]), 14)
        broll_cues = [cue for cue in plan["cues"] if cue["segment_id"] == "seg-002"]
        self.assertTrue(broll_cues)
        self.assertTrue(all(cue["box"]["x"] + cue["box"]["width"] <= 735 for cue in broll_cues))
        self.assertTrue(all(cue["box"]["y"] >= 1390 for cue in broll_cues))
        self.assertTrue(all(cue["box"]["y"] == 1462 and cue["box"]["height"] == 230 for cue in broll_cues))
        self.assertTrue(all(cue["bottom"] == 228 for cue in renderer_cues if cue["cue_id"] in {item["id"] for item in broll_cues}))
        self.assertTrue(all(cue["bottom"] == 350 for cue in renderer_cues if cue["cue_id"] not in {item["id"] for item in broll_cues}))
        self.assertTrue(all(cue["box"]["y"] + cue["box"]["height"] <= cue["safe_zones"]["subtitle"]["y"] + cue["safe_zones"]["subtitle"]["height"] for cue in broll_cues))
        self.assertTrue(all(cue["placement"] == "above_avatar" for cue in renderer_cues if cue["cue_id"] in {item["id"] for item in broll_cues}))

    def test_right_avatar_uses_two_line_card_in_its_actual_left_space(self) -> None:
        plan = copy.deepcopy(self.visual_plan)
        avatar = plan["segments"][1]["shot_recipe"]["composition"]["avatar"]
        avatar["position"] = {"x":672, "y":1372}
        avatar["profile"] = {"diameter":320, "border_width":4}
        rendered = []
        result = subtitles_v2.build_render_plan(records=self.records, words=self.words,
            timeline=self.timeline, visual_plan=plan, keyword_index=self.keywords,
            renderer_cues=rendered)
        broll = [cue for cue in result["cues"] if cue["segment_id"] == "seg-002"]
        self.assertTrue(broll)
        self.assertTrue(all(cue["box"] == {"x":80,"y":1462,"width":584,"height":230}
                            for cue in broll))
        self.assertTrue(all(cue["box"]["x"] + cue["box"]["width"] + 8 <= 672 for cue in broll))
        ids = {cue["id"] for cue in broll}
        self.assertTrue(all(cue["width"] == 584 and cue["bottom"] == 228
                            for cue in rendered if cue["cue_id"] in ids))
        self.assertEqual("".join(cue["text"] for cue in result["cues"]),
                         "".join(cue["text"] for cue in self._plan()["cues"]))

    def test_center_avatar_moves_broll_subtitle_below_outer_ring(self) -> None:
        plan = copy.deepcopy(self.visual_plan)
        avatar = plan["segments"][1]["shot_recipe"]["composition"]["avatar"]
        avatar["position"] = {"x": 406, "y": 1336}
        avatar["profile"]["diameter"] = 256
        avatar["profile"]["border_width"] = 6
        renderer_cues = []
        subtitles_v2.build_render_plan(records=self.records, words=self.words,
            timeline=self.timeline, visual_plan=plan, keyword_index=self.keywords,
            renderer_cues=renderer_cues)
        broll = [c for c in renderer_cues if c["placement"] == "above_avatar"]
        self.assertTrue(broll)
        self.assertTrue(all(c["bottom"] == 136 for c in broll))
        self.assertTrue(all(c["bottom"] == 350 for c in renderer_cues if c["placement"] == "standard"))

    def test_avatar_too_low_is_rejected_before_render(self) -> None:
        plan = copy.deepcopy(self.visual_plan)
        avatar = plan["segments"][1]["shot_recipe"]["composition"]["avatar"]
        avatar["position"] = {"x": 406, "y": 1420}
        avatar["profile"]["diameter"] = 256
        avatar["profile"]["border_width"] = 6
        with self.assertRaisesRegex(subtitles_v2.SubtitlesV2Error, "cannot fit two lines"):
            subtitles_v2.build_render_plan(records=self.records, words=self.words,
                timeline=self.timeline, visual_plan=plan, keyword_index=self.keywords)

    def test_unapproved_emphasis_is_rejected(self) -> None:
        plan = self._plan()
        changed = copy.deepcopy(plan)
        changed["cues"][0]["emphasis_words"] = ["错误重点"]

        with self.assertRaisesRegex(
            subtitles_v2.SubtitlesV2Error, "approved exact keyword"
        ):
            subtitles_v2.validate_emphasis(
                changed, self.keywords, self.visual_plan["segments"], emphasis_times={}
            )

    def test_keyword_can_return_after_cooldown_without_flooding_adjacent_cues(self) -> None:
        segments = [{"segment_id": "seg-001", "content_item_ids": ["idea-01"]}]
        def plan(times):
            return {"cues": [{"id": f"cue-{index}", "segment_id": "seg-001", "start": time, "end": time + 1,
                              "text": "优化流程", "emphasis_words": ["优化流程"]}
                             for index, time in enumerate(times)]}
        subtitles_v2.validate_emphasis(plan([5.0, 21.0]),
                                       {"idea-01": ("优化流程",)}, segments,
                                       emphasis_times={"cue-0": 5.0, "cue-1": 21.0})
        with self.assertRaisesRegex(subtitles_v2.SubtitlesV2Error, "too closely spaced"):
            subtitles_v2.validate_emphasis(plan([5.0, 19.0]),
                                           {"idea-01": ("优化流程",)}, segments,
                                           emphasis_times={"cue-0": 5.0, "cue-1": 19.0})
        segments.append({"segment_id": "seg-002", "content_item_ids": ["idea-02"]})
        adjacent = {"cues": [plan([5.0])["cues"][0],
                             {"id": "cue-1", "segment_id": "seg-002", "start": 6.5, "end": 7.5,
                              "text": "行业经验", "emphasis_words": ["行业经验"]}]}
        with self.assertRaisesRegex(subtitles_v2.SubtitlesV2Error, "too closely spaced"):
            subtitles_v2.validate_emphasis(adjacent,
                                           {"idea-01": ("优化流程",), "idea-02": ("行业经验",)},
                                           segments, emphasis_times={"cue-0": 5.0, "cue-1": 6.5})

    def test_keyword_cooldown_uses_word_time_not_subtitle_start(self) -> None:
        words = [{"text": "接私活", "start": 1.0, "end": 1.3},
                 {"text": "事情", "start": 2.2, "end": 2.4},
                 {"text": "做完", "start": 3.5, "end": 3.8}]
        visual = {"duration": 4.0, "segments": [
            {"segment_id": "seg-001", "start": 0.0, "end": 2.0,
             "content_item_ids": ["idea-01"], "shot_recipe": {"mode": "none"}},
            {"segment_id": "seg-002", "start": 2.0, "end": 4.0,
             "content_item_ids": ["idea-02"], "shot_recipe": {"mode": "none"}}]}
        renderer = []
        plan = subtitles_v2.build_render_plan(
            records=self.records, words=words, timeline=self.timeline,
            visual_plan=visual, keyword_index={"idea-01": ("接私活",), "idea-02": ("做完",)},
            renderer_cues=renderer)
        self.assertEqual([cue["emphasis_words"] for cue in plan["cues"]], [["接私活"], ["做完"]])
        self.assertEqual([cue["emphasis"]["start"] for cue in renderer], [1.0, 3.5])

    def test_approved_keywords_remain_visible_across_a_long_video(self) -> None:
        terms = ("认知", "流程", "效率", "价值")
        duration = 80.0
        words = [
            {"text": term, "start": 5.0 + index * 20.0,
             "end": 5.8 + index * 20.0}
            for index, term in enumerate(terms)
        ]
        timeline = copy.deepcopy(self.timeline)
        timeline["source_duration"] = duration
        timeline["output_duration"] = duration
        timeline["segments"][0]["source_end"] = duration
        timeline["segments"][0]["timeline_end"] = duration
        visual = {
            "duration": duration,
            "segments": [
                {"segment_id": f"seg-{index + 1:03d}", "start": index * 20.0,
                 "end": (index + 1) * 20.0,
                 "content_item_ids": [f"idea-{index + 1:02d}"],
                 "shot_recipe": {"mode": "none"}}
                for index in range(4)
            ],
        }
        keywords = {f"idea-{index + 1:02d}": (term,)
                    for index, term in enumerate(terms)}

        renderer = []
        plan = subtitles_v2.build_render_plan(
            records=self.records, words=words, timeline=timeline,
            visual_plan=visual, keyword_index=keywords, renderer_cues=renderer,
        )

        self.assertEqual([cue["emphasis_words"] for cue in plan["cues"]],
                         [[term] for term in terms])
        subtitles_v2.validate_emphasis(plan, keywords, visual["segments"],
            emphasis_times={cue["cue_id"]: cue["emphasis"]["start"] for cue in renderer if cue["emphasis"]})

    def test_audible_pause_beats_length_balancing_without_new_emphasis(self) -> None:
        text = "只是我们一直在主动调整自己的评判标准"
        intervals = [(0.14, 0.26), (0.26, 0.40), (0.40, 0.46), (0.46, 0.60),
                     (0.60, 0.76), (0.76, 0.92), (0.92, 1.20), (1.20, 1.40),
                     (1.42, 1.62), (1.62, 1.82), (1.82, 1.84), (2.06, 2.16),
                     (2.16, 2.18), (2.18, 2.30), (2.30, 2.46), (2.46, 2.64),
                     (2.64, 2.80), (2.80, 2.96)]
        words = [{"text": char, "start": start, "end": end}
                 for char, (start, end) in zip(text, intervals)]
        visual = {"duration": 4.0, "segments": [{"segment_id": "seg-001",
                  "start": 0.0, "end": 4.0, "content_item_ids": ["idea-01"],
                  "shot_recipe": {"mode": "none"}}]}
        renderer_cues = []
        plan = subtitles_v2.build_render_plan(records=self.records, words=words,
            timeline=self.timeline, visual_plan=visual,
            keyword_index={"idea-01": ("评判标准",)}, renderer_cues=renderer_cues)
        self.assertEqual([cue["text"] for cue in plan["cues"]],
                         ["只是我们一直在主动调整", "自己的评判标准"])
        self.assertEqual([(cue["start"], cue["end"]) for cue in plan["cues"]],
                         [(0.14, 1.84), (2.06, 2.96)])
        self.assertEqual([cue["emphasis_words"] for cue in plan["cues"]],
                         [[], ["评判标准"]])
        self.assertEqual([cue["text"] for cue in renderer_cues],
                         [cue["text"] for cue in plan["cues"]])

    def test_chinese_words_are_kept_whole_at_cue_boundaries(self) -> None:
        text = "只是我们一直在主动调整自己。朋友知道，电动机诞生之后才爆发。"
        phrases = subtitles_v2._chinese_word_phrases(text)
        for word in ("主动", "朋友", "电动机", "之后", "爆发"):
            self.assertIn(word, phrases)
        text = "那朋友们，你们大促的时候有没有遇到说"
        words = [{"text": char, "start": index * 0.1, "end": (index + 1) * 0.1}
                 for index, char in enumerate(text)]
        visual = {"duration": 3.0, "segments": [{"segment_id": "seg-001",
                  "start": 0.0, "end": 3.0, "content_item_ids": ["idea-01"],
                  "shot_recipe": {"mode": "none"}}]}
        plan = subtitles_v2.build_render_plan(records=self.records, words=words,
            timeline=self.timeline, visual_plan=visual, keyword_index={},
            protected_phrases=("大促",))
        self.assertTrue(any("大促" in cue["text"] for cue in plan["cues"]))
        self.assertTrue(all(cue["emphasis_words"] == [] for cue in plan["cues"]))

    def test_pause_hint_does_not_create_fragments_or_split_protected_phrases(self) -> None:
        text = "只是我们一直在主动调整自己的评判标准"
        visual = {"duration": 4.0, "segments": [{"segment_id": "seg-001",
                  "start": 0.0, "end": 4.0, "content_item_ids": ["idea-01"],
                  "shot_recipe": {"mode": "none"}}]}

        def cues(gap_index=None, gap=0.0, keywords=("评判标准",)):
            words = [{"text": char,
                      "start": round(0.14 + index * 0.1 + (gap if gap_index is not None and index >= gap_index else 0), 3),
                      "end": round(0.24 + index * 0.1 + (gap if gap_index is not None and index >= gap_index else 0), 3)}
                     for index, char in enumerate(text)]
            plan = subtitles_v2.build_render_plan(records=self.records, words=words,
                timeline=self.timeline, visual_plan=visual,
                keyword_index={"idea-01": keywords})
            self.assertEqual("".join(cue["text"] for cue in plan["cues"]), text)
            self.assertTrue(all(len(cue["text"]) <= 14 for cue in plan["cues"]))
            return [cue["text"] for cue in plan["cues"]]

        baseline = cues()
        self.assertEqual(cues(11, 0.05), baseline)  # A short ASR gap is not a pause.
        self.assertEqual(cues(2, 0.5), baseline)  # Do not create a two-character cue.
        protected = ("调整自己", "评判标准")
        self.assertEqual(cues(11, 0.5, protected), cues(keywords=protected))
        self.assertTrue(any("调整自己" in cue for cue in cues(11, 0.5, protected)))

    def test_hidden_presenter_broll_keeps_regular_subtitles_without_avatar(self) -> None:
        visual_plan = copy.deepcopy(self.visual_plan)
        visual_plan["segments"][0]["shot_recipe"] = {
            "mode": "single", "composition": {"presenter_mode": "hidden"}
        }
        renderer_cues = []
        plan = subtitles_v2.build_render_plan(
            records=self.records, words=self.words, timeline=self.timeline,
            visual_plan=visual_plan, keyword_index=self.keywords,
            renderer_cues=renderer_cues,
        )
        opening = [cue for cue in plan["cues"] if cue["segment_id"] == "seg-001"]
        self.assertTrue(opening)
        self.assertTrue(all(cue["safe_zones"]["face"] is None for cue in opening))
        ids = {cue["id"] for cue in opening}
        self.assertTrue(all(cue["bottom"] == 350 for cue in renderer_cues
                            if cue["cue_id"] in ids))
        self.assertTrue(all(cue["safe_zones"]["face"] is not None
                            for cue in plan["cues"] if cue["segment_id"] == "seg-002"))

    def test_single_and_hybrid_recipes_receive_regular_subtitles(self) -> None:
        visual_plan = copy.deepcopy(self.visual_plan)
        visual_plan["segments"][0]["shot_recipe"]["mode"] = "single"
        visual_plan["segments"][0]["shot_recipe"]["composition"] = copy.deepcopy(
            visual_plan["segments"][1]["shot_recipe"]["composition"]
        )
        visual_plan["segments"][1]["shot_recipe"]["mode"] = "hybrid"

        plan = subtitles_v2.build_render_plan(
            records=self.records,
            words=self.words,
            timeline=self.timeline,
            visual_plan=visual_plan,
            keyword_index=self.keywords,
        )

        self.assertTrue(plan["cues"])
        self.assertEqual({cue["segment_id"] for cue in plan["cues"]}, {"seg-001", "seg-002"})
        self.assertTrue(all(cue["safe_zones"]["face"] is not None for cue in plan["cues"]))

    def test_aroll_cue_after_broll_does_not_start_with_stray_punctuation(self) -> None:
        visual_plan = copy.deepcopy(self.visual_plan)
        visual_plan["segments"][0]["shot_recipe"]["mode"] = "single"
        visual_plan["segments"][0]["shot_recipe"]["composition"] = copy.deepcopy(
            visual_plan["segments"][1]["shot_recipe"]["composition"]
        )
        visual_plan["segments"][1]["shot_recipe"]["mode"] = "none"
        words = [
            {"text": "前", "start": 0.1, "end": 0.2},
            {"text": "，", "start": 2.05, "end": 2.1},
            {"text": "启", "start": 2.15, "end": 2.25},
            {"text": "发", "start": 2.25, "end": 2.35},
        ]

        plan = subtitles_v2.build_render_plan(
            records=self.records,
            words=words,
            timeline=self.timeline,
            visual_plan=visual_plan,
            keyword_index={"idea-01": (), "idea-02": ("启发",)},
        )

        self.assertEqual([cue["text"] for cue in plan["cues"]], ["前", "启发"])

    def test_layout_consumes_shot_recipe_without_old_plan_translation(self) -> None:
        with mock.patch.object(
            subtitles,
            "_build_plan",
            side_effect=AssertionError("old plan builder must not be called"),
        ) as old_builder:
            plan = self._plan()

        old_builder.assert_not_called()
        self.assertNotIn("implementation", self.visual_plan["segments"][0])
        self.assertEqual({cue["type"] for cue in plan["cues"]}, {"emphasis"})

    def test_old_route_field_cannot_replace_shot_recipe(self) -> None:
        visual_plan = copy.deepcopy(self.visual_plan)
        visual_plan["segments"][0].pop("shot_recipe")
        visual_plan["segments"][0]["implementation"] = "arroll"

        with self.assertRaisesRegex(
            subtitles_v2.SubtitlesV2Error, "ShotRecipe is invalid"
        ):
            subtitles_v2.build_render_plan(
                records=self.records,
                words=self.words,
                timeline=self.timeline,
                visual_plan=visual_plan,
                keyword_index=self.keywords,
            )

    def test_publication_journal_has_one_writer(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job = SimpleNamespace(job_dir=Path(directory))
            barrier = Barrier(2)
            errors: list[BaseException] = []

            def absent_for_both(_path: object) -> bool:
                barrier.wait()
                return False

            def write() -> None:
                try:
                    subtitles_v2._write_transaction(job, {"schema_version": 1})
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                subtitles_v2.os.path,
                "lexists",
                side_effect=absent_for_both,
            ):
                threads = [Thread(target=write) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], subtitles_v2.SubtitlesV2Error)


if __name__ == "__main__":
    unittest.main()

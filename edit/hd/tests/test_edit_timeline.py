"""Tests for cleanup proposals and the approved A-roll edit timeline."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from edit.hd.tools import edit_timeline
from edit.hd.tools.edit_timeline import (
    EditTimelineError,
    build_cleanup_proposal,
    generate_cleanup_proposal,
    parse_edit_plan_json,
    render_edit,
    validate_edit_plan,
)
from edit.hd.tests.media_fixture import make_av_fixture
from edit.hd.tools.state import (
    WorkflowError,
    complete,
    create_job,
    load_job,
    mark_ready,
    revise,
)


WORDS = [
    {"text": "你好", "start": 0.5, "end": 1.0},
    {"text": "嗯", "start": 1.0, "end": 1.3},
    {"text": "世界", "start": 1.3, "end": 2.0},
]


def _correction_manifest() -> dict[str, object]:
    return {
        "version": 1,
        "source": {
            "path": "05-speech-cleanup/word-transcript.json",
            "sha256": "1" * 64,
            "bytes": 123,
        },
        "corrections": [{
            "word_start": 1,
            "word_end": 3,
            "expected_words": copy.deepcopy(WORDS[1:3]),
            "replacement_texts": ["评判", "标准"],
            "reason": "按原稿与录音人工核对",
        }],
    }


def _segment(
    action: str,
    word_start: int,
    word_end: int,
    original: str,
    cleaned: str,
    reason: str,
    *,
    before: float = 0.0,
    after: float = 0.0,
) -> dict[str, object]:
    return {
        "action": action,
        "word_start": word_start,
        "word_end": word_end,
        "source_start": WORDS[word_start]["start"],
        "source_end": WORDS[word_end - 1]["end"],
        "original_sentence": original,
        "cleaned_sentence": cleaned,
        "reason": reason,
        "breathing_padding": {"before": before, "after": after},
    }


class EditTimelineTests(unittest.TestCase):
    def test_workflow_before_payload_accepts_legacy_and_requires_strict_lineage_schema(self) -> None:
        valid = {
            "revision": 7,
            "stage": {
                "status": "needs_revision",
                "reason": "重新编排",
                "artifacts": [],
                "ai_attempts": 0,
                "lineage": [
                    {
                        "path": "06-edit-structure/edit-plan.json",
                        "sha256": "a" * 64,
                        "bytes": 17,
                        "device": 1,
                        "inode": 2,
                        "parent_device": 1,
                        "parent_inode": 3,
                    }
                ],
            },
        }
        self.assertEqual(
            edit_timeline._validate_workflow_before_payload(valid), valid,
        )

        legacy = json.loads(json.dumps(valid))
        del legacy["stage"]["lineage"]
        normalized = edit_timeline._validate_workflow_before_payload(legacy)
        self.assertEqual(normalized["stage"]["lineage"], [])

        invalid_payloads = []
        extra = json.loads(json.dumps(valid))
        extra["stage"]["lineage"][0]["extra"] = True
        invalid_payloads.append(extra)
        malformed = json.loads(json.dumps(valid))
        malformed["stage"]["lineage"][0]["inode"] = True
        invalid_payloads.append(malformed)
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(EditTimelineError):
                edit_timeline._validate_workflow_before_payload(payload)

    def test_edit_plan_accepts_only_word_boundaries(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                {
                    **_segment("keep", 0, 3, "你好嗯世界", "你好世界", "保留"),
                    "source_start": 1.023,
                }
            ],
        }
        with self.assertRaises(EditTimelineError):
            validate_edit_plan(plan, WORDS)

    def test_edit_plan_is_a_continuous_strict_word_partition(self) -> None:
        valid = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留"),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留"),
            ],
        }
        self.assertEqual(validate_edit_plan(valid, WORDS), valid)
        for invalid in (
            {**valid, "extra": True},
            {**valid, "version": True},
            {**valid, "segments": [valid["segments"][0], valid["segments"][2]]},
            {
                **valid,
                "segments": [
                    valid["segments"][0],
                    {**valid["segments"][1], "word_start": True},
                    valid["segments"][2],
                ],
            },
            {
                **valid,
                "segments": [
                    {**valid["segments"][0], "source_end": float("nan")},
                    *valid["segments"][1:],
                ],
            },
            {
                **valid,
                "segments": [
                    {**valid["segments"][0], "breathing_padding": {"before": -0.1, "after": 0.0}},
                    *valid["segments"][1:],
                ],
            },
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(EditTimelineError):
                    validate_edit_plan(invalid, WORDS)

    def test_edit_plan_v2_accepts_reviewed_cuts_hidden_by_asr(self) -> None:
        plan = {
            "version": 2,
            "segments": [
                _segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留"),
            ],
            "reviewed_cut_ranges": [{
                "source_start": 1.04,
                "source_end": 1.16,
                "reason": "人工核听确认词内口吃",
                "evidence": "whisper-dtw+人工复核",
            }],
        }
        self.assertEqual(validate_edit_plan(plan, WORDS), plan)
        proposal = build_cleanup_proposal(
            "你好嗯世界", WORDS, plan, media_duration=3.0,
        )
        self.assertEqual(
            proposal["diff_summary"]["reviewed_cut_ranges"],
            plan["reviewed_cut_ranges"],
        )
        self.assertAlmostEqual(proposal["estimated_duration"]["seconds"], 2.88)

    def test_edit_plan_v2_rejects_overlapping_or_unexplained_reviewed_cuts(self) -> None:
        base = {
            "version": 2,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
            "reviewed_cut_ranges": [{
                "source_start": 1.04,
                "source_end": 1.16,
                "reason": "人工核听",
                "evidence": "whisper-dtw",
            }],
        }
        overlapping = copy.deepcopy(base)
        overlapping["reviewed_cut_ranges"].append({
            "source_start": 1.15,
            "source_end": 1.20,
            "reason": "重叠",
            "evidence": "whisper-dtw",
        })
        unexplained = copy.deepcopy(base)
        unexplained["reviewed_cut_ranges"][0]["reason"] = ""

        for plan in (overlapping, unexplained):
            with self.subTest(plan=plan), self.assertRaises(EditTimelineError):
                validate_edit_plan(plan, WORDS)

    def test_edit_plan_json_rejects_duplicate_keys_and_nonfinite_numbers(self) -> None:
        for source in (
            '{"version":1,"version":1,"segments":[]}',
            '{"version":1,"segments":[{"source_start":NaN}]}',
            '{"version":1,"segments":[{"source_start":Infinity}]}',
        ):
            with self.subTest(source=source):
                with self.assertRaises(EditTimelineError):
                    parse_edit_plan_json(source, WORDS)

    def test_keep_cleaned_sentence_cannot_claim_different_copy(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 3, "你好嗯世界", "声称完全不同", "保留"),
            ],
        }
        with self.assertRaises(EditTimelineError):
            validate_edit_plan(plan, WORDS)
        with self.assertRaises(EditTimelineError):
            build_cleanup_proposal("你好嗯世界", WORDS, plan, media_duration=3.0)


    def test_cleanup_proposal_records_diff_and_estimated_duration(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留", after=0.05),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留", before=0.05),
            ],
        }
        proposal = build_cleanup_proposal(
            "你好嗯世界", WORDS, plan, media_duration=3.0,
        )
        self.assertEqual(proposal["cleanup_proposal"], plan)
        self.assertEqual(proposal["word_transcript"]["words"], WORDS)
        self.assertEqual(proposal["diff_summary"]["deleted_words"], ["嗯"])
        self.assertAlmostEqual(proposal["estimated_duration"]["seconds"], 2.7)


    def _assert_final_leaf_swap_is_preserved(self, label: str) -> None:
        unknown = f"unknown-{label}".encode("ascii")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = root / "generation"
            directory.mkdir()
            leaf = directory / "artifact.bin" if label == "generation" else root / label
            leaf.write_bytes(b"owned artifact")
            real_ftruncate = os.ftruncate
            raced = False

            def truncate_after_swap(descriptor, length):
                nonlocal raced
                if not raced:
                    raced = True
                    opened = os.fstat(descriptor)
                    leaves = [path for path in root.rglob("*")
                              if path.is_file() and os.path.samestat(opened, os.lstat(path))]
                    self.assertEqual(len(leaves), 1)
                    current = leaves[0]
                    current.replace(current.with_name(current.name + ".owned"))
                    current.write_bytes(unknown)
                return real_ftruncate(descriptor, length)

            with mock.patch.object(os, "ftruncate", side_effect=truncate_after_swap):
                if label == "generation":
                    edit_timeline._discard_directory(directory, {leaf.name})
                else:
                    edit_timeline._retire_pin(edit_timeline._pin_path(leaf), label)
            self.assertTrue(raced)
            self.assertEqual(sum(path.is_file() and path.read_bytes() == unknown
                                 for path in root.rglob("*")), 1)

    def test_generation_final_leaf_swap_preserves_unknown(self) -> None:
        self._assert_final_leaf_swap_is_preserved("generation")

    def test_marker_final_leaf_swap_preserves_unknown(self) -> None:
        self._assert_final_leaf_swap_is_preserved("marker")

    def test_lock_final_leaf_swap_preserves_unknown(self) -> None:
        self._assert_final_leaf_swap_is_preserved("lock")

    def test_unapproved_cleanup_cannot_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "edit" / "hd" / "jobs").mkdir(parents=True)
            video = root / "video.mp4"
            script = root / "script.txt"
            video.write_bytes(b"not-media")
            script.write_text("你好世界", encoding="utf-8")
            job = create_job(root, video, script, profile="full-v2")
            with self.assertRaises(WorkflowError):
                render_edit(job)


    def test_current_jobs_delegate_cleanup_and_render_to_the_single_v2_runner(self) -> None:
        job = SimpleNamespace(version=2)
        plan = {"version": 1, "segments": []}
        output = Path("/unused/current-output.json")
        with mock.patch("edit.hd.tools.speech_edit_v2.prepare_cleanup_proposal", return_value=output) as cleanup:
            self.assertEqual(generate_cleanup_proposal(job, plan), output)
        cleanup.assert_called_once_with(job, plan)
        with mock.patch("edit.hd.tools.speech_edit_v2.render_edit", return_value=output) as render:
            self.assertEqual(render_edit(job), output)
        render.assert_called_once_with(job)


class TranscriptCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory()
        cls.fixture = make_av_fixture(Path(cls.fixture_temporary.name).resolve())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def _revised_cleanup_job(self, root: Path):
        job, previous, corrections = self._full_v2_cleanup_job(root, explicit_revision=True)
        plan = json.loads(previous["cleanup-proposal.json"])
        manifest = json.loads(corrections.read_text(encoding="utf-8"))
        return job, previous, plan, manifest, corrections

    def _full_v2_cleanup_job(
        self,
        root: Path,
        *,
        explicit_revision: bool,
        historical_inventory: bool = False,
        tampered_terminology: bool = False,
        bound_terminology: bool = False,
    ):
        video = root / "video.mp4"
        script = root / "script.txt"
        shutil.copyfile(self.fixture, video)
        script.write_text("你好嗯世界", encoding="utf-8")
        job = create_job(root, video, script, profile="full-v2")

        inspect_dir = job.job_dir / "01-inspect"
        inspect_dir.mkdir()
        inspect_report = inspect_dir / "report.json"
        inspect_report.write_text('{"schema_version":1}\n', encoding="utf-8")
        mark_ready(job, "inspect", (inspect_report,))
        complete(job, "inspect")
        from edit.hd.tools import content_analysis

        content_analysis.prepare_content_analysis(job, {
            "thesis": "清理口播中的语气词",
            "hook": "你好，世界",
            "sections": [{
                "id": "section-1",
                "title": "完整口播",
                "source_span": [0, len("你好嗯世界")],
            }],
            "items": [{
                "id": "item-1",
                "source_text": "你好嗯世界",
                "source_span": [0, len("你好嗯世界")],
                "priority": "high",
                "keywords": ["你好", "世界"],
                "semantic_type": "thesis",
                "evidence_status": "supported",
                "broll_priority": "medium",
            }],
            "claims": [],
        })
        complete(job, "content_analysis")
        approved_content = content_analysis.load_approved_content_analysis(job)
        for stage_id, relative in (
            ("cover_direction", "03-cover-direction/review.html"),
            ("cover", "04-cover/cover.png"),
        ):
            artifact = job.job_dir / relative
            artifact.parent.mkdir()
            artifact.write_bytes(stage_id.encode("utf-8"))
            mark_ready(job, stage_id, (artifact,))
            complete(job, stage_id)

        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留"),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留"),
            ],
        }
        proposal = build_cleanup_proposal(
            "你好嗯世界", WORDS, plan, media_duration=2.0,
        )
        if bound_terminology or tampered_terminology:
            from edit.hd.tools import terminology_review

            proposal["diff_summary"]["terminology_review"] = (
                terminology_review.build_bound_report(
                    WORDS,
                    content_record=approved_content,
                    summary=proposal["diff_summary"],
                )
            )
            if tampered_terminology:
                proposal["diff_summary"]["terminology_review"][
                    "content_analysis_sha256"
                ] = "0" * 64
        speech_dir = job.job_dir / "05-speech-cleanup"
        speech_dir.mkdir()
        (speech_dir / "speech-16k.wav").write_bytes(b"wav")
        (speech_dir / "scribe.json").write_text(
            '{"source":"fixture"}\n', encoding="utf-8",
        )
        (speech_dir / "report.json").write_text(
            '{"version":1}\n', encoding="utf-8",
        )
        for name, payload in {
            "word-transcript.json": proposal["word_transcript"],
            "diff-summary.json": proposal["diff_summary"],
            "cleanup-proposal.json": proposal["cleanup_proposal"],
            "estimated-duration.json": proposal["estimated_duration"],
        }.items():
            (speech_dir / name).write_text(
                json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
        from edit.hd.tools import material_usage

        proposal_artifacts = tuple(
            speech_dir / name for name in sorted(edit_timeline._V2_PROPOSAL_NAMES)
        )
        if historical_inventory:
            mark_ready(job, "speech_cleanup", proposal_artifacts)
        else:
            material_usage.publish_and_mark_ready(
                job,
                "speech_cleanup",
                proposal_artifacts,
                producer="edit.hd.tools.speech_edit_v2",
                producer_version="1",
                stage_input_records=material_usage.current_stage_input_records(
                    job, "speech_cleanup"
                ),
                references=[],
            )
        complete(job, "speech_cleanup")
        original = {
            name: (speech_dir / name).read_bytes()
            for name in edit_timeline._V2_PROPOSAL_NAMES
        }

        if explicit_revision:
            revise(job, "speech_cleanup", "修正人工核对错词")
            records = job.stages["speech_cleanup"]["lineage"]
        else:
            records = job.stages["speech_cleanup"]["artifacts"]
        source = next(
            record for record in records
            if record["path"] == "05-speech-cleanup/word-transcript.json"
        )
        manifest = _correction_manifest()
        manifest["source"] = {
            key: source[key] for key in ("path", "sha256", "bytes")
        }
        corrections = root / "corrections-v2.json"
        corrections.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return job, original, corrections

    def _assert_failed_revision_is_intact(
        self,
        job,
        expected_tree: dict[str, bytes],
        expected_lineage: list[dict[str, object]],
    ) -> None:
        target = job.job_dir / "05-speech-cleanup"
        self.assertEqual(
            {name: (target / name).read_bytes() for name in edit_timeline._V2_PROPOSAL_NAMES},
            expected_tree,
        )
        persisted = load_job(job.job_dir)
        self.assertEqual(persisted.stages["speech_cleanup"]["status"], "needs_revision")
        self.assertEqual(persisted.stages["speech_cleanup"]["artifacts"], [])
        self.assertEqual(persisted.stages["speech_cleanup"]["lineage"], expected_lineage)
        self.assertFalse(list(job.job_dir.glob(".05-speech-cleanup.stage-*")))
        self.assertFalse(list(job.job_dir.glob(".05-speech-cleanup.backup-*")))

    def test_accepts_exact_manifest(self) -> None:
        payload = _correction_manifest()

        parsed = edit_timeline.parse_transcript_corrections_json(
            json.dumps(payload, ensure_ascii=False),
        )

        self.assertEqual(parsed, payload)

    def test_rejects_ambiguous_or_overlapping_manifest(self) -> None:
        payload = _correction_manifest()
        cases: list[tuple[str, str]] = []

        extra = copy.deepcopy(payload)
        extra["extra"] = True
        cases.append(("extra top-level key", json.dumps(extra)))

        extra_source = copy.deepcopy(payload)
        extra_source["source"]["inode"] = 7
        cases.append(("extra source key", json.dumps(extra_source)))

        extra_correction = copy.deepcopy(payload)
        extra_correction["corrections"][0]["note"] = "ambiguous"
        cases.append(("extra correction key", json.dumps(extra_correction)))

        bool_index = copy.deepcopy(payload)
        bool_index["corrections"][0]["word_start"] = True
        cases.append(("boolean index", json.dumps(bool_index)))

        blank_reason = copy.deepcopy(payload)
        blank_reason["corrections"][0]["reason"] = "   "
        cases.append(("blank reason", json.dumps(blank_reason)))

        unequal = copy.deepcopy(payload)
        unequal["corrections"][0]["replacement_texts"] = ["评判"]
        cases.append(("unequal replacement count", json.dumps(unequal)))

        overlap = copy.deepcopy(payload)
        overlap["corrections"].append({
            "word_start": 2,
            "word_end": 3,
            "expected_words": copy.deepcopy(WORDS[2:3]),
            "replacement_texts": ["重复"],
            "reason": "重叠",
        })
        cases.append(("overlap", json.dumps(overlap)))

        descending = copy.deepcopy(payload)
        descending["corrections"] = list(reversed([
            {
                "word_start": 0,
                "word_end": 1,
                "expected_words": copy.deepcopy(WORDS[0:1]),
                "replacement_texts": ["你们好"],
                "reason": "第一处",
            },
            *descending["corrections"],
        ]))
        cases.append(("descending", json.dumps(descending)))

        duplicate = (
            '{"version":1,"version":1,"source":'
            '{"path":"05-speech-cleanup/word-transcript.json",'
            '"sha256":"' + "1" * 64 + '","bytes":123},"corrections":[]}'
        )
        cases.append(("duplicate key", duplicate))

        for label, source in cases:
            with self.subTest(label=label), self.assertRaises(EditTimelineError):
                edit_timeline.parse_transcript_corrections_json(source)

    def test_rejects_whitespace_only_expected_and_replacement_text(self) -> None:
        for field in ("expected", "replacement"):
            with self.subTest(field=field):
                payload = _correction_manifest()
                if field == "expected":
                    payload["corrections"][0]["expected_words"][0]["text"] = " \t "
                else:
                    payload["corrections"][0]["replacement_texts"][0] = " \n "
                with self.assertRaises(EditTimelineError):
                    edit_timeline.parse_transcript_corrections_json(
                        json.dumps(payload, ensure_ascii=False),
                    )

    def test_accepts_nonblank_correction_text_with_surrounding_spaces(self) -> None:
        payload = _correction_manifest()
        payload["corrections"][0]["expected_words"][0]["text"] = " 嗯 "
        payload["corrections"][0]["replacement_texts"][0] = " 评判 "

        parsed = edit_timeline.parse_transcript_corrections_json(
            json.dumps(payload, ensure_ascii=False),
        )

        self.assertEqual(parsed, payload)

    def test_applies_text_only_after_exact_expected_word_match(self) -> None:
        manifest = _correction_manifest()
        before = copy.deepcopy(WORDS)

        corrected = edit_timeline.apply_transcript_corrections(WORDS, manifest)

        self.assertEqual([word["text"] for word in corrected], ["你好", "评判", "标准"])
        self.assertEqual(
            [(word["start"], word["end"]) for word in corrected],
            [(word["start"], word["end"]) for word in WORDS],
        )
        self.assertEqual(WORDS, before)

    def test_rejects_expected_word_mismatch_without_mutating_input(self) -> None:
        manifest = _correction_manifest()
        manifest["corrections"][0]["expected_words"][0]["text"] = "错误原词"
        before = copy.deepcopy(WORDS)

        with self.assertRaises(EditTimelineError):
            edit_timeline.apply_transcript_corrections(WORDS, manifest)

        self.assertEqual(WORDS, before)

    def test_rebuilds_current_artifacts_from_revision_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, old_plan, manifest, corrections = self._revised_cleanup_job(root)

            proposal_path = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready")
            self.assertEqual(job.stages["edit_structure"]["status"], "pending")
            self.assertEqual(
                {Path(record["path"]).name for record in job.stages["speech_cleanup"]["artifacts"]},
                {*edit_timeline._V2_PROPOSAL_NAMES, "material-usage.json"},
            )
            self.assertEqual(proposal_path.name, "cleanup-proposal.json")
            for name in edit_timeline._V2_TASK2_NAMES:
                self.assertEqual((proposal_path.parent / name).read_bytes(), previous[name])

            corrected_words = json.loads(
                (proposal_path.parent / "word-transcript.json").read_text(encoding="utf-8")
            )["words"]
            self.assertEqual(
                [word["text"] for word in corrected_words],
                ["你好", "评判", "标准"],
            )
            corrected_plan = json.loads(proposal_path.read_text(encoding="utf-8"))
            for before, after in zip(old_plan["segments"], corrected_plan["segments"]):
                for key in (
                    "action", "word_start", "word_end", "source_start", "source_end",
                    "reason", "breathing_padding",
                ):
                    self.assertEqual(after[key], before[key])
            self.assertEqual(corrected_plan["segments"][0]["cleaned_sentence"], "你好")
            self.assertEqual(corrected_plan["segments"][1]["original_sentence"], "评判")
            self.assertEqual(corrected_plan["segments"][1]["cleaned_sentence"], "")
            self.assertEqual(corrected_plan["segments"][2]["original_sentence"], "标准")
            self.assertEqual(corrected_plan["segments"][2]["cleaned_sentence"], "标准")

            summary = json.loads(
                (proposal_path.parent / "diff-summary.json").read_text(encoding="utf-8")
            )
            audit = summary["transcript_corrections"]
            self.assertEqual(audit["version"], 1)
            self.assertEqual(len(audit["runs"]), 1)
            run = audit["runs"][0]
            self.assertEqual(run["source"], manifest["source"])
            self.assertEqual(
                run["manifest"]["sha256"],
                hashlib.sha256(corrections.read_bytes()).hexdigest(),
            )
            self.assertEqual(run["manifest"]["bytes"], len(corrections.read_bytes()))
            self.assertEqual(run["changes"], [{
                "word_start": 1,
                "word_end": 3,
                "before": ["嗯", "世界"],
                "after": ["评判", "标准"],
                "reason": "按原稿与录音人工核对",
            }])
            self.assertEqual(summary["cleaned_script"], "你好标准")

    def test_full_v2_correction_rebuilds_current_generation_after_explicit_revision(
        self,
    ) -> None:
        from edit.hd.tools import content_analysis, speech_edit_v2

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, corrections = self._full_v2_cleanup_job(
                root, explicit_revision=True,
            )
            revision_after_request = job.revision

            output = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(output.parent, job.job_dir / "05-speech-cleanup")
            self.assertFalse((job.job_dir / "02-speech-cleanup").exists())
            self.assertEqual(job.revision, revision_after_request + 1)
            self.assertEqual(
                job.stages["speech_cleanup"]["status"], "ready",
            )
            self.assertEqual(
                {Path(item["path"]).name for item in job.stages["speech_cleanup"]["artifacts"]},
                {*edit_timeline._V2_PROPOSAL_NAMES, "material-usage.json"},
            )
            from edit.hd.tools import material_usage

            receipt = material_usage.load_current_receipt(job, "speech_cleanup")
            self.assertEqual(receipt["stage_revision"], job.revision)
            self.assertEqual(receipt["references"], [])
            for name in edit_timeline._V2_TASK2_NAMES:
                self.assertEqual((output.parent / name).read_bytes(), previous[name])
            corrected = json.loads(
                (output.parent / "word-transcript.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [word["text"] for word in corrected["words"]],
                ["你好", "评判", "标准"],
            )
            summary = json.loads(
                (output.parent / "diff-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                summary["terminology_review"]["approved_terms"],
                ["你好", "世界"],
            )
            self.assertEqual(
                summary["terminology_review"]["content_analysis_sha256"],
                content_analysis.load_approved_content_analysis(job)[
                    "analysis_sha256"
                ],
            )
            estimate = json.loads(
                (output.parent / "estimated-duration.json").read_text(encoding="utf-8")
            )
            corrected_plan = json.loads(
                (output.parent / "cleanup-proposal.json").read_text(encoding="utf-8")
            )
            expected_intervals = speech_edit_v2._video_use_intervals(
                corrected_plan, estimate["source_seconds"],
            )
            self.assertAlmostEqual(
                estimate["seconds"],
                sum(end - start for start, end in expected_intervals),
            )
            self.assertGreater(expected_intervals[0][0], 0.4)

    def test_full_v2_correction_after_content_keywords_expand(self) -> None:
        from edit.hd.tools import content_analysis

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _, corrections = self._full_v2_cleanup_job(
                root, explicit_revision=False, bound_terminology=True,
            )
            analysis = content_analysis.load_approved_content_analysis(job)["analysis"]
            analysis["items"][0]["keywords"].append("嗯")
            revise(job, "content_analysis", "增加已提供原稿中的重点词")
            content_analysis.prepare_content_analysis(job, analysis)
            complete(job, "content_analysis")
            for stage_id, relative in (
                ("cover_direction", "03-cover-direction/review.html"),
                ("cover", "04-cover/cover.png"),
            ):
                mark_ready(job, stage_id, (job.job_dir / relative,))
                complete(job, stage_id)
            revise(job, "speech_cleanup", "修正错词")

            output = edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            summary = json.loads((output.parent / "diff-summary.json").read_text())
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready")
            self.assertEqual(
                summary["terminology_review"]["content_analysis_sha256"],
                content_analysis.load_approved_content_analysis(job)["analysis_sha256"],
            )
            self.assertEqual(summary["terminology_review"]["approved_terms"], ["你好", "世界", "嗯"])
            self.assertEqual(summary["cleaned_script"], "你好标准")

    def test_full_v2_correction_requires_an_explicit_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, corrections = self._full_v2_cleanup_job(
                root, explicit_revision=False,
            )
            revision_before = job.revision

            with self.assertRaises(EditTimelineError):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self.assertEqual(job.revision, revision_before)
            self.assertEqual(job.stages["speech_cleanup"]["status"], "completed")
            self.assertEqual(
                {
                    name: (job.job_dir / "05-speech-cleanup" / name).read_bytes()
                    for name in edit_timeline._V2_PROPOSAL_NAMES
                },
                previous,
            )
            self.assertFalse((job.job_dir / "02-speech-cleanup").exists())

    def test_full_v2_correction_upgrades_historical_seven_file_generation(
        self,
    ) -> None:
        from edit.hd.tools import material_usage

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _previous, corrections = self._full_v2_cleanup_job(
                root,
                explicit_revision=True,
                historical_inventory=True,
            )
            self.assertEqual(
                {Path(record["path"]).name for record in job.stages[
                    "speech_cleanup"
                ]["lineage"]},
                edit_timeline._V2_PROPOSAL_NAMES,
            )

            output = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(
                {Path(record["path"]).name for record in job.stages[
                    "speech_cleanup"
                ]["artifacts"]},
                {*edit_timeline._V2_PROPOSAL_NAMES, "material-usage.json"},
            )
            summary = json.loads(
                (output.parent / "diff-summary.json").read_text(encoding="utf-8")
            )
            self.assertIn("terminology_review", summary)
            receipt = material_usage.load_current_receipt(job, "speech_cleanup")
            self.assertEqual(receipt["stage_revision"], job.revision)

    def test_full_v2_correction_rejects_tampered_bound_terminology(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, corrections = self._full_v2_cleanup_job(
                root,
                explicit_revision=True,
                tampered_terminology=True,
            )
            revision_before = job.revision

            with self.assertRaises(EditTimelineError):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self.assertEqual(job.revision, revision_before)
            self.assertEqual(
                job.stages["speech_cleanup"]["status"], "needs_revision",
            )
            self.assertEqual(
                {
                    name: (job.job_dir / "05-speech-cleanup" / name).read_bytes()
                    for name in edit_timeline._V2_PROPOSAL_NAMES
                },
                previous,
            )

    def test_full_v2_correction_ready_failure_restores_and_same_retry_succeeds(
        self,
    ) -> None:
        from edit.hd.tools import speech_edit_v2

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, corrections = self._full_v2_cleanup_job(
                root, explicit_revision=True,
            )

            with mock.patch.object(
                speech_edit_v2.state,
                "mark_ready",
                side_effect=RuntimeError("injected ready failure"),
            ), self.assertRaises(EditTimelineError):
                edit_timeline.generate_corrected_cleanup_proposal(
                    job, corrections,
                )

            target = job.job_dir / "05-speech-cleanup"
            self.assertEqual(
                {name: (target / name).read_bytes() for name in previous},
                previous,
            )
            self.assertEqual(
                load_job(job.job_dir).stages["speech_cleanup"]["status"],
                "needs_revision",
            )

            output = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(output.parent, target)
            self.assertEqual(
                job.stages["speech_cleanup"]["status"], "ready",
            )

    def test_full_v2_correction_interruption_recovers_on_same_retry(
        self,
    ) -> None:
        from edit.hd.tools import speech_edit_v2

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _previous, corrections = self._full_v2_cleanup_job(
                root, explicit_revision=True,
            )

            def stop_after_journal(name: str) -> None:
                if name == "marker_durable":
                    raise KeyboardInterrupt

            with mock.patch.object(
                speech_edit_v2.edit_timeline,
                "_crash_checkpoint",
                side_effect=stop_after_journal,
            ), self.assertRaises(EditTimelineError):
                edit_timeline.generate_corrected_cleanup_proposal(
                    job, corrections,
                )

            marker = job.job_dir / ".05-speech-cleanup.generation.marker"
            self.assertTrue(marker.is_file())

            output = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(output.parent, job.job_dir / "05-speech-cleanup")
            self.assertEqual(
                job.stages["speech_cleanup"]["status"], "ready",
            )
            self.assertFalse(marker.exists())

    def test_preserves_raw_asr_evidence_and_every_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            old_words = json.loads(previous["word-transcript.json"])["words"]

            proposal_path = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            new_words = json.loads(
                (proposal_path.parent / "word-transcript.json").read_text(encoding="utf-8")
            )["words"]
            self.assertEqual(len(new_words), len(old_words))
            self.assertEqual(
                [(word["start"], word["end"]) for word in new_words],
                [(word["start"], word["end"]) for word in old_words],
            )
            for name in ("speech-16k.wav", "scribe.json", "report.json"):
                self.assertEqual((proposal_path.parent / name).read_bytes(), previous[name])

    def test_accepts_read_only_corrections_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            corrections.chmod(0o400)

            proposal_path = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertTrue(proposal_path.is_file())
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready")

    def test_rejects_lineage_file_identity_hash_or_parent_drift_fail_closed(self) -> None:
        for drift in ("inode", "hash", "parent"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job, _previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
                target = job.job_dir / "05-speech-cleanup"
                transcript = target / "word-transcript.json"
                if drift == "inode":
                    replacement = root / "replacement.json"
                    replacement.write_bytes(transcript.read_bytes())
                    os.replace(replacement, transcript)
                elif drift == "hash":
                    transcript.write_bytes(transcript.read_bytes() + b" ")
                else:
                    retired = job.job_dir / "retired-speech-cleanup"
                    os.replace(target, retired)
                    target.mkdir()
                    for name in edit_timeline._V2_PROPOSAL_NAMES:
                        shutil.copyfile(retired / name, target / name)
                expected_tree = {
                    name: (target / name).read_bytes()
                    for name in edit_timeline._V2_PROPOSAL_NAMES
                }
                lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])

                with self.assertRaises(EditTimelineError):
                    edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

                self._assert_failed_revision_is_intact(job, expected_tree, lineage)

    def test_rejects_manifest_source_or_expected_word_mismatch_fail_closed(self) -> None:
        for mismatch in ("source", "expected"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job, previous, _plan, manifest, corrections = self._revised_cleanup_job(root)
                if mismatch == "source":
                    manifest["source"]["sha256"] = "f" * 64
                else:
                    manifest["corrections"][0]["expected_words"][0]["text"] = "错位"
                corrections.write_text(
                    json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8",
                )
                lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])

                with self.assertRaises(EditTimelineError):
                    edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

                self._assert_failed_revision_is_intact(job, previous, lineage)

    def test_rejects_corrections_replacement_after_pin_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])
            original_fsync = edit_timeline._fsync_directory
            replaced = False

            def replace_manifest(directory: Path) -> None:
                nonlocal replaced
                original_fsync(directory)
                if directory.name.startswith(".05-speech-cleanup.stage-") and not replaced:
                    replacement = corrections.with_suffix(".replacement")
                    replacement.write_text('{}\n', encoding="utf-8")
                    os.replace(replacement, corrections)
                    replaced = True

            with (
                mock.patch.object(edit_timeline, "_fsync_directory", side_effect=replace_manifest),
                self.assertRaises(EditTimelineError),
            ):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self.assertTrue(replaced)
            self._assert_failed_revision_is_intact(job, previous, lineage)

    def test_rejects_cleanup_tree_replacement_between_lineage_check_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])
            target = job.job_dir / "05-speech-cleanup"
            foreign = root / "foreign-speech-cleanup"
            retired = root / "retired-speech-cleanup"
            shutil.copytree(target, foreign)
            real_swap = edit_timeline._swap_generation
            replacement_identity: tuple[int, int] | None = None

            def replace_tree_then_swap(*args, **kwargs) -> None:
                nonlocal replacement_identity
                os.replace(target, retired)
                os.replace(foreign, target)
                status = os.lstat(target)
                replacement_identity = (status.st_dev, status.st_ino)
                real_swap(*args, **kwargs)

            with (
                mock.patch.object(
                    edit_timeline,
                    "_swap_generation",
                    side_effect=replace_tree_then_swap,
                ),
                self.assertRaises(EditTimelineError),
            ):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self.assertIsNotNone(replacement_identity)
            current = os.lstat(target)
            self.assertEqual((current.st_dev, current.st_ino), replacement_identity)
            self._assert_failed_revision_is_intact(job, previous, lineage)

    def test_pre_publish_interruption_keeps_old_generation_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])

            with (
                mock.patch.object(edit_timeline, "_swap_generation", side_effect=RuntimeError("stop")),
                self.assertRaises(EditTimelineError),
            ):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self._assert_failed_revision_is_intact(job, previous, lineage)

    def test_publish_exchange_failure_restores_old_generation_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            lineage = copy.deepcopy(job.stages["speech_cleanup"]["lineage"])
            real_replace = edit_timeline._replace
            calls = 0

            def fail_second(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("exchange failed")
                real_replace(source, destination)

            with (
                mock.patch.object(edit_timeline, "_replace", side_effect=fail_second),
                self.assertRaises(EditTimelineError),
            ):
                edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            self.assertGreaterEqual(calls, 3)
            self._assert_failed_revision_is_intact(job, previous, lineage)

    def test_marker_retired_crash_recovers_corrected_revision_and_reruns(self) -> None:
        child_source = """
import sys
from pathlib import Path
from types import SimpleNamespace
from edit.hd.tools.edit_timeline import generate_corrected_cleanup_proposal
from edit.hd.tools.state import load_job
generate_corrected_cleanup_proposal(load_job(Path(sys.argv[1])), Path(sys.argv[2]))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_retired"
            child = subprocess.run(
                [sys.executable, "-c", child_source, str(job.job_dir), str(corrections)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91, child.stderr.decode(errors="replace"))
            recovered = load_job(job.job_dir)
            self.assertEqual(
                recovered.stages["speech_cleanup"]["status"], "ready",
            )

            output = edit_timeline.generate_corrected_cleanup_proposal(
                recovered, corrections,
            )

            self.assertTrue(output.is_file())
            self.assertEqual(
                recovered.stages["speech_cleanup"]["status"], "ready",
            )
            self.assertFalse((job.job_dir / ".05-speech-cleanup.lock").exists())

    def test_crash_recovery_rejects_a_different_corrections_manifest(self) -> None:
        child_source = """
import sys
from pathlib import Path
from types import SimpleNamespace
from edit.hd.tools.edit_timeline import generate_corrected_cleanup_proposal
from edit.hd.tools.state import load_job
generate_corrected_cleanup_proposal(load_job(Path(sys.argv[1])), Path(sys.argv[2]))
"""
        for checkpoint in ("workflow_ready", "marker_retired"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job, _previous, _plan, manifest, corrections = self._revised_cleanup_job(root)
                environment = os.environ.copy()
                environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = checkpoint
                child = subprocess.run(
                    [sys.executable, "-c", child_source, str(job.job_dir), str(corrections)],
                    cwd=Path(__file__).resolve().parents[3],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(
                    child.returncode, 91, child.stderr.decode(errors="replace"),
                )
                different = copy.deepcopy(manifest)
                different["corrections"][0]["reason"] = "另一份人工复核说明"
                different_path = root / "different-corrections.json"
                different_path.write_text(
                    json.dumps(different, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                metadata = {
                    path.name: path.read_bytes()
                    for path in (
                        job.job_dir / ".05-speech-cleanup.lock",
                        edit_timeline._marker_path(
                            job.job_dir, "05-speech-cleanup",
                        ),
                    )
                    if path.exists()
                }
                target = job.job_dir / "05-speech-cleanup"
                published = {
                    name: (target / name).read_bytes()
                    for name in edit_timeline._V2_PROPOSAL_NAMES
                }

                recovered = load_job(job.job_dir)
                with self.assertRaises(EditTimelineError):
                    edit_timeline.generate_corrected_cleanup_proposal(
                        recovered, different_path,
                    )

                self.assertEqual(
                    {
                        path.name: path.read_bytes()
                        for path in (
                            job.job_dir / ".05-speech-cleanup.lock",
                            edit_timeline._marker_path(
                                job.job_dir, "05-speech-cleanup",
                            ),
                        )
                        if path.exists()
                    },
                    metadata,
                )
                self.assertEqual(
                    {
                        name: (target / name).read_bytes()
                        for name in edit_timeline._V2_PROPOSAL_NAMES
                    },
                    published,
                )
                output = edit_timeline.generate_corrected_cleanup_proposal(
                    load_job(job.job_dir), corrections,
                )
                self.assertTrue(output.is_file())

    def test_two_explicit_revisions_append_versioned_correction_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, _previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
            first_output = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )
            first_words = json.loads(
                (first_output.parent / "word-transcript.json").read_text(encoding="utf-8")
            )["words"]
            complete(job, "speech_cleanup")
            revise(job, "speech_cleanup", "第二轮人工核对")
            source = next(
                record for record in job.stages["speech_cleanup"]["lineage"]
                if record["path"] == "05-speech-cleanup/word-transcript.json"
            )
            second_manifest = {
                "version": 1,
                "source": {key: source[key] for key in ("path", "sha256", "bytes")},
                "corrections": [{
                    "word_start": 1,
                    "word_end": 3,
                    "expected_words": copy.deepcopy(first_words[1:3]),
                    "replacement_texts": ["审查", "准则"],
                    "reason": "第二轮按录音人工核对",
                }],
            }
            second_corrections = root / "second-corrections.json"
            second_corrections.write_text(
                json.dumps(second_manifest, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            second_output = edit_timeline.generate_corrected_cleanup_proposal(
                job, second_corrections,
            )

            second_words = json.loads(
                (second_output.parent / "word-transcript.json").read_text(encoding="utf-8")
            )["words"]
            self.assertEqual(
                [word["text"] for word in second_words], ["你好", "审查", "准则"],
            )
            summary = json.loads(
                (second_output.parent / "diff-summary.json").read_text(encoding="utf-8")
            )
            audit = summary["transcript_corrections"]
            self.assertEqual(audit["version"], 1)
            self.assertEqual(len(audit["runs"]), 2)
            self.assertEqual(
                audit["runs"][0]["changes"][0]["after"], ["评判", "标准"],
            )
            self.assertEqual(
                audit["runs"][1]["changes"][0]["before"], ["评判", "标准"],
            )
            self.assertEqual(
                audit["runs"][1]["changes"][0]["after"], ["审查", "准则"],
            )


if __name__ == "__main__":
    unittest.main()

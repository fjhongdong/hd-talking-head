"""Tests for cleanup proposals and the approved A-roll edit timeline."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import signal
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from edit.hd.tools import edit_timeline
from edit.hd.tools.edit_timeline import (
    EditTimelineError,
    build_cleanup_proposal,
    generate_cleanup_proposal,
    parse_edit_plan_json,
    render_edit,
    validate_edit_plan,
)
from edit.hd.tests.media_fixture import assert_complete_decode, make_av_fixture
from edit.hd.tools.inspect_inputs import inspect_job
from edit.hd.tools.state import (
    STAGE_IDS,
    WorkflowError,
    approve,
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
_EDIT_OUTPUT_NAMES = {"edit-plan.json", "edited-aroll.mp4", "timeline-map.json"}


def _correction_manifest() -> dict[str, object]:
    return {
        "version": 1,
        "source": {
            "path": "02-speech-cleanup/word-transcript.json",
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
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory()
        cls.fixture = make_av_fixture(Path(cls.fixture_temporary.name).resolve())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def _job_with_transcript_ready(self, root: Path):
        video = root / "video.mp4"
        script = root / "script.txt"
        shutil.copyfile(self.fixture, video)
        script.write_text("你好嗯世界", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        inspect_job(job)
        approve(job, "inspect")
        transcript_dir = job.job_dir / "02-speech-cleanup"
        transcript_dir.mkdir()
        (transcript_dir / "speech-16k.wav").write_bytes(b"wav")
        (transcript_dir / "whisper.json").write_text('{"source":"fixture"}\n', encoding="utf-8")
        report = transcript_dir / "report.json"
        report.write_text(
            json.dumps(
                {
                    "version": 1,
                    "runtime": {"engine": "whisper.cpp", "model_sha256": "0" * 64},
                    "script": {"sha256": "1" * 64, "bytes": 18, "coverage": 1.0},
                    "transcript": {
                        "word_count": len(WORDS),
                        "first": WORDS[0]["start"],
                        "last": WORDS[-1]["end"],
                        "words": WORDS,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        mark_ready(
            job,
            "speech_cleanup",
            [transcript_dir / "speech-16k.wav", transcript_dir / "whisper.json", report],
        )
        return job

    def _job_ready_for_render(
        self,
        root: Path,
        plan: dict[str, object],
        *,
        words: list[dict[str, object]] | None = None,
    ):
        transcript_words = WORDS if words is None else words
        video = root / "video.mp4"
        script = root / "script.txt"
        shutil.copyfile(self.fixture, video)
        script.write_text("你好嗯世界", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        inspect_job(job)
        approve(job, "inspect")
        speech_dir = job.job_dir / "02-speech-cleanup"
        speech_dir.mkdir()
        payloads = {
            "speech-16k.wav": b"wav",
            "whisper.json": b'{"source":"fixture"}\n',
            "report.json": b'{"version":1}\n',
            "word-transcript.json": (
                json.dumps(
                    {"version": 1, "words": transcript_words},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
            "diff-summary.json": b'{"version":1}\n',
            "cleanup-proposal.json": (
                json.dumps(plan, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            ).encode("utf-8"),
            "estimated-duration.json": b'{"version":1,"seconds":3.0}\n',
        }
        for name, source in payloads.items():
            (speech_dir / name).write_bytes(source)
        mark_ready(job, "speech_cleanup", [speech_dir / name for name in sorted(payloads)])
        approve(job, "speech_cleanup")
        return job

    def _audio_elementary_hash(self, source: Path, destination: Path) -> str:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(source), "-map", "0:a:0", "-c:a", "copy", "-f", "adts",
                str(destination),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=True,
        )
        return hashlib.sha256(destination.read_bytes()).hexdigest()

    def _artifact_lineage(self, job, stage_id: str) -> list[dict[str, object]]:
        records = []
        for artifact in job.stages[stage_id]["artifacts"]:
            path = job.job_dir / artifact["path"]
            status = os.lstat(path)
            parent = os.lstat(path.parent)
            records.append({
                **artifact,
                "device": status.st_dev,
                "inode": status.st_ino,
                "parent_device": parent.st_dev,
                "parent_inode": parent.st_ino,
            })
        return records

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
                        "path": "03-edit-structure/edit-plan.json",
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

    def test_multiple_all_keep_segments_preserve_natural_pauses_and_audio(self) -> None:
        words = [
            {"text": "甲", "start": 0.2, "end": 0.7},
            {"text": "乙", "start": 1.1, "end": 1.5},
            {"text": "丙", "start": 2.0, "end": 2.4},
        ]
        plan = {
            "version": 1,
            "segments": [
                {
                    **_segment("keep", 0, 1, "甲", "甲", "保留"),
                    "source_start": 0.2,
                    "source_end": 0.7,
                },
                {
                    **_segment("keep", 1, 2, "乙", "乙", "保留"),
                    "source_start": 1.1,
                    "source_end": 1.5,
                },
                {
                    **_segment("keep", 2, 3, "丙", "丙", "保留"),
                    "source_start": 2.0,
                    "source_end": 2.4,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan, words=words)
            source_hash = self._audio_elementary_hash(
                root / "video.mp4", root / "source-all-keep.aac",
            )
            output = render_edit(job)
            rendered_hash = self._audio_elementary_hash(
                output, root / "rendered-all-keep.aac",
            )
            timeline = json.loads((output.parent / "timeline-map.json").read_text())
            self.assertFalse(timeline["has_deletion"])
            self.assertEqual(timeline["segments"], [{
                "source_start": 0.0,
                "source_end": 3.0,
                "timeline_start": 0.0,
                "timeline_end": 3.0,
            }])
            self.assertAlmostEqual(timeline["output_duration"], 3.0)
            self.assertEqual(rendered_hash, source_hash)

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

    def test_padding_cannot_cover_deleted_word_interval(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                _segment(
                    "keep", 0, 1, "你好", "你好", "保留", after=0.4,
                ),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment(
                    "keep", 2, 3, "世界", "世界", "保留", before=0.4,
                ),
            ],
        }
        proposal = build_cleanup_proposal(
            "你好嗯世界", WORDS, plan, media_duration=3.0,
        )
        self.assertAlmostEqual(proposal["estimated_duration"]["seconds"], 2.7)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            output = render_edit(job)
            timeline = json.loads((output.parent / "timeline-map.json").read_text())
            self.assertTrue(timeline["has_deletion"])
            self.assertAlmostEqual(timeline["output_duration"], 2.7)
            self.assertEqual(
                [(item["source_start"], item["source_end"]) for item in timeline["segments"]],
                [(0.0, 1.0), (1.3, 3.0)],
            )

    def test_formal_reported_estimate_matches_rendered_timeline_duration(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留"),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留"),
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            generate_cleanup_proposal(job, plan)
            proposal = json.loads(
                (job.job_dir / "02-speech-cleanup" / "estimated-duration.json").read_text()
            )
            approve(job, "speech_cleanup")
            output = render_edit(job)
            timeline = json.loads((output.parent / "timeline-map.json").read_text())
            self.assertAlmostEqual(proposal["seconds"], timeline["output_duration"])

    def test_formal_proposal_revises_task2_generation_and_only_marks_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            original = {
                name: (job.job_dir / "02-speech-cleanup" / name).read_bytes()
                for name in ("speech-16k.wav", "whisper.json", "report.json")
            }
            plan = {
                "version": 1,
                "segments": [
                    _segment("keep", 0, 1, "你好", "你好", "保留"),
                    _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                    _segment("keep", 2, 3, "世界", "世界", "保留"),
                ],
            }
            proposal_path = generate_cleanup_proposal(job, plan)
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(job.stages["edit_structure"]["status"], "pending")
            self.assertEqual(len(job.stages["speech_cleanup"]["artifacts"]), 7)
            self.assertEqual(proposal_path.name, "cleanup-proposal.json")
            for name, source in original.items():
                self.assertEqual((proposal_path.parent / name).read_bytes(), source)
            self.assertEqual(
                set(path.name for path in proposal_path.parent.iterdir()),
                {
                    "speech-16k.wav",
                    "whisper.json",
                    "report.json",
                    "word-transcript.json",
                    "diff-summary.json",
                    "cleanup-proposal.json",
                    "estimated-duration.json",
                },
            )

    def test_ready_proposal_can_be_revised_and_rerun_as_one_complete_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            first = {
                "version": 1,
                "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
            }
            second = {
                "version": 1,
                "segments": [
                    _segment("keep", 0, 1, "你好", "你好", "保留"),
                    _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                    _segment("keep", 2, 3, "世界", "世界", "保留"),
                ],
            }
            generate_cleanup_proposal(job, first)
            generate_cleanup_proposal(job, second)
            proposal = json.loads(
                (job.job_dir / "02-speech-cleanup" / "cleanup-proposal.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(proposal, second)
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(len(job.stages["speech_cleanup"]["artifacts"]), 7)

    def test_proposal_second_directory_publication_failure_restores_ready_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            expected_lineage = self._artifact_lineage(job, "speech_cleanup")
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            plan = {
                "version": 1,
                "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
            }
            real_replace = __import__("os").replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("sensitive /absolute/path")
                return real_replace(source, destination)

            with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=fail_second):
                with self.assertRaisesRegex(EditTimelineError, "edit timeline operation failed") as caught:
                    generate_cleanup_proposal(job, plan)
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_proposal_publish_rollback_marker_retired_crash_restores_task2_ready(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import json
import os
import sys
from pathlib import Path
from unittest import mock
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
real_replace = os.replace
calls = 0
def fail_second(source, destination):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("injected publication failure")
    return real_replace(source, destination)
with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=fail_second):
    generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            expected_lineage = self._artifact_lineage(job, "speech_cleanup")
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_retired"
            child = subprocess.run(
                [
                    "python3", "-c", child_source, str(job.job_dir),
                    json.dumps(plan, ensure_ascii=False),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91, child.stderr.decode(errors="replace"))
            crashed = load_job(job.job_dir)
            self.assertEqual(crashed.stages["speech_cleanup"], {
                "status": "needs_revision",
                "reason": edit_timeline._INTERNAL_REVISION_REASON,
                "artifacts": [],
                "ai_attempts": 0,
                "lineage": expected_lineage,
            })
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

            recovery_source = """
import sys
from pathlib import Path
from edit.hd.tools import edit_timeline
from edit.hd.tools.state import load_job
job = load_job(Path(sys.argv[1]))
edit_timeline._recover_generation(
    job,
    "02-speech-cleanup",
    "speech_cleanup",
    edit_timeline._PROPOSAL_NAMES,
    restore_ready=True,
    allowed_old_names=(edit_timeline._TASK2_NAMES, edit_timeline._PROPOSAL_NAMES),
)
"""
            recovery_environment = os.environ.copy()
            recovery_environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = (
                "workflow_restored"
            )
            second = subprocess.run(
                ["python3", "-c", recovery_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=recovery_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(second.returncode, 92, second.stderr.decode(errors="replace"))
            restored = load_job(job.job_dir)
            self.assertEqual(restored.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(len(restored.stages["speech_cleanup"]["artifacts"]), 3)
            self.assertTrue((job.job_dir / ".02-speech-cleanup.lock").is_file())

            self.assertFalse(edit_timeline._recover_generation(
                restored,
                "02-speech-cleanup",
                "speech_cleanup",
                edit_timeline._PROPOSAL_NAMES,
                restore_ready=True,
                allowed_old_names=(
                    edit_timeline._TASK2_NAMES,
                    edit_timeline._PROPOSAL_NAMES,
                ),
            ))
            self.assertEqual(restored.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(len(restored.stages["speech_cleanup"]["artifacts"]), 3)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)
            self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
            self.assertFalse(
                (job.job_dir / ".02-speech-cleanup.generation.marker").exists()
            )

            output = generate_cleanup_proposal(restored, plan)
            self.assertTrue(output.is_file())
            self.assertEqual(restored.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(len(restored.stages["speech_cleanup"]["artifacts"]), 7)

    def test_proposal_orphan_rejects_forged_marker_tombstone_before_restore(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import json
import os
import sys
from pathlib import Path
from unittest import mock
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
real_replace = os.replace
calls = 0
def fail_second(source, destination):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("injected publication failure")
    return real_replace(source, destination)
with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=fail_second):
    generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            expected_lineage = self._artifact_lineage(job, "speech_cleanup")
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_retired"
            child = subprocess.run(
                [
                    "python3", "-c", child_source, str(job.job_dir),
                    json.dumps(plan, ensure_ascii=False),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91)
            lock = job.job_dir / ".02-speech-cleanup.lock"
            payload = json.loads(lock.read_text(encoding="utf-8"))
            marker_stage = job.job_dir / payload["marker_stage"]["name"]
            owned = marker_stage.with_name(marker_stage.name + ".owned")
            marker_stage.replace(owned)
            marker_stage.write_bytes(b"")
            forged = job.job_dir / (
                "..02-speech-cleanup.generation.marker.marker.retained-"
                + "e" * 32
            )
            os.link(marker_stage, forged)

            crashed = load_job(job.job_dir)
            with self.assertRaises(EditTimelineError) as caught:
                edit_timeline._recover_generation(
                    crashed,
                    "02-speech-cleanup",
                    "speech_cleanup",
                    edit_timeline._PROPOSAL_NAMES,
                    restore_ready=True,
                    allowed_old_names=(
                        edit_timeline._TASK2_NAMES,
                        edit_timeline._PROPOSAL_NAMES,
                    ),
                )
            self.assertIsNone(caught.exception.__cause__)
            persisted = load_job(job.job_dir)
            self.assertEqual(persisted.stages["speech_cleanup"], {
                "status": "needs_revision",
                "reason": edit_timeline._INTERNAL_REVISION_REASON,
                "artifacts": [],
                "ai_attempts": 0,
                "lineage": expected_lineage,
            })
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)
            self.assertTrue(lock.is_file())
            self.assertEqual(marker_stage.read_bytes(), b"")
            self.assertEqual(forged.read_bytes(), b"")

    def test_proposal_workflow_restored_crash_preserves_external_approval(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        first_source = """
import json
import os
import sys
from pathlib import Path
from unittest import mock
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
real_replace = os.replace
calls = 0
def fail_second(source, destination):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("injected publication failure")
    return real_replace(source, destination)
with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=fail_second):
    generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        recovery_source = """
import os
import signal
import sys
from pathlib import Path
from edit.hd.tools import edit_timeline
from edit.hd.tools.state import load_job
signal.signal(signal.SIGUSR1, lambda *_args: os._exit(92))
edit_timeline._recover_generation(
    load_job(Path(sys.argv[1])),
    "02-speech-cleanup",
    "speech_cleanup",
    edit_timeline._PROPOSAL_NAMES,
    restore_ready=True,
    allowed_old_names=(edit_timeline._TASK2_NAMES, edit_timeline._PROPOSAL_NAMES),
)
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            first_environment = os.environ.copy()
            first_environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_retired"
            first = subprocess.run(
                [
                    "python3", "-c", first_source, str(job.job_dir),
                    json.dumps(plan, ensure_ascii=False),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=first_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(first.returncode, 91)
            ready = root / "workflow-restored.ready"
            release = root / "workflow-restored.release"
            recovery_environment = os.environ.copy()
            recovery_environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "workflow_restored",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
            })
            second = subprocess.Popen(
                ["python3", "-c", recovery_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=recovery_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                external = load_job(job.job_dir)
                approve(external, "speech_cleanup")
                second.send_signal(signal.SIGUSR1)
                second.communicate(timeout=10)
                self.assertEqual(second.returncode, 92)

                restored = load_job(job.job_dir)
                self.assertEqual(restored.stages["speech_cleanup"]["status"], "approved")
                self.assertFalse(edit_timeline._recover_generation(
                    restored,
                    "02-speech-cleanup",
                    "speech_cleanup",
                    edit_timeline._PROPOSAL_NAMES,
                    restore_ready=True,
                    allowed_old_names=(
                        edit_timeline._TASK2_NAMES,
                        edit_timeline._PROPOSAL_NAMES,
                    ),
                ))
                self.assertEqual(restored.stages["speech_cleanup"]["status"], "approved")
                self.assertEqual(len(restored.stages["speech_cleanup"]["artifacts"]), 3)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()}, before,
                )
                self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
                load_job(job.job_dir)
            finally:
                if second.poll() is None:
                    second.send_signal(signal.SIGUSR1)
                    second.communicate(timeout=10)

    def test_marker_present_workflow_restoration_is_idempotent(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        first_source = """
import json
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        recovery_source = """
import sys
from pathlib import Path
from edit.hd.tools import edit_timeline
from edit.hd.tools.state import load_job
edit_timeline._recover_generation(
    load_job(Path(sys.argv[1])), "02-speech-cleanup", "speech_cleanup",
    edit_timeline._PROPOSAL_NAMES, restore_ready=True,
    allowed_old_names=(edit_timeline._TASK2_NAMES, edit_timeline._PROPOSAL_NAMES),
)
"""
        for approve_restored in (False, True):
            with self.subTest(approved=approve_restored), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_with_transcript_ready(root)
                target = job.job_dir / "02-speech-cleanup"
                before = {path.name: path.read_bytes() for path in target.iterdir()}
                first_environment = os.environ.copy()
                first_environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = (
                    "new_generation_moved"
                )
                first = subprocess.run(
                    [
                        "python3", "-c", first_source, str(job.job_dir),
                        json.dumps(plan, ensure_ascii=False),
                    ],
                    cwd=Path(__file__).resolve().parents[3],
                    env=first_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(first.returncode, 91)
                second_environment = os.environ.copy()
                second_environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = (
                    "workflow_restored_marker_present"
                )
                second = subprocess.run(
                    ["python3", "-c", recovery_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    env=second_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(second.returncode, 93, second.stderr.decode(errors="replace"))
                restored = load_job(job.job_dir)
                self.assertEqual(restored.stages["speech_cleanup"]["status"], "ready_for_review")
                if approve_restored:
                    approve(restored, "speech_cleanup")
                for _attempt in range(25):
                    self.assertFalse(edit_timeline._recover_generation(
                        restored,
                        "02-speech-cleanup",
                        "speech_cleanup",
                        edit_timeline._PROPOSAL_NAMES,
                        restore_ready=True,
                        allowed_old_names=(
                            edit_timeline._TASK2_NAMES,
                            edit_timeline._PROPOSAL_NAMES,
                        ),
                    ))
                self.assertEqual(
                    restored.stages["speech_cleanup"]["status"],
                    "approved" if approve_restored else "ready_for_review",
                )
                self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)
                self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".02-speech-cleanup.generation.marker").exists()
                )
                load_job(job.job_dir)
                if not approve_restored:
                    self.assertTrue(generate_cleanup_proposal(restored, plan).is_file())

    def test_real_deletion_renders_normalized_cfr_aac_generation_and_stops_ready(self) -> None:
        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留"),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留"),
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            output = render_edit(job)
            self.assertEqual(output.name, "edited-aroll.mp4")
            self.assertEqual(job.stages["edit_structure"]["status"], "ready_for_review")
            self.assertEqual(job.stages["visual_direction"]["status"], "pending")
            self.assertEqual(
                set(path.name for path in output.parent.iterdir()),
                {"edit-plan.json", "edited-aroll.mp4", "timeline-map.json"},
            )
            assert_complete_decode(output)
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_streams", "-show_format",
                    "-of", "json", str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=True,
            )
            metadata = json.loads(probe.stdout)
            video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
            audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
            self.assertEqual((video["width"], video["height"], video["r_frame_rate"]), (1080, 1920, "24/1"))
            self.assertEqual((audio["codec_name"], audio["sample_rate"], audio["channels"]), ("aac", "48000", 2))
            self.assertLess(float(metadata["format"]["duration"]), 2.8)
            timeline = json.loads(
                (output.parent / "timeline-map.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                timeline["render_adapter"], "local-ffmpeg-trim-concat"
            )

    def test_no_deletion_preserves_aac_elementary_bitstream(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            source_hash = self._audio_elementary_hash(root / "video.mp4", root / "source.aac")
            output = render_edit(job)
            output_hash = self._audio_elementary_hash(output, root / "output.aac")
            self.assertEqual(output_hash, source_hash)
            timeline = json.loads(
                (output.parent / "timeline-map.json").read_text(encoding="utf-8")
            )
            self.assertEqual(timeline["render_adapter"], "local-ffmpeg-no-cut")

    def test_ffmpeg_failure_keeps_previous_three_file_generation(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "调整剪辑")
            with mock.patch("edit.hd.tools.edit_timeline._run_ffmpeg", side_effect=OSError("secret /tmp/path")):
                with self.assertRaises(EditTimelineError) as caught:
                    render_edit(job)
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_second_directory_publication_failure_keeps_previous_three_file_generation(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "调整剪辑")
            real_replace = os.replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("secret /tmp/path")
                return real_replace(source, destination)

            with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=fail_second):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_completed_first_rename_then_error_still_restores_previous_generation(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "调整剪辑")
            real_replace = os.replace
            calls = 0

            def complete_then_fail(source, destination):
                nonlocal calls
                calls += 1
                result = real_replace(source, destination)
                if calls == 1:
                    raise OSError("rename completion was uncertain")
                return result

            with mock.patch(
                "edit.hd.tools.edit_timeline._replace", side_effect=complete_then_fail
            ):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_render_rejects_source_inode_replacement_after_fixed_fd_render(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            real_run = subprocess.run

            def replace_after_run(command, **kwargs):
                result = real_run(command, **kwargs)
                replacement = root / "replacement.mp4"
                shutil.copyfile(self.fixture, replacement)
                os.replace(replacement, root / "video.mp4")
                return result

            with mock.patch("edit.hd.tools.edit_timeline._run_ffmpeg", side_effect=replace_after_run):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            self.assertFalse((job.job_dir / "03-edit-structure").exists())

    def test_render_rejects_same_inode_source_modification_after_fixed_fd_render(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            source = root / "video.mp4"
            inode = os.lstat(source).st_ino
            real_run = subprocess.run

            def modify_after_run(command, **kwargs):
                result = real_run(command, **kwargs)
                with source.open("r+b") as handle:
                    handle.seek(128)
                    original = handle.read(1)
                    handle.seek(128)
                    handle.write(bytes([original[0] ^ 1]))
                    handle.flush()
                    os.fsync(handle.fileno())
                return result

            with mock.patch("edit.hd.tools.edit_timeline._run_ffmpeg", side_effect=modify_after_run):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            self.assertEqual(os.lstat(source).st_ino, inode)
            self.assertFalse((job.job_dir / "03-edit-structure").exists())

    def test_existing_transaction_lock_fails_closed_without_deleting_unknown_file(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            lock = job.job_dir / ".03-edit-structure.lock"
            lock.write_bytes(b"foreign-lock")
            with self.assertRaises(EditTimelineError):
                render_edit(job)
            self.assertEqual(lock.read_bytes(), b"foreign-lock")
            self.assertFalse((job.job_dir / "03-edit-structure").exists())

    def test_hard_crash_checkpoints_recover_and_rerun_idempotently(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        for checkpoint in (
            "lock_stage_partial_write",
            "lock_stage_fsync",
            "lock_canonical_installed",
            "lock_canonical_dirsync",
            "lock_durable",
            "marker_stage_partial_write",
            "marker_stage_fsync",
            "marker_canonical_installed",
            "marker_canonical_dirsync",
            "marker_durable",
            "old_generation_moved",
            "new_generation_moved",
            "workflow_ready",
            "marker_retired",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_ready_for_render(root, plan)
                render_edit(job)
                revise(job, "edit_structure", "硬崩溃恢复测试")
                environment = os.environ.copy()
                environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = checkpoint
                child = subprocess.run(
                    ["python3", "-c", child_source, str(job.job_dir)],
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
                output = render_edit(recovered)
                self.assertEqual(recovered.stages["edit_structure"]["status"], "ready_for_review")
                self.assertEqual(
                    set(path.name for path in output.parent.iterdir()),
                    _EDIT_OUTPUT_NAMES,
                )
                assert_complete_decode(output)
                self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
                self.assertFalse((job.job_dir / ".03-edit-structure.generation.marker").exists())
                load_job(job.job_dir)

    def test_marker_staging_crash_windows_preserve_old_generation_and_rerun(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        for checkpoint in (
            "marker_stage_partial_write",
            "marker_stage_fsync",
            "marker_canonical_installed",
            "marker_canonical_dirsync",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_ready_for_render(root, plan)
                render_edit(job)
                target = job.job_dir / "03-edit-structure"
                before = {path.name: path.read_bytes() for path in target.iterdir()}
                revise(job, "edit_structure", "marker staging crash")
                environment = os.environ.copy()
                environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = checkpoint
                child = subprocess.run(
                    ["python3", "-c", child_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(child.returncode, 91, child.stderr.decode(errors="replace"))
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()},
                    before,
                )
                recovered = load_job(job.job_dir)
                output = render_edit(recovered)
                self.assertTrue(output.is_file())
                self.assertEqual(recovered.stages["edit_structure"]["status"], "ready_for_review")
                self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".03-edit-structure.generation.marker").exists()
                )

    def test_foreign_replacement_of_partial_marker_stage_fails_closed(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "marker stage foreign replacement")
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = (
                "marker_stage_partial_write"
            )
            child = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91)
            stages = list(job.job_dir.glob(".03-edit-structure.marker-stage-*"))
            self.assertEqual(len(stages), 2)
            partial = next(path for path in stages if path.stat().st_size > 0)
            owned = partial.with_name(partial.name + ".owned")
            partial.replace(owned)
            foreign = b"foreign-marker-stage"
            partial.write_bytes(foreign)

            lock = job.job_dir / ".03-edit-structure.lock"
            lock_inode = os.lstat(lock).st_ino
            before_recovery = {
                path.relative_to(job.job_dir).as_posix(): path.read_bytes()
                for path in job.job_dir.rglob("*") if path.is_file()
            }
            recovered = load_job(job.job_dir)
            with self.assertRaises(EditTimelineError) as caught:
                render_edit(recovered)
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(partial.read_bytes(), foreign)
            self.assertEqual(os.lstat(lock).st_ino, lock_inode)
            self.assertEqual(
                {
                    path.relative_to(job.job_dir).as_posix(): path.read_bytes()
                    for path in job.job_dir.rglob("*") if path.is_file()
                },
                before_recovery,
            )

    def test_foreign_replacement_of_partial_lock_stage_is_preserved_and_rerunnable(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "lock stage foreign replacement")
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = (
                "lock_stage_partial_write"
            )
            child = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91)
            stages = list(job.job_dir.glob(".03-edit-structure.lock-stage-*"))
            partial = next(path for path in stages if path.stat().st_size > 0)
            owned = partial.with_name(partial.name + ".owned")
            partial.replace(owned)
            foreign = b"foreign-lock-stage"
            partial.write_bytes(foreign)

            recovered = load_job(job.job_dir)
            self.assertTrue(render_edit(recovered).is_file())
            self.assertEqual(partial.read_bytes(), foreign)
            self.assertEqual(recovered.stages["edit_structure"]["status"], "ready_for_review")
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())

    def test_marker_retired_recovery_rejects_forged_tombstone_identity(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "marker tombstone identity")
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_retired"
            child = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91)
            lock = job.job_dir / ".03-edit-structure.lock"
            lock_payload = json.loads(lock.read_text(encoding="utf-8"))
            marker_stage = job.job_dir / lock_payload["marker_stage"]["name"]
            owned = marker_stage.with_name(marker_stage.name + ".owned")
            marker_stage.replace(owned)
            marker_stage.write_bytes(b"")
            forged_retained = job.job_dir / (
                "..03-edit-structure.generation.marker.marker.retained-"
                + "f" * 32
            )
            os.link(marker_stage, forged_retained)

            with self.assertRaises(EditTimelineError):
                render_edit(load_job(job.job_dir))
            self.assertEqual(marker_stage.read_bytes(), b"")
            self.assertEqual(forged_retained.read_bytes(), b"")
            self.assertTrue((job.job_dir / "03-edit-structure").is_dir())

    def test_recovery_rolls_back_media_without_overwriting_concurrent_workflow_revision(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "事务自己的返修")
            ready = root / "checkpoint.ready"
            release = root / "checkpoint.release"
            environment = os.environ.copy()
            environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "new_generation_moved",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
            })
            child = subprocess.Popen(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                external = load_job(job.job_dir)
                revise(external, "edit_structure", "外部并发返修")
                child.kill()
                child.communicate(timeout=10)

                recovered = load_job(job.job_dir)
                self.assertFalse(edit_timeline._recover_generation(
                    recovered,
                    "03-edit-structure",
                    "edit_structure",
                    edit_timeline._EDIT_NAMES,
                    restore_ready=False,
                    allowed_old_names=(edit_timeline._EDIT_NAMES,),
                ))
                persisted = load_job(job.job_dir)
                self.assertEqual(
                    persisted.stages["edit_structure"],
                    external.stages["edit_structure"],
                )
                self.assertEqual(recovered.stages["edit_structure"], persisted.stages["edit_structure"])
                self.assertEqual(recovered.revision, persisted.revision)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()}, before,
                )
                self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".03-edit-structure.generation.marker").exists()
                )
                self.assertTrue(render_edit(recovered).is_file())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)

    def test_approved_render_generation_is_committed_across_workflow_ready_crash(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import os
import signal
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
signal.signal(signal.SIGUSR1, lambda *_args: os._exit(91))
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "测试批准后的崩溃恢复")
            target = job.job_dir / "03-edit-structure"
            with (target / "timeline-map.json").open("ab") as handle:
                handle.write(b" ")
                handle.flush()
                os.fsync(handle.fileno())
            old_generation = {
                path.name: path.read_bytes() for path in target.iterdir()
            }
            ready = root / "approved-render.ready"
            release = root / "approved-render.release"
            environment = os.environ.copy()
            environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "workflow_ready",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
            })
            child = subprocess.Popen(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                new_generation = {
                    path.name: path.read_bytes() for path in target.iterdir()
                }
                self.assertNotEqual(new_generation, old_generation)
                external = load_job(job.job_dir)
                approve(external, "edit_structure")
                child.send_signal(signal.SIGUSR1)
                child.communicate(timeout=10)
                self.assertEqual(child.returncode, 91)

                recovered = load_job(job.job_dir)
                output = render_edit(recovered)
                self.assertEqual(recovered.stages["edit_structure"]["status"], "approved")
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()},
                    new_generation,
                )
                self.assertTrue(output.is_file())
                self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".03-edit-structure.generation.marker").exists()
                )
                load_job(job.job_dir)
            finally:
                if child.poll() is None:
                    child.send_signal(signal.SIGUSR1)
                    child.communicate(timeout=10)

    def test_upstream_revision_keeps_lineage_bound_render_after_workflow_ready_crash(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            approve(job, "edit_structure")
            revise(job, "edit_structure", "publish generation B")
            target = job.job_dir / "03-edit-structure"
            old_inode = target.stat().st_ino
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "workflow_ready"
            crashed = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(crashed.returncode, 91, crashed.stderr.decode(errors="replace"))
            generation_b = (
                target.stat().st_ino,
                {path.name: (path.stat().st_ino, path.read_bytes()) for path in target.iterdir()},
            )
            self.assertNotEqual(generation_b[0], old_inode)

            external = load_job(job.job_dir)
            revise(external, "speech_cleanup", "upstream changed after B committed")
            self.assertEqual(external.stages["edit_structure"]["status"], "pending")
            self.assertEqual(
                external.stages["edit_structure"]["lineage"],
                edit_timeline._tree_lineage_payload(
                    target.name,
                    edit_timeline._snapshot_tree(target, edit_timeline._EDIT_NAMES),
                ),
            )

            recovered = load_job(job.job_dir)
            self.assertFalse(edit_timeline._recover_generation(
                recovered,
                "03-edit-structure",
                "edit_structure",
                edit_timeline._EDIT_NAMES,
                restore_ready=False,
                allowed_old_names=(edit_timeline._EDIT_NAMES,),
            ))
            self.assertEqual(
                (
                    target.stat().st_ino,
                    {
                        path.name: (path.stat().st_ino, path.read_bytes())
                        for path in target.iterdir()
                    },
                ),
                generation_b,
            )
            self.assertTrue(edit_timeline._lineage_binds_tree(
                recovered.stages["edit_structure"]["lineage"],
                target.name,
                edit_timeline._snapshot_tree(target, edit_timeline._EDIT_NAMES),
            ))
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
            self.assertFalse(
                (job.job_dir / ".03-edit-structure.generation.marker").exists()
            )

    def test_first_generation_external_revision_rolls_back_empty_lineage(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        for revised_stage, expected_status in (
            ("speech_cleanup", "pending"),
            ("edit_structure", "needs_revision"),
        ):
            with self.subTest(status=expected_status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_ready_for_render(root, plan)
                environment = os.environ.copy()
                environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "new_generation_moved"
                crashed = subprocess.run(
                    ["python3", "-c", child_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(
                    crashed.returncode, 91, crashed.stderr.decode(errors="replace"),
                )
                target = job.job_dir / "03-edit-structure"
                self.assertTrue(target.is_dir())

                external = load_job(job.job_dir)
                revise(external, revised_stage, "external revision before first commit")
                expected_stage = copy.deepcopy(external.stages["edit_structure"])
                expected_revision = external.revision
                self.assertEqual(expected_stage["status"], expected_status)
                self.assertEqual(expected_stage["artifacts"], [])
                self.assertEqual(expected_stage["lineage"], [])

                recovered = load_job(job.job_dir)
                self.assertFalse(edit_timeline._recover_generation(
                    recovered,
                    "03-edit-structure",
                    "edit_structure",
                    edit_timeline._EDIT_NAMES,
                    restore_ready=False,
                    allowed_old_names=(edit_timeline._EDIT_NAMES,),
                ))
                self.assertFalse(target.exists())
                self.assertEqual(recovered.revision, expected_revision)
                self.assertEqual(recovered.stages["edit_structure"], expected_stage)
                self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".03-edit-structure.generation.marker").exists()
                )

    def test_legacy_four_key_workflow_before_recovers_durable_marker(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "marker_canonical_dirsync"
            crashed = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(crashed.returncode, 91, crashed.stderr.decode(errors="replace"))

            for path in (
                job.job_dir / ".03-edit-structure.generation.marker",
                job.job_dir / ".03-edit-structure.lock",
            ):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    set(payload["workflow_before"]["stage"]),
                    {"status", "reason", "artifacts", "ai_attempts", "lineage"},
                )
                del payload["workflow_before"]["stage"]["lineage"]
                with path.open("r+b") as handle:
                    handle.seek(0)
                    handle.write(edit_timeline._json_bytes(payload))
                    handle.truncate()
                    handle.flush()
                    os.fsync(handle.fileno())

            recovered = load_job(job.job_dir)
            output = render_edit(recovered)
            self.assertTrue(output.is_file())
            self.assertEqual(
                recovered.stages["edit_structure"]["status"], "ready_for_review",
            )
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
            self.assertFalse(
                (job.job_dir / ".03-edit-structure.generation.marker").exists()
            )

    def test_approved_proposal_generation_is_committed_across_workflow_ready_crash(self) -> None:
        first_plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        second_plan = first_plan
        child_source = """
import json
import os
import signal
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
signal.signal(signal.SIGUSR1, lambda *_args: os._exit(91))
generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            generate_cleanup_proposal(job, first_plan)
            target = job.job_dir / "02-speech-cleanup"
            old_generation = {
                path.name: path.read_bytes() for path in target.iterdir()
            }
            old_inodes = {path.name: os.lstat(path).st_ino for path in target.iterdir()}
            ready = root / "approved-proposal.ready"
            release = root / "approved-proposal.release"
            environment = os.environ.copy()
            environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "workflow_ready",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
            })
            child = subprocess.Popen(
                [
                    "python3", "-c", child_source, str(job.job_dir),
                    json.dumps(second_plan, ensure_ascii=False),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                new_generation = {
                    path.name: path.read_bytes() for path in target.iterdir()
                }
                new_inodes = {
                    path.name: os.lstat(path).st_ino for path in target.iterdir()
                }
                self.assertEqual(new_generation, old_generation)
                self.assertNotEqual(new_inodes, old_inodes)
                external = load_job(job.job_dir)
                approve(external, "speech_cleanup")
                child.send_signal(signal.SIGUSR1)
                child.communicate(timeout=10)
                self.assertEqual(child.returncode, 91)

                recovered = load_job(job.job_dir)
                proposal = generate_cleanup_proposal(recovered, second_plan)
                self.assertEqual(recovered.stages["speech_cleanup"]["status"], "approved")
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()},
                    new_generation,
                )
                self.assertTrue(proposal.is_file())
                self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
                self.assertFalse(
                    (job.job_dir / ".02-speech-cleanup.generation.marker").exists()
                )
                load_job(job.job_dir)
            finally:
                if child.poll() is None:
                    child.send_signal(signal.SIGUSR1)
                    child.communicate(timeout=10)

    def test_same_proposal_ready_generation_uses_new_tree_identity_on_recovery(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import json
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            generate_cleanup_proposal(job, plan)
            target = job.job_dir / "02-speech-cleanup"
            old_bytes = {path.name: path.read_bytes() for path in target.iterdir()}
            old_inodes = {path.name: os.lstat(path).st_ino for path in target.iterdir()}
            environment = os.environ.copy()
            environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = "workflow_ready"
            child = subprocess.run(
                [
                    "python3", "-c", child_source, str(job.job_dir),
                    json.dumps(plan, ensure_ascii=False),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(child.returncode, 91)
            self.assertEqual(
                {path.name: path.read_bytes() for path in target.iterdir()}, old_bytes,
            )
            self.assertNotEqual(
                {path.name: os.lstat(path).st_ino for path in target.iterdir()}, old_inodes,
            )
            recovered = load_job(job.job_dir)
            self.assertTrue(generate_cleanup_proposal(recovered, plan).is_file())
            for _attempt in range(25):
                self.assertFalse(edit_timeline._recover_generation(
                    recovered,
                    "02-speech-cleanup",
                    "speech_cleanup",
                    edit_timeline._PROPOSAL_NAMES,
                    restore_ready=True,
                    allowed_old_names=(
                        edit_timeline._TASK2_NAMES,
                        edit_timeline._PROPOSAL_NAMES,
                    ),
                ))
            self.assertEqual(recovered.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
            load_job(job.job_dir)

    def test_catchable_mark_ready_cas_drift_restores_media_and_reloads_workflow(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "事务自己的返修")
            real_mark_ready = edit_timeline.mark_ready
            external_stage = None

            def concurrent_ready(candidate, stage_id, artifacts):
                nonlocal external_stage
                external = load_job(job.job_dir)
                revise(external, "edit_structure", "外部CAS返修")
                external_stage = external.stages["edit_structure"]
                return real_mark_ready(candidate, stage_id, artifacts)

            with mock.patch.object(
                edit_timeline, "mark_ready", side_effect=concurrent_ready,
            ):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            persisted = load_job(job.job_dir)
            self.assertIsNotNone(external_stage)
            self.assertEqual(persisted.stages["edit_structure"], external_stage)
            self.assertEqual(job.stages["edit_structure"], persisted.stages["edit_structure"])
            self.assertEqual(job.revision, persisted.revision)
            self.assertEqual(
                {path.name: path.read_bytes() for path in target.iterdir()}, before,
            )
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
            self.assertFalse(
                (job.job_dir / ".03-edit-structure.generation.marker").exists()
            )

    def test_catchable_proposal_revise_cas_drift_preserves_task2_and_external_state(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            real_revise = edit_timeline.revise
            external_stage = None

            def concurrent_revise(candidate, stage_id, reason):
                nonlocal external_stage
                external = load_job(job.job_dir)
                real_revise(external, "speech_cleanup", "外部proposal CAS返修")
                external_stage = external.stages["speech_cleanup"]
                return real_revise(candidate, stage_id, reason)

            with mock.patch.object(
                edit_timeline, "revise", side_effect=concurrent_revise,
            ):
                with self.assertRaises(EditTimelineError):
                    generate_cleanup_proposal(job, plan)
            persisted = load_job(job.job_dir)
            self.assertIsNotNone(external_stage)
            self.assertEqual(persisted.stages["speech_cleanup"], external_stage)
            self.assertEqual(job.stages["speech_cleanup"], persisted.stages["speech_cleanup"])
            self.assertEqual(job.revision, persisted.revision)
            self.assertEqual(
                {path.name: path.read_bytes() for path in target.iterdir()}, before,
            )
            self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
            self.assertFalse(
                (job.job_dir / ".02-speech-cleanup.generation.marker").exists()
            )

    def test_catchable_proposal_mark_ready_cas_drift_does_not_restore_over_external_state(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_with_transcript_ready(root)
            target = job.job_dir / "02-speech-cleanup"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            real_mark_ready = edit_timeline.mark_ready
            external_stage = None

            def concurrent_ready(candidate, stage_id, artifacts):
                nonlocal external_stage
                external = load_job(job.job_dir)
                revise(external, "speech_cleanup", "外部proposal ready CAS返修")
                external_stage = external.stages["speech_cleanup"]
                return real_mark_ready(candidate, stage_id, artifacts)

            with mock.patch.object(
                edit_timeline, "mark_ready", side_effect=concurrent_ready,
            ):
                with self.assertRaises(EditTimelineError):
                    generate_cleanup_proposal(job, plan)
            persisted = load_job(job.job_dir)
            self.assertIsNotNone(external_stage)
            self.assertEqual(persisted.stages["speech_cleanup"], external_stage)
            self.assertEqual(job.stages["speech_cleanup"], persisted.stages["speech_cleanup"])
            self.assertEqual(job.revision, persisted.revision)
            self.assertEqual(
                {path.name: path.read_bytes() for path in target.iterdir()}, before,
            )
            self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())
            self.assertFalse(
                (job.job_dir / ".02-speech-cleanup.generation.marker").exists()
            )

    def test_proposal_hard_crash_recovers_original_ready_state_and_reruns(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import json
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import generate_cleanup_proposal
from edit.hd.tools.state import load_job
generate_cleanup_proposal(load_job(Path(sys.argv[1])), json.loads(sys.argv[2]))
"""
        for checkpoint in (
            "lock_stage_partial_write",
            "lock_stage_fsync",
            "lock_canonical_installed",
            "lock_canonical_dirsync",
            "lock_durable",
            "marker_stage_partial_write",
            "marker_stage_fsync",
            "marker_canonical_installed",
            "marker_canonical_dirsync",
            "marker_durable",
            "old_generation_moved",
            "new_generation_moved",
            "workflow_ready",
            "marker_retired",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_with_transcript_ready(root)
                environment = os.environ.copy()
                environment["HD_EDIT_TIMELINE_CRASH_CHECKPOINT"] = checkpoint
                child = subprocess.run(
                    [
                        "python3", "-c", child_source, str(job.job_dir),
                        json.dumps(plan, ensure_ascii=False),
                    ],
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
                if checkpoint in {
                    "lock_stage_partial_write",
                    "lock_stage_fsync",
                    "lock_canonical_installed",
                    "lock_canonical_dirsync",
                    "lock_durable",
                    "marker_stage_partial_write",
                    "marker_stage_fsync",
                    "marker_canonical_installed",
                    "marker_canonical_dirsync",
                    "marker_durable",
                }:
                    self.assertEqual(
                        recovered.stages["speech_cleanup"]["status"],
                        "ready_for_review",
                    )
                    self.assertEqual(
                        len(recovered.stages["speech_cleanup"]["artifacts"]), 3,
                    )
                output = generate_cleanup_proposal(recovered, plan)
                self.assertEqual(
                    recovered.stages["speech_cleanup"]["status"],
                    "ready_for_review",
                )
                self.assertEqual(len(recovered.stages["speech_cleanup"]["artifacts"]), 7)
                self.assertTrue(output.is_file())

    def test_active_transaction_blocks_second_process_without_any_recovery_mutation(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
try:
    render_edit(load_job(Path(sys.argv[1])))
except BaseException:
    raise SystemExit(7)
"""
        for checkpoint in (
            "lock_durable",
            "marker_durable",
            "old_generation_moved",
            "new_generation_moved",
            "workflow_ready",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job = self._job_ready_for_render(root, plan)
                render_edit(job)
                revise(job, "edit_structure", "并发活跃事务")
                ready = root / "checkpoint.ready"
                release = root / "checkpoint.release"
                environment = os.environ.copy()
                environment.update({
                    "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": checkpoint,
                    "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                    "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
                })
                first = subprocess.Popen(
                    ["python3", "-c", child_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), f"checkpoint not reached: {checkpoint}")
                before = {
                    path.relative_to(job.job_dir).as_posix(): path.read_bytes()
                    for path in job.job_dir.rglob("*")
                    if path.is_file()
                }
                started = time.monotonic()
                second = subprocess.run(
                    ["python3", "-c", child_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(second.returncode, 7)
                self.assertLess(time.monotonic() - started, 5)
                after = {
                    path.relative_to(job.job_dir).as_posix(): path.read_bytes()
                    for path in job.job_dir.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
                release.write_bytes(b"release")
                stdout, stderr = first.communicate(timeout=90)
                self.assertEqual(first.returncode, 0, (stdout + stderr).decode(errors="replace"))

    def test_crashed_lock_holder_releases_os_lock_for_recovery_process(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
render_edit(load_job(Path(sys.argv[1])))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "锁持有者崩溃")
            ready = root / "checkpoint.ready"
            environment = os.environ.copy()
            environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "marker_durable",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_EXIT": "1",
            })
            first = subprocess.run(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            self.assertEqual(first.returncode, 91)
            self.assertTrue(ready.exists())
            recovered = load_job(job.job_dir)
            output = render_edit(recovered)
            self.assertTrue(output.is_file())
            self.assertEqual(recovered.stages["edit_structure"]["status"], "ready_for_review")

    def test_replaced_lock_leaf_cannot_create_split_brain_or_delete_foreign_lock(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        child_source = """
import sys
from pathlib import Path
from edit.hd.tools.edit_timeline import render_edit
from edit.hd.tools.state import load_job
try:
    render_edit(load_job(Path(sys.argv[1])))
except BaseException:
    raise SystemExit(7)
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "锁叶身份替换")
            ready = root / "checkpoint.ready"
            release = root / "checkpoint.release"
            environment = os.environ.copy()
            environment.update({
                "HD_EDIT_TIMELINE_HOLD_CHECKPOINT": "marker_durable",
                "HD_EDIT_TIMELINE_HOLD_READY_FILE": str(ready),
                "HD_EDIT_TIMELINE_HOLD_RELEASE_FILE": str(release),
            })
            first = subprocess.Popen(
                ["python3", "-c", child_source, str(job.job_dir)],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                lock = job.job_dir / ".03-edit-structure.lock"
                owned = job.job_dir / ".03-edit-structure.lock.original"
                lock.replace(owned)
                lock.write_bytes(b"foreign-lock")
                second = subprocess.run(
                    ["python3", "-c", child_source, str(job.job_dir)],
                    cwd=Path(__file__).resolve().parents[3],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(second.returncode, 7)
                self.assertEqual(lock.read_bytes(), b"foreign-lock")
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()},
                    before,
                )
                release.write_bytes(b"release")
                stdout, stderr = first.communicate(timeout=90)
                self.assertEqual(first.returncode, 7, (stdout + stderr).decode(errors="replace"))
                self.assertEqual(lock.read_bytes(), b"foreign-lock")
                self.assertEqual(
                    {path.name: path.read_bytes() for path in target.iterdir()},
                    before,
                )
            finally:
                if first.poll() is None:
                    release.write_bytes(b"release")
                    first.kill()
                    first.communicate(timeout=10)

    def test_successful_revisions_leave_no_unbounded_transaction_media(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            descriptors_before = len(os.listdir("/dev/fd"))
            for generation in range(6):
                if generation:
                    revise(job, "edit_structure", f"连续返修 {generation}")
                render_edit(job)
            retained = [
                path for path in job.job_dir.iterdir() if ".retained-" in path.name
            ]
            self.assertGreater(len(retained), 0)
            for path in retained:
                prefix, token = path.name.rsplit(".retained-", 1)
                self.assertTrue(prefix.startswith("."))
                self.assertEqual(len(token), 32)
                self.assertTrue(all(character in "0123456789abcdef" for character in token))
            retained_files = [
                candidate
                for path in retained
                for candidate in ([path] if path.is_file() else path.rglob("*"))
                if candidate.is_file()
            ]
            self.assertGreater(len(retained_files), 0)
            self.assertEqual(sum(path.stat().st_size for path in retained_files), 0)
            self.assertEqual(sum(path.stat().st_blocks for path in retained_files), 0)
            output = job.job_dir / "03-edit-structure" / "edited-aroll.mp4"
            self.assertGreater(output.stat().st_size, 0)
            assert_complete_decode(output)
            self.assertFalse(any(".quarantine-" in path.name for path in job.job_dir.iterdir()))
            load_job(job.job_dir)
            self.assertLessEqual(len(os.listdir("/dev/fd")), descriptors_before)

    def test_unknown_stage_swap_is_preserved_while_old_generation_is_restored(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            target = job.job_dir / "03-edit-structure"
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            revise(job, "edit_structure", "注入未知替换")
            real_replace = os.replace
            calls = 0

            def swap_stage(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    source_path = Path(source)
                    owned = source_path.with_name(source_path.name + ".owned")
                    real_replace(source_path, owned)
                    source_path.mkdir()
                    (source_path / "foreign.bin").write_bytes(b"foreign")
                return real_replace(source, destination)

            with mock.patch("edit.hd.tools.edit_timeline._replace", side_effect=swap_stage):
                with self.assertRaises(EditTimelineError):
                    render_edit(job)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)
            foreign = [path for path in job.job_dir.rglob("foreign.bin")]
            self.assertEqual(len(foreign), 1)
            self.assertEqual(foreign[0].read_bytes(), b"foreign")

    def test_post_commit_backup_cleanup_failure_keeps_new_ready_generation_unambiguous(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "清理失败测试")
            with mock.patch(
                "edit.hd.tools.edit_timeline._discard_directory",
                side_effect=EditTimelineError("injected cleanup failure"),
            ):
                output = render_edit(job)
            self.assertTrue(output.is_file())
            self.assertEqual(job.stages["edit_structure"]["status"], "ready_for_review")
            self.assertEqual(set(path.name for path in output.parent.iterdir()), _EDIT_OUTPUT_NAMES)
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
            load_job(job.job_dir)

    def test_post_commit_internal_cleanup_failure_retains_only_pinned_old_generation(self) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", "内部清理失败测试")
            with mock.patch(
                "edit.hd.tools.edit_timeline._truncate_snapshot",
                side_effect=EditTimelineError("injected cleanup failure"),
            ):
                output = render_edit(job)
            retained = [
                path
                for path in job.job_dir.iterdir()
                if ".retained-" in path.name and path.is_dir()
            ]
            self.assertEqual(len(retained), 1)
            self.assertEqual(set(path.name for path in retained[0].iterdir()), _EDIT_OUTPUT_NAMES)
            self.assertGreater(
                sum(path.stat().st_size for path in retained[0].iterdir()),
                0,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(job.stages["edit_structure"]["status"], "ready_for_review")
            self.assertFalse((job.job_dir / ".03-edit-structure.lock").exists())
            self.assertFalse(
                (job.job_dir / ".03-edit-structure.generation.marker").exists()
            )
            load_job(job.job_dir)

    def _assert_final_leaf_swap_is_preserved(self, label: str) -> None:
        plan = {
            "version": 1,
            "segments": [_segment("keep", 0, 3, "你好嗯世界", "你好嗯世界", "保留")],
        }
        unknown = f"unknown-{label}".encode("ascii")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job_ready_for_render(root, plan)
            render_edit(job)
            revise(job, "edit_structure", f"{label} leaf race")
            real_ftruncate = os.ftruncate
            real_truncate_snapshot = edit_timeline._truncate_snapshot
            real_retire_pin = edit_timeline._retire_pin
            raced = False

            def truncate_after_swap(descriptor, length):
                nonlocal raced
                if not raced:
                    raced = True
                    opened = os.fstat(descriptor)
                    leaves = [
                        path
                        for path in job.job_dir.rglob("*")
                        if path.is_file()
                        and os.path.samestat(opened, os.lstat(path))
                    ]
                    if label == "marker":
                        leaves = [
                            path for path in leaves
                            if ".marker.retained-" in path.name
                        ]
                    elif label == "lock":
                        leaves = [
                            path for path in leaves
                            if ".lock.retained-" in path.name
                        ]
                    self.assertEqual(len(leaves), 1)
                    leaf = leaves[0]
                    owned = leaf.with_name(leaf.name + ".owned-before-truncate")
                    leaf.replace(owned)
                    leaf.write_bytes(unknown)
                return real_ftruncate(descriptor, length)

            def race_generation(directory, snapshot):
                with mock.patch.object(os, "ftruncate", side_effect=truncate_after_swap):
                    return real_truncate_snapshot(directory, snapshot)

            def race_pin(pin, pin_label):
                if pin_label != label:
                    return real_retire_pin(pin, pin_label)
                with mock.patch.object(os, "ftruncate", side_effect=truncate_after_swap):
                    return real_retire_pin(pin, pin_label)

            patcher = (
                mock.patch.object(
                    edit_timeline,
                    "_truncate_snapshot",
                    side_effect=race_generation,
                )
                if label == "generation"
                else mock.patch.object(
                    edit_timeline,
                    "_retire_pin",
                    side_effect=race_pin,
                )
            )
            with patcher:
                output = render_edit(job)
            self.assertTrue(raced)
            self.assertTrue(output.is_file())
            preserved = [
                path
                for path in job.job_dir.rglob("*")
                if path.is_file() and path.read_bytes() == unknown
            ]
            self.assertEqual(len(preserved), 1)

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
            job = create_job(root, video, script, profile="legacy-v1")
            with self.assertRaises(WorkflowError):
                render_edit(job)


class TranscriptCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory()
        cls.fixture = make_av_fixture(Path(cls.fixture_temporary.name).resolve())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def _revised_cleanup_job(self, root: Path):
        job = EditTimelineTests._job_with_transcript_ready(self, root)
        plan = {
            "version": 1,
            "segments": [
                _segment("keep", 0, 1, "你好", "你好", "保留"),
                _segment("delete", 1, 2, "嗯", "", "删除语气词"),
                _segment("keep", 2, 3, "世界", "世界", "保留"),
            ],
        }
        generate_cleanup_proposal(job, plan)
        approve(job, "speech_cleanup")
        edit_dir = job.job_dir / "03-edit-structure"
        edit_dir.mkdir()
        edit_artifact = edit_dir / "timeline-map.json"
        edit_artifact.write_text('{"version":1}\n', encoding="utf-8")
        mark_ready(job, "edit_structure", [edit_artifact])
        approve(job, "edit_structure")
        previous = {
            name: (job.job_dir / "02-speech-cleanup" / name).read_bytes()
            for name in edit_timeline._PROPOSAL_NAMES
        }

        revise(job, "speech_cleanup", "修正人工核对错词")
        self.assertEqual(job.stages["speech_cleanup"]["status"], "needs_revision")
        for stage_id in STAGE_IDS[2:]:
            self.assertEqual(job.stages[stage_id]["status"], "pending")
        source = next(
            record for record in job.stages["speech_cleanup"]["lineage"]
            if record["path"] == "02-speech-cleanup/word-transcript.json"
        )
        manifest = _correction_manifest()
        manifest["source"] = {
            key: source[key] for key in ("path", "sha256", "bytes")
        }
        corrections = root / "corrections.json"
        corrections.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
        approve(job, "inspect")
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
        approve(job, "content_analysis")
        approved_content = content_analysis.load_approved_content_analysis(job)
        for stage_id, relative in (
            ("cover_direction", "03-cover-direction/review.html"),
            ("cover", "04-cover/cover.png"),
        ):
            artifact = job.job_dir / relative
            artifact.parent.mkdir()
            artifact.write_bytes(stage_id.encode("utf-8"))
            mark_ready(job, stage_id, (artifact,))
            approve(job, stage_id)

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
        approve(job, "speech_cleanup")
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
        target = job.job_dir / "02-speech-cleanup"
        self.assertEqual(
            {name: (target / name).read_bytes() for name in edit_timeline._PROPOSAL_NAMES},
            expected_tree,
        )
        persisted = load_job(job.job_dir)
        self.assertEqual(persisted.stages["speech_cleanup"]["status"], "needs_revision")
        self.assertEqual(persisted.stages["speech_cleanup"]["artifacts"], [])
        self.assertEqual(persisted.stages["speech_cleanup"]["lineage"], expected_lineage)
        self.assertFalse(list(job.job_dir.glob(".02-speech-cleanup.stage-*")))
        self.assertFalse(list(job.job_dir.glob(".02-speech-cleanup.backup-*")))

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
            '{"path":"02-speech-cleanup/word-transcript.json",'
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

    def test_rebuilds_seven_artifacts_from_revision_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, previous, old_plan, manifest, corrections = self._revised_cleanup_job(root)

            proposal_path = edit_timeline.generate_corrected_cleanup_proposal(
                job, corrections,
            )

            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")
            self.assertEqual(job.stages["edit_structure"]["status"], "pending")
            self.assertEqual(len(job.stages["speech_cleanup"]["artifacts"]), 7)
            self.assertEqual(proposal_path.name, "cleanup-proposal.json")
            for name in edit_timeline._TASK2_NAMES:
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
                job.stages["speech_cleanup"]["status"], "ready_for_review",
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
            approve(job, "content_analysis")
            for stage_id, relative in (
                ("cover_direction", "03-cover-direction/review.html"),
                ("cover", "04-cover/cover.png"),
            ):
                mark_ready(job, stage_id, (job.job_dir / relative,))
                approve(job, stage_id)
            revise(job, "speech_cleanup", "修正错词")

            output = edit_timeline.generate_corrected_cleanup_proposal(job, corrections)

            summary = json.loads((output.parent / "diff-summary.json").read_text())
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")
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
            self.assertEqual(job.stages["speech_cleanup"]["status"], "approved")
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
                job.stages["speech_cleanup"]["status"], "ready_for_review",
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
                job.stages["speech_cleanup"]["status"], "ready_for_review",
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
            for name in ("speech-16k.wav", "whisper.json", "report.json"):
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
            self.assertEqual(job.stages["speech_cleanup"]["status"], "ready_for_review")

    def test_rejects_lineage_file_identity_hash_or_parent_drift_fail_closed(self) -> None:
        for drift in ("inode", "hash", "parent"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                job, _previous, _plan, _manifest, corrections = self._revised_cleanup_job(root)
                target = job.job_dir / "02-speech-cleanup"
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
                    for name in edit_timeline._PROPOSAL_NAMES:
                        shutil.copyfile(retired / name, target / name)
                expected_tree = {
                    name: (target / name).read_bytes()
                    for name in edit_timeline._PROPOSAL_NAMES
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
                if directory.name.startswith(".02-speech-cleanup.stage-") and not replaced:
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
            target = job.job_dir / "02-speech-cleanup"
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
                ["python3", "-c", child_source, str(job.job_dir), str(corrections)],
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
                recovered.stages["speech_cleanup"]["status"], "ready_for_review",
            )

            output = edit_timeline.generate_corrected_cleanup_proposal(
                recovered, corrections,
            )

            self.assertTrue(output.is_file())
            self.assertEqual(
                recovered.stages["speech_cleanup"]["status"], "ready_for_review",
            )
            self.assertFalse((job.job_dir / ".02-speech-cleanup.lock").exists())

    def test_crash_recovery_rejects_a_different_corrections_manifest(self) -> None:
        child_source = """
import sys
from pathlib import Path
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
                    ["python3", "-c", child_source, str(job.job_dir), str(corrections)],
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
                        job.job_dir / ".02-speech-cleanup.lock",
                        edit_timeline._marker_path(
                            job.job_dir, "02-speech-cleanup",
                        ),
                    )
                    if path.exists()
                }
                target = job.job_dir / "02-speech-cleanup"
                published = {
                    name: (target / name).read_bytes()
                    for name in edit_timeline._PROPOSAL_NAMES
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
                            job.job_dir / ".02-speech-cleanup.lock",
                            edit_timeline._marker_path(
                                job.job_dir, "02-speech-cleanup",
                            ),
                        )
                        if path.exists()
                    },
                    metadata,
                )
                self.assertEqual(
                    {
                        name: (target / name).read_bytes()
                        for name in edit_timeline._PROPOSAL_NAMES
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
            approve(job, "speech_cleanup")
            revise(job, "speech_cleanup", "第二轮人工核对")
            source = next(
                record for record in job.stages["speech_cleanup"]["lineage"]
                if record["path"] == "02-speech-cleanup/word-transcript.json"
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

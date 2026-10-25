from __future__ import annotations

from array import array
import copy
import json
import math
import os
import stat
import tempfile
import subprocess
import unittest
import wave
from pathlib import Path
from unittest import mock

from edit.hd.tools import (
    content_analysis, contract_artifacts, edit_timeline, speech_edit_v2, state,
)


class FormalSpeechCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        video = self.root / "source.mp4"
        script = self.root / "script.md"
        video.write_bytes(b"video")
        script.write_text("你好AI", encoding="utf-8")
        self.job = state.create_job(
            self.root, video, script, profile="full-v2"
        )
        inspect = self.job.job_dir / "01-inspect" / "report.json"
        contract_artifacts.write_json_artifact(
            inspect,
            {
                "version": 1,
                "streams": {"video": 1, "audio": 1},
                "video": {"duration": 2.0},
                "audio": {"duration": 2.0},
            },
        )
        state.mark_ready(self.job, "inspect", (inspect,))
        state.approve(self.job, "inspect")
        content_analysis.prepare_content_analysis(self.job, {
            "thesis": "你好AI",
            "hook": "你好AI",
            "sections": [{"id": "section-1", "title": "你好AI", "source_span": [0, 4]}],
            "items": [{
                "id": "item-1", "source_text": "你好AI", "source_span": [0, 4],
                "priority": "high", "keywords": ["AI"], "semantic_type": "thesis",
                "evidence_status": "supported", "broll_priority": "high",
            }],
            "claims": [],
        })
        state.approve(self.job, "content_analysis")
        for stage_id, relative in (
            ("cover_direction", "03-cover-direction/cover-direction.json"),
            ("cover", "04-cover/cover-report.json"),
        ):
            path = self.job.job_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            state.mark_ready(self.job, stage_id, (path,))
            state.approve(self.job, stage_id)
        speech = self.job.job_dir / "05-speech-cleanup"
        speech.mkdir()
        with wave.open(str(speech / "speech-16k.wav"), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(array("h", (
                int(6000 * math.sin(2 * math.pi * 220 * index / 16000))
                if index < 16000 else 0
                for index in range(32000)
            )).tobytes())
        (speech / "scribe.json").write_text("{}\n", encoding="utf-8")
        words = [
            {
                "text": value,
                "start": round(index * 0.3 + 0.1, 2),
                "end": round(index * 0.3 + 0.3, 2),
            }
            for index, value in enumerate(("你", "好", "AI"))
        ]
        contract_artifacts.write_json_artifact(
            speech / "report.json",
            {
                "version": 1,
                "runtime": {"engine": "video-use/elevenlabs-scribe"},
                "script": {"sha256": self.job.inputs["script"]["sha256"], "bytes": 8, "coverage": 1.0},
                "transcript": {"word_count": 3, "first": 0.1, "last": 0.9, "words": words},
            },
        )
        state.mark_ready(
            self.job,
            "speech_cleanup",
            tuple(speech / name for name in ("speech-16k.wav", "scribe.json", "report.json")),
        )
        self.plan = {
            "version": 1,
            "segments": [{
                "action": "keep",
                "word_start": 0,
                "word_end": 3,
                "source_start": 0.1,
                "source_end": 0.9,
                "original_sentence": "你好AI",
                "cleaned_sentence": "你好AI",
                "reason": "保留原句",
                "breathing_padding": {"before": 0.0, "after": 0.0},
            }],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _publication_stage(
        self,
        token: str,
        names: tuple[str, ...],
        marker: bytes,
    ) -> Path:
        stage = self.job.job_dir / f".05-speech-cleanup.stage-{token:0<32}"
        stage.mkdir()
        for name in names:
            (stage / name).write_bytes(marker + name.encode("utf-8"))
        return stage

    def test_cleanup_extends_same_stage_to_one_seven_file_review(self) -> None:
        path = speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)

        self.assertEqual(path.parent.name, "05-speech-cleanup")
        self.assertEqual(
            {item.name for item in path.parent.iterdir()},
            {
                "speech-16k.wav", "scribe.json", "report.json",
                "word-transcript.json", "diff-summary.json",
                "cleanup-proposal.json", "estimated-duration.json",
                "material-usage.json",
            },
        )
        self.assertEqual(
            self.job.stages["speech_cleanup"]["status"], "ready_for_review"
        )
        self.assertIn(
            "05-speech-cleanup/material-usage.json",
            {
                item["path"]
                for item in self.job.stages["speech_cleanup"]["artifacts"]
            },
        )

    def test_edit_structure_publication_binds_material_usage_receipt(self) -> None:
        speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        state.approve(self.job, "speech_cleanup")
        target = self.job.job_dir / "06-edit-structure"
        stage = self.job.job_dir / f".06-edit-structure.stage-{'b' * 32}"
        stage.mkdir()
        names = ("edit-plan.json", "edited-aroll.mp4", "timeline-map.json")
        for name in names:
            (stage / name).write_bytes(name.encode("utf-8"))

        speech_edit_v2._publish(
            self.job, stage, target, names, stage_id="edit_structure"
        )

        self.assertTrue((target / "material-usage.json").is_file())
        self.assertIn(
            "06-edit-structure/material-usage.json",
            {
                item["path"]
                for item in self.job.stages["edit_structure"]["artifacts"]
            },
        )

    def test_cleanup_risk_report_is_published_and_refreshed_without_approval(self) -> None:
        path = speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        summary = path.parent / "diff-summary.json"
        first_hash = contract_artifacts.sha256_file(summary)
        payload = contract_artifacts.read_json_artifact(summary)
        self.assertIn("risk_assessment", payload)
        self.assertEqual(payload["risk_assessment"]["candidates"], [])
        state.approve(self.job, "speech_cleanup")
        state.revise(self.job, "speech_cleanup", "核听发现局部口误")
        revised = {**self.plan, "version": 2, "reviewed_cut_ranges": [{
            "source_start": 0.32, "source_end": 0.44,
            "reason": "人工核听词内重复", "evidence": "当前源音频试听",
        }]}
        speech_edit_v2.prepare_cleanup_proposal(self.job, revised)
        payload = contract_artifacts.read_json_artifact(summary)
        self.assertNotEqual(contract_artifacts.sha256_file(summary), first_hash)
        self.assertEqual(payload["risk_assessment"]["counts"]["review"], 1)
        current = state.load_job(self.job.job_dir)
        self.assertEqual(current.stages["speech_cleanup"]["status"], "ready_for_review")
        self.assertEqual(current.stages["edit_structure"]["status"], "pending")
        record = next(item for item in current.stages["speech_cleanup"]["artifacts"]
                      if item["path"].endswith("/diff-summary.json"))
        self.assertEqual(record["sha256"], contract_artifacts.sha256_file(summary))

    def test_cleanup_summary_consumes_approved_content_terms(self) -> None:
        path = speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        payload = contract_artifacts.read_json_artifact(path.parent / "diff-summary.json")
        approved = content_analysis.load_approved_content_analysis(self.job)

        terminology = payload["terminology_review"]
        self.assertEqual(terminology["content_analysis_sha256"], approved["analysis_sha256"])
        self.assertEqual(terminology["approved_terms"], ["AI"])
        self.assertFalse(terminology["report"]["automatic_replacement"])

    def test_cleanup_proposal_can_be_rebuilt_after_review_revision(self) -> None:
        speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        state.approve(self.job, "speech_cleanup")
        state.revise(self.job, "speech_cleanup", "补充清理重字")
        revised = {
            **self.plan,
            "version": 2,
            "reviewed_cut_ranges": [{
                "source_start": 0.32,
                "source_end": 0.44,
                "reason": "人工核听确认词内口吃",
                "evidence": "whisper-dtw+人工复核",
            }],
        }

        path = speech_edit_v2.prepare_cleanup_proposal(self.job, revised)

        self.assertTrue(path.is_file())
        self.assertEqual(
            self.job.stages["speech_cleanup"]["status"], "ready_for_review"
        )
        self.assertEqual(self.job.stages["edit_structure"]["status"], "pending")

    def test_cleanup_revision_retains_corrected_transcript_and_history(self) -> None:
        speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        state.approve(self.job, "speech_cleanup")
        transcript = self.job.job_dir / "05-speech-cleanup/word-transcript.json"
        manifest = self.root / "corrections.json"
        manifest.write_text(json.dumps({
            "version": 1,
            "source": {
                "path": "05-speech-cleanup/word-transcript.json",
                "sha256": contract_artifacts.sha256_file(transcript),
                "bytes": transcript.stat().st_size,
            },
            "corrections": [{
                "word_start": 0, "word_end": 1,
                "expected_words": [{"text": "你", "start": 0.1, "end": 0.3}],
                "replacement_texts": ["您"], "reason": "人工核听",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        state.revise(self.job, "speech_cleanup", "修正口误")
        edit_timeline.generate_corrected_cleanup_proposal(self.job, manifest)
        state.approve(self.job, "speech_cleanup")
        state.revise(self.job, "speech_cleanup", "重新调整节奏")

        revised_plan = copy.deepcopy(self.plan)
        revised_plan["segments"][0]["original_sentence"] = "您好AI"
        revised_plan["segments"][0]["cleaned_sentence"] = "您好AI"
        speech_edit_v2.prepare_cleanup_proposal(self.job, revised_plan)
        corrected = contract_artifacts.read_json_artifact(transcript)
        summary = contract_artifacts.read_json_artifact(
            self.job.job_dir / "05-speech-cleanup/diff-summary.json"
        )
        self.assertEqual(corrected["words"][0]["text"], "您")
        self.assertEqual(corrected["words"][0]["start"], 0.1)
        self.assertEqual(corrected["words"][0]["end"], 0.3)
        self.assertEqual(len(summary["transcript_corrections"]["runs"]), 1)
        self.assertEqual(summary["terminology_review"]["report"]["history_run_count"], 1)
        self.assertEqual(
            summary["transcript_corrections"]["runs"][0]["changes"][0]["after"],
            ["您"],
        )

    def test_publish_mark_ready_failure_restores_generation_and_retry_succeeds(
        self,
    ) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        previous = {name: (target / name).read_bytes() for name in names}
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        first = self._publication_stage("1", names, b"new-")

        with mock.patch.object(
            speech_edit_v2.state,
            "mark_ready",
            side_effect=RuntimeError("injected ready failure"),
        ), self.assertRaises(RuntimeError):
            speech_edit_v2._publish(
                self.job, first, target, names, stage_id="speech_cleanup"
            )

        self.assertEqual(
            {name: (target / name).read_bytes() for name in names}, previous
        )
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["speech_cleanup"]["status"],
            "needs_revision",
        )
        self.assertFalse(
            (self.job.job_dir / ".05-speech-cleanup.generation.marker").exists()
        )

        retry = self._publication_stage("2", names, b"new-")
        published = speech_edit_v2._publish(
            self.job, retry, target, names, stage_id="speech_cleanup"
        )

        self.assertEqual(published, target)
        self.assertEqual(
            self.job.stages["speech_cleanup"]["status"], "ready_for_review"
        )

    def test_publish_deduplicates_two_independent_job_snapshots(self) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        first_job = state.load_job(self.job.job_dir)
        second_job = state.load_job(self.job.job_dir)
        first = self._publication_stage("3", names, b"same-")
        second = self._publication_stage("4", names, b"same-")

        speech_edit_v2._publish(
            first_job, first, target, names, stage_id="speech_cleanup"
        )
        published = speech_edit_v2._publish(
            second_job, second, target, names, stage_id="speech_cleanup"
        )

        self.assertEqual(published, target)
        self.assertFalse(second.exists())
        self.assertEqual(second_job.revision, first_job.revision)
        self.assertEqual(
            second_job.stages["speech_cleanup"]["status"], "ready_for_review"
        )

    def test_publish_interruption_is_recovered_by_the_next_retry(self) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        interrupted = self._publication_stage("5", names, b"retry-")

        def stop_after_journal(name: str) -> None:
            if name == "marker_durable":
                raise KeyboardInterrupt

        with mock.patch.object(
            speech_edit_v2.edit_timeline,
            "_crash_checkpoint",
            side_effect=stop_after_journal,
        ), self.assertRaises(KeyboardInterrupt):
            speech_edit_v2._publish(
                self.job,
                interrupted,
                target,
                names,
                stage_id="speech_cleanup",
            )

        self.assertTrue(
            (self.job.job_dir / ".05-speech-cleanup.generation.marker").is_file()
        )
        self.assertTrue(
            speech_edit_v2._publication_owns_stage(
                self.job, target, interrupted
            )
        )
        retry_job = state.load_job(self.job.job_dir)
        retry = self._publication_stage("6", names, b"retry-")

        speech_edit_v2._publish(
            retry_job, retry, target, names, stage_id="speech_cleanup"
        )

        self.assertEqual(
            retry_job.stages["speech_cleanup"]["status"], "ready_for_review"
        )
        self.assertFalse(
            (self.job.job_dir / ".05-speech-cleanup.generation.marker").exists()
        )

    def test_publish_fsyncs_every_stage_file_and_directory_before_journal_and_state(
        self,
    ) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        stage = self._publication_stage("7", names, b"ordered-")
        file_identities = {
            (status.st_dev, status.st_ino): name
            for name in names
            for status in ((stage / name).stat(),)
        }
        directory_status = stage.stat()
        directory_identity = (directory_status.st_dev, directory_status.st_ino)
        events: list[str] = []
        real_fsync = os.fsync
        real_marker = speech_edit_v2.edit_timeline._write_generation_marker
        real_ready = speech_edit_v2.state.mark_ready

        def record_fsync(descriptor: int) -> None:
            status = os.fstat(descriptor)
            identity = (status.st_dev, status.st_ino)
            if identity in file_identities:
                self.assertTrue(stat.S_ISREG(status.st_mode))
                events.append(f"file:{file_identities[identity]}")
            elif identity == directory_identity:
                self.assertTrue(stat.S_ISDIR(status.st_mode))
                events.append("stage-directory")
            real_fsync(descriptor)

        def record_marker(*args, **kwargs):
            events.append("journal")
            return real_marker(*args, **kwargs)

        def record_ready(*args, **kwargs):
            events.append("workflow")
            return real_ready(*args, **kwargs)

        with mock.patch.object(
            speech_edit_v2.os, "fsync", side_effect=record_fsync,
        ), mock.patch.object(
            speech_edit_v2.edit_timeline,
            "_write_generation_marker",
            side_effect=record_marker,
        ), mock.patch.object(
            speech_edit_v2.state,
            "mark_ready",
            side_effect=record_ready,
        ):
            speech_edit_v2._publish(
                self.job, stage, target, names, stage_id="speech_cleanup"
            )

        self.assertEqual(
            events,
            [
                "stage-directory",
                *(f"file:{name}" for name in sorted(names)),
                "stage-directory",
                "journal",
                "workflow",
            ],
        )

    def test_stage_file_fsync_failure_keeps_old_generation_and_retry_succeeds(
        self,
    ) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        previous = {name: (target / name).read_bytes() for name in names}
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        workflow_before = copy.deepcopy(
            state.load_job(self.job.job_dir).stages["speech_cleanup"]
        )
        stage = self._publication_stage("8", names, b"durable-")
        stage_identities = {
            (status.st_dev, status.st_ino)
            for name in names
            for status in ((stage / name).stat(),)
        }
        real_fsync = os.fsync
        stage_file_calls = 0

        def fail_second_stage_file(descriptor: int) -> None:
            nonlocal stage_file_calls
            status = os.fstat(descriptor)
            if (status.st_dev, status.st_ino) in stage_identities:
                stage_file_calls += 1
                if stage_file_calls == 2:
                    raise OSError("injected stage fsync failure")
            real_fsync(descriptor)

        with mock.patch.object(
            speech_edit_v2.os,
            "fsync",
            side_effect=fail_second_stage_file,
        ), self.assertRaises(speech_edit_v2.SpeechEditV2Error):
            speech_edit_v2._publish(
                self.job, stage, target, names, stage_id="speech_cleanup"
            )

        self.assertEqual(stage_file_calls, 2)
        self.assertEqual(
            {name: (target / name).read_bytes() for name in names}, previous
        )
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["speech_cleanup"],
            workflow_before,
        )
        self.assertFalse(
            (self.job.job_dir / ".05-speech-cleanup.generation.marker").exists()
        )
        self.assertTrue(stage.is_dir())

        published = speech_edit_v2._publish(
            self.job, stage, target, names, stage_id="speech_cleanup"
        )

        self.assertEqual(published, target)
        self.assertEqual(
            self.job.stages["speech_cleanup"]["status"], "ready_for_review"
        )

    def test_stage_sync_rejects_unexpected_and_nonregular_entries(self) -> None:
        names = ("speech-16k.wav", "scribe.json", "report.json")
        target = self.job.job_dir / "05-speech-cleanup"
        previous = {name: (target / name).read_bytes() for name in names}
        state.revise(self.job, "speech_cleanup", "重新生成口播整理")
        workflow_before = copy.deepcopy(
            state.load_job(self.job.job_dir).stages["speech_cleanup"]
        )
        unexpected = self._publication_stage("9", names, b"unexpected-")
        (unexpected / "extra.json").write_text("{}\n", encoding="utf-8")
        nonregular = self._publication_stage("a", names, b"nonregular-")
        (nonregular / "report.json").unlink()
        (nonregular / "report.json").mkdir()

        for stage in (unexpected, nonregular):
            with self.subTest(stage=stage.name), self.assertRaises(
                speech_edit_v2.SpeechEditV2Error
            ):
                speech_edit_v2._publish(
                    self.job, stage, target, names, stage_id="speech_cleanup"
                )

        self.assertEqual(
            {name: (target / name).read_bytes() for name in names}, previous
        )
        self.assertEqual(
            state.load_job(self.job.job_dir).stages["speech_cleanup"],
            workflow_before,
        )
        self.assertFalse(
            (self.job.job_dir / ".05-speech-cleanup.generation.marker").exists()
        )

    def test_cleanup_rejects_reviewed_cut_that_only_targets_silence(self) -> None:
        silent_cut = {
            **self.plan,
            "version": 2,
            "reviewed_cut_ranges": [{
                "source_start": 1.20,
                "source_end": 1.30,
                "reason": "词内口吃",
                "evidence": "人工复核",
            }],
        }

        with self.assertRaisesRegex(
            speech_edit_v2.SpeechEditV2Error,
            "does not overlap audible speech",
        ):
            speech_edit_v2.prepare_cleanup_proposal(self.job, silent_cut)

    def test_video_use_renderer_requires_a_bound_preflight_dependency(self) -> None:
        repository = self.root / "video-use"
        renderer = repository / "helpers" / "render.py"
        renderer.parent.mkdir(parents=True)
        renderer.write_text("print('fixture')\n", encoding="utf-8")
        manifests = self.job.job_dir / "manifests"
        manifests.mkdir(exist_ok=True)
        contract_artifacts.write_json_artifact(
            manifests / "dependency-preflight.json",
            {
                "schema_version": 2,
                "dependencies": [{
                    "id": "video-use-runtime",
                    "status": "bound",
                    "availability_level": "bound",
                    "resolved_path": str(repository),
                }],
            },
        )

        self.assertEqual(speech_edit_v2._video_use_renderer(self.job), renderer)

    def test_video_use_renderer_rejects_directory_only_availability(self) -> None:
        repository = self.root / "video-use"
        (repository / "helpers").mkdir(parents=True)
        (repository / "helpers" / "render.py").write_text(
            "print('fixture')\n", encoding="utf-8"
        )
        manifests = self.job.job_dir / "manifests"
        manifests.mkdir(exist_ok=True)
        contract_artifacts.write_json_artifact(
            manifests / "dependency-preflight.json",
            {
                "schema_version": 2,
                "dependencies": [{
                    "id": "video-use-runtime",
                    "status": "available",
                    "availability_level": "installed",
                    "resolved_path": str(repository),
                }],
            },
        )

        with self.assertRaises(speech_edit_v2.SpeechEditV2Error):
            speech_edit_v2._video_use_renderer(self.job)

    def test_video_use_render_receives_the_approved_kept_ranges(self) -> None:
        renderer = self.root / "render.py"
        renderer.write_text("print('fixture')\n", encoding="utf-8")
        source = self.root / "source-real.mp4"
        source.write_bytes(b"video")
        stage = self.root / "stage"
        stage.mkdir()
        output = stage / "edited-aroll.mp4"
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if len(calls) == 1:
                self.assertEqual(command[0], str(Path(__import__('sys').executable)))
                self.assertEqual(command[1], str(renderer))
                self.assertIn("--no-subtitles", command)
                self.assertIn("--no-loudnorm", command)
                Path(command[command.index("-o") + 1]).write_bytes(b"square-render")
                clips = stage / "clips_graded"
                clips.mkdir()
                for index in range(2):
                    (clips / f"seg_{index:02d}_aroll.mp4").write_bytes(b"graded-video")
            else:
                self.assertEqual(command[0], "ffmpeg")
                filters = command[command.index("-filter_complex") + 1]
                self.assertIn(speech_edit_v2.PORTRAIT_NORMALIZE_FILTER, filters)
                self.assertIn("atrim=start=1.800000000:end=3.000000000", filters)
                self.assertIn("aresample=48000,asplit=2", filters)
                self.assertIn("apad=whole_len=58000,atrim=end_sample=58000", filters)
                self.assertIn("concat=n=2:v=0:a=1", filters)
                self.assertEqual(command[command.index("-c:a") + 1], "aac")
                self.assertEqual(command[-1], str(output))
                output.write_bytes(b"normalized-render")
            return mock.Mock(returncode=0)

        with mock.patch.object(speech_edit_v2.subprocess, "run", side_effect=fake_run):
            speech_edit_v2._render_with_video_use(
                renderer,
                source,
                [(0.0, 1.2), (1.8, 3.0)],
                output,
                stage,
                timeout=60,
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(output.read_bytes(), b"normalized-render")
        self.assertFalse((stage / "video-use-edl.json").exists())
        self.assertFalse((stage / "video-use-render.mp4").exists())

    def test_portrait_normalization_resets_non_square_source_pixels(self) -> None:
        output = self.root / "normalized.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1080x1080:r=1:d=1",
                "-vf", f"setsar=9/16,{speech_edit_v2.PORTRAIT_NORMALIZE_FILTER}",
                "-frames:v", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,sample_aspect_ratio,display_aspect_ratio",
                "-of", "default=noprint_wrappers=1", str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

        self.assertIn("width=1080", probe)
        self.assertIn("height=1920", probe)
        self.assertIn("sample_aspect_ratio=1:1", probe)
        self.assertIn("display_aspect_ratio=9:16", probe)

    def test_video_use_pacing_splits_long_silence_without_deleting_words(self) -> None:
        words = [
            {"text": "先", "start": 0.10, "end": 0.30},
            {"text": "说", "start": 0.32, "end": 0.52},
            {"text": "再", "start": 1.20, "end": 1.40},
            {"text": "说", "start": 1.42, "end": 1.62},
        ]
        plan = {
            "version": 1,
            "segments": [{
                "action": "keep",
                "word_start": 0,
                "word_end": 4,
                "source_start": 0.10,
                "source_end": 1.62,
                "original_sentence": "先说再说",
                "cleaned_sentence": "先说再说",
                "reason": "保留原句",
                "breathing_padding": {"before": 0.0, "after": 0.0},
            }],
        }

        silent = self.root / "pacing-silence.wav"
        with wave.open(str(silent), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(array("h", [0] * 32000).tobytes())
        paced = speech_edit_v2._apply_video_use_pacing(plan, words, silent)
        intervals = speech_edit_v2._video_use_intervals(paced, 2.0)

        breathing_plan = copy.deepcopy(plan)
        breathing_plan["segments"][0]["breathing_padding"] = {"before": 0.16, "after": 0.18}
        breathing = speech_edit_v2._apply_video_use_pacing(breathing_plan, words, silent)
        self.assertEqual(breathing["segments"][0]["breathing_padding"]["before"], 0.16)
        self.assertEqual(breathing["segments"][-1]["breathing_padding"]["after"], 0.18)
        self.assertAlmostEqual(breathing["segments"][0]["breathing_padding"]["after"], 0.16)
        self.assertAlmostEqual(breathing["segments"][-1]["breathing_padding"]["before"], 0.16, delta=1/16000)

        self.assertEqual(len(paced["segments"]), 2)
        self.assertEqual(
            [(round(start, 2), round(end, 2)) for start, end in intervals],
            [(0.0, 0.68), (1.04, 1.62)],
        )
        audible = speech_edit_v2._apply_video_use_pacing(
            plan, words, self.job.job_dir / "05-speech-cleanup/speech-16k.wav"
        )
        self.assertEqual(len(audible["segments"]), 1)

    def test_residual_cleanup_requires_exact_host_audio_review(self) -> None:
        speech_edit_v2.prepare_cleanup_proposal(self.job, self.plan)
        candidates = [{"candidate_id": "repeat-one"}]
        with mock.patch.object(speech_edit_v2, "cleanup_check_candidates", return_value=candidates):
            with self.assertRaises(speech_edit_v2.SpeechEditV2Error):
                speech_edit_v2.validate_cleanup_review(self.job, {})
            review = {"speech_cleanup_resolutions": [{
                "candidate_id": "repeat-one", "decision": "keep",
                "reason": "已核听为有意重复强调，保留原语气",
            }]}
            speech_edit_v2.validate_cleanup_review(self.job, review)
            state.approve(self.job, "speech_cleanup")
            with self.assertRaises(speech_edit_v2.SpeechEditV2Error):
                speech_edit_v2._require_cleanup_review(self.job)
            receipt = {**review, "job_id": self.job.job_id, "job_dir": str(self.job.job_dir),
                       "stage": "speech_cleanup", "passed": True, "reviewed_by": "host",
                       "artifacts": self.job.stages["speech_cleanup"]["artifacts"]}
            path = self.job.job_dir / "manifests/local-qa-speech_cleanup-r1.json"
            contract_artifacts.write_json_artifact(path, receipt)
            speech_edit_v2._require_cleanup_review(self.job)
            receipt["artifacts"] = []
            contract_artifacts.write_json_artifact(path, receipt)
            with self.assertRaises(speech_edit_v2.SpeechEditV2Error):
                speech_edit_v2._require_cleanup_review(self.job)

    def test_pacing_finds_quiet_middle_after_audible_word_tail(self) -> None:
        words = [
            {"text": "第二。", "start": 0.1, "end": 0.4},
            {"text": "这次", "start": 3.6, "end": 3.9},
        ]
        plan = {"version": 1, "segments": [{
            "action": "keep", "word_start": 0, "word_end": 2,
            "source_start": 0.1, "source_end": 3.9,
            "original_sentence": "第二。这次", "cleaned_sentence": "第二。这次",
            "reason": "保留", "breathing_padding": {"before": 0.5, "after": 0.5},
        }]}
        wav = self.root / "word-tail.wav"
        with wave.open(str(wav), "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
            audio.writeframes(array("h", (
                int(6000 * math.sin(2 * math.pi * 220 * i / 16000))
                if i < 0.62 * 16000 or i >= 3.48 * 16000 else 20
                for i in range(64000)
            )).tobytes())
        paced = speech_edit_v2._apply_video_use_pacing(plan, words, wav)
        self.assertEqual(len(paced["segments"]), 2)
        left, right = paced["segments"]
        self.assertGreaterEqual(left["source_end"] + left["breathing_padding"]["after"], 0.62)
        self.assertLessEqual(right["source_start"] - right["breathing_padding"]["before"], 3.48)
        self.assertLess(left["breathing_padding"]["after"] + right["breathing_padding"]["before"], 0.8)
        self.assertEqual(speech_edit_v2._apply_video_use_pacing(paced, words, wav), paced)
        # A different keep partition must not hide the same retained long pause.
        split = copy.deepcopy(plan)
        split["segments"] = [dict(plan["segments"][0]), dict(plan["segments"][0])]
        for segment, index in zip(split["segments"], (0, 1)):
            segment.update(word_start=index, word_end=index + 1,
                           source_start=words[index]["start"], source_end=words[index]["end"],
                           original_sentence=words[index]["text"], cleaned_sentence=words[index]["text"])
        result = speech_edit_v2._apply_video_use_pacing(split, words, wav)
        self.assertLess(sum(result["segments"][i]["breathing_padding"][k]
                            for i, k in ((0, "after"), (1, "before"))), 0.8)

    def test_video_use_pacing_preserves_and_applies_reviewed_cut_ranges(self) -> None:
        words = [
            {"text": "你", "start": 0.10, "end": 0.30},
            {"text": "好", "start": 0.30, "end": 0.60},
        ]
        plan = {
            "version": 2,
            "segments": [{
                "action": "keep",
                "word_start": 0,
                "word_end": 2,
                "source_start": 0.10,
                "source_end": 0.60,
                "original_sentence": "你好",
                "cleaned_sentence": "你好",
                "reason": "保留",
                "breathing_padding": {"before": 0.0, "after": 0.0},
            }],
            "reviewed_cut_ranges": [{
                "source_start": 0.32,
                "source_end": 0.44,
                "reason": "人工核听确认词内口吃",
                "evidence": "whisper-dtw+人工复核",
            }],
        }

        paced = speech_edit_v2._apply_video_use_pacing(
            plan, words, self.job.job_dir / "05-speech-cleanup/speech-16k.wav"
        )
        intervals = speech_edit_v2._video_use_intervals(paced, 1.0)

        self.assertEqual(paced["version"], 2)
        self.assertEqual(
            paced["reviewed_cut_ranges"], plan["reviewed_cut_ranges"]
        )
        self.assertEqual(
            [(round(start, 2), round(end, 2)) for start, end in intervals],
            [(0.0, 0.32), (0.44, 0.6)],
        )

    def test_video_use_intervals_do_not_restore_long_recording_lead_in(self) -> None:
        plan = {
            "segments": [
                {"action": "keep", "source_start": 3.14, "source_end": 4.46,
                 "original_sentence": "学AI看这里。",
                 "breathing_padding": {"before": 0.08, "after": 0.08}},
                {"action": "keep", "source_start": 5.72, "source_end": 9.04,
                 "original_sentence": "国庆假期过半。",
                 "breathing_padding": {"before": 0.08, "after": 0.08}},
                {"action": "delete", "source_start": 9.50, "source_end": 10.0},
            ],
        }
        intervals = speech_edit_v2._video_use_intervals(plan, 10.0)
        self.assertEqual(
            [(round(start, 2), round(end, 2)) for start, end in intervals],
            [(3.06, 4.54), (5.64, 9.12)],
        )

    def test_video_use_intervals_omit_padding_only_micro_segments(self) -> None:
        plan = {
            "segments": [
                {"action": "keep", "source_start": 0.10, "source_end": 0.30,
                 "original_sentence": "你", "breathing_padding": {"before": 0.08, "after": 0.08}},
                {"action": "delete", "source_start": 0.30, "source_end": 0.34},
                {"action": "keep", "source_start": 0.80, "source_end": 0.82,
                 "original_sentence": "，", "breathing_padding": {"before": 0.08, "after": 0.08}},
                {"action": "keep", "source_start": 1.40, "source_end": 1.60,
                 "original_sentence": "好", "breathing_padding": {"before": 0.08, "after": 0.08}},
            ],
        }
        intervals = speech_edit_v2._video_use_intervals(plan, 2.0)
        self.assertEqual(
            [(round(start, 2), round(end, 2)) for start, end in intervals],
            [(0.0, 0.30), (1.32, 1.68)],
        )

    def test_video_use_timeline_uses_complete_rendered_frames(self) -> None:
        segments, duration = speech_edit_v2._frame_aligned_timeline(
            [(0.0, 1.01), (2.0, 3.01)], fps=24,
        )

        self.assertAlmostEqual(segments[0]["timeline_end"], 25 / 24)
        self.assertAlmostEqual(segments[1]["timeline_start"], 25 / 24)
        self.assertAlmostEqual(duration, 50 / 24)

    def test_video_use_zero_duration_words_keep_verbatim_text(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "最", "start": 0.1, "end": 0.3},
            {"type": "word", "text": "近", "start": 0.3, "end": 0.3},
            {"type": "spacing", "text": " "},
            {"type": "word", "text": "AI", "start": 0.4, "end": 0.7},
            {"type": "audio_event", "text": "(noise)", "start": 0.8, "end": 0.9},
        ]}

        words, merged = speech_edit_v2._normalize_video_use_words(payload, 1.0)

        self.assertEqual(merged, 1)
        self.assertEqual([(word.text, word.start, word.end) for word in words], [
            ("最近 ", 0.1, 0.3), ("AI", 0.4, 0.7),
        ])

    def test_video_use_rejects_overlapping_words(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "你", "start": 0.1, "end": 0.3},
            {"type": "word", "text": "好", "start": 0.2, "end": 0.4},
        ]}

        with self.assertRaisesRegex(speech_edit_v2.SpeechEditV2Error, "overlap"):
            speech_edit_v2._normalize_video_use_words(payload, 1.0)

    def test_video_use_zero_duration_punctuation_does_not_extend_previous_word(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "多", "start": 78.40, "end": 78.44},
            {"type": "word", "text": "，", "start": 84.16, "end": 84.16},
            {"type": "word", "text": "靠", "start": 84.40, "end": 84.42},
        ]}
        words, _ = speech_edit_v2._normalize_video_use_words(payload, 90.0)
        self.assertEqual([(word.text, word.start, word.end) for word in words], [
            ("多，", 78.40, 78.44), ("靠", 84.40, 84.42),
        ])

    def test_video_use_positive_duration_punctuation_is_attached(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "你好", "start": 0.10, "end": 0.30},
            {"type": "word", "text": "，", "start": 0.30, "end": 0.80},
            {"type": "word", "text": "世界", "start": 0.90, "end": 1.10},
        ]}
        words, _ = speech_edit_v2._normalize_video_use_words(payload, 2.0)
        self.assertEqual([(word.text, word.start, word.end) for word in words], [
            ("你好，", 0.10, 0.30), ("世界", 0.90, 1.10),
        ])

    def test_video_use_semantic_symbols_keep_their_timing(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "%", "start": 0.10, "end": 0.20},
            {"type": "word", "text": "你好，", "start": 0.30, "end": 0.60},
        ]}
        words, _ = speech_edit_v2._normalize_video_use_words(payload, 1.0)
        self.assertEqual([(word.text, word.start, word.end) for word in words], [
            ("%", 0.10, 0.20), ("你好，", 0.30, 0.60),
        ])

    def test_video_use_zero_duration_lexical_word_requires_endpoint(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "前", "start": 0.10, "end": 0.30},
            {"type": "word", "text": "图", "start": 0.60, "end": 0.60},
        ]}
        with self.assertRaisesRegex(speech_edit_v2.SpeechEditV2Error, "separated"):
            speech_edit_v2._normalize_video_use_words(payload, 1.0)

    def test_video_use_zero_duration_lexical_word_at_endpoint_keeps_text(self) -> None:
        payload = {"words": [
            {"type": "word", "text": "前", "start": 0.10, "end": 0.30},
            {"type": "word", "text": "图", "start": 0.30, "end": 0.30},
        ]}
        words, _ = speech_edit_v2._normalize_video_use_words(payload, 1.0)
        self.assertEqual([(word.text, word.start, word.end) for word in words], [
            ("前图", 0.10, 0.30),
        ])


if __name__ == "__main__":
    unittest.main()

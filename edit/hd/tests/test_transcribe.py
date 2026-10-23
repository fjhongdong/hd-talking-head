from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from edit.hd.tests.media_fixture import make_av_fixture, make_video_only_fixture
from edit.hd.tools.inspect_inputs import inspect_inputs, inspect_job
from edit.hd.tools.state import approve, create_job, mark_ready, revise
from edit.hd.tools.transcribe import (
    GenerationRecoveryError,
    TranscriptionError,
    WhisperRuntime,
    Word,
    discover_runtime,
    extract_pcm16k,
    parse_words_json,
    script_coverage,
    transcribe_job,
    transcribe_words,
)


class TranscribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_tmp = tempfile.TemporaryDirectory()
        cls.video = make_av_fixture(Path(cls.fixture_tmp.name).resolve())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_tmp.cleanup()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _runtime_files(self) -> WhisperRuntime:
        executable = self.directory / "whisper-cli"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        model = self.directory / "model.bin"
        model.write_bytes(b"model")
        return WhisperRuntime(executable, model)

    def _approve_inspect(self, job) -> None:
        inspect_job(job)
        approve(job, "inspect")

    def test_discover_runtime_prefers_complete_environment_pair(self) -> None:
        runtime = self._runtime_files()
        with mock.patch.dict(os.environ, {
            "HD_WHISPER_CLI": str(runtime.executable),
            "HD_WHISPER_MODEL": str(runtime.model),
        }, clear=False):
            self.assertEqual(runtime, discover_runtime())

    def test_discover_runtime_rejects_incomplete_environment_pair(self) -> None:
        with mock.patch.dict(os.environ, {"HD_WHISPER_CLI": "/tmp/nope"}, clear=True):
            with self.assertRaises(TranscriptionError):
                discover_runtime()

    def test_discover_runtime_falls_back_to_path_and_current_home_cache(self) -> None:
        runtime = self._runtime_files()
        home = self.directory / "home"
        model = home / ".cache/hd-talking-head/models/ggml-large-v3-turbo.bin"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"model")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "edit.hd.tools.transcribe.shutil.which", return_value=str(runtime.executable),
        ), mock.patch(
            "edit.hd.tools.transcribe.Path.home", return_value=home,
        ):
            self.assertEqual(WhisperRuntime(runtime.executable, model), discover_runtime())

    def test_extract_pcm16k_outputs_valid_mono_s16le_wav(self) -> None:
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        with wave.open(str(wav), "rb") as handle:
            self.assertEqual((1, 16000, 2), (
                handle.getnchannels(), handle.getframerate(), handle.getsampwidth(),
            ))
            self.assertGreater(handle.getnframes(), 0)

    def test_extract_pcm16k_rejects_symlink_output_directory(self) -> None:
        outside = self.directory / "outside"
        outside.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(TranscriptionError):
            extract_pcm16k(self.video, alias / "speech.wav")
        self.assertFalse((outside / "speech.wav").exists())

    def test_extract_pcm16k_sanitizes_publication_errors_and_cleans_partial(self) -> None:
        wav = self.directory / "speech.wav"
        with mock.patch(
            "edit.hd.tools.transcribe.os.replace",
            side_effect=OSError("/secret/audio publication failed"),
        ):
            with self.assertRaises(TranscriptionError) as captured:
                extract_pcm16k(self.video, wav)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertFalse(wav.exists())
        residuals = [
            path for path in self.directory.iterdir() if path.name.endswith(".partial")
        ]
        self.assertLessEqual(len(residuals), 1)
        for residual in residuals:
            with wave.open(str(residual), "rb") as handle:
                self.assertGreater(handle.getnframes(), 0)

    def test_extract_cleanup_error_never_overrides_primary_error(self) -> None:
        from edit.hd.tools import transcribe as module

        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                wav = self.directory / f"speech-{failure_type.__name__}.wav"
                real_unlink = os.unlink
                injected = False

                def fail_cleanup(path, *args, **kwargs):
                    nonlocal injected
                    if not injected and Path(path).name.endswith(".partial"):
                        injected = True
                        raise failure_type("/secret/cleanup failed")
                    return real_unlink(path, *args, **kwargs)

                with mock.patch(
                    "edit.hd.tools.transcribe._run",
                    side_effect=TranscriptionError("primary decode failed"),
                ), mock.patch(
                    "edit.hd.tools.transcribe.os.unlink", side_effect=fail_cleanup,
                ), self.assertRaises(TranscriptionError) as captured:
                    extract_pcm16k(self.video, wav)
                self.assertTrue(injected)
                self.assertEqual("primary decode failed", str(captured.exception))
                self.assertNotIn("/secret", str(captured.exception))

    def test_extract_cleanup_does_not_delete_unknown_partial_replacement(self) -> None:
        wav = self.directory / "speech-unknown.wav"
        valuable = self.directory / "valuable.bin"
        valuable.write_bytes(b"must survive")

        def replace_partial_then_fail(command, **_kwargs):
            partial = Path(command[-1])
            partial.write_bytes(b"owned partial")
            os.replace(valuable, partial)
            raise TranscriptionError("primary decode failed")

        with mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=replace_partial_then_fail,
        ), self.assertRaisesRegex(TranscriptionError, "primary decode failed"):
            extract_pcm16k(self.video, wav)
        replacements = [
            path for path in self.directory.iterdir()
            if path.name.endswith(".partial") and path.read_bytes() == b"must survive"
        ]
        self.assertEqual(1, len(replacements))

    def test_extract_pin_interrupt_is_sanitized(self) -> None:
        with mock.patch(
            "edit.hd.tools.transcribe._descriptor_sha256",
            side_effect=KeyboardInterrupt("/secret/pin interrupted"),
        ), self.assertRaises(TranscriptionError) as captured:
            extract_pcm16k(self.video, self.directory / "speech-pin.wav")
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn("/secret", str(captured.exception))

    def test_cleanup_move_failure_removes_empty_quarantine(self) -> None:
        wav = self.directory / "speech-cleanup.wav"
        with mock.patch(
            "edit.hd.tools.transcribe._run",
            side_effect=TranscriptionError("primary decode failed"),
        ), mock.patch(
            "edit.hd.tools.transcribe._move_owned",
            side_effect=GenerationRecoveryError("cleanup move failed"),
        ), self.assertRaisesRegex(TranscriptionError, "primary decode failed"):
            extract_pcm16k(self.video, wav)
        self.assertFalse(any(
            ".cleanup." in path.name for path in self.directory.iterdir()
        ))

    def test_fixed_fixture_parses_ordered_chinese_words_and_coverage(self) -> None:
        source = json.dumps({
            "transcription": [{
                "tokens": [
                    {"text": "你", "offsets": {"from": 100, "to": 300}},
                    {"text": "好", "offsets": {"from": 300, "to": 600}},
                    {"text": "世界", "offsets": {"from": 700, "to": 1100}},
                ]
            }]
        }, ensure_ascii=False)
        words = parse_words_json(source, media_duration=3.0)
        self.assertEqual([" ".join(()) + "你", "好", "世界"], [w.text for w in words])
        self.assertEqual((0.1, 1.1), (words[0].start, words[-1].end))
        self.assertEqual(1.0, script_coverage("你好，世界！", words))

    def test_parser_ignores_whisper_timestamp_control_tokens(self) -> None:
        source = json.dumps({
            "transcription": [{
                "tokens": [
                    {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
                    {"text": "你", "offsets": {"from": 0, "to": 300}},
                    {"text": "[_TT_150]", "offsets": {"from": 3000, "to": 3000}},
                ]
            }]
        }, ensure_ascii=False)

        words = parse_words_json(source, media_duration=3.0)

        self.assertEqual([Word("你", 0.0, 0.3)], words)

    def test_parser_ignores_zero_duration_whitespace_markers(self) -> None:
        source = json.dumps({
            "transcription": [{
                "tokens": [
                    {"text": "你", "offsets": {"from": 100, "to": 300}},
                    {"text": " ", "offsets": {"from": 300, "to": 300}},
                    {"text": "好", "offsets": {"from": 300, "to": 600}},
                ]
            }]
        }, ensure_ascii=False)

        words = parse_words_json(source, media_duration=3.0)

        self.assertEqual([Word("你", 0.1, 0.3), Word("好", 0.3, 0.6)], words)

    def test_parser_validates_zero_duration_whitespace_marker_timeline(self) -> None:
        invalid_tokens = (
            [
                {"text": "你", "offsets": {"from": 500, "to": 700}},
                {"text": " ", "offsets": {"from": 400, "to": 400}},
            ],
            [
                {"text": "你", "offsets": {"from": 100, "to": 300}},
                {"text": " ", "offsets": {"from": 400, "to": 400}},
                {"text": "好", "offsets": {"from": 350, "to": 500}},
            ],
            [
                {"text": "你", "offsets": {"from": 100, "to": 300}},
                {"text": " ", "offsets": {"from": 4000, "to": 4000}},
            ],
        )
        for tokens in invalid_tokens:
            source = json.dumps({"transcription": [{"tokens": tokens}]}, ensure_ascii=False)
            with self.subTest(tokens=tokens), self.assertRaises(TranscriptionError):
                parse_words_json(source, media_duration=3.0)

    def test_parser_uses_raw_offsets_to_identify_zero_duration_marker(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 0, "to": 100}},
            {
                "text": " ",
                "offsets": {
                    "from": 9007199254740992,
                    "to": 9007199254740993,
                },
            },
        ]}]}, ensure_ascii=False)

        with self.assertRaisesRegex(TranscriptionError, "empty whisper word"):
            parse_words_json(source, media_duration=10_000_000_000_000.0)

    def test_parser_rejects_whitespace_offsets_that_round_equal_as_floats(self) -> None:
        invalid_sources = (
            '{"transcription":[{"tokens":['
            '{"text":" ","offsets":{"from":0,"to":1e-324}},'
            '{"text":"你","offsets":{"from":100,"to":200}}]}]}',
            '{"transcription":[{"tokens":['
            '{"text":" ","offsets":{"from":1e-324,"to":0}},'
            '{"text":"你","offsets":{"from":100,"to":200}}]}]}',
            '{"transcription":[{"tokens":['
            '{"text":" ","offsets":{'
            '"from":100.000000000000001,"to":100.000000000000002}},'
            '{"text":"你","offsets":{"from":200,"to":300}}]}]}',
        )

        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(TranscriptionError):
                parse_words_json(source, media_duration=3.0)

    def test_parser_rejects_words_without_representable_float_duration(self) -> None:
        invalid_sources = (
            '{"transcription":[{"tokens":['
            '{"text":"你","offsets":{"from":0,"to":1e-324}}]}]}',
            '{"transcription":[{"tokens":['
            '{"text":"你","offsets":{'
            '"from":9007199254740992,"to":9007199254740993}}]}]}',
            '{"transcription":[{"tokens":['
            '{"text":"你","offsets":{'
            '"from":100.000000000000001,"to":100.000000000000002}}]}]}',
        )

        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(TranscriptionError):
                parse_words_json(source, media_duration=10_000_000_000_000.0)

    def test_parser_ignores_zero_duration_word_at_exact_media_boundary(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 0, "to": 100}},
            {"text": "AI", "offsets": {"from": 3000, "to": 3000}},
        ]}]}, ensure_ascii=False)

        words = parse_words_json(source, media_duration=3.0)

        self.assertEqual([Word("你", 0.0, 0.1)], words)

    def test_parser_projects_fractional_audio_boundary_to_whisper_milliseconds(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 0, "to": 100}},
            {"text": "AI", "offsets": {"from": 640440, "to": 640440}},
        ]}]}, ensure_ascii=False)

        words = parse_words_json(source, media_duration=640.437875)

        self.assertEqual([Word("你", 0.0, 0.1)], words)
        for invalid in (640430, 640450, 320000):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                TranscriptionError, "invalid whisper word timestamps",
            ):
                parse_words_json(
                    source.replace("640440", str(invalid)),
                    media_duration=640.437875,
                )

    def test_parser_rejects_zero_duration_words_away_from_exact_boundary(self) -> None:
        invalid_offsets = (
            {"from": 500, "to": 500},
            {"from": 3001, "to": 3001},
        )
        for offsets in invalid_offsets:
            source = json.dumps({"transcription": [{"tokens": [
                {"text": "你", "offsets": {"from": 0, "to": 100}},
                {"text": "AI", "offsets": offsets},
            ]}]}, ensure_ascii=False)
            with self.subTest(offsets=offsets), self.assertRaises(TranscriptionError):
                parse_words_json(source, media_duration=3.0)

    def test_parser_coalesces_zero_duration_prefix_into_following_word(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "用", "offsets": {"from": 361230, "to": 361440}},
            {"text": "数", "offsets": {"from": 362040, "to": 362040}},
            {"text": "字", "offsets": {"from": 362040, "to": 362040}},
            {"text": "化", "offsets": {"from": 362040, "to": 362040}},
            {"text": "变", "offsets": {"from": 362040, "to": 362400}},
        ]}]}, ensure_ascii=False)

        words = parse_words_json(source, media_duration=400.0)

        self.assertEqual([
            Word("用", 361.23, 361.44),
            Word("数字化变", 362.04, 362.4),
        ], words)

    def test_parser_truncates_quantized_tail_past_fractional_boundary(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "谢", "offsets": {"from": 640340, "to": 640400}},
            {"text": "观", "offsets": {"from": 640400, "to": 640460}},
            {"text": "看", "offsets": {"from": 640460, "to": 640520}},
            {"text": "欢", "offsets": {"from": 640520, "to": 640580}},
            {"text": "迎", "offsets": {"from": 640580, "to": 640640}},
        ]}]}, ensure_ascii=False)

        words = parse_words_json(source, media_duration=640.437875)

        self.assertEqual([
            Word("谢", 640.34, 640.4),
            Word("观", 640.4, 640.437875),
        ], words)

    def test_parser_drops_positive_word_starting_at_exact_boundary(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "前", "offsets": {"from": 2900, "to": 3000}},
            {"text": "尾", "offsets": {"from": 3000, "to": 3040}},
        ]}]}, ensure_ascii=False)

        words = parse_words_json(source, media_duration=3.0)

        self.assertEqual([Word("前", 2.9, 3.0)], words)

    def test_parser_rejects_boundary_word_only_transcript_as_no_words(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
            {"text": "AI", "offsets": {"from": 3000, "to": 3000}},
        ]}]}, ensure_ascii=False)

        with self.assertRaisesRegex(TranscriptionError, "whisper produced no words"):
            parse_words_json(source, media_duration=3.0)

    def test_parser_sanitizes_huge_whitespace_marker_offsets(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [{
            "text": " ", "offsets": {"from": 10**400, "to": 10**400},
        }]}]})

        with self.assertRaises(TranscriptionError) as captured:
            parse_words_json(source, media_duration=3.0)

        self.assertIsNone(captured.exception.__cause__)

    def test_parser_sanitizes_extreme_decimal_exponents(self) -> None:
        invalid_sources = (
            '{"transcription":[{"tokens":[{"text":"你","offsets":{'
            '"from":0,"to":1e999999999999999999999999999}}]}]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{'
            '"from":0,"to":1e-999999999999999999999999999}}]}]}',
        )

        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(TranscriptionError) as captured:
                    parse_words_json(source, media_duration=3.0)
                self.assertIsNone(captured.exception.__cause__)

    def test_parser_rejects_marker_only_transcript_as_no_words(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
            {"text": " ", "offsets": {"from": 100, "to": 100}},
        ]}]})

        with self.assertRaisesRegex(TranscriptionError, "whisper produced no words"):
            parse_words_json(source, media_duration=3.0)

    def test_parser_rejects_duplicate_nonfinite_bool_invalid_and_empty_words(self) -> None:
        invalid_sources = (
            '{"transcription":[],"transcription":[]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{"from":NaN,"to":2}}]}]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{"from":true,"to":2}}]}]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{"from":-1,"to":2}}]}]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{"from":500,"to":400}}]}]}',
            '{"transcription":[{"tokens":[{"text":"词","offsets":{"from":300,"to":300}}]}]}',
            '{"transcription":[{"tokens":[{"text":"你","offsets":{"from":4000,"to":4500}}]}]}',
            '{"transcription":[{"tokens":[{"text":" ","offsets":{"from":0,"to":100}}]}]}',
            '{"transcription":[{"tokens":[{"text":" ","offsets":{"from":0,"to":0}}]}]}',
            '{"transcription":[{"tokens":[{"text":" ","offsets":{"from":0}}]}]}',
            '{"transcription":[{"tokens":[{"text":" ","offsets":{"from":true,"to":true}}]}]}',
            '{"transcription":[]}',
        )
        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(TranscriptionError):
                parse_words_json(source, media_duration=3.0)

    def test_parser_rejects_word_timeline_regression(self) -> None:
        source = json.dumps({"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 500, "to": 700}},
            {"text": "好", "offsets": {"from": 400, "to": 600}},
        ]}]}, ensure_ascii=False)
        with self.assertRaises(TranscriptionError):
            parse_words_json(source, media_duration=3.0)

    def test_script_coverage_rejects_blank_script(self) -> None:
        with self.assertRaises(TranscriptionError):
            script_coverage(" \n", [Word("你", 0.0, 0.1)])

    def test_script_coverage_rejects_unvalidated_word_objects(self) -> None:
        invalid = (
            Word("", 0.0, 0.1),
            Word("你", True, 0.1),
            Word("你", 0.2, 0.1),
            Word("你", float("nan"), 0.1),
        )
        for word in invalid:
            with self.subTest(word=word), self.assertRaises(TranscriptionError):
                script_coverage("你", [word])

    def test_transcribe_command_is_local_fixed_and_cleans_partial(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        output = self.directory / "words.json"
        fixture = {"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 0, "to": 200}},
        ]}]}

        def fake_run(command, **kwargs):
            self.assertIs(subprocess.DEVNULL, kwargs["stdin"])
            self.assertIsNotNone(kwargs["timeout"])
            self.assertIn("-l", command)
            self.assertEqual(command[command.index("-l") + 1], "zh")
            self.assertIn("-ojf", command)
            self.assertIn("-of", command)
            self.assertFalse(any("http://" in item or "https://" in item for item in command))
            stem = Path(command[command.index("-of") + 1])
            Path(str(stem) + ".json").write_text(json.dumps(fixture), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with mock.patch("edit.hd.tools.transcribe.subprocess.run", side_effect=fake_run):
            words = transcribe_words(runtime, wav, output)
        self.assertEqual(["你"], [word.text for word in words])
        self.assertTrue(output.exists())
        self.assertFalse(any(path.name.endswith(".partial") for path in self.directory.iterdir()))

    def test_reference_language_is_forwarded_without_translation_or_fallback(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "english.wav"
        with wave.open(str(wav), "wb") as handle:
            handle.setnchannels(1)
            handle.setframerate(16000)
            handle.setsampwidth(2)
            handle.writeframes(b"\0\0" * 16000)
        output = self.directory / "english.json"

        def fake_run(command, **kwargs):
            self.assertEqual(command[command.index("-l") + 1], "en")
            self.assertNotIn("-tr", command)
            self.assertNotIn("--translate", command)
            stem = Path(command[command.index("-of") + 1])
            Path(str(stem) + ".json").write_text(json.dumps({"transcription": [{"tokens": [
                {"text": "Hello", "offsets": {"from": 0, "to": 200}},
            ]}]}))
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with mock.patch("edit.hd.tools.transcribe.subprocess.run", side_effect=fake_run) as run:
            self.assertEqual(transcribe_words(runtime, wav, output, language="en"), [Word("Hello", 0, .2)])
            self.assertEqual(run.call_count, 1)
        with mock.patch("edit.hd.tools.transcribe.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 1, b"", b"failure")) as run:
            with self.assertRaises(TranscriptionError):
                transcribe_words(runtime, wav, self.directory / "failed.json", language="en")
            self.assertEqual(run.call_count, 1)
        self.assertFalse((self.directory / "failed.json").exists())

    def test_reference_language_must_be_explicit_engine_code(self) -> None:
        runtime = self._runtime_files()
        with mock.patch("edit.hd.tools.transcribe.subprocess.run") as run:
            for language in (None, "", "auto", "EN", "en-US", "--translate", [], 1):
                with self.subTest(language=language), self.assertRaisesRegex(TranscriptionError, "explicit whisper language"):
                    transcribe_words(runtime, self.directory / "absent.wav",
                                     self.directory / "absent.json", language=language)
            run.assert_not_called()
        self.assertFalse((self.directory / "absent.json").exists())

    def test_transcribe_uses_source_duration_for_exact_boundary_token(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "padded.wav"
        with wave.open(str(wav), "wb") as handle:
            handle.setnchannels(1)
            handle.setframerate(16000)
            handle.setsampwidth(2)
            handle.writeframes(b"\0\0" * 480256)
        output = self.directory / "source-boundary.json"
        fixture = {"transcription": [{"tokens": [
            {"text": "部", "offsets": {"from": 29910, "to": 30000}},
            {"text": "AI", "offsets": {"from": 30000, "to": 30000}},
        ]}]}

        def fake_run(command, **_kwargs):
            stem = Path(command[command.index("-of") + 1])
            Path(str(stem) + ".json").write_text(
                json.dumps(fixture, ensure_ascii=False), encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=fake_run,
        ):
            words = transcribe_words(
                runtime, wav, output, source_media_duration=30.0,
            )

        self.assertEqual([Word("部", 29.91, 30.0)], words)

        with mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=fake_run,
        ), self.assertRaisesRegex(TranscriptionError, "invalid whisper word timestamps"):
            transcribe_words(runtime, wav, self.directory / "wav-boundary.json")

    def test_transcribe_reads_pinned_wav_not_swapped_path(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        expected = wav.read_bytes()
        foreign = self.directory / "foreign.wav"
        with wave.open(str(foreign), "wb") as handle:
            handle.setnchannels(1)
            handle.setframerate(16000)
            handle.setsampwidth(2)
            handle.writeframes(b"\x01\x00" * 16000)
        output = self.directory / "words-pinned.json"
        used: bytes | None = None

        def fake_run(command, **_kwargs):
            nonlocal used
            saved = self.directory / "speech.saved"
            os.replace(wav, saved)
            os.replace(foreign, wav)
            try:
                wav_arg = Path(command[command.index("-f") + 1])
                used = wav_arg.read_bytes()
                stem = Path(command[command.index("-of") + 1])
                Path(str(stem) + ".json").write_text(json.dumps({
                    "transcription": [{"tokens": [{
                        "text": "你", "offsets": {"from": 0, "to": 200},
                    }]}],
                }, ensure_ascii=False), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, b"", b"")
            finally:
                os.replace(wav, foreign)
                os.replace(saved, wav)

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=fake_run,
        ):
            words = transcribe_words(runtime, wav, output)
        descriptors_after = len(os.listdir("/dev/fd"))
        self.assertEqual(expected, used)
        self.assertEqual(["你"], [word.text for word in words])
        self.assertEqual(descriptors_before, descriptors_after)

    def test_transcribe_subprocess_error_has_no_sensitive_cause(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        output = self.directory / "words-error.json"
        with mock.patch(
            "edit.hd.tools.transcribe.subprocess.run",
            side_effect=OSError("/secret/subprocess failed"),
        ), self.assertRaises(TranscriptionError) as captured:
            transcribe_words(runtime, wav, output)
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn("/secret", str(captured.exception))

    def test_transcribe_cleanup_does_not_delete_unknown_json_replacement(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        output = self.directory / "words-unknown.json"
        valuable = self.directory / "valuable.json"
        valuable.write_bytes(b"must survive")

        def replace_generated_then_fail(command, **_kwargs):
            stem = Path(command[command.index("-of") + 1])
            generated = Path(str(stem) + ".json")
            generated.write_bytes(b"owned generated")
            os.replace(valuable, generated)
            raise TranscriptionError("primary whisper failed")

        with mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=replace_generated_then_fail,
        ), self.assertRaisesRegex(TranscriptionError, "primary whisper failed"):
            transcribe_words(runtime, wav, output)
        replacements = [
            path for path in self.directory.iterdir()
            if path.name.endswith(".json") and path.read_bytes() == b"must survive"
        ]
        self.assertEqual(1, len(replacements))

    def test_transcribe_rejects_symlink_output_directory_before_execution(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        outside = self.directory / "outside"
        outside.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with mock.patch("edit.hd.tools.transcribe.subprocess.run") as run, self.assertRaises(
            TranscriptionError
        ):
            transcribe_words(runtime, wav, alias / "words.json")
        run.assert_not_called()

    def test_transcribe_sanitizes_output_publication_error(self) -> None:
        runtime = self._runtime_files()
        wav = self.directory / "speech.wav"
        extract_pcm16k(self.video, wav)
        output = self.directory / "words.json"
        fixture = {"transcription": [{"tokens": [
            {"text": "你", "offsets": {"from": 0, "to": 200}},
        ]}]}

        def fake_run(command, **_kwargs):
            stem = Path(command[command.index("-of") + 1])
            Path(str(stem) + ".json").write_text(json.dumps(fixture), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        real_replace = os.replace

        def fail_final_replace(source, target):
            if Path(target) == output:
                raise OSError("/secret/transcript publication failed")
            return real_replace(source, target)

        with mock.patch(
            "edit.hd.tools.transcribe.subprocess.run", side_effect=fake_run,
        ), mock.patch(
            "edit.hd.tools.transcribe.os.replace", side_effect=fail_final_replace,
        ):
            with self.assertRaises(TranscriptionError) as captured:
                transcribe_words(runtime, wav, output)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertFalse(output.exists())

    def test_missing_runtime_blocks_job_without_fake_timestamps_or_path_leak(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        report = job.job_dir / "inspect.json"
        report.write_text("{}\n", encoding="utf-8")
        mark_ready(job, "inspect", [report])
        approve(job, "inspect")
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime",
            side_effect=TranscriptionError("/secret/model is unavailable"),
        ):
            self.assertIsNone(transcribe_job(job))
        stage = job.stages["speech_cleanup"]
        self.assertEqual("blocked", stage["status"])
        self.assertEqual([], stage["artifacts"])
        self.assertEqual(0, stage["ai_attempts"])
        self.assertNotIn("/secret", stage["reason"])
        self.assertFalse((job.job_dir / "02-speech-cleanup" / "words.json").exists())

    def test_runtime_discovery_interrupt_is_sanitized(self) -> None:
        root = self.directory / "repo-runtime-interrupt"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime",
            side_effect=KeyboardInterrupt("/secret/runtime interrupted"),
        ), self.assertRaises(TranscriptionError) as captured:
            transcribe_job(job)
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn("/secret", str(captured.exception))

    def test_successful_job_freezes_coverage_and_only_marks_ready(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好世界", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()
        words = [Word("你", 0.0, 0.2), Word("好", 0.2, 0.4), Word("世界", 0.4, 0.8)]
        media_duration: float | None = None

        def fake_transcribe(_runtime, _wav, output, **kwargs):
            nonlocal media_duration
            media_duration = kwargs.get("source_media_duration")
            output.write_text('{"transcription":[]}\n', encoding="utf-8")
            return words

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ):
            report_path = transcribe_job(job)
        descriptors_after = len(os.listdir("/dev/fd"))

        self.assertIsNotNone(report_path)
        self.assertEqual(descriptors_before, descriptors_after)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(1.0, payload["script"]["coverage"])
        self.assertEqual(3, payload["transcript"]["word_count"])
        self.assertEqual(3.0, media_duration)
        self.assertEqual("ready_for_review", job.stages["speech_cleanup"]["status"])
        self.assertNotEqual("approved", job.stages["speech_cleanup"]["status"])

    def test_job_uses_audio_duration_when_video_track_is_longer(self) -> None:
        root = self.directory / "repo-shorter-audio"
        root.mkdir()
        video = root / "source.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.9",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(video),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        report = json.loads(
            (job.job_dir / "01-inspect/report.json").read_text(encoding="utf-8"),
        )
        self.assertGreater(report["video"]["duration"], report["audio"]["duration"])
        runtime = self._runtime_files()
        media_duration: float | None = None

        def fake_transcribe(_runtime, _wav, output, **kwargs):
            nonlocal media_duration
            media_duration = kwargs.get("source_media_duration")
            output.write_text('{"transcription":[]}\n', encoding="utf-8")
            return [Word("你好", 0.0, 0.5)]

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ):
            transcribe_job(job)

        self.assertEqual(report["audio"]["duration"], media_duration)

    def test_job_rejects_legacy_report_that_used_container_duration_for_audio(self) -> None:
        root = self.directory / "repo-legacy-container-duration"
        root.mkdir()
        video = root / "source.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.9",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(video),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        payload = inspect_inputs(video, script)
        payload["video"].update(job.inputs["video"])
        payload["script"] = job.inputs["script"].copy()
        payload["audio"]["duration"] = payload["video"]["duration"]
        report = job.job_dir / "01-inspect/report.json"
        report.parent.mkdir()
        report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        mark_ready(job, "inspect", [report])
        approve(job, "inspect")
        runtime = self._runtime_files()

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words",
        ) as transcribe, self.assertRaisesRegex(
            TranscriptionError, "invalid inspect report",
        ):
            transcribe_job(job)

        transcribe.assert_not_called()

    def test_job_rejects_inspect_report_not_bound_to_input_and_closes_fds(self) -> None:
        root = self.directory / "repo-invalid-inspect"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        report = job.job_dir / "01-inspect/report.json"
        report.parent.mkdir()
        report.write_text(json.dumps({
            "version": 1,
            "streams": {"video": 1, "audio": 1},
            "video": {
                "path": "wrong.mp4",
                "sha256": job.inputs["video"]["sha256"],
                "bytes": job.inputs["video"]["bytes"],
                "codec": "h264",
                "duration": 3.0,
                "fps": 24.0,
                "width": 320,
                "height": 240,
            },
            "audio": {
                "codec": "aac",
                "duration": 3.0,
                "sample_rate": 48000,
                "channels": 1,
            },
            "script": job.inputs["script"],
        }, ensure_ascii=False), encoding="utf-8")
        mark_ready(job, "inspect", [report])
        approve(job, "inspect")
        runtime = self._runtime_files()

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words",
        ) as transcribe, self.assertRaisesRegex(
            TranscriptionError, "invalid inspect report",
        ):
            transcribe_job(job)
        descriptors_after = len(os.listdir("/dev/fd"))

        transcribe.assert_not_called()
        self.assertEqual(descriptors_before, descriptors_after)

    def test_job_rejects_inspect_report_inode_drift_and_closes_fds(self) -> None:
        root = self.directory / "repo-inspect-drift"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        report = job.job_dir / "01-inspect/report.json"
        runtime = self._runtime_files()
        from edit.hd.tools import transcribe as module
        real_read = module._read_descriptor_text
        read_count = 0

        def replace_report_after_read(descriptor):
            nonlocal read_count
            read_count += 1
            source = real_read(descriptor)
            if read_count == 2:
                original = report.with_name("original-report.json")
                os.replace(report, original)
                report.write_bytes(original.read_bytes())
            return source

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe._read_descriptor_text",
            side_effect=replace_report_after_read,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words",
        ) as transcribe, self.assertRaisesRegex(
            TranscriptionError, "invalid inspect report",
        ):
            transcribe_job(job)
        descriptors_after = len(os.listdir("/dev/fd"))

        transcribe.assert_not_called()
        self.assertEqual(descriptors_before, descriptors_after)

    def test_job_sanitizes_model_disappearance_after_transcription(self) -> None:
        root = self.directory / "repo-model-disappears"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()

        def disappear(_runtime, _wav, output, **_kwargs):
            output.write_text("{}\n", encoding="utf-8")
            runtime.model.unlink()
            return [Word("你好", 0.0, 0.5)]

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=disappear,
        ), self.assertRaises(TranscriptionError) as captured:
            transcribe_job(job)
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn(str(runtime.model), str(captured.exception))

    def test_job_sanitizes_model_hash_io_error(self) -> None:
        root = self.directory / "repo-model-hash"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe._sha256",
            side_effect=OSError("/secret/model hash failed"),
        ), self.assertRaises(TranscriptionError) as captured:
            transcribe_job(job)
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn("/secret", str(captured.exception))

    def test_job_runs_whisper_with_pinned_model_not_swapped_path(self) -> None:
        root = self.directory / "repo-model-pin"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()
        foreign = self.directory / "foreign-model.bin"
        foreign.write_bytes(b"FOREIGN model")
        from edit.hd.tools import transcribe as module
        real_run = module._run
        model_used: bytes | None = None

        def run_with_model_swap(command, **kwargs):
            nonlocal model_used
            if command[0] == "ffmpeg":
                return real_run(command, **kwargs)
            saved = self.directory / "model.saved"
            os.replace(runtime.model, saved)
            os.replace(foreign, runtime.model)
            try:
                model_arg = Path(command[command.index("-m") + 1])
                model_used = model_arg.read_bytes()
                stem = Path(command[command.index("-of") + 1])
                Path(str(stem) + ".json").write_text(json.dumps({
                    "transcription": [{"tokens": [{
                        "text": "你好", "offsets": {"from": 0, "to": 500},
                    }]}],
                }, ensure_ascii=False), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, b"", b"")
            finally:
                os.replace(runtime.model, foreign)
                os.replace(saved, runtime.model)

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=run_with_model_swap,
        ):
            report_path = transcribe_job(job)
        self.assertEqual(b"model", model_used)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(b"model").hexdigest(),
            payload["runtime"]["model_sha256"],
        )

    def test_job_reads_script_from_pinned_input_not_swapped_path(self) -> None:
        root = self.directory / "repo-script-pin"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        foreign = root / "foreign.txt"
        foreign.write_text("再见", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()
        from edit.hd.tools import transcribe as module
        real_read_descriptor = module._read_descriptor_text

        def swap_only_during_pinned_read(descriptor):
            saved = root / "script.saved"
            os.replace(script, saved)
            os.replace(foreign, script)
            try:
                return real_read_descriptor(descriptor)
            finally:
                os.replace(script, foreign)
                os.replace(saved, script)

        def fake_transcribe(_runtime, _wav, output, **_kwargs):
            output.write_text("{}\n", encoding="utf-8")
            return [Word("再见", 0.0, 0.5)]

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ), mock.patch(
            "edit.hd.tools.transcribe._read_descriptor_text",
            side_effect=swap_only_during_pinned_read,
        ):
            report_path = transcribe_job(job)
        descriptors_after = len(os.listdir("/dev/fd"))
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(descriptors_before, descriptors_after)
        self.assertEqual(0.0, payload["script"]["coverage"])
        self.assertEqual(job.inputs["script"]["sha256"], payload["script"]["sha256"])

    def test_job_decodes_video_from_pinned_fd_not_swapped_path(self) -> None:
        root = self.directory / "repo-video-pin"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        foreign = root / "foreign.mp4"
        foreign.write_bytes(make_video_only_fixture(self.directory).read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()
        from edit.hd.tools import transcribe as module
        real_run = module._run
        swapped = False

        def swap_during_ffmpeg(command, **kwargs):
            nonlocal swapped
            if command[0] != "ffmpeg" or swapped:
                return real_run(command, **kwargs)
            swapped = True
            saved = root / "source.saved"
            os.replace(video, saved)
            os.replace(foreign, video)
            try:
                return real_run(command, **kwargs)
            finally:
                os.replace(video, foreign)
                os.replace(saved, video)

        def fake_transcribe(_runtime, wav, output, **_kwargs):
            with wave.open(str(wav), "rb") as handle:
                self.assertGreater(handle.getnframes(), 0)
            output.write_text("{}\n", encoding="utf-8")
            return [Word("你好", 0.0, 0.5)]

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ), mock.patch(
            "edit.hd.tools.transcribe._run", side_effect=swap_during_ffmpeg,
        ):
            report_path = transcribe_job(job)
        descriptors_after = len(os.listdir("/dev/fd"))
        self.assertTrue(swapped)
        self.assertEqual(descriptors_before, descriptors_after)
        self.assertTrue(report_path.exists())

    def test_job_preserves_artifacts_if_ready_state_committed_before_error(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()

        def fake_transcribe(_runtime, _wav, output, **_kwargs):
            output.write_text("{}\n", encoding="utf-8")
            return [Word("你好", 0.0, 0.5)]

        def committed_then_error(current, _stage, _artifacts):
            current.stages["speech_cleanup"]["status"] = "ready_for_review"
            raise RuntimeError("cleanup pending")

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ), mock.patch(
            "edit.hd.tools.transcribe.mark_ready", side_effect=committed_then_error,
        ), self.assertRaises(RuntimeError):
            transcribe_job(job)
        output_dir = job.job_dir / "02-speech-cleanup"
        self.assertTrue((output_dir / "speech-16k.wav").exists())
        self.assertTrue((output_dir / "whisper.json").exists())
        self.assertTrue((output_dir / "report.json").exists())

    def test_revised_transcription_replaces_all_three_artifacts_as_one_generation(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好世界", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        self._approve_inspect(job)
        runtime = self._runtime_files()
        run_number = 0

        def fake_transcribe(_runtime, _wav, output, **_kwargs):
            nonlocal run_number
            run_number += 1
            output.write_text(json.dumps({"run": run_number}) + "\n", encoding="utf-8")
            return [Word("你好世界" if run_number == 1 else "你好", 0.0, 0.5)]

        with mock.patch(
            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
        ), mock.patch(
            "edit.hd.tools.transcribe.transcribe_words", side_effect=fake_transcribe,
        ):
            first_report = transcribe_job(job)
            output = job.job_dir / "02-speech-cleanup"
            first = {name: (output / name).read_bytes() for name in (
                "speech-16k.wav", "whisper.json", "report.json",
            )}
            revise(job, "speech_cleanup", "重新转写")
            second_report = transcribe_job(job)

        self.assertEqual(first_report, second_report)
        self.assertNotEqual(first["whisper.json"], (output / "whisper.json").read_bytes())
        self.assertNotEqual(first["report.json"], (output / "report.json").read_bytes())
        self.assertGreater((output / "speech-16k.wav").stat().st_size, 0)
        self.assertEqual("ready_for_review", job.stages["speech_cleanup"]["status"])
        self.assertFalse(any("generation" in path.name for path in job.job_dir.iterdir()))

    def test_mark_ready_failure_cleanup_matrix_restores_old_generation(self) -> None:
        from edit.hd.tools import inspect_inputs as inspect_module

        for failure_type in (OSError, KeyboardInterrupt):
            for timing in ("pre", "post"):
                for position in range(3):
                    with self.subTest(
                        failure=failure_type.__name__, timing=timing, position=position,
                    ):
                        case = self.directory / f"{failure_type.__name__}-{timing}-{position}"
                        root = case / "repo"
                        root.mkdir(parents=True)
                        video = root / "source.mp4"
                        video.write_bytes(self.video.read_bytes())
                        script = root / "script.txt"
                        script.write_text("你好", encoding="utf-8")
                        job = create_job(root, video, script, profile="legacy-v1")
                        self._approve_inspect(job)
                        runtime = self._runtime_files()
                        run_number = 0

                        def fake_transcribe(_runtime, _wav, output, **_kwargs):
                            nonlocal run_number
                            run_number += 1
                            output.write_text(
                                json.dumps({"run": run_number}) + "\n", encoding="utf-8",
                            )
                            return [Word("你好", 0.0, 0.5)]

                        with mock.patch(
                            "edit.hd.tools.transcribe.discover_runtime", return_value=runtime,
                        ), mock.patch(
                            "edit.hd.tools.transcribe.transcribe_words",
                            side_effect=fake_transcribe,
                        ):
                            transcribe_job(job)
                            stable = job.job_dir / "02-speech-cleanup"
                            old_generation = {
                                name: (stable / name).read_bytes()
                                for name in (
                                    "speech-16k.wav", "whisper.json", "report.json",
                                )
                            }
                            revise(job, "speech_cleanup", "重新转写")
                            real_unlink = inspect_module.os.unlink
                            cleanup_call = 0
                            injected = False

                            def failing_unlink(candidate):
                                nonlocal cleanup_call, injected
                                candidate = Path(candidate)
                                is_generation_file = (
                                    candidate.parent.name.startswith(
                                        ".02-speech-cleanup.generation."
                                    )
                                    and candidate.parent.name.endswith(".stage")
                                )
                                if is_generation_file:
                                    current = cleanup_call
                                    cleanup_call += 1
                                    if current == position and not injected:
                                        injected = True
                                        if timing == "post":
                                            real_unlink(candidate)
                                        raise failure_type("/secret/cleanup failed")
                                return real_unlink(candidate)

                            descriptors_before = len(os.listdir("/dev/fd"))
                            with mock.patch(
                                "edit.hd.tools.transcribe.mark_ready",
                                side_effect=RuntimeError("state publication failed"),
                            ), mock.patch(
                                "edit.hd.tools.inspect_inputs.os.unlink",
                                side_effect=failing_unlink,
                            ):
                                with self.assertRaises(BaseException) as captured:
                                    transcribe_job(job)
                            descriptors_after = len(os.listdir("/dev/fd"))

                            self.assertTrue(injected)
                            self.assertNotIn("/secret", str(captured.exception))
                            self.assertEqual(descriptors_before, descriptors_after)
                            self.assertEqual(
                                "needs_revision", job.stages["speech_cleanup"]["status"],
                            )
                            self.assertEqual(
                                old_generation,
                                {name: (stable / name).read_bytes() for name in old_generation},
                            )
                            retried = transcribe_job(job)
                            self.assertTrue(retried.exists())
                            self.assertEqual(
                                "ready_for_review",
                                job.stages["speech_cleanup"]["status"],
                            )


if __name__ == "__main__":
    unittest.main()

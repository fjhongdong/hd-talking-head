from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import wave
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from edit.hd.tests.media_fixture import make_av_fixture
from edit.hd.tools.state import WorkflowError, create_job
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

    def test_parser_ignores_valid_whitespace_but_rejects_empty_or_invalid_tokens(self) -> None:
        cases = (
            (" ", 70470, 70470, True),
            (" ", 70470, 70480, True),
            ("", 70470, 70470, False),
            ("", 70470, 70480, False),
            (" ", True, 70480, False),
            (" ", 70480, 70470, False),
            (" ", 69810, 70480, False),
            (" ", 70470, 72500, False),
        )
        for text, start, end, valid in cases:
            source = json.dumps({"transcription": [{"tokens": [
                {"text": "查", "offsets": {"from": 69820, "to": 70440}},
                {"text": text, "offsets": {"from": start, "to": end}},
                {"text": "写", "offsets": {"from": 70480, "to": 71080}},
            ]}]}, ensure_ascii=False)
            with self.subTest(text=text, start=start, end=end):
                if valid:
                    self.assertEqual(
                        [Word("查", 69.82, 70.44), Word("写", 70.48, 71.08)],
                        parse_words_json(source, media_duration=72.42),
                    )
                else:
                    with self.assertRaises(TranscriptionError):
                        parse_words_json(source, media_duration=72.42)

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

    def test_current_job_requires_external_result_and_invocation_without_local_fallback(self) -> None:
        from edit.hd.tools import speech_edit_v2
        job = SimpleNamespace(version=2)
        with mock.patch("edit.hd.tools.transcribe.discover_runtime") as local_runtime:
            for inputs in ({}, {"video_use_result": self.directory / "result.json"},
                           {"invocation": {"exit_code": 0}}):
                with self.subTest(inputs=inputs), self.assertRaisesRegex(
                    speech_edit_v2.SpeechEditV2Error, "result and invocation evidence"):
                    transcribe_job(job, **inputs)
        local_runtime.assert_not_called()

    def test_current_job_delegates_exact_result_and_invocation(self) -> None:
        job = SimpleNamespace(version=2)
        result = self.directory / "scribe.json"
        invocation = {"source_sha256": "a" * 64}
        output = self.directory / "report.json"
        with mock.patch("edit.hd.tools.speech_edit_v2.prepare_transcription", return_value=output) as prepare:
            self.assertEqual(transcribe_job(job, video_use_result=result, invocation=invocation), output)
        prepare.assert_called_once_with(job, video_use_result=result, invocation=invocation)

    def test_removed_job_profile_is_rejected_before_creating_outputs(self) -> None:
        script = self.directory / "script.txt"
        script.write_text("你好", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "unsupported workflow profile"):
            create_job(self.directory, self.video, script, profile="legacy-v1")
        self.assertFalse((self.directory / "edit").exists())

    def test_bound_scribe_result_keeps_words_and_audio_duration(self) -> None:
        from edit.hd.tools import speech_edit_v2
        result = self.directory / "scribe.json"
        result.write_text(json.dumps({"words": [
            {"type": "word", "text": "你好", "start": .1, "end": .8},
        ]}, ensure_ascii=False), encoding="utf-8")
        original = result.read_bytes()
        entrypoint = self.directory / "transcribe.py"
        job = SimpleNamespace(inputs={"video": {"sha256": "a" * 64}})
        invocation = {"entrypoint": str(entrypoint), "exit_code": 0,
                      "source_sha256": "a" * 64,
                      "result_sha256": hashlib.sha256(original).hexdigest()}
        with mock.patch.object(speech_edit_v2, "_video_use_entrypoint", return_value=entrypoint):
            words, runtime = speech_edit_v2._transcribe_with_video_use(job, result, invocation, .9)
            self.assertEqual(words, [Word("你好", .1, .8)])
            self.assertEqual(runtime["invocation"], invocation)
            with self.assertRaisesRegex(speech_edit_v2.SpeechEditV2Error, "timestamp"):
                speech_edit_v2._transcribe_with_video_use(job, result, invocation, .5)
        self.assertEqual(result.read_bytes(), original)

    def test_scribe_invocation_rejects_wrong_source_result_launcher_or_exit(self) -> None:
        from edit.hd.tools import speech_edit_v2
        result = self.directory / "scribe.json"
        result.write_text('{"words":[{"type":"word","text":"你好","start":0.1,"end":0.8}]}', encoding="utf-8")
        entrypoint = self.directory / "transcribe.py"
        job = SimpleNamespace(inputs={"video": {"sha256": "a" * 64}})
        invocation = {"entrypoint": str(entrypoint), "exit_code": 0,
                      "source_sha256": "a" * 64,
                      "result_sha256": hashlib.sha256(result.read_bytes()).hexdigest()}
        for key, invalid in (("entrypoint", str(self.directory / "other.py")),
                             ("exit_code", 1), ("source_sha256", "b" * 64),
                             ("result_sha256", "c" * 64)):
            with self.subTest(field=key), mock.patch.object(
                speech_edit_v2, "_video_use_entrypoint", return_value=entrypoint
            ), self.assertRaisesRegex(speech_edit_v2.SpeechEditV2Error, "does not match"):
                speech_edit_v2._transcribe_with_video_use(job, result, {**invocation, key: invalid}, 1.)


if __name__ == "__main__":
    unittest.main()

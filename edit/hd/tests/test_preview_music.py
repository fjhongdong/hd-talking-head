"""Real audio tests for the unpublished BGM mixing primitive, not Job delivery."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from edit.hd.tools import preview_music


OPTIONS = {
    "voice_gain_db": 0, "music_gain_db": -12,
    "fade_in_frames": 12, "fade_out_frames": 12,
    "duck_threshold": 0.03, "duck_ratio": 8,
    "duck_attack_ms": 5, "duck_release_ms": 150,
}


def run(command):
    return subprocess.run(command, check=True, capture_output=True, timeout=60)


def samples(path):
    return np.frombuffer(run([
        "ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
        "-map", "0:a:0", "-f", "f32le", "-ac", "2", "-ar", "48000", "pipe:1",
    ]).stdout, dtype=np.float32).reshape(-1, 2)


class MusicMixTests(unittest.TestCase):
    def test_continuous_loop_keeps_start_and_crossfades_every_seam(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source, output = root / "ramp.wav", root / "continuous.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "aevalsrc=-0.4+0.4*t:s=48000:d=2", "-ac", "2",
                 "-c:a", "pcm_f32le", str(source)])
            self.assertTrue(hasattr(preview_music, "prepare_continuous_music"),
                            "continuous music preparation is missing")
            preview_music.prepare_continuous_music(source, output, frames=144,
                start_frame=6, end_frame=48, crossfade_frames=6)
            actual, original = samples(output), samples(source)
            self.assertEqual(actual.shape, (288000, 2))
            np.testing.assert_allclose(actual[:12000], original[12000:24000], atol=1e-6)
            self.assertLess(float(np.max(np.abs(np.diff(actual[:, 0])))), .001)
            before = output.read_bytes()
            with self.assertRaises(preview_music.MusicError):
                preview_music.prepare_continuous_music(source, output, frames=144,
                    start_frame=6, end_frame=48, crossfade_frames=6)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(set(p.name for p in root.iterdir()), {"ramp.wav", "continuous.wav"})

    def test_continuous_music_short_target_is_exact_crop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source, output = root / "source.wav", root / "crop.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=duration=2:sample_rate=48000", "-ac", "2", str(source)])
            self.assertTrue(hasattr(preview_music, "prepare_continuous_music"))
            preview_music.prepare_continuous_music(source, output, frames=13,
                start_frame=3, end_frame=48, crossfade_frames=6)
            np.testing.assert_allclose(samples(output), samples(source)[6000:32000], atol=1e-6)

    def test_continuous_music_rejects_invalid_clocks(self):
        self.assertTrue(hasattr(preview_music, "prepare_continuous_music"))
        base = dict(frames=144, start_frame=0, end_frame=48, crossfade_frames=6)
        for changes in ({"frames": True}, {"frames": 0}, {"start_frame": -1},
                        {"end_frame": 0}, {"crossfade_frames": 0}, {"crossfade_frames": 25}):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    preview_music.MusicError, "invalid continuous music frame range or crossfade"):
                preview_music.prepare_continuous_music(Path("missing.wav"), Path("unused.wav"),
                    **{**base, **changes})

    def test_invalid_parameters_fail_before_media_work(self):
        changes = [{"music_gain_db": True}, {"music_gain_db": float("nan")},
                   {"voice_gain_db": float("inf")}, {"fade_in_frames": -1},
                   {"fade_out_frames": 145}, {"duck_ratio": 0},
                   {"duck_attack_ms": 0}, {"duck_release_ms": "150"},
                   {"duck_threshold": 0}, {"unexpected": 1}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(preview_music.MusicError):
                preview_music.validate_mix_options({**OPTIONS, **change}, frames=144)
        for frames in (True, 0, 1.5):
            with self.subTest(frames=frames), self.assertRaises(preview_music.MusicError):
                preview_music.validate_mix_options(OPTIONS, frames=frames)

    def test_actual_mix_preserves_voice_and_ducks_only_music(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            voice, music = root / "voice.wav", root / "music.wav"
            # Voice speaks during body seconds 1..3; an approved opening adds 0.5 s.
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "aevalsrc=0.3*sin(2*PI*440*t)*between(t\\,1\\,3):s=48000:d=5.5",
                 "-ac", "2", "-c:a", "pcm_f32le", str(voice)])
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "aevalsrc=0.2*sin(2*PI*880*t):s=48000:d=6",
                 "-ac", "2", "-c:a", "pcm_f32le", str(music)])
            mixed, stem = root / "mix.wav", root / "music-audit.wav"
            command = preview_music.build_mix_command(
                voice, music, mixed, stem, frames=144, voice_offset_frames=12, options=OPTIONS)
            run(command)
            result, audit, original = samples(mixed), samples(stem), samples(voice)
            self.assertEqual(result.shape, (288000, 2))
            self.assertEqual(audit.shape, result.shape)
            aligned = np.pad(original, ((24000, 0), (0, 0)))
            np.testing.assert_allclose(result - audit, aligned, atol=1e-6)
            rms = lambda start, end: float(np.sqrt(np.mean(audit[int(start*48000):int(end*48000)]**2)))
            self.assertGreater(rms(4.5, 5), 0.02)
            self.assertLess(rms(2, 3), rms(4.5, 5) * 0.4)
            self.assertLess(rms(0, .05), rms(4.5, 5) * .15)
            self.assertLess(rms(5.95, 6), rms(4.5, 5) * .15)
            report = preview_music.measure_audio(mixed)
            self.assertTrue(-60 < report["integrated_lufs"] < 0)
            self.assertLess(report["true_peak_dbtp"], -1)
            info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(mixed)]).stdout)
            self.assertEqual(len(info["streams"]), 1)
            self.assertEqual(info["streams"][0]["channels"], 2)
            encoded = root / "mixed.m4a"
            run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(mixed),
                 "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", str(encoded)])
            encoded_report = preview_music.measure_audio(encoded)
            self.assertLess(encoded_report["true_peak_dbtp"], -1)
            self.assertLess(abs(encoded_report["integrated_lufs"] - report["integrated_lufs"]), .5)
            decoded = samples(encoded)
            # No voice in this interval: verify actual encoded music, not just metadata.
            self.assertGreater(float(np.sqrt(np.mean(decoded[216000:240000]**2))), .02)
            before = mixed.read_bytes()
            with self.assertRaises(preview_music.MusicError):
                preview_music.build_mix_command(voice, music, mixed, stem,
                    frames=144, voice_offset_frames=12, options=OPTIONS)
            self.assertEqual(mixed.read_bytes(), before)

    def test_mono_requires_explicit_upstream_conversion_not_hidden_gain_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "mono.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=duration=6:sample_rate=48000", str(source)])
            with self.assertRaisesRegex(preview_music.MusicError, "stereo"):
                preview_music.build_mix_command(source, source, root / "mix.wav", root / "audit.wav",
                    frames=144, voice_offset_frames=0, options=OPTIONS)

    def test_silent_audio_does_not_pass_measurement(self):
        with tempfile.TemporaryDirectory() as temp:
            silent = Path(temp).resolve() / "silent.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "anullsrc=r=48000:cl=stereo", "-t", "4", str(silent)])
            with self.assertRaises(preview_music.MusicError):
                preview_music.measure_audio(silent)

    def test_resampling_gain_and_partial_final_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "stereo-44100.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=duration=1:sample_rate=44100", "-ac", "2", str(source)])
            mixed, audit = root / "mix.wav", root / "audit.wav"
            opts = {**OPTIONS, "voice_gain_db": 6, "fade_in_frames": 2, "fade_out_frames": 2}
            run(preview_music.build_mix_command(source, source, mixed, audit,
                frames=13, voice_offset_frames=0, options=opts))
            actual = samples(mixed) - samples(audit)
            self.assertEqual(len(actual), 26000)
            np.testing.assert_allclose(actual, samples(source)[:26000] * (10**(6/20)), atol=2e-6)

    def test_output_aliases_and_symlinks_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "source.wav"
            source.write_bytes(b"not decoded for path checks")
            link = root / "alias.wav"
            link.symlink_to(source)
            for output, audit in ((source, root / "audit.wav"), (link, root / "audit.wav"),
                                  (root / "same.wav", root / "same.wav")):
                with self.subTest(output=output), self.assertRaises(preview_music.MusicError):
                    preview_music.build_mix_command(source, source, output, audit,
                        frames=144, voice_offset_frames=0, options=OPTIONS)
            self.assertEqual(source.read_bytes(), b"not decoded for path checks")
            self.assertFalse((root / "audit.wav").exists())

    def test_short_music_cannot_silently_leave_the_ending_unscored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "short.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=duration=1", "-ac", "2", str(source)])
            with self.assertRaisesRegex(preview_music.MusicError, "cover"):
                preview_music.build_mix_command(source, source, root / "mix.wav", root / "audit.wav",
                    frames=144, voice_offset_frames=0, options=OPTIONS)

    def test_one_missing_decoded_sample_is_not_accepted_as_probe_rounding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "one-sample-short.wav"
            run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=duration=1:sample_rate=48000", "-af", "atrim=end_sample=25999",
                 "-ac", "2", str(source)])
            with self.assertRaisesRegex(preview_music.MusicError, "cover"):
                preview_music.build_mix_command(source, source, root / "mix.wav", root / "audit.wav",
                    frames=13, voice_offset_frames=0,
                    options={**OPTIONS, "fade_in_frames": 2, "fade_out_frames": 2})


if __name__ == "__main__":
    unittest.main()

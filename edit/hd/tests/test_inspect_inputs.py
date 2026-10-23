from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from edit.hd.tests.media_fixture import (
    assert_complete_decode,
    make_av_fixture,
    make_video_only_fixture,
)
from edit.hd.tools.inspect_inputs import (
    GenerationRecoveryError,
    InspectionError,
    inspect_inputs,
    inspect_job,
)
from edit.hd.tools.state import WorkflowError, create_job, revise


class InspectInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_tmp = tempfile.TemporaryDirectory()
        directory = Path(cls.fixture_tmp.name).resolve()
        cls.video = make_av_fixture(directory)
        cls.video_only = make_video_only_fixture(directory)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_tmp.cleanup()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name).resolve()
        self.script = self.directory / "script.txt"
        self.script.write_text("你好，这是 HD 口播。\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_real_fixture_is_strict_1v1a_and_fully_decodable(self) -> None:
        report = inspect_inputs(self.video, self.script)
        self.assertEqual({"video": 1, "audio": 1}, report["streams"])
        self.assertEqual((1080, 1920, 24), (
            report["video"]["width"], report["video"]["height"],
            report["video"]["fps"],
        ))
        self.assertEqual(48000, report["audio"]["sample_rate"])
        self.assertEqual(2, report["audio"]["channels"])
        self.assertEqual("1:1", report["video"]["sample_aspect_ratio"])
        self.assertEqual("9:16", report["video"]["display_aspect_ratio"])
        assert_complete_decode(self.video)

    def test_fresh_job_can_publish_into_precreated_empty_stage_directory(self) -> None:
        video = self.directory / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        job = create_job(self.directory, video, self.script, profile="full-v2")
        target = job.job_dir / "01-inspect"
        target.mkdir()
        inspect_job(job)
        self.assertTrue((target / "report.json").is_file())
        self.assertEqual(job.stages["inspect"]["status"], "ready_for_review")

    def test_precreated_stage_with_unknown_file_is_preserved(self) -> None:
        video = self.directory / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        job = create_job(self.directory, video, self.script, profile="full-v2")
        target = job.job_dir / "01-inspect"
        target.mkdir()
        marker = target / "user-notes.md"
        marker.write_text("preserve this input", encoding="utf-8")
        with self.assertRaises(GenerationRecoveryError):
            inspect_job(job)
        self.assertEqual(marker.read_text(), "preserve this input")

    def test_legacy_inspect_keeps_its_single_report_contract(self) -> None:
        video = self.directory / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        job = create_job(self.directory, video, self.script, profile="legacy-v1")

        inspect_job(job)

        self.assertEqual(
            {item["path"] for item in job.stages["inspect"]["artifacts"]},
            {"01-inspect/report.json"},
        )
        self.assertFalse((job.job_dir / "01-inspect/material-usage.json").exists())

    def test_report_preserves_non_square_pixel_display_aspect_ratio(self) -> None:
        video = self.directory / "non-square-pixels.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x320:r=24:d=0.25",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "0.25", "-map", "0:v:0", "-map", "1:a:0",
                "-vf", "setsar=9/16", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        report = inspect_inputs(video, self.script)

        self.assertEqual((320, 320), (
            report["video"]["width"], report["video"]["height"],
        ))
        self.assertEqual("9:16", report["video"]["sample_aspect_ratio"])
        self.assertEqual("9:16", report["video"]["display_aspect_ratio"])

    def test_report_preserves_distinct_video_and_audio_stream_durations(self) -> None:
        video = self.directory / "shorter-audio.mp4"
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

        report = inspect_inputs(video, self.script)

        self.assertEqual(3.0, report["video"]["duration"])
        self.assertLess(report["audio"]["duration"], report["video"]["duration"])

    def test_report_reads_matroska_stream_tag_durations(self) -> None:
        video = self.directory / "shorter-audio.mkv"
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

        report = inspect_inputs(video, self.script)

        self.assertEqual(3.0, report["video"]["duration"])
        self.assertAlmostEqual(2.921, report["audio"]["duration"], places=3)

    def test_inspection_freezes_source_and_script_hashes(self) -> None:
        report = inspect_inputs(self.video, self.script)
        self.assertEqual(hashlib.sha256(self.video.read_bytes()).hexdigest(),
                         report["video"]["sha256"])
        self.assertEqual(self.video.stat().st_size, report["video"]["bytes"])
        self.assertEqual(hashlib.sha256(self.script.read_bytes()).hexdigest(),
                         report["script"]["sha256"])
        self.assertEqual(self.script.stat().st_size, report["script"]["bytes"])
        self.assertEqual(str(self.video.absolute()), report["video"]["path"])

    def test_corrupt_video_is_rejected(self) -> None:
        damaged = self.directory / "damaged.mp4"
        damaged.write_bytes(self.video.read_bytes()[:4096])
        with self.assertRaises(InspectionError):
            inspect_inputs(damaged, self.script)

    def test_video_without_audio_is_rejected(self) -> None:
        with self.assertRaises(InspectionError):
            inspect_inputs(self.video_only, self.script)

    def test_blank_script_is_rejected(self) -> None:
        self.script.write_text("  \n\t", encoding="utf-8")
        with self.assertRaises(InspectionError):
            inspect_inputs(self.video, self.script)

    def test_input_close_faults_close_every_descriptor_and_preserve_primary(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        valid_profile = {
            "streams": {"video": 1, "audio": 1},
            "video": {
                "codec": "h264", "width": 1080, "height": 1920,
                "fps": 24, "duration": 3.0,
            },
            "audio": {
                "codec": "aac", "sample_rate": 48000,
                "channels": 2, "duration": 3.0,
            },
        }
        real_pin = module._pin_regular
        real_close = module.os.close
        for primary in (False, True):
            for close_position in (0, 1):
                for timing in ("pre", "post"):
                    for failure_type in (OSError, KeyboardInterrupt):
                        with self.subTest(
                            primary=primary, close_position=close_position,
                            timing=timing, failure=failure_type.__name__,
                        ):
                            pinned = []
                            injected = False

                            def record_pin(path):
                                value = real_pin(path)
                                pinned.append(value)
                                return value

                            def fail_selected_close(descriptor):
                                nonlocal injected
                                close_order = (
                                    [pinned[1].descriptor, pinned[0].descriptor]
                                    if len(pinned) == 2 else []
                                )
                                if (
                                    not injected and close_order
                                    and descriptor == close_order[close_position]
                                ):
                                    injected = True
                                    if timing == "post":
                                        real_close(descriptor)
                                    raise failure_type("/secret/input close failed")
                                return real_close(descriptor)

                            def inspect_profile(_pinned):
                                if primary:
                                    raise InspectionError(
                                        "primary inspection failed"
                                    )
                                return json.loads(json.dumps(valid_profile))
                            descriptors_before = len(os.listdir("/dev/fd"))
                            captured = None
                            observed_after = None
                            try:
                                with mock.patch(
                                    "edit.hd.tools.inspect_inputs._pin_regular",
                                    side_effect=record_pin,
                                ), mock.patch(
                                    "edit.hd.tools.inspect_inputs._media_profile",
                                    side_effect=inspect_profile,
                                ), mock.patch(
                                    "edit.hd.tools.inspect_inputs.os.close",
                                    side_effect=fail_selected_close,
                                ):
                                    try:
                                        inspect_inputs(self.video, self.script)
                                    except BaseException as exc:
                                        captured = exc
                                observed_after = len(os.listdir("/dev/fd"))
                            finally:
                                for value in pinned:
                                    try:
                                        real_close(value.descriptor)
                                    except OSError:
                                        pass
                            self.assertTrue(injected)
                            self.assertIsInstance(captured, InspectionError)
                            self.assertIsNone(captured.__cause__)
                            self.assertNotIn("/secret", str(captured))
                            if primary:
                                self.assertEqual(
                                    "primary inspection failed", str(captured),
                                )
                            self.assertEqual(descriptors_before, observed_after)

    def test_script_pin_failure_closes_script_and_video_descriptors(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        real_open = module.os.open
        real_close = module.os.close
        real_digest = module._digest_descriptor
        for target in ("script", "video"):
            for timing in ("pre", "post"):
                for failure_type in (OSError, KeyboardInterrupt):
                    with self.subTest(
                        target=target, timing=timing,
                        failure=failure_type.__name__,
                    ):
                        opened: dict[str, int] = {}
                        digest_calls = 0
                        injected = False

                        def record_open(path, flags, *args, **kwargs):
                            descriptor = real_open(path, flags, *args, **kwargs)
                            candidate = Path(path)
                            if candidate == Path(self.video):
                                opened["video"] = descriptor
                            elif candidate == self.script:
                                opened["script"] = descriptor
                            return descriptor

                        def fail_script_digest(descriptor):
                            nonlocal digest_calls
                            digest_calls += 1
                            if digest_calls == 2:
                                raise InspectionError("script pin failed")
                            return real_digest(descriptor)

                        def fail_selected_close(descriptor):
                            nonlocal injected
                            if (
                                not injected and opened.get(target) == descriptor
                            ):
                                injected = True
                                if timing == "post":
                                    real_close(descriptor)
                                raise failure_type("/secret/pin close failed")
                            return real_close(descriptor)

                        descriptors_before = len(os.listdir("/dev/fd"))
                        captured = None
                        observed_after = None
                        try:
                            with mock.patch(
                                "edit.hd.tools.inspect_inputs.os.open",
                                side_effect=record_open,
                            ), mock.patch(
                                "edit.hd.tools.inspect_inputs._digest_descriptor",
                                side_effect=fail_script_digest,
                            ), mock.patch(
                                "edit.hd.tools.inspect_inputs.os.close",
                                side_effect=fail_selected_close,
                            ):
                                try:
                                    inspect_inputs(self.video, self.script)
                                except BaseException as exc:
                                    captured = exc
                            observed_after = len(os.listdir("/dev/fd"))
                        finally:
                            for descriptor in opened.values():
                                try:
                                    real_close(descriptor)
                                except OSError:
                                    pass
                        self.assertTrue(injected)
                        self.assertIsInstance(captured, InspectionError)
                        self.assertEqual("script pin failed", str(captured))
                        self.assertIsNone(captured.__cause__)
                        self.assertNotIn("/secret", str(captured))
                        self.assertEqual(descriptors_before, observed_after)

    def test_symlink_and_hardlink_inputs_are_rejected(self) -> None:
        symlink = self.directory / "source-link.mp4"
        symlink.symlink_to(self.video)
        hardlink = self.directory / "source-hard.mp4"
        os.link(self.video, hardlink)
        for path in (symlink, hardlink):
            with self.subTest(path=path.name), self.assertRaises(InspectionError):
                inspect_inputs(path, self.script)

    def test_ancestor_symlink_is_rejected(self) -> None:
        real = self.directory / "real"
        real.mkdir()
        source = real / "source.mp4"
        source.write_bytes(self.video.read_bytes())
        alias = self.directory / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(InspectionError):
            inspect_inputs(alias / "source.mp4", self.script)

    def test_duplicate_and_nonfinite_probe_json_are_rejected(self) -> None:
        from edit.hd.tools.inspect_inputs import parse_probe_json

        for source in ('{"streams":[],"streams":[]}', '{"streams":[],"x":NaN}'):
            with self.subTest(source=source), self.assertRaises(InspectionError):
                parse_probe_json(source)

    def test_generation_marker_rejects_bool_version_and_nonhex_hash(self) -> None:
        from edit.hd.tools.inspect_inputs import _read_marker

        marker = self.directory / ".01-inspect.generation-recovery.json"
        base = {
            "version": 1, "phase": 0,
            "target": "01-inspect",
            "stage": ".01-inspect.generation.0123456789abcdef0123456789abcdef.stage",
            "backup": None,
            "new": {
                "report.json": {
                    "device": 1, "inode": 2, "sha256": "0" * 64, "bytes": 3,
                }
            },
            "old": None,
        }
        invalid = []
        bool_version = dict(base)
        bool_version["version"] = True
        invalid.append(bool_version)
        nonhex = json.loads(json.dumps(base))
        nonhex["new"]["report.json"]["sha256"] = "z" * 64
        invalid.append(nonhex)
        malformed_token = json.loads(json.dumps(base))
        malformed_token["stage"] = ".01-inspect.generation.not-owned.stage"
        invalid.append(malformed_token)
        mismatched_backup = json.loads(json.dumps(base))
        mismatched_backup["backup"] = (
            ".01-inspect.generation.ffffffffffffffffffffffffffffffff.backup"
        )
        mismatched_backup["old"] = json.loads(json.dumps(base["new"]))
        invalid.append(mismatched_backup)
        for payload in invalid:
            marker.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaises(GenerationRecoveryError):
                _read_marker(marker, "01-inspect", ("report.json",))

    def test_job_wrapper_writes_report_and_only_marks_ready(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="full-v2")

        report_path = inspect_job(job)

        self.assertEqual(job.job_dir / "01-inspect" / "report.json", report_path)
        self.assertTrue((report_path.parent / "material-usage.json").is_file())
        self.assertIn(
            "01-inspect/material-usage.json",
            {item["path"] for item in job.stages["inspect"]["artifacts"]},
        )
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])
        self.assertNotEqual("approved", job.stages["inspect"]["status"])
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(job.inputs["video"]["sha256"], payload["video"]["sha256"])

    def test_job_wrapper_removes_report_if_state_publication_fails(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        with mock.patch(
            "edit.hd.tools.inspect_inputs.mark_ready",
            side_effect=WorkflowError("state failed"),
        ), self.assertRaises(WorkflowError):
            inspect_job(job)
        self.assertFalse((job.job_dir / "01-inspect" / "report.json").exists())
        self.assertEqual("pending", job.stages["inspect"]["status"])

    def test_job_wrapper_preserves_report_if_state_committed_before_error(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")

        def committed_then_error(current, _stage, _artifacts):
            current.stages["inspect"]["status"] = "ready_for_review"
            raise WorkflowError("cleanup pending")

        with mock.patch(
            "edit.hd.tools.inspect_inputs.mark_ready", side_effect=committed_then_error,
        ), self.assertRaises(WorkflowError):
            inspect_job(job)
        self.assertTrue((job.job_dir / "01-inspect" / "report.json").exists())

    def test_report_publication_error_is_sanitized_and_cleans_stage(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.replace",
            side_effect=OSError("/secret/report publication failed"),
        ):
            with self.assertRaises(InspectionError) as captured:
                inspect_job(job)
        self.assertNotIn("/secret", str(captured.exception))
        output = job.job_dir / "01-inspect"
        self.assertFalse((output / "report.json").exists())
        if output.exists():
            self.assertFalse(any(path.name.endswith(".stage") for path in output.iterdir()))

    def test_revised_inspection_atomically_replaces_existing_generation(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        first = inspect_job(job)
        first_inode = first.stat().st_ino
        revise(job, "inspect", "重新检查")

        second = inspect_job(job)

        self.assertEqual(first, second)
        self.assertNotEqual(first_inode, second.stat().st_ino)
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])
        self.assertFalse(any("generation" in path.name for path in job.job_dir.iterdir()))

    def test_publish_fsync_interrupt_restores_old_generation_and_allows_retry(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        report = inspect_job(job)
        old_bytes = report.read_bytes()
        revise(job, "inspect", "重新检查")
        from edit.hd.tools import inspect_inputs as module

        original_fsync = module._fsync_directory
        failed = False
        job_dir_fsyncs = 0

        def interrupt_once(directory):
            nonlocal failed, job_dir_fsyncs
            if Path(directory) == job.job_dir:
                job_dir_fsyncs += 1
                if job_dir_fsyncs == 3 and not failed:
                    failed = True
                    raise KeyboardInterrupt("/secret/publish fsync failed")
            return original_fsync(directory)

        with mock.patch(
            "edit.hd.tools.inspect_inputs._fsync_directory", side_effect=interrupt_once,
        ), self.assertRaises(InspectionError) as captured:
            inspect_job(job)
        self.assertTrue(failed)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertEqual(old_bytes, report.read_bytes())
        self.assertEqual("needs_revision", job.stages["inspect"]["status"])

        retried = inspect_job(job)
        self.assertTrue(retried.exists())
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])

    def test_inspect_mark_ready_cleanup_interrupt_preserves_old_and_recovers(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        report = inspect_job(job)
        old_bytes = report.read_bytes()
        revise(job, "inspect", "重新检查")
        from edit.hd.tools import inspect_inputs as module

        real_unlink = module.os.unlink
        injected = False

        def interrupt_generation_cleanup(candidate):
            nonlocal injected
            candidate = Path(candidate)
            if (
                not injected
                and candidate.parent.name.startswith(".01-inspect.generation.")
                and candidate.parent.name.endswith(".stage")
            ):
                injected = True
                raise KeyboardInterrupt("/secret/cleanup failed")
            return real_unlink(candidate)

        with mock.patch(
            "edit.hd.tools.inspect_inputs.mark_ready",
            side_effect=RuntimeError("state publication failed"),
        ), mock.patch(
            "edit.hd.tools.inspect_inputs.os.unlink",
            side_effect=interrupt_generation_cleanup,
        ):
            with self.assertRaises(GenerationRecoveryError) as captured:
                inspect_job(job)
        self.assertTrue(injected)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertEqual(old_bytes, report.read_bytes())
        self.assertEqual("needs_revision", job.stages["inspect"]["status"])
        self.assertTrue(inspect_job(job).exists())
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])

    def test_committed_marker_cleanup_failure_allows_revision_retry(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        inspect_job(job)
        revise(job, "inspect", "重新检查")
        from edit.hd.tools import inspect_inputs as module

        real_unlink = module.os.unlink
        injected = False

        def fail_before_marker_unlink(candidate):
            nonlocal injected
            candidate = Path(candidate)
            if not injected and candidate.name == ".01-inspect.generation-recovery.json":
                injected = True
                raise OSError("/secret/marker cleanup failed")
            return real_unlink(candidate)

        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.unlink",
            side_effect=fail_before_marker_unlink,
        ), self.assertRaises(GenerationRecoveryError) as captured:
            inspect_job(job)
        self.assertTrue(injected)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])
        self.assertTrue((job.job_dir / "01-inspect" / "report.json").exists())

        revise(job, "inspect", "再次检查")
        retried = inspect_job(job)
        self.assertTrue(retried.exists())
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])

    def test_snapshot_close_failure_is_sanitized_and_does_not_leak_fd(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        generation = self.directory / "generation"
        generation.mkdir()
        (generation / "report.json").write_text("{}\n", encoding="utf-8")
        real_close = module.os.close
        injected = False

        def fail_first_close(descriptor):
            nonlocal injected
            if not injected:
                injected = True
                raise OSError("/secret/close failed")
            return real_close(descriptor)

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.close", side_effect=fail_first_close,
        ), self.assertRaises(GenerationRecoveryError) as captured:
            module._snapshot_generation(generation, ("report.json",))
        descriptors_after = len(os.listdir("/dev/fd"))
        self.assertTrue(injected)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertIsNone(captured.exception.__cause__)
        self.assertEqual(descriptors_before, descriptors_after)

    def test_publish_does_not_remove_a_marker_it_did_not_create(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        marker = job.job_dir / ".01-inspect.generation-recovery.json"
        marker_bytes = b"other transaction\n"
        marker.write_bytes(marker_bytes)
        stage = module._new_generation(job.job_dir, "other", ("report.json",))
        (stage / "report.json").write_text("{}\n", encoding="utf-8")

        with self.assertRaises(GenerationRecoveryError):
            module._publish_generation(
                job, "inspect", stage, "01-inspect", ("report.json",),
                lambda artifacts: None,
            )
        self.assertEqual(marker_bytes, marker.read_bytes())

    def test_cleanup_does_not_unlink_a_replacement_after_validation(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        generation = self.directory / (
            ".01-inspect.generation."
            "0123456789abcdef0123456789abcdef.stage"
        )
        generation.mkdir()
        candidate = generation / "report.json"
        candidate.write_bytes(b"owned generation\n")
        records = module._snapshot_generation(generation, ("report.json",))
        moved = self.directory / "owned-away.json"
        valuable = self.directory / "valuable.json"
        valuable.write_bytes(b"must not be deleted\n")
        real_snapshot = module._snapshot_generation
        snapshots = 0

        def swap_after_validation(*args, **kwargs):
            nonlocal snapshots
            result = real_snapshot(*args, **kwargs)
            snapshots += 1
            if snapshots == 2:
                os.replace(candidate, moved)
                os.replace(valuable, candidate)
            return result

        with mock.patch(
            "edit.hd.tools.inspect_inputs._snapshot_generation",
            side_effect=swap_after_validation,
        ), self.assertRaises(GenerationRecoveryError):
            module._cleanup_generation(generation, records)
        self.assertTrue(candidate.exists())
        self.assertEqual(b"must not be deleted\n", candidate.read_bytes())

    def test_marker_cleanup_does_not_unlink_a_replacement(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        marker = self.directory / ".01-inspect.generation-recovery.json"
        marker.write_bytes(b"owned marker\n")
        record = module._snapshot_file(marker)
        saved = self.directory / "owned-marker-away"
        valuable = self.directory / "valuable-marker-replacement"
        valuable.write_bytes(b"must not be deleted\n")
        real_snapshot = module._snapshot_file
        injected = False

        def swap_after_validation(path):
            nonlocal injected
            result = real_snapshot(path)
            if Path(path) == marker and not injected:
                injected = True
                os.replace(marker, saved)
                os.replace(valuable, marker)
            return result

        with mock.patch(
            "edit.hd.tools.inspect_inputs._snapshot_file",
            side_effect=swap_after_validation,
        ), self.assertRaises(GenerationRecoveryError):
            module._cleanup_marker(marker, record)
        self.assertTrue(injected)
        self.assertTrue(marker.exists())
        self.assertEqual(b"must not be deleted\n", marker.read_bytes())

    def test_cleanup_does_not_unlink_replacement_inside_quarantine(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        generation = self.directory / (
            ".01-inspect.generation."
            "0123456789abcdef0123456789abcdef.stage"
        )
        generation.mkdir()
        candidate = generation / "report.json"
        candidate.write_bytes(b"owned generation\n")
        records = module._snapshot_generation(generation, ("report.json",))
        saved = self.directory / "owned-quarantine-away"
        valuable = self.directory / "valuable-quarantine-replacement"
        valuable.write_bytes(b"must not be deleted\n")
        real_snapshot = module._snapshot_generation
        snapshots = 0
        replacement_path = None

        def swap_inside_quarantine(*args, **kwargs):
            nonlocal snapshots, replacement_path
            result = real_snapshot(*args, **kwargs)
            snapshots += 1
            if snapshots == 3:
                quarantine = Path(args[0])
                replacement_path = quarantine / "report.json"
                os.replace(replacement_path, saved)
                os.replace(valuable, replacement_path)
            return result

        with mock.patch(
            "edit.hd.tools.inspect_inputs._snapshot_generation",
            side_effect=swap_inside_quarantine,
        ), self.assertRaises(GenerationRecoveryError):
            module._cleanup_generation(generation, records)
        self.assertIsNotNone(replacement_path)
        self.assertTrue(replacement_path.exists())
        self.assertEqual(b"must not be deleted\n", replacement_path.read_bytes())

    def test_committed_backup_cleanup_failure_keeps_marker_for_retry(self) -> None:
        root = self.directory / "repo"
        root.mkdir()
        video = root / "source.mp4"
        video.write_bytes(self.video.read_bytes())
        script = root / "script.txt"
        script.write_text("你好口播", encoding="utf-8")
        job = create_job(root, video, script, profile="legacy-v1")
        inspect_job(job)
        revise(job, "inspect", "重新检查")
        from edit.hd.tools import inspect_inputs as module

        real_unlink = module.os.unlink
        injected = False

        def fail_backup_cleanup(candidate):
            nonlocal injected
            candidate = Path(candidate)
            if not injected and ".backup.cleanup." in candidate.parent.name:
                injected = True
                raise OSError("/secret/backup cleanup failed")
            return real_unlink(candidate)

        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.unlink", side_effect=fail_backup_cleanup,
        ), self.assertRaises(GenerationRecoveryError) as captured:
            inspect_job(job)
        marker = job.job_dir / ".01-inspect.generation-recovery.json"
        self.assertTrue(injected)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertTrue(marker.exists())
        self.assertTrue((job.job_dir / "01-inspect" / "report.json").exists())

        revise(job, "inspect", "再次检查")
        retried = inspect_job(job)
        self.assertTrue(retried.exists())
        self.assertFalse(marker.exists())
        self.assertEqual("ready_for_review", job.stages["inspect"]["status"])

    def test_generation_cleanup_accepts_completed_move_after_system_error(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                case = self.directory / failure_type.__name__
                case.mkdir()
                generation = case / (
                    ".01-inspect.generation."
                    "0123456789abcdef0123456789abcdef.stage"
                )
                generation.mkdir()
                candidate = generation / "report.json"
                candidate.write_bytes(b"owned generation\n")
                records = module._snapshot_generation(
                    generation, ("report.json",),
                )
                real_replace = module.os.replace
                injected = False

                def move_then_fail(source, destination):
                    nonlocal injected
                    source = Path(source)
                    destination = Path(destination)
                    if (
                        not injected
                        and source == candidate
                        and ".cleanup." in destination.parent.name
                    ):
                        injected = True
                        real_replace(source, destination)
                        raise failure_type("/secret/move completed")
                    return real_replace(source, destination)

                descriptors_before = len(os.listdir("/dev/fd"))
                with mock.patch(
                    "edit.hd.tools.inspect_inputs.os.replace",
                    side_effect=move_then_fail,
                ):
                    module._cleanup_generation(generation, records)
                descriptors_after = len(os.listdir("/dev/fd"))
                self.assertTrue(injected)
                self.assertEqual(descriptors_before, descriptors_after)
                self.assertFalse(generation.exists())
                self.assertFalse(any(".cleanup." in path.name for path in case.iterdir()))

    def test_marker_cleanup_accepts_completed_move_after_system_error(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                case = self.directory / f"marker-{failure_type.__name__}"
                case.mkdir()
                marker = case / ".01-inspect.generation-recovery.json"
                marker.write_bytes(b"owned marker\n")
                record = module._snapshot_file(marker)
                real_replace = module.os.replace
                injected = False

                def move_then_fail(source, destination):
                    nonlocal injected
                    source = Path(source)
                    destination = Path(destination)
                    if (
                        not injected
                        and source == marker
                        and ".cleanup." in destination.parent.name
                    ):
                        injected = True
                        real_replace(source, destination)
                        raise failure_type("/secret/marker move completed")
                    return real_replace(source, destination)

                descriptors_before = len(os.listdir("/dev/fd"))
                with mock.patch(
                    "edit.hd.tools.inspect_inputs.os.replace",
                    side_effect=move_then_fail,
                ):
                    module._cleanup_marker(marker, record)
                descriptors_after = len(os.listdir("/dev/fd"))
                self.assertTrue(injected)
                self.assertEqual(descriptors_before, descriptors_after)
                self.assertFalse(marker.exists())
                self.assertFalse(any(".cleanup." in path.name for path in case.iterdir()))

    def test_uncertain_move_preserves_owned_recovery_and_unknown_destination(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        source = self.directory / "report.json"
        destination = self.directory / "quarantine-report.json"
        valuable = self.directory / "valuable-replacement.json"
        source.write_bytes(b"owned generation\n")
        valuable.write_bytes(b"must not be deleted\n")
        record = module._snapshot_file(source)
        real_replace = module.os.replace
        real_unlink = module.os.unlink
        injected = False

        def replace_then_swap(source_path, destination_path):
            nonlocal injected
            source_path = Path(source_path)
            destination_path = Path(destination_path)
            if not injected and source_path == source:
                injected = True
                real_replace(source_path, destination_path)
                real_unlink(destination_path)
                real_replace(valuable, destination_path)
                raise OSError("/secret/move destination changed")
            return real_replace(source_path, destination_path)

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.replace",
            side_effect=replace_then_swap,
        ), self.assertRaises(GenerationRecoveryError) as captured:
            module._move_owned(source, destination, record)
        descriptors_after = len(os.listdir("/dev/fd"))
        self.assertTrue(injected)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertEqual(descriptors_before, descriptors_after)
        self.assertEqual(b"must not be deleted\n", destination.read_bytes())
        recoveries = [
            path for path in self.directory.iterdir()
            if path != destination and path.is_file()
            and path.read_bytes() == b"owned generation\n"
        ]
        self.assertGreaterEqual(len(recoveries), 1)
        self.assertTrue(any(path.name.endswith(".retained") for path in recoveries))

    def test_uncertain_move_keeps_owned_retained_copy_if_canonical_is_raced(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        source = self.directory / "report.json"
        destination = self.directory / "quarantine-report.json"
        valuable = self.directory / "valuable-replacement.json"
        source.write_bytes(b"owned generation\n")
        valuable.write_bytes(b"must not be deleted\n")
        record = module._snapshot_file(source)
        real_replace = module.os.replace
        real_unlink = module.os.unlink
        real_open = module.os.open
        moved = False
        raced = False

        def replace_then_swap(source_path, destination_path):
            nonlocal moved
            source_path = Path(source_path)
            destination_path = Path(destination_path)
            if not moved and source_path == source:
                moved = True
                real_replace(source_path, destination_path)
                real_unlink(destination_path)
                real_replace(valuable, destination_path)
                raise OSError("/secret/move destination changed")
            return real_replace(source_path, destination_path)

        def race_canonical_open(path, flags, *args, **kwargs):
            nonlocal raced
            candidate = Path(path)
            if (
                not raced
                and candidate == source
                and flags & os.O_CREAT
            ):
                raced = True
                source.write_bytes(b"foreign canonical\n")
            return real_open(path, flags, *args, **kwargs)

        descriptors_before = len(os.listdir("/dev/fd"))
        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.replace",
            side_effect=replace_then_swap,
        ), mock.patch(
            "edit.hd.tools.inspect_inputs.os.open",
            side_effect=race_canonical_open,
        ), self.assertRaises(GenerationRecoveryError) as captured:
            module._move_owned(source, destination, record)
        descriptors_after = len(os.listdir("/dev/fd"))
        self.assertTrue(moved)
        self.assertTrue(raced)
        self.assertNotIn("/secret", str(captured.exception))
        self.assertEqual(descriptors_before, descriptors_after)
        self.assertEqual(b"foreign canonical\n", source.read_bytes())
        self.assertEqual(b"must not be deleted\n", destination.read_bytes())
        retained = [
            path for path in self.directory.iterdir()
            if path.name.endswith(".retained")
            and path.is_file()
            and path.read_bytes() == b"owned generation\n"
        ]
        self.assertEqual(1, len(retained))

    def test_owned_retained_copy_retries_single_write_and_fsync_faults(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for operation in ("write", "fsync"):
            with self.subTest(operation=operation):
                case = self.directory / operation
                case.mkdir()
                source = case / "report.json"
                destination = case / "quarantine-report.json"
                valuable = case / "valuable.json"
                source.write_bytes(b"owned generation\n")
                valuable.write_bytes(b"valuable\n")
                record = module._snapshot_file(source)
                real_replace = module.os.replace
                real_unlink = module.os.unlink
                real_operation = getattr(module.os, operation)
                move_injected = False
                operation_injected = False
                operation_calls = 0

                def replace_then_swap(source_path, destination_path):
                    nonlocal move_injected
                    source_path = Path(source_path)
                    destination_path = Path(destination_path)
                    if not move_injected and source_path == source:
                        move_injected = True
                        real_replace(source_path, destination_path)
                        real_unlink(destination_path)
                        real_replace(valuable, destination_path)
                        raise OSError("/secret/move uncertain")
                    return real_replace(source_path, destination_path)

                def fail_once(*args, **kwargs):
                    nonlocal operation_injected, operation_calls
                    operation_calls += 1
                    if not operation_injected:
                        operation_injected = True
                        raise OSError(f"/secret/{operation} interrupted")
                    return real_operation(*args, **kwargs)

                descriptors_before = len(os.listdir("/dev/fd"))
                with mock.patch(
                    "edit.hd.tools.inspect_inputs.os.replace",
                    side_effect=replace_then_swap,
                ), mock.patch(
                    f"edit.hd.tools.inspect_inputs.os.{operation}",
                    side_effect=fail_once,
                ), self.assertRaises(GenerationRecoveryError) as captured:
                    module._move_owned(source, destination, record)
                descriptors_after = len(os.listdir("/dev/fd"))
                self.assertTrue(operation_injected)
                self.assertGreaterEqual(operation_calls, 2)
                self.assertNotIn("/secret", str(captured.exception))
                self.assertEqual(descriptors_before, descriptors_after)
                retained = [
                    path for path in case.iterdir()
                    if path.name.endswith(".retained")
                    and path.is_file()
                ]
                self.assertGreaterEqual(len(retained), 1)
                self.assertTrue(all(
                    path.read_bytes() == b"owned generation\n" for path in retained
                ))
                self.assertFalse(any(
                    ".cleanup." in path.name for path in case.iterdir()
                ))

    def test_owned_retained_copy_survives_single_close_exception(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                case = self.directory / f"close-{failure_type.__name__}"
                case.mkdir()
                source = case / "report.json"
                destination = case / "quarantine-report.json"
                valuable = case / "valuable.json"
                source.write_bytes(b"owned generation\n")
                valuable.write_bytes(b"valuable\n")
                record = module._snapshot_file(source)
                real_replace = module.os.replace
                real_unlink = module.os.unlink
                real_close = module.os.close
                moved = False
                close_injected = False

                def replace_then_swap(source_path, destination_path):
                    nonlocal moved
                    source_path = Path(source_path)
                    destination_path = Path(destination_path)
                    if not moved and source_path == source:
                        moved = True
                        real_replace(source_path, destination_path)
                        real_unlink(destination_path)
                        real_replace(valuable, destination_path)
                        raise OSError("/secret/move uncertain")
                    return real_replace(source_path, destination_path)

                def fail_close_once(descriptor):
                    nonlocal close_injected
                    if not close_injected:
                        close_injected = True
                        raise failure_type("/secret/close interrupted")
                    return real_close(descriptor)

                descriptors_before = len(os.listdir("/dev/fd"))
                with mock.patch(
                    "edit.hd.tools.inspect_inputs.os.replace",
                    side_effect=replace_then_swap,
                ), mock.patch(
                    "edit.hd.tools.inspect_inputs.os.close",
                    side_effect=fail_close_once,
                ), self.assertRaises(GenerationRecoveryError) as captured:
                    module._move_owned(source, destination, record)
                descriptors_after = len(os.listdir("/dev/fd"))
                self.assertTrue(close_injected)
                self.assertNotIn("/secret", str(captured.exception))
                self.assertEqual(descriptors_before, descriptors_after)
                retained = [
                    path for path in case.iterdir()
                    if path.name.endswith(".retained")
                    and path.is_file()
                    and path.read_bytes() == b"owned generation\n"
                ]
                self.assertGreaterEqual(len(retained), 1)

    def test_failed_retained_candidate_cleanup_never_claims_foreign_entry(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for write_extent in ("partial", "full"):
            for replacement_kind in ("file", "dangling_symlink"):
                for failure_type in (OSError, KeyboardInterrupt):
                    with self.subTest(
                        write_extent=write_extent,
                        replacement_kind=replacement_kind,
                        failure=failure_type.__name__,
                    ):
                        self._assert_failed_retained_candidate_is_not_reclaimed(
                            module, write_extent, replacement_kind, failure_type,
                        )

    def _assert_failed_retained_candidate_is_not_reclaimed(
        self, module, write_extent, replacement_kind, failure_type,
    ) -> None:
        case = self.directory / (
            f"{write_extent}-{replacement_kind}-{failure_type.__name__}"
        )
        case.mkdir()
        source = case / "report.json"
        owned = b"owned generation content\n"
        foreign = b"foreign valuable content\n"
        source.write_bytes(owned)
        expected = module._snapshot_file(source)
        first_token = "1" * 32
        first_candidate = case / (
            f".{source.name}.owned.{first_token}."
            f"{expected.sha256}.{expected.size}.retained"
        )
        token_values = iter(
            [first_token, "2" * 32, "3" * 32, "4" * 32,
             "5" * 32, "6" * 32, "7" * 32, "8" * 32]
        )
        real_write = module.os.write
        real_unlink = module.os.unlink
        injected = False

        def next_token(_size):
            return next(token_values)

        def write_then_swap(descriptor, data):
            nonlocal injected
            if not injected and first_candidate.exists():
                injected = True
                payload = bytes(data)
                amount = (
                    len(payload) if write_extent == "full"
                    else max(1, len(payload) // 2)
                )
                real_write(descriptor, payload[:amount])
                real_unlink(first_candidate)
                if replacement_kind == "file":
                    first_candidate.write_bytes(foreign)
                else:
                    first_candidate.symlink_to("missing-foreign-target")
                raise failure_type("/secret/retained write interrupted")
            return real_write(descriptor, data)

        descriptors_before = len(os.listdir("/dev/fd"))
        source_descriptor = os.open(source, os.O_RDONLY)
        try:
            with mock.patch(
                "edit.hd.tools.inspect_inputs.secrets.token_hex",
                side_effect=next_token,
            ), mock.patch(
                "edit.hd.tools.inspect_inputs.os.write",
                side_effect=write_then_swap,
            ):
                module._write_owned_reference(
                    source_descriptor, source, expected,
                )
        finally:
            os.close(source_descriptor)
        descriptors_after = len(os.listdir("/dev/fd"))

        self.assertTrue(injected)
        self.assertEqual(descriptors_before, descriptors_after)
        if replacement_kind == "file":
            self.assertTrue(first_candidate.is_file())
            self.assertEqual(foreign, first_candidate.read_bytes())
        else:
            self.assertTrue(first_candidate.is_symlink())
            self.assertEqual(
                "missing-foreign-target", os.readlink(first_candidate),
            )
        valid_retained = [
            path for path in case.iterdir()
            if path != first_candidate and path.name.endswith(".retained")
            and path.is_file() and path.read_bytes() == owned
        ]
        self.assertGreaterEqual(len(valid_retained), 1)

    def test_report_cleanup_error_never_overrides_primary_error(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        for failure_type in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure_type.__name__):
                case = self.directory / f"report-{failure_type.__name__}"
                report = case / "report.json"
                real_unlink = os.unlink
                injected = False

                def fail_cleanup(path, *args, **kwargs):
                    nonlocal injected
                    if not injected and Path(path).name.endswith(".stage"):
                        injected = True
                        raise failure_type("/secret/report cleanup failed")
                    return real_unlink(path, *args, **kwargs)

                descriptors_before = len(os.listdir("/dev/fd"))
                with mock.patch(
                    "edit.hd.tools.inspect_inputs.os.write",
                    side_effect=InspectionError("primary report failed"),
                ), mock.patch(
                    "edit.hd.tools.inspect_inputs.os.unlink", side_effect=fail_cleanup,
                ), self.assertRaises(InspectionError) as captured:
                    module._write_report(report, {"version": 1})
                descriptors_after = len(os.listdir("/dev/fd"))
                self.assertTrue(injected)
                self.assertEqual("primary report failed", str(captured.exception))
                self.assertNotIn("/secret", str(captured.exception))
                self.assertEqual(descriptors_before, descriptors_after)

    def test_report_cleanup_does_not_delete_unknown_stage_replacement(self) -> None:
        from edit.hd.tools import inspect_inputs as module

        case = self.directory / "report-unknown"
        valuable = self.directory / "valuable-report.json"
        valuable.write_bytes(b"must survive")
        real_unlink = os.unlink

        def replace_stage_then_fail(_descriptor, _data):
            stage = next(case.glob(".report.*.stage"))
            real_unlink(stage)
            os.replace(valuable, stage)
            raise InspectionError("primary report failed")

        with mock.patch(
            "edit.hd.tools.inspect_inputs.os.write",
            side_effect=replace_stage_then_fail,
        ), self.assertRaisesRegex(InspectionError, "primary report failed"):
            module._write_report(case / "report.json", {"version": 1})
        replacements = [
            path for path in case.iterdir() if path.read_bytes() == b"must survive"
        ]
        self.assertEqual(1, len(replacements))


if __name__ == "__main__":
    unittest.main()

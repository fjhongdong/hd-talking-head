import unittest
import hashlib
import json
import contextlib
import io
import tempfile
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from edit.hd.tools import reference_transcripts as refs


class ReferenceTranscriptTests(unittest.TestCase):
    def test_asr_report_rejects_incomplete_or_extra_fields(self):
        identity = {"version": 1, "material": {}, "language": "en", "runtime": {}, "implementation": "fixture"}
        report = {**identity, "cues": [{"text": "Hello", "start": 0.1, "end": 0.5}],
                  "raw_output_sha256": "a" * 64, "method": "local_whisper_cpp",
                  "precision": "word", "source_approval": "not_asserted"}
        self.assertTrue(callable(getattr(refs, "_validate_asr_report", None)))
        refs._validate_asr_report(report, identity)
        for change in ("missing", "extra", "invalid"):
            candidate = dict(report)
            if change == "missing":
                del candidate["raw_output_sha256"]
            elif change == "extra":
                candidate["extra"] = True
            else:
                candidate["raw_output_sha256"] = "invalid"
            with self.subTest(change=change), self.assertRaises(ValueError):
                refs._validate_asr_report(candidate, identity)

    def test_reference_publisher_enforces_readable_size_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / "job"
            job_dir.mkdir()
            job = SimpleNamespace(job_dir=job_dir)
            with mock.patch.object(refs, "REFERENCE_REPORT_LIMIT", 32, create=True):
                with self.assertRaisesRegex(ValueError, "exceeds limit"):
                    refs._publish_reference_report(job, "material-0001", {"text": "x" * 40})
            partition = job_dir / "cache/reference-transcripts/material-0001"
            self.assertEqual(list(partition.iterdir()), [])

    def test_cache_cli_routes_empty_tracks_to_approved_transcript_entry(self):
        from edit.hd.tools import cli
        with tempfile.TemporaryDirectory() as directory:
            selection = Path(directory) / "tracks.json"
            selection.write_text('{"tracks": []}')
            job_dir = Path(directory) / "job"
            args = SimpleNamespace(tracks=str(selection), job=str(job_dir),
                                   material_id="material-0001", language="en")
            with mock.patch.object(refs, "cache_reference_transcript", return_value={"path": "report"}) as cache, \
                 mock.patch.object(refs, "cache_material_captions", side_effect=AssertionError("old caption-only entry")):
                self.assertEqual(cli._cache_reference(args), {"path": "report"})
                cache.assert_called_once_with(job_dir, "material-0001", tracks=[], language="en")

    def test_reference_cache_uses_captions_without_asr_fallback(self):
        from edit.hd.tools import reference_asr
        self.assertTrue(callable(getattr(refs, "cache_reference_transcript", None)))
        tracks = [{"language": "en", "material_id": "material-0002", "format": "srt"}]
        with mock.patch.object(refs, "cache_material_captions", side_effect=ValueError("bad caption")), \
             mock.patch.object(reference_asr, "_approved_material_request") as asr:
            with self.assertRaisesRegex(ValueError, "bad caption"):
                refs.cache_reference_transcript(Path("/unused"), "material-0001", tracks=tracks, language="en")
            asr.assert_not_called()

    def test_reference_asr_cache_reuses_report_and_rejects_corruption(self):
        from edit.hd.tools import reference_asr, state
        self.assertTrue(callable(getattr(refs, "cache_reference_transcript", None)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / "job"
            job_dir.mkdir()
            job = SimpleNamespace(root=root, job_dir=job_dir)
            identity = {"version": 1, "material": {"material_id": "material-0001", "sha256": "a" * 64},
                        "language": "en", "runtime": {"model": "ggml-test"}, "implementation": "fixture"}
            recheck = mock.Mock()
            @contextlib.contextmanager
            def request(*args, **kwargs):
                yield identity, [None, None, None], recheck
            raw_source = b'{"fixture": "Hello"}'
            def recognition(*args, raw_output_callback, **kwargs):
                raw_output_callback(raw_source)
                return {"cues": [{"text": "Hello", "start": 0.1, "end": 0.5}],
                        "raw_output_sha256": hashlib.sha256(raw_source).hexdigest()}
            with mock.patch.object(state, "load_job", return_value=job), \
                 mock.patch.object(reference_asr, "_approved_material_request", side_effect=request), \
                 mock.patch.object(reference_asr, "_recognize_pinned_reference", side_effect=recognition) as recognize:
                with self.assertRaises(FileNotFoundError):
                    refs.read_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                recognize.assert_not_called()
                self.assertEqual(list(job_dir.iterdir()), [])
                first = refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                second = refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(first, second)
                recognize.assert_called_once()
                self.assertGreaterEqual(recheck.call_count, 2)
                report_path = Path(first["path"])
                self.assertTrue(callable(getattr(refs, "read_reference_transcript", None)))
                cache_before = {p.name: p.read_bytes() for p in report_path.parent.iterdir()}
                loaded = refs.read_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(loaded["cues"][0]["text"], "Hello")
                self.assertEqual(cache_before, {p.name: p.read_bytes() for p in report_path.parent.iterdir()})
                recognize.assert_called_once()
                report = json.loads(report_path.read_text())
                self.assertEqual(report["method"], "local_whisper_cpp")
                self.assertEqual(report["source_approval"], "not_asserted")
                self.assertEqual(report["precision"], "word")
                raw_path = report_path.parent / (report["raw_output_sha256"] + ".json")
                raw_path.write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "raw reference output checksum differs"):
                    refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                recognize.assert_called_once()
                raw_path.unlink()
                with self.assertRaisesRegex(ValueError, "raw reference output is missing"):
                    refs.read_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                raw_path.write_bytes(raw_source)
                raw_binding_path = next(report_path.parent.glob("raw-request-*.json"))
                raw_binding_source = raw_binding_path.read_bytes()
                raw_binding = json.loads(raw_binding_source)
                raw_binding["extra"] = True
                raw_binding_path.write_text(json.dumps(raw_binding))
                with self.assertRaisesRegex(ValueError, "raw reference request identity is invalid"):
                    refs.read_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                raw_binding_path.write_bytes(raw_binding_source)
                pointer_path = next(report_path.parent.glob("request-*.json"))
                original_pointer = pointer_path.read_bytes()
                for mutation in ("missing", "extra", "invalid"):
                    malformed = dict(report)
                    if mutation == "missing":
                        del malformed["raw_output_sha256"]
                    elif mutation == "extra":
                        malformed["extra"] = True
                    else:
                        malformed["raw_output_sha256"] = "invalid"
                    data = json.dumps(malformed).encode()
                    digest = hashlib.sha256(data).hexdigest()
                    (report_path.parent / (digest + ".json")).write_bytes(data)
                    pointer = json.loads(original_pointer)
                    pointer["report_sha256"] = digest
                    pointer_path.write_text(json.dumps(pointer))
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                    with self.subTest(read_mutation=mutation), self.assertRaises(ValueError):
                        refs.read_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                    recognize.assert_called_once()
                pointer_path.write_bytes(original_pointer)
                recheck.side_effect = RuntimeError("approval withdrawn")
                with self.assertRaisesRegex(RuntimeError, "approval withdrawn"):
                    refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                recognize.assert_called_once()
                recheck.side_effect = None
                report_path.write_text("corrupt")
                with self.assertRaises(ValueError):
                    refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="en")
                recognize.assert_called_once()
                self.assertEqual(report_path.read_text(), "corrupt")

    def test_reference_asr_cache_single_flight_and_failure_has_no_pointer(self):
        from edit.hd.tools import reference_asr, state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / "job"
            job_dir.mkdir()
            job = SimpleNamespace(root=root, job_dir=job_dir)
            identity = {"version": 1, "material": {"material_id": "material-0001", "sha256": "a" * 64},
                        "language": "en", "runtime": {"model": "ggml-test"}, "implementation": "fixture"}
            barrier = threading.Barrier(2)
            @contextlib.contextmanager
            def request(*args, **kwargs):
                barrier.wait(timeout=5)
                yield identity, [None, None, None], lambda: None
            raw_source = b'{"fixture": "Hello"}'
            def recognition(*args, raw_output_callback, **kwargs):
                raw_output_callback(raw_source)
                return {"cues": [{"text": "Hello", "start": 0.1, "end": 0.5}],
                        "raw_output_sha256": hashlib.sha256(raw_source).hexdigest()}
            with mock.patch.object(state, "load_job", return_value=job), \
                 mock.patch.object(reference_asr, "_approved_material_request", side_effect=request), \
                 mock.patch.object(reference_asr, "_recognize_pinned_reference", side_effect=recognition) as recognize:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(refs.cache_reference_transcript, job_dir, "material-0001",
                                           tracks=[], language="en") for _ in range(2)]
                    first, second = [future.result(timeout=10) for future in futures]
                self.assertEqual(first, second)
                recognize.assert_called_once()
                barrier = threading.Barrier(1)
                identity["language"] = "zh"
                recognize.side_effect = RuntimeError("engine failed")
                partition = Path(first["path"]).parent
                before = set(partition.glob("*.json"))
                with self.assertRaisesRegex(RuntimeError, "engine failed"):
                    refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="zh")
                self.assertEqual(set(partition.glob("*.json")), before)
                recognize.side_effect = recognition
                with mock.patch.object(refs, "REFERENCE_REPORT_LIMIT", 32):
                    with self.assertRaisesRegex(ValueError, "exceeds limit"):
                        refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="zh")
                self.assertEqual(set(partition.glob("*.json")), before)
                self.assertEqual(list(partition.glob(".*.tmp")), [])
                changed = refs.cache_reference_transcript(job_dir, "material-0001", tracks=[], language="zh")
                self.assertNotEqual(changed["path"], first["path"])
                self.assertEqual(recognize.call_count, 4)

    def test_cache_rechecks_source_and_rejects_symlink_partition(self):
        from edit.hd.tools import state, startup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / "job"
            job_dir.mkdir()
            outside = root / "outside"
            outside.mkdir()
            job = SimpleNamespace(root=root, job_dir=job_dir)
            with mock.patch.object(state, "load_job", return_value=job), \
                 mock.patch.object(startup, "require_startup") as setup, \
                 mock.patch.object(refs, "read_material_captions") as read:
                setup.side_effect = RuntimeError("not approved")
                with self.assertRaises(RuntimeError):
                    refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                read.assert_not_called()
                setup.side_effect = None
                read.side_effect = RuntimeError("withdrawn")
                with self.assertRaises(RuntimeError):
                    refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(list(job_dir.iterdir()), [])
                read.side_effect = None
                read.return_value = {"material": {"material_id": "material-0001"}}
                (job_dir / "cache").symlink_to(outside, target_is_directory=True)
                with self.assertRaises(OSError):
                    refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(list(outside.iterdir()), [])

    def test_cache_does_not_remove_unowned_temporary(self):
        from edit.hd.tools import state, startup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            partition = root / "job/cache/reference-transcripts/material-0001"
            partition.mkdir(parents=True)
            existing = partition / ".fixed.tmp"
            existing.write_bytes(b"keep")
            job = SimpleNamespace(root=root, job_dir=root / "job")
            with mock.patch.object(state, "load_job", return_value=job), \
                 mock.patch.object(startup, "require_startup"), \
                 mock.patch.object(refs, "read_material_captions", return_value={}), \
                 mock.patch.object(refs.uuid, "uuid4", return_value=SimpleNamespace(hex="fixed")):
                with self.assertRaises(FileExistsError):
                    refs.cache_material_captions(job.job_dir, "material-0001", tracks=[], language="en")
            self.assertEqual(existing.read_bytes(), b"keep")

    def test_cache_partitions_materials_and_reuses_identical_bytes(self):
        from edit.hd.tools import state, startup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_dir = root / "job"
            job_dir.mkdir()
            job = SimpleNamespace(root=root, job_dir=job_dir)
            report = {"version": 1, "material": {"material_id": "material-0001"}, "cues": []}
            with mock.patch.object(state, "load_job", return_value=job), \
                 mock.patch.object(startup, "require_startup"), \
                 mock.patch.object(refs, "read_material_captions", return_value=report), \
                 mock.patch.object(refs.json, "dumps", side_effect=AssertionError("whole report copy")):
                first = refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                path = Path(first["path"])
                before = path.stat()
                second = refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(first, second)
                self.assertEqual(before.st_ino, path.stat().st_ino)
                self.assertEqual(json.loads(path.read_text()), report)
                report["material"]["material_id"] = "material-0002"
                other = refs.cache_material_captions(job_dir, "material-0002", tracks=[], language="en")
                self.assertNotEqual(path.parent, Path(other["path"]).parent)
                path.write_text("damaged")
                report["material"]["material_id"] = "material-0001"
                with self.assertRaises(ValueError):
                    refs.cache_material_captions(job_dir, "material-0001", tracks=[], language="en")
                self.assertEqual(path.read_text(), "damaged")

    def test_selection_limits_and_malformed_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            for data in (b" " * 65537, b'{"tracks": [], "tracks": []}', b'[]'):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    refs.read_track_selection(path)
            for value in ([], {}, None, ""):
                with self.assertRaises(ValueError):
                    refs.read_material_captions(Path(directory), "material-0001", language="en",
                                               tracks=[{"language": "en", "material_id": value, "format": "srt"}])

    def test_reference_cli_returns_search_without_writing_or_approval(self):
        from edit.hd.tools import cli
        with tempfile.TemporaryDirectory() as directory:
            tracks = Path(directory) / "tracks.json"
            selection = [{"language": "en", "material_id": "material-0002", "format": "srt"}]
            tracks.write_text(json.dumps({"tracks": selection}))
            result = {"precision": "segment", "cues": [{"start": 1, "end": 2, "text": "AI"}]}
            output = io.StringIO()
            with mock.patch.object(refs, "read_material_captions", return_value=result) as read, \
                 mock.patch.object(cli, "approve") as approve, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["search-reference", "--workspace", directory,
                                          "--material-id", "material-0001", "--tracks", str(tracks),
                                          "--language", "en", "--query", "ai"]), 0)
            read.assert_called_once_with(Path(directory), "material-0001", tracks=selection, language="en")
            approve.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["matches"][0]["start"], 1)
            self.assertEqual(list(Path(directory).iterdir()), [tracks])

    def test_real_index_distinguishes_same_names_and_rejects_withdrawal(self):
        # Synthetic index only; no production Job or approval is changed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            assets, materials = [], []
            for number, (kind, data) in enumerate((
                ("video", b"first source"), ("video", b"second source"),
                ("documents", b"1\n00:00:01,000 --> 00:00:02,000\nfirst"),
                ("documents", b"1\n00:00:07,000 --> 00:00:08,000\nsecond")), 1):
                relative = f"00-user-provided/{kind}/{number}.data"
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                asset = {"asset_id": f"asset-{number}", "imported_path": relative,
                         "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "media_type": kind}
                assets.append(asset)
                materials.append({**asset, "material_id": f"material-{number:04d}",
                                  "original_name": "same-name", "status": "active"})
            index = {"schema_version": 1, "job_id": root.name, "assets": assets, "materials": materials}
            index_path = root / "00-user-provided/material-index.json"
            index_path.write_text(json.dumps(index))
            first = refs.read_material_captions(root, "material-0001", language="en", tracks=[
                {"language": "en", "material_id": "material-0003", "format": "srt"}])
            second_tracks = [{"language": "en", "material_id": "material-0004", "format": "srt"}]
            second = refs.read_material_captions(root, "material-0002", language="en", tracks=second_tracks)
            self.assertNotEqual(first["material"]["sha256"], second["material"]["sha256"])
            self.assertEqual(first["cues"][0]["start"], 1)
            self.assertEqual(second["cues"][0]["start"], 7)
            selection = root / "tracks.json"
            selection.write_text(json.dumps({"tracks": second_tracks}))
            command = [sys.executable, "-m", "edit.hd.tools.cli", "search-reference",
                       "--workspace", str(root), "--material-id", "material-0002",
                       "--tracks", str(selection), "--language", "en", "--query", "second"]
            files_before = {str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*") if path.is_file()}
            process = subprocess.run(command, cwd=Path(__file__).resolve().parents[3],
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual(report["matches"][0]["start"], 7)
            self.assertEqual(report["material"]["material_id"], "material-0002")
            self.assertEqual(files_before, {str(path.relative_to(root)): path.read_bytes()
                                           for path in root.rglob("*") if path.is_file()})
            before = index_path.read_bytes()
            refs.read_material_captions(root, "material-0002", language="en", tracks=second_tracks)
            self.assertEqual(before, index_path.read_bytes())
            from edit.hd.tools import cli, state, startup
            script = root / "script.md"
            script.write_text("isolated reference test")
            job = state.create_job(root, root / materials[0]["imported_path"], script, profile="full-v2")
            cache_command = ["cache-reference", "--job", str(job.job_dir),
                             "--material-id", "material-0002", "--tracks", str(selection), "--language", "en"]
            workflow_before = (job.job_dir / "workflow.json").read_bytes()
            # Real state/index/CLI/storage; only release/setup is isolated here.
            # Current development Skill is deliberately not re-signed for this fixture.
            with mock.patch.object(startup, "require_startup"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(cli.main(cache_command), 0)
                cached = json.loads(output.getvalue())
                saved = Path(cached["path"])
                saved_info = saved.stat()
                self.assertEqual(json.loads(saved.read_text())["cues"][0]["start"], 7)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(cache_command), 0)
                self.assertEqual(saved_info.st_ino, saved.stat().st_ino)
            self.assertEqual((job.job_dir / "workflow.json").read_bytes(), workflow_before)
            self.assertEqual(before, index_path.read_bytes())
            # The unpatched managed-Job gate must refuse this unapproved fixture,
            # even though a valid cache now exists.
            denied = subprocess.run([sys.executable, "-m", "edit.hd.tools.cli", *cache_command],
                                    cwd=Path(__file__).resolve().parents[3],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(denied.returncode, 2)
            self.assertEqual(denied.stdout, "")
            self.assertEqual(saved_info.st_ino, saved.stat().st_ino)
            index["materials"][1]["status"] = "withdrawn"
            index_path.write_text(json.dumps(index))
            with self.assertRaisesRegex(RuntimeError, "withdrawn"):
                refs.read_material_captions(root, "material-0002", language="en", tracks=second_tracks)
            rejected = subprocess.run(command, cwd=Path(__file__).resolve().parents[3],
                                      capture_output=True, text=True, timeout=15)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected.stdout, "")
            with mock.patch.object(startup, "require_startup"), \
                 contextlib.redirect_stdout(io.StringIO()) as output, \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(cache_command), 2)
                self.assertEqual(output.getvalue(), "")
            self.assertEqual(saved_info.st_ino, saved.stat().st_ino)
            self.assertEqual((job.job_dir / "workflow.json").read_bytes(), workflow_before)

    def test_descriptor_walk_rejects_nested_and_final_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "real").mkdir()
            (root / "real" / "caption.srt").write_text("data")
            (root / "linked").symlink_to(root / "real", target_is_directory=True)
            (root / "caption.srt").symlink_to(root / "real" / "caption.srt")
            for relative in (Path("linked/caption.srt"), Path("caption.srt")):
                with self.subTest(relative=relative), self.assertRaises(OSError):
                    refs._open_caption(root, relative)

    def test_indexed_caption_read_binds_media_and_caption_identity(self):
        from edit.hd.tools import user_materials
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "movie.mp4").write_bytes(b"source media fixture")
            caption = root / "captions.srt"
            caption.write_text("1\n00:00:01,000 --> 00:00:02,000\nexample", encoding="utf-8")
            records = {}
            for identifier, name in (("material-0001", "movie.mp4"), ("material-0002", "captions.srt")):
                data = (root / name).read_bytes()
                records[identifier] = {"material_id": identifier, "imported_path": name,
                                       "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
            def resolve(workspace, identifier, *_args):
                self.assertEqual(workspace, root)
                return records[identifier].copy()
            tracks = [{"language": "en", "material_id": "material-0002", "format": "srt"}]
            with mock.patch.object(user_materials, "require_active_material") as resolver:
                with self.assertRaises(ValueError):
                    refs.read_material_captions(root, "material-0001", tracks=tracks, language="zh")
                resolver.assert_not_called()
            with mock.patch.object(user_materials, "require_active_material", side_effect=resolve):
                result = refs.read_material_captions(root, "material-0001", tracks=tracks, language="en")
                self.assertEqual(result["material"], records["material-0001"])
                self.assertEqual(result["caption_material"], records["material-0002"])
                self.assertEqual(result["precision"], "segment")
                self.assertEqual(result["cues"][0]["text"], "example")
                calls = 0
                def withdraw(workspace, identifier, *_args):
                    nonlocal calls
                    calls += 1
                    if calls >= 3:
                        raise ValueError("material withdrawn")
                    return resolve(workspace, identifier)
                with mock.patch.object(user_materials, "require_active_material", side_effect=withdraw):
                    with self.assertRaisesRegex(ValueError, "withdrawn"):
                        refs.read_material_captions(root, "material-0001", tracks=tracks, language="en")
                caption.write_text("changed", encoding="utf-8")
                with self.assertRaises(ValueError):
                    refs.read_material_captions(root, "material-0001", tracks=tracks, language="en")

    def test_srt_keeps_repeated_text_and_overlapping_cues(self):
        cues = refs.parse_caption_text(
            "1\n00:00:01,000 --> 00:00:03,000\n相同内容\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n相同内容\n", format="srt")
        self.assertEqual(cues, [{"start": 1.0, "end": 3.0, "text": "相同内容"},
                                {"start": 2.0, "end": 4.0, "text": "相同内容"}])

    def test_vtt_header_identifiers_and_settings(self):
        cues = refs.parse_caption_text(
            "\ufeffWEBVTT\n\nintro\n00:01.200 --> 00:02.500 align:start\nHello\nworld\n", format="vtt")
        self.assertEqual(cues, [{"start": 1.2, "end": 2.5, "text": "Hello\nworld"}])

    def test_invalid_times_are_not_repaired(self):
        for timing in ("00:00:02,000 --> 00:00:01,000", "00:61:01,000 --> 00:62:02,000",
                       "00:00:00,000 --> 00:00:00,000", "NaN --> Infinity"):
            with self.subTest(timing=timing), self.assertRaises(ValueError):
                refs.parse_caption_text(f"1\n{timing}\n内容", format="srt")

    def test_unsupported_vtt_metadata_does_not_return_partial_cues(self):
        cue = "00:01.000 --> 00:02.000\nvalid"
        for text in ("WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:900000\n\n" + cue,
                     "WEBVTT\n\n" + cue + "\n\nSTYLE\n::cue {color:red}",
                     "WEBVTT\n\n" + cue + "\n\nREGION\nid:main"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                refs.parse_caption_text(text, format="vtt")

    def test_language_selection_never_uses_first_or_guesses(self):
        tracks = [{"language": "en", "id": "english"}, {"language": "zh-CN", "id": "chinese"}]
        self.assertEqual(refs.select_caption_track(tracks, language="zh-CN")["id"], "chinese")
        for candidates, language in ((tracks, "zh"), (tracks + [tracks[1]], "zh-CN")):
            with self.assertRaises(ValueError):
                refs.select_caption_track(candidates, language=language)
        self.assertEqual(tracks[0]["id"], "english")

    def test_search_preserves_all_times_and_declares_precision(self):
        cues = [{"start": 1, "end": 2, "text": "AI model"},
                {"start": 5, "end": 6, "text": "AI model"}]
        hits = refs.search_cues(cues, "ai", precision="segment")
        self.assertEqual([hit["start"] for hit in hits], [1, 5])
        self.assertTrue(all(hit["precision"] == "segment" for hit in hits))
        self.assertFalse(refs.search_cues(cues, "AI", precision="whole")[0]["precise_cut_eligible"])
        with self.assertRaises(ValueError):
            refs.search_cues(cues, "", precision="segment")


if __name__ == "__main__":
    unittest.main()

"""Reference ASR configuration tests; never approve or transcribe user media."""

import hashlib
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import os
import wave
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest import mock
from datetime import datetime, timezone

from edit.hd.tools import startup
from edit.hd.tools.state import WorkflowError


class ReferenceASRConfigTests(unittest.TestCase):
    def test_reference_request_rejects_unapproved_job_before_engine_discovery(self):
        from edit.hd.tools import reference_asr
        self.assertTrue(callable(getattr(reference_asr, "_approved_material_request", None)))
        with mock.patch.object(reference_asr, "load_job", return_value=object()), \
             mock.patch.object(startup, "require_startup", side_effect=WorkflowError("not approved")), \
             mock.patch.object(reference_asr, "probe_configured_runtime") as probe:
            with self.assertRaisesRegex(WorkflowError, "not approved"):
                with reference_asr._approved_material_request(Path("/unused"), "material-0001", language="en"):
                    self.fail("unapproved request opened")
            probe.assert_not_called()

    def test_reference_request_pins_current_index_and_rechecks_withdrawal(self):
        from edit.hd.tools import reference_asr, state
        self.assertTrue(callable(getattr(reference_asr, "_approved_material_request", None)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "00-user-provided/video/source.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"synthetic media")
            asset = {"asset_id": "asset-1", "imported_path": str(source.relative_to(root)),
                     "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                     "size_bytes": source.stat().st_size, "media_type": "video"}
            material = {**asset, "material_id": "material-0001", "original_name": "source.mp4", "status": "active"}
            index = {"schema_version": 1, "job_id": root.name, "assets": [asset], "materials": [material]}
            index_path = root / "00-user-provided/material-index.json"
            index_path.write_text(json.dumps(index))
            script = root / "script.md"
            script.write_text("fixture")
            job = state.create_job(root, source, script, profile="full-v2")
            config = job.job_dir / "manifests/provider-config.json"
            config.parent.mkdir(exist_ok=True)
            config.write_text(json.dumps({"schema_version": 2, "providers": [], "max_concurrency": 1,
                "generation_enabled": False, "reference_asr": {"provider": "whisper.cpp", "model": "ggml-test",
                "execution": "local", "upload_policy": "forbidden"}}))
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"model")
            with mock.patch.dict(os.environ, {"HD_WHISPER_CLI": str(executable), "HD_WHISPER_MODEL": str(model)}):
                proof = reference_asr.probe_configured_runtime(job)
                (config.parent / "dependency-preflight.json").write_text(json.dumps({"dependencies": [
                    {"id": "reference-asr", "reference_asr_probe": proof}]}))
                with mock.patch.object(startup, "require_startup"):
                    with reference_asr._approved_material_request(job.job_dir, "material-0001", language="en") as request:
                        identity, pins, recheck = request
                        self.assertEqual(identity["material"], material)
                        self.assertEqual(identity["language"], "en")
                        self.assertEqual(identity["runtime"], proof)
                        self.assertEqual(pins[0].sha256, asset["sha256"])
                        recheck()
                        index["materials"][0]["status"] = "withdrawn"
                        index_path.write_text(json.dumps(index))
                        with self.assertRaises((ValueError, RuntimeError)):
                            recheck()
                    for pin in pins:
                        with self.assertRaises(OSError):
                            os.fstat(pin.descriptor)

    def test_reference_recognition_uses_real_decoder_and_pinned_engine_inputs(self):
        from edit.hd.tools import reference_asr, transcribe
        self.assertTrue(callable(getattr(reference_asr, "_recognize_pinned_reference", None)),
                        "reference recognition execution is missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.wav"
            with wave.open(str(source), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 16000)
            executable = root / "whisper-cli"
            payload = {"result": {"language": "en"}, "transcription": [
                {"text": "Hello", "offsets": {"from": 100, "to": 500}, "tokens": [
                {"text": "Hello", "offsets": {"from": 100, "to": 500}}]}]}
            executable.write_text(f'#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\n'
                'args=sys.argv[1:]\nlanguage=args[args.index("-l")+1]\n'
                'if language=="ja": sys.exit(1)\n'
                'if language=="es": sys.exit(0)\n'
                'assert Path(args[args.index("-m")+1]).read_bytes()==b"model"\n'
                'assert Path(args[args.index("-f")+1]).read_bytes()[:4]==b"RIFF"\n'
                f'payload=json.loads({json.dumps(json.dumps(payload))})\n'
                'if language=="zh":\n'
                ' payload["result"]["language"]="zh"\n'
                ' payload["transcription"][0]["tokens"][0]["offsets"]={"from":500,"to":100}\n'
                'Path(args[args.index("-of")+1]+".json").write_text(json.dumps(payload))\n')
            executable.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"model")
            pins = [transcribe._pin_local_media(path) for path in (source, executable, model)]
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            try:
                report = reference_asr._recognize_pinned_reference(*pins, language="en")
                self.assertEqual(report["cues"], [{"text": "Hello", "start": 0.1, "end": 0.5}])
                self.assertEqual(report["raw_output_sha256"], hashlib.sha256(json.dumps(payload).encode()).hexdigest())
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            finally:
                self.assertTrue(transcribe._close_pinned_inputs(pins))

            # Exercise the real index, request guard, decoder, engine and cache
            # via CLI. Only unpublished release/setup approval is isolated.
            from edit.hd.tools import state, cli
            imported = root / "00-user-provided/audio/source.wav"
            imported.parent.mkdir(parents=True)
            source.rename(imported)
            source = imported
            executable.write_text(executable.read_text().replace(
                'args=sys.argv[1:]\n', 'args=sys.argv[1:]\nif args==["--help"]: sys.exit(0)\n'))
            asset = {"asset_id": "asset-1", "imported_path": str(source.relative_to(root)),
                     "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                     "size_bytes": source.stat().st_size, "media_type": "audio"}
            material = {**asset, "material_id": "material-0001", "original_name": source.name, "status": "active"}
            index_path = root / "00-user-provided/material-index.json"
            index_path.parent.mkdir(exist_ok=True)
            index_path.write_text(json.dumps({"schema_version": 1, "job_id": root.name,
                                             "assets": [asset], "materials": [material]}))
            script = root / "script.md"
            script.write_text("fixture")
            job = state.create_job(root, source, script, profile="full-v2")
            config = job.job_dir / "manifests/provider-config.json"
            config.parent.mkdir(exist_ok=True)
            config.write_text(json.dumps({"schema_version": 2, "providers": [], "max_concurrency": 1,
                "generation_enabled": False, "reference_asr": {"provider": "whisper.cpp", "model": "ggml-test",
                "execution": "local", "upload_policy": "forbidden"}}))
            selection = root / "tracks.json"
            selection.write_text('{"tracks": []}')
            command = ["cache-reference", "--job", str(job.job_dir), "--material-id", "material-0001",
                       "--tracks", str(selection), "--language", "en"]
            before = {path: path.read_bytes() for path in (source, index_path, job.job_dir / "workflow.json")}
            with mock.patch.dict(os.environ, {"HD_WHISPER_CLI": str(executable), "HD_WHISPER_MODEL": str(model)}):
                proof = reference_asr.probe_configured_runtime(job)
                (config.parent / "dependency-preflight.json").write_text(json.dumps({"dependencies": [
                    {"id": "reference-asr", "reference_asr_probe": proof}]}))
                with mock.patch.object(startup, "require_startup"):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(cli.main(command), 0)
                    saved = Path(json.loads(output.getvalue())["path"])
                    self.assertEqual(json.loads(saved.read_text())["cues"], report["cues"])
                    raw_saved = saved.parent / (report["raw_output_sha256"] + ".json")
                    self.assertTrue(raw_saved.is_file(), "native Whisper JSON must survive temporary cleanup")
                    self.assertEqual(raw_saved.read_bytes(), json.dumps(payload).encode())
                    raw_binding = json.loads(next(saved.parent.glob("raw-request-*.json")).read_text())
                    self.assertEqual(raw_binding["raw_output_sha256"], report["raw_output_sha256"])
                    self.assertEqual(raw_binding["material"]["sha256"], material["sha256"])
                    inode = saved.stat().st_ino
                    with mock.patch.object(reference_asr, "_recognize_pinned_reference",
                                           side_effect=AssertionError("cache should reuse recognition")):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(cli.main(command), 0)
                    self.assertEqual(saved.stat().st_ino, inode)
                    failed_command = [*command[:-1], "zh"]
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(cli.main(failed_command), 2)
                    failed_binding_path = next(path for path in saved.parent.glob("raw-request-*.json")
                                               if json.loads(path.read_text())["language"] == "zh")
                    failed_binding = json.loads(failed_binding_path.read_text())
                    failed_raw = saved.parent / (failed_binding["raw_output_sha256"] + ".json")
                    failed_payload = copy.deepcopy(payload)
                    failed_payload["result"]["language"] = "zh"
                    failed_payload["transcription"][0]["tokens"][0]["offsets"] = {"from": 500, "to": 100}
                    self.assertEqual(failed_raw.read_bytes(), json.dumps(failed_payload).encode())
                    self.assertFalse((saved.parent / failed_binding_path.name.removeprefix("raw-")).exists())
                    raw_inode = failed_raw.stat().st_ino
                    from edit.hd.tools import reference_transcripts
                    with mock.patch.object(reference_asr, "_recognize_pinned_reference",
                                           side_effect=AssertionError("saved raw result must not rerun recognition")):
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(cli.main(failed_command), 2)
                        imported_report = reference_transcripts.import_saved_reference_segments(
                            job.job_dir, "material-0001", raw_result=failed_raw,
                            expected_sha256=failed_binding["raw_output_sha256"], language="zh")
                    imported_data = json.loads(Path(imported_report["path"]).read_text())
                    self.assertEqual(imported_data["precision"], "segment")
                    self.assertEqual(imported_data["cues"], report["cues"])
                    self.assertEqual(failed_raw.stat().st_ino, raw_inode)
                    before_failure = {path.name: path.read_bytes() for path in saved.parent.glob("*.json")}
                    for empty_language in ("ja", "es"):
                        with self.subTest(empty_language=empty_language), \
                             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(cli.main([*command[:-1], empty_language]), 2)
                        self.assertEqual(before_failure,
                                         {path.name: path.read_bytes() for path in saved.parent.glob("*.json")})
                    search_command = ["search-reference", *command[1:], "--query", "Hello"]
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(cli.main(search_command), 0)
                    matches = json.loads(output.getvalue())["matches"]
                    self.assertEqual(matches[0]["start"], 0.1)
                    self.assertFalse(matches[0]["precise_cut_eligible"])
                denied = subprocess.run([sys.executable, "-m", "edit.hd.tools.cli", *command],
                                        cwd=Path(__file__).resolve().parents[3], capture_output=True,
                                        text=True, timeout=15)
                self.assertEqual(denied.returncode, 2, denied.stderr)
                self.assertEqual(denied.stdout, "")
                self.assertEqual(saved.stat().st_ino, inode)
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_startup_report_requires_selected_asr_evidence(self):
        from edit.hd.tools import state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video, script = root / "source.mp4", root / "script.md"
            video.write_bytes(b"fixture")
            script.write_text("fixture")
            job = state.create_job(root, video, script, profile="full-v2")
            manifest = root / "references/dependency-manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({"dependencies": [{"id": "reference-asr", "required": False,
                "required_level": "callable", "config_selection": "reference_asr"}]}))
            context = {"project_root": str(root), "runtime": {}, "skill_release": {"root": str(root)}}
            config = job.job_dir / "manifests/provider-config.json"
            config.parent.mkdir(exist_ok=True)
            selected = {"provider": "whisper.cpp", "model": "ggml-test", "execution": "local",
                        "upload_policy": "forbidden"}
            config.write_text(json.dumps({"schema_version": 2, "providers": [], "max_concurrency": 1,
                                          "generation_enabled": False, "reference_asr": selected}))
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            report = {"job_context": {"job_id": job.job_id, "workspace": str(root)},
                "provider_config_sha256": digest, "manifest_path": str(manifest),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "project_root": str(root), "runtime": {}, "checked_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"status": "ready", "required_missing": 0}, "dependencies": []}
            path = job.job_dir / "manifests/dependency-preflight.json"
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(WorkflowError, "reference ASR"):
                startup._report(job, context, digest)
            config.write_text("{}")
            with self.assertRaisesRegex(WorkflowError, "reference ASR"):
                startup._report(job, context, digest)

    def test_probe_cli_is_read_only_and_reports_disabled_or_failure(self):
        from edit.hd.tools import state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video = root / "source.mp4"
            video.write_bytes(b"synthetic video; probe must not decode")
            script = root / "script.md"
            script.write_text("Synthetic script")
            job = state.create_job(root, video, script, profile="full-v2")
            config_path = job.job_dir / "manifests/provider-config.json"
            config_path.parent.mkdir(exist_ok=True)
            base = {"schema_version": 1, "providers": [], "max_concurrency": 1,
                    "generation_enabled": False}
            command = [sys.executable, "-m", "edit.hd.tools.reference_asr", "--job", str(job.job_dir)]
            env = {**os.environ, "HD_WHISPER_CLI": str(root / "missing-executable"),
                   "HD_WHISPER_MODEL": str(root / "missing-model")}
            for config, expected in ((base, 0), ({**base, "schema_version": 2, "reference_asr": {
                    "provider": "whisper.cpp", "model": "ggml-test", "execution": "local",
                    "upload_policy": "forbidden"}}, 2), ({**base, "reference_asr": {}}, 3)):
                config_path.write_text(json.dumps(config))
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                result = subprocess.run(command, cwd=Path(__file__).resolve().parents[3],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected == 0:
                    self.assertEqual(result.stdout.strip(), "null")
                else:
                    self.assertEqual(result.stdout, "")
                    self.assertIn("reference ASR probe failed", result.stderr)
                self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes()
                                        for p in root.rglob("*") if p.is_file()})
            config_path.write_text(json.dumps({**base, "schema_version": 2, "reference_asr": {
                "provider": "whisper.cpp", "model": "ggml-test", "execution": "local",
                "upload_policy": "forbidden"}}))
            executable = root / "whisper-cli"
            executable.write_text('#!/bin/sh\n[ "$#" -eq 1 ] && [ "$1" = "--help" ]\n')
            executable.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"synthetic weights; no model load")
            env.update(HD_WHISPER_CLI=str(executable), HD_WHISPER_MODEL=str(model))
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[3],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["model"], "ggml-test")
            self.assertTrue(report["callable"])
            self.assertFalse(report["model_load_verified"])
            self.assertEqual(report["executable"]["sha256"], hashlib.sha256(executable.read_bytes()).hexdigest())
            self.assertEqual(report["model_file"]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes()
                                    for p in root.rglob("*") if p.is_file()})

    def test_configured_probe_does_not_enable_asr_from_environment(self):
        from edit.hd.tools import reference_asr
        with tempfile.TemporaryDirectory() as directory:
            job = SimpleNamespace(job_dir=Path(directory).resolve())
            path = job.job_dir / "manifests/provider-config.json"
            path.parent.mkdir()
            base = {"schema_version": 1, "providers": [], "max_concurrency": 1, "generation_enabled": False}
            with mock.patch.object(reference_asr, "probe_local_runtime", return_value={"fixture": True}) as probe:
                for config in (base, {**base, "schema_version": 2, "reference_asr": None}):
                    path.write_text(json.dumps(config))
                    self.assertIsNone(reference_asr.probe_configured_runtime(job))
                probe.assert_not_called()
                config = {**base, "schema_version": 2, "reference_asr": {
                    "provider": "whisper.cpp", "model": "ggml-test", "execution": "local",
                    "upload_policy": "forbidden"}}
                path.write_text(json.dumps(config))
                self.assertEqual(reference_asr.probe_configured_runtime(job), {
                    "fixture": True, "provider_config_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                probe.assert_called_once_with("ggml-test")
                def mutate(model_id):
                    path.write_text(json.dumps(base))
                    return {"fixture": True}
                probe.side_effect = mutate
                with self.assertRaises(WorkflowError):
                    reference_asr.probe_configured_runtime(job)
                path.write_text(json.dumps(config))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                substituted = {**config, "reference_asr": {**config["reference_asr"], "model": "ggml-other"}}
                probe.side_effect = None
                probe.reset_mock()
                with mock.patch.object(startup, "_config", return_value=(path, digest)), \
                     mock.patch.object(startup, "_read", return_value=substituted):
                    reference_asr.probe_configured_runtime(job)
                probe.assert_called_once_with("ggml-test")

    def test_local_probe_binds_files_and_runs_only_help(self):
        from edit.hd.tools import reference_asr, transcribe
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"synthetic model")
            runtime = transcribe.WhisperRuntime(executable, model)
            with mock.patch.object(transcribe, "discover_runtime", return_value=runtime), \
                 mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                report = reference_asr.probe_local_runtime("ggml-test")
            command = run.call_args.args[0]
            self.assertEqual(command[1:], ["--help"])
            self.assertNotEqual(command[0], str(executable))
            self.assertFalse(Path(command[0]).exists())
            self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(report["model_file"]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertEqual(report["executable"]["sha256"], hashlib.sha256(executable.read_bytes()).hexdigest())
            self.assertTrue(report["callable"])
            self.assertFalse(report["model_load_verified"])
            self.assertEqual(report["upload_policy"], "forbidden")
            self.assertEqual(set(root.iterdir()), {executable, model})

    def test_local_probe_rejects_mismatch_failure_and_changed_model(self):
        from edit.hd.tools import reference_asr, transcribe
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"model")
            runtime = transcribe.WhisperRuntime(executable, model)
            with mock.patch.object(transcribe, "discover_runtime", return_value=runtime), \
                 mock.patch.object(subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    reference_asr.probe_local_runtime("ggml-other")
                run.assert_not_called()
                run.return_value = subprocess.CompletedProcess([], 1)
                with self.assertRaises(RuntimeError):
                    reference_asr.probe_local_runtime("ggml-test")
                def mutate(*args, **kwargs):
                    model.write_bytes(b"changed")
                    return subprocess.CompletedProcess([], 0)
                run.side_effect = mutate
                with self.assertRaises(RuntimeError):
                    reference_asr.probe_local_runtime("ggml-test")

    def test_probe_never_executes_replacement_path(self):
        from edit.hd.tools import reference_asr, transcribe
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            replacement = root / "replacement"
            marker = root / "replacement-executed"
            replacement.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 0\n')
            replacement.chmod(0o700)
            model = root / "ggml-test.bin"
            model.write_bytes(b"model")
            actual_run = subprocess.run
            def swap_and_run(command, **kwargs):
                replacement.replace(executable)
                return actual_run(command, **kwargs)
            with mock.patch.object(transcribe, "discover_runtime",
                                   return_value=transcribe.WhisperRuntime(executable, model)), \
                 mock.patch.object(subprocess, "run", side_effect=swap_and_run):
                with self.assertRaises(RuntimeError):
                    reference_asr.probe_local_runtime("ggml-test")
            self.assertFalse(marker.exists())

    def test_explicit_local_asr_config_and_disabled_legacy_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            job = SimpleNamespace(job_dir=Path(directory).resolve())
            path = job.job_dir / "manifests/provider-config.json"
            path.parent.mkdir()
            base = {"schema_version": 1, "providers": [], "max_concurrency": 1,
                    "generation_enabled": False}
            for config in (base, {**base, "schema_version": 2, "reference_asr": None},
                           {**base, "schema_version": 2, "reference_asr": {
                               "provider": "whisper.cpp", "model": "ggml-large-v3-turbo",
                               "execution": "local", "upload_policy": "forbidden"}}):
                with self.subTest(config=config):
                    path.write_text(json.dumps(config))
                    before = path.read_bytes()
                    self.assertEqual(startup._config(job), (path, hashlib.sha256(before).hexdigest()))
                    self.assertEqual(path.read_bytes(), before)

    def test_unknown_or_upload_enabled_asr_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            job = SimpleNamespace(job_dir=Path(directory).resolve())
            path = job.job_dir / "manifests/provider-config.json"
            path.parent.mkdir()
            local = {"provider": "whisper.cpp", "model": "ggml-large-v3-turbo",
                     "execution": "local", "upload_policy": "forbidden"}
            base = {"schema_version": 2, "providers": [], "max_concurrency": 1,
                    "generation_enabled": False, "reference_asr": local}
            invalid = [True, [], {}, {**local, "execution": "cloud"},
                       {**local, "upload_policy": "allowed"}, {**local, "provider": "unknown"},
                       {**local, "api_key": "not-a-real-key"}, {**local, "model": "../model"},
                       {**local, "model": ""}]
            configs = [{**base, "reference_asr": value} for value in invalid]
            configs.extend([{**base, "schema_version": 1}, {**base, "schema_version": 3}])
            configs.append({k: v for k, v in base.items() if k != "reference_asr"})
            for config in configs:
                with self.subTest(config=config):
                    path.write_text(json.dumps(config))
                    with self.assertRaises(WorkflowError):
                        startup._config(job)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tests import test_visual_plan
from edit.hd.tools import (
    broll_component_executor,
    contract_artifacts,
    material_usage,
    preview_v2,
    segment_render,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _artifact_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _rewrite_approved_json(
    job: SimpleNamespace,
    stage_id: str,
    relative: str,
    payload: object,
) -> None:
    path = Path(job.job_dir) / relative
    path.write_bytes(contract_artifacts.canonical_json_bytes(payload) + b"\n")
    record = next(
        item
        for item in job.stages[stage_id]["artifacts"]
        if item["path"] == relative
    )
    record.update(sha256=_sha256(path), bytes=path.stat().st_size)


def _source_fixture(
    root: Path,
    kinds: tuple[str, ...] = ("external_stock",),
    *,
    attribution_required: bool = False,
    job_id: str = "job-source-manifest-001",
) -> tuple[SimpleNamespace, dict[str, object], dict[str, object]]:
    root = root.resolve()
    job = SimpleNamespace(job_dir=root, job_id=job_id, version=2)
    plan = test_visual_plan.valid_plan(kinds)
    segment = plan["segments"][0]
    recipe = segment["shot_recipe"]
    artifacts = []
    for index, component in enumerate(recipe["components"], start=1):
        component_id = component["component_id"]
        kind = component["kind"]
        binding = segment["bindings"][component_id]
        if kind in {"local_material", "external_stock"}:
            source = _write(
                root / binding["job_path"], f"source-{kind}-{index}".encode()
            )
            binding["sha256"] = _sha256(source)
            component["sha256"] = binding["sha256"]
        elif kind == "official_material":
            source = _write(
                root / binding["snapshot_path"], f"source-{kind}-{index}".encode()
            )
            binding["sha256"] = _sha256(source)
            component["sha256"] = binding["sha256"]

        final = _write(
            root / f"09-visual-assets/components/{component_id}/artifact.png",
            f"final-{kind}-{index}".encode(),
        )
        if kind == "ai_generated":
            binding["sha256"] = _sha256(final)
            component["sha256"] = binding["sha256"]

        evidence: dict[str, object] = {
            "output_job_path": final.relative_to(root).as_posix(),
            "output_sha256": _sha256(final),
        }
        if kind == "external_stock":
            evidence["adapter_record"] = {
                "attribution_required": attribution_required,
            }
            license_record = {
                "schema_version": 1,
                "idempotency_key": "7" * 64,
                "search_generation": "search-001",
                "snapshot_sha256": "8" * 64,
                "query_sha256": "9" * 64,
                "provider": binding["provider"],
                "provider_asset_id": binding["provider_asset_id"],
                "author": binding["author"],
                "asset_page": binding["asset_page"],
                "license_name": "Example Stock License",
                "license_version": "license-v1",
                "downloaded_at": binding["downloaded_at"],
                "byte_count": source.stat().st_size,
                "sha256": _sha256(source),
                "job_path": binding["job_path"],
                "license_snapshot": binding["license_snapshot"],
            }
            _write(
                root / binding["license_snapshot"],
                contract_artifacts.canonical_json_bytes(license_record) + b"\n",
            )
        elif kind == "code_generated":
            evidence.update(
                invocation_type="reference_process",
                invocation_id=f"invocation-{index}",
                dependency_id=binding["dependency_id"],
                approved_entrypoint=binding["entrypoint"],
                producer_version=binding["producer_version"],
                brief_sha256=binding["brief_sha256"],
                primary_renderer=binding["primary_renderer"],
                renderer_version=binding["renderer_version"],
                exit_code=0,
                timed_out=False,
                unresolved_process_group=False,
            )
        elif kind == "ai_generated":
            evidence.update(
                provider=binding["provider"],
                model=binding["model"],
                endpoint_id=binding["endpoint_id"],
            )

        window = component["render_window"]
        artifacts.append(
            {
                "schema_version": 1,
                "status": "success",
                "job_id": job.job_id,
                "segment_id": segment["segment_id"],
                "component_id": component_id,
                "kind": kind,
                "strategy_revision": recipe["strategy_revision"],
                "media_type": "image",
                "render_window": copy.deepcopy(window),
                "z_index": window["z_index"],
                "layout_slot": window["layout_slot"],
                "opacity": window["opacity"],
                "safe_zone": copy.deepcopy(window["safe_zone"]),
                "artifact_contract": copy.deepcopy(component["artifact_contract"]),
                "source_media_type": component["media_type"],
                "artifact_media_type": "image",
                "media_probe": {
                    "media_type": "image",
                    "container": "png",
                    "codec": "png",
                    "pixel_format": (
                        "rgba" if component["artifact_contract"]["alpha"] else "rgb24"
                    ),
                    "alpha": component["artifact_contract"]["alpha"],
                    "width": 1080,
                    "height": 1920,
                    "fps": None,
                    "frame_count": 1,
                    "duration": None,
                },
                "input_sha256": contract_artifacts.sha256_json(
                    {"recipe": recipe, "component_id": component_id}
                ),
                "job_path": final.relative_to(root).as_posix(),
                "byte_count": final.stat().st_size,
                "output_sha256": _sha256(final),
                "invocation_evidence": evidence,
                "qa": {"passed": True, "checks": ["component_output"]},
                "error_code": None,
            }
        )

    unsigned_plan = {
        key: value for key, value in plan.items() if key != "visual_plan_sha256"
    }
    plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned_plan)
    asset_base = {
        "schema_version": 3,
        "renderer_contract_version": segment_render.RENDERER_CONTRACT_VERSION,
        "job_id": job.job_id,
        "visual_plan_sha256": plan["visual_plan_sha256"],
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "duration": 3.0,
        "reused_canary_segment_ids": [],
        "segments": [
            {
                "segment_id": segment["segment_id"],
                "component_artifacts": artifacts,
            }
        ],
        "visual_track": {
            "path": "09-visual-assets/visual-track.mp4",
            "sha256": "a" * 64,
            "bytes": 1,
        },
    }
    asset_manifest = {
        **asset_base,
        "asset_manifest_sha256": contract_artifacts.sha256_json(asset_base),
    }
    return job, plan, asset_manifest


def _output_probe(frames: int = 72) -> dict[str, object]:
    return {
        "width": 1080,
        "height": 1920,
        "r_frame_rate": "24/1",
        "nb_read_frames": str(frames),
        "duration": frames / 24,
        "codec_name": "h264",
        "pix_fmt": "yuv420p",
    }


def _publish_rendered_manifest(
    root: Path,
    job: SimpleNamespace,
    plan: dict[str, object],
    asset_manifest: dict[str, object],
) -> None:
    arroll = _write(root / "06-edit-structure/edited-aroll.mp4", b"arroll")
    plan["edited_aroll_sha256"] = _sha256(arroll)
    for key in ("visual_strategy", "shot_recipe"):
        composition = plan["segments"][0][key]["composition"]
        if composition.get("presenter_mode") == "bottom_window":
            composition["avatar"]["profile"]["source_sha256"] = _sha256(arroll)
    unsigned_plan = {
        key: value for key, value in plan.items() if key != "visual_plan_sha256"
    }
    plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned_plan)
    segment = plan["segments"][0]
    recipe = segment["shot_recipe"]
    for value in asset_manifest["segments"][0]["component_artifacts"]:
        value["input_sha256"] = segment_render._input_sha(
            recipe, value["component_id"]
        )
    artifacts = tuple(
        broll_component_executor.ComponentArtifact(**value)
        for value in asset_manifest["segments"][0]["component_artifacts"]
    )

    def runner(command: tuple[str, ...], _timeout: float) -> None:
        Path(command[-1]).write_bytes(b"rendered-segment")

    def extract(_video: Path, timestamp: float, output: Path) -> None:
        output.write_bytes(f"frame:{timestamp:.6f}".encode())

    rendered = segment_render.render_segment_video(
        job,
        segment,
        artifacts,
        output_dir=root / "09-visual-assets/segments",
        visual_plan_sha256=plan["visual_plan_sha256"],
        arroll_source=arroll,
        arroll_sha256=_sha256(arroll),
        arroll_bytes=arroll.stat().st_size,
        ffmpeg_runner=runner,
        probe=lambda _path: _output_probe(),
        frame_extractor=extract,
    )
    asset_manifest["visual_plan_sha256"] = plan["visual_plan_sha256"]
    asset_manifest["segments"] = [asdict(rendered)]
    asset_base = {
        key: value
        for key, value in asset_manifest.items()
        if key != "asset_manifest_sha256"
    }
    asset_manifest["asset_manifest_sha256"] = contract_artifacts.sha256_json(
        asset_base
    )


def _preview_job(
    root: Path,
    plan: dict[str, object],
    asset_manifest: dict[str, object],
) -> SimpleNamespace:
    root = root.resolve()
    source_job = SimpleNamespace(
        job_dir=root,
        job_id="job-source-manifest-001",
        version=2,
    )
    if "video_path" not in asset_manifest["segments"][0]:
        _publish_rendered_manifest(
            root, source_job, plan, asset_manifest
        )
    paths = {
        "visual_direction": _write(
            root / "07-visual-direction/visual-plan.json",
            contract_artifacts.canonical_json_bytes(plan) + b"\n",
        ),
        "visual_track": _write(root / "09-visual-assets/visual-track.mp4", b"visual"),
        "asset_manifest": _write(
            root / "09-visual-assets/asset-manifest.json",
            contract_artifacts.canonical_json_bytes(asset_manifest) + b"\n",
        ),
        "subtitle_track": _write(root / "10-subtitles/subtitles.webm", b"subtitles"),
        "subtitle_plan": _write(
            root / "10-subtitles/subtitle-plan.json",
            b'{"subtitle_plan_sha256":"' + b"b" * 64 + b'"}\n',
        ),
        "arroll": root / "06-edit-structure/edited-aroll.mp4",
        "cover": _write(root / "04-cover/cover.png", b"cover"),
    }
    return SimpleNamespace(
        job_dir=root,
        job_id="job-source-manifest-001",
        revision=4,
        version=2,
        stages={
            "preview": {"status": "pending", "artifacts": []},
            "visual_direction": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["visual_direction"], root)],
            },
            "visual_assets": {
                "status": "approved",
                "artifacts": [
                    _artifact_record(paths["visual_track"], root),
                    _artifact_record(paths["asset_manifest"], root),
                ],
            },
            "subtitles": {
                "status": "approved",
                "artifacts": [
                    _artifact_record(paths["subtitle_track"], root),
                    _artifact_record(paths["subtitle_plan"], root),
                ],
            },
            "edit_structure": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["arroll"], root)],
            },
            "cover": {
                "status": "approved",
                "artifacts": [_artifact_record(paths["cover"], root)],
            },
        },
    )


def _pending_preview_job(root: Path) -> SimpleNamespace:
    _source_job, plan, asset_manifest = _source_fixture(root)
    job = _preview_job(root, plan, asset_manifest)
    subtitle_plan = {
        "subtitle_plan_sha256": "b" * 64,
        "visual_plan_sha256": plan["visual_plan_sha256"],
        "schema_version": 4,
        "render_plan": {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 72}, "cues": []},
    }
    from edit.hd.tools import talkcraft_subtitles
    subtitle_plan["renderer_input"] = talkcraft_subtitles.renderer_input(subtitle_plan["render_plan"], [])
    subtitle_plan["renderer"] = talkcraft_subtitles.identity(subtitle_plan["renderer_input"], subtitle_plan["render_plan"])
    _rewrite_approved_json(
        job,
        "subtitles",
        "10-subtitles/subtitle-plan.json",
        subtitle_plan,
    )
    return job


def _set_reusable_preview(
    job: SimpleNamespace,
    source_manifest: dict[str, object],
) -> dict[str, Path]:
    root = Path(job.job_dir)
    review = _write(root / "11-preview/review.mp4", b"review")
    source = _write(
        root / "11-preview/source-manifest.json",
        contract_artifacts.canonical_json_bytes(source_manifest) + b"\n",
    )
    keyframes = [
        _write(
            root / f"11-preview/keyframes/frame-{index:02d}.png",
            f"frame-{index}".encode(),
        )
        for index in range(1, 6)
    ]
    report_base = {
        "preview_sha256": _sha256(review),
        "source_manifest_sha256": source_manifest["source_manifest_sha256"],
        "media": {"frames": 72},
        "evidence": [
            {
                "path": f"keyframes/{path.name}",
                "sha256": _sha256(path),
            }
            for path in keyframes
        ],
    }
    report = {
        **report_base,
        "qa_report_sha256": contract_artifacts.sha256_json(report_base),
    }
    report_path = _write(
        root / "11-preview/qa-report.json",
        contract_artifacts.canonical_json_bytes(report) + b"\n",
    )
    paths = {
        "review": review,
        "source": source,
        "report": report_path,
        **{f"keyframe-{index}": path for index, path in enumerate(keyframes, 1)},
    }
    job.stages["preview"] = {
        "status": "ready_for_review",
        "artifacts": [
            _artifact_record(path, root)
            for path in paths.values()
        ],
    }
    return paths


class FormalPreviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        dependencies_for = material_usage.state.dependencies_for

        def compatible_dependencies(job, stage_id: str):
            if not isinstance(job, preview_v2.state.JobState) and stage_id == "preview":
                return ("cover", "edit_structure", "visual_assets", "subtitles")
            return dependencies_for(job, stage_id)

        patcher = mock.patch.object(
            material_usage.state,
            "dependencies_for",
            side_effect=compatible_dependencies,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # These SimpleNamespace fixtures exercise publication/recovery, not a
        # human-confirmed Job. Approval and badges have dedicated workflow tests.
        numbered = preview_v2.visual_confirmation.approved_numbered_rows
        check_content = preview_v2.confirmed_content.check_confirmed_content
        approved = preview_v2._approved

        def fixture_approved(job, stage, relative):
            if not isinstance(job, preview_v2.state.JobState) and stage not in getattr(job, 'stages', {}):
                path = Path(job.job_dir) / 'fixture-plan.json'
                path.write_text('{}')
                return path
            return approved(job, stage, relative)

        for target, name, function in (
            (preview_v2.visual_confirmation, 'approved_numbered_rows',
             lambda job: numbered(job) if isinstance(job, preview_v2.state.JobState) else []),
            (preview_v2.confirmed_content, 'check_confirmed_content',
             lambda job, plan: check_content(job, plan) if isinstance(job, preview_v2.state.JobState) else None),
            (preview_v2, '_approved', fixture_approved),
        ):
            boundary = mock.patch.object(target, name, side_effect=function)
            boundary.start()
            self.addCleanup(boundary.stop)

    @staticmethod
    def _preview_build_patches(job: SimpleNamespace):
        def compose(command, **_kwargs) -> mock.Mock:
            Path(command[-1]).write_bytes(b"review-video")
            return mock.Mock(returncode=0, stdout="")

        def extract(_video: Path, output: Path, _duration: float) -> list[Path]:
            output.mkdir()
            paths = []
            for index in range(1, 6):
                path = output / f"frame-{index:02d}.png"
                path.write_bytes(f"frame-{index}".encode())
                paths.append(path)
            return paths

        def mark_ready(_job, _stage_id: str, artifacts) -> None:
            _job.revision += 1
            _job.stages["preview"].update(
                status="ready_for_review",
                artifacts=[
                    _artifact_record(path, Path(_job.job_dir))
                    for path in artifacts
                ],
            )

        return (
            mock.patch.object(preview_v2.state, "require_runnable"),
            mock.patch.object(preview_v2.subprocess, "run", side_effect=compose),
            mock.patch.object(
                preview_v2,
                "_validate_media",
                return_value={
                    "width": 1080,
                    "height": 1920,
                    "fps": 24,
                    "frames": 72,
                    "duration": 3.0,
                    "video_streams": 1,
                    "audio_streams": 1,
                },
            ),
            mock.patch.object(preview_v2, "_extract_frames", side_effect=extract),
            mock.patch.object(preview_v2.state, "mark_ready", side_effect=mark_ready),
        )

    def test_pending_preview_publishes_complete_outputs_and_stage_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = _pending_preview_job(Path(directory))
            patches = self._preview_build_patches(job)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = preview_v2.prepare_preview_v2(job)

            expected = {
                "review.mp4",
                "qa-report.json",
                "source-manifest.json",
                "material-usage.json",
                *(f"keyframes/frame-{index:02d}.png" for index in range(1, 6)),
            }
            actual = {
                path.relative_to(result.directory).as_posix()
                for path in result.directory.rglob("*")
                if path.is_file()
            }
            self.assertEqual(expected, actual)
            self.assertEqual("ready_for_review", job.stages["preview"]["status"])
            self.assertEqual(
                expected,
                {
                    Path(record["path"]).relative_to("11-preview").as_posix()
                    for record in job.stages["preview"]["artifacts"]
                },
            )
            self.assertEqual(
                result.qa_report["source_manifest_sha256"],
                contract_artifacts.read_json_artifact(
                    result.directory / "source-manifest.json"
                )["source_manifest_sha256"],
            )
            receipt = material_usage.load_current_receipt(job, "preview")
            self.assertEqual([], receipt["references"])

    def test_mark_ready_failure_restores_previous_preview_and_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = _pending_preview_job(Path(directory))
            target = Path(job.job_dir) / "11-preview"
            target.mkdir()
            old = target / "previous.txt"
            old.write_bytes(b"previous-preview")
            previous_stage = copy.deepcopy(job.stages["preview"])
            patches = self._preview_build_patches(job)

            def reject(_job, _stage_id: str, _artifacts) -> None:
                _job.stages["preview"].update(status="ready_for_review")
                raise RuntimeError("workflow update rejected")

            with patches[0], patches[1], patches[2], patches[3], patches[4], mock.patch.object(
                preview_v2.state, "mark_ready", side_effect=reject
            ), self.assertRaisesRegex(RuntimeError, "workflow update rejected"):
                preview_v2.prepare_preview_v2(job)

            self.assertEqual(b"previous-preview", old.read_bytes())
            self.assertEqual(previous_stage, job.stages["preview"])
            self.assertFalse(any(Path(job.job_dir).glob(".11-preview.stage-*")))
            self.assertFalse(any(Path(job.job_dir).glob(".11-preview.backup-*")))
            self.assertFalse(
                (Path(job.job_dir) / ".11-preview.publication.json").exists()
            )

    def test_interrupted_preview_recovery_can_resume_after_another_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = _pending_preview_job(root)
            target = root / "11-preview"
            target.mkdir()
            previous = _write(target / "previous.txt", b"previous-preview")
            old_digest = preview_v2._preview_tree_digest(target)
            stage = root / ".11-preview.stage-recovery"
            stage.mkdir()
            _write(stage / "review.mp4", b"new-preview")
            new_digest = preview_v2._preview_tree_digest(stage)
            backup = root / ".11-preview.backup-recovery"
            os.replace(target, backup)
            os.replace(stage, target)
            preview_v2._write_preview_journal(
                root,
                {
                    "schema_version": 1,
                    "state": "installed",
                    "stage_name": stage.name,
                    "backup_name": backup.name,
                    "had_target": True,
                    "old_tree_sha256": old_digest,
                    "new_tree_sha256": new_digest,
                },
            )
            replace = os.replace

            def interrupt_restore(source, destination) -> None:
                if Path(source) == backup and Path(destination) == target:
                    raise OSError("recovery interrupted")
                replace(source, destination)

            with mock.patch.object(
                preview_v2.os, "replace", side_effect=interrupt_restore
            ), self.assertRaisesRegex(OSError, "recovery interrupted"):
                preview_v2.prepare_preview_v2(job)

            self.assertFalse(target.exists())
            self.assertTrue(backup.exists())
            self.assertTrue((root / ".11-preview.publication.json").exists())

            with mock.patch.object(
                preview_v2.state,
                "require_runnable",
                side_effect=RuntimeError("stop after recovery"),
            ), self.assertRaisesRegex(RuntimeError, "stop after recovery"):
                preview_v2.prepare_preview_v2(job)

            self.assertEqual(b"previous-preview", previous.read_bytes())
            self.assertFalse(backup.exists())
            self.assertFalse((root / ".11-preview.publication.json").exists())

    def test_interrupted_install_restores_then_publishes_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = _pending_preview_job(root)
            target = root / "11-preview"
            target.mkdir()
            _write(target / "previous.txt", b"previous-preview")
            replace = os.replace

            def interrupt_install(source, destination) -> None:
                source_path = Path(source)
                if (
                    source_path.name.startswith(".11-preview.stage-")
                    and Path(destination) == target
                ):
                    raise OSError("preview install interrupted")
                replace(source, destination)

            patches = self._preview_build_patches(job)
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                mock.patch.object(
                    preview_v2.os, "replace", side_effect=interrupt_install
                ),
                self.assertRaisesRegex(OSError, "preview install interrupted"),
            ):
                preview_v2.prepare_preview_v2(job)

            self.assertFalse(target.exists())
            self.assertTrue(any(root.glob(".11-preview.backup-*")))
            self.assertTrue((root / ".11-preview.publication.json").exists())

            retry_patches = self._preview_build_patches(job)
            with (
                retry_patches[0],
                retry_patches[1],
                retry_patches[2],
                retry_patches[3],
                retry_patches[4],
            ):
                result = preview_v2.prepare_preview_v2(job)

            self.assertEqual("ready_for_review", job.stages["preview"]["status"])
            self.assertTrue(result.review.is_file())
            self.assertFalse((target / "previous.txt").exists())
            self.assertFalse(any(root.glob(".11-preview.backup-*")))
            self.assertFalse((root / ".11-preview.publication.json").exists())

    def test_preview_calls_for_one_job_enter_publication_one_at_a_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = SimpleNamespace(job_dir=Path(directory).resolve())
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()
            results: list[str] = []
            errors: list[BaseException] = []

            def build(_job) -> str:
                if not first_entered.is_set():
                    first_entered.set()
                    if not release_first.wait(3):
                        raise RuntimeError("first publication did not resume")
                    return "first"
                second_entered.set()
                return "second"

            def invoke() -> None:
                try:
                    results.append(preview_v2.prepare_preview_v2(job))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                preview_v2, "_prepare_preview_v2_locked", side_effect=build
            ):
                first = threading.Thread(target=invoke)
                second = threading.Thread(target=invoke)
                first.start()
                self.assertTrue(first_entered.wait(1))
                second.start()
                self.assertFalse(second_entered.wait(0.1))
                release_first.set()
                first.join(3)
                second.join(3)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertCountEqual(["first", "second"], results)

    def test_preview_lock_closes_its_descriptor_when_acquisition_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real_close = os.close
            with mock.patch.object(
                preview_v2.fcntl,
                "flock",
                side_effect=OSError("lock acquisition stopped"),
            ), mock.patch.object(
                preview_v2.os, "close", wraps=real_close
            ) as close:
                for _index in range(20):
                    lock = preview_v2._PreviewLock(Path(directory))
                    with self.assertRaisesRegex(OSError, "lock acquisition stopped"):
                        lock.__enter__()
                    self.assertIsNone(lock.descriptor)
            self.assertEqual(20, close.call_count)

    def test_preview_journal_accepts_only_direct_job_child_names(self) -> None:
        cases = (
            ("stage_name", ".11-preview.stage-x/../../other-tree"),
            ("stage_name", ".11-preview.stage-x\\other-tree"),
            ("backup_name", ".11-preview.backup-x/../../other-tree"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                job_dir = root / "job"
                job_dir.mkdir()
                other = root / "other-tree"
                other.mkdir()
                sentinel = _write(other / "sentinel.bin", b"other-tree")
                digest = preview_v2._preview_tree_digest(other)
                had_target = field == "backup_name"
                payload = {
                    "schema_version": 1,
                    "state": "installed",
                    "stage_name": (
                        value if field == "stage_name" else ".11-preview.stage-valid"
                    ),
                    "backup_name": value if had_target else None,
                    "had_target": had_target,
                    "old_tree_sha256": digest if had_target else None,
                    "new_tree_sha256": digest,
                }
                contract_artifacts.write_json_artifact(
                    job_dir / ".11-preview.publication.json", payload
                )
                job = SimpleNamespace(
                    job_dir=job_dir,
                    version=2,
                    stages={"preview": {"status": "pending", "artifacts": []}},
                )
                error = None
                try:
                    with mock.patch.object(
                        preview_v2.state,
                        "require_runnable",
                        side_effect=RuntimeError("stop after recovery"),
                    ):
                        preview_v2.prepare_preview_v2(job)
                except BaseException as exc:
                    error = exc

                self.assertIsInstance(error, preview_v2.PreviewV2Error)
                self.assertEqual(b"other-tree", sentinel.read_bytes())

    def test_preview_uses_only_edited_aroll_audio_without_background_music(self) -> None:
        command = preview_v2.build_preview_command_v2(
            Path("visual.mp4"),
            Path("subtitles.webm"),
            Path("edited-aroll.mp4"),
            Path("review.mp4"),
            frames=96,
            duration=4.0,
        )

        self.assertEqual(command.count("-i"), 3)
        self.assertIn("2:a:0", command)
        self.assertNotIn("amix", " ".join(command))
        self.assertNotIn("music", " ".join(command).lower())
        self.assertIn("fps=24", " ".join(command))
        # Mixed native color metadata must not reset frame/subtitle clocks.
        self.assertEqual(command.count("-reinit_filter"), 2)
        for index, value in enumerate(command):
            if value == "-reinit_filter":
                self.assertEqual(command[index + 1], "0")

    def test_cover_preview_bounds_encoder_threads_without_changing_clock_or_quality(self) -> None:
        command = preview_v2.build_preview_command_v2(
            Path("visual.mp4"), Path("subtitles.webm"),
            Path("edited-aroll.mp4"), Path("review.mp4"),
            frames=96, duration=4.0, cover=Path("cover.png"),
            opening={"body_frames": 96, "body_offset_frames": 4,
                     "total_frames": 100, "options": {"transition_frames": 0}},
        )
        self.assertEqual(
            [command[i + 1] for i, value in enumerate(command) if value == "-threads"],
            ["1", "1", "1", "4"],
        )
        for flag, expected in (("-filter_complex_threads", "1"), ("-preset", "medium"),
                               ("-crf", "18"), ("-frames:v", "100")):
            self.assertEqual(command[command.index(flag) + 1], expected)
        self.assertIn("[outa]", command)
        self.assertIn("adelay=8000S:all=1", command[command.index("-filter_complex") + 1])

    def test_real_v2_preview_has_exact_frames_and_one_aroll_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            visual = root / "visual.mp4"
            subtitles = root / "subtitles.webm"
            arroll = root / "edited-aroll.mp4"
            output = root / "review.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=24:d=1",
                    "-frames:v", "24", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-y", str(visual),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=24:d=1",
                    "-frames:v", "24", "-c:v", "libvpx-vp9", "-deadline", "realtime",
                    "-cpu-used", "8", "-pix_fmt", "yuv420p", "-y", str(subtitles),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=1080x1920:r=24:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-frames:v", "24", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-shortest", "-y", str(arroll),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )

            subprocess.run(
                preview_v2.build_preview_command_v2(
                    visual,
                    subtitles,
                    arroll,
                    output,
                    frames=24,
                    duration=1.0,
                ),
                check=True,
                capture_output=True,
                timeout=180,
            )

            media = preview_v2._validate_media(output, frames=24, duration=1.0)
            self.assertEqual(24, media["frames"])
            self.assertEqual(1, media["video_streams"])
            self.assertEqual(1, media["audio_streams"])
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-i", str(output), "-f", "null", "-",
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )

            def audio_probe(path: Path) -> dict[str, object]:
                result = subprocess.run(
                    [
                        "ffprobe", "-v", "error", "-count_packets",
                        "-select_streams", "a:0", "-show_entries",
                        "stream=codec_type,sample_rate,channels,nb_read_packets,duration",
                        "-of", "json", str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                return json.loads(result.stdout)["streams"][0]

            arroll_audio = audio_probe(arroll)
            preview_audio = audio_probe(output)
            self.assertEqual("audio", preview_audio["codec_type"])
            self.assertEqual(arroll_audio["sample_rate"], preview_audio["sample_rate"])
            self.assertEqual(arroll_audio["channels"], preview_audio["channels"])
            self.assertLessEqual(
                abs(
                    int(arroll_audio["nb_read_packets"])
                    - int(preview_audio["nb_read_packets"])
                ),
                1,
            )
            self.assertLessEqual(
                abs(float(arroll_audio["duration"]) - float(preview_audio["duration"])),
                1 / 24 + 0.01,
            )

    def test_preview_rejects_non_frame_aligned_duration(self) -> None:
        with self.assertRaisesRegex(preview_v2.PreviewV2Error, "clock"):
            preview_v2.build_preview_command_v2(
                Path("visual.mp4"),
                Path("subtitles.webm"),
                Path("edited-aroll.mp4"),
                Path("review.mp4"),
                frames=95,
                duration=4.0,
            )

    def test_source_manifest_matches_every_recipe_component_and_same_kind_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(
                root, ("official_material", "code_generated")
            )
            candidates = plan["segments"][0]["candidate_snapshots"]["component-1"]
            candidates.append(
                {
                    **copy.deepcopy(candidates[0]),
                    "asset_id": "official-alternative",
                    "semantic_match_score": 0.7,
                }
            )
            unsigned = {
                key: value
                for key, value in plan.items()
                if key != "visual_plan_sha256"
            }
            plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
            asset_manifest["visual_plan_sha256"] = plan["visual_plan_sha256"]
            asset_base = {
                key: value
                for key, value in asset_manifest.items()
                if key != "asset_manifest_sha256"
            }
            asset_manifest["asset_manifest_sha256"] = (
                contract_artifacts.sha256_json(asset_base)
            )

            manifest = preview_v2.build_source_manifest(job, plan, asset_manifest)

            self.assertEqual(
                ["component-1", "component-2"],
                [record["component_id"] for record in manifest["components"]],
            )
            official, code = manifest["components"]
            self.assertEqual("official_material", official["provenance"]["kind"])
            self.assertEqual("asset-1", official["source_asset_id"])
            self.assertEqual(
                [
                    {
                        "asset_id": "official-alternative",
                        "kind": "official_material",
                        "reason": "ranked_after_selected_same_kind_candidate",
                    }
                ],
                official["not_selected_candidates"],
            )
            self.assertEqual("invocation", code["activity_record"]["type"])
            self.assertEqual("html-video", code["activity_record"]["dependency_id"])
            self.assertEqual("invocation-2", code["activity_record"]["invocation_id"])
            self.assertEqual(
                contract_artifacts.sha256_json(
                    asset_manifest["segments"][0]["component_artifacts"][1]["invocation_evidence"]
                ),
                code["activity_record"]["invocation_evidence_sha256"],
            )
            self.assertTrue(
                all(record["qa"]["passed"] for record in manifest["components"])
            )
            self.assertIs(
                manifest,
                preview_v2.validate_source_manifest(
                    root,
                    manifest,
                    job_id=job.job_id,
                    visual_plan_sha256=plan["visual_plan_sha256"],
                    asset_manifest_sha256=asset_manifest["asset_manifest_sha256"],
                ),
            )

    def test_source_manifest_rejects_code_invocation_from_another_dependency(self) -> None:
        for field, value in (("dependency_id", "another-skill"), ("exit_code", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                job, plan, asset_manifest = _source_fixture(root, ("code_generated",))
                evidence = asset_manifest["segments"][0]["component_artifacts"][0]["invocation_evidence"]
                evidence[field] = value
                base = {key: value for key, value in asset_manifest.items() if key != "asset_manifest_sha256"}
                asset_manifest["asset_manifest_sha256"] = contract_artifacts.sha256_json(base)

                with self.assertRaisesRegex(
                    preview_v2.PreviewV2Error, "^BROLL_SOURCE_MANIFEST_BLOCKED$"
                ):
                    preview_v2.build_source_manifest(job, plan, asset_manifest)

    def test_source_manifest_records_stock_license_and_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(
                root, attribution_required=True
            )

            manifest = preview_v2.build_source_manifest(job, plan, asset_manifest)

            record = manifest["components"][0]
            self.assertEqual("download", record["activity_record"]["type"])
            self.assertEqual("Example Stock", record["attribution"]["provider"])
            self.assertEqual("Example Author", record["attribution"]["author"])
            self.assertEqual(
                "Example Stock License", record["attribution"]["license"]
            )
            self.assertTrue(record["attribution"]["required"])

    def test_stock_license_bytes_must_match_the_current_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(root)
            component = plan["segments"][0]["shot_recipe"]["components"][0]
            license_path = root / component["license_snapshot"]
            license_record = contract_artifacts.read_json_artifact(license_path)
            license_record["byte_count"] += 1
            license_path.write_bytes(
                contract_artifacts.canonical_json_bytes(license_record) + b"\n"
            )

            with self.assertRaisesRegex(
                preview_v2.PreviewV2Error, "^BROLL_SOURCE_MANIFEST_BLOCKED$"
            ):
                preview_v2.build_source_manifest(job, plan, asset_manifest)

    def test_source_manifest_accepts_asset_page_query_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(root)
            plan["segments"][0]["bindings"]["component-1"]["asset_page"] += (
                "?collection=training&position=1"
            )
            plan["segments"][0]["shot_recipe"]["components"][0][
                "asset_page"
            ] += "?collection=training&position=1"
            component = plan["segments"][0]["shot_recipe"]["components"][0]
            license_path = root / component["license_snapshot"]
            license_record = contract_artifacts.read_json_artifact(license_path)
            license_record["asset_page"] = component["asset_page"]
            license_path.write_bytes(
                contract_artifacts.canonical_json_bytes(license_record) + b"\n"
            )
            unsigned = {
                key: value
                for key, value in plan.items()
                if key != "visual_plan_sha256"
            }
            plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
            asset_manifest["visual_plan_sha256"] = plan["visual_plan_sha256"]
            recipe = plan["segments"][0]["shot_recipe"]
            asset_manifest["segments"][0]["component_artifacts"][0][
                "input_sha256"
            ] = contract_artifacts.sha256_json(
                {"recipe": recipe, "component_id": "component-1"}
            )
            asset_base = {
                key: value
                for key, value in asset_manifest.items()
                if key != "asset_manifest_sha256"
            }
            asset_manifest["asset_manifest_sha256"] = (
                contract_artifacts.sha256_json(asset_base)
            )

            manifest = preview_v2.build_source_manifest(
                job, plan, asset_manifest
            )

            self.assertEqual(
                "https://stock.example/assets/asset-1"
                "?collection=training&position=1",
                manifest["components"][0]["attribution"]["asset_page"],
            )

    def test_preview_replays_complete_component_layout_and_qa_records(self) -> None:
        mutations = (
            lambda artifact: artifact.update(z_index=99),
            lambda artifact: artifact.update(layout_slot="annotation"),
            lambda artifact: artifact.update(
                qa={"passed": True, "checks": ["changed-record"]}
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _job, plan, asset_manifest = _source_fixture(root)
                job = _preview_job(root, plan, asset_manifest)
                artifact = asset_manifest["segments"][0]["component_artifacts"][0]
                mutate(artifact)
                asset_base = {
                    key: value
                    for key, value in asset_manifest.items()
                    if key != "asset_manifest_sha256"
                }
                asset_manifest["asset_manifest_sha256"] = (
                    contract_artifacts.sha256_json(asset_base)
                )
                _rewrite_approved_json(
                    job,
                    "visual_assets",
                    "09-visual-assets/asset-manifest.json",
                    asset_manifest,
                )

                with mock.patch.object(
                    preview_v2.segment_render,
                    "_default_probe",
                    return_value=_output_probe(),
                ), mock.patch.object(
                    preview_v2.state, "require_runnable"
                ), mock.patch.object(
                    preview_v2.subprocess, "run"
                ) as runner, self.assertRaisesRegex(
                    preview_v2.PreviewV2Error,
                    "^BROLL_SOURCE_MANIFEST_BLOCKED$",
                ):
                    preview_v2.prepare_preview_v2(job)

                runner.assert_not_called()

    def test_preview_replays_code_dependency_and_every_kind_activity_record(self) -> None:
        kinds = (
            "local_material",
            "official_material",
            "external_stock",
            "code_generated",
            "ai_generated",
        )
        for kind in kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected_kinds = (
                    ("external_stock", "code_generated")
                    if kind == "code_generated"
                    else (kind,)
                )
                _job, plan, asset_manifest = _source_fixture(
                    root, selected_kinds
                )
                job = _preview_job(root, plan, asset_manifest)
                artifact = asset_manifest["segments"][0]["component_artifacts"][-1]
                if kind == "code_generated":
                    artifact["invocation_evidence"]["dependency_id"] = (
                        "another-code-dependency"
                    )
                else:
                    artifact["invocation_evidence"]["record_revision"] = (
                        "changed-record"
                    )
                asset_base = {
                    key: value
                    for key, value in asset_manifest.items()
                    if key != "asset_manifest_sha256"
                }
                asset_manifest["asset_manifest_sha256"] = (
                    contract_artifacts.sha256_json(asset_base)
                )
                _rewrite_approved_json(
                    job,
                    "visual_assets",
                    "09-visual-assets/asset-manifest.json",
                    asset_manifest,
                )

                with mock.patch.object(
                    preview_v2.segment_render,
                    "_default_probe",
                    return_value=_output_probe(),
                ), mock.patch.object(
                    preview_v2.state, "require_runnable"
                ), mock.patch.object(
                    preview_v2.subprocess, "run"
                ) as runner, self.assertRaisesRegex(
                    preview_v2.PreviewV2Error,
                    "^BROLL_SOURCE_MANIFEST_BLOCKED$",
                ):
                    preview_v2.prepare_preview_v2(job)

                runner.assert_not_called()

    def test_source_manifest_blocks_incomplete_mapping_hash_and_job_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutators = (
                lambda manifest: manifest["segments"][0].update(
                    component_artifacts=[]
                ),
                lambda manifest: manifest["segments"][0]["component_artifacts"][
                    0
                ].update(output_sha256=""),
                lambda manifest: manifest["segments"][0]["component_artifacts"][
                    0
                ].update(job_path="../outside.png"),
            )
            for index, mutate in enumerate(mutators):
                case_root = root / f"case-{index}"
                job, plan, asset_manifest = _source_fixture(case_root)
                mutate(asset_manifest)
                asset_base = {
                    key: value
                    for key, value in asset_manifest.items()
                    if key != "asset_manifest_sha256"
                }
                asset_manifest["asset_manifest_sha256"] = (
                    contract_artifacts.sha256_json(asset_base)
                )
                with self.subTest(index=index), self.assertRaisesRegex(
                    preview_v2.PreviewV2Error, "^BROLL_SOURCE_MANIFEST_BLOCKED$"
                ):
                    preview_v2.build_source_manifest(job, plan, asset_manifest)

    def test_source_manifest_validator_requires_the_complete_kind_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(
                root, attribution_required=True
            )
            original = preview_v2.build_source_manifest(job, plan, asset_manifest)
            mutators = (
                lambda record: record.update(activity_record={}),
                lambda record: record["provenance"].update(source_bytes=None),
                lambda record: record["source_time"].update(value=""),
                lambda record: record["attribution"].update(provider=""),
            )
            for mutate in mutators:
                changed = copy.deepcopy(original)
                mutate(changed["components"][0])
                unsigned = {
                    key: value
                    for key, value in changed.items()
                    if key != "source_manifest_sha256"
                }
                changed["source_manifest_sha256"] = (
                    contract_artifacts.sha256_json(unsigned)
                )
                with self.subTest(mutate=mutate), self.assertRaisesRegex(
                    preview_v2.PreviewV2Error, "^BROLL_SOURCE_MANIFEST_BLOCKED$"
                ):
                    preview_v2.validate_source_manifest(root, changed)

    def test_source_manifest_requires_the_current_asset_manifest_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, asset_manifest = _source_fixture(root)
            asset_manifest["schema_version"] = 2
            unsigned = {
                key: value
                for key, value in asset_manifest.items()
                if key != "asset_manifest_sha256"
            }
            asset_manifest["asset_manifest_sha256"] = (
                contract_artifacts.sha256_json(unsigned)
            )

            with self.assertRaisesRegex(
                preview_v2.PreviewV2Error, "^BROLL_SOURCE_MANIFEST_BLOCKED$"
            ):
                preview_v2.build_source_manifest(job, plan, asset_manifest)

    def test_rendered_manifest_validates_formal_reuse_identities(self) -> None:
        from edit.hd.tools import visual_assets_v2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job, plan, manifest = _source_fixture(root)
            source = _write(root / "06-edit-structure/edited-aroll.mp4", b"aroll")
            manifest["reused_formal_segment_ids"] = []
            manifest["segment_input_identities"] = {
                segment["segment_id"]: visual_assets_v2._segment_input_identity(plan, segment)
                for segment in plan["segments"]
            }
            variants = [None, "frame_float", "duration", "identity", "unknown",
                        "duplicate", "overlap", "partial"]
            for variant in variants:
                with self.subTest(variant=variant):
                    value = copy.deepcopy(manifest)
                    plan_value = copy.deepcopy(plan)
                    segment_id = plan["segments"][0]["segment_id"]
                    if variant == "frame_float":
                        plan_value["duration"] = math.nextafter(float(plan["duration"]), 0.0)
                    elif variant == "duration":
                        value["duration"] = float(value["duration"]) + 1 / 24
                    elif variant == "identity":
                        value["segment_input_identities"][segment_id] = "0" * 64
                    elif variant == "unknown":
                        value["reused_formal_segment_ids"] = ["unknown"]
                    elif variant == "duplicate":
                        value["reused_formal_segment_ids"] = [segment_id, segment_id]
                    elif variant == "overlap":
                        value["reused_formal_segment_ids"] = [segment_id]
                        value["reused_canary_segment_ids"] = [segment_id]
                    elif variant == "partial":
                        del value["segment_input_identities"]
                    value["asset_manifest_sha256"] = contract_artifacts.sha256_json({
                        key: item for key, item in value.items() if key != "asset_manifest_sha256"
                    })
                    with mock.patch.object(preview_v2, "_job_file", return_value=source), mock.patch.object(
                        segment_render, "load_rendered_segment_replay"
                    ):
                        if variant in (None, "frame_float"):
                            preview_v2._validate_rendered_asset_manifest(job, plan_value, value, source)
                        else:
                            with self.assertRaises(preview_v2.PreviewV2Error):
                                preview_v2._validate_rendered_asset_manifest(job, plan_value, value, source)

    def test_reusable_preview_rechecks_every_approved_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _source_job, plan, asset_manifest = _source_fixture(root)
            job = _preview_job(root, plan, asset_manifest)
            source_manifest = preview_v2.build_source_manifest(
                job, plan, asset_manifest
            )
            source_manifest["components"] = []
            source_base = {
                key: value
                for key, value in source_manifest.items()
                if key != "source_manifest_sha256"
            }
            source_manifest["source_manifest_sha256"] = (
                contract_artifacts.sha256_json(source_base)
            )
            review = _write(root / "11-preview/review.mp4", b"review")
            source = _write(
                root / "11-preview/source-manifest.json",
                contract_artifacts.canonical_json_bytes(source_manifest) + b"\n",
            )
            report = {
                "preview_sha256": _sha256(review),
                "source_manifest_sha256": source_manifest[
                    "source_manifest_sha256"
                ],
                "media": {},
            }
            report_path = _write(
                root / "11-preview/qa-report.json",
                contract_artifacts.canonical_json_bytes(report) + b"\n",
            )
            job.stages["preview"] = {
                "status": "approved",
                "artifacts": [
                    _artifact_record(review, root),
                    _artifact_record(report_path, root),
                    _artifact_record(source, root),
                ],
            }

            with self.assertRaisesRegex(
                preview_v2.PreviewV2Error,
                "^BROLL_SOURCE_MANIFEST_BLOCKED$",
            ):
                preview_v2.prepare_preview_v2(job)

    def test_ready_for_review_preview_reuses_its_current_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _source_job, plan, asset_manifest = _source_fixture(root)
            job = _preview_job(root, plan, asset_manifest)
            source_manifest = preview_v2.build_source_manifest(
                job, plan, asset_manifest
            )
            paths = _set_reusable_preview(job, source_manifest)

            with mock.patch.object(
                preview_v2.segment_render,
                "_default_probe",
                side_effect=AssertionError("default probe must not run"),
            ) as default_probe, mock.patch.object(
                preview_v2.subprocess,
                "run",
                side_effect=AssertionError("subprocess must not run"),
            ) as runner:
                result = preview_v2.prepare_preview_v2(job)

            self.assertEqual(paths["review"].resolve(), result.review.resolve())
            self.assertEqual({"frames": 72}, result.media_summary)
            runner.assert_not_called()
            default_probe.assert_not_called()

    def test_reusable_preview_rechecks_every_published_file_and_exact_inventory(self) -> None:
        for name in ("review", "report", "source", "keyframe-3"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _source_job, plan, asset_manifest = _source_fixture(root)
                job = _preview_job(root, plan, asset_manifest)
                source_manifest = preview_v2.build_source_manifest(
                    job, plan, asset_manifest
                )
                paths = _set_reusable_preview(job, source_manifest)
                paths[name].write_bytes(b"changed-preview-evidence")

                with mock.patch.object(
                    preview_v2.segment_render,
                    "_default_probe",
                    side_effect=AssertionError("default probe must not run"),
                ) as default_probe, mock.patch.object(
                    preview_v2.subprocess,
                    "run",
                    side_effect=AssertionError("subprocess must not run"),
                ) as runner, self.assertRaises(preview_v2.PreviewV2Error):
                    preview_v2.prepare_preview_v2(job)

                default_probe.assert_not_called()
                runner.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _source_job, plan, asset_manifest = _source_fixture(root)
            job = _preview_job(root, plan, asset_manifest)
            source_manifest = preview_v2.build_source_manifest(
                job, plan, asset_manifest
            )
            _set_reusable_preview(job, source_manifest)
            _write(root / "11-preview/unrecorded.json", b"{}\n")

            with mock.patch.object(
                preview_v2.segment_render,
                "_default_probe",
                side_effect=AssertionError("default probe must not run"),
            ) as default_probe, mock.patch.object(
                preview_v2.subprocess,
                "run",
                side_effect=AssertionError("subprocess must not run"),
            ) as runner, self.assertRaises(preview_v2.PreviewV2Error):
                preview_v2.prepare_preview_v2(job)

            default_probe.assert_not_called()
            runner.assert_not_called()

    def test_source_time_matches_each_approved_source_record(self) -> None:
        kinds = (
            "local_material",
            "official_material",
            "external_stock",
            "code_generated",
            "ai_generated",
        )
        for kind in kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected_kinds = (
                    ("external_stock", "code_generated")
                    if kind == "code_generated"
                    else (kind,)
                )
                _source_job, plan, asset_manifest = _source_fixture(
                    root, selected_kinds
                )
                job = _preview_job(root, plan, asset_manifest)
                source_manifest = preview_v2.build_source_manifest(
                    job, plan, asset_manifest
                )
                record = next(
                    item
                    for item in source_manifest["components"]
                    if item["kind"] == kind
                )
                record["source_time"]["value"] = "2099-01-01T00:00:00+00:00"
                source_base = {
                    key: value
                    for key, value in source_manifest.items()
                    if key != "source_manifest_sha256"
                }
                source_manifest["source_manifest_sha256"] = (
                    contract_artifacts.sha256_json(source_base)
                )

                with mock.patch.object(
                    preview_v2.segment_render,
                    "_default_probe",
                    side_effect=AssertionError("default probe must not run"),
                ) as default_probe, self.assertRaisesRegex(
                    preview_v2.PreviewV2Error,
                    "^BROLL_SOURCE_MANIFEST_BLOCKED$",
                ):
                    preview_v2.validate_source_manifest_against_approved_sources(
                        job,
                        source_manifest,
                        plan,
                        asset_manifest,
                        arroll_source=Path(job.job_dir)
                        / "06-edit-structure/edited-aroll.mp4",
                    )
                default_probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()

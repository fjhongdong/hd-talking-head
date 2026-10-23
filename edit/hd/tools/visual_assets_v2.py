"""Formal visual-assets builder for approved ShotRecipe v2 generations."""

from __future__ import annotations

import copy
import contextlib
import fcntl
import os
import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from . import (
    contract_artifacts,
    material_usage,
    segment_render,
    state,
    variant_matrix,
    visual_canary,
)


class VisualAssetsV2Error(RuntimeError):
    """Raised when approved segment generations cannot be assembled exactly."""


PUBLICATION_JOURNAL_NAME = ".09-visual-assets.publication-journal.json"
_LOCK_NAME = ".09-visual-assets.lock"
_PUBLICATION_STATES = {
    "staged",
    "backed_up",
    "installed",
    "restoring",
    "restored",
}


@contextlib.contextmanager
def _visual_assets_writer(job: state.JobState):
    descriptor = os.open(
        job.job_dir / _LOCK_NAME,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _synchronize_job(target: state.JobState, current: state.JobState) -> None:
    target.root = current.root
    target.job_dir = current.job_dir
    target.job_id = current.job_id
    target.inputs = copy.deepcopy(current.inputs)
    target.revision = current.revision
    target.expected_revision = current.expected_revision
    target.expected_sha256 = current.expected_sha256
    target.expected_bytes = current.expected_bytes
    target.version = current.version
    target.stages.clear()
    target.stages.update(copy.deepcopy(current.stages))


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    directories = [root]
    for path in root.rglob("*"):
        if path.is_file():
            _fsync_file(path)
        elif path.is_dir():
            directories.append(path)
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(path)


def _journal_path(job: state.JobState) -> Path:
    return job.job_dir / PUBLICATION_JOURNAL_NAME


def _write_publication_journal(
    job: state.JobState,
    journal: Mapping[str, object],
    publication_state: str,
) -> dict[str, object]:
    if publication_state not in _PUBLICATION_STATES:
        raise VisualAssetsV2Error("visual-assets publication state is invalid")
    value = {**journal, "state": publication_state}
    contract_artifacts.write_json_artifact(_journal_path(job), value)
    _fsync_directory(job.job_dir)
    return value


def _clear_publication_journal(job: state.JobState) -> None:
    path = _journal_path(job)
    if path.exists():
        path.unlink()
        _fsync_directory(job.job_dir)


def _artifact_records_from_stage(
    job: state.JobState,
    stage: Path,
    target: Path,
    paths: list[Path],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        relative = path.relative_to(target)
        source = stage / relative
        records.append(
            {
                "path": path.relative_to(job.job_dir).as_posix(),
                "sha256": contract_artifacts.sha256_file(source),
                "bytes": source.stat().st_size,
            }
        )
    return records


def _journal_artifact_paths(
    job: state.JobState,
    records: object,
) -> list[Path]:
    if type(records) is not list:
        raise VisualAssetsV2Error("visual-assets publication journal is invalid")
    paths: list[Path] = []
    for record in records:
        if (
            type(record) is not dict
            or set(record) != {"path", "sha256", "bytes"}
            or type(record["path"]) is not str
            or type(record["sha256"]) is not str
            or len(record["sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in record["sha256"]
            )
            or type(record["bytes"]) is not int
            or record["bytes"] <= 0
        ):
            raise VisualAssetsV2Error("visual-assets publication journal is invalid")
        relative = PurePosixPath(record["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.parts[0] != "09-visual-assets"
            or ".." in relative.parts
        ):
            raise VisualAssetsV2Error("visual-assets publication journal is invalid")
        paths.append(job.job_dir.joinpath(*relative.parts))
    if len(paths) != len(set(paths)):
        raise VisualAssetsV2Error("visual-assets publication journal is invalid")
    return paths


def _publication_committed(
    job: state.JobState,
    records: list[dict[str, object]],
    paths: list[Path],
) -> bool:
    if job.stages["visual_assets"]["status"] not in {
        "ready_for_review",
        "approved",
    } or job.stages["visual_assets"].get("artifacts") != records:
        return False
    try:
        _confirm_formal_artifact_records(job, paths)
    except VisualAssetsV2Error:
        return False
    return True


def _records_match_target(
    job: state.JobState,
    records: list[dict[str, object]],
    paths: list[Path],
) -> bool:
    target = job.job_dir / "09-visual-assets"
    if not target.is_dir() or len(records) != len(paths):
        return False
    expected = set(paths)
    try:
        actual = {path for path in target.rglob("*") if path.is_file()}
        if actual != expected:
            return False
        return all(
            path.is_file()
            and record["sha256"] == contract_artifacts.sha256_file(path)
            and record["bytes"] == path.stat().st_size
            for record, path in zip(records, paths)
        )
    except (KeyError, OSError, TypeError):
        return False


def _current_generation_records(
    job: state.JobState,
) -> tuple[list[dict[str, object]], list[Path]] | None:
    stage = job.stages["visual_assets"]
    source = stage.get("artifacts") or stage.get("lineage")
    if type(source) is not list or not source:
        return None
    records = [
        {
            "path": record.get("path"),
            "sha256": record.get("sha256"),
            "bytes": record.get("bytes"),
        }
        for record in source
        if type(record) is dict
    ]
    if len(records) != len(source):
        return None
    try:
        paths = _journal_artifact_paths(job, records)
    except VisualAssetsV2Error:
        return None
    if not _records_match_target(job, records, paths):
        return None
    return records, paths


def _remove_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise VisualAssetsV2Error("visual-assets publication path is invalid")
        shutil.rmtree(path)


def _recover_publication(job: state.JobState) -> None:
    path = _journal_path(job)
    if not path.exists():
        return
    try:
        journal = contract_artifacts.read_json_artifact(path)
    except contract_artifacts.ContractArtifactError:
        raise VisualAssetsV2Error("visual-assets publication journal is invalid") from None
    expected_fields = {
        "schema_version",
        "job_id",
        "state",
        "target_name",
        "stage_name",
        "backup_name",
        "artifact_records",
    }
    if (
        type(journal) is not dict
        or set(journal) != expected_fields
        or journal.get("schema_version") != 1
        or journal.get("job_id") != job.job_id
        or journal.get("state") not in _PUBLICATION_STATES
        or journal.get("target_name") != "09-visual-assets"
        or type(journal.get("stage_name")) is not str
        or Path(str(journal["stage_name"])).name != journal["stage_name"]
        or not str(journal["stage_name"]).startswith(".09-visual-assets.stage-")
        or (
            journal.get("backup_name") is not None
            and (
                type(journal["backup_name"]) is not str
                or Path(str(journal["backup_name"])).name
                != journal["backup_name"]
                or not str(journal["backup_name"]).startswith(
                    ".09-visual-assets.backup-"
                )
            )
        )
    ):
        raise VisualAssetsV2Error("visual-assets publication journal is invalid")
    target = job.job_dir / str(journal["target_name"])
    stage = job.job_dir / str(journal["stage_name"])
    backup = (
        None
        if journal["backup_name"] is None
        else job.job_dir / str(journal["backup_name"])
    )
    records = journal["artifact_records"]
    paths = _journal_artifact_paths(job, records)
    publication_state = str(journal["state"])
    if publication_state == "installed" and _publication_committed(
        job,
        records,
        paths,
    ):
        if backup is not None:
            _remove_directory(backup)
        _remove_directory(stage)
        _clear_publication_journal(job)
        _fsync_directory(job.job_dir)
        return

    if publication_state == "staged" and (
        backup is None or not backup.exists()
    ):
        _remove_directory(stage)
        _clear_publication_journal(job)
        return

    current = _current_generation_records(job)
    if publication_state == "installed" and current is not None:
        current_records, _current_paths = current
        if current_records != records:
            raise VisualAssetsV2Error(
                "publication journal conflicts with current visual-assets generation"
            )

    if publication_state == "restored":
        if backup is not None and backup.exists():
            raise VisualAssetsV2Error("visual-assets publication layout is invalid")
        _remove_directory(stage)
        _clear_publication_journal(job)
        return

    if publication_state != "restoring":
        journal = _write_publication_journal(job, journal, "restoring")

    if backup is not None:
        if backup.exists():
            if not backup.is_dir():
                raise VisualAssetsV2Error("visual-assets publication layout is invalid")
            if target.exists():
                if not _records_match_target(job, records, paths):
                    raise VisualAssetsV2Error(
                        "visual-assets publication target does not match the journal"
                    )
                _remove_directory(target)
            os.replace(backup, target)
            _fsync_directory(job.job_dir)
        elif not target.exists() or _current_generation_records(job) is None:
            raise VisualAssetsV2Error("visual-assets restoration is incomplete")
    elif target.exists():
        if not _records_match_target(job, records, paths):
            raise VisualAssetsV2Error(
                "visual-assets publication target does not match the journal"
            )
        _remove_directory(target)
        _fsync_directory(job.job_dir)

    journal = _write_publication_journal(job, journal, "restored")
    _remove_directory(stage)
    _clear_publication_journal(job)


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _relocate(
    rendered: segment_render.RenderedSegment,
    destination: Path,
) -> segment_render.RenderedSegment:
    keyframes = {
        name: {
            **record,
            "path": str(destination / "keyframes" / f"{name}.png"),
        }
        for name, record in rendered.keyframes.items()
    }
    return replace(
        rendered,
        video_path=str(destination / "segment.mp4"),
        keyframes=keyframes,
    )


def _materialize_reused(
    rendered: segment_render.RenderedSegment,
    destination: Path,
) -> segment_render.RenderedSegment:
    source_video = Path(rendered.video_path)
    if (
        not source_video.is_file()
        or contract_artifacts.sha256_file(source_video) != rendered.video_sha256
        or source_video.stat().st_size != rendered.video_bytes
    ):
        raise VisualAssetsV2Error("approved segment bytes changed")
    destination.mkdir(parents=True, exist_ok=False)
    _copy_exact(source_video, destination / "segment.mp4")
    for name, record in rendered.keyframes.items():
        source = Path(str(record["path"]))
        if (
            not source.is_file()
            or contract_artifacts.sha256_file(source) != record["sha256"]
            or source.stat().st_size != record["bytes"]
        ):
            raise VisualAssetsV2Error("approved segment keyframe bytes changed")
        copied = destination / "keyframes" / f"{name}.png"
        _copy_exact(source, copied)
        if (
            contract_artifacts.sha256_file(copied) != record["sha256"]
            or copied.stat().st_size != record["bytes"]
        ):
            raise VisualAssetsV2Error("approved segment keyframe copy is incomplete")
    relocated = _relocate(rendered, destination)
    if (
        contract_artifacts.sha256_file(destination / "segment.mp4")
        != rendered.video_sha256
        or (destination / "segment.mp4").stat().st_size != rendered.video_bytes
    ):
        raise VisualAssetsV2Error("approved segment copy is incomplete")
    contract_artifacts.write_json_artifact(
        destination / "segment-manifest.json",
        asdict(relocated),
    )
    return relocated


def _segment_input_identity(plan: Mapping[str, Any], segment: Mapping[str, Any]) -> str:
    """Conservative reuse boundary, including upstream timeline/content identity."""
    return contract_artifacts.sha256_json({
        "segment": segment,
        "context": {
            key: plan[key]
            for key in (
                "canvas", "content_analysis_sha256", "edit_plan_sha256",
                "timeline_map_sha256", "edited_aroll_sha256",
            )
        },
        "renderer_contract_version": segment_render.RENDERER_CONTRACT_VERSION,
    })


def _manifest(
    job: state.JobState,
    plan: Mapping[str, Any],
    segments: list[segment_render.RenderedSegment],
    track_source: Path,
    track_path: Path,
    reused_canary_ids: list[str],
    reused_formal_ids: list[str],
) -> dict[str, Any]:
    base = {
        "schema_version": 3,
        "renderer_contract_version": segment_render.RENDERER_CONTRACT_VERSION,
        "job_id": job.job_id,
        "visual_plan_sha256": plan["visual_plan_sha256"],
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "duration": sum(item.frames for item in segments) / 24,
        "reused_canary_segment_ids": reused_canary_ids,
        "reused_formal_segment_ids": reused_formal_ids,
        "segment_input_identities": {
            item["segment_id"]: _segment_input_identity(plan, item)
            for item in plan["segments"]
        },
        "segments": [asdict(item) for item in segments],
        "visual_track": {
            "path": str(track_path),
            "sha256": contract_artifacts.sha256_file(track_source),
            "bytes": track_source.stat().st_size,
        },
    }
    return {**base, "asset_manifest_sha256": contract_artifacts.sha256_json(base)}


def _variant_matrix(
    job: state.JobState,
    plan: Mapping[str, Any],
    segments: list[segment_render.RenderedSegment],
) -> dict[str, Any]:
    """Publish one explicit visual candidate per segment for safe local reuse."""
    revision = str(plan["visual_plan_sha256"])
    targets: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for item in segments:
        segment_id = str(item.segment_id)
        target_id = f"segment-{segment_id}"
        candidate_id = f"candidate-{segment_id}-visual"
        targets.append({
            "target_id": target_id,
            "candidates": {"visual": candidate_id},
        })
        candidates.append({
            "candidate_id": candidate_id,
            "target_id": target_id,
            "slot": "visual",
            "status": "ready_for_review",
            "input_fingerprint": _segment_input_identity(
                plan,
                next(segment for segment in plan["segments"] if str(segment["segment_id"]) == segment_id),
            ),
            "artifact_sha256": item.video_sha256,
            "source_revision": revision,
            "reuse_from": None,
            "affected_scope": [segment_id],
            "approval": {
                "status": "ready_for_review",
                "stage": "visual_assets",
                "revision": revision,
                "receipt_sha256": None,
            },
        })
    return variant_matrix.build_variant_matrix(
        job_revision=revision,
        targets=targets,
        candidates=candidates,
    )


def _validate_manifest_identity(payload: Mapping[str, Any]) -> None:
    identity = payload.get("asset_manifest_sha256")
    base = {
        key: value for key, value in payload.items()
        if key != "asset_manifest_sha256"
    }
    if identity != contract_artifacts.sha256_json(base):
        raise VisualAssetsV2Error("visual-assets manifest identity changed")


def _confirm_formal_artifact_records(
    job: state.JobState,
    paths: list[Path],
) -> None:
    try:
        records = job.stages["visual_assets"].get("artifacts", [])
        expected = {
            path.relative_to(job.job_dir).as_posix(): path for path in paths
        }
        receipt_records = [
            record
            for record in records
            if type(record) is dict
            and record.get("path") == "09-visual-assets/material-usage.json"
        ]
        if len(receipt_records) > 1:
            raise VisualAssetsV2Error("visual-assets artifact records changed")
        if receipt_records:
            expected["09-visual-assets/material-usage.json"] = (
                Path(job.job_dir) / "09-visual-assets/material-usage.json"
            )
        if (
            type(records) is not list
            or len(records) != len(expected)
            or {
                record.get("path")
                for record in records
                if type(record) is dict
            }
            != set(expected)
        ):
            raise VisualAssetsV2Error("visual-assets artifact records changed")
        for record in records:
            path = expected[str(record["path"])]
            if (
                not path.is_file()
                or record.get("sha256") != contract_artifacts.sha256_file(path)
                or record.get("bytes") != path.stat().st_size
            ):
                raise VisualAssetsV2Error("visual-assets artifact records changed")
        if receipt_records:
            material_usage.load_current_receipt(job, "visual_assets")
    except VisualAssetsV2Error:
        raise
    except (KeyError, OSError, TypeError, ValueError):
        raise VisualAssetsV2Error("visual-assets artifact records changed") from None


def _load_segments(
    job: state.JobState,
    plan: Mapping[str, Any],
    target: Path,
    *,
    require_manifest: bool,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    canary_segment_ids: frozenset[str] = frozenset(),
) -> dict[str, segment_render.RenderedSegment]:
    manifest_path = target / "asset-manifest.json"
    if not manifest_path.is_file():
        # Job initialization creates the output directory eagerly. An empty
        # directory is not a prior generation and must not block first publish.
        has_prior_files = target.exists() and any(
            child.is_file() for child in target.rglob("*")
        )
        if require_manifest or has_prior_files:
            raise VisualAssetsV2Error("visual-assets manifest is unavailable")
        return {}
    try:
        payload = contract_artifacts.read_json_artifact(manifest_path)
        if (
            payload.get("schema_version") != 3
            or payload.get("job_id") != job.job_id
            or payload.get("renderer_contract_version")
            != segment_render.RENDERER_CONTRACT_VERSION
            or type(payload.get("segments")) is not list
        ):
            raise VisualAssetsV2Error("visual-assets manifest is invalid")
        _validate_manifest_identity(payload)
        changed_plan = payload.get("visual_plan_sha256") != plan["visual_plan_sha256"]
        if changed_plan and require_manifest:
            raise VisualAssetsV2Error("visual-assets manifest does not match the plan")
        if changed_plan and _current_generation_records(job) is None:
            raise VisualAssetsV2Error("previous visual-assets approval evidence changed")
        variant_path = target / "variant-matrix.json"
        if variant_path.is_file() and not changed_plan:
            try:
                variant_matrix.validate_variant_matrix(
                contract_artifacts.read_json_artifact(variant_path),
                    expected_job_revision=str(plan["visual_plan_sha256"]),
                )
            except (variant_matrix.VariantMatrixError, contract_artifacts.ContractArtifactError):
                raise VisualAssetsV2Error("visual-assets variant matrix is invalid") from None
        identities = payload.get("segment_input_identities")
        if type(identities) is not dict:
            raise VisualAssetsV2Error("visual-assets segment input identities are missing")
        plan_segments = {
            str(segment["segment_id"]): segment for segment in plan["segments"]
        }
        results: dict[str, segment_render.RenderedSegment] = {}
        seen: set[str] = set()
        for value in payload["segments"]:
            if type(value) is not dict:
                raise VisualAssetsV2Error("visual-assets segment manifest is invalid")
            identifier = value.get("segment_id")
            if type(identifier) is not str or identifier in seen or identifier not in identities:
                raise VisualAssetsV2Error("visual-assets segment list is invalid")
            seen.add(identifier)
            if changed_plan and (
                # A canary approved for the NEW plan supersedes older formal
                # bytes, even when this segment's declared recipe is unchanged.
                identifier in canary_segment_ids
                or identifier not in plan_segments
                or identities[identifier] != _segment_input_identity(plan, plan_segments[identifier])
            ):
                continue
            if (
                identifier not in plan_segments
                or identities[identifier] != _segment_input_identity(plan, plan_segments[identifier])
            ):
                raise VisualAssetsV2Error("visual-assets segment input identity changed")
            results[str(identifier)] = visual_canary.validate_rendered_segment(
                job,
                plan,
                plan_segments[str(identifier)],
                value,
                root=target / "segments",
                probe=probe,
            )
        if set(identities) != seen:
            raise VisualAssetsV2Error("visual-assets segment input list is invalid")
        if not changed_plan and set(results) != set(plan_segments):
            raise VisualAssetsV2Error("visual-assets segment list is incomplete")
        track = target / "visual-track.mp4"
        record = payload.get("visual_track")
        if (
            type(record) is not dict
            or record.get("path") != str(track)
            or not track.is_file()
            or record.get("sha256") != contract_artifacts.sha256_file(track)
            or record.get("bytes") != track.stat().st_size
        ):
            raise VisualAssetsV2Error("visual track bytes changed")
        if require_manifest:
            formal_paths = [manifest_path, track]
            if variant_path.is_file():
                formal_paths.append(variant_path)
            for item in results.values():
                directory = Path(item.video_path).parent
                formal_paths.extend(
                    (directory / "segment-manifest.json", Path(item.video_path))
                )
                formal_paths.extend(
                    Path(str(record["path"]))
                    for record in item.keyframes.values()
                )
            _confirm_formal_artifact_records(job, formal_paths)
        return results
    except VisualAssetsV2Error:
        raise
    except (
        OSError,
        KeyError,
        TypeError,
        contract_artifacts.ContractArtifactError,
        visual_canary.VisualCanaryError,
    ):
        raise VisualAssetsV2Error("visual-assets generation is invalid") from None


def _approved_canary_segments(
    job: state.JobState,
    plan: Mapping[str, Any],
    *,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
) -> dict[str, segment_render.RenderedSegment]:
    manifest = visual_canary.load_approved_visual_canary(job, probe=probe)
    plan_segments = {
        str(segment["segment_id"]): segment for segment in plan["segments"]
    }
    results: dict[str, segment_render.RenderedSegment] = {}
    for value in manifest["segments"]:
        identifier = str(value.get("segment_id"))
        segment = plan_segments.get(identifier)
        if segment is None or identifier in results:
            raise VisualAssetsV2Error("approved canary does not match the visual plan")
        try:
            results[identifier] = visual_canary.validate_rendered_segment(
                job,
                plan,
                segment,
                value,
                root=job.job_dir / "08-visual-canary/segments",
                probe=probe,
            )
        except visual_canary.VisualCanaryError:
            raise VisualAssetsV2Error(
                "approved canary does not match the visual plan"
            ) from None
    return results


def _prepare_visual_assets_v2_locked(
    job: state.JobState,
    plan: Mapping[str, Any],
    canary: Mapping[str, segment_render.RenderedSegment],
    *,
    component_adapters: Mapping[str, object],
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
    assembler: Callable[[list[Path], Path], None] | None = None,
) -> Path:
    target = job.job_dir / "09-visual-assets"
    status = job.stages["visual_assets"]["status"]
    if status in {"ready_for_review", "approved"}:
        _load_segments(job, plan, target, require_manifest=True, probe=probe)
        return target / "visual-track.mp4"

    state.require_runnable(job, "visual_assets")
    scope_values = job.stages["visual_assets"].get("artifact_scope", [])
    if type(scope_values) is not list or any(
        type(identifier) is not str for identifier in scope_values
    ):
        raise VisualAssetsV2Error("visual-assets revision scope is invalid")
    scope = set(scope_values)
    valid_ids = {str(item["segment_id"]) for item in plan["segments"]}
    if scope - valid_ids:
        raise VisualAssetsV2Error("visual-assets revision scope is invalid")
    old = _load_segments(
        job,
        plan,
        target,
        require_manifest=False,
        probe=probe,
        canary_segment_ids=frozenset(canary),
    )
    arroll = visual_canary.approved_aroll_record(job, plan)

    stage = job.job_dir / f".09-visual-assets.stage-{uuid.uuid4().hex[:16]}"
    stage_segments = stage / "segments"
    stage_segments.mkdir(parents=True)
    rendered: list[segment_render.RenderedSegment] = []
    reused_canary_ids: list[str] = []
    reused_formal_ids: list[str] = []
    try:
        for segment in plan["segments"]:
            identifier = str(segment["segment_id"])
            destination = stage_segments / identifier
            if identifier not in scope and identifier in old:
                rendered.append(_materialize_reused(old[identifier], destination))
                reused_formal_ids.append(identifier)
                continue
            if identifier not in scope and identifier in canary:
                rendered.append(_materialize_reused(canary[identifier], destination))
                reused_canary_ids.append(identifier)
                continue
            recipe = segment["shot_recipe"]
            render_args = {
                "output_dir": stage_segments,
                "visual_plan_sha256": str(plan["visual_plan_sha256"]),
                "arroll_source": Path(arroll["path"]),
                "arroll_sha256": str(arroll["sha256"]),
                "arroll_bytes": int(arroll["bytes"]),
                "ffmpeg_runner": ffmpeg_runner,
                "probe": probe,
                "frame_extractor": frame_extractor,
            }
            if recipe["mode"] == "none":
                overlay_args = {}
                if recipe["composition"]["family"] == "aroll_with_overlay":
                    overlay_args["artifacts"] = visual_canary.execute_approved_components(
                        job, segment, adapters=component_adapters,
                    )
                item = segment_render.render_arroll_segment(
                    job,
                    segment,
                    **overlay_args,
                    **render_args,
                )
            else:
                component_artifacts = visual_canary.execute_approved_components(
                    job,
                    segment,
                    adapters=component_adapters,
                )
                item = segment_render.render_segment_video(
                    job,
                    segment,
                    component_artifacts,
                    **render_args,
                )
            rendered.append(item)

        track = segment_render.assemble_visual_track(
            rendered,
            stage / "visual-track.mp4",
            assembler=assembler,
        )
        final_segments = [
            _relocate(item, target / "segments" / item.segment_id)
            for item in rendered
        ]
        for item in final_segments:
            contract_artifacts.write_json_artifact(
                stage_segments / item.segment_id / "segment-manifest.json",
                asdict(item),
            )
        final_track = target / "visual-track.mp4"
        payload = _manifest(
            job,
            plan,
            final_segments,
            track,
            final_track,
            reused_canary_ids,
            reused_formal_ids,
        )
        contract_artifacts.write_json_artifact(stage / "asset-manifest.json", payload)
        contract_artifacts.write_json_artifact(
            stage / "variant-matrix.json",
            _variant_matrix(job, plan, final_segments),
        )

        manifest_path = target / "asset-manifest.json"
        variant_path = target / "variant-matrix.json"
        artifacts = [manifest_path, variant_path, final_track]
        artifact_paths_by_segment: dict[str, list[str]] = {}
        for item in final_segments:
            directory = target / "segments" / item.segment_id
            segment_artifacts = [
                directory / "segment-manifest.json",
                directory / "segment.mp4",
                *(
                directory / "keyframes" / f"{name}.png"
                for name in item.keyframes
                ),
            ]
            artifacts.extend(segment_artifacts)
            artifact_paths_by_segment[item.segment_id] = [
                manifest_path.relative_to(job.job_dir).as_posix(),
                final_track.relative_to(job.job_dir).as_posix(),
                *(
                    path.relative_to(job.job_dir).as_posix()
                    for path in segment_artifacts
                ),
            ]
        for lock_path in stage_segments.glob(".seg-*.render.lock"):
            lock_path.unlink()
        material_usage.write_staged_receipt(
            job,
            "visual_assets",
            stage,
            target,
            [path.relative_to(target).as_posix() for path in artifacts],
            producer="edit.hd.tools.visual_assets_v2",
            producer_version="3",
            stage_input_records=material_usage.current_stage_input_records(
                job, "visual_assets"
            ),
            references=material_usage.visual_segment_references(
                plan["segments"],
                consumer_kind="visual_asset_segment",
                artifact_paths_by_segment=artifact_paths_by_segment,
            ),
        )
        artifacts.append(target / "material-usage.json")
        _fsync_tree(stage)
        backup = (
            job.job_dir / f".09-visual-assets.backup-{uuid.uuid4().hex[:16]}"
            if target.exists()
            else None
        )
        journal: dict[str, object] = {
            "schema_version": 1,
            "job_id": job.job_id,
            "target_name": target.name,
            "stage_name": stage.name,
            "backup_name": None if backup is None else backup.name,
            "artifact_records": _artifact_records_from_stage(
                job,
                stage,
                target,
                artifacts,
            ),
        }
        journal = _write_publication_journal(job, journal, "staged")
        if backup is not None:
            os.replace(target, backup)
            _fsync_directory(job.job_dir)
        journal = _write_publication_journal(job, journal, "backed_up")
        os.replace(stage, target)
        _fsync_directory(job.job_dir)
        journal = _write_publication_journal(job, journal, "installed")
        state.mark_ready(job, "visual_assets", tuple(artifacts))
        _recover_publication(job)
        return final_track
    except (KeyboardInterrupt, SystemExit):
        if not _journal_path(job).exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    except BaseException:
        if _journal_path(job).exists():
            _recover_publication(job)
        else:
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _preflight_visual_assets_v2(
    job: state.JobState,
    *,
    probe: Callable[[Path], Mapping[str, object]] | None,
) -> tuple[dict[str, Any], dict[str, segment_render.RenderedSegment]]:
    if job.version != 2:
        raise VisualAssetsV2Error("formal visual-assets builder requires full-v2")
    try:
        plan = visual_canary.load_approved_visual_plan(job)
        canary = _approved_canary_segments(job, plan, probe=probe)
    except visual_canary.VisualCanaryError as error:
        raise VisualAssetsV2Error(str(error)) from None
    return plan, canary


def prepare_visual_assets_v2(
    job: state.JobState,
    *,
    component_adapters: Mapping[str, object],
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
    assembler: Callable[[list[Path], Path], None] | None = None,
) -> Path:
    """Reuse approved canary bytes and execute only non-canary recipes."""

    plan, canary = _preflight_visual_assets_v2(job, probe=probe)
    with _visual_assets_writer(job):
        requested_job = job
        current_job = state.load_job(requested_job.job_dir)
        plan, canary = _preflight_visual_assets_v2(current_job, probe=probe)
        _recover_publication(current_job)
        result = _prepare_visual_assets_v2_locked(
            current_job,
            plan,
            canary,
            component_adapters=component_adapters,
            ffmpeg_runner=ffmpeg_runner,
            probe=probe,
            frame_extractor=frame_extractor,
            assembler=assembler,
        )
        _synchronize_job(requested_job, current_job)
        return result

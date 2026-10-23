"""Formal visual-canary review gate built from approved production recipes."""

from __future__ import annotations

import copy
import contextlib
import fcntl
import os
import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import (
    broll_component_executor,
    contract_artifacts,
    material_usage,
    segment_render,
    state,
    visual_plan,
)


MAX_CANARY_SECONDS = 30.0
_AROLL_JOB_PATH = "06-edit-structure/edited-aroll.mp4"
PUBLICATION_JOURNAL_NAME = ".08-visual-canary.publication-journal.json"
_LOCK_NAME = ".08-visual-canary.lock"
_PUBLICATION_STATES = {
    "staged",
    "backed_up",
    "installed",
    "restoring",
    "restored",
}


class VisualCanaryError(RuntimeError):
    """Raised when a formal canary cannot be selected, rendered, or reused."""


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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


@contextlib.contextmanager
def _visual_canary_writer(job: state.JobState):
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


def _journal_path(job: state.JobState) -> Path:
    return job.job_dir / PUBLICATION_JOURNAL_NAME


def _write_publication_journal(
    job: state.JobState,
    journal: Mapping[str, object],
    publication_state: str,
) -> dict[str, object]:
    if publication_state not in _PUBLICATION_STATES:
        raise VisualCanaryError("visual-canary publication state is invalid")
    value = {**journal, "state": publication_state}
    contract_artifacts.write_json_artifact(_journal_path(job), value)
    _fsync_directory(job.job_dir)
    return value


def _clear_publication_journal(job: state.JobState) -> None:
    path = _journal_path(job)
    if path.exists():
        path.unlink()
        _fsync_directory(job.job_dir)


def _remove_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise VisualCanaryError("visual-canary publication path is invalid")
        shutil.rmtree(path)


def _artifact_records_from_stage(
    job: state.JobState,
    stage: Path,
    target: Path,
    paths: list[Path],
) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(job.job_dir).as_posix(),
            "sha256": contract_artifacts.sha256_file(
                stage / path.relative_to(target)
            ),
            "bytes": (stage / path.relative_to(target)).stat().st_size,
        }
        for path in paths
    ]


def _record_paths(
    job: state.JobState,
    records: object,
) -> tuple[list[dict[str, object]], list[Path]]:
    if type(records) is not list:
        raise VisualCanaryError("visual-canary publication journal is invalid")
    normalized: list[dict[str, object]] = []
    paths: list[Path] = []
    for record in records:
        if (
            type(record) is not dict
            or type(record.get("path")) is not str
            or not str(record["path"]).startswith("08-visual-canary/")
            or ".." in Path(str(record["path"])).parts
            or type(record.get("sha256")) is not str
            or len(str(record["sha256"])) != 64
            or type(record.get("bytes")) is not int
            or int(record["bytes"]) <= 0
        ):
            raise VisualCanaryError("visual-canary publication journal is invalid")
        normalized.append(
            {
                "path": record["path"],
                "sha256": record["sha256"],
                "bytes": record["bytes"],
            }
        )
        paths.append(job.job_dir / str(record["path"]))
    if len(paths) != len(set(paths)):
        raise VisualCanaryError("visual-canary publication journal is invalid")
    return normalized, paths


def _records_match_target(
    job: state.JobState,
    records: list[dict[str, object]],
    paths: list[Path],
) -> bool:
    target = job.job_dir / "08-visual-canary"
    if not target.is_dir():
        return False
    try:
        if {path for path in target.rglob("*") if path.is_file()} != set(paths):
            return False
        return all(
            record["sha256"] == contract_artifacts.sha256_file(path)
            and record["bytes"] == path.stat().st_size
            for record, path in zip(records, paths)
        )
    except (KeyError, OSError, TypeError):
        return False


def _current_generation_records(
    job: state.JobState,
) -> tuple[list[dict[str, object]], list[Path]] | None:
    stage = job.stages["visual_canary"]
    source = stage.get("artifacts") or stage.get("lineage")
    if type(source) is not list or not source:
        return None
    try:
        records, paths = _record_paths(job, source)
    except VisualCanaryError:
        return None
    return (records, paths) if _records_match_target(job, records, paths) else None


def _recover_publication(job: state.JobState) -> None:
    path = _journal_path(job)
    if not path.exists():
        return
    try:
        journal = contract_artifacts.read_json_artifact(path)
    except contract_artifacts.ContractArtifactError:
        raise VisualCanaryError("visual-canary publication journal is invalid") from None
    if (
        type(journal) is not dict
        or journal.get("schema_version") != 1
        or journal.get("job_id") != job.job_id
        or journal.get("state") not in _PUBLICATION_STATES
        or journal.get("target_name") != "08-visual-canary"
        or type(journal.get("stage_name")) is not str
        or Path(str(journal["stage_name"])).name != journal["stage_name"]
        or not str(journal["stage_name"]).startswith(".08-visual-canary.stage-")
        or (
            journal.get("backup_name") is not None
            and (
                type(journal["backup_name"]) is not str
                or Path(str(journal["backup_name"])).name
                != journal["backup_name"]
                or not str(journal["backup_name"]).startswith(
                    ".08-visual-canary.backup-"
                )
            )
        )
    ):
        raise VisualCanaryError("visual-canary publication journal is invalid")
    records, paths = _record_paths(job, journal.get("artifact_records"))
    target = job.job_dir / str(journal["target_name"])
    stage = job.job_dir / str(journal["stage_name"])
    backup = (
        None
        if journal["backup_name"] is None
        else job.job_dir / str(journal["backup_name"])
    )
    publication_state = str(journal["state"])
    current = _current_generation_records(job)
    if (
        publication_state == "installed"
        and current is not None
        and current[0] == records
    ):
        if backup is not None:
            _remove_directory(backup)
        _remove_directory(stage)
        _clear_publication_journal(job)
        return
    if publication_state == "staged" and (
        backup is None or not backup.exists()
    ):
        _remove_directory(stage)
        _clear_publication_journal(job)
        return
    if publication_state == "installed" and current is not None:
        raise VisualCanaryError(
            "publication journal conflicts with current visual-canary generation"
        )
    if publication_state == "restored":
        if backup is not None and backup.exists():
            raise VisualCanaryError("visual-canary publication layout is invalid")
        _remove_directory(stage)
        _clear_publication_journal(job)
        return
    if publication_state != "restoring":
        journal = _write_publication_journal(job, journal, "restoring")
    if backup is not None:
        if backup.exists():
            if target.exists():
                if not _records_match_target(job, records, paths):
                    raise VisualCanaryError(
                        "visual-canary target does not match the journal"
                    )
                _remove_directory(target)
            os.replace(backup, target)
            _fsync_directory(job.job_dir)
        elif not target.exists() or _current_generation_records(job) is None:
            raise VisualCanaryError("visual-canary restoration is incomplete")
    elif target.exists():
        if not _records_match_target(job, records, paths):
            raise VisualCanaryError("visual-canary target does not match the journal")
        _remove_directory(target)
        _fsync_directory(job.job_dir)
    journal = _write_publication_journal(job, journal, "restored")
    _remove_directory(stage)
    _clear_publication_journal(job)


def _relocate_segment(
    rendered: segment_render.RenderedSegment,
    destination: Path,
) -> segment_render.RenderedSegment:
    return replace(
        rendered,
        video_path=str(destination / "segment.mp4"),
        keyframes={
            name: {
                **record,
                "path": str(destination / "keyframes" / f"{name}.png"),
            }
            for name, record in rendered.keyframes.items()
        },
    )


def _recipe_identities(
    segments: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    return {
        str(segment["segment_id"]): contract_artifacts.sha256_json(
            segment["shot_recipe"]
        )
        for segment in segments
    }


def _require_new_strategy_revision(
    target: Path,
    selected: Sequence[Mapping[str, Any]],
) -> None:
    manifest_path = target / "canary-manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = contract_artifacts.read_json_artifact(manifest_path)
        previous_identities = manifest["recipe_identities"]
        previous_segments = {
            value["segment_id"]: value for value in manifest["segments"]
        }
        if type(previous_identities) is not dict:
            raise KeyError
        for segment in selected:
            identifier = str(segment["segment_id"])
            previous = previous_segments.get(identifier)
            if previous is None:
                continue
            current_identity = contract_artifacts.sha256_json(
                segment["shot_recipe"]
            )
            if previous_identities.get(identifier) == current_identity:
                continue
            revisions = {
                value["strategy_revision"]
                for value in previous["component_artifacts"]
            }
            if (
                len(revisions) != 1
                or segment["shot_recipe"]["strategy_revision"] <= max(revisions)
            ):
                raise VisualCanaryError(
                    "changed recipe requires a new strategy revision"
                )
    except VisualCanaryError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        contract_artifacts.ContractArtifactError,
    ):
        raise VisualCanaryError("previous visual-canary generation is invalid") from None


def _confirm_stage_artifact(
    job: state.JobState,
    stage_id: str,
    path: Path,
) -> None:
    try:
        relative = path.relative_to(job.job_dir).as_posix()
        records = [
            record
            for record in job.stages[stage_id].get("artifacts", [])
            if record.get("path") == relative
        ]
        if (
            len(records) != 1
            or not path.is_file()
            or records[0].get("sha256") != contract_artifacts.sha256_file(path)
            or records[0].get("bytes") != path.stat().st_size
        ):
            raise VisualCanaryError(f"{stage_id} artifact identity changed")
    except (KeyError, OSError, ValueError):
        raise VisualCanaryError(f"{stage_id} artifact identity changed") from None


def load_approved_visual_plan(
    job: state.JobState,
    *,
    qualification_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if job.version != 2 or "visual_direction" not in job.stages:
        raise VisualCanaryError("formal visual plan is unavailable")
    if job.stages["visual_direction"]["status"] != "approved":
        raise VisualCanaryError("visual_direction must be approved")
    path = job.job_dir / "07-visual-direction" / "visual-plan.json"
    try:
        plan = visual_plan.validate_visual_plan(
            contract_artifacts.read_json_artifact(path),
            qualification_context=qualification_context,
        )
    except (
        contract_artifacts.ContractArtifactError,
        visual_plan.VisualPlanError,
    ):
        raise VisualCanaryError("formal visual plan schema is invalid") from None
    artifacts = job.stages["visual_direction"].get("artifacts", [])
    matches = [
        record
        for record in artifacts
        if record.get("path") == "07-visual-direction/visual-plan.json"
    ]
    if (
        len(matches) != 1
        or matches[0].get("sha256") != contract_artifacts.sha256_file(path)
        or matches[0].get("bytes") != path.stat().st_size
    ):
        raise VisualCanaryError("formal visual plan is not the approved artifact")
    return plan


def approved_aroll_record(
    job: state.JobState,
    plan: Mapping[str, Any],
) -> dict[str, object]:
    """Return the approved edited A-roll identity used by every segment."""

    stage = job.stages.get("edit_structure")
    if not isinstance(stage, Mapping) or stage.get("status") != "approved":
        raise VisualCanaryError("edited A-roll must be approved")
    matches = [
        record
        for record in stage.get("artifacts", [])
        if record.get("path") == _AROLL_JOB_PATH
    ]
    source = job.job_dir / _AROLL_JOB_PATH
    if len(matches) != 1 or not source.is_file():
        raise VisualCanaryError("approved edited A-roll is unavailable")
    record = matches[0]
    expected_sha256 = plan.get("edited_aroll_sha256")
    try:
        actual_sha256 = contract_artifacts.sha256_file(source)
        actual_bytes = source.stat().st_size
    except OSError:
        raise VisualCanaryError("approved edited A-roll is unavailable") from None
    if (
        record.get("sha256") != expected_sha256
        or record.get("bytes") != actual_bytes
        or actual_sha256 != expected_sha256
    ):
        raise VisualCanaryError("approved edited A-roll bytes changed")
    return {
        "path": source,
        "job_path": _AROLL_JOB_PATH,
        "sha256": actual_sha256,
        "bytes": actual_bytes,
    }


def select_representative_segments(
    segments: Sequence[Mapping[str, Any]],
    *,
    requested: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    eligible = [
        dict(segment)
        for segment in segments
        if isinstance(segment.get("shot_recipe"), Mapping)
        and (segment["shot_recipe"].get("mode") != "none"
             or segment["shot_recipe"].get("composition", {}).get("family") == "aroll_with_overlay")
    ]
    if not eligible:
        # A pure A-roll plan (every segment no_broll) still deserves a render
        # canary: verify the A-roll cutting/compositor path before visual_assets
        # renders the full track, instead of rejecting the legal plan shape.
        eligible = [
            dict(segment)
            for segment in segments
            if isinstance(segment.get("shot_recipe"), Mapping)
        ]
    if not eligible:
        raise VisualCanaryError("visual plan contains no renderable segment")
    by_id = {str(segment.get("segment_id")): segment for segment in eligible}
    if len(by_id) != len(eligible):
        raise VisualCanaryError("visual plan contains duplicate segment ids")
    if requested is not None:
        if not requested or len(requested) != len(set(requested)):
            raise VisualCanaryError("requested canary segment ids are invalid")
        if any(identifier not in by_id for identifier in requested):
            raise VisualCanaryError("requested canary segment is unavailable")
        candidates = [by_id[identifier] for identifier in requested]
    else:
        candidates = []
        used_families: set[str] = set()
        for segment in eligible:
            recipe = segment["shot_recipe"]
            composition = recipe.get("composition")
            family = (
                composition.get("family")
                if isinstance(composition, Mapping)
                else None
            )
            if not isinstance(family, str):
                raise VisualCanaryError("canary segment is missing its ShotRecipe")
            if family not in used_families:
                candidates.append(segment)
                used_families.add(family)
        candidates.extend(segment for segment in eligible if segment not in candidates)

    selected: list[dict[str, Any]] = []
    seconds = 0.0
    for segment in candidates:
        duration = float(segment["end"]) - float(segment["start"])
        if duration <= 0 or duration > MAX_CANARY_SECONDS:
            raise VisualCanaryError("canary segment duration is invalid")
        if seconds + duration > MAX_CANARY_SECONDS + 1e-6:
            continue
        selected.append(segment)
        seconds += duration
    if not selected:
        raise VisualCanaryError("no segment fits the 30-second canary")
    return sorted(selected, key=lambda segment: float(segment["start"]))


def execute_approved_components(
    job: state.JobState,
    segment: Mapping[str, Any],
    *,
    adapters: Mapping[str, object],
) -> tuple[broll_component_executor.ComponentArtifact, ...]:
    """Execute the exact components and reading order in one approved recipe."""

    recipe = segment.get("shot_recipe")
    if not isinstance(recipe, Mapping) or (
        recipe.get("mode") == "none"
        and recipe.get("composition", {}).get("family") not in {"aroll_with_overlay", "no_broll"}
    ):
        raise VisualCanaryError("B-roll segment ShotRecipe is invalid")
    if recipe.get("composition", {}).get("family") == "no_broll":
        # A pure A-roll segment executes no components; the renderer cuts
        # the A-roll window directly.
        return ()
    components = recipe.get("components")
    composition = recipe.get("composition")
    if not isinstance(components, list) or not isinstance(composition, Mapping):
        raise VisualCanaryError("B-roll segment ShotRecipe is invalid")
    by_id = {
        component.get("component_id"): component
        for component in components
        if isinstance(component, Mapping)
    }
    reading_order = composition.get("reading_order")
    if (
        len(by_id) != len(components)
        or not isinstance(reading_order, list)
        or set(reading_order) != set(by_id)
        or len(reading_order) != len(by_id)
    ):
        raise VisualCanaryError("B-roll component order is invalid")
    return tuple(
        broll_component_executor.execute_component(
            job,
            broll_component_executor.ComponentExecutionRequest(
                recipe=recipe,
                component_id=component_id,
            ),
            adapters=adapters,
        )
        for component_id in reading_order
    )


def validate_rendered_segment(
    job: state.JobState,
    plan: Mapping[str, Any],
    segment: Mapping[str, Any],
    value: object,
    *,
    root: Path,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
) -> segment_render.RenderedSegment:
    """Apply the shared render replay contract to one existing segment."""

    try:
        arroll_record = approved_aroll_record(job, plan)
        return segment_render.load_rendered_segment_replay(
            job,
            segment,
            value,
            output_dir=root,
            visual_plan_sha256=str(plan["visual_plan_sha256"]),
            arroll_source=Path(arroll_record["path"]),
            arroll_sha256=str(arroll_record["sha256"]),
            arroll_bytes=int(arroll_record["bytes"]),
            probe=probe,
        )
    except (KeyError, TypeError, ValueError, segment_render.SegmentRenderError):
        raise VisualCanaryError("canary segment identity is invalid") from None


def _load_reusable(
    job: state.JobState,
    plan: Mapping[str, Any],
    *,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
) -> dict[str, Any] | None:
    if job.stages["visual_canary"]["status"] not in {
        "ready_for_review",
        "approved",
    }:
        return None
    root = job.job_dir / "08-visual-canary"
    manifest_path = root / "canary-manifest.json"
    if not manifest_path.is_file():
        raise VisualCanaryError("approved canary manifest is missing")
    try:
        manifest = contract_artifacts.read_json_artifact(manifest_path)
        identity = manifest.get("canary_sha256")
        base = {key: value for key, value in manifest.items() if key != "canary_sha256"}
        video = root / "visual-canary.mp4"
        if (
            manifest.get("schema_version") != 2
            or manifest.get("visual_plan_sha256") != plan["visual_plan_sha256"]
            or manifest.get("renderer_contract_version")
            != segment_render.RENDERER_CONTRACT_VERSION
            or identity != contract_artifacts.sha256_json(base)
            or manifest.get("video_path") != str(video)
            or not video.is_file()
            or manifest.get("video_sha256") != contract_artifacts.sha256_file(video)
            or manifest.get("video_bytes") != video.stat().st_size
            or type(manifest.get("segments")) is not list
        ):
            raise VisualCanaryError("approved canary identity changed")
        plan_segments = {
            str(segment["segment_id"]): segment for segment in plan["segments"]
        }
        rendered = [
            validate_rendered_segment(
                job,
                plan,
                plan_segments[str(value.get("segment_id"))],
                value,
                root=root / "segments",
                probe=probe,
            )
            for value in manifest["segments"]
        ]
        if (
            manifest.get("segment_ids") != [item.segment_id for item in rendered]
            or len(rendered) != len(set(item.segment_id for item in rendered))
            or manifest.get("recipe_identities")
            != {
                item.segment_id: contract_artifacts.sha256_json(
                    plan_segments[item.segment_id]["shot_recipe"]
                )
                for item in rendered
            }
        ):
            raise VisualCanaryError("approved canary segment list changed")
        _confirm_stage_artifact(job, "visual_canary", manifest_path)
        _confirm_stage_artifact(job, "visual_canary", video)
        for item in rendered:
            directory = Path(item.video_path).parent
            _confirm_stage_artifact(job, "visual_canary", Path(item.video_path))
            _confirm_stage_artifact(
                job,
                "visual_canary",
                directory / "segment-manifest.json",
            )
            for record in item.keyframes.values():
                _confirm_stage_artifact(
                    job,
                    "visual_canary",
                    Path(str(record["path"])),
                )
    except VisualCanaryError:
        raise
    except (KeyError, OSError, contract_artifacts.ContractArtifactError):
        raise VisualCanaryError("approved canary identity changed") from None
    return manifest


def load_approved_visual_canary(
    job: state.JobState,
    *,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    if job.version != 2 or "visual_canary" not in job.stages:
        raise VisualCanaryError("formal visual canary is unavailable")
    if job.stages["visual_canary"]["status"] != "approved":
        raise VisualCanaryError("visual_canary must be approved")
    plan = load_approved_visual_plan(job)
    manifest = _load_reusable(job, plan, probe=probe)
    if manifest is None:
        raise VisualCanaryError("approved visual canary is unavailable")
    return manifest


def prepare_visual_canary(
    job: state.JobState,
    segment_ids: Sequence[str] | None = None,
    *,
    component_adapters: Mapping[str, object],
    ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    probe: Callable[[Path], Mapping[str, object]] | None = None,
    frame_extractor: Callable[[Path, float, Path], None] | None = None,
    assembler: Callable[[list[Path], Path], None] | None = None,
) -> dict[str, Any]:
    plan = load_approved_visual_plan(job)
    with _visual_canary_writer(job):
        requested_job = job
        job = state.load_job(requested_job.job_dir)
        plan = load_approved_visual_plan(job)
        _recover_publication(job)
        reusable = _load_reusable(job, plan, probe=probe)
        if reusable is not None:
            _synchronize_job(requested_job, job)
            return reusable
        state.require_runnable(job, "visual_canary")
        selected = select_representative_segments(
            plan["segments"], requested=segment_ids
        )
        target = job.job_dir / "08-visual-canary"
        _require_new_strategy_revision(target, selected)
        stage = job.job_dir / f".08-visual-canary.stage-{uuid.uuid4().hex[:16]}"
        segment_root = stage / "segments"
        segment_root.mkdir(parents=True)
        arroll = approved_aroll_record(job, plan)
        try:
            rendered: list[segment_render.RenderedSegment] = []
            for segment in selected:
                artifacts = execute_approved_components(
                    job,
                    segment,
                    adapters=component_adapters,
                )
                renderer = (segment_render.render_arroll_segment
                            if segment["shot_recipe"]["mode"] == "none"
                            else segment_render.render_segment_video)
                rendered.append(
                    renderer(
                        job,
                        segment,
                        artifacts=artifacts,
                        output_dir=segment_root,
                        visual_plan_sha256=str(plan["visual_plan_sha256"]),
                        arroll_source=Path(arroll["path"]),
                        arroll_sha256=str(arroll["sha256"]),
                        arroll_bytes=int(arroll["bytes"]),
                        ffmpeg_runner=ffmpeg_runner,
                        probe=probe,
                        frame_extractor=frame_extractor,
                    )
                )
            video = segment_render.assemble_visual_track(
                rendered,
                stage / "visual-canary.mp4",
                assembler=assembler,
            )
            final_segments = [
                _relocate_segment(
                    item,
                    target / "segments" / item.segment_id,
                )
                for item in rendered
            ]
            for item in final_segments:
                contract_artifacts.write_json_artifact(
                    segment_root / item.segment_id / "segment-manifest.json",
                    asdict(item),
                )
            final_video = target / "visual-canary.mp4"
            base = {
                "schema_version": 2,
                "renderer_contract_version": segment_render.RENDERER_CONTRACT_VERSION,
                "visual_plan_sha256": plan["visual_plan_sha256"],
                "segment_ids": [item.segment_id for item in final_segments],
                "recipe_identities": _recipe_identities(selected),
                "duration": (
                    sum(item.frames for item in final_segments)
                    / segment_render.FPS
                ),
                "canvas": {
                    "width": segment_render.WIDTH,
                    "height": segment_render.HEIGHT,
                    "fps": segment_render.FPS,
                },
                "video_path": str(final_video),
                "video_sha256": contract_artifacts.sha256_file(video),
                "video_bytes": video.stat().st_size,
                "segments": [asdict(item) for item in final_segments],
            }
            manifest = {
                **base,
                "canary_sha256": contract_artifacts.sha256_json(base),
            }
            manifest_path = target / "canary-manifest.json"
            contract_artifacts.write_json_artifact(
                stage / "canary-manifest.json",
                manifest,
            )
            published: list[Path] = [manifest_path, final_video]
            artifact_paths_by_segment: dict[str, list[str]] = {}
            for item in final_segments:
                directory = Path(item.video_path).parent
                segment_artifacts = [
                    Path(item.video_path),
                    directory / "segment-manifest.json",
                    *(Path(record["path"]) for record in item.keyframes.values()),
                ]
                published.extend(segment_artifacts)
                artifact_paths_by_segment[item.segment_id] = [
                    manifest_path.relative_to(job.job_dir).as_posix(),
                    final_video.relative_to(job.job_dir).as_posix(),
                    *(
                        path.relative_to(job.job_dir).as_posix()
                        for path in segment_artifacts
                    ),
                ]
            for lock_path in segment_root.glob(".seg-*.render.lock"):
                lock_path.unlink()
            material_usage.write_staged_receipt(
                job,
                "visual_canary",
                stage,
                target,
                [path.relative_to(target).as_posix() for path in published],
                producer="edit.hd.tools.visual_canary",
                producer_version="2",
                stage_input_records=material_usage.current_stage_input_records(
                    job, "visual_canary"
                ),
                references=material_usage.visual_segment_references(
                    selected,
                    consumer_kind="visual_canary_segment",
                    artifact_paths_by_segment=artifact_paths_by_segment,
                ),
            )
            published.append(target / "material-usage.json")
            _fsync_tree(stage)
            backup = (
                job.job_dir
                / f".08-visual-canary.backup-{uuid.uuid4().hex[:16]}"
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
                    published,
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
            state.mark_ready(job, "visual_canary", tuple(published))
            _recover_publication(job)
            _synchronize_job(requested_job, job)
            return manifest
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

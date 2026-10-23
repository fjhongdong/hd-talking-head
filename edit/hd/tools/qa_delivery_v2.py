"""Immutable full-v2 delivery publication with complete lineage."""

from __future__ import annotations

import copy
import fcntl
import os
import secrets
import shutil
from pathlib import Path
from typing import Any, Mapping

from . import contract_artifacts, material_usage, preview_music, preview_v2, state


_DELIVERY_JOURNAL = ".12-delivery.publication.json"
_SHA256_CHARACTERS = frozenset("0123456789abcdef")
_COVER_ASPECTS = {
    "16:9": ("cover-16x9.png", {"width": 1920, "height": 1080}),
    "9:16": ("cover-9x16.png", {"width": 1080, "height": 1920}),
    "3:4": ("cover-3x4.png", {"width": 1080, "height": 1440}),
    "1:1": ("cover-1x1.png", {"width": 1080, "height": 1080}),
}
_COVER_REPORT_KEYS = {
    "version",
    "generator",
    "generation_id",
    "mode",
    "base_reused",
    "base_generation",
    "output_aspect_ratio",
    "direction_sha256",
    "reference_sha256",
    "model",
    "prompt",
    "workflow",
    "source_bindings",
    "face_frame",
    "person_composite",
    "alternative_evidence",
    "canvas",
    "artifacts",
    "output_sha256",
}


class DeliveryV2Error(RuntimeError):
    """Raised when an approved v2 artifact cannot be published exactly."""


class _DeliveryLock:
    def __init__(self, job_dir: Path) -> None:
        self.path = Path(job_dir) / ".12-delivery.lock"
        self.descriptor: int | None = None

    def __enter__(self) -> "_DeliveryLock":
        self.descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX)
        except BaseException:
            os.close(self.descriptor)
            self.descriptor = None
            raise
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        if self.descriptor is not None:
            try:
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self.descriptor)
                self.descriptor = None


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_CHARACTERS for character in value)
    )


def _direct_publication_child_name(
    job_dir: Path, value: object, prefix: str
) -> bool:
    if (
        type(value) is not str
        or value in {".", ".."}
        or not value.startswith(prefix)
        or value == prefix
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        return False
    try:
        root = Path(job_dir).resolve(strict=True)
        candidate = root / value
        return (
            candidate.parent == root
            and candidate.resolve(strict=False).parent == root
        )
    except (OSError, ValueError):
        return False


def _approved(job: state.JobState, stage_id: str, relative: str) -> Path:
    return _stage_artifact(job, stage_id, relative, {"approved"})


def _stage_artifact(job: state.JobState, stage_id: str, relative: str,
                    statuses: set[str]) -> Path:
    stage = job.stages[stage_id]
    if stage["status"] not in statuses:
        raise DeliveryV2Error(f"{stage_id} is not in the required state")
    matches = [record for record in stage["artifacts"] if record.get("path") == relative]
    path = job.job_dir / relative
    if (
        len(matches) != 1
        or not path.is_file()
        or matches[0].get("sha256") != contract_artifacts.sha256_file(path)
        or matches[0].get("bytes") != path.stat().st_size
    ):
        raise DeliveryV2Error(f"approved {relative} changed")
    return path


def _source(path: Path, *, base: Path) -> dict[str, Any]:
    try:
        relative = path.relative_to(base).as_posix()
    except ValueError:
        relative = str(path)
    return {
        "path": relative,
        "sha256": contract_artifacts.sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if contract_artifacts.sha256_file(destination) != contract_artifacts.sha256_file(source):
        raise DeliveryV2Error("delivery copy changed bytes")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _delivery_tree_digest(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise DeliveryV2Error("delivery publication directory is incomplete")
    records = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink() or (not item.is_file() and not item.is_dir()):
            raise DeliveryV2Error("delivery publication entry is incomplete")
        if item.is_file():
            records.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "sha256": contract_artifacts.sha256_file(item),
                    "bytes": item.stat().st_size,
                }
            )
    return contract_artifacts.sha256_json(records)


def _fsync_delivery_tree(path: Path) -> None:
    directories = [path]
    for item in path.rglob("*"):
        if item.is_file():
            descriptor = os.open(item, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        elif item.is_dir():
            directories.append(item)
    for directory in sorted(
        directories, key=lambda value: len(value.parts), reverse=True
    ):
        _fsync_directory(directory)


def _write_delivery_journal(job_dir: Path, payload: Mapping[str, Any]) -> None:
    path = Path(job_dir) / _DELIVERY_JOURNAL
    stage = Path(job_dir) / f".{_DELIVERY_JOURNAL}.stage-{secrets.token_hex(8)}"
    data = contract_artifacts.canonical_json_bytes(payload) + b"\n"
    try:
        with stage.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, path)
        _fsync_directory(Path(job_dir))
    finally:
        if stage.exists():
            stage.unlink()


def _clear_delivery_journal(job_dir: Path) -> None:
    path = Path(job_dir) / _DELIVERY_JOURNAL
    if path.exists():
        path.unlink()
        _fsync_directory(Path(job_dir))


def _remove_delivery_tree(path: Path, expected_digest: str) -> None:
    if path.exists():
        if _delivery_tree_digest(path) != expected_digest:
            raise DeliveryV2Error("delivery publication directory changed")
        shutil.rmtree(path)
        _fsync_directory(path.parent)


def _recover_delivery_publication(job: state.JobState) -> None:
    job_dir = Path(job.job_dir)
    journal_path = job_dir / _DELIVERY_JOURNAL
    if not journal_path.exists():
        return
    try:
        payload = contract_artifacts.read_json_artifact(journal_path)
    except contract_artifacts.ContractArtifactError:
        raise DeliveryV2Error("delivery publication record is incomplete") from None
    expected_keys = {
        "schema_version",
        "state",
        "stage_name",
        "backup_name",
        "had_target",
        "old_tree_sha256",
        "new_tree_sha256",
    }
    if (
        type(payload) is not dict
        or set(payload) != expected_keys
        or payload.get("schema_version") != 1
        or payload.get("state") not in {"prepared", "installed"}
        or not _direct_publication_child_name(
            job_dir, payload.get("stage_name"), ".12-delivery.stage-"
        )
        or type(payload.get("had_target")) is not bool
        or not _valid_sha256(payload.get("new_tree_sha256"))
    ):
        raise DeliveryV2Error("delivery publication record is incomplete")
    had_target = payload["had_target"]
    backup_name = payload["backup_name"]
    old_digest = payload["old_tree_sha256"]
    if had_target != (
        _direct_publication_child_name(
            job_dir, backup_name, ".12-delivery.backup-"
        )
        and _valid_sha256(old_digest)
    ):
        raise DeliveryV2Error("delivery publication record is incomplete")
    if not had_target and (backup_name is not None or old_digest is not None):
        raise DeliveryV2Error("delivery publication record is incomplete")
    target = job_dir / "12-delivery"
    stage = job_dir / payload["stage_name"]
    backup = None if backup_name is None else job_dir / backup_name
    new_digest = payload["new_tree_sha256"]

    def digest(path: Path | None) -> str | None:
        if path is None or not path.exists():
            return None
        return _delivery_tree_digest(path)

    target_digest = digest(target)
    stage_digest = digest(stage)
    backup_digest = digest(backup)
    if stage_digest not in {None, new_digest}:
        raise DeliveryV2Error("delivery recovery stage changed")
    if backup_digest not in {None, old_digest}:
        raise DeliveryV2Error("delivery recovery backup changed")
    committed = job.stages["delivery"]["status"] in {
        "ready_for_review",
        "approved",
    }
    if committed:
        if target_digest != new_digest:
            raise DeliveryV2Error("published delivery is incomplete")
        _remove_delivery_tree(stage, new_digest)
        if backup is not None:
            _remove_delivery_tree(backup, old_digest)
        _clear_delivery_journal(job_dir)
        return
    if had_target:
        if target_digest == new_digest:
            _remove_delivery_tree(target, new_digest)
            target_digest = None
        elif target_digest not in {None, old_digest}:
            raise DeliveryV2Error("delivery recovery target changed")
        if target_digest is None:
            if backup is None or digest(backup) != old_digest:
                raise DeliveryV2Error("delivery recovery backup is incomplete")
            os.replace(backup, target)
            _fsync_directory(job_dir)
        elif backup is not None:
            _remove_delivery_tree(backup, old_digest)
    else:
        if target_digest == new_digest:
            _remove_delivery_tree(target, new_digest)
        elif target_digest is not None:
            raise DeliveryV2Error("delivery recovery target changed")
    _remove_delivery_tree(stage, new_digest)
    _clear_delivery_journal(job_dir)


def _job_snapshot(job: state.JobState) -> dict[str, Any]:
    return {
        "stages": copy.deepcopy(job.stages),
        **{
            name: getattr(job, name)
            for name in (
                "revision",
                "expected_revision",
                "expected_sha256",
                "expected_bytes",
            )
            if hasattr(job, name)
        },
    }


def _restore_job_snapshot(job: state.JobState, snapshot: Mapping[str, Any]) -> None:
    job.stages.clear()
    job.stages.update(copy.deepcopy(snapshot["stages"]))
    for name, value in snapshot.items():
        if name != "stages":
            setattr(job, name, value)


def _cover_sources(job: state.JobState) -> dict[str, Path]:
    return _validated_cover_sources(job, for_review=False)


def _validated_cover_sources(job: state.JobState, *, for_review: bool) -> dict[str, Path]:
    statuses = {"ready_for_review", "approved"} if for_review else {"approved"}
    report_path = _stage_artifact(job, "cover", "04-cover/cover-report.json", statuses)
    try:
        report = contract_artifacts.read_json_artifact(report_path)
    except contract_artifacts.ContractArtifactError:
        raise DeliveryV2Error("approved cover report is incomplete") from None
    aspect = report.get("output_aspect_ratio")
    artifacts = report.get("artifacts")
    version = report.get("version")
    report_keys = _COVER_REPORT_KEYS
    if (
        set(report) != report_keys
        or type(version) is not int or version not in (1, 3)
        or type(aspect) is not str
        or aspect not in _COVER_ASPECTS
        or type(artifacts) is not list
        or type(report.get("output_sha256")) is not dict
    ):
        raise DeliveryV2Error("approved cover report is incomplete")
    selected_name, canvas = _COVER_ASPECTS[aspect]
    full_image_mode = report.get("mode") == "approved-full-image"
    if full_image_mode and (
        report.get("base_generation") != "approved_full_image"
        or report.get("generator") != "punk-cover"
    ):
        raise DeliveryV2Error("approved full-image cover report is incomplete")
    expected_names = {
        "cover-brief.json",
        selected_name,
        "cover-delivery-raster.png",
    }
    if not full_image_mode:
        expected_names.add("cover-base.png")
    records: dict[str, Mapping[str, Any]] = {}
    for record in artifacts:
        if (
            type(record) is not dict
            or set(record) != {"path", "sha256", "bytes"}
            or type(record.get("path")) is not str
        ):
            raise DeliveryV2Error("approved cover report is incomplete")
        path = Path(record["path"])
        if (
            path.parent.as_posix() != "04-cover"
            or path.name in records
            or not _valid_sha256(record.get("sha256"))
            or type(record.get("bytes")) is not int
            or record["bytes"] <= 0
        ):
            raise DeliveryV2Error("approved cover report is incomplete")
        records[path.name] = record
    if (
        set(records) != expected_names
        or report.get("canvas") != canvas
        or report["output_sha256"]
        != {name: records[name]["sha256"] for name in expected_names}
    ):
        raise DeliveryV2Error("approved cover report does not match its outputs")
    if full_image_mode:
        bindings = report.get("source_bindings")
        preview = bindings.get("approved_preview") if isinstance(bindings, dict) else None
        final = records[selected_name]
        delivery = records["cover-delivery-raster.png"]
        if (
            not isinstance(preview, dict)
            or preview.get("sha256") != final["sha256"]
            or preview.get("bytes") != final["bytes"]
            or delivery["sha256"] != final["sha256"]
            or delivery["bytes"] != final["bytes"]
        ):
            raise DeliveryV2Error("approved full-image cover differs from its source")
    expected_stage_paths = {
        *(f"04-cover/{name}" for name in expected_names),
        "04-cover/cover-report.json",
    }
    stage_paths = [record.get("path") for record in job.stages["cover"]["artifacts"]]
    receipt_path = "04-cover/material-usage.json"
    if receipt_path in stage_paths:
        expected_stage_paths.add(receipt_path)
    if len(stage_paths) != len(expected_stage_paths) or set(stage_paths) != expected_stage_paths:
        raise DeliveryV2Error("approved cover artifact inventory is incomplete")
    if receipt_path in stage_paths:
        try:
            material_usage.load_current_receipt(job, "cover")
        except (material_usage.MaterialUsageError, OSError) as exc:
            raise DeliveryV2Error("approved cover material usage receipt is invalid") from exc
    paths: dict[str, Path] = {}
    for name in expected_names:
        source = _stage_artifact(job, "cover", f"04-cover/{name}", statuses)
        if records[name] != {
            "path": f"04-cover/{name}",
            "sha256": contract_artifacts.sha256_file(source),
            "bytes": source.stat().st_size,
        }:
            raise DeliveryV2Error("approved cover report does not match its outputs")
        paths[name] = source
    return {
        f"cover/{selected_name}": paths[selected_name],
        "cover/cover-delivery-raster.png": paths["cover-delivery-raster.png"],
        "cover/cover-report.json": report_path,
    }


def _sources(job: state.JobState) -> dict[str, Path]:
    sources = {
        "final.mp4": _approved(job, "preview", "11-preview/review.mp4"),
        "qa/qa-report.json": _approved(job, "preview", "11-preview/qa-report.json"),
        "source-manifest.json": _approved(
            job, "preview", "11-preview/source-manifest.json"
        ),
        "plans/content-analysis.json": _approved(job, "content_analysis", "02-content-analysis/content-analysis.json"),
        "plans/visual-plan.json": _approved(job, "visual_direction", "07-visual-direction/visual-plan.json"),
        "plans/asset-manifest.json": _approved(job, "visual_assets", "09-visual-assets/asset-manifest.json"),
        "plans/subtitle-plan.json": _approved(job, "subtitles", "10-subtitles/subtitle-plan.json"),
        "subtitles/subtitles.srt": _approved(job, "subtitles", "10-subtitles/subtitles.srt"),
        "subtitles/subtitles.webm": _approved(job, "subtitles", "10-subtitles/subtitles.webm"),
    }
    sources.update(_cover_sources(job))
    try:
        report = contract_artifacts.read_json_artifact(sources["qa/qa-report.json"])
        opening = preview_v2.validate_preview_opening(job, report)
        music = preview_v2.validate_preview_music(job, report)
    except (preview_v2.PreviewV2Error, contract_artifacts.ContractArtifactError) as exc:
        raise DeliveryV2Error("approved preview opening evidence is invalid") from exc
    if opening is not None:
        sources["opening-manifest.json"] = _approved(job, "preview", "11-preview/opening-manifest.json")
        sources["subtitles/subtitles.srt"] = _approved(job, "preview", "11-preview/subtitles.srt")
        sources["plans/body-subtitles.webm"] = sources.pop("subtitles/subtitles.webm")
    if music is not None:
        for name in preview_music.ATTACHMENTS:
            sources[name] = _approved(job, "preview", f"11-preview/{name}")
    material_index = job.root / "00-user-provided" / "material-index.json"
    if material_index.is_file():
        sources["sources/user-material-index.json"] = material_index
    return sources


def _credits_markdown(source_manifest: Mapping[str, Any]) -> str | None:
    records = []
    for component in source_manifest["components"]:
        attribution = component["attribution"]
        if attribution is not None and attribution["required"]:
            records.append(attribution)
    if not records:
        return None
    lines = ["# 素材署名", ""]
    for index, record in enumerate(records, start=1):
        lines.extend(
            (
                f"## {index}. {record['provider']} — {record['author']}",
                "",
                f"- 作品页：{record['asset_page']}",
                f"- 许可：{record['license']}（{record['license_version']}）",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _published_delivery(job: state.JobState, relative: str) -> Path:
    if job.stages["delivery"]["status"] not in {
        "ready_for_review",
        "approved",
    }:
        raise DeliveryV2Error("delivery is not published")
    matches = [
        record
        for record in job.stages["delivery"]["artifacts"]
        if record.get("path") == relative
    ]
    path = Path(job.job_dir) / relative
    if (
        len(matches) != 1
        or not path.is_file()
        or matches[0].get("sha256") != contract_artifacts.sha256_file(path)
        or matches[0].get("bytes") != path.stat().st_size
    ):
        raise DeliveryV2Error(f"published {relative} changed")
    return path


def _validate_reusable_delivery(
    job: state.JobState,
    target: Path,
    manifest: object,
    sources: Mapping[str, Path],
    source_manifest: Mapping[str, Any],
    credits: str | None,
) -> dict[str, Any]:
    if type(manifest) is not dict or set(manifest) != {
        "schema_version",
        "job_id",
        "workflow_revision",
        "workflow_sha256",
        "final_sha256",
        "canvas",
        "background_music",
        "artifacts",
        "delivery_manifest_sha256",
    }:
        raise DeliveryV2Error("delivery record is incomplete")
    base = {
        key: value
        for key, value in manifest.items()
        if key != "delivery_manifest_sha256"
    }
    inventory = manifest.get("artifacts")
    expected_names = set(sources)
    if credits is not None:
        expected_names.add("credits.md")
    transition_count = (
        1 if job.stages["delivery"]["status"] == "ready_for_review" else 2
    )
    if (
        manifest.get("schema_version") != 2
        or manifest.get("job_id") != job.job_id
        or manifest.get("workflow_revision") != job.revision - transition_count
        or not _valid_sha256(manifest.get("workflow_sha256"))
        or manifest.get("canvas") != {"width": 1080, "height": 1920, "fps": 24}
        or manifest.get("background_music") is not (preview_music.MANIFEST in sources)
        or type(inventory) is not dict
        or set(inventory) != expected_names
        or manifest.get("delivery_manifest_sha256")
        != contract_artifacts.sha256_json(base)
    ):
        raise DeliveryV2Error("delivery record is incomplete")
    artifact_paths = [
        record.get("path") for record in job.stages["delivery"]["artifacts"]
    ]
    receipt_path = "12-delivery/material-usage.json"
    has_receipt = receipt_path in artifact_paths
    expected_published_names = expected_names | {"delivery-manifest.json"}
    if has_receipt:
        expected_published_names.add("material-usage.json")
    if "12-delivery/approval-receipt.json" in artifact_paths:
        from .delivery_approval import validate_approval_receipt
        try:
            validate_approval_receipt(job)
        except state.WorkflowError as exc:
            raise DeliveryV2Error("final approval receipt is invalid") from exc
        expected_published_names.add("approval-receipt.json")
    actual_files = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_published_names:
        raise DeliveryV2Error("delivery file set is incomplete")
    expected_stage_paths = {
        f"12-delivery/{relative}"
        for relative in expected_published_names
    }
    if (
        len(artifact_paths) != len(expected_stage_paths)
        or set(artifact_paths) != expected_stage_paths
    ):
        raise DeliveryV2Error("delivery artifact inventory is incomplete")
    for relative in expected_stage_paths:
        _published_delivery(job, relative)
    if has_receipt:
        material_usage.load_current_receipt(job, "delivery")
    for relative, source in sources.items():
        destination = target / relative
        if inventory[relative] != {
            "source": _source(source, base=job.job_dir),
            "output": _source(destination, base=target),
        }:
            raise DeliveryV2Error("delivery copy does not match its approved source")
    if credits is not None:
        credits_path = target / "credits.md"
        if credits_path.read_text(encoding="utf-8") != credits or inventory[
            "credits.md"
        ] != {
            "generated_from": {
                "path": "11-preview/source-manifest.json",
                "sha256": source_manifest["source_manifest_sha256"],
            },
            "output": _source(credits_path, base=target),
        }:
            raise DeliveryV2Error("delivery credits do not match source records")
    final = target / "final.mp4"
    if manifest["final_sha256"] != contract_artifacts.sha256_file(final):
        raise DeliveryV2Error("delivery final bytes changed")
    return manifest


def _publish_delivery(
    job: state.JobState,
    stage: Path,
    target: Path,
    artifact_paths: list[str],
) -> None:
    job_dir = Path(job.job_dir)
    had_target = target.exists()
    old_digest = _delivery_tree_digest(target) if had_target else None
    new_digest = _delivery_tree_digest(stage)
    backup = (
        job_dir / f".12-delivery.backup-{secrets.token_hex(8)}"
        if had_target
        else None
    )
    journal = {
        "schema_version": 1,
        "state": "prepared",
        "stage_name": stage.name,
        "backup_name": None if backup is None else backup.name,
        "had_target": had_target,
        "old_tree_sha256": old_digest,
        "new_tree_sha256": new_digest,
    }
    _fsync_delivery_tree(stage)
    _write_delivery_journal(job_dir, journal)
    if backup is not None:
        os.replace(target, backup)
        _fsync_directory(job_dir)
    os.replace(stage, target)
    _fsync_directory(job_dir)
    _write_delivery_journal(job_dir, {**journal, "state": "installed"})
    snapshot = _job_snapshot(job)
    try:
        state.mark_ready(
            job,
            "delivery",
            tuple(target / relative for relative in artifact_paths),
        )
    except BaseException as exc:
        if isinstance(exc, state._CommittedWorkflowError):
            _recover_delivery_publication(job)
        else:
            _restore_job_snapshot(job, snapshot)
            _recover_delivery_publication(job)
        raise
    if backup is not None:
        _remove_delivery_tree(backup, old_digest)
    _clear_delivery_journal(job_dir)


def _prepare_delivery_v2_locked(job: state.JobState):
    from .qa_delivery import DeliveryResult

    if job.version != 2:
        raise DeliveryV2Error("formal delivery builder requires full-v2")
    _recover_delivery_publication(job)
    target = job.job_dir / "12-delivery"
    manifest_path = target / "delivery-manifest.json"
    sources = _sources(job)
    try:
        arroll_source = _approved(
            job, "edit_structure", "06-edit-structure/edited-aroll.mp4"
        )
        visual_plan = contract_artifacts.read_json_artifact(
            sources["plans/visual-plan.json"]
        )
        asset_manifest = contract_artifacts.read_json_artifact(
            sources["plans/asset-manifest.json"]
        )
        source_manifest = (
            preview_v2.validate_source_manifest_against_approved_sources(
                job,
                contract_artifacts.read_json_artifact(
                    sources["source-manifest.json"]
                ),
                visual_plan,
                asset_manifest,
                arroll_source=arroll_source,
            )
        )
    except (
        DeliveryV2Error,
        preview_v2.PreviewV2Error,
        contract_artifacts.ContractArtifactError,
    ):
        raise DeliveryV2Error("BROLL_SOURCE_MANIFEST_BLOCKED") from None
    credits = _credits_markdown(source_manifest)
    if job.stages["delivery"]["status"] in {"ready_for_review", "approved"}:
        try:
            manifest_path = _published_delivery(
                job, "12-delivery/delivery-manifest.json"
            )
            manifest = _validate_reusable_delivery(
                job,
                target,
                contract_artifacts.read_json_artifact(manifest_path),
                sources,
                source_manifest,
                credits,
            )
        except (
            OSError,
            UnicodeError,
            contract_artifacts.ContractArtifactError,
        ):
            raise DeliveryV2Error("delivery record is incomplete") from None
        final = target / "final.mp4"
        artifacts = tuple(
            job.job_dir / record["path"]
            for record in job.stages["delivery"]["artifacts"]
        )
        return DeliveryResult(
            target,
            artifacts,
            manifest,
            {"sha256": manifest["final_sha256"], "bytes": final.stat().st_size},
        )
    state.require_runnable(job, "delivery")
    stage = job.job_dir / f".12-delivery.stage-{secrets.token_hex(8)}"
    stage.mkdir()
    try:
        inventory: dict[str, Any] = {}
        for relative, source in sources.items():
            destination = stage / relative
            _copy(source, destination)
            inventory[relative] = {
                "source": _source(source, base=job.job_dir),
                "output": _source(destination, base=stage),
            }
        if credits is not None:
            credits_path = stage / "credits.md"
            credits_path.write_text(credits, encoding="utf-8")
            inventory["credits.md"] = {
                "generated_from": {
                    "path": "11-preview/source-manifest.json",
                    "sha256": source_manifest["source_manifest_sha256"],
                },
                "output": _source(credits_path, base=stage),
            }
        final_sha256 = inventory["final.mp4"]["output"]["sha256"]
        base = {
            "schema_version": 2,
            "job_id": job.job_id,
            "workflow_revision": job.revision,
            "workflow_sha256": job.expected_sha256,
            "final_sha256": final_sha256,
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "background_music": preview_music.MANIFEST in sources,
            "artifacts": inventory,
        }
        manifest = {
            **base,
            "delivery_manifest_sha256": contract_artifacts.sha256_json(base),
        }
        contract_artifacts.write_json_artifact(stage / "delivery-manifest.json", manifest)
        artifact_paths = list(sources)
        if credits is not None:
            artifact_paths.append("credits.md")
        artifact_paths.append("delivery-manifest.json")
        references = []
        if preview_music.MANIFEST in sources:
            music_manifest = preview_v2.validate_preview_music(job,
                contract_artifacts.read_json_artifact(sources["qa/qa-report.json"]))
            references = preview_music.material_references(music_manifest["plan"], "12-delivery", artifact_paths)
        material_usage.write_staged_receipt(
            job,
            "delivery",
            stage,
            target,
            artifact_paths,
            producer="edit.hd.tools.qa_delivery_v2",
            producer_version="2",
            stage_input_records=material_usage.current_stage_input_records(
                job, "delivery"
            ),
            references=references,
        )
        artifact_paths.append("material-usage.json")
        _publish_delivery(job, stage, target, artifact_paths)
        artifacts = tuple(target / relative for relative in artifact_paths)
        final = target / "final.mp4"
        return DeliveryResult(
            target,
            artifacts,
            manifest,
            {"sha256": contract_artifacts.sha256_file(final), "bytes": final.stat().st_size},
        )
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def prepare_delivery_v2(job: state.JobState):
    if job.version != 2:
        raise DeliveryV2Error("formal delivery builder requires full-v2")
    with _DeliveryLock(Path(job.job_dir)):
        current = (
            state.load_job(job.job_dir)
            if isinstance(job, state.JobState)
            else job
        )
        result = _prepare_delivery_v2_locked(current)
        if current is not job:
            state._synchronize_committed_job(job)
        return result

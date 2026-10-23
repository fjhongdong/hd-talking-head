"""Native 9:16 preview and evidence builder for the full-v2 workflow."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import (
    broll_component_executor,
    confirmed_content,
    contract_artifacts,
    event_audio,
    material_usage,
    preview_opening,
    preview_music,
    segment_render,
    state,
    talkcraft_subtitles,
    visual_plan,
)


class PreviewV2Error(RuntimeError):
    """Raised when the approved visual/audio tracks cannot form an exact preview."""


_SOURCE_MANIFEST_BLOCKED = "BROLL_SOURCE_MANIFEST_BLOCKED"
_SHA256_CHARACTERS = frozenset("0123456789abcdef")
_SOURCE_MANIFEST_KEYS = {
    "schema_version",
    "job_id",
    "visual_plan_sha256",
    "asset_manifest_sha256",
    "components",
    "source_manifest_sha256",
}
_SOURCE_COMPONENT_KEYS = {
    "segment_id",
    "component_id",
    "kind",
    "semantic_role",
    "provenance",
    "source_asset_id",
    "final_asset_id",
    "source_time",
    "artifact",
    "qa",
    "activity_record",
    "not_selected_candidates",
    "attribution",
}
_ARTIFACT_KEYS = set(broll_component_executor.ComponentArtifact.__dataclass_fields__)
_PREVIEW_JOURNAL = ".11-preview.publication.json"


def _blocked() -> PreviewV2Error:
    return PreviewV2Error(_SOURCE_MANIFEST_BLOCKED)


def _approved_event_audio_plan(
    job: state.JobState,
    *,
    frames: int,
) -> dict[str, object] | None:
    stage = job.stages.get("visual_direction", {})
    records = stage.get("artifacts", []) if isinstance(stage, Mapping) else []
    declared = any(
        isinstance(record, Mapping)
        and record.get("path") == "07-visual-direction/audio-event-plan.json"
        for record in records
    )
    semantic_stage = job.stages.get("visual_direction", {})
    semantic_records = semantic_stage.get("artifacts", []) if isinstance(semantic_stage, Mapping) else []
    semantic_declared = any(
        isinstance(record, Mapping)
        and record.get("path") == "07-visual-direction/semantic-events.json"
        for record in semantic_records
    )
    if not semantic_declared:
        return None
    event_path = _approved(job, "visual_direction", "07-visual-direction/semantic-events.json")
    event_plan = contract_artifacts.read_json_artifact(event_path)
    if not declared:
        return event_audio.build_default_plan(
            event_plan,
            runtime_root=job.root.parents[1] / "edit/hd/integrations/talkcraft/runtime",
            job_id=job.job_id,
            total_frames=frames,
        )
    audio_path = _approved(job, "visual_direction", "07-visual-direction/audio-event-plan.json")
    audio_plan = contract_artifacts.read_json_artifact(audio_path)
    runtime_root = job.root.parents[1] / "edit/hd/integrations/talkcraft/runtime"
    return event_audio.validate_plan(
        audio_plan,
        event_plan,
        job_id=job.job_id,
        total_frames=frames,
        allowed_roots=(runtime_root / "qualification-fixtures",),
    )


class _PreviewLock:
    def __init__(self, job_dir: Path) -> None:
        self.path = Path(job_dir) / ".11-preview.lock"
        self.descriptor: int | None = None

    def __enter__(self) -> "_PreviewLock":
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


def _job_file(
    root: Path,
    relative: object,
    *,
    sha256: object | None = None,
    byte_count: object | None = None,
) -> Path:
    if type(relative) is not str:
        raise _blocked()
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or "\\" in relative
        or pure.as_posix() != relative
    ):
        raise _blocked()
    try:
        base = Path(root).resolve(strict=True)
        path = base.joinpath(*pure.parts)
        resolved = path.resolve(strict=True)
        resolved.relative_to(base)
    except (OSError, ValueError):
        raise _blocked() from None
    if resolved != path or not resolved.is_file():
        raise _blocked()
    if sha256 is not None and (
        not _valid_sha256(sha256)
        or contract_artifacts.sha256_file(resolved) != sha256
    ):
        raise _blocked()
    if byte_count is not None and (
        type(byte_count) is not int
        or byte_count <= 0
        or resolved.stat().st_size != byte_count
    ):
        raise _blocked()
    return resolved


def _file_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _source_id(kind: str, component: Mapping[str, Any]) -> str:
    fields = {
        "local_material": "material_id",
        "official_material": "source_id",
        "external_stock": "provider_asset_id",
        "code_generated": "dependency_id",
        "ai_generated": "generation_id",
    }
    value = component.get(fields[kind])
    if type(value) is not str or not value:
        raise _blocked()
    return value


def _license_record(
    root: Path,
    component: Mapping[str, Any],
    source_bytes: int,
) -> tuple[dict[str, Any], Path]:
    path = _job_file(root, component.get("license_snapshot"))
    try:
        value = contract_artifacts.read_json_artifact(path)
    except contract_artifacts.ContractArtifactError:
        raise _blocked() from None
    required = {
        "schema_version",
        "idempotency_key",
        "search_generation",
        "snapshot_sha256",
        "query_sha256",
        "provider",
        "provider_asset_id",
        "author",
        "asset_page",
        "license_name",
        "license_version",
        "downloaded_at",
        "byte_count",
        "sha256",
        "job_path",
        "license_snapshot",
    }
    if type(value) is not dict or set(value) not in (required, required | {"attribution_required"}):
        raise _blocked()
    expected = {
        "provider": component.get("provider"),
        "provider_asset_id": component.get("provider_asset_id"),
        "author": component.get("author"),
        "asset_page": component.get("asset_page"),
        "downloaded_at": component.get("downloaded_at"),
        "sha256": component.get("sha256"),
        "byte_count": source_bytes,
        "job_path": component.get("job_path"),
        "license_snapshot": component.get("license_snapshot"),
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise _blocked()
    if any(type(value.get(key)) is not str or not value[key] for key in required - {"schema_version", "byte_count"}):
        raise _blocked()
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise _blocked()
    if type(value.get("byte_count")) is not int or value["byte_count"] <= 0:
        raise _blocked()
    if "attribution_required" in value and type(value["attribution_required"]) is not bool:
        raise _blocked()
    return value, path


def _source_component_record(
    job: Any,
    segment: Mapping[str, Any],
    recipe_component: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(job.job_dir)
    recipe = segment["shot_recipe"]
    component_id = recipe_component["component_id"]
    kind = recipe_component["kind"]
    if (
        type(artifact) is not dict
        or set(artifact) != _ARTIFACT_KEYS
        or artifact.get("schema_version") != 1
        or artifact.get("status") != "success"
        or artifact.get("error_code") is not None
        or artifact.get("job_id") != job.job_id
        or artifact.get("segment_id") != segment["segment_id"]
        or artifact.get("component_id") != component_id
        or artifact.get("kind") != kind
        or artifact.get("strategy_revision") != recipe["strategy_revision"]
        or artifact.get("source_media_type") != recipe_component["media_type"]
        or artifact.get("render_window") != recipe_component["render_window"]
        or artifact.get("artifact_contract") != recipe_component["artifact_contract"]
    ):
        raise _blocked()
    qa = artifact.get("qa")
    evidence = artifact.get("invocation_evidence")
    if (
        type(qa) is not dict
        or qa.get("passed") is not True
        or type(evidence) is not dict
        or evidence.get("output_job_path") != artifact.get("job_path")
        or evidence.get("output_sha256") != artifact.get("output_sha256")
    ):
        raise _blocked()
    final = _job_file(
        root,
        artifact.get("job_path"),
        sha256=artifact.get("output_sha256"),
        byte_count=artifact.get("byte_count"),
    )
    source_id = _source_id(kind, recipe_component)
    candidates = segment["candidate_snapshots"].get(component_id, [])
    not_selected = []
    for candidate in candidates[1:]:
        if type(candidate) is not dict or candidate.get("kind") != kind:
            raise _blocked()
        not_selected.append(
            {
                "asset_id": candidate["asset_id"],
                "kind": kind,
                "reason": "ranked_after_selected_same_kind_candidate",
            }
        )

    source_path: Path | None = None
    source_relative: str | None = None
    source_sha256: str
    source_bytes: int | None = None
    details: dict[str, Any]
    activity: dict[str, Any] | None
    attribution: dict[str, Any] | None = None
    if kind == "local_material":
        source_relative = recipe_component["job_path"]
        source_sha256 = recipe_component["sha256"]
        source_path = _job_file(root, source_relative, sha256=source_sha256)
        source_bytes = source_path.stat().st_size
        details = {"material_id": source_id}
        activity = None
        time_field = "artifact_file_mtime"
        time_value = _file_time(source_path)
    elif kind == "official_material":
        source_relative = recipe_component["snapshot_path"]
        source_sha256 = recipe_component["sha256"]
        source_path = _job_file(root, source_relative, sha256=source_sha256)
        source_bytes = source_path.stat().st_size
        details = {
            "source_id": source_id,
            "publisher": recipe_component["publisher"],
            "source_url": recipe_component["source_url"],
        }
        activity = {
            "type": "download",
            "source_url": recipe_component["source_url"],
            "snapshot_path": source_relative,
            "fetched_at": recipe_component["fetched_at"],
            "sha256": source_sha256,
        }
        time_field = "fetched_at"
        time_value = recipe_component["fetched_at"]
    elif kind == "external_stock":
        source_relative = recipe_component["job_path"]
        source_sha256 = recipe_component["sha256"]
        source_path = _job_file(root, source_relative, sha256=source_sha256)
        source_bytes = source_path.stat().st_size
        license_value, license_path = _license_record(
            root, recipe_component, source_bytes
        )
        adapter_record = evidence.get("adapter_record", {})
        if type(adapter_record) is not dict:
            raise _blocked()
        attribution_required = adapter_record.get(
            "attribution_required", license_value.get("attribution_required", False)
        )
        if type(attribution_required) is not bool:
            raise _blocked()
        details = {
            "provider": recipe_component["provider"],
            "provider_asset_id": source_id,
            "author": recipe_component["author"],
            "asset_page": recipe_component["asset_page"],
        }
        activity = {
            "type": "download",
            "provider": recipe_component["provider"],
            "provider_asset_id": source_id,
            "downloaded_at": recipe_component["downloaded_at"],
            "job_path": source_relative,
            "sha256": source_sha256,
            "bytes": source_bytes,
            "license_snapshot": recipe_component["license_snapshot"],
            "license_sha256": contract_artifacts.sha256_file(license_path),
        }
        attribution = {
            "required": attribution_required,
            "provider": recipe_component["provider"],
            "author": recipe_component["author"],
            "asset_page": recipe_component["asset_page"],
            "license": license_value["license_name"],
            "license_version": license_value["license_version"],
        }
        time_field = "downloaded_at"
        time_value = recipe_component["downloaded_at"]
    elif kind == "code_generated":
        if any(
            evidence.get(evidence_key) != recipe_component[recipe_key]
            for evidence_key, recipe_key in (
                ("dependency_id", "dependency_id"),
                ("approved_entrypoint", "entrypoint"),
                ("producer_version", "producer_version"),
                ("brief_sha256", "brief_sha256"),
                ("primary_renderer", "primary_renderer"),
                ("renderer_version", "renderer_version"),
            )
        ):
            raise _blocked()
        if (
            evidence.get("invocation_type") not in {"reference_process", "skill_invocation"}
            or type(evidence.get("invocation_id")) is not str
            or not evidence["invocation_id"]
        ):
            raise _blocked()
        if evidence["invocation_type"] == "reference_process":
            if (
                evidence.get("exit_code") != 0
                or evidence.get("timed_out") is not False
                or evidence.get("unresolved_process_group") is not False
            ):
                raise _blocked()
        else:
            receipt = evidence.get("receipt")
            if type(receipt) is not dict or any(
                receipt.get(key) != expected
                for key, expected in (
                    ("status", "completed"),
                    ("invocation_id", evidence["invocation_id"]),
                    ("dependency_id", recipe_component["dependency_id"]),
                    ("brief_sha256", recipe_component["brief_sha256"]),
                    ("output_sha256", artifact["output_sha256"]),
                )
            ):
                raise _blocked()
        source_sha256 = recipe_component["brief_sha256"]
        details = {
            "dependency_id": recipe_component["dependency_id"],
            "entrypoint": recipe_component["entrypoint"],
            "producer_version": recipe_component["producer_version"],
        }
        activity = {
            "type": "invocation",
            "dependency_id": recipe_component["dependency_id"],
            "entrypoint": recipe_component["entrypoint"],
            "producer_version": recipe_component["producer_version"],
            "brief_sha256": recipe_component["brief_sha256"],
            "invocation_record_sha256": contract_artifacts.sha256_json(
                recipe_component["invocation_record"]
            ),
            "invocation_type": evidence["invocation_type"],
            "invocation_id": evidence["invocation_id"],
            "invocation_evidence_sha256": contract_artifacts.sha256_json(evidence),
            "primary_renderer": recipe_component["primary_renderer"],
            "renderer_version": recipe_component["renderer_version"],
            "output_sha256": artifact["output_sha256"],
        }
        time_field = "artifact_file_mtime"
        time_value = _file_time(final)
    elif kind == "ai_generated":
        if recipe_component["sha256"] != artifact["output_sha256"]:
            raise _blocked()
        source_sha256 = recipe_component["prompt_sha256"]
        details = {
            "provider": recipe_component["provider"],
            "model": recipe_component["model"],
            "generation_id": recipe_component["generation_id"],
        }
        activity = {
            "type": "generation",
            "provider": recipe_component["provider"],
            "model": recipe_component["model"],
            "endpoint_id": recipe_component["endpoint_id"],
            "generation_id": recipe_component["generation_id"],
            "prompt_sha256": recipe_component["prompt_sha256"],
            "output_sha256": artifact["output_sha256"],
        }
        time_field = "artifact_file_mtime"
        time_value = _file_time(final)
    else:
        raise _blocked()

    record = {
        "segment_id": segment["segment_id"],
        "component_id": component_id,
        "kind": kind,
        "semantic_role": recipe_component["semantic_role"],
        "provenance": {
            "kind": kind,
            "source_path": source_relative,
            "source_sha256": source_sha256,
            "source_bytes": source_bytes,
            "details": details,
        },
        "source_asset_id": source_id,
        "final_asset_id": (
            f"{segment['segment_id']}:{component_id}:{artifact['output_sha256']}"
        ),
        "source_time": {"field": time_field, "value": time_value},
        "artifact": {
            "job_path": artifact["job_path"],
            "media_type": artifact["artifact_media_type"],
            "bytes": artifact["byte_count"],
            "sha256": artifact["output_sha256"],
        },
        "qa": {
            "passed": True,
            "record_sha256": contract_artifacts.sha256_json(qa),
        },
        "activity_record": activity,
        "not_selected_candidates": not_selected,
        "attribution": attribution,
    }
    return record


def _validate_rendered_asset_manifest(
    job: Any,
    checked_plan: Mapping[str, Any],
    asset_manifest: object,
    arroll_source: Path,
) -> None:
    expected_keys = {
        "schema_version",
        "renderer_contract_version",
        "job_id",
        "visual_plan_sha256",
        "canvas",
        "duration",
        "segments",
        "visual_track",
        "asset_manifest_sha256",
    }
    reuse_keys = {
        "reused_canary_segment_ids",
        "reused_formal_segment_ids",
        "segment_input_identities",
    }
    legacy_canary_only = (
        type(asset_manifest) is dict
        and set(asset_manifest) == expected_keys | {"reused_canary_segment_ids"}
        and asset_manifest.get("reused_canary_segment_ids") == []
    )
    if type(asset_manifest) is not dict or set(asset_manifest) not in (
        expected_keys, expected_keys | reuse_keys
    ) and not legacy_canary_only:
        raise _blocked()
    if reuse_keys.issubset(asset_manifest):
        from . import visual_assets_v2

        expected_identities = {
            segment["segment_id"]: visual_assets_v2._segment_input_identity(checked_plan, segment)
            for segment in checked_plan["segments"]
        }
        if asset_manifest["segment_input_identities"] != expected_identities:
            raise _blocked()
        reuse_lists = [asset_manifest[key] for key in (
        "reused_canary_segment_ids", "reused_formal_segment_ids"
        )]
        for ids in reuse_lists:
            if (type(ids) is not list or any(type(item) is not str for item in ids)
                    or len(set(ids)) != len(ids) or not set(ids).issubset(expected_identities)):
                raise _blocked()
        if set(reuse_lists[0]) & set(reuse_lists[1]):
            raise _blocked()
    asset_base = {
        key: value
        for key, value in asset_manifest.items()
        if key != "asset_manifest_sha256"
    }
    if (
        asset_manifest.get("schema_version") != 3
        or asset_manifest.get("renderer_contract_version")
        != segment_render.RENDERER_CONTRACT_VERSION
        or asset_manifest.get("job_id") != job.job_id
        or asset_manifest.get("visual_plan_sha256")
        != checked_plan["visual_plan_sha256"]
        or asset_manifest.get("canvas") != checked_plan["canvas"]
        or asset_manifest.get("duration") != (
            round(float(checked_plan["duration"]) * checked_plan["canvas"]["fps"])
            / checked_plan["canvas"]["fps"]
        )
        or asset_manifest.get("asset_manifest_sha256")
        != contract_artifacts.sha256_json(asset_base)
        or type(asset_manifest.get("segments")) is not list
        or len(asset_manifest["segments"]) != len(checked_plan["segments"])
    ):
        raise _blocked()
    arroll_path = _job_file(
        Path(job.job_dir),
        "06-edit-structure/edited-aroll.mp4",
        sha256=checked_plan["edited_aroll_sha256"],
    )
    try:
        if Path(arroll_source).resolve(strict=True) != arroll_path:
            raise _blocked()
    except OSError:
        raise _blocked() from None
    rendered_by_id = {
        value.get("segment_id"): value
        for value in asset_manifest["segments"]
        if type(value) is dict and type(value.get("segment_id")) is str
    }
    if len(rendered_by_id) != len(asset_manifest["segments"]):
        raise _blocked()
    try:
        for segment in checked_plan["segments"]:
            value = rendered_by_id.get(segment["segment_id"])
            if value is None:
                raise _blocked()
            segment_render.load_rendered_segment_replay(
                job,
                segment,
                value,
                output_dir=Path(job.job_dir) / "09-visual-assets/segments",
                visual_plan_sha256=checked_plan["visual_plan_sha256"],
                arroll_source=arroll_path,
                arroll_sha256=checked_plan["edited_aroll_sha256"],
                arroll_bytes=arroll_path.stat().st_size,
            )
    except segment_render.SegmentRenderError:
        raise _blocked() from None


def build_source_manifest(
    job: Any,
    visual_plan_payload: object,
    asset_manifest_payload: object,
    *,
    arroll_source: Path | None = None,
) -> dict[str, Any]:
    """Build the delivery source record from approved recipes and artifacts."""
    try:
        checked_plan = visual_plan.validate_visual_plan(visual_plan_payload)
        if arroll_source is not None:
            _validate_rendered_asset_manifest(
                job, checked_plan, asset_manifest_payload, arroll_source
            )
        if type(asset_manifest_payload) is not dict:
            raise _blocked()
        asset_identity = asset_manifest_payload.get("asset_manifest_sha256")
        asset_base = {
            key: value
            for key, value in asset_manifest_payload.items()
            if key != "asset_manifest_sha256"
        }
        if (
            not _valid_sha256(asset_identity)
            or asset_identity != contract_artifacts.sha256_json(asset_base)
            or asset_manifest_payload.get("schema_version") != 3
            or asset_manifest_payload.get("job_id") != job.job_id
            or asset_manifest_payload.get("visual_plan_sha256")
            != checked_plan["visual_plan_sha256"]
            or type(asset_manifest_payload.get("segments")) is not list
        ):
            raise _blocked()
        asset_segments = {
            item.get("segment_id"): item
            for item in asset_manifest_payload["segments"]
            if type(item) is dict and type(item.get("segment_id")) is str
        }
        if len(asset_segments) != len(asset_manifest_payload["segments"]):
            raise _blocked()
        records: list[dict[str, Any]] = []
        for segment in checked_plan["segments"]:
            rendered = asset_segments.get(segment["segment_id"])
            if type(rendered) is not dict:
                raise _blocked()
            artifacts = rendered.get("component_artifacts")
            recipe_components = segment["shot_recipe"]["components"]
            if (
                type(artifacts) is not list
                or len(artifacts) != len(recipe_components)
                or [item.get("component_id") for item in artifacts if type(item) is dict]
                != [item["component_id"] for item in recipe_components]
            ):
                raise _blocked()
            records.extend(
                _source_component_record(job, segment, component, artifact)
                for component, artifact in zip(recipe_components, artifacts)
            )
        if set(asset_segments) != {
            segment["segment_id"] for segment in checked_plan["segments"]
        }:
            raise _blocked()
        base = {
            "schema_version": 1,
            "job_id": job.job_id,
            "visual_plan_sha256": checked_plan["visual_plan_sha256"],
            "asset_manifest_sha256": asset_identity,
            "components": records,
        }
        result = {
            **base,
            "source_manifest_sha256": contract_artifacts.sha256_json(base),
        }
        return validate_source_manifest(
            Path(job.job_dir),
            result,
            job_id=job.job_id,
            visual_plan_sha256=checked_plan["visual_plan_sha256"],
            asset_manifest_sha256=asset_identity,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except PreviewV2Error:
        raise
    except BaseException:
        raise _blocked() from None


def _validate_kind_record(job_dir: Path, record: Mapping[str, Any]) -> None:
    kind = record["kind"]
    provenance = record["provenance"]
    details = provenance["details"]
    activity = record["activity_record"]
    attribution = record["attribution"]
    artifact = record["artifact"]
    configurations = {
        "local_material": {
            "detail_keys": {"material_id"},
            "source_id_field": "material_id",
            "time_field": "artifact_file_mtime",
            "activity_keys": None,
        },
        "official_material": {
            "detail_keys": {"source_id", "publisher", "source_url"},
            "source_id_field": "source_id",
            "time_field": "fetched_at",
            "activity_keys": {
                "type",
                "source_url",
                "snapshot_path",
                "fetched_at",
                "sha256",
            },
        },
        "external_stock": {
            "detail_keys": {"provider", "provider_asset_id", "author", "asset_page"},
            "source_id_field": "provider_asset_id",
            "time_field": "downloaded_at",
            "activity_keys": {
                "type",
                "provider",
                "provider_asset_id",
                "downloaded_at",
                "job_path",
                "sha256",
                "bytes",
                "license_snapshot",
                "license_sha256",
            },
        },
        "code_generated": {
            "detail_keys": {"dependency_id", "entrypoint", "producer_version"},
            "source_id_field": "dependency_id",
            "time_field": "artifact_file_mtime",
            "activity_keys": {
                "type",
                "dependency_id",
                "entrypoint",
                "producer_version",
                "brief_sha256",
                "invocation_record_sha256",
                "invocation_type",
                "invocation_id",
                "invocation_evidence_sha256",
                "primary_renderer",
                "renderer_version",
                "output_sha256",
            },
        },
        "ai_generated": {
            "detail_keys": {"provider", "model", "generation_id"},
            "source_id_field": "generation_id",
            "time_field": "artifact_file_mtime",
            "activity_keys": {
                "type",
                "provider",
                "model",
                "endpoint_id",
                "generation_id",
                "prompt_sha256",
                "output_sha256",
            },
        },
    }
    configuration = configurations.get(kind)
    if configuration is None or set(details) != configuration["detail_keys"]:
        raise _blocked()
    if any(type(value) is not str or not value for value in details.values()):
        raise _blocked()
    if details[configuration["source_id_field"]] != record["source_asset_id"]:
        raise _blocked()
    is_material = kind in {
        "local_material",
        "official_material",
        "external_stock",
    }
    if is_material != (provenance["source_path"] is not None):
        raise _blocked()
    if is_material and type(provenance["source_bytes"]) is not int:
        raise _blocked()
    if not is_material and provenance["source_bytes"] is not None:
        raise _blocked()
    if record["source_time"]["field"] != configuration["time_field"]:
        raise _blocked()
    activity_keys = configuration["activity_keys"]
    if activity_keys is None:
        if activity is not None:
            raise _blocked()
    elif type(activity) is not dict or set(activity) != activity_keys:
        raise _blocked()
    else:
        if any(
            type(value) is not str or not value
            for key, value in activity.items()
            if key != "bytes"
        ):
            raise _blocked()
        if "bytes" in activity and (
            type(activity["bytes"]) is not int or activity["bytes"] <= 0
        ):
            raise _blocked()
        for key, value in activity.items():
            if key.endswith("sha256") and not _valid_sha256(value):
                raise _blocked()
        expected_type = {
            "official_material": "download",
            "external_stock": "download",
            "code_generated": "invocation",
            "ai_generated": "generation",
        }[kind]
        if activity["type"] != expected_type:
            raise _blocked()
    if kind == "official_material" and (
        activity["snapshot_path"] != provenance["source_path"]
        or activity["sha256"] != provenance["source_sha256"]
        or activity["source_url"] != details["source_url"]
    ):
        raise _blocked()
    if kind == "external_stock":
        if (
            activity["job_path"] != provenance["source_path"]
            or activity["sha256"] != provenance["source_sha256"]
            or activity["bytes"] != provenance["source_bytes"]
            or activity["provider"] != details["provider"]
            or activity["provider_asset_id"] != details["provider_asset_id"]
        ):
            raise _blocked()
        _job_file(
            job_dir,
            activity["license_snapshot"],
            sha256=activity["license_sha256"],
        )
    if kind == "code_generated" and (
        activity["dependency_id"] != details["dependency_id"]
        or activity["entrypoint"] != details["entrypoint"]
        or activity["producer_version"] != details["producer_version"]
        or activity["brief_sha256"] != provenance["source_sha256"]
        or activity["output_sha256"] != artifact["sha256"]
        or activity["invocation_type"] not in {"reference_process", "skill_invocation"}
    ):
        raise _blocked()
    if kind == "ai_generated" and (
        activity["provider"] != details["provider"]
        or activity["model"] != details["model"]
        or activity["generation_id"] != details["generation_id"]
        or activity["prompt_sha256"] != provenance["source_sha256"]
        or activity["output_sha256"] != artifact["sha256"]
    ):
        raise _blocked()
    if kind == "external_stock":
        if type(attribution) is not dict:
            raise _blocked()
    elif attribution is not None:
        raise _blocked()
    expected_final_id = (
        f"{record['segment_id']}:{record['component_id']}:{artifact['sha256']}"
    )
    if record["final_asset_id"] != expected_final_id:
        raise _blocked()


def validate_source_manifest(
    job_dir: Path,
    payload: object,
    *,
    job_id: str | None = None,
    visual_plan_sha256: str | None = None,
    asset_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the closed delivery source schema and current artifact bytes."""
    try:
        if type(payload) is not dict or set(payload) != _SOURCE_MANIFEST_KEYS:
            raise _blocked()
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or type(payload["job_id"]) is not str
            or not payload["job_id"]
            or (job_id is not None and payload["job_id"] != job_id)
            or not _valid_sha256(payload["visual_plan_sha256"])
            or not _valid_sha256(payload["asset_manifest_sha256"])
            or (
                visual_plan_sha256 is not None
                and payload["visual_plan_sha256"] != visual_plan_sha256
            )
            or (
                asset_manifest_sha256 is not None
                and payload["asset_manifest_sha256"] != asset_manifest_sha256
            )
        ):
            raise _blocked()
        base = {
            key: value for key, value in payload.items() if key != "source_manifest_sha256"
        }
        if (
            not _valid_sha256(payload["source_manifest_sha256"])
            or payload["source_manifest_sha256"]
            != contract_artifacts.sha256_json(base)
            or type(payload["components"]) is not list
        ):
            raise _blocked()
        seen: set[tuple[str, str]] = set()
        for record in payload["components"]:
            if type(record) is not dict or set(record) != _SOURCE_COMPONENT_KEYS:
                raise _blocked()
            identity = (record.get("segment_id"), record.get("component_id"))
            if (
                any(type(item) is not str or not item for item in identity)
                or identity in seen
                or type(record.get("kind")) is not str
                or type(record.get("semantic_role")) is not str
                or type(record.get("source_asset_id")) is not str
                or not record["source_asset_id"]
                or type(record.get("final_asset_id")) is not str
                or not record["final_asset_id"]
            ):
                raise _blocked()
            seen.add(identity)
            provenance = record["provenance"]
            if (
                type(provenance) is not dict
                or set(provenance)
                != {"kind", "source_path", "source_sha256", "source_bytes", "details"}
                or provenance["kind"] != record["kind"]
                or not _valid_sha256(provenance["source_sha256"])
                or type(provenance["details"]) is not dict
            ):
                raise _blocked()
            if provenance["source_path"] is None:
                if provenance["source_bytes"] is not None:
                    raise _blocked()
            else:
                _job_file(
                    job_dir,
                    provenance["source_path"],
                    sha256=provenance["source_sha256"],
                    byte_count=provenance["source_bytes"],
                )
            source_time = record["source_time"]
            artifact = record["artifact"]
            qa = record["qa"]
            if (
                type(source_time) is not dict
                or set(source_time) != {"field", "value"}
                or any(type(source_time[key]) is not str or not source_time[key] for key in source_time)
                or type(artifact) is not dict
                or set(artifact) != {"job_path", "media_type", "bytes", "sha256"}
                or type(artifact["media_type"]) is not str
                or not artifact["media_type"]
                or type(qa) is not dict
                or set(qa) != {"passed", "record_sha256"}
                or qa["passed"] is not True
                or not _valid_sha256(qa["record_sha256"])
            ):
                raise _blocked()
            _job_file(
                job_dir,
                artifact["job_path"],
                sha256=artifact["sha256"],
                byte_count=artifact["bytes"],
            )
            if record["activity_record"] is not None and type(record["activity_record"]) is not dict:
                raise _blocked()
            not_selected = record["not_selected_candidates"]
            if type(not_selected) is not list:
                raise _blocked()
            for candidate in not_selected:
                if (
                    type(candidate) is not dict
                    or set(candidate) != {"asset_id", "kind", "reason"}
                    or candidate["kind"] != record["kind"]
                    or candidate["reason"]
                    != "ranked_after_selected_same_kind_candidate"
                    or type(candidate["asset_id"]) is not str
                    or not candidate["asset_id"]
                ):
                    raise _blocked()
            attribution = record["attribution"]
            if attribution is not None and (
                type(attribution) is not dict
                or set(attribution)
                != {
                    "required",
                    "provider",
                    "author",
                    "asset_page",
                    "license",
                    "license_version",
                }
                or type(attribution["required"]) is not bool
                or any(
                    type(attribution[key]) is not str or not attribution[key]
                    for key in (
                        "provider",
                        "author",
                        "asset_page",
                        "license",
                        "license_version",
                    )
                )
            ):
                raise _blocked()
            _validate_kind_record(job_dir, record)
        return payload
    except (KeyboardInterrupt, SystemExit):
        raise
    except PreviewV2Error:
        raise
    except BaseException:
        raise _blocked() from None


def validate_source_manifest_against_approved_sources(
    job: Any,
    payload: object,
    visual_plan_payload: object,
    asset_manifest_payload: object,
    *,
    arroll_source: Path,
) -> dict[str, Any]:
    """Validate source records against the current approved component set."""
    expected = build_source_manifest(
        job,
        visual_plan_payload,
        asset_manifest_payload,
        arroll_source=arroll_source,
    )
    checked = validate_source_manifest(
        Path(job.job_dir),
        payload,
        job_id=job.job_id,
        visual_plan_sha256=expected["visual_plan_sha256"],
        asset_manifest_sha256=expected["asset_manifest_sha256"],
    )

    if checked["components"] != expected["components"]:
        raise _blocked()
    return checked


def build_preview_command_v2(
    visual: Path,
    subtitle_track: Path,
    edited_aroll: Path,
    output: Path,
    *,
    frames: int,
    duration: float,
    opening: Mapping[str, Any] | None = None,
    cover: Path | None = None,
    mixed_audio: Path | None = None,
) -> list[str]:
    if mixed_audio is not None:
        command = build_preview_command_v2(visual, subtitle_track, edited_aroll, output,
            frames=frames, duration=duration, opening=opening, cover=cover)
        index = command.index("-filter_complex")
        if opening is not None:
            # The mix already uses the final clock; remove the unused body-audio branch.
            command[index + 1] = command[index + 1].split(";[2:a:0]", 1)[0]
        audio_map = command.index("[outa]" if opening is not None else "2:a:0")
        command[audio_map] = "4:a:0" if opening is not None else "3:a:0"
        command[index:index] = ["-i", str(mixed_audio)]
        return command
    if frames <= 0 or duration <= 0 or frames != round(duration * 24):
        raise PreviewV2Error("preview clock is invalid")
    if opening is not None:
        if cover is None or opening["body_frames"] != frames:
            raise PreviewV2Error("opening does not match the body clock")
        hold = opening["body_offset_frames"]
        transition = opening["options"]["transition_frames"]
        total_frames = opening["total_frames"]
        # Padding is covered by the approved image. Body frame zero and its
        # original audio start together at hold/24, not (hold+transition)/24.
        filters = (
            "[0:v]fps=24,format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v];"
            "[1:v]fps=24,format=rgba,setpts=PTS-STARTPTS[s];"
            "[v][s]overlay=0:0:eof_action=pass:shortest=1,"
            f"tpad=start={hold}:start_mode=clone[body];"
            "[3:v]format=rgba,setsar=1,setpts=PTS-STARTPTS"
        )
        if transition:
            filters += f",fade=t=out:st={hold / 24:.9f}:d={transition / 24:.9f}:alpha=1"
        filters += (
            "[cover];[body][cover]overlay=0:0:eof_action=pass:shortest=0:"
            f"enable='lt(n,{hold + transition})'[outv];"
            "[2:a:0]aresample=48000,asetpts=PTS-STARTPTS,"
            f"adelay={hold * 2000}S:all=1[outa]"
        )
        return [
            "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
            "-threads", "1", "-reinit_filter", "0", "-i", str(visual), "-threads", "1",
            "-c:v", "libvpx-vp9", "-reinit_filter", "0", "-i", str(subtitle_track),
            "-threads", "1", "-i", str(edited_aroll),
            "-loop", "1", "-framerate", "24", "-t", f"{(hold + transition + 1) / 24:.9f}",
            "-i", str(cover), "-filter_complex_threads", "1", "-filter_complex", filters,
            "-map", "[outv]", "-map", "[outa]", "-frames:v", str(total_frames),
            # Keep decoding/filtering bounded; one encoder may use four CPU threads.
            "-c:v", "libx264", "-threads", "4", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", f"{total_frames / 24:.9f}", "-movflags", "+faststart", "-y", str(output),
        ]
    if cover is not None:
        raise PreviewV2Error("cover needs an explicit opening plan")
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        # Native segment color metadata may change at a cut. Reinitializing
        # this geometry-locked graph would reset N and the subtitle clock.
        "-reinit_filter", "0", "-i", str(visual), "-c:v", "libvpx-vp9",
        "-reinit_filter", "0", "-i", str(subtitle_track),
        "-i", str(edited_aroll),
        "-filter_complex",
        "[0:v]setpts=N/(24*TB),fps=24,format=yuv420p,setpts=PTS-STARTPTS,"
        "tpad=stop_mode=clone:stop_duration=5[v];"
        "[1:v]setpts=N/(24*TB),fps=24,format=rgba,setpts=PTS-STARTPTS,"
        "tpad=stop_mode=clone:stop_duration=5[s];"
        # The VP9 subtitle track may carry a sparse tail timestamp even when
        # its decoded frame count matches the approved clock.  The visual
        # track is authoritative; preserve it through the explicit frame
        # count instead of letting shortest=1 truncate the preview early.
        "[v][s]overlay=0:0:eof_action=pass:shortest=0[outv]",
        "-map", "[outv]", "-map", "2:a:0", "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-t", f"{duration:.6f}",
        "-movflags", "+faststart", "-y", str(output),
    ]


def _approved(job: state.JobState, stage_id: str, relative: str) -> Path:
    stage = job.stages[stage_id]
    if stage["status"] != "approved":
        raise PreviewV2Error(f"{stage_id} must be approved")
    matches = [record for record in stage["artifacts"] if record.get("path") == relative]
    path = job.job_dir / relative
    if (
        len(matches) != 1
        or not path.is_file()
        or matches[0].get("sha256") != contract_artifacts.sha256_file(path)
        or matches[0].get("bytes") != path.stat().st_size
    ):
        raise PreviewV2Error(f"approved {relative} changed")
    return path


def _published_preview(job: state.JobState, relative: str) -> Path:
    stage = job.stages["preview"]
    if stage["status"] not in {"ready_for_review", "approved"}:
        raise PreviewV2Error("preview output is not published")
    matches = [record for record in stage["artifacts"] if record.get("path") == relative]
    path = job.job_dir / relative
    if (
        len(matches) != 1
        or not path.is_file()
        or matches[0].get("sha256") != contract_artifacts.sha256_file(path)
        or matches[0].get("bytes") != path.stat().st_size
    ):
        raise PreviewV2Error(f"published {relative} changed")
    return path


def _validate_published_preview_inventory(
    job: state.JobState,
    report: Mapping[str, Any],
) -> None:
    report_base = {
        key: value for key, value in report.items() if key != "qa_report_sha256"
    }
    evidence = report.get("evidence")
    if (
        not _valid_sha256(report.get("qa_report_sha256"))
        or report["qa_report_sha256"]
        != contract_artifacts.sha256_json(report_base)
        or type(evidence) is not list
        or not evidence
    ):
        raise PreviewV2Error("preview report is incomplete")
    evidence_paths: list[str] = []
    for record in evidence:
        if (
            type(record) is not dict
            or set(record) != {"path", "sha256"}
            or type(record.get("path")) is not str
            or not record["path"].startswith("keyframes/")
            or not _valid_sha256(record.get("sha256"))
            or record["path"] in evidence_paths
        ):
            raise PreviewV2Error("preview evidence record is incomplete")
        evidence_paths.append(record["path"])
    expected = {
        "11-preview/review.mp4",
        "11-preview/qa-report.json",
        "11-preview/source-manifest.json",
        *(f"11-preview/{path}" for path in evidence_paths),
    }
    if "opening_manifest_sha256" in report:
        expected.update({"11-preview/opening-manifest.json", "11-preview/subtitles.srt"})
    if report.get("background_music") is True:
        expected.update(f"11-preview/{name}" for name in preview_music.ATTACHMENTS)
    if "event_audio_plan_sha256" in report:
        expected.update({"11-preview/event-audio-plan.json", "11-preview/event-audio.m4a"})
    artifact_paths = [
        record.get("path") for record in job.stages["preview"]["artifacts"]
    ]
    receipt_path = "11-preview/material-usage.json"
    if receipt_path in artifact_paths:
        expected.add(receipt_path)
    if len(artifact_paths) != len(expected) or set(artifact_paths) != expected:
        raise PreviewV2Error("preview artifact inventory is incomplete")
    for relative in expected:
        path = _published_preview(job, relative)
        if relative.startswith("11-preview/keyframes/"):
            record = next(
                item
                for item in evidence
                if f"11-preview/{item['path']}" == relative
            )
            if contract_artifacts.sha256_file(path) != record["sha256"]:
                raise PreviewV2Error("preview evidence bytes changed")
    target = Path(job.job_dir) / "11-preview"
    actual = {
        f"11-preview/{path.relative_to(target).as_posix()}"
        for path in target.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise PreviewV2Error("preview file inventory is incomplete")
    if receipt_path in expected:
        material_usage.load_current_receipt(job, "preview")
    validate_preview_opening(job, report)
    validate_preview_music(job, report)
    validate_preview_event_audio(job, report)


def validate_preview_music(job, report):
    target = Path(job.job_dir) / "11-preview"
    indicated = (report.get("background_music") is True or "music_manifest_sha256" in report
                 or (target / preview_music.MANIFEST).exists()
                 or any(r.get("path") == "11-preview/music-manifest.json"
                        for r in job.stages["preview"]["artifacts"]))
    if not indicated:
        if (("background_music" in report and report["background_music"] is not False)
                or ("event_audio_plan_sha256" not in report
                    and "audio_mix_layers" in report
                    and report["audio_mix_layers"] != 1)):
            raise PreviewV2Error("preview audio mode is invalid")
        return None
    try:
        for name in preview_music.ATTACHMENTS:
            _published_preview(job, f"11-preview/{name}")
        manifest = preview_music.validate_metadata(job, target,
            contract_artifacts.read_json_artifact(target / preview_music.MANIFEST),
            _approved(job, "edit_structure", "06-edit-structure/edited-aroll.mp4"))
        opening = validate_preview_opening(job, report)
        asset = contract_artifacts.read_json_artifact(
            _approved(job, "visual_assets", "09-visual-assets/asset-manifest.json"))
        frames = round(float(asset["duration"]) * 24) if opening is None else opening["total_frames"]
        offset = 0 if opening is None else opening["body_offset_frames"]
        if (report.get("background_music") is not True or report.get("audio_mix_layers") != 2
                or report.get("music_manifest_sha256") != manifest["music_manifest_sha256"]
                or report.get("preview_sha256") != manifest["preview_sha256"]
                or manifest["plan"]["total_frames"] != frames
                or manifest["plan"]["body_offset_frames"] != offset
                or report.get("media", {}).get("frames") != frames):
            raise PreviewV2Error("preview music identity or clock changed")
        return manifest
    except (preview_music.MusicError, OSError, ValueError, TypeError, KeyError) as exc:
        raise PreviewV2Error("music evidence is incomplete or changed") from exc


def validate_preview_event_audio(job: state.JobState, report: Mapping[str, Any]):
    indicated = "event_audio_plan_sha256" in report
    if not indicated:
        return None
    try:
        asset = contract_artifacts.read_json_artifact(
            _approved(job, "visual_assets", "09-visual-assets/asset-manifest.json")
        )
        plan = _approved_event_audio_plan(job, frames=round(float(asset["duration"]) * 24))
        published_plan = contract_artifacts.read_json_artifact(
            _published_preview(job, "11-preview/event-audio-plan.json")
        )
        path = _published_preview(job, "11-preview/event-audio.m4a")
        if plan is None or published_plan != plan or report["event_audio_plan_sha256"] != plan["plan_sha256"]:
            raise PreviewV2Error("event audio plan identity changed")
        if report.get("event_audio_cue_ids") != [cue["cue_id"] for cue in plan["cues"]]:
            raise PreviewV2Error("event audio cue identity changed")
        if contract_artifacts.sha256_file(path) != report.get("event_audio_mix_sha256"):
            raise PreviewV2Error("event audio mix identity changed")
        return plan
    except (event_audio.EventAudioError, OSError, ValueError, TypeError, KeyError) as exc:
        raise PreviewV2Error("event audio evidence is incomplete or changed") from exc


def validate_preview_opening(job: state.JobState, report: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read-only optional contract; missing evidence must not become body-only."""
    target = Path(job.job_dir) / "11-preview"
    manifest_path = target / preview_opening.MANIFEST
    indicated = (
        "opening_manifest_sha256" in report or manifest_path.exists() or manifest_path.is_symlink()
        or any(record.get("path") == "11-preview/opening-manifest.json"
               for record in job.stages["preview"]["artifacts"])
    )
    if not indicated:
        return None
    try:
        path = _published_preview(job, "11-preview/opening-manifest.json")
        _published_preview(job, "11-preview/subtitles.srt")
        asset = contract_artifacts.read_json_artifact(
            _approved(job, "visual_assets", "09-visual-assets/asset-manifest.json")
        )
        manifest = preview_opening.validate_metadata(
            job, target, contract_artifacts.read_json_artifact(path),
            body_frames=round(float(asset["duration"]) * 24),
        )
        if (report.get("opening_manifest_sha256") != manifest["opening_manifest_sha256"]
                or report.get("preview_sha256") != manifest["preview_sha256"]
                or report.get("media", {}).get("frames") != manifest["total_frames"]
                or report.get("media", {}).get("duration") != manifest["total_frames"] / 24):
            raise PreviewV2Error("preview report does not match opening clock")
        return manifest
    except (OSError, ValueError, KeyError, TypeError, preview_opening.OpeningError,
            contract_artifacts.ContractArtifactError) as exc:
        raise PreviewV2Error("opening evidence is incomplete or changed") from exc


def _probe(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-count_frames",
                "-show_entries",
                "stream=index,codec_type,width,height,r_frame_rate,nb_read_frames,duration,"
                "sample_aspect_ratio,display_aspect_ratio,start_time,pix_fmt:stream_side_data=rotation",
                "-show_entries", "format=duration", "-of", "json", str(path),
            ],
            check=True, capture_output=True, text=True, timeout=180,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise PreviewV2Error("preview media probe failed") from exc


def _validate_media(path: Path, *, frames: int, duration: float,
                    require_opening_contract: bool = False) -> dict[str, Any]:
    payload = _probe(path)
    streams = payload.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if (
        len(video) != 1
        or len(audio) != 1
        or video[0].get("width") != 1080
        or video[0].get("height") != 1920
        or video[0].get("r_frame_rate") != "24/1"
        or int(video[0].get("nb_read_frames", 0)) != frames
        or abs(float(payload["format"]["duration"]) - duration) > 1 / 24 + 0.01
    ):
        raise PreviewV2Error("preview is not one native video plus one synced audio track")
    if require_opening_contract:
        if (video[0].get("sample_aspect_ratio") != "1:1"
                or video[0].get("display_aspect_ratio") != "9:16"
                or video[0].get("pix_fmt") != "yuv420p"
                or any(abs(float(stream.get("start_time", -1))) > .001 for stream in (video[0], audio[0]))
                or any(abs(float(stream.get("duration", 0)) - duration) > 1 / 24 + .01
                       for stream in (video[0], audio[0]))
                or any(float(side.get("rotation", 0)) != 0 for side in video[0].get("side_data_list", []))):
            raise PreviewV2Error("opening output has invalid pixel geometry or audio/video timing")
        try:
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-threads", "1",
                "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
            ], check=True, capture_output=True, timeout=max(180, int(duration * 5)))
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreviewV2Error("opening output full decode failed") from exc
    return {
        "width": 1080,
        "height": 1920,
        "fps": 24,
        "frames": frames,
        "duration": duration,
        "video_streams": 1,
        "audio_streams": 1,
    }


def _extract_frames(video: Path, output: Path, duration: float) -> list[Path]:
    output.mkdir()
    frames = []
    for index, ratio in enumerate((0.1, 0.25, 0.5, 0.75, 0.9), start=1):
        frame = output / f"frame-{index:02d}.png"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                    "-ss", f"{duration * ratio:.6f}", "-i", str(video),
                    "-frames:v", "1",
                    "-y", str(frame),
                ],
                check=True, capture_output=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreviewV2Error("preview evidence extraction failed") from exc
        frames.append(frame)
    return frames


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preview_tree_digest(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise PreviewV2Error("preview publication directory is incomplete")
    records = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink() or (not item.is_file() and not item.is_dir()):
            raise PreviewV2Error("preview publication entry is incomplete")
        if item.is_file():
            records.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "sha256": contract_artifacts.sha256_file(item),
                    "bytes": item.stat().st_size,
                }
            )
    return contract_artifacts.sha256_json(records)


def _fsync_preview_tree(path: Path) -> None:
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


def _write_preview_journal(job_dir: Path, payload: Mapping[str, Any]) -> None:
    path = Path(job_dir) / _PREVIEW_JOURNAL
    stage = Path(job_dir) / f".{_PREVIEW_JOURNAL}.stage-{secrets.token_hex(8)}"
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


def _clear_preview_journal(job_dir: Path) -> None:
    path = Path(job_dir) / _PREVIEW_JOURNAL
    if path.exists():
        path.unlink()
        _fsync_directory(Path(job_dir))


def _remove_preview_tree(path: Path, expected_digest: str) -> None:
    if path.exists():
        if _preview_tree_digest(path) != expected_digest:
            raise PreviewV2Error("preview publication directory changed")
        shutil.rmtree(path)
        _fsync_directory(path.parent)


def _recover_preview_publication(job: state.JobState) -> None:
    job_dir = Path(job.job_dir)
    journal_path = job_dir / _PREVIEW_JOURNAL
    if not journal_path.exists():
        return
    try:
        payload = contract_artifacts.read_json_artifact(journal_path)
    except contract_artifacts.ContractArtifactError:
        raise PreviewV2Error("preview publication record is incomplete") from None
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
            job_dir, payload.get("stage_name"), ".11-preview.stage-"
        )
        or type(payload.get("had_target")) is not bool
        or not _valid_sha256(payload.get("new_tree_sha256"))
    ):
        raise PreviewV2Error("preview publication record is incomplete")
    had_target = payload["had_target"]
    backup_name = payload["backup_name"]
    old_digest = payload["old_tree_sha256"]
    if had_target != (
        _direct_publication_child_name(
            job_dir, backup_name, ".11-preview.backup-"
        )
        and _valid_sha256(old_digest)
    ):
        raise PreviewV2Error("preview publication record is incomplete")
    if not had_target and (backup_name is not None or old_digest is not None):
        raise PreviewV2Error("preview publication record is incomplete")
    target = job_dir / "11-preview"
    stage = job_dir / payload["stage_name"]
    backup = None if backup_name is None else job_dir / backup_name
    new_digest = payload["new_tree_sha256"]

    def digest(path: Path | None) -> str | None:
        if path is None or not path.exists():
            return None
        return _preview_tree_digest(path)

    target_digest = digest(target)
    stage_digest = digest(stage)
    backup_digest = digest(backup)
    if stage_digest not in {None, new_digest}:
        raise PreviewV2Error("preview recovery stage changed")
    if backup_digest not in {None, old_digest}:
        raise PreviewV2Error("preview recovery backup changed")
    committed = job.stages["preview"]["status"] in {
        "ready_for_review",
        "approved",
    }
    if committed:
        if target_digest != new_digest:
            raise PreviewV2Error("published preview is incomplete")
        _remove_preview_tree(stage, new_digest)
        if backup is not None:
            _remove_preview_tree(backup, old_digest)
        _clear_preview_journal(job_dir)
        return
    if had_target:
        if target_digest == new_digest:
            _remove_preview_tree(target, new_digest)
            target_digest = None
        elif target_digest not in {None, old_digest}:
            raise PreviewV2Error("preview recovery target changed")
        if target_digest is None:
            if backup is None or digest(backup) != old_digest:
                raise PreviewV2Error("preview recovery backup is incomplete")
            os.replace(backup, target)
            _fsync_directory(job_dir)
        elif backup is not None:
            _remove_preview_tree(backup, old_digest)
    else:
        if target_digest == new_digest:
            _remove_preview_tree(target, new_digest)
        elif target_digest is not None:
            raise PreviewV2Error("preview recovery target changed")
    _remove_preview_tree(stage, new_digest)
    _clear_preview_journal(job_dir)


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


def _publish_preview(
    job: state.JobState,
    stage: Path,
    target: Path,
    artifact_paths: list[str],
) -> None:
    job_dir = Path(job.job_dir)
    had_target = target.exists()
    old_digest = _preview_tree_digest(target) if had_target else None
    new_digest = _preview_tree_digest(stage)
    backup = (
        job_dir / f".11-preview.backup-{secrets.token_hex(8)}"
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
    _fsync_preview_tree(stage)
    _write_preview_journal(job_dir, journal)
    if backup is not None:
        os.replace(target, backup)
        _fsync_directory(job_dir)
    os.replace(stage, target)
    _fsync_directory(job_dir)
    _write_preview_journal(job_dir, {**journal, "state": "installed"})
    snapshot = _job_snapshot(job)
    try:
        state.mark_ready(
            job,
            "preview",
            tuple(target / relative for relative in artifact_paths),
        )
    except BaseException as exc:
        if isinstance(exc, state._CommittedWorkflowError):
            _recover_preview_publication(job)
        else:
            _restore_job_snapshot(job, snapshot)
            _recover_preview_publication(job)
        raise
    if backup is not None:
        _remove_preview_tree(backup, old_digest)
    _clear_preview_journal(job_dir)


def _prepare_preview_v2_locked(job: state.JobState, *, opening: object = None, music: object = None):
    from .preview import PreviewResult

    if job.version != 2:
        raise PreviewV2Error("formal preview builder requires full-v2")
    _recover_preview_publication(job)
    target = job.job_dir / "11-preview"
    review = target / "review.mp4"
    report_path = target / "qa-report.json"
    if job.stages["preview"]["status"] in {"ready_for_review", "approved"}:
        review = _published_preview(job, "11-preview/review.mp4")
        report_path = _published_preview(job, "11-preview/qa-report.json")
        report = contract_artifacts.read_json_artifact(report_path)
        source_path = _published_preview(
            job, "11-preview/source-manifest.json"
        )
        source_manifest = contract_artifacts.read_json_artifact(source_path)
        visual_plan_payload = contract_artifacts.read_json_artifact(
            _approved(
                job, "visual_direction", "07-visual-direction/visual-plan.json"
            )
        )
        asset_manifest_payload = contract_artifacts.read_json_artifact(
            _approved(
                job, "visual_assets", "09-visual-assets/asset-manifest.json"
            )
        )
        arroll = _approved(
            job, "edit_structure", "06-edit-structure/edited-aroll.mp4"
        )
        validate_source_manifest_against_approved_sources(
            job,
            source_manifest,
            visual_plan_payload,
            asset_manifest_payload,
            arroll_source=arroll,
        )
        _validate_published_preview_inventory(job, report)
        if music is not None:
            saved_music = validate_preview_music(job, report)
            if saved_music is None or contract_artifacts.sha256_json(saved_music["plan"]["options"]) != contract_artifacts.sha256_json(music):
                raise PreviewV2Error("music changed; revise preview before rebuilding")
        if opening is not None:
            saved = validate_preview_opening(job, report)
            if saved is None or saved["options"] != opening:
                raise PreviewV2Error("opening changed; revise preview before rebuilding")
        if (
            review.is_file()
            and report.get("preview_sha256") == contract_artifacts.sha256_file(review)
            and report.get("source_manifest_sha256")
            == source_manifest["source_manifest_sha256"]
        ):
            artifacts = tuple(job.job_dir / record["path"] for record in job.stages["preview"]["artifacts"])
            return PreviewResult(target, review, artifacts, report, report["media"])
        raise PreviewV2Error("published preview changed after review")
    state.require_runnable(job, "preview")
    visual_plan_path = _approved(
        job, "visual_direction", "07-visual-direction/visual-plan.json"
    )
    visual = _approved(job, "visual_assets", "09-visual-assets/visual-track.mp4")
    manifest_path = _approved(job, "visual_assets", "09-visual-assets/asset-manifest.json")
    subtitles_track = _approved(job, "subtitles", "10-subtitles/subtitles.webm")
    subtitle_plan_path = _approved(job, "subtitles", "10-subtitles/subtitle-plan.json")
    arroll = _approved(job, "edit_structure", "06-edit-structure/edited-aroll.mp4")
    visual_plan_payload = contract_artifacts.read_json_artifact(visual_plan_path)
    manifest = contract_artifacts.read_json_artifact(manifest_path)
    source_manifest = build_source_manifest(
        job,
        visual_plan_payload,
        manifest,
        arroll_source=arroll,
    )
    subtitle_plan = contract_artifacts.read_json_artifact(subtitle_plan_path)
    try:
        talkcraft_subtitles.validate_binding(subtitle_plan)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise PreviewV2Error("preview requires verified TalkCraft subtitles") from exc
    duration = float(manifest["duration"])
    frames = round(duration * 24)
    if (
        manifest.get("canvas") != {"width": 1080, "height": 1920, "fps": 24}
        or subtitle_plan.get("visual_plan_sha256") != manifest.get("visual_plan_sha256")
        or subtitle_plan.get("render_plan", {}).get("canvas", {}).get("frames") != frames
    ):
        raise PreviewV2Error("preview source identities do not match")
    broll_segment_ids = {
        segment["segment_id"] for segment in visual_plan_payload["segments"]
        if segment["shot_recipe"]["mode"] != "none"
    }
    broll_subtitle_cue_count = sum(
        cue["segment_id"] in broll_segment_ids
        for cue in subtitle_plan["render_plan"]["cues"]
    )
    opening_plan = None
    if opening is not None:
        try:
            opening_plan = preview_opening.plan_opening(job, opening, body_frames=frames)
        except preview_opening.OpeningError as exc:
            raise PreviewV2Error(str(exc)) from exc
    output_frames = frames if opening_plan is None else opening_plan["total_frames"]
    output_duration = duration if opening_plan is None else output_frames / 24
    event_audio_plan = _approved_event_audio_plan(job, frames=frames)
    music_plan = None
    if music is not None:
        music_plan = preview_music.plan_music(job, music, frames=output_frames,
            voice_offset_frames=0 if opening_plan is None else opening_plan["body_offset_frames"])
    stage = job.job_dir / f".11-preview.stage-{secrets.token_hex(8)}"
    stage.mkdir()
    try:
        output = stage / "review.mp4"
        event_audio_mix = None
        if event_audio_plan is not None:
            if music_plan is not None:
                raise PreviewV2Error("event audio and background music require a combined mix plan")
            event_audio_mix = event_audio.prepare_stage_audio(
                event_audio_plan, arroll, stage / "event-audio.m4a"
            )
        mixed_audio = (
            event_audio_mix
            if event_audio_mix is not None
            else None if music_plan is None
            else preview_music.prepare_stage_audio(job, stage, music_plan, arroll)
        )
        command = build_preview_command_v2(
            visual,
            subtitles_track,
            arroll,
            output,
            frames=frames,
            duration=duration,
            **({"mixed_audio": mixed_audio} if mixed_audio is not None else {}),
            **({"opening": opening_plan, "cover": job.job_dir / opening_plan["cover"]["path"]}
               if opening_plan is not None else {}),
        )
        try:
            subprocess.run(
                command, check=True, capture_output=True,
                timeout=max(600, int(duration * 20)),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreviewV2Error("preview composition failed") from exc
        media = _validate_media(output, frames=output_frames, duration=output_duration,
                                **({"require_opening_contract": True} if opening_plan is not None or music_plan is not None else {}))
        music_manifest = None if music_plan is None else preview_music.publish_metadata(job, stage, music_plan, arroll)
        evidence = _extract_frames(output, stage / "keyframes", output_duration)
        opening_manifest = None
        if opening_plan is not None:
            opening_manifest = preview_opening.publish_metadata(job, stage, opening_plan)
            evidence += preview_opening.extract_evidence(output, stage / "keyframes", opening_plan)
        report_base = {
            "schema_version": 2,
            "status": "PASS",
            "preview_sha256": contract_artifacts.sha256_file(output),
            "visual_plan_sha256": manifest["visual_plan_sha256"],
            "source_manifest_sha256": source_manifest["source_manifest_sha256"],
            "subtitle_plan_sha256": subtitle_plan["subtitle_plan_sha256"],
            "broll_subtitle_cue_count": broll_subtitle_cue_count,
            "audio_source_sha256": contract_artifacts.sha256_file(arroll),
            "audio_mix_layers": (
                1 + len(event_audio_plan["cues"])
                if event_audio_plan is not None
                else 1 if music_manifest is None else 2
            ),
            "background_music": music_manifest is not None,
            **({
                "event_audio_plan_sha256": event_audio_plan["plan_sha256"],
                "event_audio_mix_sha256": contract_artifacts.sha256_file(event_audio_mix),
                "event_audio_cue_ids": [cue["cue_id"] for cue in event_audio_plan["cues"]],
            } if event_audio_plan is not None else {}),
            **({"music_manifest_sha256": music_manifest["music_manifest_sha256"]}
               if music_manifest is not None else {}),
            "media": media,
            **({"opening_manifest_sha256": opening_manifest["opening_manifest_sha256"]}
               if opening_manifest is not None else {}),
            "checks": {
                "native_9_16": True,
                "single_video_single_audio": True,
                "audio_uses_edited_aroll_clock": True,
                "audio_event_ids_bound": event_audio_plan is not None,
                "broll_subtitles_use_single_talkcraft_track": True,
                "approved_keyword_only": True,
                "approved_canary_reused": bool(manifest.get("reused_canary_segment_ids", [])),
                "source_manifest_complete": True,
            },
            "evidence": [
                {
                    "path": f"keyframes/{path.name}",
                    "sha256": contract_artifacts.sha256_file(path),
                }
                for path in evidence
            ],
        }
        contract_artifacts.write_json_artifact(
            stage / "source-manifest.json", source_manifest
        )
        if event_audio_plan is not None:
            contract_artifacts.write_json_artifact(
                stage / "event-audio-plan.json", event_audio_plan
            )
        report = {
            **report_base,
            "qa_report_sha256": contract_artifacts.sha256_json(report_base),
        }
        contract_artifacts.write_json_artifact(stage / "qa-report.json", report)
        artifact_paths = [
            "review.mp4",
            "qa-report.json",
            "source-manifest.json",
        ]
        if event_audio_plan is not None:
            artifact_paths.extend(["event-audio-plan.json", "event-audio.m4a"])
        artifact_paths.extend(f"keyframes/{path.name}" for path in evidence)
        references = []
        if music_manifest is not None:
            artifact_paths.extend(preview_music.ATTACHMENTS)
            preview_music.validate_metadata(job, stage, music_manifest, arroll)
            references = preview_music.material_references(music_plan, "11-preview", artifact_paths)
        if opening_manifest is not None:
            artifact_paths.extend([preview_opening.MANIFEST, preview_opening.OUTPUT_SRT])
            # Catch input mutation during a potentially long render before publication.
            preview_opening.validate_metadata(job, stage, opening_manifest, body_frames=frames)
        material_usage.write_staged_receipt(
            job,
            "preview",
            stage,
            target,
            artifact_paths,
            producer="edit.hd.tools.preview_v2",
            producer_version="2",
            stage_input_records=material_usage.current_stage_input_records(
                job, "preview"
            ),
            references=references,
        )
        artifact_paths.append("material-usage.json")
        _publish_preview(job, stage, target, artifact_paths)
        artifacts = tuple(target / relative for relative in artifact_paths)
        return PreviewResult(
            target,
            target / "review.mp4",
            artifacts,
            report,
            media,
        )
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def prepare_preview_v2(job: state.JobState, *, opening: object = None, music: object = None):
    with _PreviewLock(Path(job.job_dir)):
        current = (
            state.load_job(job.job_dir)
            if isinstance(job, state.JobState)
            else job
        )
        try:
            plan_path = _approved(current, "visual_direction", "07-visual-direction/visual-plan.json")
            confirmed_content.check_confirmed_content(
                current, contract_artifacts.read_json_artifact(plan_path)
            )
        except confirmed_content.ConfirmedContentError as error:
            raise PreviewV2Error(str(error)) from None
        options = {}
        if opening is not None:
            options["opening"] = opening
        if music is not None:
            options["music"] = music
        result = _prepare_preview_v2_locked(current, **options)
        if current is not job:
            state._synchronize_committed_job(job)
        return result

"""Fail-closed bridge from Workbench drafts to the HD workflow."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Sequence

from . import contract_artifacts, state, visual_plan


class TalkCraftWorkbenchBridgeError(ValueError):
    pass


def _fail(message: str) -> None:
    raise TalkCraftWorkbenchBridgeError(message)


def _sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} must be a lowercase sha256")
    return value


def _read_safe_draft(
    job_dir: Path, draft_path: Path
) -> tuple[Path, dict[str, object], str]:
    descriptors: list[int] = []
    payload_bytes = b""
    try:
        job_root = job_dir.resolve(strict=True)
        lexical = Path(os.path.abspath(os.fspath(draft_path)))
        relative = lexical.relative_to(job_root)
        if len(relative.parts) < 3 or relative.parts[:2] != (
            ".workbench", "drafts"
        ):
            _fail("Workbench draft must stay inside Job .workbench/drafts")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        directory_flags = (
            flags
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(job_root, directory_flags)
        descriptors.append(descriptor)
        for part in relative.parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        file_descriptor = os.open(
            relative.parts[-1],
            flags | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        descriptors.append(file_descriptor)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            _fail("Workbench draft must be a regular file")
        chunks = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload_bytes = b"".join(chunks)
    except TalkCraftWorkbenchBridgeError:
        raise
    except (OSError, ValueError):
        _fail("Workbench draft must stay inside Job .workbench/drafts")
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
    try:
        source = payload_bytes.decode("utf-8")
        preview = json.loads(source)
        if type(preview) is dict and preview.get("schema_version") == 4:
            _fail("Workbench v4 publication is not available yet")
        parsed = visual_plan.parse_visual_brief_json(source)
    except TalkCraftWorkbenchBridgeError:
        raise
    except (UnicodeError, ValueError, json.JSONDecodeError,
            visual_plan.VisualPlanError):
        _fail("Workbench visual draft is invalid")
    return lexical, parsed, contract_artifacts.sha256_json(parsed)


def apply_visual_direction_revision(
    job_dir: Path,
    director_brief: Path,
    official_preview_root: Path,
    *,
    base_revision: int,
    base_workflow_sha256: str,
    reason: str,
    artifact_scope: Sequence[str] = (),
    treatment_path: Path | None = None,
) -> dict[str, Any]:
    """Revise then prepare one schema-v3 draft using two workflow checkpoints.

    VisualPlan v4 publication is deliberately refused before state mutation
    until the v4 compiler can publish spans and TalkCraft brief bundles together.
    """

    if type(base_revision) is not int or base_revision < 0:
        _fail("base revision is invalid")
    _sha256(base_workflow_sha256, "base workflow sha256")
    if type(reason) is not str or not reason.strip():
        _fail("revision reason must be non-empty text")
    if (
        type(artifact_scope) not in {list, tuple}
        or any(type(item) is not str or not item for item in artifact_scope)
        or len(artifact_scope) != len(set(artifact_scope))
    ):
        _fail("artifact scope is invalid")

    try:
        job = state.load_job(Path(job_dir).resolve(strict=True))
    except (OSError, state.WorkflowError):
        _fail("Workbench Job is invalid")
    draft_path, draft_payload, draft_sha256 = _read_safe_draft(
        job.job_dir, Path(director_brief)
    )
    if (
        job.revision != base_revision
        or job.expected_sha256 != base_workflow_sha256
    ):
        _fail("Workbench revision conflicts with current workflow")

    # Refuse a missing or stale selection before revise changes the workflow.
    try:
        visual_plan._skill_selection_for_publication(job, draft_payload, treatment_path)
    except visual_plan.VisualPlanError as error:
        raise TalkCraftWorkbenchBridgeError(str(error)) from None

    try:
        state.revise(
            job,
            "visual_direction",
            reason.strip(),
            tuple(artifact_scope),
        )
        revised_revision = job.revision
        revised_workflow_sha256 = job.expected_sha256
        output = visual_plan.prepare_visual_direction(
            job,
            draft_path,
            Path(official_preview_root),
            expected_revision=revised_revision,
            expected_workflow_sha256=revised_workflow_sha256,
            director_brief_sha256=draft_sha256,
            director_brief_payload=draft_payload,
            treatment_path=treatment_path,
        )
    except (state.WorkflowError, visual_plan.VisualPlanError) as error:
        raise TalkCraftWorkbenchBridgeError(str(error)) from None

    current = state.load_job(job.job_dir)
    return {
        "schema_version": "talkcraft-workbench-revision-result/v1",
        "job_id": current.job_id,
        "outcome": "ready_for_review",
        "draft_sha256": draft_sha256,
        "base_checkpoint": {
            "revision": base_revision,
            "workflow_sha256": base_workflow_sha256,
        },
        "revised_checkpoint": {
            "revision": revised_revision,
            "workflow_sha256": revised_workflow_sha256,
        },
        "published_checkpoint": {
            "revision": current.revision,
            "workflow_sha256": current.expected_sha256,
        },
        "visual_plan_path": str(output.relative_to(current.job_dir)),
        "approval_status": "not_approved",
    }


__all__ = [
    "TalkCraftWorkbenchBridgeError",
    "apply_visual_direction_revision",
]

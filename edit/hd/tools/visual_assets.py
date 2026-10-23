"""Public ShotRecipe v2 visual-assets entry."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from . import contract_artifacts
from .state import JobState
from .visual_plan import VisualPlanError, validate_visual_plan


class VisualAssetsError(RuntimeError):
    """Raised when the public visual-assets request cannot be started."""


def _require_current_schema(job: JobState) -> None:
    if job.version != 2:
        raise VisualAssetsError("BROLL_SCHEMA_UNSUPPORTED")
    try:
        plan = contract_artifacts.read_json_artifact(
            job.job_dir / "07-visual-direction/visual-plan.json"
        )
    except (OSError, contract_artifacts.ContractArtifactError):
        raise VisualAssetsError("BROLL_SCHEMA_UNSUPPORTED") from None
    if type(plan) is not dict or plan.get("schema_version") != 3:
        raise VisualAssetsError("BROLL_SCHEMA_UNSUPPORTED")
    try:
        validate_visual_plan(plan)
    except VisualPlanError:
        raise VisualAssetsError("BROLL_SCHEMA_UNSUPPORTED") from None


def prepare_visual_assets(
    job: JobState,
    *,
    component_adapters: Mapping[str, object] | None = None,
    segment_ffmpeg_runner: Callable[[tuple[str, ...], float], None] | None = None,
    segment_probe: Callable[[Path], Mapping[str, object]] | None = None,
    segment_frame_extractor: Callable[[Path, float, Path], None] | None = None,
    segment_assembler: Callable[[list[Path], Path], None] | None = None,
) -> Path:
    """Build formal visual assets from the approved current visual plan."""

    _require_current_schema(job)
    from . import visual_assets_v2

    return visual_assets_v2.prepare_visual_assets_v2(
        job,
        component_adapters=(
            {} if component_adapters is None else component_adapters
        ),
        ffmpeg_runner=segment_ffmpeg_runner,
        probe=segment_probe,
        frame_extractor=segment_frame_extractor,
        assembler=segment_assembler,
    )


__all__ = ["VisualAssetsError", "prepare_visual_assets"]

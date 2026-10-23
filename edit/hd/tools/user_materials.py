"""Bridge runtime callers to the one canonical material lifecycle contract."""
import importlib.util
import os
from pathlib import Path
import sys


_CANONICAL_SCRIPTS = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts"


def _workspace(job_or_workspace):
    if isinstance(job_or_workspace, (str, os.PathLike)):
        return str(job_or_workspace)
    return str(getattr(job_or_workspace, "root", job_or_workspace))


def _lifecycle_module():
    scripts = _CANONICAL_SCRIPTS
    for name in ("initialize_video_job", "create_job_workspace", "verify_skill_release"):
        cached = sys.modules.get(name)
        if cached is not None and Path(getattr(cached, "__file__", "")).resolve() != scripts / f"{name}.py":
            raise ValueError("material contract module origin conflicts")
    spec = importlib.util.spec_from_file_location(
        "hd_shared_material_lifecycle", scripts / "manage_user_materials.py")
    if spec is None or spec.loader is None:
        raise ValueError("material lifecycle Skill entrypoint is unavailable")
    module = importlib.util.module_from_spec(spec)
    inserted = str(scripts) not in sys.path
    if inserted:
        sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(str(scripts))
    return module


def plan_material_change(
    job_or_workspace, operation, *, operation_id, source=None, material_id=None,
):
    """Return the canonical Skill's read-only material change plan."""
    return _lifecycle_module().plan_material_change(
        _workspace(job_or_workspace), operation, operation_id=operation_id,
        source=source, material_id=material_id,
    )


def apply_material_change(
    job_or_workspace, plan, *, confirmed_plan_hash,
):
    """Apply only the exact human-confirmed canonical plan."""
    return _lifecycle_module().apply_material_change(
        _workspace(job_or_workspace), plan,
        confirmed_plan_hash=confirmed_plan_hash,
    )


def require_active_material(job_or_workspace, material_id, sha256=None):
    """Resolve an active material through the same canonical contract."""
    return _lifecycle_module().require_active_material(
        _workspace(job_or_workspace), material_id, sha256,
    )


def assert_active_local_material(job, material_id, sha256):
    root = getattr(job, "root", None)
    if root is None:
        return  # Bare media resolver fixtures have no managed workspace.
    root = Path(root)
    if not any(os.path.lexists(root / name) for name in
               ("job-context.json", "initialization.json")):
        return  # Historical bare jobs are not silently migrated.
    try:
        require_active_material(root, material_id, sha256)
    except (RuntimeError, OSError, ValueError, ImportError) as exc:
        raise ValueError("local material is unavailable, retired or changed") from exc

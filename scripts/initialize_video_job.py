#!/usr/bin/env python3
"""Create one isolated workspace and its authoritative full-v2 workflow."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from create_job_workspace import JOB_DIRS, create_workspace, _write_json_atomic  # noqa: E402
from verify_skill_release import verify_release  # noqa: E402


class InitializeJobError(RuntimeError):
    """Raised when the current project cannot initialize a formal video Job."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_runtime(project_root):
    release = verify_release(SCRIPT_DIR.parent)
    if release["status"] != "pass":
        raise InitializeJobError(
            "Skill release integrity check failed: " + "; ".join(release["failures"])
        )
    resolved_project_root: Path | None = None
    if project_root is not None:
        resolved_project_root = Path(project_root).expanduser().resolve()
        state_module = resolved_project_root / "edit" / "hd" / "tools" / "state.py"
        if not state_module.is_file():
            raise InitializeJobError(
                f"project root has no full-v2 state engine: {resolved_project_root}"
            )
        for name, module in tuple(sys.modules.items()):
            if name != "edit" and not name.startswith("edit."):
                continue
            filename = getattr(module, "__file__", None)
            paths = [Path(filename)] if filename else [Path(p) for p in getattr(module, "__path__", ())]
            if any(not path.resolve().is_relative_to(resolved_project_root / "edit") for path in paths):
                raise InitializeJobError("cached project module origin conflicts; use a fresh Python process")
        if str(resolved_project_root) not in sys.path:
            sys.path.insert(0, str(resolved_project_root))
    try:
        from edit.hd.tools import state
        from edit.hd.tools.startup import assert_project_origin, runtime_identity
    except ImportError as exc:
        raise InitializeJobError(
            "edit.hd.tools.state is unavailable in the current project"
        ) from exc
    resolved_project_root = resolved_project_root or Path(state.__file__).resolve().parents[3]
    assert_project_origin(resolved_project_root)
    runtime = runtime_identity(resolved_project_root)
    identity = {"runtime": runtime, "project_root": str(resolved_project_root),
                "skill_release": {key: release[key] for key in ("root", "release_id", "manifest_sha256")}}
    return state, identity


def initialize_video_job(
    jobs_root: str | Path,
    title: str,
    video: str | Path,
    script: str | Path | None = None,
    user_files: list[str | Path] | tuple[str | Path, ...] = (),
    *,
    project_root: str | Path | None = None,
    script_text: str | None = None,
):
    if (script is None) == (script_text is None):
        raise InitializeJobError("provide exactly one script file or inline script text")
    if script_text is not None and (not isinstance(script_text, str) or not script_text.strip()):
        raise InitializeJobError("inline script must contain text")
    _state, identity = _current_runtime(project_root)
    video_path = Path(video).expanduser().resolve()
    script_path = Path(script).expanduser().resolve() if script is not None else None
    extras = [Path(value).expanduser().resolve() for value in user_files]
    ordered: list[Path] = []
    for path in (video_path, script_path, *extras):
        if path is not None and path not in ordered:
            ordered.append(path)
    primary = {"video": f"material-{ordered.index(video_path) + 1:04d}",
               "script": f"material-{ordered.index(script_path) + 1 if script_path else len(ordered) + 1:04d}"}
    workspace = create_workspace(
        jobs_root,
        title,
        ordered,
        create_output_directories=False,
        inline_script=script_text,
        initialization={**identity, "primary_material_ids": primary},
    )
    return resume_video_job(workspace, project_root=project_root)


def _local_path(workspace: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise InitializeJobError("invalid recovery path")
    path = workspace / relative
    if path.resolve() != path.absolute():
        raise InitializeJobError("recovery path must not contain symlinks")
    return path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_record(path: Path) -> dict:
    if not path.is_file() or path.stat().st_nlink != 1:
        raise InitializeJobError(f"recovery record missing or not exclusive: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(record, dict):
            raise ValueError("expected object")
        return record
    except (ValueError, UnicodeError) as exc:
        raise InitializeJobError(f"invalid recovery record: {path.name}") from exc


@contextmanager
def _initialization_lock(workspace):
    path = _local_path(workspace, ".initialization.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise InitializeJobError("initialization lock is not exclusive")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InitializeJobError("another initializer is using this workspace") from exc
        yield
    finally:
        os.close(descriptor)


def _finish_initialization(workspace, record, state, identity):
    if (record.get("schema_version") != 1 or record.get("phase") not in ("imported", "ready")
            or record.get("workspace") != str(workspace)):
        raise InitializeJobError("recovery record belongs to another workspace or schema")
    if any(record.get(key) != value for key, value in identity.items()):
        raise InitializeJobError("recovery runtime/release identity changed; explicit migration required")
    inputs = record.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"video", "script"}:
        raise InitializeJobError("recovery primary inputs are missing")
    paths = {}
    for role, item in inputs.items():
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"}:
            raise InitializeJobError("invalid recovery input record")
        path = _local_path(workspace, item["path"])
        if (not item["path"].startswith("00-user-provided/") or not path.is_file()
                or path.stat().st_nlink != 1 or path.stat().st_size != item["bytes"]
                or _sha256(path) != item["sha256"]):
            raise InitializeJobError(f"imported input changed: {role}")
        paths[role] = path
    context_path = _local_path(workspace, "job-context.json")
    index_path = _local_path(workspace, "00-user-provided/material-index.json")
    index = _read_record(index_path)
    if record["phase"] == "imported":
        if _sha256(index_path) != record.get("material_index_sha256"):
            raise InitializeJobError("material index changed during initialization")
        for asset in index["assets"]:
            path = _local_path(workspace, asset["imported_path"])
            if (not path.is_file() or path.stat().st_nlink != 1
                    or path.stat().st_size != asset["size_bytes"] or _sha256(path) != asset["sha256"]):
                raise InitializeJobError("imported material integrity changed")
    # Keep Job identity in the existing engine. Only an empty, uncommitted
    # directory may be removed; transaction debris needs state-engine recovery.
    job_id = state._job_id(inputs)
    job_dir = _local_path(workspace, f"edit/hd/jobs/{job_id}")
    context = {
        "schema_version": 1,
        **identity,
        "workspace": str(workspace),
        "job_dir": str(job_dir),
        "job_id": job_id,
        "video": str(paths["video"]),
        "script": str(paths["script"]),
        "material_index": str(index_path),
        "workflow": str(job_dir / "workflow.json"),
    }
    if context_path.exists() and _read_record(context_path) != context:
        raise InitializeJobError("existing context differs; refusing to overwrite identity")
    if record["phase"] == "ready" and not context_path.exists():
        raise InitializeJobError("completed context missing; do not recreate approved identity")
    if context_path.exists() and not (job_dir / "workflow.json").is_file():
        raise InitializeJobError("committed workflow missing; state-engine recovery required")
    if job_dir.exists() and not (job_dir / "workflow.json").exists():
        if record["phase"] != "imported" or context_path.exists():
            raise InitializeJobError("committed workflow missing; state-engine recovery required")
        try:
            job_dir.rmdir()
        except OSError as exc:
            raise InitializeJobError("nonempty partial workflow retained; state-engine recovery required") from exc
    if record["phase"] == "ready":
        job = state.load_job(job_dir)
    else:
        job = state.create_job(workspace, paths["video"], paths["script"], profile="full-v2")
    if job.inputs != inputs or job.version != 2 or job.job_id != job_id or job.job_dir != job_dir:
        raise InitializeJobError("workflow inputs/profile/identity differ; context not published")
    for relative in JOB_DIRS:
        _local_path(workspace, f"edit/hd/jobs/{job_id}/{relative}").mkdir(parents=True, exist_ok=True)
    if not context_path.exists():
        _write_json_atomic(context_path, context)
    if record["phase"] != "ready":
        _write_json_atomic(workspace / "initialization.json", {**record, "phase": "ready"})
    return job, context


def resume_video_job(workspace: str | Path, *, project_root: str | Path | None = None):
    """Resume one imported workspace without copying inputs or resetting state."""
    workspace = Path(workspace).expanduser().absolute()
    if workspace.resolve() != workspace or not workspace.is_dir():
        raise InitializeJobError("resume workspace must be an existing canonical directory")
    try:
        with _initialization_lock(workspace):
            record = _read_record(_local_path(workspace, "initialization.json"))
            state, identity = _current_runtime(project_root or record.get("project_root"))
            return _finish_initialization(workspace, record, state, identity)
    except Exception as exc:
        # Boundary error: preserve the original cause (including engine-specific
        # WorkflowError) and always expose the retained workspace for recovery.
        raise InitializeJobError(
            f"initialize/resume stopped: {exc}; retained workspace: {workspace}; "
            f"retry with --resume-workspace '{workspace}' after resolving the cause"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--jobs-root", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--video", type=Path)
    scripts = parser.add_mutually_exclusive_group()
    scripts.add_argument("--script", type=Path)
    scripts.add_argument("--script-text")
    scripts.add_argument("--script-stdin", action="store_true")
    parser.add_argument("--resume-workspace", type=Path)
    parser.add_argument("--user-file", action="append", default=[], type=Path)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.resume_workspace:
        if any(value is not None for value in (args.jobs_root, args.title, args.video, args.script, args.script_text)) or args.script_stdin or args.user_file:
            parser.error("resume accepts only --resume-workspace and optional --project-root")
        _job, context = resume_video_job(args.resume_workspace, project_root=args.project_root)
    else:
        if args.jobs_root is None or args.title is None or args.video is None:
            parser.error("new Job requires --jobs-root, --title and --video")
        text = sys.stdin.buffer.read().decode("utf-8") if args.script_stdin else args.script_text
        _job, context = initialize_video_job(
            args.jobs_root, args.title, args.video, args.script, args.user_file,
            project_root=args.project_root, script_text=text,
        )
    print(json.dumps(context, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

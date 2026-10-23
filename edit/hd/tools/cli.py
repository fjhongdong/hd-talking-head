"""Command-line interface for the HD talking-head workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .edit_timeline import EditTimelineError, generate_corrected_cleanup_proposal
from .state import (
    WorkflowError,
    approve,
    block,
    create_job,
    current_stage,
    load_job,
    mark_ready,
    revise,
)


class _ArgumentParseError(Exception):
    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentParseError()


def _non_negative_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def _repository_root() -> Path:
    current = Path.cwd()
    for candidate in (current, *current.parents):
        marker = candidate / ".git"
        if marker.is_dir() or marker.is_file():
            return candidate
    raise WorkflowError("repository root is unavailable")


def _absolute_input(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise WorkflowError("workflow input must be absolute")
    return path


def _current_stage(job: Any) -> str | None:
    return current_stage(job)


def _summary(job: Any) -> dict[str, Any]:
    return {
        "version": job.version,
        "job_id": job.job_id,
        "revision": job.revision,
        "current_stage": _current_stage(job),
        "stages": {
            stage_id: {
                "status": stage["status"],
                "ai_attempts": stage["ai_attempts"],
                "artifact_count": len(stage["artifacts"]),
            }
            for stage_id, stage in job.stages.items()
        },
    }


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _init(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root) if args.root else _repository_root()
    job = create_job(
        root,
        _absolute_input(args.video),
        _absolute_input(args.script),
        profile=args.profile,
    )
    return {"job_id": job.job_id, "job": job.job_dir.relative_to(job.root).as_posix(),
            "status": "created"}


def _status(args: argparse.Namespace) -> dict[str, Any]:
    return _summary(load_job(Path(args.job)))


def _review_cover(args: argparse.Namespace) -> dict[str, Any]:
    from .cover import CoverError, review_cover
    try:
        return review_cover(load_job(Path(args.job)))
    except CoverError as exc:
        raise WorkflowError("cover review is unavailable") from exc


def _review_subtitles(args: argparse.Namespace) -> dict[str, Any]:
    from .subtitles_v2 import SubtitlesV2Error, review_subtitles
    try:
        return review_subtitles(load_job(Path(args.job)))
    except SubtitlesV2Error as exc:
        raise WorkflowError("subtitle review is unavailable") from exc


def _search_reference(args: argparse.Namespace) -> dict[str, Any]:
    from . import reference_transcripts

    try:
        tracks = reference_transcripts.read_track_selection(Path(args.tracks))
        if getattr(args, "job", None):
            report = reference_transcripts.read_reference_transcript(
                Path(args.job), args.material_id, tracks=tracks, language=args.language)
        else:
            report = reference_transcripts.read_material_captions(
                Path(args.workspace), args.material_id, tracks=tracks, language=args.language)
        return {**report, "matches": reference_transcripts.search_cues(
            report["cues"], args.query, precision=report["precision"])}
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkflowError("reference transcript lookup is unavailable") from exc


def _cache_reference(args: argparse.Namespace) -> dict[str, Any]:
    from . import reference_transcripts

    try:
        tracks = reference_transcripts.read_track_selection(Path(args.tracks))
        return reference_transcripts.cache_reference_transcript(
            Path(args.job), args.material_id, tracks=tracks, language=args.language)
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkflowError("reference transcript cache is unavailable") from exc


def _approve(args: argparse.Namespace) -> dict[str, Any]:
    job = load_job(Path(args.job))
    if job.version == 2 and args.stage == "delivery":
        from .delivery_approval import approve_delivery
        approve_delivery(
            job, expected_revision=args.expected_revision,
            delivery_sha256=args.delivery_sha256, user_confirmation=args.user_confirmation,
        )
    else:
        if any(value is not None for value in (
            args.expected_revision, args.delivery_sha256, args.user_confirmation,
        )):
            raise WorkflowError("final confirmation parameters apply only to full-v2 delivery")
        approve(job, args.stage)
    return _summary(job)


def _revise(args: argparse.Namespace) -> dict[str, Any]:
    job = load_job(Path(args.job))
    revise(job, args.stage, args.reason)
    return _summary(job)


def _block(args: argparse.Namespace) -> dict[str, Any]:
    job = load_job(Path(args.job))
    block(job, args.stage, args.reason, args.ai_attempts)
    return _summary(job)


def _ready(args: argparse.Namespace) -> dict[str, Any]:
    job = load_job(Path(args.job))
    mark_ready(job, args.stage, [Path(artifact) for artifact in args.artifact])
    return _summary(job)


def _apply_cleanup_corrections(args: argparse.Namespace) -> dict[str, Any]:
    job = load_job(Path(args.job))
    generate_corrected_cleanup_proposal(job, Path(args.corrections))
    return _summary(job)


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="python3 -m edit.hd.tools.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    reference = commands.add_parser("search-reference")
    reference_scope = reference.add_mutually_exclusive_group(required=True)
    reference_scope.add_argument("--workspace")
    reference_scope.add_argument("--job")
    reference.add_argument("--material-id", required=True)
    reference.add_argument("--tracks", required=True)
    reference.add_argument("--language", required=True)
    reference.add_argument("--query", required=True)
    reference.set_defaults(handler=_search_reference)

    cache_reference = commands.add_parser("cache-reference")
    cache_reference.add_argument("--job", required=True)
    cache_reference.add_argument("--material-id", required=True)
    cache_reference.add_argument("--tracks", required=True)
    cache_reference.add_argument("--language", required=True)
    cache_reference.set_defaults(handler=_cache_reference)

    init = commands.add_parser("init")
    init.add_argument("--video", required=True)
    init.add_argument("--script", required=True)
    init.add_argument("--root")
    init.add_argument(
        "--profile", choices=("full-v2",), default="full-v2"
    )
    init.set_defaults(handler=_init)

    corrections = commands.add_parser("apply-cleanup-corrections")
    corrections.add_argument("--job", required=True)
    corrections.add_argument("--corrections", required=True)
    corrections.set_defaults(handler=_apply_cleanup_corrections)

    review = commands.add_parser("review-subtitles")
    review.add_argument("--job", required=True)
    review.set_defaults(handler=_review_subtitles)

    cover_review = commands.add_parser("review-cover")
    cover_review.add_argument("--job", required=True)
    cover_review.set_defaults(handler=_review_cover)

    for name, handler in (("status", _status), ("approve", _approve),
                          ("revise", _revise), ("block", _block), ("ready", _ready)):
        command = commands.add_parser(name)
        command.add_argument("--job", required=True)
        if name != "status":
            command.add_argument("--stage", required=True)
        if name in {"revise", "block"}:
            command.add_argument("--reason", required=True)
        if name == "block":
            command.add_argument("--ai-attempts", required=True, type=_non_negative_int)
        if name == "ready":
            command.add_argument("--artifact", action="append", required=True)
        if name == "approve":
            command.add_argument("--expected-revision", type=_non_negative_int)
            command.add_argument("--delivery-sha256")
            command.add_argument("--user-confirmation")
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _ArgumentParseError:
        print("错误: 无效的工作流请求", file=sys.stderr)
        return 2
    try:
        _emit(args.handler(args))
    except (WorkflowError, EditTimelineError, OSError, ValueError, TypeError):
        print("错误: 无效的工作流请求", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

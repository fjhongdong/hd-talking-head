"""Frame-based cover opening metadata; the existing preview runner owns publication."""

from pathlib import Path
import subprocess
from typing import Any, Mapping

from PIL import Image

from . import contract_artifacts, subtitles


class OpeningError(RuntimeError):
    """The cover opening cannot be traced to current approved inputs."""


MANIFEST = "opening-manifest.json"
OUTPUT_SRT = "subtitles.srt"


def _approved_record(job: Any, stage_id: str, relative: str) -> dict[str, Any]:
    stage = job.stages[stage_id]
    path = Path(job.job_dir) / relative
    records = [item for item in stage["artifacts"] if item.get("path") == relative]
    if (stage["status"] != "approved" or len(records) != 1 or path.is_symlink()
            or path.resolve() != path.absolute() or not path.is_file()):
        raise OpeningError(f"opening requires approved {relative}")
    record = {"path": relative, "sha256": contract_artifacts.sha256_file(path),
              "bytes": path.stat().st_size}
    if records[0] != record:
        raise OpeningError(f"opening source changed: {relative}")
    return record


def plan_opening(job: Any, options: object, *, body_frames: int) -> dict[str, Any]:
    if (type(options) is not dict
            or set(options) != {"hold_frames", "transition_frames", "user_confirmation"}
            or type(body_frames) is not int or body_frames <= 0):
        raise OpeningError("opening options or body clock are invalid")
    hold, transition = options["hold_frames"], options["transition_frames"]
    if (type(hold) is not int or hold <= 0 or type(transition) is not int
            or not 0 <= transition < body_frames
            or type(options["user_confirmation"]) is not str
            or not options["user_confirmation"].strip()):
        raise OpeningError("opening requires confirmed integer frame durations")
    cover = _approved_record(job, "cover", "04-cover/cover-delivery-raster.png")
    report = _approved_record(job, "cover", "04-cover/cover-report.json")
    source_srt = _approved_record(job, "subtitles", "10-subtitles/subtitles.srt")
    try:
        cover_report = contract_artifacts.read_json_artifact(job.job_dir / report["path"])
        outputs = cover_report.get("output_sha256")
        if not isinstance(outputs, dict) or outputs.get("cover-delivery-raster.png") != cover["sha256"]:
            raise OpeningError("opening cover does not match its approved report")
        with Image.open(job.job_dir / cover["path"]) as image:
            image.load()
            if image.size != (1080, 1920):
                raise OpeningError("opening requires the approved 1080x1920 delivery raster")
    except (OSError, ValueError, contract_artifacts.ContractArtifactError) as exc:
        raise OpeningError("opening cover is invalid") from exc
    return {
        "schema_version": 1, "job_id": job.job_id, "options": dict(options),
        "fps": 24, "body_frames": body_frames, "body_offset_frames": hold,
        "total_frames": body_frames + hold, "cover": cover, "cover_report": report,
        "source_srt": source_srt,
        "artifact_clocks": {
            "final.mp4": "final", "subtitles/subtitles.srt": "final",
            "plans/body-subtitles.webm": "body", "plans/subtitle-plan.json": "body",
            "plans/visual-plan.json": "body", "plans/asset-manifest.json": "body",
        },
    }


def shift_srt(source: str, offset_frames: int) -> bytes:
    if type(offset_frames) is not int or offset_frames < 0:
        raise OpeningError("subtitle offset must be non-negative integer frames")
    try:
        cues = subtitles.parse_srt(source)
        return subtitles._srt_bytes([
            {"start": start + offset_frames / 24, "end": end + offset_frames / 24, "text": text}
            for start, end, text in cues
        ])
    except (ValueError, subtitles.SubtitleError) as exc:
        raise OpeningError("approved body SRT is invalid") from exc


def publish_metadata(job: Any, directory: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Write only into the preview runner's unpublished staging directory."""
    source = (job.job_dir / plan["source_srt"]["path"]).read_text(encoding="utf-8")
    shifted = directory / OUTPUT_SRT
    shifted.write_bytes(shift_srt(source, plan["body_offset_frames"]))
    base = {
        **plan, "preview_sha256": contract_artifacts.sha256_file(directory / "review.mp4"),
        "output_srt": {"path": OUTPUT_SRT, "sha256": contract_artifacts.sha256_file(shifted),
                       "bytes": shifted.stat().st_size},
    }
    manifest = {**base, "opening_manifest_sha256": contract_artifacts.sha256_json(base)}
    contract_artifacts.write_json_artifact(directory / MANIFEST, manifest)
    return manifest


def validate_metadata(job: Any, directory: Path, manifest: object, *, body_frames: int) -> dict[str, Any]:
    if type(manifest) is not dict:
        raise OpeningError("opening manifest is invalid")
    plan = plan_opening(job, manifest.get("options"), body_frames=body_frames)
    source = (job.job_dir / plan["source_srt"]["path"]).read_text(encoding="utf-8")
    shifted = directory / OUTPUT_SRT
    if shifted.is_symlink() or not shifted.is_file() or shifted.read_bytes() != shift_srt(source, plan["body_offset_frames"]):
        raise OpeningError("opening SRT is not an exact time-shift of approved subtitles")
    base = {
        **plan, "preview_sha256": contract_artifacts.sha256_file(directory / "review.mp4"),
        "output_srt": {"path": OUTPUT_SRT, "sha256": contract_artifacts.sha256_file(shifted),
                       "bytes": shifted.stat().st_size},
    }
    if manifest != {**base, "opening_manifest_sha256": contract_artifacts.sha256_json(base)}:
        raise OpeningError("opening identity or timeline changed")
    return manifest


def extract_evidence(video: Path, directory: Path, plan: Mapping[str, Any]) -> list[Path]:
    hold = plan["body_offset_frames"]
    transition = plan["options"]["transition_frames"]
    boundaries = {"opening-first": 0, "opening-hold-end": hold - 1,
                  "opening-body-start": hold, "opening-transition-end": hold + transition}
    paths = []
    for name, frame in boundaries.items():
        path = directory / f"{name}.png"
        try:
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-threads", "1", "-reinit_filter", "0", "-i", str(video), "-vf",
                f"select=eq(n\\,{frame})",
                "-frames:v", "1", "-threads", "1", "-y", str(path),
            ], check=True, capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            raise OpeningError("opening boundary frame extraction failed") from exc
        paths.append(path)
    return paths

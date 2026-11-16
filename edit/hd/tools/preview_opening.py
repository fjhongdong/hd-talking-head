"""Frame-based cover opening metadata; the existing preview runner owns publication."""

from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from PIL import Image

from . import contract_artifacts, speech_edit_v2, subtitles, talkcraft_subtitles


class OpeningError(RuntimeError):
    """The cover opening cannot be traced to current approved inputs."""


MANIFEST = "opening-manifest.json"
OUTPUT_SRT = "subtitles.srt"


def _approved_record(job: Any, stage_id: str, relative: str) -> dict[str, Any]:
    stage = job.stages[stage_id]
    path = Path(job.job_dir) / relative
    records = [item for item in stage["artifacts"] if item.get("path") == relative]
    if (stage["status"] != "completed" or len(records) != 1 or path.is_symlink()
            or path.resolve() != path.absolute() or not path.is_file()):
        raise OpeningError(f"opening requires approved {relative}")
    record = {"path": relative, "sha256": contract_artifacts.sha256_file(path),
              "bytes": path.stat().st_size}
    if records[0] != record:
        raise OpeningError(f"opening source changed: {relative}")
    return record


def plan_opening(job: Any, options: object, *, body_frames: int) -> dict[str, Any]:
    fields = {"hold_frames", "transition_frames", "user_confirmation"}
    if (type(options) is not dict
            or not fields <= options.keys()
            or set(options) - (fields | {"video", "spoken_intro"})
            or type(body_frames) is not int or body_frames <= 0):
        raise OpeningError("opening options or body clock are invalid")
    hold, transition = options["hold_frames"], options["transition_frames"]
    if (type(hold) is not int or hold <= 0 or type(transition) is not int
            or not 0 <= transition < body_frames
            or type(options["user_confirmation"]) is not str
            or not options["user_confirmation"].strip()):
        raise OpeningError("opening requires confirmed integer frame durations")
    if "video" in options:
        if hold != 24 or transition != 0:
            raise OpeningError("dynamic opening must be a one-second prefix with no overlap")
        _check_opening_video(job, options["video"])
    spoken_intro = None
    if "spoken_intro" in options:
        if "video" not in options:
            raise OpeningError("restoring a spoken intro requires a separate dynamic cover")
        spoken_intro = _plan_spoken_intro(job, options["spoken_intro"])
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
    offset = hold + (0 if spoken_intro is None else spoken_intro["frames"])
    return {
        "schema_version": 1, "job_id": job.job_id, "options": dict(options),
        "fps": 24, "body_frames": body_frames, "body_offset_frames": offset,
        "total_frames": body_frames + offset, "cover": cover, "cover_report": report,
        "source_srt": source_srt,
        **({"spoken_intro": spoken_intro} if spoken_intro is not None else {}),
        "artifact_clocks": {
            "final.mp4": "final", "subtitles/subtitles.srt": "final",
            "plans/body-subtitles.webm": "body", "plans/subtitle-plan.json": "body",
            "plans/visual-plan.json": "body", "plans/asset-manifest.json": "body",
        },
    }


def _plan_spoken_intro(job, options):
    if (type(options) is not dict or set(options) != {"start_frame", "end_frame"}
            or any(type(value) is not int for value in options.values())):
        raise OpeningError("spoken intro needs original source frame bounds")
    start_frame, end_frame = options["start_frame"], options["end_frame"]
    start, end = start_frame / 24, end_frame / 24
    cleanup = _approved_record(job, "speech_cleanup", "05-speech-cleanup/cleanup-proposal.json")
    transcript = _approved_record(job, "speech_cleanup", "05-speech-cleanup/word-transcript.json")
    timeline = _approved_record(job, "edit_structure", "06-edit-structure/timeline-map.json")
    first = contract_artifacts.read_json_artifact(job.job_dir / cleanup["path"])["segments"][0]
    body = contract_artifacts.read_json_artifact(job.job_dir / timeline["path"])["segments"][0]
    words = subtitles._validate_words(contract_artifacts.read_json_artifact(job.job_dir / transcript["path"]))
    if (first["action"] != "delete" or first["word_start"] != 0
            or not 0 <= start < first["source_start"] <= first["source_end"] < end <= body["source_start"]):
        raise OpeningError("spoken intro must cover the removed opening and end before the existing cut")
    selected = words[:first["word_end"]]
    if any(word["start"] < end for word in words[first["word_end"]:]):
        raise OpeningError("spoken intro window would duplicate another word")
    cue = {"id": "opening-speech", "text": "".join(word["text"] for word in selected),
           "start": round(selected[0]["start"] - start, 3),
           "end": round(selected[-1]["end"] - start, 3), "emphasis_words": []}
    speech_edit_v2._input(job, "video")
    return {"source": job.inputs["video"], "source_start_frame": start_frame,
            "frames": end_frame - start_frame, "transcript": transcript, "cleanup": cleanup,
            "timeline": timeline, "cue": cue,
            "renderer_cue": talkcraft_subtitles.cue_input(cue, [
                {**word, "start": word["start"] - start, "end": word["end"] - start}
                for word in selected
            ])}


def render_spoken_subtitle(intro, output):
    canvas = {"width": 1080, "height": 1920, "fps": 24, "frames": intro["frames"]}
    data = talkcraft_subtitles.renderer_input({"canvas": canvas}, [intro["renderer_cue"]])
    with output.open("w+b") as descriptor:
        talkcraft_subtitles.render(data, descriptor.fileno())


def _check_opening_video(job, record):
    from .material_adapter import create_artifact_probe

    if type(record) is not dict or set(record) != {"path", "sha256", "bytes"} or not isinstance(record["path"], str):
        raise OpeningError("dynamic opening requires a bound Job video")
    relative = Path(record["path"])
    target = Path(job.job_dir) / relative
    if (relative.is_absolute() or ".." in relative.parts or target.resolve() != target.absolute()
            or not target.is_file() or target.stat().st_size != record["bytes"]
            or contract_artifacts.sha256_file(target) != record["sha256"]):
        raise OpeningError("dynamic opening video is missing or changed")
    try:
        probe = create_artifact_probe(ffprobe_executable=shutil.which("ffprobe") or "ffprobe")
        media = probe.probe(target, "video", {"alpha": False})
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise OpeningError("dynamic opening video must be a readable silent portrait clip") from exc
    if (media["width"], media["height"], media["fps"], media["frame_count"], media["alpha"]) != (1080, 1920, 24, 24, False):
        raise OpeningError("dynamic opening must contain exactly 24 silent 1080x1920 frames at 24 fps")


def shift_srt(source: str, offset_frames: int, *, spoken_intro=None, cover_frames=0) -> bytes:
    if type(offset_frames) is not int or offset_frames < 0:
        raise OpeningError("subtitle offset must be non-negative integer frames")
    try:
        cues = subtitles.parse_srt(source)
        shifted = [
            {"start": start + offset_frames / 24, "end": end + offset_frames / 24, "text": text}
            for start, end, text in cues
        ]
        if spoken_intro is not None:
            cue = spoken_intro["cue"]
            shifted.insert(0, {"start": cue["start"] + cover_frames / 24,
                               "end": cue["end"] + cover_frames / 24, "text": cue["text"]})
        return subtitles._srt_bytes(shifted)
    except (ValueError, subtitles.SubtitleError) as exc:
        raise OpeningError("approved body SRT is invalid") from exc


def publish_metadata(job: Any, directory: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Write only into the preview runner's unpublished staging directory."""
    source = (job.job_dir / plan["source_srt"]["path"]).read_text(encoding="utf-8")
    shifted = directory / OUTPUT_SRT
    shifted.write_bytes(shift_srt(source, plan["body_offset_frames"],
                                  spoken_intro=plan.get("spoken_intro"),
                                  cover_frames=plan["options"]["hold_frames"]))
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
    if shifted.is_symlink() or not shifted.is_file() or shifted.read_bytes() != shift_srt(
            source, plan["body_offset_frames"], spoken_intro=plan.get("spoken_intro"),
            cover_frames=plan["options"]["hold_frames"]):
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
    hold = plan["options"]["hold_frames"]
    body = plan["body_offset_frames"]
    transition = plan["options"]["transition_frames"]
    boundaries = {"opening-first": 0, "opening-hold-end": hold - 1,
                  "opening-body-start": body, "opening-transition-end": hold + transition}
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

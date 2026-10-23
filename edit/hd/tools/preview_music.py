"""Explicit, source-bound music preparation for the formal preview transaction.

The caller owns approval, source identity, continuous music preparation and staging.
No Job is mutated here. PCM outputs must pass final encoded-media QA before delivery.
Sidechain routing follows the local video-autopilot-kit audio_chain reference:
music is the compressed input, original speech is only its control signal.
"""

import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from . import contract_artifacts, user_materials

MANIFEST = "music-manifest.json"
ATTACHMENTS = (MANIFEST, "music-audit.m4a", "music-license-source", "music-credits.txt")


def prepare_stage_audio(job, directory, plan, voice):
    """Private intermediates remain caller-owned until the preview is encoded."""
    validate_music_plan(job, plan)
    work = directory / ".music-work"
    work.mkdir()
    continuous, mix, audit = (work / name for name in ("continuous.wav", "mix.wav", "audit.wav"))
    prepare_continuous_music(job.root / plan["music"]["path"], continuous,
        frames=plan["total_frames"], **plan["options"]["selection"])
    _run(build_mix_command(voice, continuous, mix, audit, frames=plan["total_frames"],
        voice_offset_frames=plan["body_offset_frames"], options=plan["options"]["mix"]))
    for path in (mix, audit):
        if _decoded_samples(path) != plan["total_frames"] * 2000:
            raise MusicError("mixed audio clock is incomplete")
    _run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(audit), "-map", "0:a:0",
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
          str(directory / "music-audit.m4a")])
    return mix


def publish_metadata(job, directory, plan, voice):
    validate_music_plan(job, plan)
    metrics = {"final": measure_audio(directory / "review.mp4"),
               "music": measure_audio(directory / "music-audit.m4a")}
    if metrics["final"]["true_peak_dbtp"] > 0 or metrics["music"]["integrated_lufs"] < -60:
        raise MusicError("music is effectively silent or final audio clips; revise explicit gains")
    shutil.copyfile(job.root / plan["license"]["path"], directory / "music-license-source")
    options = plan["options"]
    credits = "\n".join(f"{key}: {options[key]}" for key in
                        ("title", "author", "source", "license_material_id", "license_sha256")) + "\n"
    (directory / "music-credits.txt").write_text(credits, encoding="utf-8")
    base = {"schema_version": 1, "plan": plan,
            "voice_sha256": contract_artifacts.sha256_file(voice),
            "preview_sha256": contract_artifacts.sha256_file(directory / "review.mp4"),
            "metrics": metrics, "listening_approval": "required_at_preview",
            "attachments": {name: contract_artifacts.sha256_file(directory / name)
                            for name in ATTACHMENTS[1:]}}
    manifest = {**base, "music_manifest_sha256": contract_artifacts.sha256_json(base)}
    contract_artifacts.write_json_artifact(directory / MANIFEST, manifest)
    validate_metadata(job, directory, manifest, voice)
    shutil.rmtree(directory / ".music-work")
    return manifest


def validate_metadata(job, directory, manifest, voice):
    try:
        if set(manifest) != {"schema_version", "plan", "voice_sha256", "preview_sha256",
                             "metrics", "listening_approval", "attachments", "music_manifest_sha256"}:
            raise MusicError("incomplete music manifest")
        base = {k: v for k, v in manifest.items() if k != "music_manifest_sha256"}
        validate_music_plan(job, manifest["plan"])
        if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
                or manifest["music_manifest_sha256"] != contract_artifacts.sha256_json(base)
                or manifest["preview_sha256"] != contract_artifacts.sha256_file(directory / "review.mp4")
                or manifest["voice_sha256"] != contract_artifacts.sha256_file(voice)
                or manifest["listening_approval"] != "required_at_preview"
                or set(manifest["attachments"]) != set(ATTACHMENTS[1:])):
            raise MusicError("music evidence changed")
        for name, digest in manifest["attachments"].items():
            if contract_artifacts.sha256_file(_source(directory / name)) != digest:
                raise MusicError("music attachment changed")
        if manifest["attachments"]["music-license-source"] != manifest["plan"]["license"]["sha256"]:
            raise MusicError("music license copy changed")
        metrics = manifest["metrics"]
        if set(metrics) != {"final", "music"}:
            raise MusicError("music measurement missing")
        for item in metrics.values():
            if set(item) != {"integrated_lufs", "true_peak_dbtp"} or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in item.values()):
                raise MusicError("music measurement invalid")
        if metrics["final"]["true_peak_dbtp"] > 0 or metrics["music"]["integrated_lufs"] < -60:
            raise MusicError("music measurement failed")
        return manifest
    except (KeyError, TypeError, OSError, ValueError, AttributeError, OverflowError) as exc:
        raise MusicError("music evidence is incomplete") from exc


def material_references(plan, stage, artifact_paths):
    return [{"material_id": plan[name]["material_id"], "material_sha256": plan[name]["sha256"],
             "consumer_kind": "background_music", "consumer_id": name,
             "binding_path": f"/plan/{name}",
             "artifact_paths": [f"{stage}/{path}" for path in artifact_paths]}
            for name in ("music", "license")]


class MusicError(RuntimeError):
    """Music cannot be mixed or measured without silently losing audio."""


_RANGES = {
    "voice_gain_db": (-30, 12), "music_gain_db": (-60, 0),
    "duck_threshold": (0.00097563, 1), "duck_ratio": (1, 20),
    "duck_attack_ms": (0.01, 2000), "duck_release_ms": (0.01, 9000),
}


def validate_mix_options(options: object, *, frames: int) -> dict:
    if (type(frames) is not int or frames <= 0 or type(options) is not dict
            or set(options) != set(_RANGES) | {"fade_in_frames", "fade_out_frames"}):
        raise MusicError("mix requires explicit options and positive integer frames")
    for key, (low, high) in _RANGES.items():
        value = options[key]
        if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
            raise MusicError(f"invalid mix parameter: {key}")
    for key in ("fade_in_frames", "fade_out_frames"):
        if type(options[key]) is not int or not 0 < options[key] <= frames:
            raise MusicError(f"invalid fade duration: {key}")
    if options["fade_in_frames"] + options["fade_out_frames"] > frames:
        raise MusicError("music fades must not overlap")
    return dict(options)


def plan_music(job, options: object, *, frames: int, voice_offset_frames: int) -> dict:
    """Bind explicit selection to active indexed music and license document.

    Records the supplied current confirmation, not proof of legal permission or
    final listening approval. The formal runner must revalidate before publishing.
    No workflow or material index is changed here.
    """
    fields = {"material_id", "material_sha256", "license_material_id", "license_sha256",
              "title", "author", "source", "user_confirmation", "selection", "mix"}
    if type(options) is not dict or set(options) != fields:
        raise MusicError("music selection requires explicit provenance, license and confirmation")
    for key in fields - {"selection", "mix"}:
        if type(options[key]) is not str or not options[key].strip():
            raise MusicError(f"missing music selection field: {key}")
    for key in ("material_sha256", "license_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", options[key]) is None:
            raise MusicError(f"invalid music identity: {key}")
    validate_mix_options(options["mix"], frames=frames)
    if type(voice_offset_frames) is not int or not 0 <= voice_offset_frames < frames:
        raise MusicError("invalid music body offset")
    selection = options["selection"]
    if (type(selection) is not dict
            or set(selection) != {"start_frame", "end_frame", "crossfade_frames"}
            or any(type(value) is not int for value in selection.values())):
        raise MusicError("invalid music selection clock")
    start, end, overlap = (selection[k] for k in ("start_frame", "end_frame", "crossfade_frames"))
    if start < 0 or not 0 < 2 * overlap < end - start:
        raise MusicError("invalid music selection range")
    records = {}
    for name, id_key, hash_key, kind in (
        ("music", "material_id", "material_sha256", "audio"),
        ("license", "license_material_id", "license_sha256", "documents"),
    ):
        try:
            item = user_materials.require_active_material(job, options[id_key], options[hash_key])
        except (RuntimeError, OSError, ValueError, ImportError) as exc:
            raise MusicError(f"{name} material is missing, retired or changed") from exc
        if item["media_type"] != kind:
            raise MusicError(f"{name} material requires {kind}")
        records[name] = {"material_id": item["material_id"], "path": item["imported_path"],
                         "sha256": item["sha256"], "bytes": item["size_bytes"]}
    base = {"schema_version": 1, "job_id": job.job_id, "fps": 24,
            "total_frames": frames, "body_offset_frames": voice_offset_frames,
            "options": copy.deepcopy(options), **records}
    return {**base, "music_plan_sha256": contract_artifacts.sha256_json(base)}


def validate_music_plan(job, plan: object) -> dict:
    """Recheck active input bytes and every frozen field before downstream use."""
    if type(plan) is not dict:
        raise MusicError("invalid music plan")
    expected = plan_music(job, plan.get("options"), frames=plan.get("total_frames"),
                          voice_offset_frames=plan.get("body_offset_frames"))
    if plan != expected or contract_artifacts.sha256_json(plan) != contract_artifacts.sha256_json(expected):
        raise MusicError("music plan identity or clock changed")
    return expected


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MusicError("audio command failed; no verified mix is available") from exc


def _source(path: Path) -> Path:
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise MusicError("audio source must be a regular local file without symlink components")
    return path


def _duration(path: Path, *, require_stereo: bool = False) -> float:
    raw = _run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)])
    try:
        audio = [s for s in json.loads(raw.stdout)["streams"] if s.get("codec_type") == "audio"]
        if require_stereo and (len(audio) != 1 or audio[0].get("channels") != 2):
            raise MusicError("mix sources must already be stereo; no implicit channel gain changes")
        duration = float(audio[0]["duration"]) if len(audio) == 1 else float("nan")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid duration")
        return duration
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MusicError("source requires one audio stream with a known duration") from exc


def _decoded_samples(path: Path) -> int:
    """Stream decoded audio through a counter, without loading PCM into Python."""
    result = _run(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-xerror",
                   "-threads", "1", "-i", str(path), "-map", "0:a:0", "-vn", "-af",
                   "aresample=48000,astats=metadata=0:reset=0:measure_perchannel=none:"
                   "measure_overall=Number_of_samples", "-f", "null", "-"])
    counts = re.findall(rb"Number of samples: ([0-9]+)\s", result.stderr)
    if len(counts) != 1 or int(counts[0]) <= 0:
        raise MusicError("cannot verify decoded audio sample count")
    return int(counts[0])


def prepare_continuous_music(source: Path, output: Path, *, frames: int,
                             start_frame: int, end_frame: int, crossfade_frames: int) -> Path:
    """Crop a selected source interval and repeat it with linear overlap fades.

    Preserve the selected first sample. A small prefix followed by a reusable
    crossfaded cycle avoids one decoder/filter branch per repetition. The caller
    owns source approval and the private staging directory, not this primitive.
    """
    if (any(type(v) is not int for v in (frames, start_frame, end_frame, crossfade_frames))
            or frames <= 0 or start_frame < 0 or end_frame <= start_frame
            or not 0 < 2 * crossfade_frames < end_frame - start_frame):
        raise MusicError("invalid continuous music frame range or crossfade")
    source, output = _source(source), Path(output).absolute()
    if (output.exists() or output.is_symlink() or output.resolve() != output
            or not output.parent.is_dir()):
        raise MusicError("continuous music output must be a new local staging path")
    _duration(source, require_stereo=True)
    if _decoded_samples(source) < end_frame * 2000:
        raise MusicError("selected music interval exceeds decoded source")
    start, length = start_frame * 2000, (end_frame - start_frame) * 2000
    total, overlap = frames * 2000, crossfade_frames * 2000
    common = ["ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-n"]
    encoding = ["-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2", "-threads", "1", "-f", "wav"]
    with tempfile.TemporaryDirectory(prefix=".music-", dir=output.parent) as temp:
        directory = Path(temp)
        candidate = directory / "continuous.wav"
        if total <= length:
            _run(common + ["-threads", "1", "-i", str(source), "-map", "0:a:0", "-af",
                 f"aresample=48000,atrim=start_sample={start}:end_sample={start+total},"
                 "asetpts=PTS-STARTPTS"] + encoding + [str(candidate)])
        else:
            prefix, cycle = directory / "prefix.wav", directory / "cycle.wav"
            graph = (
                f"[0:a:0]aresample=48000,atrim=start_sample={start}:end_sample={start+length},"
                "asetpts=PTS-STARTPTS,asplit=3[p][body][head];"
                f"[p]atrim=end_sample={overlap}[prefix];"
                f"[body]atrim=start_sample={overlap},asetpts=PTS-STARTPTS[body1];"
                f"[head]atrim=end_sample={overlap}[head1];"
                f"[body1][head1]acrossfade=ns={overlap}:c1=tri:c2=tri[cycle]"
            )
            _run(common + ["-threads", "1", "-i", str(source), "-filter_complex_threads", "1",
                 "-filter_complex", graph, "-map", "[prefix]"] + encoding + [str(prefix),
                 "-map", "[cycle]"] + encoding + [str(cycle)])
            _run(common + ["-threads", "1", "-i", str(prefix), "-stream_loop", "-1",
                 "-threads", "1", "-i", str(cycle), "-filter_complex_threads", "1",
                 "-filter_complex", f"[0:a:0][1:a:0]concat=n=2:v=0:a=1,atrim=end_sample={total}[out]",
                 "-map", "[out]"] + encoding + [str(candidate)])
        if _decoded_samples(candidate) != total:
            raise MusicError("continuous music has an incorrect decoded sample count")
        # Exclusive link publishes only a completely encoded and validated file.
        try:
            os.link(candidate, output)
        except OSError as exc:
            raise MusicError("continuous music publication failed without overwriting output") from exc
    return output


def build_mix_command(voice: Path, continuous_music: Path, output: Path, audit: Path,
                      *, frames: int, voice_offset_frames: int, options: object) -> list[str]:
    """Mix preassembled music on the final clock; delay body speech exactly once.

    Both inputs must already be stereo. Short music is rejected, never implicitly
    looped or padded. Outputs are one
    stereo PCM mix and its ducked music stem, not two selectable delivery tracks.
    """
    opts = validate_mix_options(options, frames=frames)
    if type(voice_offset_frames) is not int or not 0 <= voice_offset_frames < frames:
        raise MusicError("voice offset must be integer frames within the final clock")
    voice, music = _source(voice), _source(continuous_music)
    output, audit = Path(output).absolute(), Path(audit).absolute()
    if output == audit or any(p.exists() or p.is_symlink() or p.resolve() != p
                              or not p.parent.is_dir() for p in (output, audit)):
        raise MusicError("mix outputs must be distinct, new local staging paths")
    _duration(voice, require_stereo=True)
    _duration(music, require_stereo=True)
    if (_decoded_samples(voice) < (frames - voice_offset_frames) * 2000
            or _decoded_samples(music) < frames * 2000):
        raise MusicError("audio does not cover the requested clock; prepare continuous music first")
    total, offset = frames * 2000, voice_offset_frames * 2000
    fade_in, fade_out = opts["fade_in_frames"] * 2000, opts["fade_out_frames"] * 2000
    # Equal-sized sidechain blocks prevent FFmpeg dropping the final partial block.
    # Only filter buffers are padded; trim them back to the exact final sample count.
    graph = (
        f"[0:a:0]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,"
        f"volume={opts['voice_gain_db']}dB,adelay={offset}S:all=1,atrim=end_sample={total},"
        "asplit=2[voice][controlraw];[controlraw]asetnsamples=n=1024:p=1[control];"
        f"[1:a:0]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,"
        f"atrim=end_sample={total},volume={opts['music_gain_db']}dB,"
        f"afade=t=in:ss=0:ns={fade_in},afade=t=out:ss={total-fade_out}:ns={fade_out},"
        "asetnsamples=n=1024:p=1[music];"
        f"[music][control]sidechaincompress=threshold={opts['duck_threshold']}:"
        f"ratio={opts['duck_ratio']}:attack={opts['duck_attack_ms']}:"
        f"release={opts['duck_release_ms']}:makeup=1,atrim=end_sample={total},"
        "asplit=2[ducked][audit];"
        "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
    )
    return ["ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error", "-n",
            "-threads", "1", "-i", str(voice), "-threads", "1", "-i", str(music),
            "-filter_complex_threads", "1", "-filter_complex", graph,
            "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2",
            "-threads", "1", "-f", "wav", str(output),
            "-map", "[audit]", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2",
            "-threads", "1", "-f", "wav", str(audit)]


def measure_audio(path: Path) -> dict[str, float]:
    """Measure decoded audio, including AAC when supplied; reject silence/NaN.

    This is measurement, not loudness normalization or human listening approval.
    """
    path = _source(path)
    _duration(path)
    result = _run(["ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-threads", "1",
                   "-i", str(path), "-map", "0:a:0", "-vn", "-af",
                   "loudnorm=I=-18:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    try:
        text = result.stderr.decode("utf-8")
        raw = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
        values = {"integrated_lufs": float(raw["input_i"]),
                  "true_peak_dbtp": float(raw["input_tp"])}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError("silent or invalid audio")
        return values
    except (UnicodeError, KeyError, TypeError, ValueError) as exc:
        raise MusicError("audio has no finite loudness and peak measurement") from exc

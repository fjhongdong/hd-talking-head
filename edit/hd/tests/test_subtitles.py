from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib
import math
import os
import json
import shutil
import subprocess
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFont


def _record(path: str, marker: str = "a") -> dict[str, object]:
    return {"path": path, "sha256": marker * 64, "bytes": 1}


def _zones() -> dict[str, object]:
    return {
        "face": {"x": 24, "y": 36, "width": 280, "height": 360},
        "subtitle": {"x": 120, "y": 1510, "width": 840, "height": 220},
        "source": {"x": 70, "y": 120, "width": 940, "height": 110},
        "chart": {"x": 80, "y": 300, "width": 920, "height": 1000},
    }


def _plan() -> dict[str, object]:
    types = ("emphasis", "statement", "source", "action")
    cues = []
    for index, cue_type in enumerate(types):
        start = 0.25 + index * 0.4
        cues.append(
            {
                "id": f"cue-{index + 1:03d}",
                "type": cue_type,
                "segment_id": f"seg-{index + 1:03d}",
                "start": start,
                "end": start + 0.3,
                "text": "严格字幕",
                "emphasis_words": ["字幕"],
                "safe_zones": _zones(),
                "box": {
                    "x": 120 + index * 10,
                    "y": 1510 + index * 10,
                    "width": 840 - index * 20,
                    "height": 180 - index * 10,
                },
            }
        )
    return {
        "version": 1,
        "canvas": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "frames": 48,
            "duration": 2.0,
        },
        "source_bindings": {
            "word_transcript": _record("02-speech-cleanup/word-transcript.json"),
            "timeline_map": _record("03-edit-structure/timeline-map.json"),
            "edited_aroll": _record("03-edit-structure/edited-aroll.mp4"),
            "visual_plan": _record("04-visual-direction/visual-plan.json"),
            "asset_manifest": _record("05-visual-assets/asset-manifest.json"),
            "visual_track": _record("05-visual-assets/visual-track.mp4"),
        },
        "layout_counts": {name: 1 for name in types},
        "cues": cues,
    }


def _dense_aroll_plan() -> tuple[str, dict[str, object]]:
    from edit.hd.tools import subtitles

    text = "掌握人工智能学习方法可以提升表达能力并且建立清晰内容结构让每次分享都更有价值"
    words = [
        {
            "text": character,
            "start": round(0.1 + index * 0.13, 3),
            "end": round(0.21 + index * 0.13, 3),
        }
        for index, character in enumerate(text)
    ]
    duration = 8.0
    return text, subtitles._build_plan(
        records=_plan()["source_bindings"],
        words=words,
        timeline={
            "version": 1,
            "source_duration": duration,
            "output_duration": duration,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "segments": [{
                "source_start": 0.0,
                "source_end": duration,
                "timeline_start": 0.0,
                "timeline_end": duration,
            }],
        },
        visual_plan={
            "duration": duration,
            "segments": [{
                "segment_id": "seg-001",
                "start": 0.0,
                "end": duration,
                "implementation": "arroll",
                "keywords": [
                    {"text": "人工智能"},
                    {"text": "表达能力"},
                    {"text": "内容结构"},
                ],
                "safe_zones": _zones(),
            }],
        },
    )


def _canonical(path: Path, payload: object) -> None:
    path.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _file_record(path: Path, base: Path) -> dict[str, object]:
    source = path.read_bytes()
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": hashlib.sha256(source).hexdigest(),
        "bytes": len(source),
    }


def _visual_flags(**changes: bool) -> dict[str, bool]:
    result = {
        "facts": False,
        "numbers": False,
        "steps": False,
        "text": False,
        "ui": False,
        "chart": False,
        "named_source": False,
        "teacher_expression": False,
        "atmosphere": False,
    }
    result.update(changes)
    return result


def _stage_plan(
    root: Path,
    job_dir: Path,
    script: Path,
    transcript: Path,
    edit_plan: Path,
    timeline: Path,
    edited: Path,
    brief: Path,
    preview: Path,
    routes: tuple[str, ...] = ("arroll", "official", "code", "ai"),
    duration: float = 2.0,
) -> dict[str, object]:
    zones = {
        "face": {"x": 24, "y": 36, "width": 280, "height": 360},
        "subtitle": {"x": 120, "y": 1600, "width": 840, "height": 180},
        "source": {"x": 70, "y": 120, "width": 940, "height": 110},
        "chart": {"x": 80, "y": 300, "width": 920, "height": 1000},
    }
    scores = {
        "teacher_expression": 70,
        "information_density": 70,
        "official_evidence": 70,
        "metaphor_value": 50,
        "continuity": 80,
        "safety": 100,
    }
    base = {
        "spoken_summary": "严格口播内容只用于时间线绑定",
        "keywords": [{"text": "核心", "role": "primary"}],
        "safe_zones": zones,
        "scores": scores,
        "reason": "根据内容动态选择实现路由",
        "confidence": "high",
        "official": None,
        "code": None,
        "ai": None,
    }
    segments = []
    segment_duration = duration / len(routes)
    for index, route in enumerate(routes):
        segment = {
            **base,
            "segment_id": f"seg-{index + 1:03d}",
            "start": index * segment_duration,
            "end": (index + 1) * segment_duration,
            "implementation": route,
            "visual_type": "keyword_depth" if route == "arroll" else route,
            "arroll_mode": "full" if route == "arroll" else "none",
            "avatar_position": "none" if route == "arroll" else "bottom_right",
            "content_flags": _visual_flags(
                teacher_expression=route == "arroll"
            ),
        }
        if route == "official":
            preview_record = _file_record(preview, preview.parent)
            segment.update(
                visual_type="image",
                content_flags=_visual_flags(facts=True, named_source=True),
                official={
                    "publisher": "Example Institute",
                    "title": "Bound Official Preview",
                    "published_at": "2026-08-01",
                    "url": "https://reports.example.org/annual",
                    "accessed_at": "2026-08-20T10:30:00+08:00",
                    "kind": "image",
                    "official_host": "reports.example.org",
                    "identity_evidence": "官网标识与发布机构一致",
                    "preview": preview_record,
                    "selection": {
                        "kind": "crop",
                        "x": 10,
                        "y": 10,
                        "width": 200,
                        "height": 100,
                        "start": None,
                        "end": None,
                    },
                    "attribution": "来源：Example Institute",
                    "usage_scope": "仅用于本口播证据卡",
                },
            )
        elif route == "code":
            segment.update(
                visual_type="metric",
                content_flags=_visual_flags(numbers=True, text=True, chart=True),
                code={
                    "type": "metric",
                    "exact_text": ["效率提升"],
                    "exact_numbers": ["42%"],
                    "source_refs": ["original_script"],
                    "template": {"accent": "yellow"},
                },
            )
        elif route == "ai":
            segment.update(
                visual_type="metaphor",
                content_flags=_visual_flags(atmosphere=True),
                ai={
                    "composition": "中心留白，四周柔和光束",
                    "subject_position": "center",
                    "camera_motion": "slow push in",
                    "palette": "deep blue and cyan",
                    "mood": "calm",
                    "prompt_summary": "抽象知识网络形成光点",
                    "negative_constraints": [
                        "no factual text",
                        "no logo",
                        "no ui",
                        "no watermark",
                        "no fabricated source",
                    ],
                },
            )
        segments.append(segment)
    return {
        "version": 1,
        "source_bindings": {
            "original_script": _file_record(script, root),
            "word_transcript": _file_record(transcript, job_dir),
            "edit_plan": _file_record(edit_plan, job_dir),
            "timeline_map": _file_record(timeline, job_dir),
            "edited_aroll": _file_record(edited, job_dir),
            "director_brief": _file_record(brief, root),
            "official_previews": (
                [_file_record(preview, preview.parent)]
                if "official" in routes
                else []
            ),
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24.0},
        "duration": duration,
        "segments": segments,
        "routing_summary": {
            route: {
                "seconds": routes.count(route) * segment_duration,
                "ratio": routes.count(route) / len(routes),
            }
            for route in ("arroll", "official", "code", "ai")
        },
    }


def _video(path: Path, *, audio: bool, duration: float = 2.0) -> None:
    command = [
        "ffmpeg", "-v", "error", "-xerror", "-y",
        "-f", "lavfi", "-i", f"color=c=0x203040:s=1080x1920:r=24:d={duration}",
    ]
    if audio:
        command += [
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=48000:d={duration}",
        ]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    else:
        command += ["-an"]
    command.append(str(path))
    subprocess.run(command, check=True)


def _ready_job(
    root: Path,
    *,
    approve_assets: bool = True,
    mismatch_manifest_inputs: bool = False,
    timeline_duration: float = 2.0,
    routes: tuple[str, ...] = ("arroll", "official", "code", "ai"),
    render_deletion: bool | None = None,
):
    from edit.hd.tools import edit_timeline, state

    video = root / "source.mp4"
    script = root / "script.txt"
    _video(video, audio=True)
    script.write_text("严格动态字幕覆盖完整整理内容", encoding="utf-8")
    job = state.create_job(root, video, script, profile="legacy-v1")

    inspect = job.job_dir / "01-inspect"
    inspect.mkdir()
    inspect_payload: dict[str, object] = {"version": 1}
    if render_deletion is not None:
        inspect_payload = {
            "version": 1,
            "streams": {"video": 1, "audio": 1},
            "video": {
                "codec": "h264", "width": 1080, "height": 1920,
                "sample_aspect_ratio": "1:1", "display_aspect_ratio": "9:16",
                "fps": 24.0, "duration": 2.0,
                "path": job.inputs["video"]["path"],
                "sha256": job.inputs["video"]["sha256"],
                "bytes": job.inputs["video"]["bytes"],
            },
            "audio": {
                "codec": "aac", "sample_rate": 48000,
                "channels": 1, "duration": 2.0,
            },
            "script": {
                "path": job.inputs["script"]["path"],
                "sha256": job.inputs["script"]["sha256"],
                "bytes": job.inputs["script"]["bytes"],
            },
        }
    _canonical(inspect / "report.json", inspect_payload)
    state.mark_ready(job, "inspect", [inspect / "report.json"])
    state.approve(job, "inspect")

    speech = job.job_dir / "02-speech-cleanup"
    speech.mkdir()
    words = [
        {"text": text, "start": index * 0.14 + 0.05, "end": index * 0.14 + 0.17}
        for index, text in enumerate("严格动态字幕覆盖完整整理")
    ]
    transcript = speech / "word-transcript.json"
    _canonical(transcript, {"version": 1, "words": words})
    if render_deletion is None:
        speech_artifacts = [transcript]
    else:
        split = 4
        segments = [
            {
                "action": "keep", "word_start": 0,
                "word_end": split if render_deletion else len(words),
                "source_start": words[0]["start"],
                "source_end": words[(split if render_deletion else len(words)) - 1]["end"],
                "original_sentence": "".join(
                    word["text"]
                    for word in words[: split if render_deletion else len(words)]
                ),
                "cleaned_sentence": "".join(
                    word["text"]
                    for word in words[: split if render_deletion else len(words)]
                ),
                "reason": "保留口播",
                "breathing_padding": {"before": 0.0, "after": 0.0},
            }
        ]
        if render_deletion:
            segments.extend(
                [
                    {
                        "action": "delete", "word_start": split,
                        "word_end": split + 1,
                        "source_start": words[split]["start"],
                        "source_end": words[split]["end"],
                        "original_sentence": words[split]["text"],
                        "cleaned_sentence": "", "reason": "删除测试词",
                        "breathing_padding": {"before": 0.0, "after": 0.0},
                    },
                    {
                        "action": "keep", "word_start": split + 1,
                        "word_end": len(words),
                        "source_start": words[split + 1]["start"],
                        "source_end": words[-1]["end"],
                        "original_sentence": "".join(
                            word["text"] for word in words[split + 1 :]
                        ),
                        "cleaned_sentence": "".join(
                            word["text"] for word in words[split + 1 :]
                        ),
                        "reason": "保留口播",
                        "breathing_padding": {"before": 0.0, "after": 0.0},
                    },
                ]
            )
        proposal = speech / "cleanup-proposal.json"
        _canonical(proposal, {"version": 1, "segments": segments})
        for name in (
            "speech-16k.wav", "whisper.json", "report.json",
            "diff-summary.json", "estimated-duration.json",
        ):
            (speech / name).write_bytes(b"fixture\n")
        speech_artifacts = sorted(speech.iterdir())
    state.mark_ready(job, "speech_cleanup", speech_artifacts)
    state.approve(job, "speech_cleanup")

    if render_deletion is None:
        edit = job.job_dir / "03-edit-structure"
        edit.mkdir()
        edited = edit / "edited-aroll.mp4"
        shutil.copyfile(video, edited)
        timeline = edit / "timeline-map.json"
        _canonical(
            timeline,
            {
                "version": 1, "source_duration": timeline_duration,
                "output_duration": timeline_duration,
                "has_deletion": False, "audio_policy": "copy-original-elementary",
                "render_adapter": "local-ffmpeg-no-cut",
                "segments": [
                    {
                        "source_start": 0.0, "source_end": timeline_duration,
                        "timeline_start": 0.0, "timeline_end": timeline_duration,
                    }
                ],
            },
        )
        edit_plan = edit / "edit-plan.json"
        _canonical(edit_plan, {"version": 1})
        state.mark_ready(job, "edit_structure", [edit_plan, edited, timeline])
    else:
        edited = edit_timeline.render_edit(job)
        edit = edited.parent
        edit_plan = edit / "edit-plan.json"
        timeline = edit / "timeline-map.json"
        timeline_duration = round(
            float(json.loads(timeline.read_text(encoding="utf-8"))["output_duration"])
            * 24
        ) / 24
    state.approve(job, "edit_structure")

    preview = root / "preview.png"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-xerror", "-y", "-f", "lavfi", "-i",
            "color=c=white:s=320x180", "-frames:v", "1", str(preview),
        ],
        check=True,
    )
    brief = root / "brief.json"
    _canonical(brief, {"version": 1})
    direction = job.job_dir / "04-visual-direction"
    direction.mkdir()
    visual_plan = direction / "visual-plan.json"
    payload = _stage_plan(
        root,
        job.job_dir,
        script,
        transcript,
        edit_plan,
        timeline,
        edited,
        brief,
        preview,
        routes=routes,
        duration=timeline_duration,
    )
    _canonical(visual_plan, payload)
    (direction / "storyboard.svg").write_text("<svg/>", encoding="utf-8")
    (direction / "visual-routing.md").write_text("routes\n", encoding="utf-8")
    state.mark_ready(job, "visual_direction", sorted(direction.iterdir()))
    state.approve(job, "visual_direction")

    assets = job.job_dir / "05-visual-assets"
    assets.mkdir()
    track = assets / "visual-track.mp4"
    _video(track, audio=False, duration=timeline_duration)
    track_record = _file_record(track, assets)
    asset_record = {
        **track_record,
        "type": "visual-track", "segment_id": None, "generation_id": None,
        "requested_duration": None, "used_duration": None,
        "frames": round(timeline_duration * 24),
        "source_label": None, "source_preview": None, "selection": None,
    }
    manifest = assets / "asset-manifest.json"
    manifest_inputs = copy.deepcopy(payload["source_bindings"])
    if mismatch_manifest_inputs:
        manifest_inputs["timeline_map"]["sha256"] = "c" * 64
    _canonical(
        manifest,
        {
            "version": 1, "generation_id": "b" * 64,
            "visual_plan": _file_record(visual_plan, job.job_dir),
            "inputs": manifest_inputs,
            "canvas": {"width": 1080, "height": 1920, "fps": 24.0},
            "duration": timeline_duration, "frames": round(timeline_duration * 24),
            "routing_summary": payload["routing_summary"],
            "ai_attempts": 0, "assets": [asset_record],
        },
    )
    state.mark_ready(job, "visual_assets", [manifest, track])
    if approve_assets:
        state.approve(job, "visual_assets")
    return job, track


def _ready_v2_job(
    root: Path,
    *,
    kinds: tuple[str, ...] = (),
) -> tuple[object, Path]:
    from edit.hd.tests import test_visual_plan
    from edit.hd.tools import (
        content_analysis,
        contract_artifacts,
        state,
    )

    source = root / "source.mp4"
    script = root / "script.txt"
    _video(source, audio=True)
    script_text = "严格动态字幕覆盖完整整理内容"
    script.write_text(script_text, encoding="utf-8")
    job = state.create_job(
        root,
        source,
        script,
        profile="full-v2",
    )

    inspect = job.job_dir / "01-inspect/report.json"
    inspect.parent.mkdir()
    _canonical(inspect, {"schema_version": 1})
    state.mark_ready(job, "inspect", (inspect,))
    state.approve(job, "inspect")

    analysis = content_analysis.prepare_content_analysis(
        job,
        {
            "thesis": script_text,
            "hook": script_text,
            "sections": [
                {"id": "section-01", "title": "字幕整理", "source_span": [0, len(script_text)]}
            ],
            "items": [
                {
                    "id": "idea-01",
                    "source_text": script_text,
                    "source_span": [0, len(script_text)],
                    "priority": "critical",
                    "keywords": ["严格", "字幕"],
                    "semantic_type": "thesis",
                    "evidence_status": "supported",
                    "broll_priority": "high",
                }
            ],
            "claims": [],
        },
    )
    state.approve(job, "content_analysis")

    for stage_id, relative in (
        ("cover_direction", "03-cover-direction/review.html"),
        ("cover", "04-cover/cover.png"),
    ):
        artifact = job.job_dir / relative
        artifact.parent.mkdir()
        artifact.write_bytes(stage_id.encode())
        state.mark_ready(job, stage_id, (artifact,))
        state.approve(job, stage_id)

    transcript = job.job_dir / "05-speech-cleanup/word-transcript.json"
    transcript.parent.mkdir()
    _canonical(
        transcript,
        {
            "version": 1,
            "words": [
                {
                    "text": glyph,
                    "start": 0.05 + index * 0.15,
                    "end": 0.17 + index * 0.15,
                }
                for index, glyph in enumerate(script_text)
            ],
        },
    )
    summary = transcript.parent / "diff-summary.json"
    _canonical(summary, {"version": 1, "original_script": script_text,
                         "cleaned_script": script_text, "deleted_words": [],
                         "deleted_word_count": 0})
    state.mark_ready(job, "speech_cleanup", (transcript, summary))
    state.approve(job, "speech_cleanup")

    edit_root = job.job_dir / "06-edit-structure"
    edit_root.mkdir()
    edited = edit_root / "edited-aroll.mp4"
    shutil.copyfile(source, edited)
    edit_plan = edit_root / "edit-plan.json"
    timeline = edit_root / "timeline-map.json"
    _canonical(edit_plan, {"version": 1})
    _canonical(
        timeline,
        {
            "version": 1,
            "source_duration": 3.0,
            "output_duration": 3.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "render_adapter": "native-ffmpeg-no-cut",
            "segments": [
                {
                    "source_start": 0.0,
                    "source_end": 3.0,
                    "timeline_start": 0.0,
                    "timeline_end": 3.0,
                }
            ],
        },
    )
    state.mark_ready(job, "edit_structure", (edit_plan, edited, timeline))
    state.approve(job, "edit_structure")

    plan = test_visual_plan.valid_plan(kinds)
    plan["content_analysis_sha256"] = analysis["analysis_sha256"]
    plan["edit_plan_sha256"] = contract_artifacts.sha256_file(edit_plan)
    plan["timeline_map_sha256"] = contract_artifacts.sha256_file(timeline)
    plan["edited_aroll_sha256"] = contract_artifacts.sha256_file(edited)
    for key in ("visual_strategy", "shot_recipe"):
        composition = plan["segments"][0][key]["composition"]
        if composition.get("presenter_mode") == "bottom_window":
            composition["avatar"]["profile"]["source_sha256"] = plan[
                "edited_aroll_sha256"
            ]
    unsigned = {
        key: value for key, value in plan.items() if key != "visual_plan_sha256"
    }
    plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
    direction = job.job_dir / "07-visual-direction"
    direction.mkdir()
    visual_plan = direction / "visual-plan.json"
    review = direction / "visual-routing.md"
    contract_artifacts.write_json_artifact(visual_plan, plan)
    review.write_text("# Visual plan\n", encoding="utf-8")
    state.mark_ready(job, "visual_direction", (visual_plan, review))
    state.approve(job, "visual_direction")

    canary = job.job_dir / "08-visual-canary/canary-manifest.json"
    canary.parent.mkdir()
    _canonical(canary, {"schema_version": 2})
    state.mark_ready(job, "visual_canary", (canary,))
    state.approve(job, "visual_canary")

    asset_root = job.job_dir / "09-visual-assets"
    asset_root.mkdir()
    track = asset_root / "visual-track.mp4"
    _video(track, audio=False)
    manifest = asset_root / "asset-manifest.json"
    _canonical(
        manifest,
        {
            "schema_version": 3,
            "visual_plan_sha256": plan["visual_plan_sha256"],
            "visual_track": {
                "path": "09-visual-assets/visual-track.mp4",
                "sha256": contract_artifacts.sha256_file(track),
                "bytes": track.stat().st_size,
            },
        },
    )
    state.mark_ready(job, "visual_assets", (manifest, track))
    state.approve(job, "visual_assets")
    return job, track


class SubtitleContractTests(unittest.TestCase):
    def test_cut_does_not_reintroduce_leading_false_start_punctuation(self):
        from edit.hd.tools import subtitles
        words = [
            {"text": "少了", "start": 1.0, "end": 1.2},
            {"text": "，", "start": 1.2, "end": 1.8},
            {"text": "口误", "start": 1.8, "end": 2.3},
            {"text": "，", "start": 2.3, "end": 2.8},
            {"text": "靠谱感", "start": 2.8, "end": 3.2},
            {"text": "。", "start": 3.2, "end": 3.3},
        ]
        timeline = {"segments": [
            {"source_start": 1.0, "source_end": 1.5, "timeline_start": 0.0},
            {"source_start": 2.5, "source_end": 3.4, "timeline_start": 0.5},
        ]}
        mapped = subtitles._map_words(words, timeline)
        self.assertEqual("".join(word["text"] for word in mapped), "少了，靠谱感。")
        self.assertAlmostEqual(mapped[2]["start"], 0.8)

    def test_srt_keeps_trailing_space_in_last_cue(self) -> None:
        from edit.hd.tools import subtitles

        cues = [{"start": 0.08, "end": 1.5, "text": "最后一个词 "}]
        self.assertEqual(
            subtitles.parse_srt(subtitles._srt_bytes(cues).decode("utf-8")),
            [(0.08, 1.5, "最后一个词 ")],
        )

    def test_timeline_contract_accepts_the_matching_render_adapter(self) -> None:
        from edit.hd.tools import subtitles

        timeline = {
            "version": 1,
            "source_duration": 3.0,
            "output_duration": 3.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "render_adapter": "native-ffmpeg-no-cut",
            "segments": [{
                "source_start": 0.0,
                "source_end": 3.0,
                "timeline_start": 0.0,
                "timeline_end": 3.0,
            }],
        }

        self.assertEqual(subtitles._validate_timeline(timeline), timeline)

    def test_timeline_contract_rejects_missing_wrong_or_extra_render_adapter(
        self,
    ) -> None:
        from edit.hd.tools import subtitles

        valid = {
            "version": 1,
            "source_duration": 3.0,
            "output_duration": 3.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "render_adapter": "native-ffmpeg-no-cut",
            "segments": [{
                "source_start": 0.0,
                "source_end": 3.0,
                "timeline_start": 0.0,
                "timeline_end": 3.0,
            }],
        }
        cases: list[dict[str, object]] = []
        missing = copy.deepcopy(valid)
        missing.pop("render_adapter")
        cases.append(missing)
        wrong = copy.deepcopy(valid)
        wrong["render_adapter"] = "another-renderer"
        cases.append(wrong)
        extra = copy.deepcopy(valid)
        extra["adapter_note"] = "unexpected"
        cases.append(extra)

        for timeline in cases:
            with self.subTest(timeline=timeline), self.assertRaises(
                subtitles.SubtitleError,
            ):
                subtitles._validate_timeline(timeline)

    def test_legacy_timeline_contract_accepts_each_local_ffmpeg_adapter(
        self,
    ) -> None:
        from edit.hd.tools import subtitles

        for has_deletion, adapter, audio_policy in (
            (False, "local-ffmpeg-no-cut", "copy-original-elementary"),
            (True, "local-ffmpeg-trim-concat", "aac-48000-stereo-single-encode"),
        ):
            timeline = {
                "version": 1,
                "source_duration": 3.0,
                "output_duration": 3.0,
                "has_deletion": has_deletion,
                "audio_policy": audio_policy,
                "render_adapter": adapter,
                "segments": [{
                    "source_start": 0.0,
                    "source_end": 3.0,
                    "timeline_start": 0.0,
                    "timeline_end": 3.0,
                }],
            }

            with self.subTest(has_deletion=has_deletion):
                self.assertEqual(
                    subtitles._validate_timeline(timeline, workflow_version=1),
                    timeline,
                )

    def test_legacy_timeline_contract_rejects_missing_or_wrong_adapter(
        self,
    ) -> None:
        from edit.hd.tools import subtitles

        valid = {
            "version": 1,
            "source_duration": 3.0,
            "output_duration": 3.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "render_adapter": "local-ffmpeg-no-cut",
            "segments": [{
                "source_start": 0.0,
                "source_end": 3.0,
                "timeline_start": 0.0,
                "timeline_end": 3.0,
            }],
        }
        missing = copy.deepcopy(valid)
        missing.pop("render_adapter")
        wrong = copy.deepcopy(valid)
        wrong["render_adapter"] = "native-ffmpeg-no-cut"

        for timeline in (missing, wrong):
            with self.subTest(timeline=timeline), self.assertRaises(
                subtitles.SubtitleError,
            ):
                subtitles._validate_timeline(timeline, workflow_version=1)

    def test_module_exposes_only_the_minimal_public_stage_api(self) -> None:
        module = importlib.import_module("edit.hd.tools.subtitles")
        self.assertEqual(
            module.__all__,
            [
                "SubtitleError",
                "validate_subtitle_plan",
                "render_subtitle_frame",
                "build_final_overlay_command",
                "prepare_subtitles",
            ],
        )

    def test_strict_plan_accepts_all_four_layouts(self) -> None:
        from edit.hd.tools import subtitles

        checked = subtitles.validate_subtitle_plan(_plan())
        self.assertEqual(
            [cue["type"] for cue in checked["cues"]],
            ["emphasis", "statement", "source", "action"],
        )

    def test_strict_plan_accepts_no_cues_when_every_layout_count_is_zero(self) -> None:
        from edit.hd.tools import subtitles

        plan = _plan()
        plan["cues"] = []
        plan["layout_counts"] = {name: 0 for name in plan["layout_counts"]}

        try:
            checked = subtitles.validate_subtitle_plan(plan)
        except subtitles.SubtitleError:
            self.fail("zero-cue subtitle plan must be valid")

        self.assertEqual(checked["cues"], [])
        self.assertEqual(
            checked["layout_counts"],
            {"emphasis": 0, "statement": 0, "source": 0, "action": 0},
        )

    def test_plan_allows_missing_emphasis_candidates_when_a_later_one_matches(self) -> None:
        from edit.hd.tools import subtitles

        plan = _plan()
        plan["cues"][0]["text"] = "流程决定结果"
        plan["cues"][0]["emphasis_words"] = ["不存在", "结果"]
        checked = subtitles.validate_subtitle_plan(plan)
        calls = []
        original = ImageDraw.ImageDraw.text

        def capture(draw, xy, value, *args, **kwargs):
            calls.append((value, kwargs.get("fill")))
            return original(draw, xy, value, *args, **kwargs)

        cue = checked["cues"][0]
        with mock.patch.object(ImageDraw.ImageDraw, "text", new=capture):
            subtitles.render_subtitle_frame(
                checked["cues"], (cue["start"] + cue["end"]) / 2
            )
        self.assertEqual(
            "".join(value for value, fill in calls if fill == subtitles.WARM_YELLOW),
            "结果",
        )

    def test_plan_rejects_emphasis_candidates_when_none_match_text(self) -> None:
        from edit.hd.tools import subtitles

        plan = _plan()
        plan["cues"][0]["text"] = "流程决定结果"
        plan["cues"][0]["emphasis_words"] = ["不存在", "也不存在"]
        with self.assertRaises(subtitles.SubtitleError):
            subtitles.validate_subtitle_plan(plan)

    def test_plan_rejects_duplicate_extra_bool_nonfinite_and_outside_job_paths(self) -> None:
        from edit.hd.tools import subtitles

        mutations = []
        duplicate = copy.deepcopy(_plan())
        duplicate["cues"][1]["id"] = duplicate["cues"][0]["id"]
        mutations.append(duplicate)
        extra = copy.deepcopy(_plan())
        extra["cues"][0]["extra"] = "forbidden"
        mutations.append(extra)
        boolean = copy.deepcopy(_plan())
        boolean["cues"][0]["start"] = True
        mutations.append(boolean)
        nonfinite = copy.deepcopy(_plan())
        nonfinite["canvas"]["duration"] = math.inf
        mutations.append(nonfinite)
        outside_job = copy.deepcopy(_plan())
        outside_job["source_bindings"]["visual_track"]["path"] = "../track.mp4"
        mutations.append(outside_job)
        overlap = copy.deepcopy(_plan())
        overlap["cues"][1]["start"] = overlap["cues"][0]["end"] - 0.01
        mutations.append(overlap)
        for payload in mutations:
            with self.subTest(payload=payload), self.assertRaises(subtitles.SubtitleError):
                subtitles.validate_subtitle_plan(payload)

    def test_json_parser_rejects_duplicate_keys_nan_and_infinity(self) -> None:
        from edit.hd.tools import subtitles

        with self.assertRaises(subtitles.SubtitleError):
            subtitles.parse_subtitle_plan_json('{"version":1,"version":1}')
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), self.assertRaises(subtitles.SubtitleError):
                subtitles.parse_subtitle_plan_json(
                    '{"version":1,"canvas":{"duration":' + constant + "}}"
                )

    def test_plan_requires_box_inside_declared_subtitle_safe_zone(self) -> None:
        from edit.hd.tools import subtitles

        outside = copy.deepcopy(_plan())
        outside["cues"][0]["box"] = {
            "x": 320, "y": 1320, "width": 600, "height": 180,
        }
        with self.assertRaises(subtitles.SubtitleError):
            subtitles.validate_subtitle_plan(outside)

    def test_plan_keeps_first_and_last_seek_frames_transparent(self) -> None:
        from edit.hd.tools import subtitles

        starts_at_zero = copy.deepcopy(_plan())
        starts_at_zero["cues"][0]["start"] = 0.0
        ends_at_duration = copy.deepcopy(_plan())
        ends_at_duration["cues"][-1]["end"] = 2.0
        subframe = copy.deepcopy(_plan())
        subframe["cues"][0]["start"] = 0.050
        subframe["cues"][0]["end"] = 0.060
        for payload in (starts_at_zero, ends_at_duration, subframe):
            with self.subTest(payload=payload), self.assertRaises(
                subtitles.SubtitleError
            ):
                subtitles.validate_subtitle_plan(payload)

    def test_regular_cues_prefer_eight_to_fourteen_visible_glyphs(self) -> None:
        from edit.hd.tools import subtitles

        text, plan = _dense_aroll_plan()
        cues = plan["cues"]

        self.assertEqual("".join(cue["text"] for cue in cues), text)
        self.assertEqual(
            subtitles._visible_glyph_count([{"text": "词\t语\n"}]), 2
        )
        short_cues = [
            index for index, cue in enumerate(cues)
            if subtitles._visible_glyph_count([
                {"text": cue["text"]}
            ]) < 8
        ]
        self.assertLessEqual(len(short_cues), 1)
        self.assertTrue(all(index in {0, len(cues) - 1} for index in short_cues))
        self.assertTrue(all(
            subtitles._visible_glyph_count([{"text": cue["text"]}]) <= 14
            for cue in cues
        ))

    def test_cues_only_emphasize_semantic_keyword_overlaps(self) -> None:
        from edit.hd.tools import subtitles

        text, plan = _dense_aroll_plan()
        cues = plan["cues"]
        keywords = ("人工智能", "表达能力", "内容结构")

        self.assertEqual("".join(cue["text"] for cue in cues), text)
        for cue in cues:
            self.assertLessEqual(len(cue["emphasis_words"]), 1)
            if cue["emphasis_words"]:
                emphasis = cue["emphasis_words"][0]
                self.assertIn(emphasis, cue["text"])
                self.assertTrue(any(emphasis in keyword for keyword in keywords))
                self.assertGreaterEqual(subtitles._visible_glyph_count([{"text": emphasis}]), 2)

    def test_semantic_emphasis_uses_complete_overlap_and_skips_filler(self) -> None:
        from edit.hd.tools import subtitles

        cases = (
            ("的朋友们你们看懂这些底层", ["避开学习误区", "跟上趋势"], ""),
            ("逻辑能帮你避开绝大多数", ["避开学习误区"], "避开"),
            ("Spark框架联合创始人", ["Apache Spark"], "Spark"),
            ("动调整自己的评判标准", ["评判标准在变"], "评判标准"),
            ("其实想通了就很简单具备通用", ["通用能力", "这就是 AGI"], "通用"),
            ("的能力且综合智能超越多数", ["通用能力", "这就是 AGI"], "能力"),
            ("是职场人最珍贵的核心优势", ["人的核心优势"], "核心优势"),
            ("AI工具不会拉开人和人", ["工具不拉开差距"], "拉开"),
        )
        for text, keywords, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    subtitles._semantic_emphasis(text, keywords),
                    expected,
                )

    def test_semantic_emphasis_marks_each_keyword_once_at_its_best_cue(self) -> None:
        from edit.hd.tools import subtitles

        texts = [
            "分享给每一个正在接触学习AI",
            "逻辑能帮你避开绝大多数",
            "AI学习的误区稳稳跟上这波",
            "AI时代的发展趋势",
        ]

        self.assertEqual(
            subtitles._semantic_emphasis_assignments(
                texts, ["避开学习误区", "跟上趋势"]
            ),
            ["", "", "误区", "趋势"],
        )
        self.assertEqual(
            subtitles._semantic_emphasis_assignments(
                ["其实想通了就很简单具备通用", "的能力且综合智能超越多数"],
                ["通用能力"],
            ),
            ["", "能力"],
        )
        self.assertEqual(
            subtitles._semantic_emphasis_assignments(
                ["ß Spark框架联合创始人", "İ AGI已经到来"],
                ["Spark", "AGI"],
            ),
            ["Spark", "AGI"],
        )

    def test_plan_allows_empty_emphasis_for_plain_subtitle_cue(self) -> None:
        from edit.hd.tools import subtitles

        plan = _plan()
        plan["cues"][0]["emphasis_words"] = []

        checked = subtitles.validate_subtitle_plan(plan)

        self.assertEqual(checked["cues"][0]["emphasis_words"], [])
        self.assertEqual(subtitles._visible_emphasis("普通字幕", []), "")

    def test_partition_rebalances_an_avoidable_short_tail_cue(self) -> None:
        from edit.hd.tools import subtitles

        text = "字" * 35
        words = [
            {"text": character, "start": 0.1 + index * 0.1, "end": 0.19 + index * 0.1}
            for index, character in enumerate(text)
        ]
        safe_zones = _zones()
        safe_zones["subtitle"] = {"x": 120, "y": 1510, "width": 300, "height": 220}
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": 4.0,
                "output_duration": 4.0,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": 4.0,
                    "timeline_start": 0.0,
                    "timeline_end": 4.0,
                }],
            },
            visual_plan={
                "duration": 4.0,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": 4.0,
                    "implementation": "arroll",
                    "keywords": [{"text": "字"}],
                    "safe_zones": safe_zones,
                }],
            },
        )

        self.assertEqual("".join(cue["text"] for cue in plan["cues"]), text)
        self.assertTrue(all(
            subtitles._visible_glyph_count([{"text": cue["text"]}]) >= 8
            for cue in plan["cues"]
        ))

    def test_partition_prefers_globally_centered_cues_over_fewer_valid_cues(self) -> None:
        from edit.hd.tools import subtitles

        text = "字" * 42
        words = [
            {"text": character, "start": 0.1 + index * 0.1, "end": 0.19 + index * 0.1}
            for index, character in enumerate(text)
        ]
        safe_zones = _zones()
        safe_zones["subtitle"] = {"x": 120, "y": 1510, "width": 300, "height": 220}
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": 5.0,
                "output_duration": 5.0,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": 5.0,
                    "timeline_start": 0.0,
                    "timeline_end": 5.0,
                }],
            },
            visual_plan={
                "duration": 5.0,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": 5.0,
                    "implementation": "arroll",
                    "keywords": [],
                    "safe_zones": safe_zones,
                }],
            },
        )

        glyph_counts = [
            subtitles._visible_glyph_count([{"text": cue["text"]}])
            for cue in plan["cues"]
        ]
        range_penalty = sum(
            max(0, 8 - count) + max(0, count - 14)
            for count in glyph_counts
        )
        self.assertEqual("".join(cue["text"] for cue in plan["cues"]), text)
        self.assertTrue(all(count <= 14 for count in glyph_counts))
        self.assertEqual(range_penalty, 0)
        self.assertEqual(sum(abs(count - 11) for count in glyph_counts), 2)

    def test_partition_handles_four_hundred_words_with_bounded_resources(self) -> None:
        from edit.hd.tools import subtitles

        words = [
            {"text": "字", "start": index * 0.1, "end": index * 0.1 + 0.09}
            for index in range(400)
        ]
        tracemalloc.start()
        started = time.monotonic()
        try:
            with mock.patch.object(subtitles, "_word_interval_fits", return_value=True), mock.patch.object(
                subtitles, "_chunk_has_sample_frame", return_value=True,
            ):
                partition = subtitles._partition_subtitle_words(
                    words,
                    [words],
                    box={"x": 120, "y": 1510, "width": 840, "height": 220},
                    font_path=Path("/tmp/unused-font.ttf"),
                    cue_type="emphasis",
                    segment_start=0.0,
                    segment_end=40.0,
                    duration=40.0,
                    protected_boundaries=set(),
                    layout_cache={},
                )
        finally:
            elapsed = time.monotonic() - started
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        glyph_counts = [subtitles._visible_glyph_count(chunk) for chunk in partition]
        self.assertEqual("".join(word["text"] for chunk in partition for word in chunk), "字" * 400)
        self.assertTrue(all(count <= 14 for count in glyph_counts))
        self.assertEqual(sum(max(0, 8 - count) + max(0, count - 14) for count in glyph_counts), 0)
        self.assertEqual(sum(abs(count - 11) for count in glyph_counts), 4)
        self.assertLess(elapsed, 5.0)
        self.assertLess(peak, 128 * 1024 * 1024)

    def test_partition_fails_closed_for_oversized_tokens_and_phrases(self) -> None:
        from edit.hd.tools import subtitles

        base = {
            "records": _plan()["source_bindings"],
            "timeline": {
                "version": 1,
                "source_duration": 4.0,
                "output_duration": 4.0,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": 4.0,
                    "timeline_start": 0.0,
                    "timeline_end": 4.0,
                }],
            },
        }
        cases = [
            ([{"text": "超" * 15, "start": 0.1, "end": 1.0}], []),
            ([
                {"text": "长", "start": 0.1 + index * 0.2, "end": 0.28 + index * 0.2}
                for index in range(15)
            ], [{"text": "长" * 15}]),
        ]
        for words, keywords in cases:
            with self.subTest(words=words, keywords=keywords), self.assertRaises(
                subtitles.SubtitleError
            ):
                subtitles._build_plan(
                    **base,
                    words=words,
                    visual_plan={
                        "duration": 4.0,
                        "segments": [{
                            "segment_id": "seg-001",
                            "start": 0.0,
                            "end": 4.0,
                            "implementation": "arroll",
                            "keywords": keywords,
                            "safe_zones": _zones(),
                        }],
                    },
                )

    def test_final_overlay_command_keeps_subtitles_last_and_copies_aroll_audio(self) -> None:
        from edit.hd.tools import subtitles

        command = subtitles.build_final_overlay_command(
            Path("/tmp/edited-aroll.mp4"),
            Path("/tmp/subtitles.webm"),
            Path("/tmp/final.mp4"),
        )
        self.assertTrue(any("[0:v][1:v]overlay" in part for part in command))
        self.assertEqual(command[command.index("-map") + 1], "[vout]")
        audio_map = command.index("-map", command.index("-map") + 1)
        self.assertEqual(command[audio_map + 1], "0:a:0")
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertFalse(any(term in " ".join(command) for term in ("loudnorm", "volume=", "aresample")))

    def test_long_visual_segment_splits_into_renderable_cues_without_losing_text(self) -> None:
        from edit.hd.tools import subtitles

        text = "最近我刷到Deeptabreak的CEO在斯坦福大学的分享全程干过满满启发真的非常非常的大分享给每一个正在接触学习AI的朋友们你们看懂这些底层逻辑能帮"
        words = []
        for index, character in enumerate(text):
            start = 0.1 + index * 0.14
            words.append({"text": character, "start": start, "end": start + 0.1})
        duration = 12.0
        safe_zones = _zones()
        safe_zones["subtitle"] = {
            "x": 120, "y": 1600, "width": 840, "height": 180,
        }
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": duration,
                "output_duration": duration,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": duration,
                    "timeline_start": 0.0,
                    "timeline_end": duration,
                }],
            },
            visual_plan={
                "duration": duration,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": duration,
                    "implementation": "arroll",
                    "keywords": [],
                    "safe_zones": safe_zones,
                }],
            },
        )

        self.assertGreater(len(plan["cues"]), 1)
        self.assertEqual("".join(cue["text"] for cue in plan["cues"]), text)
        for cue in plan["cues"]:
            layout = subtitles._layout_text_for_box(
                cue["text"],
                subtitles.bold_subtitles.find_cjk_font(cue["text"]),
                cue["box"],
                cue["type"],
            )
            self.assertLessEqual(len(layout["lines"]), 2)
            frame = subtitles.render_subtitle_frame(
                plan["cues"], (cue["start"] + cue["end"]) / 2
            )
            bbox = frame.getchannel("A").getbbox()
            self.assertIsNotNone(bbox)
            self.assertGreaterEqual(bbox[0], cue["box"]["x"] - 2)
            self.assertGreaterEqual(bbox[1], cue["box"]["y"] - 2)
            self.assertLessEqual(
                bbox[2], cue["box"]["x"] + cue["box"]["width"] + 2
            )
            self.assertLessEqual(
                bbox[3], cue["box"]["y"] + cue["box"]["height"] + 2
            )

    def test_broll_words_are_consumed_without_cues_and_aroll_cue_stops_at_boundary(self) -> None:
        from edit.hd.tools import subtitles

        words = [
            {"text": "A", "start": 0.10, "end": 0.45},
            {"text": "口", "start": 0.45, "end": 0.95},
            {"text": "B", "start": 1.00, "end": 1.35},
            {"text": "画", "start": 1.35, "end": 1.80},
        ]
        timeline = {
            "version": 1,
            "source_duration": 2.0,
            "output_duration": 2.0,
            "has_deletion": False,
            "audio_policy": "copy-original-elementary",
            "segments": [{
                "source_start": 0.0,
                "source_end": 2.0,
                "timeline_start": 0.0,
                "timeline_end": 2.0,
            }],
        }
        visual_plan = {
            "duration": 2.0,
            "segments": [
                {
                    "segment_id": "seg-arroll",
                    "start": 0.0,
                    "end": 1.0,
                    "implementation": "arroll",
                    "keywords": [{"text": "A"}],
                    "safe_zones": _zones(),
                },
                {
                    "segment_id": "seg-broll",
                    "start": 1.0,
                    "end": 2.0,
                    "implementation": "code",
                    "keywords": [{"text": "B"}],
                    "safe_zones": _zones(),
                },
            ],
        }

        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline=timeline,
            visual_plan=visual_plan,
        )

        self.assertEqual("".join(cue["text"] for cue in plan["cues"]), "A口")
        self.assertEqual({cue["segment_id"] for cue in plan["cues"]}, {"seg-arroll"})
        self.assertTrue(all(cue["end"] <= 1.0 for cue in plan["cues"]))
        self.assertEqual(
            plan["layout_counts"],
            {"emphasis": 1, "statement": 0, "source": 0, "action": 0},
        )

    def test_all_broll_words_are_consumed_into_a_valid_empty_cue_plan(self) -> None:
        from edit.hd.tools import subtitles

        words = [
            {"text": text, "start": index * 0.4 + 0.1, "end": index * 0.4 + 0.4}
            for index, text in enumerate("全部画面")
        ]
        try:
            plan = subtitles._build_plan(
                records=_plan()["source_bindings"],
                words=words,
                timeline={
                    "version": 1,
                    "source_duration": 2.0,
                    "output_duration": 2.0,
                    "has_deletion": False,
                    "audio_policy": "copy-original-elementary",
                    "segments": [{
                        "source_start": 0.0,
                        "source_end": 2.0,
                        "timeline_start": 0.0,
                        "timeline_end": 2.0,
                    }],
                },
                visual_plan={
                    "duration": 2.0,
                    "segments": [{
                        "segment_id": "seg-code",
                        "start": 0.0,
                        "end": 2.0,
                        "implementation": "code",
                        "keywords": [{"text": "全部"}],
                        "safe_zones": _zones(),
                    }],
                },
            )
        except subtitles.SubtitleError:
            self.fail("all B-roll words must produce a valid empty-cue plan")

        self.assertEqual(plan["cues"], [])
        self.assertEqual(
            plan["layout_counts"],
            {"emphasis": 0, "statement": 0, "source": 0, "action": 0},
        )

    def test_greedy_split_uses_bounded_layout_calls(self) -> None:
        from edit.hd.tools import subtitles

        text = "字" * 90
        words = [
            {"text": character, "start": index * 0.05, "end": (index + 1) * 0.05}
            for index, character in enumerate(text)
        ]
        box = {"x": 120, "y": 1600, "width": 840, "height": 180}
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        original = subtitles._layout_text_for_box
        with mock.patch.object(
            subtitles, "_layout_text_for_box", wraps=original,
        ) as layout:
            chunks = subtitles._split_words_for_box(
                words, box, font_path, "emphasis"
            )
        self.assertEqual(
            "".join(str(word["text"]) for chunk in chunks for word in chunk),
            text,
        )
        self.assertLessEqual(layout.call_count, 20)

    def test_greedy_split_preserves_tokens_ending_in_spaces(self) -> None:
        from edit.hd.tools import subtitles

        words = [
            {"text": "A       ", "start": 0.1, "end": 0.2},
            {"text": "B", "start": 0.2, "end": 0.3},
        ]
        box = {"x": 0, "y": 0, "width": 75, "height": 180}
        font_path = subtitles.bold_subtitles.find_cjk_font("A       B")
        chunks = subtitles._split_words_for_box(
            words, box, font_path, "emphasis"
        )
        self.assertEqual(
            "".join(str(word["text"]) for chunk in chunks for word in chunk),
            "A       B",
        )
        self.assertEqual(len(chunks), 1)

    def test_long_layout_uses_bounded_font_width_measurements(self) -> None:
        from edit.hd.tools import subtitles
        from edit.v5.tools import bold_subtitles

        text = "字幕性能验证" * 7 + "字幕"
        self.assertEqual(len(text), 44)
        font_path = bold_subtitles.find_cjk_font(text)
        subtitles._font_text_width.cache_clear()
        subtitles._cached_text_layout.cache_clear()
        layout = subtitles._layout_text_for_box(
            text,
            font_path,
            {"x": 120, "y": 1600, "width": 840, "height": 180},
            "emphasis",
        )
        self.assertLessEqual(len(layout["lines"]), 2)
        self.assertLessEqual(subtitles._font_text_width.cache_info().misses, 400)

    def test_short_tail_chunk_is_rebalanced_to_a_valid_24fps_sample_frame(self) -> None:
        from edit.hd.tools import subtitles

        text = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨露结为霜金生丽水玉"
        self.assertEqual(len(text), 45)
        words = [
            {
                "text": character,
                "start": round(0.1 + index * 0.03, 3),
                "end": round(0.1 + (index + 1) * 0.03, 3),
            }
            for index, character in enumerate(text)
        ]
        duration = 2.0
        safe_zones = _zones()
        safe_zones["subtitle"] = {
            "x": 120, "y": 1600, "width": 840, "height": 220,
        }
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": duration,
                "output_duration": duration,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": duration,
                    "timeline_start": 0.0,
                    "timeline_end": duration,
                }],
            },
            visual_plan={
                "duration": duration,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": duration,
                    "implementation": "arroll",
                    "keywords": [{"text": "水玉"}],
                    "safe_zones": safe_zones,
                }],
            },
        )

        cues = plan["cues"]
        self.assertGreater(len(cues), 1)
        self.assertEqual("".join(cue["text"] for cue in cues), text)
        self.assertEqual(cues[0]["start"], words[0]["start"])
        self.assertEqual(cues[-1]["end"], words[-1]["end"])
        self.assertNotIn("水玉", cues[0]["emphasis_words"])
        self.assertEqual(cues[-1]["emphasis_words"], ["水玉"])
        previous_end = None
        for cue in cues:
            layout = subtitles._layout_text_for_box(
                cue["text"],
                subtitles.bold_subtitles.find_cjk_font(cue["text"]),
                cue["box"],
                cue["type"],
            )
            self.assertLessEqual(len(layout["lines"]), 2)
            if previous_end is not None:
                self.assertEqual(cue["start"], previous_end)
            sample_index = min(
                plan["canvas"]["frames"] - 2,
                max(1, round(((cue["start"] + cue["end"]) / 2) * 24)),
            )
            sample_time = sample_index / 24
            self.assertLessEqual(cue["start"], sample_time)
            self.assertLess(sample_time, cue["end"])
            previous_end = cue["end"]

    def test_valid_sample_boundary_is_rebalanced_when_it_splits_emphasis_phrase(self) -> None:
        from edit.hd.tools import subtitles

        text = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨露结为霜金生丽水玉"
        words = [
            {
                "text": character,
                "start": round(0.1 + index * 0.05, 3),
                "end": round(0.1 + (index + 1) * 0.05, 3),
            }
            for index, character in enumerate(text)
        ]
        duration = 3.0
        safe_zones = _zones()
        safe_zones["subtitle"] = {
            "x": 120, "y": 1600, "width": 840, "height": 220,
        }
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": duration,
                "output_duration": duration,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": duration,
                    "timeline_start": 0.0,
                    "timeline_end": duration,
                }],
            },
            visual_plan={
                "duration": duration,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": duration,
                    "implementation": "arroll",
                    "keywords": [{"text": "水玉"}],
                    "safe_zones": safe_zones,
                }],
            },
        )

        cues = plan["cues"]
        self.assertEqual("".join(cue["text"] for cue in cues), text)
        matches = [cue for cue in cues if "水玉" in cue["text"]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["emphasis_words"], ["水玉"])
        previous_end = None
        for cue in cues:
            layout = subtitles._layout_text_for_box(
                cue["text"],
                subtitles.bold_subtitles.find_cjk_font(cue["text"]),
                cue["box"],
                cue["type"],
            )
            self.assertLessEqual(len(layout["lines"]), 2)
            if previous_end is not None:
                self.assertEqual(cue["start"], previous_end)
            sample_index = min(
                plan["canvas"]["frames"] - 2,
                max(1, round(((cue["start"] + cue["end"]) / 2) * 24)),
            )
            sample_time = sample_index / 24
            self.assertLessEqual(cue["start"], sample_time)
            self.assertLess(sample_time, cue["end"])
            previous_end = cue["end"]

    def test_global_partition_preserves_two_emphasis_phrases_across_bounded_cues(self) -> None:
        from edit.hd.tools import subtitles

        characters = ["字"] * 90
        characters[43:45] = "水玉"
        characters[87:89] = "水玉"
        text = "".join(characters)
        words = [
            {
                "text": character,
                "start": round(0.1 + index * 0.05, 3),
                "end": round(0.1 + (index + 1) * 0.05, 3),
            }
            for index, character in enumerate(text)
        ]
        duration = 5.0
        safe_zones = _zones()
        safe_zones["subtitle"] = {
            "x": 120, "y": 1600, "width": 840, "height": 220,
        }
        plan = subtitles._build_plan(
            records=_plan()["source_bindings"],
            words=words,
            timeline={
                "version": 1,
                "source_duration": duration,
                "output_duration": duration,
                "has_deletion": False,
                "audio_policy": "copy-original-elementary",
                "segments": [{
                    "source_start": 0.0,
                    "source_end": duration,
                    "timeline_start": 0.0,
                    "timeline_end": duration,
                }],
            },
            visual_plan={
                "duration": duration,
                "segments": [{
                    "segment_id": "seg-001",
                    "start": 0.0,
                    "end": duration,
                    "implementation": "arroll",
                    "keywords": [{"text": "水玉"}],
                    "safe_zones": safe_zones,
                }],
            },
        )

        cues = plan["cues"]
        self.assertEqual("".join(cue["text"] for cue in cues), text)
        self.assertTrue(all(
            subtitles._visible_glyph_count([{"text": cue["text"]}]) <= 14
            for cue in cues
        ))
        self.assertEqual(
            [cue["emphasis_words"] for cue in cues if "水玉" in cue["text"]],
            [["水玉"], ["水玉"]],
        )
        boundaries = []
        offset = 0
        previous_end = None
        for cue in cues:
            self.assertTrue(cue["text"])
            offset += len(cue["text"])
            boundaries.append(offset)
            layout = subtitles._layout_text_for_box(
                cue["text"],
                subtitles.bold_subtitles.find_cjk_font(cue["text"]),
                cue["box"],
                cue["type"],
            )
            self.assertLessEqual(len(layout["lines"]), 2)
            if previous_end is not None:
                self.assertEqual(cue["start"], previous_end)
            sample_index = min(
                plan["canvas"]["frames"] - 2,
                max(1, round(((cue["start"] + cue["end"]) / 2) * 24)),
            )
            sample_time = sample_index / 24
            self.assertLessEqual(cue["start"], sample_time)
            self.assertLess(sample_time, cue["end"])
            previous_end = cue["end"]
        self.assertNotIn(44, boundaries[:-1])
        self.assertNotIn(88, boundaries[:-1])


class SubtitleRenderTests(unittest.TestCase):
    def test_magazine_caption_has_rail_but_no_background_panel(self) -> None:
        from edit.hd.tools import subtitles

        cues = [{
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "AI 模型 正在 改变 工作",
            "emphasis_words": ["正在 改变", "工作"],
            "safe_zones": _zones(),
            "box": {"x": 340, "y": 1500, "width": 400, "height": 220},
        }]
        panels = []
        rails = []
        rounded_rectangle = ImageDraw.ImageDraw.rounded_rectangle
        rectangle = ImageDraw.ImageDraw.rectangle

        def capture_panel(draw, xy, *args, **kwargs):
            panels.append((xy, kwargs))
            return rounded_rectangle(draw, xy, *args, **kwargs)

        def capture_rail(draw, xy, *args, **kwargs):
            rails.append((xy, kwargs))
            return rectangle(draw, xy, *args, **kwargs)

        with mock.patch.object(
            ImageDraw.ImageDraw, "rounded_rectangle", new=capture_panel,
        ), mock.patch.object(ImageDraw.ImageDraw, "rectangle", new=capture_rail):
            frame = subtitles.render_subtitle_frame(cues, 0.5)
        self.assertEqual(panels, [])
        matching_rails = [
            (xy, kwargs) for xy, kwargs in rails
            if round(xy[2] - xy[0] + 1) == 3
            and kwargs.get("fill") == subtitles.WARM_YELLOW
        ]
        self.assertTrue(matching_rails)
        rail, _kwargs = matching_rails[0]
        self.assertEqual(rail[0], cues[0]["box"]["x"])
        self.assertGreaterEqual(rail[1], cues[0]["box"]["y"])
        self.assertLessEqual(rail[3], cues[0]["box"]["y"] + cues[0]["box"]["height"] - 1)
        self.assertTrue(all((xy[2] - xy[0] + 1) <= 3 for xy, _kwargs in rails))
        alpha = frame.getchannel("A")
        x = cues[0]["box"]["x"]
        self.assertIsNotNone(alpha.crop((x, rail[1], x + 3, rail[3] + 1)).getbbox())
        pixels = list(frame.getdata())
        yellow = [
            pixel for pixel in pixels
            if pixel[0] > 210 and pixel[1] > 150 and pixel[2] < 100 and pixel[3] > 0
        ]
        white = [pixel for pixel in pixels if min(pixel[:3]) > 220 and pixel[3] > 0]
        self.assertTrue(yellow)
        self.assertTrue(white)

    def test_art_word_is_one_rotated_group_of_upright_glyphs(self) -> None:
        from edit.hd.tools import subtitles

        text = "正在改变"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        with mock.patch.object(
            ImageDraw.ImageDraw, "rectangle",
            side_effect=AssertionError("art word must not draw a background"),
        ), mock.patch.object(
            ImageDraw.ImageDraw, "rounded_rectangle",
            side_effect=AssertionError("art word must not draw a background"),
        ):
            layer, metadata = subtitles._render_art_word(text, font_path, 48)

        self.assertEqual(layer.mode, "RGBA")
        self.assertEqual(metadata["text"], text)
        self.assertEqual(metadata["font_size"], round(48 * 1.3))
        self.assertAlmostEqual(metadata["rotation_degrees"], 5.0, delta=0.25)
        self.assertEqual(metadata["glyph_rotations"], [0] * len(text))
        self.assertIsNotNone(layer.getchannel("A").getbbox())
        body_font = ImageFont.truetype(str(font_path), 48)
        body_bbox = body_font.getbbox(text)
        self.assertGreater(layer.height, body_bbox[3] - body_bbox[1])
        pixels = list(layer.getdata())
        self.assertTrue(any(
            red > 220 and green > 150 and blue < 100 and alpha > 0
            for red, green, blue, alpha in pixels
        ))
        self.assertTrue(any(
            max(red, green, blue) < 80 and alpha > 0
            for red, green, blue, alpha in pixels
        ))
        self.assertTrue(any(layer.getpixel(point)[3] == 0 for point in (
            (0, 0), (layer.width - 1, 0), (0, layer.height - 1),
            (layer.width - 1, layer.height - 1),
        )))

    def test_art_word_pixels_equal_one_counterclockwise_group_rotation(self) -> None:
        from edit.hd.tools import subtitles

        text = "整体旋转"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        unrotated, unrotated_metadata = subtitles._render_art_word_unrotated(
            text, font_path, 48
        )
        actual, final_metadata = subtitles._render_art_word(text, font_path, 48)
        resampling = getattr(Image, "Resampling", Image)
        expected = unrotated.rotate(
            5.0, resample=resampling.BICUBIC, expand=True
        )
        wrong_direction = unrotated.rotate(
            -5.0, resample=resampling.BICUBIC, expand=True
        )

        self.assertEqual(actual.size, expected.size)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertNotEqual(actual.tobytes(), wrong_direction.tobytes())
        self.assertEqual(unrotated_metadata["rotation_degrees"], 0.0)
        self.assertEqual(final_metadata["rotation_degrees"], 5.0)

    def test_unrotated_art_word_never_rotates_or_affine_transforms_glyphs(self) -> None:
        from edit.hd.tools import subtitles

        text = "正体字形"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        with mock.patch.object(
            Image.Image, "rotate",
            side_effect=AssertionError("glyphs must stay upright"),
        ), mock.patch.object(
            Image.Image, "transform",
            side_effect=AssertionError("glyphs must not use affine transforms"),
        ):
            layer, metadata = subtitles._render_art_word_unrotated(
                text, font_path, 48
            )
        self.assertIsNotNone(layer.getchannel("A").getbbox())
        self.assertEqual(metadata["glyph_rotations"], [0] * len(text))

    def test_art_word_character_offsets_are_bounded_and_deterministic(self) -> None:
        from edit.hd.tools import subtitles

        text = "确定偏移序列"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        first_layer, first = subtitles._render_art_word(text, font_path, 48)
        second_layer, second = subtitles._render_art_word(text, font_path, 48)
        self.assertEqual(first["baseline_offsets"], [0, -4, 3, -2, 4, -3])
        self.assertEqual(first["baseline_offsets"], second["baseline_offsets"])
        self.assertTrue(all(-4 <= value <= 4 for value in first["baseline_offsets"]))
        self.assertEqual(first_layer.tobytes(), second_layer.tobytes())

    def test_art_word_baseline_offsets_change_real_alpha_pixels(self) -> None:
        from edit.hd.tools import subtitles

        text = "偏移像素证据"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        normal_unrotated, normal_metadata = subtitles._render_art_word_unrotated(
            text, font_path, 48
        )
        normal_final, _metadata = subtitles._render_art_word(text, font_path, 48)
        with mock.patch.object(subtitles, "_ART_WORD_OFFSETS", (0,)):
            flat_unrotated, flat_metadata = subtitles._render_art_word_unrotated(
                text, font_path, 48
            )
            flat_final, _metadata = subtitles._render_art_word(text, font_path, 48)

        def row_alpha_sums(image):
            alpha = image.getchannel("A")
            return [
                sum(alpha.crop((0, y, alpha.width, y + 1)).getdata())
                for y in range(alpha.height)
            ]

        repeated_unrotated, _metadata = subtitles._render_art_word_unrotated(
            text, font_path, 48
        )
        self.assertEqual(normal_unrotated.tobytes(), repeated_unrotated.tobytes())
        self.assertNotEqual(
            (normal_unrotated.size, row_alpha_sums(normal_unrotated)),
            (flat_unrotated.size, row_alpha_sums(flat_unrotated)),
        )
        self.assertNotEqual(normal_final.tobytes(), flat_final.tobytes())
        self.assertEqual(normal_metadata["baseline_offsets"], [0, -4, 3, -2, 4, -3])
        self.assertEqual(flat_metadata["baseline_offsets"], [0] * len(text))

    def test_validate_and_render_trims_unicode_whitespace_from_emphasis(self) -> None:
        from edit.hd.tools import subtitles

        cases = (
            ("　强调中文", "　强调", "强调"),
            ("中文强调　", "强调　", "强调"),
            ("中文　强调　内容", "　强调　", "强调"),
        )
        for text, candidate, expected in cases:
            with self.subTest(candidate=candidate):
                plan = _plan()
                plan["cues"][0]["text"] = text
                plan["cues"][0]["emphasis_words"] = [candidate]
                cues = subtitles.validate_subtitle_plan(plan)["cues"]
                with mock.patch.object(
                    subtitles, "_render_art_word", wraps=subtitles._render_art_word,
                ) as art_word:
                    frame = subtitles.render_subtitle_frame(cues, 0.4)
                art_word.assert_called_once()
                self.assertEqual(art_word.call_args.args[0], expected)
                self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_validate_and_render_trims_ascii_whitespace_from_emphasis(self) -> None:
        from edit.hd.tools import subtitles

        cases = (
            (" body copy", " body", "body"),
            ("body copy ", "body ", "body"),
            ("copy body text", " body ", "body"),
        )
        for text, candidate, expected in cases:
            with self.subTest(candidate=candidate):
                plan = _plan()
                plan["cues"][0]["text"] = text
                plan["cues"][0]["emphasis_words"] = [candidate]
                cues = subtitles.validate_subtitle_plan(plan)["cues"]
                with mock.patch.object(
                    subtitles, "_render_art_word", wraps=subtitles._render_art_word,
                ) as art_word:
                    frame = subtitles.render_subtitle_frame(cues, 0.4)
                art_word.assert_called_once()
                self.assertEqual(art_word.call_args.args[0], expected)
                self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_all_whitespace_emphasis_candidates_fall_back_to_first_visible_word(self) -> None:
        from edit.hd.tools import subtitles

        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "  fallback body",
            "emphasis_words": ["   ", "　"], "safe_zones": _zones(),
            "box": {"x": 120, "y": 1600, "width": 840, "height": 180},
        }
        with mock.patch.object(
            subtitles, "_render_art_word", wraps=subtitles._render_art_word,
        ) as art_word:
            frame = subtitles.render_subtitle_frame([cue], 0.5)
        art_word.assert_called_once()
        self.assertEqual(art_word.call_args.args[0], "fallback")
        self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_repeated_frames_reuse_cached_layout_and_art_template(self) -> None:
        from edit.hd.tools import subtitles

        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "缓存强调正文",
            "emphasis_words": ["强调"], "safe_zones": _zones(),
            "box": {"x": 120, "y": 1600, "width": 840, "height": 180},
        }
        subtitles._cached_art_word_layout.cache_clear()
        subtitles._cached_art_word_template.cache_clear()
        with mock.patch.object(
            subtitles, "_compute_art_word_layout",
            wraps=subtitles._compute_art_word_layout,
        ) as layout_compute, mock.patch.object(
            subtitles, "_render_art_word_unrotated",
            wraps=subtitles._render_art_word_unrotated,
        ) as unrotated:
            entering = subtitles.render_subtitle_frame([cue], 0.12)
            middle = subtitles.render_subtitle_frame([cue], 0.5)
            leaving = subtitles.render_subtitle_frame([cue], 0.98)

        self.assertEqual(layout_compute.call_count, 1)
        self.assertEqual(unrotated.call_count, 1)
        self.assertIsNot(entering, middle)
        self.assertIsNot(middle, leaving)
        self.assertEqual(entering.convert("RGB").tobytes(), middle.convert("RGB").tobytes())
        self.assertEqual(leaving.convert("RGB").tobytes(), middle.convert("RGB").tobytes())
        alpha_sums = [
            sum(frame.getchannel("A").getdata())
            for frame in (entering, middle, leaving)
        ]
        self.assertGreater(alpha_sums[1], alpha_sums[0])
        self.assertGreater(alpha_sums[1], alpha_sums[2])
        self.assertLessEqual(subtitles._cached_art_word_layout.cache_info().maxsize, 2048)
        self.assertLessEqual(subtitles._cached_art_word_template.cache_info().maxsize, 2048)

    def test_art_word_cache_returns_isolated_image_and_metadata_copies(self) -> None:
        from edit.hd.tools import subtitles

        text = "缓存副本"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        subtitles._cached_art_word_template.cache_clear()
        with mock.patch.object(
            subtitles, "_render_art_word_unrotated",
            wraps=subtitles._render_art_word_unrotated,
        ) as unrotated:
            first, first_metadata = subtitles._render_art_word(text, font_path, 48)
            original_pixel = first.getpixel((0, 0))
            first.putpixel((0, 0), (1, 2, 3, 4))
            first_metadata["glyph_rotations"].append(9)
            first_metadata["baseline_offsets"].append(9)
            second, second_metadata = subtitles._render_art_word(text, font_path, 48)

        self.assertEqual(unrotated.call_count, 1)
        self.assertEqual(second.getpixel((0, 0)), original_pixel)
        self.assertEqual(second_metadata["glyph_rotations"], [0] * len(text))
        self.assertEqual(len(second_metadata["baseline_offsets"]), len(text))

    def test_layout_and_art_cache_keys_separate_all_render_inputs(self) -> None:
        from edit.hd.tools import subtitles

        text = "缓存强调正文"
        font_path = subtitles.bold_subtitles.find_cjk_font(text)
        box = {"x": 120, "y": 1600, "width": 840, "height": 180}
        with tempfile.TemporaryDirectory() as directory:
            alternate_font = Path(directory) / "alternate-cjk.ttf"
            shutil.copyfile(font_path, alternate_font)
            layout_variants = (
                (text, "强调", font_path, box, "emphasis"),
                (text + "甲", "强调", font_path, box, "emphasis"),
                (text, "正文", font_path, box, "emphasis"),
                (text, "强调", alternate_font, box, "emphasis"),
                (text, "强调", font_path, {**box, "x": 121}, "emphasis"),
                (text, "强调", font_path, {**box, "y": 1601}, "emphasis"),
                (text, "强调", font_path, {**box, "width": 839}, "emphasis"),
                (text, "强调", font_path, {**box, "height": 181}, "emphasis"),
                (text, "强调", font_path, box, "statement"),
            )
            subtitles._cached_art_word_layout.cache_clear()
            with mock.patch.object(
                subtitles, "_compute_art_word_layout",
                wraps=subtitles._compute_art_word_layout,
            ) as layout_compute:
                for arguments in layout_variants:
                    subtitles._layout_text_with_art_word(*arguments)
                for arguments in layout_variants:
                    subtitles._layout_text_with_art_word(*arguments)
            self.assertEqual(layout_compute.call_count, len(layout_variants))

            subtitles._cached_art_word_template.cache_clear()
            art_variants = (
                ("缓存", font_path, 48),
                ("副本", font_path, 48),
                ("缓存", alternate_font, 48),
                ("缓存", font_path, 49),
            )
            with mock.patch.object(
                subtitles, "_render_art_word_unrotated",
                wraps=subtitles._render_art_word_unrotated,
            ) as unrotated:
                first_pass = [subtitles._render_art_word(*args) for args in art_variants]
                second_pass = [subtitles._render_art_word(*args) for args in art_variants]
        self.assertEqual(unrotated.call_count, len(art_variants))
        self.assertEqual(
            [image.tobytes() for image, _metadata in first_pass],
            [image.tobytes() for image, _metadata in second_pass],
        )

    def test_only_first_emphasis_word_present_in_text_is_warm_yellow(self) -> None:
        from edit.hd.tools import subtitles

        cues = [{
            "id": "cue-001", "type": "statement", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "流程决定结果流程",
            "emphasis_words": ["不存在", "流程", "结果"],
            "safe_zones": _zones(),
            "box": {"x": 120, "y": 1600, "width": 840, "height": 180},
        }]
        calls = []
        original = ImageDraw.ImageDraw.text

        def capture(draw, xy, value, *args, **kwargs):
            calls.append((value, kwargs.get("fill")))
            return original(draw, xy, value, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, "text", new=capture):
            subtitles.render_subtitle_frame(cues, 0.5)
        yellow_fragments = [
            value for value, fill in calls if fill == subtitles.WARM_YELLOW
        ]
        white_fragments = [
            value for value, fill in calls if fill == subtitles.WHITE
        ]
        self.assertEqual("".join(yellow_fragments), "流程")
        self.assertNotIn("流程", white_fragments)
        self.assertEqual("".join(white_fragments).replace(" ", ""), "决定结果流程")

    def test_body_does_not_draw_emphasis_under_art_word(self) -> None:
        from edit.hd.tools import subtitles

        text = "流程决定结果"
        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": text,
            "emphasis_words": ["流程", "结果"],
            "safe_zones": _zones(),
            "box": {"x": 120, "y": 1600, "width": 840, "height": 180},
        }
        calls = []
        original = ImageDraw.ImageDraw.text

        def capture(draw, xy, value, *args, **kwargs):
            calls.append((value, kwargs, draw._image.size))
            return original(draw, xy, value, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, "text", new=capture), mock.patch.object(
            subtitles, "_render_art_word", wraps=subtitles._render_art_word,
        ) as art_word:
            subtitles.render_subtitle_frame([cue], 0.5)
        bases = [call for call in calls if call[1].get("fill") == subtitles.WHITE]
        highlights = [
            call for call in calls if call[1].get("fill") == subtitles.WARM_YELLOW
        ]
        art_word.assert_called_once()
        self.assertEqual(art_word.call_args.args[0], "流程")
        self.assertTrue(bases)
        self.assertTrue(all("流程" not in value for value, _kwargs, _size in bases))
        self.assertEqual("".join(value for value, _kwargs, _size in bases), "决定结果")
        self.assertEqual("".join(value for value, _kwargs, _size in highlights), "流程")
        self.assertTrue(all(size != (1080, 1920) for _value, _kwargs, size in highlights))
        self.assertEqual(len({size for _value, _kwargs, size in highlights}), 1)
        self.assertTrue(
            all(kwargs.get("stroke_width", 0) <= 2 for _value, kwargs, _size in calls)
        )

    def test_cross_line_emphasis_becomes_one_complete_art_word_group(self) -> None:
        from edit.hd.tools import subtitles
        from edit.v5.tools import bold_subtitles

        text = "AI 模型 正在 改变 工作"
        emphasis = "正在 改变"
        box = {"x": 340, "y": 1600, "width": 400, "height": 180}
        font_path = bold_subtitles.find_cjk_font(text)
        layout = subtitles._layout_text_for_box(
            text, font_path, box, "emphasis"
        )
        self.assertEqual(len(layout["lines"]), 2)
        self.assertEqual(
            "".join(text[start:end] for start, end in layout["line_spans"]),
            text,
        )
        boundary = layout["line_spans"][0][1]
        emphasis_start = text.index(emphasis)
        self.assertLess(emphasis_start, boundary)
        self.assertLess(boundary, emphasis_start + len(emphasis))

        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": text,
            "emphasis_words": [emphasis, "工作"],
            "safe_zones": _zones(), "box": box,
        }
        calls = []
        original = ImageDraw.ImageDraw.text
        subtitles._cached_art_word_template.cache_clear()

        def capture(draw, xy, value, *args, **kwargs):
            calls.append((value, kwargs.get("fill"), draw._image.size))
            return original(draw, xy, value, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, "text", new=capture), mock.patch.object(
            subtitles, "_render_art_word", wraps=subtitles._render_art_word,
        ) as art_word:
            frame = subtitles.render_subtitle_frame([cue], 0.5)
        art_word.assert_called_once()
        self.assertEqual(art_word.call_args.args[0], emphasis)
        self.assertEqual(
            "".join(value for value, fill, _size in calls if fill == subtitles.WARM_YELLOW),
            emphasis,
        )
        yellow_sizes = {
            size for _value, fill, size in calls if fill == subtitles.WARM_YELLOW
        }
        self.assertEqual(len(yellow_sizes), 1)
        self.assertNotIn((1080, 1920), yellow_sizes)
        self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_art_word_stays_inside_subtitle_box_and_safe_zones(self) -> None:
        from edit.hd.tools import subtitles

        box = {"x": 340, "y": 1600, "width": 400, "height": 180}
        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "AI 模型 正在 改变 工作",
            "emphasis_words": ["正在 改变"], "safe_zones": _zones(), "box": box,
        }
        cue["safe_zones"]["subtitle"] = dict(box)
        frame = subtitles.render_subtitle_frame([cue], 0.5)
        alpha = frame.getchannel("A")
        bbox = alpha.getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[0], box["x"])
        self.assertGreaterEqual(bbox[1], box["y"])
        self.assertLessEqual(bbox[2], box["x"] + box["width"])
        self.assertLessEqual(bbox[3], box["y"] + box["height"])
        outside = Image.new("L", alpha.size, 255)
        ImageDraw.Draw(outside).rectangle(
            (box["x"], box["y"], box["x"] + box["width"] - 1,
             box["y"] + box["height"] - 1),
            fill=0,
        )
        self.assertIsNone(Image.composite(alpha, Image.new("L", alpha.size), outside).getbbox())
        for name in ("face", "source", "chart"):
            zone = cue["safe_zones"][name]
            self.assertIsNone(alpha.crop((
                zone["x"], zone["y"], zone["x"] + zone["width"],
                zone["y"] + zone["height"],
            )).getbbox(), name)

    def test_layout_never_exceeds_two_lines(self) -> None:
        from edit.hd.tools import subtitles
        from edit.v5.tools import bold_subtitles

        text = "这是用于验证字幕两行限制的完整中文句子"
        font_path = bold_subtitles.find_cjk_font(text)
        layout = subtitles._layout_text_for_box(
            text,
            font_path,
            {"x": 120, "y": 1600, "width": 840, "height": 180},
            "emphasis",
        )
        self.assertLessEqual(len(layout["lines"]), 2)

    def test_every_cue_type_is_magazine_caption_and_respects_protected_geometry(self) -> None:
        from edit.hd.tools import subtitles

        plan = subtitles.validate_subtitle_plan(_plan())
        rails = []
        rectangle = ImageDraw.ImageDraw.rectangle

        def capture_rail(draw, xy, *args, **kwargs):
            rails.append((xy, kwargs))
            return rectangle(draw, xy, *args, **kwargs)

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                ImageDraw.ImageDraw, "rectangle", new=capture_rail,
            ))
            for method in ("ellipse", "line", "polygon", "rounded_rectangle"):
                stack.enter_context(mock.patch.object(
                    ImageDraw.ImageDraw,
                    method,
                    side_effect=AssertionError(f"decoration: {method}"),
                ))
            for cue in plan["cues"]:
                frame = subtitles.render_subtitle_frame(
                    plan["cues"], (cue["start"] + cue["end"]) / 2
                )
                self.assertEqual(frame.mode, "RGBA")
                alpha = frame.getchannel("A")
                bbox = alpha.getbbox()
                self.assertIsNotNone(bbox)
                self.assertTrue(any(
                    xy[0] == cue["box"]["x"]
                    and round(xy[2] - xy[0] + 1) == 3
                    and kwargs.get("fill") == subtitles.WARM_YELLOW
                    for xy, kwargs in rails
                ))
                for name in ("face", "source", "chart"):
                    zone = cue["safe_zones"][name]
                    crop = alpha.crop(
                        (zone["x"], zone["y"], zone["x"] + zone["width"], zone["y"] + zone["height"])
                    )
                    self.assertIsNone(crop.getbbox(), name)
                self.assertIsNone(alpha.crop((0, 1800, 1080, 1920)).getbbox())

    def test_cue_fades_scale_only_whole_rgba_alpha_and_short_opacity_is_bounded(self) -> None:
        from edit.hd.tools import subtitles

        cue = {
            "id": "cue-001", "type": "emphasis", "segment_id": "seg-001",
            "start": 0.1, "end": 1.0, "text": "流程决定结果",
            "emphasis_words": ["流程"], "safe_zones": _zones(),
            "box": {"x": 120, "y": 1600, "width": 840, "height": 180},
        }
        entering = subtitles.render_subtitle_frame([cue], cue["start"] + 1 / 24)
        middle = subtitles.render_subtitle_frame([cue], (cue["start"] + cue["end"]) / 2)
        leaving = subtitles.render_subtitle_frame([cue], cue["end"] - 1 / 24)
        self.assertEqual(
            entering.convert("RGB").tobytes(), middle.convert("RGB").tobytes()
        )
        self.assertEqual(
            leaving.convert("RGB").tobytes(), middle.convert("RGB").tobytes()
        )
        alpha_sums = [
            sum(frame.getchannel("A").getdata())
            for frame in (entering, middle, leaving)
        ]
        self.assertGreater(alpha_sums[1], alpha_sums[0])
        self.assertGreater(alpha_sums[1], alpha_sums[2])

        short = {**cue, "start": 0.2, "end": 0.25}
        opacities = [
            subtitles._cue_opacity(short, timestamp)
            for timestamp in (0.19, 0.2, 0.21, 0.225, 0.24, 0.25, 0.26)
        ]
        self.assertTrue(all(0.0 <= opacity <= 1.0 for opacity in opacities))
        self.assertEqual(opacities[3], 1.0)
        self.assertIsNotNone(
            subtitles.render_subtitle_frame([short], 0.21).getchannel("A").getbbox()
        )

    def test_first_and_last_seek_frames_are_fully_transparent(self) -> None:
        from edit.hd.tools import subtitles

        cues = _plan()["cues"]
        self.assertIsNone(subtitles.render_subtitle_frame(cues, 0.0).getchannel("A").getbbox())
        self.assertIsNone(
            subtitles.render_subtitle_frame(cues, 2.0 - 1 / 24).getchannel("A").getbbox()
        )

    def test_public_v5_encoder_produces_real_complete_vp9_alpha(self) -> None:
        from edit.hd.tools import subtitles
        from edit.v5.tools import bold_subtitles

        plan = _plan()
        for index, cue in enumerate(plan["cues"]):
            cue["end"] = (
                plan["cues"][index + 1]["start"]
                if index + 1 < len(plan["cues"])
                else 1.95
            )
        cues = subtitles.validate_subtitle_plan(plan)["cues"]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "subtitles.webm"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                bold_subtitles.encode_webm(
                    cues,
                    descriptor,
                    2.0,
                    frame_renderer=subtitles.render_subtitle_frame,
                )
                info = bold_subtitles.validate_webm_fd(descriptor, 48)
            finally:
                os.close(descriptor)
            self.assertEqual(
                info,
                {
                    "codec": "vp9", "width": 1080, "height": 1920,
                    "fps": 24, "frames": 48, "alpha_min": 0, "alpha_max": 255,
                },
            )


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
class SubtitleStageTests(unittest.TestCase):
    @contextlib.contextmanager
    def _rendering(self):
        from edit.hd.tools import subtitles, subtitles_v2, talkcraft_subtitles

        def encode(
            _cues: object,
            descriptor: int,
            _duration: float,
            **_kwargs: object,
        ) -> None:
            os.write(descriptor, b"subtitle-video")

        def encode_empty(descriptor: int, _frames: int) -> None:
            os.write(descriptor, b"empty-subtitle-video")

        def render(_renderer_input: object, descriptor: int) -> None:
            os.write(descriptor, b"subtitle-video")

        with mock.patch.object(
            subtitles.bold_subtitles,
            "encode_webm",
            side_effect=encode,
        ), mock.patch.object(
            subtitles.bold_subtitles,
            "validate_webm_fd",
            return_value={},
        ), mock.patch.object(
            subtitles,
            "_encode_transparent_webm_fd",
            side_effect=encode_empty,
        ), mock.patch.object(
            subtitles,
            "_validate_transparent_webm_fd",
        ), mock.patch.object(
            subtitles,
            "_verify_rendered_geometry",
        ), mock.patch.object(
            subtitles,
            "_contact_sheet",
            return_value=b"\x89PNG\r\n\x1a\n",
        ), mock.patch.object(
            talkcraft_subtitles,
            "render",
            side_effect=render,
        ), mock.patch.object(
            talkcraft_subtitles,
            "verify_geometry",
        ), mock.patch.object(
            subtitles_v2,
            "_validate_generation",
            side_effect=lambda directory, _records=None: json.loads(
                (directory / "subtitle-plan.json").read_text(encoding="utf-8")
            ),
            create=True,
        ):
            yield

    def test_legacy_render_edit_feeds_subtitles_with_each_local_adapter(
        self,
    ) -> None:
        from edit.hd.tools import contract_artifacts, subtitles

        for has_deletion, expected_adapter in (
            (False, "local-ffmpeg-no-cut"),
            (True, "local-ffmpeg-trim-concat"),
        ):
            with self.subTest(has_deletion=has_deletion), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job, _track = _ready_job(
                    Path(directory),
                    routes=("arroll",),
                    render_deletion=has_deletion,
                )
                timeline = contract_artifacts.read_json_artifact(
                    job.job_dir / "03-edit-structure/timeline-map.json"
                )
                self.assertEqual(timeline["render_adapter"], expected_adapter)

                with self._rendering(), mock.patch.object(
                    subtitles.visual_plan_module,
                    "validate_visual_plan",
                    side_effect=lambda value: value,
                ):
                    output = subtitles.prepare_subtitles(job)

                self.assertTrue(output.is_file())
                self.assertEqual(
                    job.stages["subtitles"]["status"], "ready_for_review"
                )

    def test_old_visual_plan_is_rejected_without_subtitle_publication(self) -> None:
        from edit.hd.tools import subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_job(Path(directory))
            before_stage = copy.deepcopy(job.stages["subtitles"])
            before_revision = job.revision

            with self.assertRaises(subtitles.SubtitleError):
                subtitles.prepare_subtitles(job)

            self.assertEqual(job.stages["subtitles"], before_stage)
            self.assertEqual(job.revision, before_revision)
            self.assertFalse((job.job_dir / "06-subtitles").exists())

    def test_v3_aroll_plan_publishes_bound_subtitles_without_changing_visual_track(
        self,
    ) -> None:
        from edit.hd.tools import contract_artifacts, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, track = _ready_v2_job(Path(directory))
            track_before = (
                contract_artifacts.sha256_file(track),
                track.stat().st_size,
            )
            with self._rendering():
                output = subtitles.prepare_subtitles(job)

            self.assertEqual(output, job.job_dir / "10-subtitles/subtitles.webm")
            self.assertEqual(
                job.stages["subtitles"]["status"],
                "ready_for_review",
            )
            wrapper = contract_artifacts.read_json_artifact(
                job.job_dir / "10-subtitles/subtitle-plan.json"
            )
            render_plan = wrapper["render_plan"]
            self.assertTrue(render_plan["cues"])
            self.assertEqual(
                {cue["segment_id"] for cue in render_plan["cues"]},
                {"seg-001"},
            )
            self.assertEqual(
                render_plan["source_bindings"]["visual_track"],
                next(
                    record
                    for record in job.stages["visual_assets"]["artifacts"]
                    if record["path"] == "09-visual-assets/visual-track.mp4"
                ),
            )
            self.assertEqual(
                (
                    contract_artifacts.sha256_file(track),
                    track.stat().st_size,
                ),
                track_before,
            )
            self.assertEqual(
                subtitles.parse_srt(
                    (output.parent / "subtitles.srt").read_text(encoding="utf-8")
                ),
                [
                    (cue["start"], cue["end"], cue["text"])
                    for cue in render_plan["cues"]
                ],
            )

    def test_v3_broll_plan_publishes_an_empty_regular_subtitle_track(self) -> None:
        from edit.hd.tools import contract_artifacts, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(
                Path(directory),
                kinds=("code_generated",),
            )
            with self._rendering():
                subtitles.prepare_subtitles(job)

            wrapper = contract_artifacts.read_json_artifact(
                job.job_dir / "10-subtitles/subtitle-plan.json"
            )
            self.assertEqual(wrapper["render_plan"]["cues"], [])
            self.assertEqual(
                (job.job_dir / "10-subtitles/subtitles.srt").read_bytes(),
                b"",
            )

    def test_v3_input_byte_change_stops_before_subtitle_rendering(self) -> None:
        from edit.hd.tools import state, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, track = _ready_v2_job(Path(directory))
            track.write_bytes(b"changed-visual-track")
            encoder = mock.Mock(
                side_effect=AssertionError("subtitle render must not start")
            )

            with mock.patch.object(
                subtitles.bold_subtitles,
                "encode_webm",
                encoder,
            ), self.assertRaises(state.WorkflowError):
                subtitles.prepare_subtitles(job)

            encoder.assert_not_called()
            self.assertFalse((job.job_dir / "10-subtitles").exists())
            self.assertEqual(job.stages["subtitles"]["status"], "pending")

    def test_v3_pending_publication_records_all_four_outputs(self) -> None:
        from edit.hd.tools import material_usage, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))
            with self._rendering():
                output = subtitles.prepare_subtitles(job)

            self.assertEqual(output, job.job_dir / "10-subtitles/subtitles.webm")
            self.assertEqual(job.stages["subtitles"]["status"], "ready_for_review")
            self.assertEqual(
                {record["path"] for record in job.stages["subtitles"]["artifacts"]},
                {
                    "10-subtitles/subtitle-plan.json",
                    "10-subtitles/subtitles.webm",
                    "10-subtitles/subtitles.srt",
                    "10-subtitles/material-usage.json",
                },
            )
            receipt = material_usage.load_current_receipt(job, "subtitles")
            self.assertEqual(receipt["references"], [])
            self.assertFalse(
                (job.job_dir / ".10-subtitles.transaction.json").exists()
            )

    def test_v3_mark_ready_failure_restores_previous_generation_and_workflow(self) -> None:
        from edit.hd.tools import state, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))
            with self._rendering():
                target = subtitles.prepare_subtitles(job).parent
            state.approve(job, "subtitles")
            state.revise(job, "subtitles", "重新生成字幕")
            old = {
                path.name: (os.stat(path), hashlib.sha256(path.read_bytes()).hexdigest())
                for path in target.iterdir()
            }
            workflow_before = (job.job_dir / "workflow.json").read_bytes()

            with self._rendering(), mock.patch.object(
                state,
                "mark_ready",
                side_effect=state.WorkflowError("workflow write stopped"),
            ), self.assertRaises(state.WorkflowError):
                subtitles.prepare_subtitles(job)

            self.assertEqual((job.job_dir / "workflow.json").read_bytes(), workflow_before)
            self.assertEqual(job.stages["subtitles"]["status"], "needs_revision")
            self.assertEqual({path.name for path in target.iterdir()}, set(old))
            for path in target.iterdir():
                self.assertTrue(os.path.samestat(old[path.name][0], os.stat(path)))
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), old[path.name][1]
                )

    @unittest.skipUnless(os.environ.get("HD_SUBTITLE_MEDIA_TEST") == "1", "explicit serial media test")
    def test_v3_real_media_recovery_preserves_terminology_report(self) -> None:
        from edit.hd.tools import subtitles, subtitles_v2, state

        scenarios = [(False, name) for name in ("before-install", "after-install", "after-workflow")]
        scenarios += [(True, name) for name in ("before-install", "after-backup", "after-install", "after-workflow")]
        for replacement, checkpoint in scenarios:
            with self.subTest(replacement=replacement, checkpoint=checkpoint), tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
                job, _track = _ready_v2_job(Path(directory))
                old_records = None
                if replacement:
                    subtitles.prepare_subtitles(job)
                    old_stats = {path.name: path.stat() for path in (job.job_dir / "10-subtitles").iterdir()}
                    old_records = copy.deepcopy(job.stages["subtitles"]["artifacts"])
                    state.revise(job, "subtitles", "synthetic recovery test")
                    job = state.load_job(job.job_dir)
                    old_lineage = copy.deepcopy(job.stages["subtitles"]["lineage"])
                    self.assertEqual(
                        [{k: record[k] for k in ("path", "sha256", "bytes")} for record in old_lineage],
                        old_records)
                def stop(name):
                    if name == checkpoint:
                        raise KeyboardInterrupt(checkpoint)
                with mock.patch.object(subtitles_v2, "_checkpoint", side_effect=stop):
                    with self.assertRaises(KeyboardInterrupt):
                        subtitles.prepare_subtitles(job)
                journal = subtitles_v2._load_transaction(job)
                self.assertIsNotNone(journal)
                self.assertEqual(journal["had_target"], replacement)
                if replacement:
                    self.assertEqual(journal["old_records"], old_lineage)
                    self.assertEqual(
                        [{k: record[k] for k in ("path", "sha256", "bytes")} for record in journal["old_records"]],
                        old_records)
                if checkpoint == "after-backup":
                    self.assertTrue((job.job_dir / journal["backup"]).is_dir())
                    self.assertFalse((job.job_dir / "10-subtitles").exists())
                original_records = copy.deepcopy(journal["new_records"])
                new_directory = job.job_dir / (journal["stage"] if checkpoint in {"before-install", "after-backup"} else "10-subtitles")
                new_stats = {path.name: path.stat() for path in new_directory.iterdir()}
                with mock.patch.object(subtitles.bold_subtitles, "encode_webm",
                                       side_effect=AssertionError("must not re-encode")):
                    output = subtitles.prepare_subtitles(state.load_job(job.job_dir))
                current = state.load_job(job.job_dir)
                self.assertEqual(current.stages["subtitles"]["status"], "ready_for_review")
                self.assertEqual(current.stages["subtitles"]["artifacts"], original_records)
                self.assertTrue(output.is_file())
                for name, expected_stat in new_stats.items():
                    actual_stat = (output.parent / name).stat()
                    self.assertTrue(os.path.samestat(expected_stat, actual_stat))
                    if replacement:
                        self.assertFalse(os.path.samestat(old_stats[name], actual_stat))
                review = subtitles_v2.review_subtitles(current)
                self.assertEqual(review["terminology_status"], "available")
                self.assertFalse(review["terminology_review"]["automatic_replacement"])
                self.assertEqual(review["terminology_review"]["history_binding"], next(
                    record for record in current.stages["speech_cleanup"]["artifacts"]
                    if record["path"].endswith("/diff-summary.json")))
                self.assertIsNone(subtitles_v2._load_transaction(current))
                self.assertFalse((job.job_dir / journal["backup"]).exists())
                self.assertFalse((job.job_dir / journal["stage"]).exists())

    def test_v3_install_interruption_recovers_without_rendering_again(self) -> None:
        from edit.hd.tools import contract_artifacts, subtitles, subtitles_v2

        for checkpoint in ("before-install", "after-install", "after-workflow"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job, _track = _ready_v2_job(Path(directory))

                def stop(name: str) -> None:
                    if name == checkpoint:
                        raise KeyboardInterrupt(checkpoint)

                with self._rendering(), mock.patch.object(
                    subtitles_v2, "_checkpoint", side_effect=stop, create=True
                ), self.assertRaises(KeyboardInterrupt):
                    subtitles.prepare_subtitles(job)

                self.assertTrue(
                    (job.job_dir / ".10-subtitles.transaction.json").is_file()
                )
                with mock.patch.object(
                    subtitles.bold_subtitles,
                    "encode_webm",
                    side_effect=AssertionError("recovery must reuse the rendered files"),
                ), mock.patch.object(
                    subtitles_v2,
                    "_validate_generation",
                    side_effect=lambda directory, _records=None: (
                        contract_artifacts.read_json_artifact(
                            directory / "subtitle-plan.json"
                        )
                    ),
                    create=True,
                ):
                    output = subtitles.prepare_subtitles(job)

                self.assertTrue(output.is_file())
                self.assertEqual(
                    job.stages["subtitles"]["status"], "ready_for_review"
                )
                self.assertFalse(
                    (job.job_dir / ".10-subtitles.transaction.json").exists()
                )

    def test_v3_recovery_can_be_interrupted_and_retried(self) -> None:
        from edit.hd.tools import subtitles, subtitles_v2

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))

            def stop_after_install(name: str) -> None:
                if name == "after-install":
                    raise KeyboardInterrupt(name)

            with self._rendering(), mock.patch.object(
                subtitles_v2, "_checkpoint", side_effect=stop_after_install, create=True
            ), self.assertRaises(KeyboardInterrupt):
                subtitles.prepare_subtitles(job)

            with mock.patch.object(
                subtitles.bold_subtitles,
                "encode_webm",
                side_effect=AssertionError("recovery must not render"),
            ), mock.patch.object(
                subtitles_v2, "_validate_generation", return_value=None, create=True
            ), mock.patch.object(
                subtitles_v2, "_checkpoint", side_effect=stop_after_install, create=True
            ), self.assertRaises(KeyboardInterrupt):
                subtitles.prepare_subtitles(job)

            with mock.patch.object(
                subtitles.bold_subtitles,
                "encode_webm",
                side_effect=AssertionError("retry must not render"),
            ), mock.patch.object(
                subtitles_v2, "_validate_generation", return_value=None, create=True
            ):
                output = subtitles.prepare_subtitles(job)

            self.assertTrue(output.is_file())
            self.assertEqual(job.stages["subtitles"]["status"], "ready_for_review")

    def test_v3_interruption_after_backup_recovers_previous_revision(self) -> None:
        from edit.hd.tools import state, subtitles, subtitles_v2

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))
            with self._rendering():
                subtitles.prepare_subtitles(job)
            state.approve(job, "subtitles")
            state.revise(job, "subtitles", "重新生成字幕")

            def stop_after_backup(name: str) -> None:
                if name == "after-backup":
                    raise KeyboardInterrupt(name)

            with self._rendering(), mock.patch.object(
                subtitles_v2, "_checkpoint", side_effect=stop_after_backup
            ), self.assertRaises(KeyboardInterrupt):
                subtitles.prepare_subtitles(job)

            self.assertFalse((job.job_dir / "10-subtitles").exists())
            self.assertEqual(len(list(job.job_dir.glob(".10-subtitles.backup-*"))), 1)
            with mock.patch.object(
                subtitles.bold_subtitles,
                "encode_webm",
                side_effect=AssertionError("recovery must not render"),
            ), mock.patch.object(
                subtitles_v2, "_validate_generation", return_value=None
            ):
                output = subtitles.prepare_subtitles(job)

            self.assertTrue(output.is_file())
            self.assertEqual(job.stages["subtitles"]["status"], "ready_for_review")

    def test_v3_ready_and_approved_reuse_returns_validated_generation(self) -> None:
        from edit.hd.tools import contract_artifacts, state, subtitles, subtitles_v2

        for approved in (False, True):
            with self.subTest(approved=approved), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job, _track = _ready_v2_job(Path(directory))
                with self._rendering():
                    first = subtitles.prepare_subtitles(job)
                    if approved:
                        state.approve(job, "subtitles")
                    with mock.patch.object(
                        subtitles.bold_subtitles,
                        "encode_webm",
                        side_effect=AssertionError("reuse must not render"),
                    ), mock.patch.object(
                        subtitles_v2,
                        "_validate_generation",
                        side_effect=lambda directory, _records=None: (
                            contract_artifacts.read_json_artifact(
                                directory / "subtitle-plan.json"
                            )
                        ),
                    ):
                        second = subtitles.prepare_subtitles(job)
                self.assertEqual(second, first)
                self.assertFalse(
                    (job.job_dir / ".10-subtitles.transaction.json").exists()
                )

    def test_v3_revision_replaces_the_complete_generation_atomically(self) -> None:
        from edit.hd.tools import state, subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))
            with self._rendering():
                target = subtitles.prepare_subtitles(job).parent
            old = {path.name: os.stat(path) for path in target.iterdir()}
            state.approve(job, "subtitles")
            state.revise(job, "subtitles", "重新生成字幕")

            with self._rendering():
                second = subtitles.prepare_subtitles(job).parent

            self.assertEqual({path.name for path in second.iterdir()}, set(old))
            self.assertTrue(all(
                not os.path.samestat(old[path.name], os.stat(path))
                for path in second.iterdir()
            ))
            self.assertEqual(job.stages["subtitles"]["status"], "ready_for_review")

    def test_v3_review_reuse_revalidates_every_published_output(self) -> None:
        from edit.hd.tools import subtitles, subtitles_v2

        for name in (
            "subtitle-plan.json",
            "subtitles.webm",
            "subtitles.srt",
            "material-usage.json",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                dir=Path.cwd()
            ) as directory:
                job, _track = _ready_v2_job(Path(directory))
                with self._rendering():
                    output = subtitles.prepare_subtitles(job)
                    with (output.parent / name).open("ab") as stream:
                        stream.write(b"changed")
                    with self.assertRaises(subtitles_v2.SubtitlesV2Error):
                        subtitles.prepare_subtitles(job)

    def test_v3_approved_reuse_revalidates_state_and_upstream_records(self) -> None:
        from edit.hd.tools import state, subtitles, subtitles_v2

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, track = _ready_v2_job(Path(directory))
            with self._rendering():
                subtitles.prepare_subtitles(job)
            state.approve(job, "subtitles")
            job.stages["subtitles"]["artifacts"][0]["sha256"] = "0" * 64
            with self._rendering():
                subtitles.prepare_subtitles(job)
            self.assertNotEqual(job.stages["subtitles"]["artifacts"][0]["sha256"], "0" * 64)

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, track = _ready_v2_job(Path(directory))
            with self._rendering():
                subtitles.prepare_subtitles(job)
            state.approve(job, "subtitles")
            track.write_bytes(track.read_bytes() + b"changed")
            with self.assertRaises((subtitles_v2.SubtitlesV2Error, state.WorkflowError)):
                subtitles.prepare_subtitles(job)

    def test_v3_broll_uses_real_transparent_media_and_exact_sidecars(self) -> None:
        from edit.hd.tools import contract_artifacts, subtitles
        from edit.v5.tools import bold_subtitles

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(
                Path(directory), kinds=("code_generated",)
            )
            output = subtitles.prepare_subtitles(job)
            wrapper = contract_artifacts.read_json_artifact(
                output.parent / "subtitle-plan.json"
            )
            render_plan = wrapper["render_plan"]
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-count_frames", "-show_entries",
                    "stream=width,height,r_frame_rate,nb_read_frames",
                    "-of", "json", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(
                stream,
                {
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "24/1",
                    "nb_read_frames": "72",
                },
            )
            descriptor = os.open(output, os.O_RDONLY)
            try:
                subtitles._validate_transparent_webm_fd(descriptor, 72)
            finally:
                os.close(descriptor)
            self.assertEqual(render_plan["cues"], [])
            self.assertEqual((output.parent / "subtitles.srt").read_bytes(), b"")
            self.assertFalse((output.parent / "contact-sheet.png").exists())

    def test_v3_public_entry_serializes_two_job_snapshots_and_renders_once(self) -> None:
        from edit.hd.tools import (
            contract_artifacts,
            state,
            subtitles,
            subtitles_v2,
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            original, _track = _ready_v2_job(Path(directory))
            first_job = state.load_job(original.job_dir)
            second_job = state.load_job(original.job_dir)
            base_revision = first_job.revision
            encoder_entered = threading.Event()
            release_encoder = threading.Event()
            results: list[Path] = []
            errors: list[BaseException] = []

            def encode(
                _renderer_input: object,
                descriptor: int,
            ) -> None:
                encoder_entered.set()
                if not release_encoder.wait(timeout=5):
                    raise AssertionError("encoder release was not signaled")
                os.write(descriptor, b"subtitle-video")

            def validate(directory: Path, _records=None):
                return contract_artifacts.read_json_artifact(
                    directory / "subtitle-plan.json"
                )

            def run(job) -> None:
                try:
                    results.append(subtitles.prepare_subtitles(job))
                except BaseException as exc:
                    errors.append(exc)

            with self._rendering(), mock.patch.object(
                subtitles_v2.talkcraft_subtitles,
                "render",
                side_effect=encode,
            ) as encoder, mock.patch.object(
                subtitles_v2,
                "_validate_generation",
                side_effect=validate,
            ):
                first = threading.Thread(target=run, args=(first_job,))
                first.start()
                self.assertTrue(encoder_entered.wait(timeout=5))
                second = threading.Thread(target=run, args=(second_job,))
                second.start()
                release_encoder.set()
                first.join(timeout=10)
                second.join(timeout=10)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], results[1])
            self.assertEqual(encoder.call_count, 1)
            self.assertEqual(first_job.stages["subtitles"]["status"], "ready_for_review")
            self.assertEqual(second_job.stages["subtitles"]["status"], "ready_for_review")
            self.assertEqual(first_job.revision, base_revision + 1)
            self.assertEqual(second_job.revision, base_revision + 1)
            self.assertFalse(
                (original.job_dir / ".10-subtitles.transaction.json").exists()
            )
            self.assertEqual(list(original.job_dir.glob(".10-subtitles.stage-*")), [])
            self.assertEqual(list(original.job_dir.glob(".10-subtitles.backup-*")), [])

    def test_v3_journal_contention_does_not_leave_its_staging_directory(self) -> None:
        from edit.hd.tools import contract_artifacts, subtitles, subtitles_v2

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            job, _track = _ready_v2_job(Path(directory))
            marker = job.job_dir / ".10-subtitles.transaction.json"

            def report_contention(_job, _payload) -> None:
                contract_artifacts.write_json_artifact(
                    marker,
                    {"stage": ".10-subtitles.stage-another-writer"},
                )
                raise subtitles_v2.SubtitlesV2Error(
                    "subtitle publication is already in progress"
                )

            with self._rendering(), mock.patch.object(
                subtitles_v2,
                "_write_transaction",
                side_effect=report_contention,
            ), self.assertRaisesRegex(
                subtitles_v2.SubtitlesV2Error,
                "already in progress",
            ):
                subtitles.prepare_subtitles(job)

            self.assertEqual(list(job.job_dir.glob(".10-subtitles.stage-*")), [])
            self.assertTrue(marker.is_file())



if __name__ == "__main__":
    unittest.main()

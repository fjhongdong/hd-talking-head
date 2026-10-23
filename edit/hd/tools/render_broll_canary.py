"""Render and verify the native 9:16 five-shot B-roll canary reel."""

from __future__ import annotations

import argparse
import os
import json
import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

from edit.hd.tools import visual_assets


WIDTH = 1080
HEIGHT = 1920
FPS = 24
SHOT_COUNT = 5
SHOT_DURATION = 6
TOTAL_DURATION = SHOT_COUNT * SHOT_DURATION
HYPERFRAMES_VERSION = "0.7.104"
DEFAULT_HYPERFRAMES = Path(
    "/Users/Abner/Library/Application Support/erduo-hyperframes-broll/"
    "runtime/node_modules/.bin/hyperframes"
)
ROUTES = {"code", "official", "ai"}
AVATAR_POSITIONS = {"bottom-left", "bottom-right"}
BANNED_FILLER = {
    "主题", "关键值", "趋势", "结果", "提问", "对照", "反馈", "结论",
    "起点", "连接", "推进", "落点", "证据", "关联", "来源", "核心",
    "补充", "层级", "强调",
}
BALANCE_READY = (3.0, 3.0, 3.0, 2.7, 3.0)
PAYOFF_AT = (2.4, 2.4, 2.4, 2.1, 2.4)
_AVATAR_MEDIA_FILTER = (
    "fps=24,split=2[avatar_bg][avatar_fg];"
    "[avatar_bg]scale=240:240:force_original_aspect_ratio=increase:"
    "flags=lanczos,crop=240:240:(iw-ow)/2:(ih-oh)*0.34,"
    "gblur=sigma=12[avatar_bg_ready];"
    "[avatar_fg]scale=187:-2:flags=lanczos[avatar_fg_ready];"
    "[avatar_bg_ready][avatar_fg_ready]overlay=(W-w)/2:(H-h)*0.40,"
    "scale=in_range=full:out_range=tv,format=yuv420p,setparams=range=tv"
)


class CanaryError(RuntimeError):
    """A clean validation or rendering failure for the canary reel."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanaryError("canary specification contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CanaryError(f"canary specification contains invalid constant: {value}")


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _all_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_strings(item)]
    return []


def validate_spec(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CanaryError("canary specification must be an object")
    if (
        payload.get("version") != 1
        or payload.get("width") != WIDTH
        or payload.get("height") != HEIGHT
        or payload.get("fps") != FPS
        or payload.get("duration") != TOTAL_DURATION
    ):
        raise CanaryError("canary specification must be native 1080x1920 at 24fps")
    shots = payload.get("shots")
    if not isinstance(shots, list) or len(shots) != SHOT_COUNT:
        raise CanaryError("canary specification must contain exactly five shots")
    ids: set[str] = set()
    grammars: set[str] = set()
    expected_start = 0
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise CanaryError("each canary shot must be an object")
        identifier = shot.get("id")
        grammar = shot.get("grammar")
        route = shot.get("route")
        if (
            identifier != f"shot-{index:02d}"
            or identifier in ids
            or not isinstance(grammar, str)
            or not grammar.strip()
            or grammar in grammars
            or route not in ROUTES
            or shot.get("start") != expected_start
            or shot.get("duration") != SHOT_DURATION
            or shot.get("avatar") not in AVATAR_POSITIONS
        ):
            raise CanaryError("canary shot timing, identity, or grammar is invalid")
        if any("subtitle" in str(key).lower() for key in shot):
            raise CanaryError("B-roll canary shots may not contain subtitles")
        strings = [text.strip() for text in _all_strings(shot) if text.strip()]
        if any(text in BANNED_FILLER for text in strings):
            raise CanaryError("generic semantic filler is forbidden in canary shots")
        if route == "code":
            units = shot.get("units")
            if not isinstance(units, list) or len(units) < 4 or not all(
                isinstance(unit, str) and unit.strip() for unit in units
            ):
                raise CanaryError("code canary shots require four meaningful units")
        else:
            overlays = shot.get("overlays")
            if not isinstance(overlays, list) or not 1 <= len(overlays) <= 2:
                raise CanaryError("media canary shots require one or two overlays")
        for required in ("kicker", "title", "hero", "payoff", "motion_reason"):
            if not isinstance(shot.get(required), str) or not shot[required].strip():
                raise CanaryError(f"canary shot is missing {required}")
        ids.add(identifier)
        grammars.add(grammar)
        expected_start += SHOT_DURATION
    return payload


def load_spec(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except CanaryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CanaryError("cannot read canary specification") from error
    return validate_spec(payload)


ROOT = Path(__file__).resolve().parents[3]
CANARY_TEMPLATE = ROOT / "edit/hd/canary/index.template.html"


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryError("canary text value is invalid")
    return html.escape(value.strip(), quote=True)


def _media_attributes(
    shot: dict[str, Any], *, local: bool, track_index: int
) -> str:
    start = int(shot["start"])
    duration = int(shot["duration"])
    media_start = 0 if local else start
    clock = "local" if local else "global"
    return (
        f'data-start="{start}" data-duration="{duration}" '
        f'data-media-start="{media_start}" data-media-clock="{clock}" '
        f'data-track-index="{track_index}" muted playsinline preload="auto"'
    )


def _avatar(shot: dict[str, Any]) -> str:
    position = _text(shot["avatar"])
    identifier = _text(shot["id"])
    return (
        f'<div class="avatar-shell avatar-{position} avatar-{identifier}">'
        '<span class="avatar-pin"></span></div>'
    )


def _section_open(shot: dict[str, Any], number: int) -> str:
    balance_ready = BALANCE_READY[number - 1]
    payoff_at = PAYOFF_AT[number - 1]
    return (
        f'<section class="shot clip shot-{number:02d} route-{_text(shot["route"])}" '
        f'id="{_text(shot["id"])}" '
        f'data-grammar="{_text(shot["grammar"])}" data-system="{_text(shot["system"])}" '
        f'data-start="{shot["start"]}" data-duration="{shot["duration"]}" '
        f'data-track-index="{number}" data-balance-ready="{balance_ready:g}" '
        f'style="--payoff-at:{payoff_at:g}s">'
    )


def _shot_one(shot: dict[str, Any]) -> str:
    dots = "".join(
        f'<span style="--i:{index};--dot-opacity:{.25 if index < 6 else 1}"></span>'
        for index in range(30)
    )
    return (
        _section_open(shot, 1)
        + '<div class="survey-grain"></div>'
        + f'<header class="survey-head"><div class="kicker">{_text(shot["kicker"])}</div>'
        + f'<h1 data-source>{_text(shot["title"])}</h1></header>'
        + '<div class="survey-stage">'
        + '<div class="survey-half survey-left"><div class="survey-index">QUESTION 01</div>'
        + '<div class="survey-big" data-source>≈ 0</div>'
        + f'<div class="survey-copy" data-source>{_text(shot["units"][0])}</div>'
        + f'<div class="survey-detail" data-source>{_text(shot["units"][3])}</div>'
        + f'<div class="dot-field">{dots}</div></div>'
        + '<div class="survey-half survey-right"><div class="survey-index">QUESTION 02</div>'
        + '<div class="survey-big" data-source>多数</div>'
        + f'<div class="survey-copy" data-source>{_text(shot["units"][1])}</div>'
        + f'<div class="survey-detail" data-source>{_text(shot["units"][2])}</div>'
        + f'<div class="dot-field">{dots}</div></div><div class="survey-axis"></div></div>'
        + f'<div class="survey-payoff" data-source>认知矛盾<strong>{_text(shot["payoff"])}</strong></div>'
        + _avatar(shot) + '</section>'
    )


def _shot_two(shot: dict[str, Any]) -> str:
    stops = []
    stop_tops = (100, 390, 680, 970)
    stop_delays = (".82s", "1.34s", "1.92s", "2.54s")
    for index, (copy, top, delay) in enumerate(
        zip(shot["units"], stop_tops, stop_delays), start=1
    ):
        title, detail = copy.split("：", 1)
        stops.append(
            f'<div class="time-stop" style="top:{top}px;--at:{delay}">'
            f'<div class="time-no">0{index}</div><div class="time-card" data-source>'
            f'{_text(title)}<small>{_text(detail)}</small></div></div>'
        )
    return (
        _section_open(shot, 2)
        + '<div class="time-grid"></div><div class="time-glow"></div>'
        + f'<header class="time-head"><div class="kicker">{_text(shot["kicker"])}</div>'
        + f'<h1 data-source>能力在增长，<em>标准也在上移</em></h1></header>'
        + '<div class="timeline-window"><div class="timeline-world">'
        + '<div class="timeline-rail"></div>' + "".join(stops)
        + '</div><div class="finish-line"></div></div>'
        + f'<div class="time-payoff" data-source>{_text(shot["hero"])}'
        + f'<span>{_text(shot["payoff"])}</span></div>'
        + _avatar(shot) + '</section>'
    )


def _shot_three(shot: dict[str, Any]) -> str:
    source_tops = (92, 300, 670, 868)
    source_delays = (".58s", ".86s", "1.14s", "1.42s")
    path_delays = (".62s", ".90s", "1.18s", "1.46s")
    paths = (
        "M286 155 C430 155 350 455 520 545",
        "M286 363 C430 363 390 500 520 545",
        "M286 733 C430 733 390 590 520 545",
        "M286 931 C430 931 350 635 520 545",
    )
    source_nodes = []
    path_nodes = []
    packet_nodes = []
    for index, (copy, top, delay, path_delay, path) in enumerate(
        zip(shot["units"], source_tops, source_delays, path_delays, paths), start=1
    ):
        source_nodes.append(
            f'<div class="context-source" data-no="SOURCE 0{index}" '
            f'style="top:{top}px;--at:{delay}" data-source>{_text(copy)}</div>'
        )
        path_nodes.append(
            f'<path class="context-path" style="--at:{path_delay}" d="{path}" />'
        )
        packet_nodes.append(
            f'<span class="packet" style="--at:{2.0 + index * .22:.2f}s;'
            f'offset-path:path(\'{path}\')"></span>'
        )
    return (
        _section_open(shot, 3)
        + '<div class="context-paper"></div>'
        + f'<header class="context-head"><div class="kicker">{_text(shot["kicker"])}</div>'
        + f'<h1 data-source>{_text(shot["title"])}</h1></header>'
        + '<div class="context-map"><svg viewBox="0 0 968 1040" aria-hidden="true">'
        + "".join(path_nodes)
        + '<path class="context-output-path" d="M540 545 C700 545 690 820 828 820" />'
        + '</svg>' + "".join(source_nodes) + "".join(packet_nodes)
        + f'<div class="context-hub" data-source>{_text(shot["hub"])}</div>'
        + f'<div class="context-target" data-source>{_text(shot["target"])}</div></div>'
        + f'<div class="context-payoff" data-source>{_text(shot["payoff"])}</div>'
        + _avatar(shot) + '</section>'
    )


def _shot_four(shot: dict[str, Any]) -> str:
    return (
        _section_open(shot, 4)
        + '<div class="dossier-grid"></div>'
        + f'<header class="dossier-head"><div class="kicker">{_text(shot["kicker"])}</div>'
        + '<div class="dossier-index">04 / EVIDENCE</div>'
        + f'<h1 data-source>{_text(shot["title"])}</h1></header>'
        + '<div class="official-frame"></div>'
        + '<div class="scan-line"></div>'
        + '<div class="focus-bracket" style="left:350px;top:500px;width:360px;height:430px;--at:1.32s"></div>'
        + f'<div class="official-chip official-chip-source" style="--at:1.82s" data-source>{_text(shot["overlays"][0])}</div>'
        + f'<div class="official-chip official-chip-finding" style="--at:2.28s" data-source>{_text(shot["overlays"][1])}</div>'
        + f'<div class="official-meta" data-source><span>{_text(shot["hero"])}</span><span>{_text(shot["source"])}</span></div>'
        + '<div class="official-insight" data-source>'
        + '<div class="official-insight-label">讲师判断</div>'
        + f'<div class="official-insight-copy">{_text(shot["payoff"])}</div></div>'
        + _avatar(shot) + '</section>'
    )


def _shot_five(shot: dict[str, Any]) -> str:
    digits = "".join(f"<span>{index}</span>" for index in range(10))
    return (
        _section_open(shot, 5)
        + '<div class="ai-scrim"></div>'
        + f'<header class="ai-head"><div class="kicker">{_text(shot["kicker"])}</div>'
        + f'<h1 data-source>{_text(shot["title"])}</h1></header>'
        + '<div class="metric-journey">'
        + f'<div class="metric-from" data-source>{_text(shot["metrics"][0])}</div>'
        + '<div class="metric-arrow"></div>'
        + f'<div class="metric-to" data-source>{_text(shot["metrics"][1])}</div>'
        + '<div class="odometer-stage"><div class="digit-window"><div class="digit-strip">'
        + digits + '</div></div><div class="metric-unit">个</div></div>'
        + f'<div class="metric-label" data-source>{_text(shot["metrics"][2])}</div></div>'
        + f'<div class="ai-chip ai-chip-1" style="--at:2.15s" data-source>{_text(shot["overlays"][0])}</div>'
        + f'<div class="ai-chip ai-chip-2" style="--at:2.55s" data-source>{_text(shot["overlays"][1])}</div>'
        + f'<div class="ai-payoff" data-source>{_text(shot["payoff"])}</div>'
        + _avatar(shot) + '</section>'
    )


SHOT_BUILDERS = (_shot_one, _shot_two, _shot_three, _shot_four, _shot_five)


def _media_nodes(spec: dict[str, Any]) -> str:
    nodes = []
    for shot in spec["shots"]:
        identifier = _text(shot["id"])
        position = _text(shot["avatar"])
        nodes.append(
            f'<video id="media-avatar-{identifier}" '
            f'class="avatar-media-direct avatar-{position} avatar-{identifier} clip" '
            f'src="media/avatar.mp4" '
            f'{_media_attributes(shot, local=False, track_index=60)}></video>'
        )
    official = spec["shots"][3]
    nodes.append(
        '<video id="media-official-shot-04" class="official-media clip" '
        'src="media/official.mp4" '
        f'{_media_attributes(official, local=True, track_index=20)}></video>'
    )
    ai = spec["shots"][4]
    nodes.append(
        '<video id="media-ai-shot-05" class="ai-media clip" '
        'src="media/ai.mp4" '
        f'{_media_attributes(ai, local=True, track_index=20)}></video>'
    )
    return "".join(nodes)


def _canary_segment(shot: dict[str, Any]) -> dict[str, Any]:
    identifier = shot["id"]
    start = float(shot["start"])
    end = start + float(shot["duration"])
    route = shot["route"]
    body_values = list(shot.get("units") or shot.get("overlays") or [])
    number_values = list(shot.get("metrics") or [])
    if route == "ai":
        body_values = list(shot["metrics"])
    if identifier == "shot-01":
        number_values = ["≈ 0", "多数"]
    if identifier == "shot-03":
        overlay_text = [shot["target"], shot["payoff"]]
    else:
        overlay_text = list(shot.get("overlays") or [shot["payoff"]])[:2]
    keyword_values = list(shot.get("units") or overlay_text)[:3]
    visual_types = {
        "shot-01": "comparison",
        "shot-02": "steps",
        "shot-03": "source_card",
        "shot-04": "video",
        "shot-05": "metric",
    }
    official = None
    if route == "official":
        official = {
            "kind": "video",
            "attribution": shot["hero"],
            "publisher": "Stanford STVP",
            "official_host": "stanford.edu",
        }
    ai = None
    if route == "ai":
        ai = {
            "prompt_summary": shot["hero"],
            "composition": "native vertical cinematic evidence",
            "subject_position": "center",
            "camera_motion": "continuous",
            "palette": "midnight gold",
            "mood": "confident",
            "negative_constraints": ["text", "logo", "audio"],
        }
    code = None
    if route == "code":
        code = {
            "exact_text": body_values,
            "exact_numbers": number_values,
        }
    return {
        "segment_id": identifier,
        "start": start,
        "end": end,
        "implementation": route,
        "visual_type": visual_types[identifier],
        "arroll_mode": "base",
        "keywords": [
            {"text": value, "role": "primary"} for value in keyword_values
        ],
        "avatar_position": shot["avatar"].replace("-", "_"),
        "safe_zones": {},
        "official": official,
        "code": code,
        "ai": ai,
        "has_person_layer": False,
        "visual_system": shot["system"],
        "motion_grammar": shot["grammar"],
        "sequence_id": f"sequence-{identifier}",
        "sequence_phase": 0,
        "sequence_start": start,
        "sequence_end": end,
        "headline": shot["title"],
        "headline_tier": "medium",
        "content_profile": {
            "body_values": body_values,
            "number_values": number_values,
            "result_token": (
                number_values[0]
                if identifier == "shot-01"
                else number_values[-1] if number_values else ""
            ),
            "semantic_units": [],
            "target_units": [2, 4],
            "density_band": "balanced",
            "overlay_text": overlay_text,
        },
        "overlay_text": overlay_text,
        "poster_density": "balanced",
        "poster_layout": None,
        "source_kind": (
            f"code-{visual_types[identifier]}"
            if route == "code"
            else "official-video" if route == "official" else "ai-video"
        ),
        "poster_geometry_status": "valid",
        "editorial_payoff": shot["payoff"],
        "keyword_layout": None,
    }


def _production_media_nodes() -> list[str]:
    return [
        '<video id="media-global-arroll-10" src="media/avatar.mp4" '
        'class="media-source clip" data-start="0" data-duration="30" '
        'data-media-start="0" data-media-clock="global" data-track-index="10" '
        'muted playsinline preload="auto"></video>',
        '<video id="media-global-avatar-11" src="media/avatar.mp4" '
        'class="media-source clip" data-start="0" data-duration="30" '
        'data-media-start="0" data-media-clock="global" data-track-index="11" '
        'muted playsinline preload="auto"></video>',
        '<video id="media-shot-04-20" src="media/official.mp4" '
        'class="media-source clip" data-start="18" data-duration="6" '
        'data-media-start="0" data-media-clock="local" data-track-index="20" '
        'muted playsinline preload="auto"></video>',
        '<video id="media-shot-05-20" src="media/ai.mp4" '
        'class="media-source clip" data-start="24" data-duration="6" '
        'data-media-start="0" data-media-clock="local" data-track-index="20" '
        'muted playsinline preload="auto"></video>',
    ]


def build_html(spec: dict[str, Any]) -> str:
    checked = validate_spec(spec)
    try:
        template = CANARY_TEMPLATE.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CanaryError("cannot read approved canary template") from error
    shots = "".join(
        builder(shot)
        for builder, shot in zip(SHOT_BUILDERS, checked["shots"])
    )
    encoded_spec = json.dumps(
        checked,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        template.replace("__DURATION__", str(TOTAL_DURATION))
        .replace("__CANARY_MEDIA_HTML__", _media_nodes(checked))
        .replace("__CANARY_SHOTS_HTML__", shots)
        .replace("__CANARY_SPEC_JSON__", encoded_spec)
    )


def build_render_command(runtime: Path, stage: Path, output: Path) -> list[str]:
    return [
        str(runtime),
        "render",
        str(stage),
        "-o",
        str(output),
        "--fps=24",
        "--quality=draft",
        "--workers=1",
        "--strict",
        "--resolution=portrait",
        "--browser-gpu",
        "--low-memory-mode",
        "--experimental-fast-capture",
        "--json",
    ]


def _media_command(
    source: Path,
    output: Path,
    *,
    seconds: int,
    video_filter: str,
    seek: int = 0,
    loop: bool = False,
) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
    ]
    if seek:
        command.extend(("-ss", str(seek)))
    if loop:
        command.extend(("-stream_loop", "-1"))
    command.extend(
        (
            "-i", str(source), "-t", str(seconds), "-map", "0:v:0", "-vf",
            video_filter, "-r", "24", "-an", "-c:v", "libx264", "-preset",
            "medium", "-crf", "20", "-g", "24", "-keyint_min", "24",
            "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-movflags",
            "+faststart", "-y", str(output),
        )
    )
    return command


def build_media_commands(
    avatar_source: Path,
    official_source: Path,
    ai_source: Path,
    media_dir: Path,
) -> dict[str, list[str]]:
    return {
        "avatar": _media_command(
            avatar_source,
            media_dir / "avatar.mp4",
            seconds=TOTAL_DURATION,
            video_filter=_AVATAR_MEDIA_FILTER,
        ),
        "official": _media_command(
            official_source,
            media_dir / "official.mp4",
            seconds=SHOT_DURATION,
            loop=True,
            video_filter=(
                "fps=24,scale=936:526:force_original_aspect_ratio=decrease:"
                "flags=lanczos,pad=936:526:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
        ),
        "ai": _media_command(
            ai_source,
            media_dir / "ai.mp4",
            seconds=SHOT_DURATION,
            video_filter=(
                "fps=24,scale=1080:1920:force_original_aspect_ratio=increase:"
                "flags=lanczos,crop=1080:1920"
            ),
        ),
    }


def validate_probe(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CanaryError("canary media probe is invalid")
    if (payload.get("width"), payload.get("height")) != (WIDTH, HEIGHT):
        raise CanaryError("canary render must be native 1080x1920")
    expected = {
        "codec_name": "h264",
        "pix_fmt": "yuv420p",
        "r_frame_rate": "24/1",
        "nb_read_frames": str(TOTAL_DURATION * FPS),
        "audio_streams": 0,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise CanaryError("canary render does not match the silent 24fps contract")
    return payload


def build_probe_command(path: Path) -> list[str]:
    return [
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames",
        "-of", "json", str(path),
    ]


def build_decode_command(path: Path) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
        "-i", str(path), "-map", "0:v:0", "-f", "null", "-",
    ]


def build_keyframe_commands(video: Path, output_dir: Path) -> list[list[str]]:
    commands = []
    for index in range(SHOT_COUNT):
        timestamp = index * SHOT_DURATION + 4.6
        output = output_dir / f"shot-{index + 1:02d}.png"
        commands.append(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-v", "error",
                "-ss", f"{timestamp:.1f}", "-i", str(video), "-frames:v", "1",
                "-vf", "scale=1080:1920:flags=lanczos", "-y", str(output),
            ]
        )
    return commands


def make_contact_sheet(frames: list[Path], output: Path) -> Path:
    if len(frames) != SHOT_COUNT:
        raise CanaryError("contact sheet requires exactly five canary frames")
    cell = (432, 768)
    sheet = Image.new("RGB", (cell[0] * 2, cell[1] * 3), "#090b10")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(frames):
        try:
            with Image.open(path) as image:
                frame = image.convert("RGB").resize(cell, Image.Resampling.LANCZOS)
        except OSError as error:
            raise CanaryError("cannot read a canary keyframe") from error
        left = (index % 2) * cell[0]
        top = (index // 2) * cell[1]
        sheet.paste(frame, (left, top))
        draw.rectangle((left + 12, top + 12, left + 110, top + 48), fill="#090b10")
        draw.text((left + 24, top + 20), f"SHOT {index + 1:02d}", fill="#ffffff")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=True)
    return output


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["HYPERFRAMES_NO_TELEMETRY"] = "1"
    environment["DO_NOT_TRACK"] = "1"
    environment["NO_PROXY"] = "localhost,127.0.0.1,::1"
    environment["no_proxy"] = "localhost,127.0.0.1,::1"
    for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        environment[name] = "http://127.0.0.1:9"
    return environment


def _run(
    command: list[str],
    *,
    label: str,
    timeout: int = 600,
    environment: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except FileNotFoundError as error:
        raise CanaryError(f"{label} runtime is unavailable") from error
    except subprocess.TimeoutExpired as error:
        raise CanaryError(f"{label} timed out") from error
    except subprocess.CalledProcessError as error:
        lines = (error.stderr or error.stdout or f"{label} failed").strip().splitlines()
        raise CanaryError(lines[-1] if lines else f"{label} failed") from error


def _require_source(path: Path, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise CanaryError(f"{label} source is unavailable")
    return candidate


def resolve_runtime(path: Path) -> Path:
    candidate = Path(path).expanduser().absolute()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise CanaryError("HyperFrames runtime is unavailable") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise CanaryError("HyperFrames runtime is unavailable")
    return resolved


def _probe(path: Path) -> dict[str, Any]:
    result = _run(build_probe_command(path), label="FFprobe", timeout=120)
    try:
        streams = json.loads(result.stdout)["streams"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CanaryError("cannot parse canary media probe") from error
    if not isinstance(streams, list):
        raise CanaryError("canary media probe is invalid")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise CanaryError("canary render must contain one video stream")
    return validate_probe({**videos[0], "audio_streams": len(audios)})


def _verify_runtime(runtime: Path) -> Path:
    candidate = resolve_runtime(runtime)
    result = _run(
        [str(candidate), "--version"],
        label="HyperFrames version check",
        timeout=30,
        environment=_environment(),
    )
    if result.stdout.strip() != HYPERFRAMES_VERSION:
        raise CanaryError("HyperFrames runtime version is invalid")
    return candidate


def render_canary(
    *,
    spec_path: Path,
    avatar_source: Path,
    official_source: Path,
    ai_source: Path,
    output_dir: Path,
    runtime: Path = DEFAULT_HYPERFRAMES,
) -> dict[str, Any]:
    spec = load_spec(spec_path)
    avatar = _require_source(avatar_source, "avatar")
    official = _require_source(official_source, "official")
    ai = _require_source(ai_source, "AI")
    hyperframes = _verify_runtime(runtime)
    destination = Path(output_dir).expanduser().absolute()
    if destination.exists() and any(destination.iterdir()):
        raise CanaryError("canary output directory must be empty")
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".canary-stage-", dir=destination) as name:
        stage = Path(name)
        media_dir = stage / "media"
        media_dir.mkdir()
        (stage / "index.html").write_text(build_html(spec), encoding="utf-8")
        shutil.copy2(spec_path, stage / "shot-spec.json")

        for label, command in build_media_commands(
            avatar, official, ai, media_dir
        ).items():
            print(f"[canary] preparing {label} media", flush=True)
            _run(command, label=f"{label} media preparation", timeout=900)

        rendered = stage / "broll-canary-5shot.mp4"
        print("[canary] rendering five native 9:16 shots with one worker", flush=True)
        _run(
            build_render_command(hyperframes, stage, rendered),
            label="HyperFrames render",
            timeout=2400,
            environment=_environment(),
        )
        probe = _probe(rendered)
        _run(build_decode_command(rendered), label="complete decode", timeout=900)

        keyframes = stage / "keyframes"
        keyframes.mkdir()
        for command in build_keyframe_commands(rendered, keyframes):
            _run(command, label="keyframe extraction", timeout=120)
        frame_paths = sorted(keyframes.glob("shot-*.png"))
        contact_sheet = make_contact_sheet(frame_paths, stage / "contact-sheet.png")
        report = {
            "version": 1,
            "status": "technical-pass",
            "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
            "duration": TOTAL_DURATION,
            "frames": TOTAL_DURATION * FPS,
            "audio_streams": 0,
            "shots": [
                {
                    "id": shot["id"],
                    "route": shot["route"],
                    "grammar": shot["grammar"],
                    "system": shot["system"],
                }
                for shot in spec["shots"]
            ],
            "probe": probe,
        }
        report_path = stage / "qa-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        outputs = {
            "video": destination / rendered.name,
            "contact_sheet": destination / contact_sheet.name,
            "keyframes": destination / "keyframes",
            "qa_report": destination / report_path.name,
            "source": destination / "source",
        }
        for path in outputs.values():
            if path.exists():
                raise CanaryError("canary output target already exists")
        os.replace(rendered, outputs["video"])
        os.replace(contact_sheet, outputs["contact_sheet"])
        os.replace(keyframes, outputs["keyframes"])
        os.replace(report_path, outputs["qa_report"])
        source_dir = outputs["source"]
        source_dir.mkdir()
        os.replace(stage / "index.html", source_dir / "index.html")
        os.replace(stage / "shot-spec.json", source_dir / "shot-spec.json")

    return {
        "video": str(outputs["video"]),
        "contact_sheet": str(outputs["contact_sheet"]),
        "keyframes": str(outputs["keyframes"]),
        "qa_report": str(outputs["qa_report"]),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "edit/hd/canary/shot-spec.json")
    parser.add_argument("--avatar-source", type=Path, required=True)
    parser.add_argument("--official-source", type=Path, required=True)
    parser.add_argument("--ai-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_HYPERFRAMES)
    args = parser.parse_args(argv)
    try:
        result = render_canary(
            spec_path=args.spec,
            avatar_source=args.avatar_source,
            official_source=args.official_source,
            ai_source=args.ai_source,
            output_dir=args.output_dir,
            runtime=args.runtime,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (CanaryError, OSError, ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

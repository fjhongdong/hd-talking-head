"""Parent subtitle renderer using the approved timing and locked TalkCraft theme."""

from __future__ import annotations
from scripts.package_paths import PACKAGE_ROOT

import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import contract_artifacts, subtitles


ROOT = PACKAGE_ROOT / "edit/hd/integrations/talkcraft"
ADAPTER = ROOT / "subtitles"
UPSTREAM = PACKAGE_ROOT / "vendor/talkcraft/template/motion-systems/Subtitles.tsx"
UPSTREAM_SHA256 = "fee88ad65d35422220fddf56c9de9efeeee85a9c28a2ca6122dcc0bfadf42390"


class TalkCraftSubtitleError(ValueError):
    """The local renderer or its source/clock binding is invalid."""


def validate_native_caption_source(source: Mapping[str, Any]) -> None:
    """Validate provenance emitted only after the frozen native result is checked."""
    if (not isinstance(source, Mapping)
            or set(source) != {'dependency_id', 'template_id', 'segment_id', 'component_id', 'result_record'}
            or source['dependency_id'] != 'sweety-handdraw-video'
            or not isinstance(source['template_id'], str)
            or re.fullmatch(r'sweety-handdraw-video/style-[a-z0-9-]+', source['template_id']) is None
            or any(not isinstance(source[k], str) or not source[k] for k in ('segment_id', 'component_id'))):
        raise TalkCraftSubtitleError('native caption source must be the verified Sweety style film')
    record = source['result_record']
    if (not isinstance(record, Mapping) or set(record) != {'path', 'sha256', 'bytes'}
            or not isinstance(record['path'], str) or Path(record['path']).is_absolute()
            or '..' in Path(record['path']).parts or not record['path'].startswith('native-inputs/')
            or not record['path'].endswith('.json')
            or re.fullmatch(r'[a-f0-9]{64}', str(record['sha256'])) is None
            or type(record['bytes']) is not int or record['bytes'] < 1):
        raise TalkCraftSubtitleError('native captions require the exact frozen completion descriptor')


def renderer_owns_cue(cue: Mapping[str, Any]) -> bool:
    if 'native_caption' not in cue:
        return True
    validate_native_caption_source(cue['native_caption'])
    return False


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def cue_input(cue: Mapping[str, Any], chunk: list[dict[str, object]], *, placement: str = "standard",
              long_keyword: bool = False) -> dict[str, Any]:
    """Keep real word intervals; never distribute a word's duration over its glyphs."""
    raw = "".join(str(word["text"]) for word in chunk)
    text = str(cue["text"])
    if not text or not raw.endswith(text):
        raise TalkCraftSubtitleError("subtitle text does not match its word group")
    dropped = len(raw) - len(text)
    cursor = 0
    words = []
    for word in chunk:
        end_cursor = cursor + len(str(word["text"]))
        left, right = max(cursor, dropped) - dropped, end_cursor - dropped
        start = max(float(cue["start"]), float(word["start"]))
        end = min(float(cue["end"]), float(word["end"]))
        if right > left:
            if end <= start:
                raise TalkCraftSubtitleError("subtitle word falls outside its cue")
            words.append({"start": start, "end": end,
                          "text_start": _utf16_length(text[:left]),
                          "text_end": _utf16_length(text[:right])})
        cursor = end_cursor
    emphasis = None
    if cue["emphasis_words"]:
        keyword = cue["emphasis_words"][0]
        offset = text.index(keyword)
        left = _utf16_length(text[:offset])
        right = left + _utf16_length(keyword)
        hits = [word for word in words
                if word["text_start"] < right and word["text_end"] > left]
        if not hits:
            raise TalkCraftSubtitleError("approved emphasis has no source word timing")
        emphasis = {"text_start": left, "text_end": right,
                    "start": hits[0]["start"], "end": hits[-1]["end"]}
    result = {"cue_id": cue["id"], "start": cue["start"], "end": cue["end"],
            "text": text, "words": words, "emphasis": emphasis,
            "placement": placement, "long_keyword": long_keyword}
    if placement == "standard":
        result["bottom"] = 350
    else:
        if "box" not in cue or "bottom" not in cue:
            raise TalkCraftSubtitleError("B-roll subtitle box is required")
        width = cue["box"].get("width")
        if type(width) is not int or not 436 <= width <= 640:
            raise TalkCraftSubtitleError("B-roll subtitle width is invalid")
        result["bottom"] = cue["bottom"]
        result["width"] = width
    return result


def renderer_input(plan: Mapping[str, Any], cues: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 2,
            "canvas": {key: plan["canvas"][key] for key in ("width", "height", "fps", "frames")},
            "cues": cues}


def identity(render_input: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    # Code-only runtime exports do not include the separately installed media runtime.
    # Keep import/CLI discovery usable; require the dependency when this stage runs.
    try:
        from ..integrations.talkcraft.check_runtime import check_runtime
    except ImportError as exc:
        raise TalkCraftSubtitleError("project TalkCraft runtime is unavailable") from exc
    # This pins the style reference, not proof that its Subtitles component runs.
    # The actual renderer is ADAPTER/Subtitles.tsx and imports the upstream theme.
    if contract_artifacts.sha256_file(UPSTREAM) != UPSTREAM_SHA256:
        raise TalkCraftSubtitleError("locked TalkCraft subtitle component changed")
    health = check_runtime(ROOT)
    files = sorted(path for path in ADAPTER.iterdir() if path.suffix in {".tsx", ".ts", ".mjs"})
    if not files or not (ADAPTER / "render.mjs").is_file():
        raise TalkCraftSubtitleError("TalkCraft subtitle adapter is unavailable")
    hashes = {path.name: contract_artifacts.sha256_file(path) for path in files}
    hashes["python-adapter"] = contract_artifacts.sha256_file(Path(__file__))
    theme = PACKAGE_ROOT / "vendor/talkcraft/template/motion-systems/theme.ts"
    hashes["upstream-theme"] = contract_artifacts.sha256_file(theme)
    react = contract_artifacts.read_json_artifact(ROOT / "runtime/node_modules/react/package.json")
    return {"id": "video-talkcraft-subtitles-adapter/v1", "upstream_sha256": UPSTREAM_SHA256,
            "implementation_sha256": contract_artifacts.sha256_json(hashes),
            "input_sha256": contract_artifacts.sha256_json(render_input),
            "render_plan_sha256": contract_artifacts.sha256_json(plan),
            "remotion_version": health["production_runtime"]["remotion"],
            "react_version": react["version"]}


def validate_binding(payload: Mapping[str, Any]) -> None:
    """New production output must carry this renderer, not the old PIL track."""
    plan, data = payload.get("render_plan"), payload.get("renderer_input")
    if payload.get("schema_version") != 4 or not isinstance(plan, Mapping) or not isinstance(data, Mapping):
        raise TalkCraftSubtitleError("TalkCraft subtitle binding missing; render the current style")
    if payload.get("renderer") != identity(data, plan):
        raise TalkCraftSubtitleError("TalkCraft subtitle renderer identity changed")
    if data.get("canvas") != {key: plan["canvas"][key] for key in ("width", "height", "fps", "frames")}:
        raise TalkCraftSubtitleError("TalkCraft subtitle clock changed")
    actual = data.get("cues", [])
    if len(actual) != len(plan["cues"]):
        raise TalkCraftSubtitleError("TalkCraft subtitle cue count changed")
    for cue, rendered in zip(plan["cues"], actual):
        if not renderer_owns_cue(rendered) and rendered['native_caption']['segment_id'] != cue['segment_id']:
            raise TalkCraftSubtitleError('native caption source belongs to another subtitle segment')
        if any(rendered.get(key) != cue[source] for key, source in
               (("cue_id", "id"), ("start", "start"), ("end", "end"), ("text", "text"))):
            raise TalkCraftSubtitleError("TalkCraft subtitle content or window changed")
        if (type(rendered.get("long_keyword")) is not bool
                or (rendered["long_keyword"] and subtitles._visible_glyph_count([cue]) <= 14)):
            raise TalkCraftSubtitleError("TalkCraft subtitle long keyword layout is invalid")
        emphasis = rendered.get("emphasis")
        encoded = str(cue["text"]).encode("utf-16-le")
        highlighted = [] if emphasis is None else [encoded[
            emphasis["text_start"] * 2:emphasis["text_end"] * 2].decode("utf-16-le")]
        if highlighted != cue["emphasis_words"]:
            raise TalkCraftSubtitleError("TalkCraft subtitle emphasis changed")
        expected_placement = "above_avatar" if cue["safe_zones"]["face"] is not None else "standard"
        if rendered.get("placement") != expected_placement:
            raise TalkCraftSubtitleError("TalkCraft subtitle placement changed")
        if expected_placement == "standard":
            expected_bottom = 350
        else:
            if "box" not in cue:
                raise TalkCraftSubtitleError("B-roll subtitle box is missing")
            expected_bottom = 1920 - (cue["box"]["y"] + cue["box"]["height"])
        if rendered.get("bottom") != expected_bottom:
            raise TalkCraftSubtitleError("TalkCraft subtitle bottom changed")
        if expected_placement == "above_avatar":
            width = rendered.get("width")
            if type(width) is not int or not 436 <= width <= 640 or width != cue["box"]["width"]:
                raise TalkCraftSubtitleError("TalkCraft subtitle width changed")
        elif "width" in rendered:
            raise TalkCraftSubtitleError("TalkCraft standard subtitle width changed")


def render(data: Mapping[str, Any], descriptor: int) -> None:
    """Call real Remotion serially, then copy the result into the transaction's fd."""
    with tempfile.TemporaryDirectory(prefix="hd-talkcraft-subtitles-") as directory:
        source, output = Path(directory) / "input.json", Path(directory) / "subtitles.webm"
        contract_artifacts.write_json_artifact(source, data)
        try:
            subprocess.run(["node", str(ADAPTER / "render.mjs"), "--input", str(source),
                            "--output", str(output)], cwd=PACKAGE_ROOT,
                           check=True, capture_output=True, text=True,
                           timeout=max(180, int(data["canvas"]["frames"]) * 2))
        except (OSError, subprocess.SubprocessError) as exc:
            detail = (getattr(exc, "stderr", "") or str(exc))[-2000:]
            raise TalkCraftSubtitleError(f"TalkCraft subtitle render failed: {detail}") from exc
        if not output.is_file() or output.stat().st_size == 0:
            raise TalkCraftSubtitleError("TalkCraft subtitle render returned no media")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        with output.open("rb") as source_file, os.fdopen(os.dup(descriptor), "wb") as target:
            shutil.copyfileobj(source_file, target)
            target.flush()
        os.fsync(descriptor)


def verify_geometry(descriptor: int, plan: Mapping[str, Any], data: Mapping[str, Any]) -> None:
    """Verify ordinary geometry plus exact cue edges and keyword animation peaks."""
    frames = int(plan["canvas"]["frames"])
    samples = {0, frames - 1}
    for cue in plan["cues"]:
        index = round(((float(cue["start"]) + float(cue["end"])) / 2) * 24)
        samples.add(min(frames - 2, max(1, index)))
    for cue in data["cues"]:
        samples.update((math.ceil(cue["start"] * 24) - 1, math.ceil(cue["start"] * 24),
                        math.ceil(cue["end"] * 24) - 1, math.ceil(cue["end"] * 24)))
        if cue["emphasis"] is not None:
            peak = (cue["emphasis"]["start"] + 0.18) * 24
            samples.update((math.floor(peak), math.ceil(peak)))
    parent_ids = {cue['cue_id'] for cue in data['cues'] if renderer_owns_cue(cue)}
    subtitles._verify_alpha_frames(descriptor, [
        (frame, next((cue for cue in plan["cues"]
                      if cue['id'] in parent_ids and cue["start"] <= frame / 24 < cue["end"]), None))
        for frame in sorted(samples) if 0 <= frame < frames
    ])

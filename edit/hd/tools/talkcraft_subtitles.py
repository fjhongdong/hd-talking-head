"""Thin timing/identity adapter for the approved video-talkcraft subtitle component."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import contract_artifacts, subtitles


ROOT = Path(__file__).resolve().parents[1] / "integrations" / "talkcraft"
ADAPTER = ROOT / "subtitles"
UPSTREAM = ROOT / "upstream/template/motion-systems/Subtitles.tsx"
UPSTREAM_SHA256 = "fee88ad65d35422220fddf56c9de9efeeee85a9c28a2ca6122dcc0bfadf42390"


class TalkCraftSubtitleError(ValueError):
    """An upstream call or its source/clock binding is invalid."""


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def cue_input(cue: Mapping[str, Any], chunk: list[dict[str, object]], *, placement: str = "standard") -> dict[str, Any]:
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
    return {"cue_id": cue["id"], "start": cue["start"], "end": cue["end"],
            "text": text, "words": words, "emphasis": emphasis,
            "placement": placement}


def renderer_input(plan: Mapping[str, Any], cues: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1,
            "canvas": {key: plan["canvas"][key] for key in ("width", "height", "fps", "frames")},
            "cues": cues}


def identity(render_input: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    # Code-only runtime exports do not include the separately installed media runtime.
    # Keep import/CLI discovery usable; require the dependency when this stage runs.
    try:
        from ..integrations.talkcraft.check_runtime import check_runtime
    except ImportError as exc:
        raise TalkCraftSubtitleError("project TalkCraft runtime is unavailable") from exc
    if contract_artifacts.sha256_file(UPSTREAM) != UPSTREAM_SHA256:
        raise TalkCraftSubtitleError("locked TalkCraft subtitle component changed")
    health = check_runtime(ROOT)
    files = sorted(path for path in ADAPTER.iterdir() if path.suffix in {".tsx", ".ts", ".mjs"})
    if not files or not (ADAPTER / "render.mjs").is_file():
        raise TalkCraftSubtitleError("TalkCraft subtitle adapter is unavailable")
    hashes = {path.name: contract_artifacts.sha256_file(path) for path in files}
    hashes["python-adapter"] = contract_artifacts.sha256_file(Path(__file__))
    theme = ROOT / "upstream/template/motion-systems/theme.ts"
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
        if any(rendered.get(key) != cue[source] for key, source in
               (("cue_id", "id"), ("start", "start"), ("end", "end"), ("text", "text"))):
            raise TalkCraftSubtitleError("TalkCraft subtitle content or window changed")
        emphasis = rendered.get("emphasis")
        encoded = str(cue["text"]).encode("utf-16-le")
        highlighted = [] if emphasis is None else [encoded[
            emphasis["text_start"] * 2:emphasis["text_end"] * 2].decode("utf-16-le")]
        if highlighted != cue["emphasis_words"]:
            raise TalkCraftSubtitleError("TalkCraft subtitle emphasis changed")
        expected_placement = "above_avatar" if cue["safe_zones"]["face"] is not None else "standard"
        if rendered.get("placement") != expected_placement:
            raise TalkCraftSubtitleError("TalkCraft subtitle placement changed")


def render(data: Mapping[str, Any], descriptor: int) -> None:
    """Call real Remotion serially, then copy the result into the transaction's fd."""
    with tempfile.TemporaryDirectory(prefix="hd-talkcraft-subtitles-") as directory:
        source, output = Path(directory) / "input.json", Path(directory) / "subtitles.webm"
        contract_artifacts.write_json_artifact(source, data)
        try:
            subprocess.run(["node", str(ADAPTER / "render.mjs"), "--input", str(source),
                            "--output", str(output)], cwd=ROOT.parents[3],
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
    subtitles._verify_alpha_frames(descriptor, [
        (frame, next((cue for cue in plan["cues"]
                      if cue["start"] <= frame / 24 < cue["end"]), None))
        for frame in sorted(samples) if 0 <= frame < frames
    ])

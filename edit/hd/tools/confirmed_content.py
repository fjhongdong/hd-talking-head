"""Small, immutable-content guard for Skill-managed HD jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping
from . import contract_artifacts


class ConfirmedContentError(RuntimeError):
    pass


def _fail(message: str = "confirmed content changed") -> None:
    raise ConfirmedContentError(message)


def _json(path: Path):
    try:
        return contract_artifacts.read_json_artifact(path)
    except (OSError, ValueError, UnicodeError, contract_artifacts.ContractArtifactError):
        _fail("confirmed content is unreadable")


def check_confirmed_content(job, plan: Mapping[str, object]) -> None:
    root = Path(getattr(job, "root", getattr(job, "job_dir", ".")))
    job_dir = Path(getattr(job, "job_dir", root))
    context = root / "job-context.json"
    path = job_dir / "manifests" / "confirmed-content.json"
    if not context.exists():
        return
    if not path.is_file():
        _fail("confirmed-content.json is required")
    value = _json(path)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1 or value.get("job_id") != job.job_id:
        _fail("confirmed content identity is invalid")
    source_words = value.get("source_words")
    visuals = value.get("visuals")
    if not isinstance(source_words, list) or not isinstance(visuals, list):
        _fail("confirmed content lists are invalid")
    indices = set()
    for item in source_words:
        if not isinstance(item, dict) or type(item.get("index")) is not int or item["index"] < 0 or not isinstance(item.get("text"), str):
            _fail("confirmed source word is invalid")
        if item["index"] in indices or not item["text"].strip():
            _fail("confirmed source words contain duplicates")
        indices.add(item["index"])
    ids = set()
    required = []
    for item in visuals:
        if not isinstance(item, dict) or not isinstance(item.get("component_id"), str) or not isinstance(item.get("composition_family"), str) or not isinstance(item.get("visible_text"), list) or not isinstance(item.get("binding"), dict):
            _fail("confirmed visual is invalid")
        cid = item["component_id"]
        if not cid.strip() or not item["composition_family"].strip() or any(
            not isinstance(text, str) or not text.strip() for text in item["visible_text"]
        ):
            _fail("confirmed visual text or identity is invalid")
        if cid in ids:
            _fail("confirmed visuals contain duplicate component ids")
        ids.add(cid)
        required.append(item)

    components = []
    for segment in plan.get("segments", []):
        recipe = segment.get("shot_recipe", {}) if isinstance(segment, dict) else {}
        if not recipe and isinstance(segment, dict):
            recipe = segment.get("visual_strategy", {})
        family = recipe.get("composition", {}).get("family") if isinstance(recipe, dict) else None
        for component in recipe.get("components", []) if isinstance(recipe, dict) else []:
            if isinstance(component, dict):
                components.append((component, family, segment))
    for wanted in required:
        matches = [(c, family, seg) for c, family, seg in components if c.get("component_id") == wanted["component_id"]]
        if len(matches) != 1:
            _fail(f"confirmed visual {wanted['component_id']} is missing or ambiguous")
        component, family, segment = matches[0]
        if family != wanted["composition_family"]:
            _fail(f"confirmed composition changed for {wanted['component_id']}")
        visible = segment.get("visible_text", [])
        if any(text not in visible for text in wanted["visible_text"]):
            _fail(f"confirmed visible text disappeared for {wanted['component_id']}")
        binding = wanted["binding"]
        if isinstance(segment.get("bindings"), dict):
            actual_binding = segment["bindings"].get(wanted["component_id"])
            if not isinstance(actual_binding, dict):
                _fail(f"confirmed visual binding is missing for {wanted['component_id']}")
            component = dict(component)
            component.update(actual_binding)
        if any(component.get(key) != expected for key, expected in binding.items()):
            _fail(f"confirmed visual binding changed for {wanted['component_id']}")

    timeline = job_dir / "06-edit-structure" / "timeline-map.json"
    if source_words and not timeline.is_file():
        _fail("timeline map is required")
    if source_words:
        mapped = _json(timeline)
        transcript = _json(job_dir / "05-speech-cleanup" / "word-transcript.json")
        words = transcript.get("words", []) if isinstance(transcript, dict) else []
        segments = mapped.get("segments", []) if isinstance(mapped, dict) else []
        for item in source_words:
            word = words[item["index"]] if 0 <= item["index"] < len(words) else None
            if not isinstance(word, dict) or word.get("text") != item["text"]:
                _fail(f"confirmed source word {item['index']} text changed")
            if not any(
                isinstance(seg, dict)
                and isinstance(seg.get("source_start"), (int, float))
                and isinstance(seg.get("source_end"), (int, float))
                and float(seg["source_start"]) <= float(word.get("start"))
                and float(seg["source_end"]) >= float(word.get("end"))
                for seg in segments
            ):
                _fail(f"confirmed source word {item['index']} interval was deleted")

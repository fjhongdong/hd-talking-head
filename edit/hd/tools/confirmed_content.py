"""Small, immutable-content guard for Skill-managed HD jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping
import hashlib
import json
import re
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


def matches_visual(item: Mapping[str, object], segment_id: str, component_id: str) -> bool:
    return (item.get("component_id") == component_id
            and ("segment_id" not in item or item["segment_id"] == segment_id))


def _check_completed_media(job, segment, component, wanted, treatment) -> None:
    """Protect the reviewed Wake bytes through the same input used by production."""
    from . import visual_confirmation as confirmation, motion_capabilities
    expected = wanted['completed_media']
    if (not isinstance(expected, dict) or set(expected) != {'path', 'sha256', 'bytes'}
            or not isinstance(expected['path'], str) or not expected['path']
            or not isinstance(expected['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', expected['sha256'])
            or type(expected['bytes']) is not int or expected['bytes'] <= 0
            or 'segment_id' not in wanted or component.get('dependency_id') != 'lemo-wake'):
        _fail('confirmed completed media identity is invalid')
    root, sid, cid = Path(job.job_dir), segment['segment_id'], component['component_id']
    try:
        if treatment is not None:
            relative = motion_capabilities._brief_relative(treatment, segment, cid)
            if not relative:
                _fail('confirmed completed media needs its actual scene brief')
            payload = confirmation._path(root, relative).read_bytes()
            result_ref = None
        else:
            # Preview consumes the already-reviewed mapping, never a folder scan.
            mapping = confirmation.validate_visual_authorization(job, require_realized=True)['mapping']
            matches = [item for item in mapping['native_inputs']
                       if (item['segment_id'], item['component_id']) == (sid, cid)]
            if len(matches) != 1:
                _fail('confirmed completed media mapping is missing or ambiguous')
            payload = confirmation._exact(root, matches[0]['artifact']).read_bytes()
            result_ref = matches[0]['result_record']
        if hashlib.sha256(payload).hexdigest() != component.get('brief_sha256'):
            _fail('confirmed completed media brief differs from the component')
        brief = json.loads(payload)
        source = brief.get('source_binding', {})
        if brief.get('job_id') != job.job_id or any(source.get(key) != value for key, value in {
                'segment_id': sid, 'start': segment['start'], 'end': segment['end']}.items()):
            _fail('confirmed completed media belongs to another source window')
        if treatment is not None:
            result_ref = confirmation._freeze_reviewed_native_result(root, treatment, sid, cid, payload, 'lemo-wake')
        elif result_ref['path'] != brief['result_record_path']:
            _fail('confirmed completed media differs from the consumed result')
        result = _json(confirmation._exact(root, result_ref))
        media = result['media']
        if expected != {'path': media['job_path'], 'sha256': media['sha256'], 'bytes': media['byte_count']}:
            _fail('confirmed completed media was replaced')
        confirmation._exact(root, expected)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        _fail('confirmed completed media verification failed: ' + str(error))


def check_confirmed_content(job, plan: Mapping[str, object], *, treatment=None) -> None:
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
        sid = item.get("segment_id")
        if "segment_id" in item and (not isinstance(sid, str) or not sid.strip()):
            _fail("confirmed visual segment identity is invalid")
        key = (sid, cid)
        if key in ids:
            _fail("confirmed visuals contain duplicate component ids")
        ids.add(key)
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
        matches = [(c, family, seg) for c, family, seg in components
                   if matches_visual(wanted, seg.get("segment_id"), c.get("component_id"))]
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
        if 'completed_media' in wanted:
            _check_completed_media(job, segment, component, wanted, treatment)

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

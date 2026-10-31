"""Immutable visual proposal, source approval, and realized production evidence."""
from __future__ import annotations
import copy
import hashlib
import os
import re
import subprocess
import shutil
import tempfile
from types import SimpleNamespace
from pathlib import Path
from . import contract_artifacts as artifacts

SCHEMA = "visual-confirmation-v1"
DIRECTORY = "07-visual-confirmation"
MAPPING = "execution-mapping.json"
CORE_FIELDS = ("segment_id", "start", "end", "content_item_ids", "visible_text",
               "visual_intent", "visual_strategy", "strategy_revision")

class VisualConfirmationError(ValueError):
    pass

def _read(path):
    return artifacts.read_json_artifact(Path(path))

def _path(root, relative):
    path = Path(root) / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise VisualConfirmationError("visual evidence must belong to this Job")
    return path

def _record(root, path):
    path = Path(path)
    return {"path": path.relative_to(root).as_posix(),
            "sha256": artifacts.sha256_file(path), "bytes": path.stat().st_size}

def _exact(root, record):
    path = _path(root, record["path"])
    if record != _record(Path(root), path):
        raise VisualConfirmationError("confirmed visual evidence changed: " + record["path"])
    return path

NATIVE_RESULT_MODULES = {'lemo-wake': 'lemo_wake_adapter', 'video-talkcraft': 'talkcraft_skill_adapter',
                         'barty-motion-graphics': 'motion_native_skill_adapter', 'bang-motion': 'motion_native_skill_adapter',
                         'mg-styles-15': 'motion_native_skill_adapter', 'video-shotcraft': 'motion_native_skill_adapter'}

def native_candidate_id(dependency, brief, segment=None, component_id=None):
    if dependency == 'lemo-wake':
        return 'lemo-wake:wake'
    if dependency == 'video-talkcraft':
        return 'video-talkcraft:' + brief['card_id']
    template = dependency + '/' + brief['template_id']
    from .semantic_visual_plan import component_use
    components = [c for c in segment['visual_strategy']['components'] if c.get('component_id') == component_id]
    if len(components) != 1:
        raise VisualConfirmationError('native result must identify one actual component')
    return ('overlay:' if component_use(segment, components[0]) == 'overlay' else dependency + ':') + template

def _native_result_adapter(dependency):
    import importlib.util
    path = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts" / (NATIVE_RESULT_MODULES[dependency] + '.py')
    spec = importlib.util.spec_from_file_location("_native_mapping_" + dependency.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _native_review_reference(treatment, segment_id, component_id, result_path, candidate_id):
    assessments = [item for item in treatment.get("semantic_assessments", [])
                   if item.get("segment_id") == segment_id and item.get("component_id") == component_id]
    if (len(assessments) != 1 or assessments[0].get("verdict") != "pass"
            or assessments[0].get("candidate_id") != candidate_id):
        raise VisualConfirmationError("Native Skill needs one passing content assessment for this component")
    refs = [ref for ref in assessments[0].get("content_refs", []) if ref.get("path") == result_path]
    if (len(refs) != 1 or refs[0].get("pointer") != "/status" or refs[0].get("value") != "completed"
            or not isinstance(refs[0].get("sha256"), str)):
        raise VisualConfirmationError("Native Skill assessment must identify the reviewed completed result")
    return refs[0]


def _freeze_reviewed_native_result(root, treatment, segment_id, component_id, brief_payload, dependency, segment=None):
    """Bind the bytes that were reviewed; never bless the current path implicitly."""
    import json
    brief = json.loads(brief_payload)
    relative = brief["result_record_path"]
    candidate = native_candidate_id(dependency, brief, segment, component_id)
    reviewed = _native_review_reference(treatment, segment_id, component_id, relative, candidate)
    data = _path(root, relative).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != reviewed["sha256"]:
        raise VisualConfirmationError("Native Skill result differs from the content the host reviewed")
    _native_result_adapter(dependency).inspect_result(root, brief_payload, record_bytes=data)
    return {"path": relative, "sha256": digest, "bytes": len(data)}


def _validate_native_results(root, mapping, director, treatment):
    """Validate frozen native results without calling an approved-plan loader."""
    if any(binding.get('dependency_id') in MOTION_CREATION for s in director['segments']
           for binding in s.get('bindings', {}).values()):
        from . import motion_readability
        motion_readability.validate_targets(
            [{**s, 'shot_recipe': {'components': s['visual_strategy']['components']}} for s in director['segments']],
            treatment.get('motion_readability', []), motion_readability._required_refs(treatment), root=root)
    for segment in director["segments"]:
        for cid, binding in segment.get("bindings", {}).items():
            dependency = binding.get("dependency_id")
            if dependency not in NATIVE_RESULT_MODULES:
                continue
            matches = [item for item in mapping.get("native_inputs", [])
                       if item.get("segment_id") == segment["segment_id"] and item.get("component_id") == cid]
            if len(matches) != 1 or matches[0].get("artifact", {}).get("sha256") != binding["brief_sha256"]:
                raise VisualConfirmationError("Wake result mapping is missing, duplicated or belongs to another brief")
            native = matches[0]
            if "result_record" not in native:
                raise VisualConfirmationError("Wake reviewed result is missing from the frozen mapping")
            payload = _exact(root, native["artifact"]).read_bytes()
            expected = native["result_record"]
            import json
            brief = json.loads(payload)
            candidate = native_candidate_id(dependency, brief, segment, cid)
            reviewed = _native_review_reference(treatment, segment["segment_id"], cid, expected["path"], candidate)
            if reviewed["sha256"] != expected["sha256"]:
                raise VisualConfirmationError("Wake mapping differs from the host's reviewed result")
            options = {'expected_renderer_version': binding['renderer_version']} if dependency != 'lemo-wake' else {}
            _native_result_adapter(dependency).load_result(root, payload, expected_record=expected, **options)


def native_result_descriptor(job, segment_id, component_id, brief_sha256):
    """Read only the already-approved mapping; the consumer verifies the result bytes."""
    if job.stages["visual_direction"]["status"] != "approved":
        raise VisualConfirmationError("Wake production requires an approved visual mapping")
    authorized = validate_visual_authorization(job)
    refs = [r for r in job.stages["visual_direction"]["artifacts"] if r["path"].endswith("/" + MAPPING)]
    if len(refs) != 1:
        raise VisualConfirmationError("approved visual mapping is missing or ambiguous")
    mapping = _read(_exact(job.job_dir, refs[0]))
    if mapping.get("source_approval") != authorized["artifact"]:
        raise VisualConfirmationError("approved visual mapping does not match its confirmation")
    matches = [item for item in mapping.get("native_inputs", [])
               if item.get("segment_id") == segment_id and item.get("component_id") == component_id]
    if (len(matches) != 1 or matches[0].get("artifact", {}).get("sha256") != brief_sha256
            or "result_record" not in matches[0]):
        raise VisualConfirmationError("Wake reviewed result is missing, duplicated or belongs to another brief")
    record = matches[0]["result_record"]
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
        raise VisualConfirmationError("approved Wake result descriptor is invalid")
    return copy.deepcopy(record)

def _core(director):
    return [{key: (segment.get(key, segment.get("shot_recipe", {}).get(key))
                   if key == "strategy_revision" else segment.get(key))
             for key in CORE_FIELDS} for segment in director["segments"]]

def _steps(treatment):
    steps = treatment.get("generation_plan", {}).get("steps", [])
    if not isinstance(steps, list):
        raise VisualConfirmationError("generation_plan.steps must be a list")
    seen = set()
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get("id"), str)
                or not step["id"] or step["id"] in seen
                or step.get("purpose") not in {"image", "video"}
                or not isinstance(step.get("arguments"), dict)
                or not isinstance(step.get("input_files", []), list)
                or any(dep not in seen for dep in step.get("depends_on", []))):
            raise VisualConfirmationError("generation steps need unique IDs and ordered dependencies")
        seen.add(step["id"])
    return steps


def planned_generation_targets(project_root, director, treatment, *, job_dir):
    """Validate missing inputs for exact, selected full-scene creation targets.

    This is a proposal contract, never a native-input or media acceptance.
    Prepared inputs cannot opt out by also listing generation steps.
    """
    steps = _steps(treatment)
    if not steps:
        return set()
    from . import motion_capabilities, generation_model, generation_inputs, generation_queue, startup
    components = {(s["segment_id"], c["component_id"]): (s, c)
                  for s in director["segments"] for c in s["visual_strategy"]["components"]}
    by_step = {step["id"]: step for step in steps}
    referenced_steps = {step["id"]: set() for step in steps}
    def references(value, step):
        if isinstance(value, dict):
            if "$step" in value:
                dependency = by_step.get(value["$step"])
                if (set(value) - {"$step", "output"} or dependency is None
                        or dependency["id"] not in step.get("depends_on", [])
                        or type(value.get("output", 0)) is not int or value.get("output", 0) < 0):
                    raise VisualConfirmationError("future input must name a valid approved dependency output")
                referenced_steps[step["id"]].add(dependency["id"])
            else:
                for child in value.values(): references(child, step)
        elif isinstance(value, list):
            for child in value: references(child, step)
    for step in steps:
        if (step.get("segment_id"), step.get("component_id")) not in components:
            raise VisualConfirmationError("generation step has no visual row")
        references(step["arguments"], step)
    selection = treatment.get("skill_selection", {})
    assignments = selection.get("assignments", [])
    if not assignments:
        return set()  # Direct generation already has its existing proposal contract.
    catalog = {r["candidate_id"]: r for r in motion_capabilities.load_catalog(Path(project_root))}
    scenes = {(r.get("segment_id"), r.get("component_id")): r for r in treatment.get("scenes", [])}
    planned = set()
    config = channels = None
    for assignment in assignments:
        key = (assignment["segment_id"], assignment["component_id"])
        own_steps = [s for s in steps if (s["segment_id"], s["component_id"]) == key]
        if not own_steps:
            continue
        segment, component = components[key]
        binding = segment.get("bindings", {}).get(key[1], {})
        if "brief_sha256" in binding or "execution_mode" in binding:
            continue  # Existing bytes and completion identities must still pass the normal gates.
        candidate = catalog.get(assignment.get("candidate_id"))
        if (candidate is None or candidate["capability"]["content_scope"]["mode"] != "full_scene"
                or candidate["status"] != "supported"
                or component.get("kind") != ("ai_generated" if candidate["role"] == "design" else "code_generated")):
            raise VisualConfirmationError("planned generation requires this component's selected full-scene route")
        if any(assignment.get(k) != candidate[k] for k in ("skill_id", "template_id", "entrypoint")):
            raise VisualConfirmationError("planned generation route differs from the selected candidate")
        beat = next((b for b in selection.get("beats", [])
                     if (b.get("segment_id"), b.get("component_id")) == key), None)
        review = next((r for r in (beat or {}).get("candidates", [])
                       if r.get("candidate_id") == candidate["candidate_id"]), None)
        if (beat is None or beat.get("binding_snapshot") != binding or review is None
                or review.get("fit") not in {"preferred", "equivalent"}
                or key in scenes and set(scenes[key]) != {"segment_id", "component_id"}):
            raise VisualConfirmationError("planned inputs need the current reviewed target, not an existing or invented brief")
        if job_dir is None:
            raise VisualConfirmationError("planned generation needs the current Job configuration")
        if config is None:
            config_path, _ = startup._config(SimpleNamespace(job_dir=Path(job_dir)))
            config = _read(config_path)
            channels = startup.selected_channels(config)
        image_inputs = {}
        for step in own_steps:
            channel = channels.get(step["purpose"])
            if channel is None:
                raise VisualConfirmationError("planned generation has no selected channel for its purpose")
            arguments = generation_model.prepare_arguments(
                job_dir, {**channel, "purpose": step["purpose"]}, step["arguments"])
            generation_model.request_identity(job_dir, {"purpose": step["purpose"],
                "tool": channel["endpoint_id"], "arguments": arguments}, config)
            generation_inputs._binding(job_dir, step["purpose"])
            for ref in step.get("input_files", []):
                _exact(Path(job_dir), ref)
            local_arguments = dict(arguments)
            if "referenced_image_paths" in arguments:
                refs = arguments["referenced_image_paths"]
                if not isinstance(refs, list):
                    raise VisualConfirmationError("reference image paths must be a list")
                # Dependency objects were checked above; actual paths retain
                # the queue's frozen-file contract before proposal publication.
                local_arguments["referenced_image_paths"] = [
                    ref for ref in refs if not isinstance(ref, dict) or "$step" not in ref]
            generation_queue._inputs(Path(job_dir), {
                "arguments": local_arguments, "input_files": step.get("input_files", [])})
            actual_refs = generation_inputs._references(Path(job_dir), {
                "arguments": arguments, "input_files": step.get("input_files", [])})
            image_inputs[step["id"]] = any(
                Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                for path, _ in actual_refs)
        purposes = {s["purpose"] for s in own_steps}
        if candidate["role"] == "design":
            if any(k in binding for k in ("generation_id", "prompt_sha256", "sha256")):
                raise VisualConfirmationError("planned AI binding must omit completed generation identity")
            final = own_steps[-1]
            # Only arguments explicitly referenced by this request reach it;
            # depends_on and an earlier video's image inputs do not transfer images.
            image_reference = image_inputs[final["id"]] or any(
                by_step[dep]["purpose"] == "image" for dep in referenced_steps[final["id"]])
            if (final["purpose"] != "video"
                    or not image_reference):
                raise VisualConfirmationError("planned design needs its image input and final video step")
            expected = channels["video"]
            if set(binding) != {"provider", "model", "endpoint_id"} or any(
                    binding.get(k) != expected[k] for k in expected):
                raise VisualConfirmationError("planned design binding differs from the selected video channel")
        else:
            fields = {"producer_type", "dependency_id", "entrypoint", "producer_version", "template_id", "primary_renderer"}
            if (set(binding) != fields or binding.get("producer_type") != "dependency"
                    or not isinstance(binding.get("primary_renderer"), str) or not binding["primary_renderer"]
                    or any(binding.get(k) != candidate[k] for k in
                           ("dependency_id", "entrypoint", "producer_version", "template_id"))):
                raise VisualConfirmationError("planned native binding must retain only its real execution identity")
            if candidate["dependency_id"] in {"lemo-wake", "paper-collage-hyperframes"} and "image" not in purposes:
                raise VisualConfirmationError("this planned native route needs its own image step")
        planned.add(key)
    return planned

def _semantic_tags(query):
    """Return the explicit semantic retrieval labels authored for this row."""
    tags = query.get("tags", []) if isinstance(query, dict) else []
    if (not isinstance(tags, list) or not tags
            or any(not isinstance(tag, str) or not tag.strip() for tag in tags)):
        raise VisualConfirmationError("each visual row needs explicit semantic retrieval tags")
    return list(dict.fromkeys(tag.strip() for tag in tags))

def _source_id(binding):
    for key in ("material_id", "source_id", "asset_id", "provider_asset_id", "job_path", "generation_id"):
        value = binding.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None

def _numbering_scope(treatment):
    """Require an explicit stable scope for every newly prepared proposal."""
    scope = treatment.get("numbering_scope_id") if isinstance(treatment, dict) else None
    if not isinstance(scope, str) or not scope.strip():
        raise VisualConfirmationError(
            "new visual proposals require treatment.numbering_scope_id"
        )
    return scope.strip()


def _prior_numbering(job, numbering_scope_id):
    """Read the latest approved mapping in this Job and numbering scope."""
    candidates = []
    for path in (Path(job.job_dir) / "manifests").glob("local-qa-visual_direction-r*.json"):
        receipt = _read(path)
        if receipt.get("source_schema") != SCHEMA or receipt.get("job_id") != job.job_id:
            continue
        if (receipt.get("job_dir") != str(job.job_dir) or receipt.get("stage") != "visual_direction"
                or receipt.get("passed") is not True or receipt.get("reviewed_by") != "human"
                or receipt.get("approval_scope") != "visual_plan_and_delivery"
                or type(receipt.get("revision")) is not int or receipt["revision"] > job.revision):
            raise VisualConfirmationError("invalid approved visual source")
        try:
            source = receipt.get("source")
            if not isinstance(source, dict):
                raise VisualConfirmationError("approved visual source descriptor is invalid")
            proposal_path = _exact(job.job_dir, source)
            proposal = _read(proposal_path)
            if proposal.get("job_id") != job.job_id or proposal.get("job_dir") != str(job.job_dir) or proposal.get("kind") != SCHEMA:
                raise VisualConfirmationError("approved visual proposal belongs to another Job")
            # A proposal from another planning scope is a separate numbering
            # universe.  Scope-less historical proposals remain readable, but
            # are intentionally not inherited by a newly scoped proposal.
            if proposal.get("numbering_scope_id") != numbering_scope_id:
                continue
            rows = proposal.get("rows", [])
            numbering = proposal.get("numbering")
            if numbering is not None:
                _validate_numbering(numbering)
                if any(row.get("semantic_row_id", row["row_id"]) not in numbering for row in rows):
                    raise VisualConfirmationError("approved numbering is incomplete")
                mapping = dict(numbering)
            else:
                mapping = {row["row_id"]: index for index, row in enumerate(rows, 1)
                           if isinstance(row, dict) and isinstance(row.get("row_id"), str)}
            candidates.append((int(receipt.get("revision", 0)), mapping))
        except VisualConfirmationError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise VisualConfirmationError("approved visual source is unreadable") from exc
    return max(candidates, key=lambda item: item[0])[1] if candidates else {}


def _validate_numbering(mapping):
    if (not isinstance(mapping, dict)
            or any(not isinstance(k, str) or not k or type(v) is not int or v < 1
                   for k, v in mapping.items())
            or len(set(mapping.values())) != len(mapping)):
        raise VisualConfirmationError("invalid or duplicate visual numbers")


def number_visual_rows(rows, numbering=None):
    """Apply a frozen sparse row-id mapping; never recycle deleted numbers."""
    mapping = dict(numbering or {})
    _validate_numbering(mapping)
    ids = [r.get("row_id") for r in rows]
    if any(not isinstance(r, str) or not r for r in ids) or len(set(ids)) != len(ids):
        raise VisualConfirmationError("visual row ids must be unique")
    next_number = max(mapping.values(), default=0) + 1
    numbered = []
    for row in rows:
        identity = row.get("semantic_row_id", row["row_id"])
        if not isinstance(identity, str) or not identity:
            raise VisualConfirmationError("semantic row identity must be stable")
        if identity not in mapping:
            mapping[identity] = next_number
            next_number += 1
        numbered.append({**row, "number": mapping[identity]})
    return numbered

def approved_numbered_rows(job):
    proposal = validate_visual_authorization(job)["source"]
    return number_visual_rows(proposal["rows"], proposal.get("numbering"))

def approved_body_opening(job):
    """Read an explicit body opening from the already confirmed treatment."""
    proposal = validate_visual_authorization(job)["source"]
    treatment = _read(_exact(job.job_dir, proposal["inputs"]["treatment"]))
    return treatment.get("skill_selection", {}).get("opening")

def _rows(director, treatment, speech, semantic_rows=None, generation_channels=None, *, job_dir=None):
    from .broll_skill_selection import source_channel
    from .semantic_visual_plan import component_use

    queries = {(q["segment_id"], q["component_id"]): q for q in treatment.get("motion_queries", [])}
    selected = treatment.get("skill_selection", {})
    steps = _steps(treatment)
    assignments = {(q["segment_id"], q["component_id"]): q
                   for q in [*selected.get("assignments", []), *selected.get("overlay_assignments", [])]}
    rows = []
    for segment in director["segments"]:
        sid = segment["segment_id"]
        spoken = "".join(w["text"] for w in speech or []
                         if w["start"] < segment["end"] and w["end"] > segment["start"])
        for component in segment["visual_strategy"]["components"]:
            cid = component["component_id"]
            binding = segment.get("bindings", {}).get(cid, {})
            tags = _semantic_tags(queries.get((sid, cid), {}))
            source = _source_id(binding)
            direct_material = component["kind"] in {"local_material", "official_material", "external_stock"}
            chosen = assignments.get((sid, cid))
            fixed = next((r for r in selected.get("fixed_context", [])
                          if (r["segment_id"], r["component_id"]) == (sid, cid)), None)
            fixed_route = None
            if fixed is not None:
                from .broll_skill_selection import fixed_identity
                fixed_route = fixed_identity(fixed, job_dir=job_dir)
            template = ("素材直用（无动效模板）" if direct_material else binding.get("template_id"))
            if chosen is not None and not direct_material:
                template = chosen["template_id"]
            elif fixed_route and fixed_route.get("template_id"):
                template = fixed_route["template_id"]
            if not template and component["kind"] == "ai_generated":
                planned = [step["id"] for step in _steps(treatment) if
                           (step["segment_id"], step["component_id"]) == (sid, cid)]
                if not planned and not binding.get("generation_id") and not source:
                    raise VisualConfirmationError("direct AI B-roll needs an explicit generation plan or completed result")
                template = ("AI生成方案：" + (" → ".join(planned) or binding["generation_id"])
                            if planned or binding.get("generation_id") else "AI生成结果（无动效模板）")
            if not template:
                raise VisualConfirmationError("each visual row needs its actual template or material source")
            physical_id = sid + ":" + cid
            semantic_row = semantic_rows.get((sid, cid)) if semantic_rows else None
            if semantic_row is None or semantic_row["type"] != ("贴片" if component_use(segment, component) == "overlay" else "B-roll"):
                raise VisualConfirmationError("visual component is missing from semantic lists")
            generation = []
            for purpose in dict.fromkeys(s["purpose"] for s in steps
                    if (s["segment_id"], s["component_id"]) == (sid, cid)):
                channel = (generation_channels or {}).get(purpose, {})
                if channel.get("provider"):
                    generation.append(("图片：" if purpose == "image" else "视频：") +
                                      channel["provider"] + " / " + channel["model"])
            if not generation and binding.get("provider"):
                generation.append(binding["provider"] + (" / " + binding["model"] if binding.get("model") else ""))
            direct_steps = [s for s in steps if (s["segment_id"], s["component_id"]) == (sid, cid)]
            direct_service = ((generation_channels or {}).get(direct_steps[-1]["purpose"], {}).get("provider", "")
                              if direct_steps else "")
            rows.append({"row_id": physical_id, "semantic_row_id": semantic_row.get("row_id"),
                         "segment_id": sid, "component_id": cid,
                         "start": segment["start"], "end": segment["end"],
                         "type": semantic_row["type"],
                         "spoken_text": spoken, "semantic": segment["visual_intent"]["statement"],
                         "tags": tags, "source": source,
                         "generation_channel": "；".join(generation),
                         "channel": (source_channel(chosen["skill_id"]) if chosen else
                                     source_channel(fixed_route["skill_id"]) if fixed_route else
                                     direct_service if component["kind"] == "ai_generated" else
                                     source_channel(binding.get("dependency_id") or binding.get("provider") or component["kind"])),
                         "template": template})
    return rows

def _routing_distribution(rows, treatment):
    """Summarize logical rows, channel exposure, and adjacent repeats for routing.md."""
    selection = treatment.get("skill_selection", {}) or {}
    choices = [*selection.get("assignments", []), *selection.get("overlay_assignments", [])]
    assignments = {(a["segment_id"], a["component_id"]): a for a in choices}
    from . import broll_skill_selection
    def channel(item):
        return broll_skill_selection.source_channel(item["channel"])
    def reason(item):
        for source in (item, assignments.get((item["segment_id"], item["component_id"]), {})):
            for key in ("selection_reason", "reason", "style_reason"):
                if str(source.get(key, "")).strip(): return str(source[key]).strip()
            if str(source.get("source_ref", "")).strip(): return "固定素材：" + str(source["source_ref"]).strip()
        return "未记录选择原因"
    logical = {}
    ordered = sorted(rows, key=lambda r: (float(r["start"]), str(r["row_id"])))
    for row in ordered:
        key = row["semantic_row_id"]
        logical.setdefault(key, {"row": row, "rows": []})["rows"].append(row)
    summary = {"贴片": {"logical_count": 0, "channels": {}}, "B-roll": {"logical_count": 0, "channels": {}}}
    intervals_by_bucket_channel = {}
    for group in logical.values():
        bucket = summary[group["row"]["type"]]
        bucket["logical_count"] += 1
        by_channel = {}
        for item in group["rows"]:
            if channel(item):
                by_channel.setdefault(channel(item), []).append(item)
        for name, parts in by_channel.items():
            entry = bucket["channels"].setdefault(name, {"count": 0, "duration": 0.0})
            entry["count"] += 1
            intervals_by_bucket_channel.setdefault((group["row"]["type"], name), []).extend(
                (float(p["start"]), float(p["end"])) for p in parts if float(p["end"]) > float(p["start"]))
    for (typ, name), intervals in intervals_by_bucket_channel.items():
        merged = []
        for begin, end in sorted(intervals):
            if merged and begin <= merged[-1][1]: merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else: merged.append((begin, end))
        summary[typ]["channels"][name]["duration"] = sum(end - begin for begin, end in merged)
    repeats, previous = [], None
    for row in ordered:
        pattern = row.get("visual_pattern") or assignments.get((row["segment_id"], row["component_id"]), {}).get("visual_pattern")
        current = (channel(row), pattern, float(row["end"]), float(row["start"]))
        if previous and row["semantic_row_id"] != previous[2]:
            same_channel = bool(current[0]) and current[0] == previous[1][0]
            same_pattern = current[1] and previous[1][1] and current[1] == previous[1][1]
            if same_channel or same_pattern:
                labels = (["同渠道：" + current[0]] if same_channel else []) + (["同构图/动作：" + current[1]] if same_pattern else [])
                relation = "同屏重叠" if current[3] < previous[1][2] else ("连续" if current[3] == previous[1][2] else "有时间间隔")
                repeats.append((previous[0], row.get("number", row["semantic_row_id"]), "；".join(labels) + "；" + relation, reason(row)))
        previous = (row.get("number", row["semantic_row_id"]), current, row["semantic_row_id"])
    return summary, repeats

def _validate_template_choices(job, director, treatment):
    from . import broll_skill_selection, motion_match_cache, overlay_selection
    project = Path(__file__).resolve().parents[3]
    selection = treatment.get("skill_selection", {})
    bindings = {(s["segment_id"], cid): value for s in director["segments"]
                for cid, value in s.get("bindings", {}).items()}
    for beat in [*selection.get("beats", []), *selection.get("overlay_beats", [])]:
        key = (beat.get("segment_id"), beat.get("component_id"))
        if not isinstance(bindings.get(key), dict) or beat.get("binding_snapshot") != bindings[key]:
            raise VisualConfirmationError("joint selected binding snapshot is missing or stale: " + str(key))
    cached = motion_match_cache.validate_reviews(project, director, treatment, job_dir=job.job_dir)
    if selection:
        chosen = broll_skill_selection.assign_skills(project, selection, job_dir=job.job_dir,
                                                       director=director, treatment=treatment)
        broll_skill_selection.validate_fixed_materials(director, selection, job_dir=job.job_dir)
        if (chosen["assignments"] != selection.get("assignments")
                or chosen["overlay_assignments"] != selection.get("overlay_assignments", [])):
            raise VisualConfirmationError("complete-list template assignments have not been resolved")
    candidates = {(a["segment_id"], a["component_id"]): a["candidate_id"]
                  for a in [*selection.get("assignments", []), *selection.get("overlay_assignments", [])]}
    for segment in director["segments"]:
        for component in segment["visual_strategy"]["components"]:
            sid, cid = segment["segment_id"], component["component_id"]
            if component["kind"] not in {"code_generated", "ai_generated"}:
                continue
            candidate = candidates.get((sid, cid))
            if segment["visual_strategy"]["composition"]["family"] == "aroll_with_overlay":
                actual = "overlay:" + overlay_selection._route(segment["bindings"][cid])
                if candidate != actual:
                    raise VisualConfirmationError("A-roll overlay differs from the joint maximum assignment")
            if candidate is None and component["kind"] == "ai_generated":
                continue  # Explicit direct generation is a material source, not a library template.
            matches = {m["candidate"]["candidate_id"]: m["candidate"] for m in cached[(sid, cid)]["matches"]}
            if candidate not in matches:
                raise VisualConfirmationError("the selected template does not match this row's semantic tags")
            native = matches[candidate]
            if component["kind"] == "code_generated" and any(
                    segment["bindings"][cid].get(field) != native[field]
                    for field in ("dependency_id", "entrypoint", "producer_version", "template_id")):
                raise VisualConfirmationError("proposed binding differs from the selected native template")
    planned = planned_generation_targets(project, director, treatment, job_dir=job.job_dir)
    motion_match_cache.validate_design_handoffs(director, treatment, job.job_dir, planned_targets=planned)

def _validate_beat_sheet(treatment, director, speech):
    from .semantic_visual_plan import component_use, require_interval_coverage
    beats = treatment.get("beat_sheet")
    if not isinstance(beats, list) or not beats:
        raise VisualConfirmationError("new visual proposals require treatment.beat_sheet")
    words = speech or []
    components = {(s["segment_id"], c["component_id"]): (s, c)
                  for s in director.get("segments", [])
                  for c in s.get("visual_strategy", {}).get("components", [])}
    cursor = 0
    component_beats = {}
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    for beat in beats:
        if not isinstance(beat, dict):
            raise VisualConfirmationError("beat_sheet entries must be objects")
        start, end = beat.get("start_word"), beat.get("end_word")
        if (type(start) is not int or type(end) is not int or start != cursor
                or not start < end <= len(words)):
            raise VisualConfirmationError("beat_sheet must cover approved words without gaps or overlaps")
        if beat.get("quote") != "".join(w["text"] for w in words[start:end]):
            raise VisualConfirmationError("beat_sheet quote does not match approved cut words")
        decision = beat.get("decision")
        if decision not in {"broll", "overlay", "aroll"} or not text(beat.get("visual")):
            raise VisualConfirmationError("beat_sheet entries need decision and visual")
        refs = beat.get("components")
        if (not isinstance(refs, list)
                or any(not isinstance(r, dict) or set(r) != {"segment_id", "component_id"}
                       or type(r["segment_id"]) is not str or not r["segment_id"]
                       or type(r["component_id"]) is not str or not r["component_id"] for r in refs)
                or len({(r["segment_id"], r["component_id"]) for r in refs}) != len(refs)):
            raise VisualConfirmationError("beat_sheet components must be unique references")
        if "merge_reason" in beat and not text(beat["merge_reason"]):
            raise VisualConfirmationError("merge_reason must be a non-empty string")
        if decision == "aroll":
            begin, finish = words[start]["start"], words[end - 1]["end"]
            if refs or not text(beat.get("reason")):
                raise VisualConfirmationError("aroll beats need a concrete reason and no visual component")
            presenter = [s for s in director.get("segments", [])
                         if s.get("visual_strategy", {}).get("composition", {}).get("family") == "no_broll"
                         and s.get("visual_strategy", {}).get("composition", {}).get("presenter_mode") == "full_frame"
                         and s.get("visual_strategy", {}).get("mode") == "none"
                         and not s.get("visual_strategy", {}).get("components")]
            presenter.sort(key=lambda s: s["start"])
            try:
                require_interval_coverage([(s["start"], s["end"]) for s in presenter],
                    begin, finish, label="aroll beat full-frame/no-broll interval")
            except ValueError as error:
                raise VisualConfirmationError(str(error)) from error
        else:
            if not refs:
                raise VisualConfirmationError("broll and overlay beats need visual components")
            if len(refs) > 1 and not text(beat.get("merge_reason")):
                raise VisualConfirmationError("merged beats need merge_reason")
            begin, finish = words[start]["start"], words[end - 1]["end"]
            covered = []
            for ref in refs:
                key = (ref.get("segment_id"), ref.get("component_id")) if isinstance(ref, dict) else None
                if key not in components:
                    raise VisualConfirmationError("beat_sheet references an unknown visual component")
                segment, component = components[key]
                covered.append((segment["start"], segment["end"]))
                family = segment.get("visual_strategy", {}).get("composition", {}).get("family")
                is_overlay = component_use(segment, component) == "overlay"
                if (decision == "overlay") != is_overlay:
                    raise VisualConfirmationError("beat_sheet decision does not match component use")
                component_beats.setdefault(key, []).append(beat)
            try:
                require_interval_coverage(covered, begin, finish, label="beat_sheet components")
            except ValueError as error:
                raise VisualConfirmationError(str(error)) from error
        cursor = end
    if cursor != len(words):
        raise VisualConfirmationError("beat_sheet does not cover the complete approved speech")
    for reused in component_beats.values():
        if len(reused) > 1 and any(not text(beat.get("merge_reason")) for beat in reused):
            raise VisualConfirmationError("a component reused across beats needs merge_reason on each beat")

def prepare_visual_confirmation(job, director_path, treatment_path, reviewed_visual_text=None):
    from . import state, visual_plan, motion_capabilities, startup, confirmed_content
    state.require_runnable(job, "visual_direction")
    director, treatment = _read(director_path), _read(treatment_path)
    numbering_scope_id = _numbering_scope(treatment)
    visual_plan._validate_draft_envelope(director)
    from . import segment_render
    for segment in director["segments"]:
        segment_id = segment.get("segment_id")
        if type(segment_id) is not str or not segment_render.re_full_segment_id(segment_id):
            raise VisualConfirmationError(
                f"director segment_id is not renderable: {segment_id!r}"
            )
    context = visual_plan._validate_job_context(job, director, reviewed_visual_text)
    from . import wake_opening
    wake_opening.validate(job, director, treatment)
    confirmed_content.check_confirmed_content(job, director, treatment=treatment)
    steps = _steps(treatment)
    try:
        _validate_template_choices(job, director, treatment)
    except ValueError as error:
        raise VisualConfirmationError("visual selection: " + str(error)) from error
    from . import overlay_alignment
    overlay_alignment.validate_treatment(job, director, Path(treatment_path), phase='planning')
    from . import motion_readability
    motion_readability.validate_direction_contract(job, director, treatment, phase='planning')
    from . import avatar_profile, visual_review
    avatar_profile.validate_avatar_plan_policy(director["segments"])
    speech = motion_capabilities._approved_speech(job.job_dir)
    from . import semantic_visual_plan
    semantic_plan = semantic_visual_plan.validate_semantic_lists(treatment, director, speech)
    config_path, config_sha = startup._config(job)
    config = _read(config_path)
    channels = startup.selected_channels(config) if steps else {}
    rows = _rows(director, treatment, speech, semantic_plan["component_rows"], channels, job_dir=job.job_dir)
    _validate_beat_sheet(treatment, director, speech)
    from . import visual_coverage
    coverage = visual_coverage.require_density({"duration": context[5], "segments": director["segments"]}, treatment=treatment)
    if coverage["blocking_issues"]:
        raise VisualConfirmationError("time coverage: " + "; ".join(coverage["blocking_issues"])
            + "; return to the affected semantic list, add a distinct supported task, match only new items and assign again")
    numbering = _prior_numbering(job, numbering_scope_id)
    numbered_rows = number_visual_rows(rows, numbering)
    numbering = {**numbering, **{row["semantic_row_id"]: row["number"] for row in numbered_rows}}
    targets = {(r["segment_id"], r["component_id"]) for r in rows}
    for step in steps:
        if (step.get("segment_id"), step.get("component_id")) not in targets:
            raise VisualConfirmationError("generation step has no visual row")
        for ref in step.get("input_files", []):
            _exact(job.job_dir, ref)
        from . import generation_model
        channel = {**channels[step["purpose"]], "purpose": step["purpose"]}
        generation_model.request_identity(job.job_dir, {
            "purpose": step["purpose"], "tool": channel["endpoint_id"],
            "arguments": generation_model.prepare_arguments(job.job_dir, channel, step["arguments"]),
        }, config)
    if steps:
        for segment in director["segments"]:
            for cid, binding in segment.get("bindings", {}).items():
                direct = any(c["component_id"] == cid and c["kind"] == "ai_generated" for c in segment["visual_strategy"]["components"])
                if direct and any((step["segment_id"], step["component_id"]) == (segment["segment_id"], cid) for step in steps):
                    if (any(key in binding for key in ("generation_id", "prompt_sha256", "sha256"))
                            and binding.get("execution_mode") not in {
                                "reuse_completed_generated_media", "reuse_completed_lovart_video"}):
                        raise VisualConfirmationError(
                            "planned AI binding must omit completed generation identity; use generation step IDs until the real result exists")
                    final_step = [step for step in steps if (step["segment_id"], step["component_id"]) == (segment["segment_id"], cid)][-1]
                    chosen = channels[final_step["purpose"]]
                    if any(key in binding and binding[key] != chosen[key] for key in ("provider", "model", "endpoint_id")):
                        raise VisualConfirmationError("AI row differs from this Job selected generation channel")
    content = {"director": director, "treatment": treatment, "reviewed_visual_text": reviewed_visual_text}
    source_id = artifacts.sha256_json(content)[:16]
    root = job.job_dir / DIRECTORY / f"r{job.revision}-{source_id}"
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, value in content.items():
        if value is not None:
            path = root / (name + ".json")
            artifacts.write_json_artifact(path, value)
            files[name] = _record(job.job_dir, path)
    proposal = {"schema_version": 1, "kind": SCHEMA, "source_id": source_id,
                "job_id": job.job_id, "job_dir": str(job.job_dir), "revision": job.revision,
                "inputs": files, "provider_config_sha256": config_sha,
                "rows": rows, "numbering_scope_id": numbering_scope_id,
                "semantic_summary": {k: semantic_plan[k] for k in ("overlay_count", "broll_count")},
                "numbering": numbering, "generation_steps": steps,
                "visual_review_policy": visual_review.POLICY_VERSION,
                "query_bindings": _record(job.job_dir, job.job_dir / "manifests/generation-channels.json")
                    if (job.job_dir / "manifests/generation-channels.json").is_file() else None}
    proposal_path = root / "proposal.json"
    artifacts.write_json_artifact(proposal_path, proposal)
    def cell(value):
        return str(value).replace("|", "／").replace("\n", "<br>")
    lines = ["# 本视频贴片与 B-roll 完整清单", "",
             "## 贴片语义列表", "", "| 原话 | 独立语义 | 画面任务 |", "|---|---|---|"]
    for row in semantic_plan["items"]:
        if row["type"] == "贴片":
            lines.append("| " + " | ".join(cell(row[k]) for k in ("quote", "semantic", "visual_task")) + " |")
    lines += ["", "## B-roll 语义列表", "", "| 原话 | 独立语义 | 画面任务 |", "|---|---|---|"]
    for row in semantic_plan["items"]:
        if row["type"] == "B-roll":
            lines.append("| " + " | ".join(cell(row[k]) for k in ("quote", "semantic", "visual_task")) + " |")
    lines += ["", f"语义清单摘要：贴片{semantic_plan['overlay_count']}处 / B-roll{semantic_plan['broll_count']}项 / 合计{len(semantic_plan['items'])}", "",
             "时间为剪后正文时间，最终成片按封面时长统一偏移。整表确认后按表制作并直接交付。", "",
             "| 编号 | 时间 | 类型 | 剪后原话 | 语义 | 标签 | 来源渠道 | 生成渠道／模型 | 素材来源 | 匹配动效模板 | 生成步骤 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    display_rows = {}
    for row in numbered_rows:
        display_rows.setdefault(row["semantic_row_id"], []).append(row)
    for identity, parts in display_rows.items():
        row = parts[0]
        semantic_row = next(item for item in semantic_plan["items"] if item["row_id"] == identity)
        part_keys = {(part["segment_id"], part["component_id"]) for part in parts}
        generated = [s for s in steps if (s["segment_id"], s["component_id"]) in part_keys]
        labels = [s["id"] + "：" + ("生图" if s["purpose"] == "image" else "生视频")
                  + ("；" + str(s["description"]) if s.get("description") else "") for s in generated]
        lines.append("| " + " | ".join(cell(v) for v in (
            row["number"], "；".join(dict.fromkeys(f"{p['start']:.3f}–{p['end']:.3f}s" for p in parts)),
            row["type"], semantic_row["quote"], semantic_row["semantic"], "、".join(row["tags"]),
            "、".join(dict.fromkeys(p["channel"] for p in parts if p["channel"])) or "素材直用（创作来源未确认）",
            "；".join(dict.fromkeys(p["generation_channel"] for p in parts if p["generation_channel"])) or "—",
            "、".join(dict.fromkeys(p["source"] for p in parts if p["source"])) or "—",
            "、".join(dict.fromkeys(p["template"] for p in parts)), " → ".join(labels) or "复用/模板渲染")) + " |")
    distribution, repeats = _routing_distribution(numbered_rows, treatment)
    lines += ["", "## 渠道分布（按贴片与 B-roll 分开统计）", ""]
    for typ in ("贴片", "B-roll"):
        bucket = distribution.get(typ, {"logical_count": 0, "channels": {}})
        lines += [f"### {typ}：{bucket['logical_count']} 个逻辑项", "", "| 渠道 | 逻辑项次数 | 累计可见时长 |", "|---|---:|---:|"]
        for name, value in sorted(bucket["channels"].items()):
            lines.append(f"| {cell(name)} | {value['count']} | {value['duration']:.3f}s |")
        if not bucket["channels"]: lines.append("| 未记录 | 0 | 0.000s |")
    lines += ["", "## 相邻重复与当前选择原因", ""]
    if repeats:
        lines += ["| 前项 | 后项 | 重复项 | 当前选择原因 |", "|---|---|---|---|"]
        for before, after, match, why in repeats:
            lines.append("| " + " | ".join(cell(v) for v in (before, after, match, why)) + " |")
    else:
        lines.append("未发现相邻同渠道或同构图/动作项。")
    lines += ["", "## 口播逐句处置", "", "| 词区间 | 实际原话 | 时间 | 决策 | 画面 | 组件 | 合并原因 |", "|---|---|---|---|---|---|---|"]
    for beat in treatment["beat_sheet"]:
        refs = "、".join(r["segment_id"] + ":" + r["component_id"] for r in beat["components"])
        begin = speech[beat["start_word"]]["start"]
        finish = speech[beat["end_word"] - 1]["end"]
        lines.append("| " + " | ".join(cell(v) for v in (
            f"{beat['start_word']}–{beat['end_word']}", beat["quote"], f"{begin:.3f}–{finish:.3f}s",
            beat["decision"], beat["visual"], refs or "A-roll",
            beat.get("merge_reason") or beat.get("reason", ""))) + " |")
    lines += ["", "生成费用说明：" + str(treatment.get("generation_plan", {}).get("cost_note", "按本次已确认渠道和规格执行")), ""]
    table = root / "visual-routing.md"
    artifacts.write_bytes_atomic(table, "\n".join(lines).encode())
    source_files = [proposal_path, table, *(_path(job.job_dir, r["path"]) for r in files.values())]
    state.mark_visual_ready(job, source_files)
    return proposal_path

def _source_from_stage(job):
    records = job.stages["visual_direction"]["artifacts"]
    proposal = next((r for r in records if r["path"].startswith(DIRECTORY + "/")
                     and r["path"].endswith("/proposal.json")), None)
    if proposal:
        return proposal
    mappings = [r for r in records if r["path"].endswith("/" + MAPPING)]
    if len(mappings) > 1:
        raise VisualConfirmationError("the realized visual mapping is ambiguous")
    if mappings:
        return _read(_exact(job.job_dir, mappings[0]))["proposal"]
    # During publication, final V3 exists but the mapping is not registered yet.
    candidates = []
    for path in (job.job_dir / "manifests").glob("local-qa-visual_direction-r*.json"):
        payload = _read(path)
        if payload.get("source_schema") == SCHEMA:
            proposal = payload["source"]
            if payload.get("revision") <= job.revision:
                candidates.append((payload["revision"], proposal))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    raise VisualConfirmationError("the current visual stage has no confirmation proposal")

def save_user_confirmation(job, review):
    proposal_ref = _source_from_stage(job)
    proposal = _read(_exact(job.job_dir, proposal_ref))
    if (review.get("artifacts") != job.stages["visual_direction"]["artifacts"]
            or review.get("revision") != job.revision or not review.get("user_confirmation", "").strip()):
        raise VisualConfirmationError("review must identify the current complete proposal")
    payload = {**review, "source_schema": SCHEMA, "source": proposal_ref,
               "source_id": proposal["source_id"], "reviewed_by": "human",
               "approval_scope": "visual_plan_and_delivery"}
    path = job.job_dir / "manifests" / f"local-qa-visual_direction-r{job.revision}.json"
    if path.exists() and _read(path) != payload:
        raise VisualConfirmationError("this confirmation has already been recorded")
    if not path.exists():
        artifacts.write_json_artifact(path, payload)
    return payload

def _validate_source(root, receipt_ref, *, job_id=None):
    receipt = _read(_exact(root, receipt_ref))
    if (receipt.get("source_schema") != SCHEMA or receipt.get("job_id") != job_id
            or receipt.get("job_dir") != str(root) or receipt.get("stage") != "visual_direction"
            or receipt.get("passed") is not True or receipt.get("reviewed_by") != "human"
            or receipt.get("approval_scope") != "visual_plan_and_delivery"
            or not receipt.get("note", "").strip() or not receipt.get("user_confirmation", "").strip()):
        raise VisualConfirmationError("invalid complete-list confirmation")
    for record in receipt["artifacts"]:
        _exact(root, record)
    proposal = _read(_exact(root, receipt["source"]))
    if proposal.get("job_id") != job_id or proposal.get("kind") != SCHEMA:
        raise VisualConfirmationError("proposal belongs to another Job")
    for record in proposal["inputs"].values():
        _exact(root, record)
    if proposal.get("query_bindings"):
        _exact(root, proposal["query_bindings"])
    config = Path(root) / "manifests/provider-config.json"
    if artifacts.sha256_file(config) != proposal["provider_config_sha256"]:
        raise VisualConfirmationError("selected generation channels changed after confirmation")
    return receipt, proposal

def _paper_referenced_assets(root, brief):
    """Resolve bound Paper assets actually referenced by its frozen scene entry."""
    from html.parser import HTMLParser
    import re
    assets = {item['job_path']: item for item in brief.get('assets', [])}
    if len(assets) != len(brief.get('assets', [])):
        raise VisualConfirmationError('Paper brief asset paths are duplicated')
    entry = brief.get('entry', {})
    entry_path = _path(root, entry['job_path'])
    if artifacts.sha256_file(entry_path) != entry.get('sha256'):
        raise VisualConfirmationError('Paper scene entry changed')
    class AssetReferences(HTMLParser):
        def __init__(self):
            super().__init__(); self.paths = set(); self.in_style = False
        def css(self, text):
            self.paths.update(re.findall(r'''url\(\s*["']?([^"')\s]+)''', text))
        def handle_starttag(self, tag, attrs):
            self.in_style |= tag.lower() == 'style'
            for name, value in attrs:
                if value is not None and name.lower() in {'src', 'href'}:
                    self.paths.add(value)
                if value is not None and name.lower() == 'style':
                    self.css(value)
        def handle_endtag(self, tag):
            if tag.lower() == 'style': self.in_style = False
        def handle_data(self, data):
            if self.in_style: self.css(data)
    references = AssetReferences()
    references.feed(entry_path.read_text(encoding='utf-8'))
    used = {path: asset for path, asset in assets.items() if asset.get('scene_path') in references.paths}
    for path, asset in used.items():
        if artifacts.sha256_file(_path(root, path)) != asset.get('sha256'):
            raise VisualConfirmationError('Paper referenced asset changed')
    return used

def _paper_crop_sources(root, brief, provenance_ref, approved_media):
    """Prove that consumed Paper assets are exact crops of approved source images."""
    from PIL import Image
    provenance = _read(_exact(root, provenance_ref))
    if not isinstance(provenance, dict) or not isinstance(provenance.get('crops'), list):
        raise VisualConfirmationError('Paper crop provenance is invalid')
    sources = provenance.get('source_images')
    if not isinstance(sources, dict) or not sources:
        raise VisualConfirmationError('Paper crop provenance has no source images')
    approved = {(m['path'], m['sha256']) for m in approved_media}
    declared = set()
    for source in sources.values():
        if not isinstance(source, dict) or set(source) != {'path', 'sha256'}:
            raise VisualConfirmationError('Paper source identity is invalid')
        path = _path(root, source['path'])
        if artifacts.sha256_file(path) != source['sha256'] or (source['path'], source['sha256']) not in approved:
            raise VisualConfirmationError('Paper source is not the approved generated image')
        declared.add((source['path'], source['sha256']))
    assets = _paper_referenced_assets(root, brief)
    consumed, outputs = set(), set()
    for crop in provenance['crops']:
        if (not isinstance(crop, dict) or set(crop) != {'source', 'source_sha256', 'crop', 'output', 'output_sha256'}
                or (crop['source'], crop['source_sha256']) not in declared
                or crop['output'] in outputs or crop['output'] not in assets
                or assets[crop['output']].get('sha256') != crop['output_sha256']):
            raise VisualConfirmationError('Paper crop does not identify an approved source and consumed asset')
        outputs.add(crop['output'])
        box = crop['crop']
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
            raise VisualConfirmationError('Paper crop bounds are invalid')
        source, output = _path(root, crop['source']), _path(root, crop['output'])
        if artifacts.sha256_file(output) != crop['output_sha256']:
            raise VisualConfirmationError('Paper crop output changed')
        with Image.open(source) as image, Image.open(output) as actual:
            if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise VisualConfirmationError('Paper crop bounds exceed the source')
            expected = image.crop(tuple(box))
            if actual.mode != expected.mode or actual.size != expected.size or actual.tobytes() != expected.tobytes():
                raise VisualConfirmationError('Paper crop pixels differ from the approved source')
        consumed.add(crop['source_sha256'])
    return consumed

def _normalize_prepared_paper(root, proposal, frozen, frozen_treatment, director, treatment):
    """Compare a completed, originally deferred Paper input as its approved plan."""
    from . import generation_queue, motion_capabilities
    from . import state
    root = Path(root)
    project = Path(__file__).resolve().parents[3]
    eligible = planned_generation_targets(project, frozen, frozen_treatment, job_dir=root)
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    previous_segments = {s['segment_id']: s for s in frozen['segments']}
    current_segments = {s['segment_id']: s for s in current['segments']}
    eligible = {key for key in eligible
                if previous_segments[key[0]]['bindings'][key[1]].get('dependency_id') == 'paper-collage-hyperframes'
                and key[0] in current_segments
                and current_segments[key[0]]['bindings'].get(key[1], {}) != previous_segments[key[0]]['bindings'][key[1]]}
    if not eligible:
        return current, actual
    old_selection, new_selection = frozen_treatment.get('skill_selection', {}), actual.get('skill_selection', {})
    job = state.load_job(root)
    queue = generation_queue.status(root)
    for key in eligible:
        before = previous_segments[key[0]]['bindings'][key[1]]
        after = current_segments[key[0]]['bindings'].get(key[1], {})
        if any(after.get(k) != v for k, v in before.items()):
            raise VisualConfirmationError('prepared Paper binding changed its approved native route')
        old_components = [c for c in previous_segments[key[0]]['visual_strategy']['components'] if c['component_id'] == key[1]]
        new_components = [c for c in current_segments[key[0]]['visual_strategy']['components'] if c['component_id'] == key[1]]
        if len(old_components) != 1 or new_components != old_components:
            raise VisualConfirmationError('prepared Paper changed the approved visual component')
        scenes = [s for s in actual.get('scenes', []) if (s.get('segment_id'), s.get('component_id')) == key]
        old_scenes = [s for s in frozen_treatment.get('scenes', []) if (s.get('segment_id'), s.get('component_id')) == key]
        if (len(scenes) != 1 or len(old_scenes) != 1 or set(old_scenes[0]) != {'segment_id', 'component_id'}
                or set(scenes[0]) != {'segment_id', 'component_id', 'brief_path', 'asset_provenance'}):
            raise VisualConfirmationError('prepared Paper requires its bound brief and explicit crop provenance')
        scene = scenes[0]
        brief_path = _path(root, scene['brief_path'])
        if artifacts.sha256_file(brief_path) != after.get('brief_sha256'):
            raise VisualConfirmationError('prepared Paper brief differs from its binding')
        brief = motion_capabilities._bound_brief(root, actual, current_segments[key[0]], key[1])
        if not isinstance(brief, dict):
            raise VisualConfirmationError('prepared Paper native brief is missing')
        candidate = next((r for r in motion_capabilities.load_catalog(project)
                          if r.get('dependency_id') == 'paper-collage-hyperframes'
                          and r.get('template_id') == before['template_id']), None)
        if not candidate or motion_capabilities._native_input_check(project, candidate, brief, job_dir=root)['status'] != 'pass':
            raise VisualConfirmationError('prepared Paper native inputs are invalid')
        entrypoint = project / 'skill-development/hd-talking-head' / before['entrypoint']
        source_sha = artifacts.sha256_file(entrypoint)
        route_path = project / 'skill-development/vendor/paper-collage-ad-codex/references/hyperframes-route.md'
        if (brief.get('source_pins', {}).get('route') != 'paper-collage-ad/hyperframes'
                or brief['source_pins'].get('sha256') != artifacts.sha256_file(route_path)):
            raise VisualConfirmationError('prepared Paper original route pin changed')
        expected_verification = hashlib.sha256((source_sha + brief['entry']['sha256']).encode()).hexdigest()
        expected_binding = {'source_entrypoint': before['entrypoint'], 'source_sha256': source_sha,
                            'template_version': before['producer_version'], 'template_origin': 'custom_fallback',
                            'adaptation_level': 'structural', 'verification_id': expected_verification,
                            'semantic_families': [brief['template_request']['semantic_family']],
                            'capacity': {'min_units': brief['template_request']['information_units'],
                                         'max_units': brief['template_request']['information_units']}}
        call = after.get('invocation_record', {})
        if (any(after.get(k) != v for k, v in expected_binding.items())
                or not isinstance(after.get('sample_sha256'), str) or len(after['sample_sha256']) != 64
                or any(ch not in '0123456789abcdef' for ch in after['sample_sha256'])
                or not isinstance(call, dict) or call.get('status') != 'planned' or call.get('exit_code') is not None
                or call.get('template_request') != brief['template_request']
                or not isinstance(call.get('argv'), list) or len(call['argv']) != 2
                or call['argv'][1] != before['entrypoint']):
            raise VisualConfirmationError('prepared Paper binding differs from the original native adapter')
        original_segment = previous_segments[key[0]]
        source = brief.get('source_binding', {})
        stage = job.stages.get('edit_structure', {})
        arroll = [r for r in stage.get('artifacts', []) if r['path'] == '06-edit-structure/edited-aroll.mp4']
        if stage.get('status') != 'approved' or len(arroll) != 1:
            raise VisualConfirmationError('prepared Paper needs the approved edited A-roll')
        _exact(root, arroll[0])
        if (source.get('segment_id') != key[0] or source.get('start') != original_segment['start']
                or source.get('end') != original_segment['end'] or source.get('aroll_sha256') != arroll[0]['sha256']):
            raise VisualConfirmationError('prepared Paper source clock or A-roll differs')
        own_steps = [step for step in proposal['generation_steps']
                     if (step['segment_id'], step['component_id']) == key]
        approved = []
        for step in own_steps:
            rid, item = generation_item(queue, proposal, step, job)
            if not item or item.get('status') != 'completed':
                raise VisualConfirmationError('prepared Paper needs the approved completed generation')
            origin = queue['items'][item.get('plan_request_id', rid)]
            auth = origin.get('authorization')
            if not auth or validate_generation_request(job, auth, origin['request'])['step']['id'] != step['id']:
                raise VisualConfirmationError('prepared Paper generation differs from its approval')
            if rid != item.get('plan_request_id', rid):
                plan = item.get('image_edit_plan', {})
                if (origin.get('status') != 'completed' or item.get('retry_of') != item.get('plan_request_id') or plan.get('from_id') != item.get('retry_of')
                        or plan.get('request') != item.get('request') or type(plan.get('count')) is not int or plan['count'] != 1
                        or item.get('channel_identity') != origin.get('channel_identity') or item.get('config_sha256') != origin.get('config_sha256')
                        or item.get('request', {}).get('tool') != origin['request']['tool'] or item['request'].get('purpose') != 'image'
                        or artifacts.sha256_json(plan) != item.get('approved_plan_sha256')
                        or not isinstance(item.get('user_confirmation'), str) or not item['user_confirmation'].strip()):
                    raise VisualConfirmationError('prepared Paper image edit authorization changed')
                originals = origin.get('completion_response', {}).get('artifacts', [])
                if len(originals) != 1 or originals[0].get('type') != 'image':
                    raise VisualConfirmationError('prepared Paper image edit original is ambiguous')
                source_path = Path(originals[0]['path'])
                if not source_path.is_absolute(): source_path = root / source_path
                original_ref = _record(root, source_path)
                if ((original_ref['sha256'], original_ref['bytes']) != (originals[0]['sha256'], originals[0]['bytes'])
                        or item['request'].get('input_files') != [original_ref]
                        or item['request'].get('arguments', {}).get('referenced_image_paths') != [str(source_path)]):
                    raise VisualConfirmationError('prepared Paper edit original image changed')
                if 'followup_evidence' in plan:
                    approved_step = validate_generation_request(job, auth, origin['request'])
                    generation_queue._validate_followup_image_evidence(job, origin, plan, approved_step)
                elif plan.get('issue') != origin.get('completion_response', {}).get('conclusion'):
                    raise VisualConfirmationError('prepared Paper image edit visual review changed')
            for media in item['completion_response']['artifacts']:
                path = Path(media['path'])
                ref = _record(root, path if path.is_absolute() else root / path)
                if (ref['sha256'], ref['bytes']) != (media['sha256'], media['bytes']):
                    raise VisualConfirmationError('prepared Paper generated media changed')
                approved.append(ref)
        if not own_steps or any(s['purpose'] != 'image' for s in own_steps):
            raise VisualConfirmationError('prepared Paper needs its approved image steps')
        provenance = scene['asset_provenance']
        if not isinstance(provenance, dict) or set(provenance) != {'job_path', 'sha256', 'byte_count'}:
            raise VisualConfirmationError('prepared Paper crop provenance is invalid')
        pref = {'path': provenance['job_path'], 'sha256': provenance['sha256'], 'bytes': provenance['byte_count']}
        consumed = _paper_crop_sources(root, brief, pref, approved)
        for asset in _paper_referenced_assets(root, brief).values():
            consumed.add(asset['sha256'])
        if not {item['sha256'] for item in approved} <= consumed:
            raise VisualConfirmationError('prepared Paper did not consume every approved source image')
        for group in ('beats', 'overlay_beats'):
            old = [b for b in old_selection.get(group, []) if (b['segment_id'], b['component_id']) == key]
            new = [b for b in new_selection.get(group, []) if (b['segment_id'], b['component_id']) == key]
            if old or new:
                if (len(old) != 1 or len(new) != 1 or new[0].get('binding_snapshot') != after
                        or {k: v for k, v in old[0].items() if k != 'binding_snapshot'} !=
                           {k: v for k, v in new[0].items() if k != 'binding_snapshot'}):
                    raise VisualConfirmationError('prepared Paper changed its approved semantic beat')
                new[0]['binding_snapshot'] = copy.deepcopy(old[0]['binding_snapshot'])
        current_segments[key[0]]['bindings'][key[1]] = copy.deepcopy(before)
    return current, actual

def _normalize_prepared_wake(root, proposal, frozen, frozen_treatment, director, treatment):
    """Bind an approved deferred Wake image to its original native route."""
    from . import generation_queue, state
    root = Path(root)
    project = Path(__file__).resolve().parents[3]
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    old_segments = {s['segment_id']: s for s in frozen['segments']}
    new_segments = {s['segment_id']: s for s in current['segments']}
    eligible = planned_generation_targets(project, frozen, frozen_treatment, job_dir=root)
    keys = {key for key in eligible if old_segments[key[0]]['bindings'][key[1]].get('dependency_id') == 'lemo-wake'
            and key[0] in new_segments
            and new_segments[key[0]]['bindings'].get(key[1], {}) != old_segments[key[0]]['bindings'][key[1]]}
    if not keys:
        return current, actual
    job = state.load_job(root)
    authorized = validate_visual_authorization(job)
    if authorized['source'] != proposal:
        raise VisualConfirmationError('prepared Wake needs the current approved proposal')
    queue = generation_queue.status(root)
    adapter = _native_result_adapter('lemo-wake')
    old_selection, new_selection = frozen_treatment.get('skill_selection', {}), actual.get('skill_selection', {})
    for key in keys:
        old_segment, segment = old_segments[key[0]], new_segments[key[0]]
        before, after = old_segment['bindings'][key[1]], segment['bindings'][key[1]]
        if any(after.get(k) != v for k, v in before.items()):
            raise VisualConfirmationError('prepared Wake changed its approved native route')
        old_components = [x for x in old_segment['visual_strategy']['components'] if x['component_id'] == key[1]]
        new_components = [x for x in segment['visual_strategy']['components'] if x['component_id'] == key[1]]
        if len(old_components) != 1 or new_components != old_components:
            raise VisualConfirmationError('prepared Wake changed its approved visual component')
        old_scenes = [x for x in frozen_treatment.get('scenes', []) if (x.get('segment_id'), x.get('component_id')) == key]
        scenes = [x for x in actual.get('scenes', []) if (x.get('segment_id'), x.get('component_id')) == key]
        if (len(old_scenes) != 1 or set(old_scenes[0]) != {'segment_id', 'component_id'}
                or len(scenes) != 1 or set(scenes[0]) != {'segment_id', 'component_id', 'brief_path'}):
            raise VisualConfirmationError('prepared Wake requires its original deferred scene and one bound brief')
        payload = _path(root, scenes[0]['brief_path']).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        brief = adapter.validate_brief(payload)
        if digest != after.get('brief_sha256') or brief['job_id'] != job.job_id or 'revision' in brief:
            raise VisualConfirmationError('prepared Wake brief identity differs from its binding')
        assignments = [a for a in old_selection.get('assignments', []) if (a.get('segment_id'), a.get('component_id')) == key]
        if (len(assignments) != 1 or assignments[0].get('candidate_id') != 'lemo-wake:wake'
                or brief['semantic_goal'] != assignments[0].get('design_plan', {}).get('focus')):
            raise VisualConfirmationError('prepared Wake semantic goal differs from its approved focus')
        stage = job.stages.get('edit_structure', {})
        aroll = [r for r in stage.get('artifacts', []) if r['path'] == '06-edit-structure/edited-aroll.mp4']
        if stage.get('status') != 'approved' or len(aroll) != 1:
            raise VisualConfirmationError('prepared Wake needs the approved edited A-roll')
        _exact(root, aroll[0])
        expected_clock = {'aroll_sha256': aroll[0]['sha256'], 'segment_id': key[0],
                          'start': old_segment['start'], 'end': old_segment['end']}
        opening = old_selection.get('opening') or {}
        expected_purpose = 'opening' if key == (opening.get('segment_id'), opening.get('component_id')) else 'body'
        if brief['source_binding'] != expected_clock or brief['purpose'] != expected_purpose:
            raise VisualConfirmationError('prepared Wake source clock or purpose differs')
        own = [s for s in proposal['generation_steps'] if (s['segment_id'], s['component_id']) == key]
        if len(own) != 1 or own[0]['purpose'] != 'image':
            raise VisualConfirmationError('prepared Wake needs one approved image step')
        rid, item = generation_item(queue, proposal, own[0], job)
        if not item or item.get('status') != 'completed':
            raise VisualConfirmationError('prepared Wake needs the approved completed image')
        origin_id = item.get('plan_request_id', rid)
        origin = queue['items'].get(origin_id, {})
        if not origin.get('authorization') or validate_generation_request(job, origin['authorization'], origin['request'])['step']['id'] != own[0]['id']:
            raise VisualConfirmationError('prepared Wake image differs from its approved step')
        if rid != origin_id:
            plan = item.get('image_edit_plan', {})
            if (origin.get('status') != 'completed' or set(plan) != {'from_id', 'request', 'issue', 'count'}
                    or item.get('retry_of') != origin_id or plan.get('from_id') != origin_id or type(plan.get('count')) is not int or plan['count'] != 1
                    or plan.get('request') != item.get('request') or plan.get('issue') != origin.get('completion_response', {}).get('conclusion')
                    or not isinstance(plan.get('issue'), str) or not plan['issue'].strip()
                    or item.get('channel_identity') != origin.get('channel_identity') or item.get('config_sha256') != origin.get('config_sha256')
                    or item.get('request', {}).get('tool') != origin['request']['tool'] or item['request'].get('purpose') != 'image'
                    or not isinstance(item.get('user_confirmation'), str) or not item['user_confirmation'].strip()
                    or item.get('approved_plan_sha256') != artifacts.sha256_json(plan)):
                raise VisualConfirmationError('prepared Wake image edit has no exact additional authorization')
            original = origin.get('completion_response', {}).get('artifacts', [])
            if len(original) != 1:
                raise VisualConfirmationError('prepared Wake image edit original is ambiguous')
            source = Path(original[0]['path'])
            if not source.is_absolute(): source = root / source
            original_ref = _record(root, source)
            if (original_ref['sha256'], original_ref['bytes']) != (original[0]['sha256'], original[0]['bytes']):
                raise VisualConfirmationError('prepared Wake original image changed')
            if (item['request']['input_files'] != [original_ref]
                    or item['request']['arguments'].get('referenced_image_paths') != [str(source)]):
                raise VisualConfirmationError('prepared Wake edit does not reference its original image')
        outputs = item.get('completion_response', {}).get('artifacts', [])
        if len(outputs) != 1 or outputs[0].get('type') != 'image':
            raise VisualConfirmationError('prepared Wake needs one completed image output')
        source = Path(outputs[0]['path'])
        if not source.is_absolute(): source = root / source
        ref = _record(root, source)
        if ((ref['sha256'], ref['bytes']) != (outputs[0]['sha256'], outputs[0]['bytes'])
                or brief['image'] != {'job_path': ref['path'], 'sha256': ref['sha256'], 'byte_count': ref['bytes']}):
            raise VisualConfirmationError('prepared Wake brief does not bind the completed image')
        source_sha = artifacts.sha256_file(project / 'skill-development/hd-talking-head' / before['entrypoint'])
        expected = {'source_entrypoint': before['entrypoint'], 'source_sha256': source_sha,
                    'renderer_version': adapter.UPSTREAM_COMMIT, 'template_version': before['producer_version'],
                    'template_origin': 'custom_fallback', 'adaptation_level': 'structural',
                    'verification_id': hashlib.sha256((source_sha + digest).encode()).hexdigest(),
                    'semantic_families': [brief['template_request']['semantic_family']],
                    'capacity': {'min_units': 1, 'max_units': brief['template_request']['information_units']}}
        call = after.get('invocation_record', {})
        if (any(after.get(k) != v for k, v in expected.items())
                or not isinstance(after.get('sample_sha256'), str) or len(after['sample_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in after['sample_sha256'])
                or not isinstance(call, dict) or call.get('status') != 'planned' or call.get('exit_code') is not None
                or call.get('template_request') != brief['template_request']
                or not isinstance(call.get('argv'), list) or len(call['argv']) != 2 or call['argv'][1] != before['entrypoint']):
            raise VisualConfirmationError('prepared Wake binding differs from its native adapter')
        for group in ('beats', 'overlay_beats'):
            old = [b for b in old_selection.get(group, []) if (b['segment_id'], b['component_id']) == key]
            new = [b for b in new_selection.get(group, []) if (b['segment_id'], b['component_id']) == key]
            if old or new:
                if (len(old) != 1 or len(new) != 1 or new[0].get('binding_snapshot') != after
                        or {k: v for k, v in old[0].items() if k != 'binding_snapshot'} !=
                           {k: v for k, v in new[0].items() if k != 'binding_snapshot'}):
                    raise VisualConfirmationError('prepared Wake changed its approved semantic beat')
                new[0]['binding_snapshot'] = copy.deepcopy(old[0]['binding_snapshot'])
        segment['bindings'][key[1]] = copy.deepcopy(before)
        scenes[0].clear()
        scenes[0].update(copy.deepcopy(old_scenes[0]))
    return current, actual


def _realized_media_hashes(root, director, completed_records, native_inputs, generations=(), proposal=None, treatment=None):
    """Collect consumption by component, never by mere occurrence elsewhere."""
    result = {}
    def collect(value, hashes):
        if isinstance(value, dict):
            if isinstance(value.get("sha256"), str): hashes.add(value["sha256"])
            for child in value.values(): collect(child, hashes)
        elif isinstance(value, list):
            for child in value: collect(child, hashes)
    for segment in director["segments"]:
        for cid, binding in segment.get("bindings", {}).items():
            collect(binding, result.setdefault((segment["segment_id"], cid), set()))
    for record in completed_records:
        payload = _read(_exact(root, record))
        collect(payload, result.setdefault((payload["segment_id"], payload["component_id"]), set()))
    for native in native_inputs:
        key = (native["segment_id"], native["component_id"])
        brief = _read(_exact(root, native["artifact"]))
        if native.get('asset_provenance') is not None:
            segment = next((s for s in director['segments'] if s['segment_id'] == key[0]), None)
            if (segment is None or segment.get('bindings', {}).get(key[1], {}).get('dependency_id') != 'paper-collage-hyperframes'
                    or segment['bindings'][key[1]].get('brief_sha256') != native['artifact']['sha256']
                    or not isinstance(proposal, dict) or not isinstance(treatment, dict)):
                raise VisualConfirmationError('crop provenance belongs only to a selected Paper component')
            scenes = [s for s in treatment.get('scenes', [])
                      if (s.get('segment_id'), s.get('component_id')) == key]
            if len(scenes) != 1 or scenes[0].get('asset_provenance') != {
                    'job_path': native['asset_provenance']['path'],
                    'sha256': native['asset_provenance']['sha256'],
                    'byte_count': native['asset_provenance']['bytes']}:
                raise VisualConfirmationError('Paper crop provenance differs from the realized scene')
            steps = {s['id'] for s in proposal['generation_steps']
                     if (s['segment_id'], s['component_id']) == key and s['purpose'] == 'image'}
            approved = [media for generation in generations if generation['step_id'] in steps
                        for media in generation['media']]
            result[key] = {a['sha256'] for a in _paper_referenced_assets(root, brief).values()}
            result[key].update(_paper_crop_sources(root, brief, native['asset_provenance'], approved))
        else:
            collect(brief, result.setdefault(key, set()))
    return result


def validate_realization_evidence(job_dir, stages, revision, receipt_descriptor, *, job_id=None):
    """Read-only shared check; imports neither state nor media engines."""
    root = Path(job_dir)
    receipt, proposal = _validate_source(root, receipt_descriptor, job_id=job_id)
    stage = stages["visual_direction"]
    mappings = [r for r in stage["artifacts"] if r["path"].endswith("/" + MAPPING)]
    if len(mappings) != 1:
        raise VisualConfirmationError("the realized visual mapping is missing or ambiguous")
    map_ref = mappings[0]
    mapping = _read(_exact(root, map_ref))
    if (mapping.get("source_approval") != receipt_descriptor or mapping.get("proposal") != receipt["source"]
            or not mapping.get("host_qa_note", "").strip()):
        raise VisualConfirmationError("realized plan does not reference its original approval")
    final_records = [r for r in stage["artifacts"] if r != map_ref]
    if mapping.get("artifacts") != final_records:
        raise VisualConfirmationError("realized visual inventory changed")
    for record in final_records:
        _exact(root, record)
    final = _read(_exact(root, mapping["final_v3"]))
    if mapping.get("rows") != proposal["rows"]:
        raise VisualConfirmationError("realized visual rows changed")
    if receipt["revision"] >= revision:
        raise VisualConfirmationError("visual approval revision is not committed")
    realized = {key: _read(_exact(root, ref)) for key, ref in mapping["realization_inputs"].items()}
    _validate_draft_against_source(root, proposal, realized["director"], realized["treatment"],
                                 generation_evidence=mapping.get("generations", []))
    if _core(final) != _core(realized['director']):
        raise VisualConfirmationError('compiled plan differs from its reviewed realization')
    compiled = {(seg["segment_id"], c["component_id"]): c
                for seg in final["segments"] for c in seg["shot_recipe"]["components"]}
    for seg in realized["director"]["segments"]:
        for cid, binding in seg.get("bindings", {}).items():
            consumed = {"execution_mode", "media_type", "source_dimensions"}
            if binding.get('execution_mode') == 'reuse_completed_generated_media':
                consumed.add('parent_static_labels')
                consumed.add('parent_camera_framing')
            if any(compiled[(seg["segment_id"], cid)].get(k) != value
                   for k, value in binding.items() if k not in consumed):
                raise VisualConfirmationError("compiled template differs from the realized inputs")
    expected_steps = {step["id"] for step in proposal["generation_steps"]}
    generations = mapping.get("generations", [])
    if {item["step_id"] for item in generations} != expected_steps or len(generations) != len(expected_steps):
        raise VisualConfirmationError("realization does not cover every approved generation step")
    for ref in mapping.get("completed_records", []):
        _exact(root, ref)
    _validate_native_results(root, mapping, realized["director"], realized["treatment"])
    hashes_by_target = _realized_media_hashes(root, realized["director"],
        mapping.get("completed_records", []), mapping.get("native_inputs", []), generations, proposal,
        realized['treatment'])
    # Generated image intermediates are consumed by later approved requests;
    # final images/videos are consumed by the native input or component binding.
    for generation in generations:
        for ref in generation["request"].get("input_files", []):
            _exact(root, ref)
    record_payloads = [_read(_exact(root, ref)) for ref in mapping.get("completed_records", [])]
    for generation in generations:
        step = next(step for step in proposal["generation_steps"] if step["id"] == generation["step_id"])
        target = (step["segment_id"], step["component_id"])
        for record in record_payloads:
            if record.get("generation_id") == generation["request_id"] and (record["segment_id"], record["component_id"]) != target:
                raise VisualConfirmationError("completed generation belongs to another approved visual row")
        for media in generation["media"]:
            _exact(root, media)
            consumed_by_dependency = any(
                step["id"] in dependent.get("depends_on", [])
                and any(ref["sha256"] == media["sha256"] for ref in consumer["request"].get("input_files", []))
                for consumer in generations
                for dependent in proposal["generation_steps"] if dependent["id"] == consumer["step_id"])
            if media["sha256"] not in hashes_by_target.get(target, set()) and not consumed_by_dependency:
                raise VisualConfirmationError("a generated output is not bound to its realized component or approved dependency")
            targets = [(record["segment_id"], record["component_id"]) for record in record_payloads
                       if record.get("media", {}).get("sha256") == media["sha256"]]
            if targets and target not in targets:
                raise VisualConfirmationError("generated content was bound to the wrong visual row")
    return {"artifact": receipt_descriptor, "payload": receipt, "source": proposal, "mapping": mapping}

def validate_visual_authorization(job, *, require_realized=False):
    proposal_ref = _source_from_stage(job)
    candidates = []
    for path in (job.job_dir / "manifests").glob("local-qa-visual_direction-r*.json"):
        receipt = _read(path)
        if receipt.get("source_schema") == SCHEMA and receipt.get("source") == proposal_ref:
            ref = _record(job.job_dir, path)
            payload, proposal = _validate_source(job.job_dir, ref, job_id=job.job_id)
            candidates.append((payload["revision"], ref, payload, proposal))
    if not candidates:
        raise VisualConfirmationError("complete visual list has not been confirmed")
    _, ref, receipt, proposal = max(candidates, key=lambda c: c[0])
    if require_realized:
        return validate_realization_evidence(job.job_dir, job.stages, job.revision, ref, job_id=job.job_id)
    return {"artifact": ref, "payload": receipt, "source": proposal, "mapping": None}

def _request_id(source, step):
    return "visual-" + source["source_id"] + "-" + step["id"]

def _equivalent_request_id(queue, request, step_id, job):
    matches = []
    for rid, item in queue.get("items", {}).items():
        auth = item.get("authorization", {})
        steps = auth.get("steps", {}) if isinstance(auth, dict) else {}
        old = item.get("request", {})
        if steps.get(rid) == step_id and {k:v for k,v in old.items() if k != "id"} == {k:v for k,v in request.items() if k != "id"}:
            validate_generation_request(job, auth, old, queue=queue)
            matches.append(rid)
    if len(matches) > 1:
        raise VisualConfirmationError("equivalent generation request has ambiguous existing ids")
    return matches[0] if matches else None

def generation_item(queue, proposal, step, job=None):
    """Follow only explicitly approved retry successors of the original step."""
    rid = _request_id(proposal, step)
    if job is None and queue.get("job_dir"):
        job = SimpleNamespace(job_dir=Path(queue["job_dir"]), job_id=queue["job_id"])
    if job is not None:
        try:
            current = _build_generation_request(job, proposal, step, queue=queue)
        except VisualConfirmationError as error:
            if str(error) != "generation dependency has not completed":
                raise
            current = None
        if current is not None:
            rid = _equivalent_request_id(queue, current, step["id"], job) or rid
    item = queue["items"].get(rid)
    while item is not None:
        successors = [(key, value) for key, value in queue["items"].items() if value.get("retry_of") == rid]
        if not successors:
            break
        if len(successors) != 1:
            raise VisualConfirmationError("generation retry has ambiguous successors")
        rid, item = successors[0]
    return rid, item

def _build_generation_request(job, proposal, step, *, queue=None):
    from . import generation_channels, generation_queue
    if queue is None:
        queue = generation_queue.status(job.job_dir)
    inputs = copy.deepcopy(step.get("input_files", []))
    def resolve(value):
        if isinstance(value, dict) and "$step" in value:
            dep = next(s for s in proposal["generation_steps"] if s["id"] == value["$step"])
            if dep["id"] not in step.get("depends_on", []):
                raise VisualConfirmationError("future input must name an approved dependency")
            _, item = generation_item(queue, proposal, dep, job)
            if not item or item.get("status") != "completed":
                raise VisualConfirmationError("generation dependency has not completed")
            media = item.get("completion_response", item.get("response", {}))["artifacts"][value.get("output", 0)]
            path = Path(media["path"])
            if not path.is_absolute():
                path = job.job_dir / path
            record = _record(job.job_dir, path)
            if record not in inputs:
                inputs.append(record)
            return str(path)
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value
    return generation_channels.prepare_request(job, step["purpose"], resolve(step["arguments"]),
        request_id=_request_id(proposal, step), input_files=inputs)

def resolve_generation_request(job, proposal, step):
    """Build the request and retain a pre-existing equivalent request identity."""
    from . import generation_queue
    request = _build_generation_request(job, proposal, step)
    queue = generation_queue.status(job.job_dir)
    rid = _equivalent_request_id(queue, request, step["id"], job) or request["id"]
    request["id"] = rid
    return request

def validate_generation_request(job, authorization, request, *, queue=None):
    receipt, proposal = _validate_source(job.job_dir, authorization["source"], job_id=job.job_id)
    step_id = authorization["steps"][request["id"]]
    step = next((s for s in proposal["generation_steps"] if s["id"] == step_id), None)
    if step is None or request != _build_generation_request(job, proposal, step, queue=queue):
        raise VisualConfirmationError("generation request differs from its approved step")
    return {"receipt": receipt, "step": step}

def generation_actions(job, *, account_limit=None):
    from . import generation_channels, generation_queue
    authorized = validate_visual_authorization(job)
    proposal = authorized["source"]
    actions = []
    for step in proposal["generation_steps"]:
        queue = generation_queue.status(job.job_dir)
        rid, item = generation_item(queue, proposal, step, job)
        if item and item["status"] == "completed":
            continue
        dependencies = [next(s for s in proposal["generation_steps"] if s["id"] == dep)
                        for dep in step.get("depends_on", [])]
        if any((generation_item(queue, proposal, dep, job)[1] or {}).get("status") != "completed" for dep in dependencies):
            continue
        if not item:
            request = resolve_generation_request(job, proposal, step)
            plan = {"requests": [request]}
            generation_queue.add_authorized(job.job_dir, plan,
                {"source": authorized["artifact"], "steps": {rid: step["id"]}}, artifacts.sha256_json(plan))
        action = generation_channels.next_action(job.job_dir, rid, account_limit=account_limit)
        action["step_id"] = step["id"]
        actions.append(action)
    return actions

MOTION_CREATION = {'barty-motion-graphics', 'bang-motion', 'mg-styles-15', 'video-shotcraft'}


def _lemo_number_change(old_text, new_text):
    pattern = re.compile(r"\b[A-Za-z_$][\w$]*\(String\([A-Za-z_$][\w$]*\),[A-Za-z_$][\w$]*,[A-Za-z_$][\w$]*\+(\d+),(\d+),[^,\n]+,\s*['\"]center['\"],\s*['\"][^'\"]+['\"]\)")
    old, new = list(pattern.finditer(old_text)), list(pattern.finditer(new_text))
    if (len(old) != 1 or len(new) != 1
            or old_text[:old[0].start(1)] + new[0].group(1) + old_text[old[0].end(1):old[0].start(2)]
               + new[0].group(2) + old_text[old[0].end(2):] != new_text):
        raise VisualConfirmationError('Lemo source has changes beyond number size and baseline')
    old_y, old_size = map(int, old[0].groups()); new_y, new_size = map(int, new[0].groups())
    if not (0 < old_size < new_size <= 256 and abs(new_y-old_y) <= new_size-old_size):
        raise VisualConfirmationError('Lemo typography values are not a scoped readability correction')
    return old_size, new_size


def _verify_lemo_measured_frames(root, video, measured, frames):
    from PIL import Image
    rows = measured.get('samples', [])
    indices = [row.get('frame') for row in rows]
    if (not indices or any(type(n) is not int or not 0 <= n < frames for n in indices)
            or indices != sorted(set(indices))):
        raise VisualConfirmationError('Lemo measured frame indices are invalid')
    selector = '+'.join(f'eq(n\\,{n})' for n in indices)
    data = subprocess.check_output([shutil.which('ffmpeg') or 'ffmpeg', '-v','error','-i',str(video),
        '-vf','select='+selector,'-vsync','0','-f','rawvideo','-pix_fmt','rgb24','-'], timeout=60)
    stride = 1080 * 1920 * 3
    if len(data) != stride * len(rows):
        raise VisualConfirmationError('Lemo measured frames cannot be decoded')
    for index, row in enumerate(rows):
        path = _path(root, row['frame_path'])
        if artifacts.sha256_file(path) != row.get('frame_sha256') or abs(row.get('time', -1) - indices[index] / 24) > 1e-6:
            raise VisualConfirmationError('Lemo measured frame identity or time differs')
        with Image.open(path) as image:
            if image.size != (1080, 1920):
                raise VisualConfirmationError('Lemo measured frame dimensions differ')
            rgb = image.convert('RGB')
            if rgb.tobytes() != data[index * stride:(index + 1) * stride]:
                raise VisualConfirmationError('Lemo measured frame is not from the composite')
            for digit in row['digits']:
                for measurement in digit['measurements']:
                    bbox = measurement.get('bbox')
                    if (not isinstance(bbox, list) or len(bbox) != 4 or any(type(v) is not int for v in bbox)):
                        raise VisualConfirmationError('Lemo measured glyph bounds are invalid')
                    x,y,w,h = bbox
                    if not (0 <= x < x+w <= 1080 and 0 <= y < y+h <= 1920 and w > 0 and h >= 36 and measurement.get('height') == h):
                        raise VisualConfirmationError('Lemo measured glyph is too small or outside the frame')
                    if measurement.get('method') == 'bright_core':
                        pixels = rgb.load()
                        if any(max(min(pixels[xx, yy]) for xx in range(x,x+w)) < 200 for yy in range(y,y+h)):
                            raise VisualConfirmationError('Lemo measured glyph pixels do not support its height')


def _normalize_lemo_typography(root, frozen, frozen_treatment, director, treatment):
    """Compare a reviewed number-only Lemo correction without replacing approval."""
    import importlib.util
    import json
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    script = Path(__file__).resolve().parents[3] / 'skill-development/hd-talking-head/scripts/upstream_scene_adapter.py'
    spec = importlib.util.spec_from_file_location('_lemo_typography_adapter', script)
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    old_segments = {s['segment_id']: s for s in frozen['segments']}
    for segment in current['segments']:
        old_segment = old_segments.get(segment['segment_id'])
        if old_segment is None:
            continue
        for cid, after in segment.get('bindings', {}).items():
            before = old_segment.get('bindings', {}).get(cid, {})
            if before.get('dependency_id') != 'lemo-opuscar' or before == after:
                continue
            key = (segment['segment_id'], cid)
            scenes = [s for s in actual.get('scenes', []) if (s.get('segment_id'), s.get('component_id')) == key]
            old_scenes = [s for s in frozen_treatment.get('scenes', []) if (s.get('segment_id'), s.get('component_id')) == key]
            if len(scenes) != 1 or len(old_scenes) != 1:
                raise VisualConfirmationError('Lemo typography revision needs its original scene')
            scene, old_scene = scenes[0], old_scenes[0]
            evidence = scene.pop('native_typography_revision', None)
            if not isinstance(evidence, dict) or set(evidence) != {'sample', 'call', 'manifest', 'qa', 'composite', 'measurements', 'composite_call', 'composite_inputs'}:
                raise VisualConfirmationError('Lemo typography revision needs real sample, call, composite and measured review')
            paths = {name: _exact(root, ref) for name, ref in evidence.items()}
            old_path, new_path = _path(root, old_scene['brief_path']), _path(root, scene['brief_path'])
            old_data, new_data = old_path.read_bytes(), new_path.read_bytes()
            if (hashlib.sha256(old_data).hexdigest() != before['brief_sha256'] or
                    hashlib.sha256(new_data).hexdigest() != after['brief_sha256']):
                raise VisualConfirmationError('Lemo typography brief identity changed')
            old, new = adapter.validate_brief(old_data), adapter.validate_brief(new_data)
            if any(old[k] != new[k] for k in old if k not in {'files', 'creative_handoff'}):
                raise VisualConfirmationError('Lemo typography changed template, source or clock')
            old_files = {f['scene_path']: f for f in old['files']}; new_files = {f['scene_path']: f for f in new['files']}
            if set(old_files) != set(new_files) or len(old_files) != len(old['files']) or len(new_files) != len(new['files']):
                raise VisualConfirmationError('Lemo typography changed project inventory')
            if any(old_files[name]['media_ref'] != new_files[name]['media_ref'] for name in old_files):
                raise VisualConfirmationError('Lemo typography changed project file identities')
            for files in (old_files, new_files):
                for f in files.values():
                    if artifacts.sha256_file(_path(root, f['job_path'])) != f['sha256']:
                        raise VisualConfirmationError('Lemo frozen project file changed')
            changed = {name for name in old_files if old_files[name]['sha256'] != new_files[name]['sha256']}
            old_work = old_files[next(f['scene_path'] for f in old['files'] if f['media_ref'] == old['workflow_media_ref'])]
            new_work = new_files[old_work['scene_path']]
            code_names = changed - {old_work['scene_path']}
            if len(code_names) != 1 or not next(iter(code_names)).endswith(('.js', '.mjs')):
                raise VisualConfirmationError('Lemo typography may change only one numeric-label source')
            name = next(iter(code_names))
            old_text = _path(root, old_files[name]['job_path']).read_text(); new_text = _path(root, new_files[name]['job_path']).read_text()
            old_size, new_size = _lemo_number_change(old_text, new_text)
            old_h, new_h = copy.deepcopy(old['creative_handoff']), copy.deepcopy(new['creative_handoff'])
            text = old_h['design_plan']['typography']; target = f'{old_size}px'
            if text.count(target) != 1 or new_h['design_plan']['typography'] != text.replace(target, f'{new_size}px'):
                raise VisualConfirmationError('Lemo typography description differs from the source change')
            new_h['design_plan']['typography'] = text
            if old_h != new_h:
                raise VisualConfirmationError('Lemo typography changed creative semantics')
            ow, nw = _read(_path(root, old_work['job_path'])), _read(_path(root, new_work['job_path']))
            if ({k:v for k,v in ow.items() if k not in {'design_plan','qa'}} != {k:v for k,v in nw.items() if k not in {'design_plan','qa'}}
                    or ow.get('design_plan') != old['creative_handoff']['design_plan']
                    or nw.get('design_plan') != new['creative_handoff']['design_plan']):
                raise VisualConfirmationError('Lemo workflow changed beyond typography and review')
            call, manifest, qa = (_read(paths[k]) for k in ('call','manifest','qa'))
            argv = call.get('argv', []); result = json.loads(call.get('stdout', '{}'))
            def argument(flag):
                if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv):
                    raise VisualConfirmationError('Lemo typography call is incomplete')
                return Path(argv[argv.index(flag)+1]).resolve()
            upstream = Path(__file__).resolve().parents[3] / 'skill-development/vendor/lemo-opuscar'
            if upstream.is_symlink():
                raise VisualConfirmationError('Lemo upstream checkout cannot be a symlink')
            if (call.get('exit_code') != 0 or len(argv) < 2 or Path(argv[1]).resolve() != script.resolve()
                    or artifacts.sha256_file(script) != after['source_sha256']
                    or argument('--brief') != new_path.resolve()
                    or argument('--media-manifest') != paths['manifest'].resolve() or argument('--output') != paths['sample'].resolve()
                    or manifest.get('brief_sha256') != after['brief_sha256']
                    or {(x['media_ref'], x['sha256']) for x in manifest.get('media', [])} != {(f['media_ref'], f['sha256']) for f in new['files']}
                    or len(manifest.get('media', [])) != len(new['files'])
                    or result.get('status') != 'rendered' or result.get('frames') != new['composition']['frames']
                    or result.get('dependency_id') != 'lemo-opuscar' or result.get('upstream_commit') != adapter.SOURCES['lemo-opuscar'][0]
                    or result.get('native_entry_sha256') != artifacts.sha256_file(upstream / adapter.SOURCES['lemo-opuscar'][1])
                    or result.get('production_evidence') != adapter.workflow_reference(new)
                    or evidence['sample']['sha256'] != after['sample_sha256']
                    or qa.get('status') != 'independent_native_and_composite_review_pass'
                    or (qa.get('segment_id'), qa.get('component_id')) != key
                    or qa.get('native_media') != {'path': evidence['sample']['path'], 'sha256': evidence['sample']['sha256']}
                    or qa.get('actual_composite_media') != {'path': evidence['composite']['path'], 'sha256': evidence['composite']['sha256']}
                    or qa.get('actual_digit_measurements') != paths['measurements'].name):
                raise VisualConfirmationError('Lemo sample and native call do not match the reviewed revision')
            sizes = {f['media_ref']: _path(root, f['job_path']).stat().st_size for f in new['files']}
            if any(x.get('byte_length') != sizes[x['media_ref']] for x in manifest['media']):
                raise VisualConfirmationError('Lemo native call file lengths differ')
            measured = _read(paths['measurements'])
            composite_call, composite_inputs = _read(paths['composite_call']), _read(paths['composite_inputs'])
            cargv = composite_call.get('argv', [])
            input_paths = [Path(cargv[i+1]).resolve() for i, value in enumerate(cargv[:-1]) if value == '-i']
            source = composite_inputs.get('aroll_input', {})
            source_path = _path(root, source.get('path', ''))
            if (composite_call.get('exit_code') != 0 or len(input_paths) != 2
                    or input_paths != [source_path.resolve(), paths['sample'].resolve()]
                    or not cargv or Path(cargv[-1]).resolve() != paths['composite'].resolve()
                    or cargv.count('-filter_complex') != 1
                    or cargv[cargv.index('-filter_complex')+1] != composite_inputs.get('graph')
                    or composite_inputs.get('actual_new_video_input') != {'path': evidence['sample']['path'], 'sha256': evidence['sample']['sha256']}
                    or source.get('sha256') != new['source_binding']['aroll_sha256']
                    or artifacts.sha256_file(source_path) != source.get('sha256')):
                raise VisualConfirmationError('Lemo composite does not match its real source and call')
            sample_rows = measured.get('samples', [])
            if (not sample_rows or measured.get('minimum_required_height', 0) < 36
                    or any(not item.get('human_review') or any(m.get('height', 0) < 36 for m in item.get('measurements', []))
                           or len(item.get('measurements', [])) < 2 for row in sample_rows for item in row.get('digits', []))
                    or any(not row.get('digits') for row in sample_rows)
                    or not all(qa.get('human_pixel_review', {}).get(k) is True for k in ('unclipped','unobstructed','no_other_text_or_avatar_overlap'))):
                raise VisualConfirmationError('Lemo typography actual pixel review is incomplete')
            _verify_lemo_measured_frames(root, paths['composite'], measured, new['composition']['frames'])
            probe = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(paths['sample'])], timeout=30))
            streams = probe.get('streams', [])
            if (len(streams) != 1 or streams[0].get('codec_type') != 'video'
                    or streams[0].get('avg_frame_rate') != '24/1'
                    or (streams[0].get('width'), streams[0].get('height'), int(streams[0].get('nb_read_frames', 0))) != (1080, 1920, new['composition']['frames'])):
                raise VisualConfirmationError('Lemo reviewed sample clock or dimensions differ')
            comparable = copy.deepcopy(after)
            for field in ('brief_sha256','sample_sha256','verification_id'):
                comparable[field] = before[field]
            comparable['invocation_record'] = copy.deepcopy(before['invocation_record'])
            if comparable != before or after['verification_id'] != hashlib.sha256((after['source_sha256']+after['renderer_version']+after['brief_sha256']).encode()).hexdigest():
                raise VisualConfirmationError('Lemo typography changed the approved source binding')
            expected_invocation = copy.deepcopy(before['invocation_record'])
            expected_invocation['production_evidence'] = adapter.workflow_reference(new)
            expected_invocation['creative_handoff'] = {k:new['creative_handoff'][k] for k in ('transcript','semantic_goal','required_change','subject','visual_pattern','design_plan')}
            if after['invocation_record'] != expected_invocation:
                raise VisualConfirmationError('Lemo typography changed unapproved invocation fields')
            if after['invocation_record'].get('production_evidence') != adapter.workflow_reference(new):
                raise VisualConfirmationError('Lemo typography workflow binding differs')
            for field in ('argv','status','exit_code','template_request','style_slug'):
                if after['invocation_record'].get(field) != before['invocation_record'].get(field):
                    raise VisualConfirmationError('Lemo typography invocation changed')
            if after['invocation_record'].get('creative_handoff') != {k:new['creative_handoff'][k] for k in ('transcript','semantic_goal','required_change','subject','visual_pattern','design_plan')}:
                raise VisualConfirmationError('Lemo typography invocation handoff differs')
            scene['brief_path'] = old_scene['brief_path']
            if scene != old_scene:
                raise VisualConfirmationError('Lemo typography changed other scene fields')
            segment['bindings'][cid] = copy.deepcopy(before)
            for group in ('beats','overlay_beats'):
                matches = [b for b in actual.get('skill_selection', {}).get(group, []) if (b.get('segment_id'), b.get('component_id')) == key]
                for beat in matches:
                    if beat.get('binding_snapshot') != after:
                        raise VisualConfirmationError('Lemo typography binding snapshot is stale')
                    beat['binding_snapshot'] = copy.deepcopy(before)
            old_read = [x for x in frozen_treatment.get('motion_readability', []) if (x.get('segment_id'),x.get('component_id')) == key]
            new_read = [x for x in actual.get('motion_readability', []) if (x.get('segment_id'),x.get('component_id')) == key]
            if len(old_read) != 1 or len(new_read) != 1:
                raise VisualConfirmationError('Lemo typography needs current readability targets')
            old_targets = {x['target_id']: x for x in old_read[0]['targets']}
            new_targets = {x['target_id']: x for x in new_read[0]['targets']}
            if (len(old_targets) != len(old_read[0]['targets']) or len(new_targets) != len(new_read[0]['targets'])
                    or set(old_targets) != set(new_targets)):
                raise VisualConfirmationError('Lemo typography changed text target inventory')
            old_paths = {f['job_path']: name for name, f in old_files.items()}
            new_paths = {f['job_path']: name for name, f in new_files.items()}
            for target_id, original in old_targets.items():
                revised = new_targets[target_id]
                if ({k:v for k,v in original.items() if k != 'content_ref'} != {k:v for k,v in revised.items() if k != 'content_ref'}
                        or original['content_ref'].get('value') != revised['content_ref'].get('value')
                        or old_paths.get(original['content_ref'].get('path')) is None
                        or old_paths.get(original['content_ref'].get('path')) != new_paths.get(revised['content_ref'].get('path'))):
                    raise VisualConfirmationError('Lemo typography changed approved text content or layout targets')
            from . import motion_readability
            original_segment = next(s for s in director['segments'] if s['segment_id'] == key[0])
            scoped = {**original_segment, 'shot_recipe': {'components': [c for c in original_segment['visual_strategy']['components'] if c['component_id'] == cid]}}
            motion_readability.validate_targets([scoped], new_read,
                motion_readability._required_refs({'motion_readability': new_read}), root=root)
            actual['motion_readability'][actual['motion_readability'].index(new_read[0])] = copy.deepcopy(old_read[0])
    return current, actual


def _motion_brief(root, director, treatment, key):
    segment = next(s for s in director['segments'] if s['segment_id'] == key[0])
    binding = segment['bindings'][key[1]]
    scenes = [scene for scene in treatment.get('scenes', [])
              if (scene.get('segment_id'), scene.get('component_id')) == key]
    if len(scenes) != 1:
        raise VisualConfirmationError('native creation must retain one scene per approved component')
    payload = _path(root, scenes[0]['brief_path']).read_bytes()
    if hashlib.sha256(payload).hexdigest() != binding['brief_sha256']:
        raise VisualConfirmationError('native execution brief differs from its binding')
    adapter = _native_result_adapter(binding['dependency_id'])
    brief = adapter.validate_brief(payload, dependency_id=binding['dependency_id'])
    if brief['task_source'] != adapter.task_source(director, treatment, *key):
        raise VisualConfirmationError('native creation task differs from its approved parent semantics')
    return binding, adapter, brief, payload


def _readability_texts(records, keys):
    return {target['content_ref']['value'][slice(*target['span'])]
            for record in records if (record['segment_id'], record['component_id']) in keys
            for target in record.get('targets', [])}


def _validate_canvas_alignment(root, director, treatment, key, adapter, brief, payload, alignment):
    if not isinstance(alignment, dict) or set(alignment) != {'mode', 'base_component_id', 'base_sha256', 'layer_sha256'} or alignment['mode'] != 'identity':
        raise VisualConfirmationError('invalid canvas alignment declaration')
    segment = next(s for s in director['segments'] if s['segment_id'] == key[0])
    strategy = segment['visual_strategy']
    components = {c['component_id']: c for c in strategy['components']}
    base_id = alignment['base_component_id']
    base = components.get(base_id, {})
    overlay = components.get(key[1], {})
    if (strategy['mode'] != 'hybrid' or strategy['composition']['family'] != 'evidence_with_data_overlay'
            or base.get('kind') != 'ai_generated' or base.get('layer_role') != 'base'
            or base.get('layout_slot') != 'full_frame' or overlay.get('layer_role') != 'annotation'
            or brief.get('alpha') is not True or brief.get('composition', {}).get('width') != 1080
            or brief.get('composition', {}).get('height') != 1920
            or not any(d['component_id'] == key[1] and base_id in d['depends_on']
                       for d in strategy['composition']['component_dependencies'])):
        raise VisualConfirmationError('canvas alignment is not an approved full-canvas hybrid')
    scenes = [s for s in treatment.get('scenes', []) if (s.get('segment_id'), s.get('component_id')) == (key[0], base_id)]
    if len(scenes) != 1 or not isinstance(scenes[0].get('completed_record'), dict):
        raise VisualConfirmationError('canvas alignment needs its approved base record')
    ref = scenes[0]['completed_record']
    path = _path(root, ref['job_path'])
    if (artifacts.sha256_file(path), path.stat().st_size) != (ref['sha256'], ref['byte_count']):
        raise VisualConfirmationError('canvas alignment base record changed')
    record = _read(path)
    media = record.get('media', {})
    if (record.get('job_id') != brief.get('job_id') or record.get('status') != 'completed'
            or record.get('segment_id') != key[0] or record.get('component_id') != base_id
            or record.get('composition_base', {}).get('action_component_id') != key[1]
            or record.get('source_dimensions') != {'width': 1080, 'height': 1920}
            or media.get('sha256') != alignment['base_sha256']
            or segment['bindings'][base_id].get('sha256') != alignment['base_sha256']):
        raise VisualConfirmationError('canvas alignment base identity differs')
    base_path = _path(root, media['job_path'])
    if (artifacts.sha256_file(base_path), base_path.stat().st_size) != (media['sha256'], media['byte_count']):
        raise VisualConfirmationError('canvas alignment base media changed')
    result = adapter.inspect_result(root, payload)
    if result['media']['sha256'] != alignment['layer_sha256']:
        raise VisualConfirmationError('canvas alignment action media differs')


def _validate_motion_realization(root, frozen, frozen_treatment, director, treatment):
    """Permit only result-derived edits of approved complete native creations.

    Compare a normalized copy with the original proposal. The actual reviewed
    copy is never rewritten and is frozen by the existing execution mapping.
    """
    keys = {(s['segment_id'], cid) for s in frozen['segments']
            for cid, binding in s.get('bindings', {}).items()
            if binding.get('dependency_id') in MOTION_CREATION}
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    if not keys:
        return current, actual
    old_records = {(r['segment_id'], r['component_id']): r for r in frozen_treatment.get('motion_readability', [])}
    new_records = {(r['segment_id'], r['component_id']): r for r in treatment.get('motion_readability', [])}
    if len(new_records) != len(treatment.get('motion_readability', [])) or set(new_records) != set(old_records):
        raise VisualConfirmationError('realization changed the readability component inventory')
    for key in keys:
        before, adapter, approved, _ = _motion_brief(root, frozen, frozen_treatment, key)
        after, _, brief, payload = _motion_brief(root, director, treatment, key)
        comparable_after = copy.deepcopy(after)
        alignment = comparable_after.get('invocation_record', {}).get('canvas_alignment')
        if alignment is not None:
            _validate_canvas_alignment(root, director, treatment, key, adapter, brief, payload, alignment)
            if 'canvas_alignment' not in before.get('invocation_record', {}):
                del comparable_after['invocation_record']['canvas_alignment']
        if adapter.approved_task(brief) != adapter.approved_task(approved):
            raise VisualConfirmationError('native revision changed its approved semantic task, template, inputs or authorization')
        if ({k: v for k, v in before.items() if k not in {'brief_sha256', 'verification_id'}}
                != {k: v for k, v in comparable_after.items() if k not in {'brief_sha256', 'verification_id'}}
                or after.get('verification_id') != hashlib.sha256(
                    (after['source_sha256'] + after['brief_sha256']).encode()).hexdigest()):
            raise VisualConfirmationError('native revision replaced an approved template or source')
        scene = next(s for s in actual['scenes'] if (s.get('segment_id'), s.get('component_id')) == key)
        original_scene = next(s for s in frozen_treatment['scenes'] if (s.get('segment_id'), s.get('component_id')) == key)
        if (scene.get('native_revision_from') is not None
                and (scene.get('native_revision_from') != original_scene.get('native_revision_from')
                     or after != before)):
            submitted = next(s for s in director['segments'] if s['segment_id'] == key[0])
            _verify_native_revision_origin(root, frozen, key, submitted, scene)
            if 'native_revision_from' in original_scene:
                scene['native_revision_from'] = copy.deepcopy(original_scene['native_revision_from'])
            else:
                scene.pop('native_revision_from')
        if any(brief[field] != approved[field] for field in ('project_directory', 'result_record_path')):
            if not isinstance(scene.get('native_revision_reason'), str) or not scene['native_revision_reason'].strip():
                raise VisualConfirmationError('native execution revision needs its diagnosed failure reason')
            if 'native_revision_reason' in original_scene:
                scene['native_revision_reason'] = original_scene['native_revision_reason']
            else:
                scene.pop('native_revision_reason')
        scene['brief_path'] = original_scene['brief_path']
        if scene != original_scene:
            raise VisualConfirmationError('native revision changed its approved scene fields')
        segment = next(s for s in current['segments'] if s['segment_id'] == key[0])
        segment['bindings'][key[1]] = copy.deepcopy(before)
        for group in ('beats', 'overlay_beats'):
            for beat in actual.get('skill_selection', {}).get(group, []):
                if (beat['segment_id'], beat['component_id']) == key:
                    if beat.get('binding_snapshot') != after:
                        raise VisualConfirmationError('native revision binding snapshot is stale')
                    beat['binding_snapshot'] = copy.deepcopy(before)
                    original_beats = [b for b in frozen_treatment.get('skill_selection', {}).get(group, [])
                                      if (b['segment_id'], b['component_id']) == key]
                    if len(original_beats) != 1 or beat != original_beats[0]:
                        raise VisualConfirmationError('native realization changed its approved semantic beat')
        for alignment in actual.get('overlay_alignment', []):
            if (alignment.get('segment_id'), alignment.get('component_id')) == key:
                if alignment.get('brief_path') != next(s['brief_path'] for s in treatment['scenes']
                        if (s.get('segment_id'), s.get('component_id')) == key):
                    raise VisualConfirmationError('native overlay revision uses another input')
                alignment['brief_path'] = original_scene['brief_path']
                original_alignment = [a for a in frozen_treatment.get('overlay_alignment', [])
                    if (a.get('segment_id'), a.get('component_id')) == key]
                if len(original_alignment) != 1 or alignment != original_alignment[0]:
                    raise VisualConfirmationError('native overlay revision changed its approved alignment')
        changed = new_records[key] != old_records[key]
        old_segment = next(s for s in frozen['segments'] if s['segment_id'] == key[0])
        actual_segment = next(s for s in director['segments'] if s['segment_id'] == key[0])
        changed |= (actual_segment['visible_text'] != old_segment['visible_text']
                    and _path(root, brief['result_record_path']).is_file())
        if changed:
            result = adapter.inspect_result(root, payload)
            call = _read(adapter.exact(root, result['render_call']))
            sources = {item['job_path']: item for item in call['project_files']}
            for target in new_records[key].get('targets', []):
                ref = target['content_ref']
                if (ref['path'] not in sources or ref['sha256'] != sources[ref['path']]['sha256']
                        or not ref['pointer'].startswith('text:')):
                    raise VisualConfirmationError('native readability must cite the actual rendered project source')
            from . import motion_readability
            scoped = {**actual_segment, 'shot_recipe': {'components': [c for c in actual_segment['visual_strategy']['components']
                       if c['component_id'] == key[1]]}}
            motion_readability.validate_targets([scoped], [new_records[key]],
                motion_readability._required_refs({'motion_readability': [new_records[key]]}), root=root)
        old_assessments = [a for a in frozen_treatment.get('semantic_assessments', [])
                           if (a.get('segment_id'), a.get('component_id')) == key]
        new_assessments = [a for a in treatment.get('semantic_assessments', [])
                           if (a.get('segment_id'), a.get('component_id')) == key]
        if len(old_assessments) != 1 or len(new_assessments) != 1 or any(
                new_assessments[0].get(field) != value for field, value in old_assessments[0].items()
                if field not in {'content_refs', 'reason', 'verdict'}):
            raise VisualConfirmationError('native result changed the approved semantic assessment identity')
    for segment in current['segments']:
        scoped = {key for key in keys if key[0] == segment['segment_id']}
        if not scoped:
            continue
        before = next(s for s in frozen['segments'] if s['segment_id'] == segment['segment_id'])
        required = set(before['visible_text'])
        confirmed = Path(root) / 'manifests/confirmed-content.json'
        if confirmed.is_file():
            from . import confirmed_content
            required.update(text for item in _read(confirmed).get('visuals', [])
                            if any(confirmed_content.matches_visual(item, *key) for key in scoped)
                            for text in item.get('visible_text', []))
        visible = set(segment['visible_text'])
        actual_text = _readability_texts(treatment.get('motion_readability', []), scoped)
        if not required <= visible or not (visible - set(before['visible_text'])) <= actual_text:
            raise VisualConfirmationError('native visible text must retain confirmed text and cite its actual readability inventory')
        segment['visible_text'] = copy.deepcopy(before['visible_text'])
    actual['motion_readability'] = [copy.deepcopy(old_records[(r['segment_id'], r['component_id'])])
        if (r['segment_id'], r['component_id']) in keys else r for r in actual.get('motion_readability', [])]
    return current, actual


def _registered_native_revision(root, stage, key, target):
    """Follow only this component's frozen origin chain from registered mappings."""
    fields = ('path', 'sha256', 'bytes')
    if (not isinstance(target, dict) or set(target) != set(fields)
            or not str(target.get('path', '')).endswith('/' + MAPPING)):
        return False
    roots = {tuple(record.get(k) for k in fields) for record in
             [*stage['artifacts'], *stage.get('lineage', [])]
             if str(record.get('path', '')).endswith('/' + MAPPING)}
    for values in roots:
        ref, visited = dict(zip(fields, values)), set()
        while ref is not None:
            if (not isinstance(ref, dict) or set(ref) != set(fields)
                    or not str(ref.get('path', '')).endswith('/' + MAPPING)):
                raise VisualConfirmationError('native revision ancestry has an invalid mapping')
            identity = tuple(ref[k] for k in fields)
            if identity in visited:
                raise VisualConfirmationError('native revision ancestry contains a cycle')
            visited.add(identity)
            mapping = _read(_exact(root, ref))
            workflow = _read(Path(root) / 'workflow.json')
            receipt, _ = _validate_source(root, mapping['source_approval'], job_id=workflow['job_id'])
            if mapping.get('proposal') != receipt['source']:
                raise VisualConfirmationError('native revision ancestry changed its approved proposal')
            _exact(root, mapping['proposal'])
            inputs = mapping['realization_inputs']
            director = _read(_exact(root, inputs['director']))
            treatment = _read(_exact(root, inputs['treatment']))
            if not any(segment.get('segment_id') == key[0] and key[1] in segment.get('bindings', {})
                       for segment in director.get('segments', [])):
                raise VisualConfirmationError('native revision ancestry lost its component')
            scenes = [item for item in treatment.get('scenes', [])
                      if (item.get('segment_id'), item.get('component_id')) == key]
            if len(scenes) != 1:
                raise VisualConfirmationError('native revision ancestry has an ambiguous component')
            if ref == target:
                return True
            ref = scenes[0].get('native_revision_from')
    return False


def _verify_native_revision_origin(root, frozen, key, submitted, scene):
    """Bind a native repair to the actual prior frozen realization, never just a version label."""
    from . import state
    ref = scene['native_revision_from']
    job = state.load_job(Path(root))
    stage = job.stages['visual_direction']
    if (not _registered_native_revision(root, stage, key, ref)
            or not str(scene.get('native_revision_reason', '')).strip()):
        raise VisualConfirmationError('native repair requires its registered previous realization and reason')
    mapping = _read(_exact(root, ref))
    source = _read(_exact(root, mapping['proposal']))
    if _read(_exact(root, source['inputs']['director'])) != frozen:
        raise VisualConfirmationError('native repair belongs to another approved proposal')
    previous = _read(_exact(root, mapping['realization_inputs']['director']))
    old = next(s for s in previous['segments'] if s['segment_id'] == key[0])
    old_binding, new_binding = old['bindings'][key[1]], submitted['bindings'][key[1]]
    unchanged = old_binding == new_binding
    compared = copy.deepcopy(submitted)
    compared['strategy_revision'] = old['strategy_revision']
    if (submitted['strategy_revision'] != old['strategy_revision'] + (0 if unchanged else 1)
            or _core({'segments': [compared]}) != _core({'segments': [old]})
            or (not unchanged and old_binding.get('brief_sha256') == new_binding.get('brief_sha256'))
            or {k: v for k, v in old_binding.items() if k not in {'brief_sha256', 'verification_id'}}
               != {k: v for k, v in new_binding.items() if k not in {'brief_sha256', 'verification_id'}}):
        raise VisualConfirmationError('native implementation must reuse its registered version or advance a changed input exactly once')


def _validate_css_font_growth(before, after):
    """Allow only increased numeric CSS font sizes in the same authored page."""
    pattern = re.compile(r'font-size\s*:\s*(\d+(?:\.\d+)?)px\b')
    def normalized(source):
        sizes = []
        def style(match):
            def font(item):
                sizes.append(float(item[1]))
                return item[0].replace(item[1], '<font-size>', 1)
            return pattern.sub(font, match[0])
        return re.sub(r'<style\b[^>]*>.*?</style>', style, source, flags=re.S), sizes
    old, old_sizes = normalized(before)
    new, new_sizes = normalized(after)
    if (old != new or not old_sizes or len(old_sizes) != len(new_sizes)
            or old_sizes == new_sizes or any(not 0 < a <= b <= 96 for a,b in zip(old_sizes,new_sizes))):
        raise VisualConfirmationError('OpenFilm typography may only increase existing numeric CSS font sizes')


def _normalize_openfilm_typography(root, frozen, frozen_treatment, director, treatment):
    """Retain the original source/task while freezing a local font-size repair."""
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    old_segments = {s['segment_id']: s for s in frozen['segments']}
    for segment in current['segments']:
        for cid, binding in list(segment.get('bindings', {}).items()):
            prior = old_segments[segment['segment_id']].get('bindings', {}).get(cid, {})
            if binding.get('dependency_id') != 'openfilm-motion-graphics' or binding == prior:
                continue
            key = segment['segment_id'], cid
            scene = next(s for s in actual['scenes'] if (s.get('segment_id'),s.get('component_id')) == key)
            original = next(s for s in frozen_treatment['scenes'] if (s.get('segment_id'),s.get('component_id')) == key)
            _verify_native_revision_origin(root, frozen, key, segment, scene)
            briefs = []
            for record, bound in ((original, prior), (scene, binding)):
                payload = _path(root, record['brief_path']).read_bytes()
                if hashlib.sha256(payload).hexdigest() != bound['brief_sha256']:
                    raise VisualConfirmationError('OpenFilm typography brief identity changed')
                briefs.append(_read(_path(root, record['brief_path'])))
            old, new = briefs
            if ({k:v for k,v in old.items() if k != 'entry'} != {k:v for k,v in new.items() if k != 'entry'}
                    or {k:v for k,v in old['entry'].items() if k not in {'job_path','sha256'}}
                       != {k:v for k,v in new['entry'].items() if k not in {'job_path','sha256'}}
                    or binding.get('verification_id') != hashlib.sha256(
                        (binding['source_sha256'] + binding['brief_sha256']).encode()).hexdigest()):
                raise VisualConfirmationError('OpenFilm typography changed its source, task, assets or clock')
            pages = []
            for brief in briefs:
                path = _path(root, brief['entry']['job_path'])
                if artifacts.sha256_file(path) != brief['entry']['sha256']:
                    raise VisualConfirmationError('OpenFilm typography page identity changed')
                pages.append(path.read_text())
            _validate_css_font_growth(*pages)
            row = next(r for r in actual['motion_readability'] if (r['segment_id'],r['component_id']) == key)
            old_row = next(r for r in frozen_treatment['motion_readability'] if (r['segment_id'],r['component_id']) == key)
            if ([(t['target_id'],t['role'],t['content_ref']['value'],t['span'],t['windows']) for t in row['targets']]
                    != [(t['target_id'],t['role'],t['content_ref']['value'],t['span'],t['windows']) for t in old_row['targets']]
                    or any(t['content_ref']['path'] != new['entry']['job_path']
                           or t['content_ref']['sha256'] != new['entry']['sha256'] for t in row['targets'])):
                raise VisualConfirmationError('OpenFilm typography changed its visible words or reading windows')
            segment['bindings'][cid] = copy.deepcopy(prior)
            segment['strategy_revision'] = old_segments[key[0]]['strategy_revision']
            scene.clear(); scene.update(copy.deepcopy(original))
            row.clear(); row.update(copy.deepcopy(old_row))
            for group in ('beats','overlay_beats'):
                for beat in actual.get('skill_selection', {}).get(group, []):
                    if (beat['segment_id'],beat['component_id']) == key:
                        if beat.get('binding_snapshot') != binding:
                            raise VisualConfirmationError('OpenFilm typography binding snapshot is stale')
                        beat['binding_snapshot'] = copy.deepcopy(prior)
    return current, actual


def _normalize_native_supplements(root, proposal, frozen, frozen_treatment, director, treatment):
    """Complete an approved generated action with one independently bound alpha layer.

    This changes a comparison copy only. Production retains the real hybrid,
    original provider result, native input/result, text targets and diagnosis.
    """
    revisions = treatment.get('native_supplements', [])
    if not revisions:
        return director, treatment
    if not isinstance(revisions, list):
        raise VisualConfirmationError('native supplements must be an explicit list')
    from . import motion_capabilities
    current, actual = copy.deepcopy(director), copy.deepcopy(treatment)
    seen = set()
    for revision in revisions:
        fields = {'segment_id', 'base_component_id', 'action_component_id', 'reason'}
        if (not isinstance(revision, dict) or set(revision) != fields
                or any(not isinstance(revision[k], str) or not revision[k].strip() for k in fields)
                or revision['segment_id'] in seen):
            raise VisualConfirmationError('native supplement needs one diagnosed existing visual row')
        if revision in frozen_treatment.get('native_supplements', []):
            continue  # Already part of this proposal; ordinary native revision gates apply.
        sid, base_id, action_id = (revision[k] for k in ('segment_id', 'base_component_id', 'action_component_id'))
        seen.add(sid)
        old = [s for s in frozen['segments'] if s['segment_id'] == sid]
        new = [s for s in director['segments'] if s['segment_id'] == sid]
        if len(old) != 1 or len(new) != 1:
            raise VisualConfirmationError('native supplement must retain its existing segment')
        old, new = old[0], new[0]
        approved = old['visual_strategy']; strategy = new['visual_strategy']
        originals = approved['components']; components = {c['component_id']: c for c in strategy['components']}
        if (approved['mode'] != 'single' or approved['composition']['family'] != 'single_full_frame'
                or len(originals) != 1 or originals[0].get('component_id') != base_id
                or originals[0].get('kind') != 'ai_generated' or originals[0].get('media_type') != 'video'
                or originals[0].get('layer_role') != 'base' or originals[0].get('layout_slot') != 'full_frame'
                or originals[0].get('semantic_role') == 'evidence' or base_id == action_id
                or set(components) != {base_id, action_id} or len(strategy['components']) != 2
                or components[base_id] != originals[0] or strategy['mode'] != 'hybrid'
                or strategy['composition'].get('family') != 'evidence_with_data_overlay'
                or {k:v for k,v in strategy.items() if k not in {'mode','components','composition'}} !=
                   {k:v for k,v in approved.items() if k not in {'mode','components','composition'}}
                or {k:v for k,v in strategy['composition'].items() if k not in {'family','reading_order','component_dependencies'}} !=
                   {k:v for k,v in approved['composition'].items() if k not in {'family','reading_order','component_dependencies'}}
                or strategy['composition']['reading_order'] != [base_id, action_id]
                or strategy['composition']['component_dependencies'] != [{'component_id':action_id,'depends_on':[base_id]}]):
            raise VisualConfirmationError('native supplement changed the original source, presentation or composition scope')
        action = components[action_id]
        if (action.get('kind') != 'code_generated' or action.get('layer_role') != 'annotation'
                or action.get('layout_slot') != 'annotation' or action.get('semantic_role') != originals[0]['semantic_role']
                or action.get('brief') != originals[0]['brief']):
            raise VisualConfirmationError('native supplement must only complete its exact approved explanatory action')
        binding, adapter, brief, payload = _motion_brief(root, director, treatment, (sid, action_id))
        if (binding.get('dependency_id') != 'barty-motion-graphics'
                or brief['template_id'] != 'motion-broll' or brief['alpha'] is not True
                or brief['authorization'].get('paid_generation') is not False
                or brief['task_source'] != adapter.task_source(frozen, frozen_treatment, sid, base_id)
                or brief['transcript'] != brief['task_source']['quote']):
            raise VisualConfirmationError('native supplement changed the approved task or native authorization')
        record, _ = motion_capabilities._ai_brief_evidence(root, treatment, new, base_id)
        steps = [s for s in proposal.get('generation_steps', []) if
                 (s.get('segment_id'),s.get('component_id'),s.get('purpose')) == (sid,base_id,'video')]
        source = record.get('source_binding', {})
        material = {k:record.get('media', {}).get(k) for k in ('job_path','sha256','byte_count')}
        generation = record.get('generation', {})
        authorization = generation.get('approved_plan', {})
        if not isinstance(authorization.get('source'), dict):
            raise VisualConfirmationError('native supplement has no original visual confirmation reference')
        _, source_proposal = _validate_source(root, authorization['source'], job_id=record.get('job_id'))
        if source_proposal != proposal:
            raise VisualConfirmationError('native supplement video belongs to another approved visual proposal')
        if (len(steps) != 1 or not generation.get('approved_request_id')
                or generation.get('approved_request_id') != generation.get('approved_request', {}).get('id')
                or generation.get('approved_plan', {}).get('steps', {}).get(generation['approved_request_id']) != steps[0]['id']
                or record.get('composition_base', {}).get('action_component_id') != action_id
                or record.get('composition_base', {}).get('source_qa', {}).get('passed') is not False
                or record.get('qa', {}).get('scope') != 'composition_base'
                or brief['source_binding'] != {**source, 'segment_id':sid}
                or material not in brief['materials']):
            raise VisualConfirmationError('native supplement lacks the original completed video, failed-effect scope or matching clock')
        # The completed-record validator proves the exact approved queue target;
        # alpha result validation separately proves the actual native invocation.
        result_path = _path(root, brief['result_record_path'])
        targets = [r for r in treatment.get('motion_readability', [])
                   if (r.get('segment_id'),r.get('component_id')) == (sid,action_id)]
        if len(targets) != 1:
            raise VisualConfirmationError('native supplement requires its own actual text inventory')
        if result_path.is_file():
            _validate_canvas_alignment(root, director, treatment, (sid,action_id), adapter, brief, payload,
                                       binding.get('invocation_record', {}).get('canvas_alignment'))
            _freeze_reviewed_native_result(root, treatment, sid, action_id, payload, 'barty-motion-graphics', new)
            result = adapter.inspect_result(root, payload)
            call = _read(adapter.exact(root, result['render_call']))
            sources = {f['job_path']:f['sha256'] for f in call['project_files']}
            for target in targets[0].get('targets', []):
                ref = target['content_ref']
                if sources.get(ref['path']) != ref['sha256'] or not ref['pointer'].startswith('text:'):
                    raise VisualConfirmationError('native supplement text must cite the actual rendered native source')
            from . import motion_readability
            motion_readability.validate_targets([{**new,'shot_recipe':{'components':[action]}}], targets,
                motion_readability._required_refs({'motion_readability':targets}), root=root)
        elif targets[0] != {'segment_id':sid,'component_id':action_id,'targets':[],'pending_native':True}:
            raise VisualConfirmationError('unfinished native supplement cannot claim completed text or output')
        required = set(old['visible_text'])
        text = _readability_texts(targets, {(sid,action_id)})
        if not required <= set(new['visible_text']) or set(new['visible_text']) - required != text - required:
            raise VisualConfirmationError('native supplement changed approved text or omitted its actual readable text')
        compared = next(s for s in current['segments'] if s['segment_id'] == sid)
        compared['visual_strategy'] = copy.deepcopy(approved)
        compared['visible_text'] = copy.deepcopy(old['visible_text'])
        compared['bindings'].pop(action_id)
        def added(item):
            return (item.get('segment_id'),item.get('component_id')) == (sid,action_id)
        for group in ('scenes','motion_queries','motion_readability','semantic_assessments'):
            actual[group] = [item for item in actual.get(group, []) if not added(item)]
        for group in ('beats','assignments'):
            actual['skill_selection'][group] = [item for item in actual['skill_selection'].get(group, []) if not added(item)]
        for row in actual.get('semantic_lists', {}).get('broll', []):
            row['components'] = [item for item in row['components'] if not added(item)]
        for index, beat in enumerate(actual.get('beat_sheet', [])):
            if any(added(item) for item in beat['components']):
                if ({'segment_id':sid,'component_id':base_id} not in beat['components']
                        or not isinstance(beat.get('merge_reason'), str) or not beat['merge_reason'].strip()
                        or index >= len(frozen_treatment.get('beat_sheet', []))):
                    raise VisualConfirmationError('native supplement must share its original beat with an explicit merge reason')
                original_beat = frozen_treatment['beat_sheet'][index]
                if 'merge_reason' in original_beat:
                    if beat['merge_reason'] != original_beat['merge_reason']:
                        raise VisualConfirmationError('native supplement changed an existing merge reason')
                else:
                    beat.pop('merge_reason')
            beat['components'] = [item for item in beat['components'] if not added(item)]
    return current, actual


def _validate_generated_readability(root, proposal, frozen, frozen_treatment, director, treatment, evidence,
                                    *, production_director, production_treatment):
    """Resolve only explicitly deferred text, using existing completed inputs."""
    from . import motion_readability, motion_capabilities
    old = {(r['segment_id'], r['component_id']): r for r in frozen_treatment.get('motion_readability', [])}
    keys = {key for key, row in old.items() if row.get('pending_generation') is True}
    if not keys:
        return treatment
    project = Path(__file__).resolve().parents[3]
    eligible = planned_generation_targets(project, frozen, frozen_treatment, job_dir=root)
    if not keys <= eligible:
        raise VisualConfirmationError('deferred text is not an uncreated approved generation target')
    actual = copy.deepcopy(treatment)
    reviews = actual.pop('reviewed_generated_text', [])
    if not isinstance(reviews, list):
        raise VisualConfirmationError('generated text reviews must be a list')
    used_reviews = set()
    records = {(r['segment_id'], r['component_id']): r for r in actual.get('motion_readability', [])}
    if len(records) != len(actual.get('motion_readability', [])) or set(records) != set(old):
        raise VisualConfirmationError('generation realization changed the text component inventory')
    completed = {e['step_id']: e for e in evidence}
    if len(completed) != len(evidence):
        raise VisualConfirmationError('generation completion evidence is duplicated')
    segments = {s['segment_id']: s for s in director['segments']}
    production_segments = {s['segment_id']: s for s in production_director['segments']}
    originals = {s['segment_id']: s for s in frozen['segments']}
    for key in keys:
        record = records[key]
        if record == old[key]:
            continue  # Still pending; the existing completed-phase gate rejects it.
        steps = [s for s in _steps(frozen_treatment) if (s['segment_id'], s['component_id']) == key]
        if not steps or any(s not in proposal.get('generation_steps', []) for s in steps):
            raise VisualConfirmationError('deferred text has no unchanged approved generation steps')
        for step in steps:
            done = completed.get(step['id'])
            if not done or not done.get('media'):
                raise VisualConfirmationError('deferred text needs actual completed generation evidence')
            for media in done['media']:
                _exact(root, media)
        segment = segments[key[0]]
        original = originals[key[0]]
        approved_text = set(original['visible_text'])
        visible = set(segment['visible_text'])
        if not approved_text <= visible:
            raise VisualConfirmationError('generation text must retain approved wording')
        original_component = next((c for c in original['visual_strategy']['components']
                                   if c['component_id'] == key[1]), None)
        approved_brief = original_component.get('brief') if original_component else None
        outputs = [media for step in steps if step.get('purpose') == 'image'
                   for media in completed[step['id']]['media']]
        for text in visible - approved_text:
            matching = [(i, review) for i, review in enumerate(reviews)
                        if isinstance(review, dict) and (review.get('segment_id'), review.get('component_id'), review.get('text')) == (*key, text)]
            if len(matching) != 1:
                raise VisualConfirmationError('generated text needs one explicit human review')
            index, review = matching[0]
            if (set(review) != {'segment_id', 'component_id', 'text', 'source_quote', 'source_image', 'verdict', 'reason'}
                    or not isinstance(approved_brief, str) or review['source_quote'] != approved_brief
                    or review['source_image'] not in outputs or review['verdict'] != 'pass'
                    or not isinstance(review['reason'], str) or not review['reason'].strip()):
                raise VisualConfirmationError('generated text review differs from approved semantics or source image')
            _exact(root, review['source_image'])
            used_reviews.add(index)
        scoped = {**segment, 'shot_recipe': {'components': [c for c in segment['visual_strategy']['components']
                    if c['component_id'] == key[1]]}}
        motion_readability.validate_targets([scoped], [record],
            motion_readability._required_refs({'motion_readability': [record]}), root=root)
        if {t['content_ref']['value'] for t in record.get('targets', [])} != set(segment['visible_text']):
            raise VisualConfirmationError('generation text targets must retain the exact approved text inventory')
        production_segment = production_segments[key[0]]
        binding = production_segment['bindings'][key[1]]
        if binding.get('execution_mode') in {'reuse_completed_lovart_video', 'reuse_completed_generated_media'}:
            brief, ref = motion_capabilities._ai_brief_evidence(root, production_treatment, production_segment, key[1])
            allowed = {ref['job_path']: ref['sha256']}
        else:
            brief = motion_capabilities._bound_brief(root, production_treatment, production_segment, key[1])
            relative = motion_capabilities._brief_relative(production_treatment, production_segment, key[1])
            allowed = {relative: binding.get('brief_sha256')}
        if brief is None:
            raise VisualConfirmationError('generation text requires its actual bound production input')
        from . import parent_static_labels
        labels = parent_static_labels.load(root, production_segment, key[1])
        if labels:
            parent_static_labels.validate_targets(labels, record.get('targets', []))
            for label in labels:
                ref = label['content_ref']
                allowed[ref['path']] = ref['sha256']
        def collect(value):
            if isinstance(value, dict):
                if {'job_path', 'sha256'} <= set(value):
                    allowed[value['job_path']] = value['sha256']
                for child in value.values(): collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(brief)
        for target in record.get('targets', []):
            ref = target['content_ref']
            image_source = (ref['pointer'] == 'image-text' and any(
                ref['path'] == output['path'] and ref['sha256'] == output['sha256'] for output in outputs))
            if ((allowed.get(ref['path']) != ref['sha256'] and not image_source)
                    or any(ref['pointer'].startswith('/' + field) for field in
                        ('prompt', 'template_request', 'creative_handoff', 'source_binding', 'composition',
                         'transcript', 'semantic_goal', 'required_change', 'authorization'))):
                raise VisualConfirmationError('generation text must cite actual bound content, not a production promise')
        segment['visible_text'] = copy.deepcopy(original['visible_text'])
        records[key] = copy.deepcopy(old[key])
    if used_reviews != set(range(len(reviews))):
        raise VisualConfirmationError('generated text review is unused or does not match an approved component')
    actual['motion_readability'] = [records[(r['segment_id'], r['component_id'])]
                                    for r in actual.get('motion_readability', [])]
    return actual


def _validate_draft_against_source(root, proposal, director, treatment, *, generation_evidence=()):
    frozen = _read(_exact(root, proposal["inputs"]["director"]))
    frozen_treatment = _read(_exact(root, proposal["inputs"]["treatment"]))
    _validate_parent_camera_framing(root, proposal, frozen, director, treatment)
    actual_director, actual_treatment = director, treatment
    director, treatment = _normalize_prepared_wake(root, proposal, frozen, frozen_treatment, director, treatment)
    director, treatment = _normalize_native_supplements(root, proposal, frozen, frozen_treatment, director, treatment)
    director, treatment = _validate_motion_realization(root, frozen, frozen_treatment, director, treatment)
    director, treatment = _normalize_lemo_typography(root, frozen, frozen_treatment, director, treatment)
    director, treatment = _normalize_openfilm_typography(root, frozen, frozen_treatment, director, treatment)
    director = _normalize_verified_technical_revisions(frozen, frozen_treatment, actual_director, actual_treatment, director)
    treatment = _normalize_official_crop_text(root, frozen, frozen_treatment, actual_director, actual_treatment, treatment)
    treatment = _validate_generated_readability(root, proposal, frozen, frozen_treatment,
                                               director, treatment, generation_evidence,
                                               production_director=actual_director,
                                               production_treatment=actual_treatment)
    if treatment.get("motion_readability", []) != frozen_treatment.get("motion_readability", []):
        raise VisualConfirmationError("readability targets changed after visual approval")
    if (_core(director) != _core(frozen)
            or treatment.get("semantic_lists") != frozen_treatment.get("semantic_lists")
            or treatment.get("motion_matches") != frozen_treatment.get("motion_matches")
            or treatment.get("motion_queries", []) != frozen_treatment.get("motion_queries", [])
            or treatment.get("skill_selection", {}).get("assignments", []) != frozen_treatment.get("skill_selection", {}).get("assignments", [])
            or treatment.get("skill_selection", {}).get("overlay_assignments", []) != frozen_treatment.get("skill_selection", {}).get("overlay_assignments", [])
            or treatment.get("skill_selection", {}).get("fixed_context", []) != frozen_treatment.get("skill_selection", {}).get("fixed_context", [])
            or treatment.get("skill_selection", {}).get("opening") != frozen_treatment.get("skill_selection", {}).get("opening")
            or treatment.get("generation_plan", {}) != frozen_treatment.get("generation_plan", {})):
        raise VisualConfirmationError("realization changed approved timing, meaning, tags or template")
    if any(treatment.get(field) != frozen_treatment.get(field) for field in ('numbering_scope_id', 'beat_sheet', 'overlay_selection')):
        raise VisualConfirmationError('realization changed approved rows, numbering, scene inputs or overlay use')
    for segment, original in zip(director["segments"], frozen["segments"]):
        for cid, binding in original.get("bindings", {}).items():
            new = segment.get("bindings", {}).get(cid, {})
            if any(new.get(k) != v for k, v in binding.items()):
                raise VisualConfirmationError("realization replaced an approved template or source")


def _normalize_official_crop_text(root, frozen, frozen_treatment, director, treatment, comparison):
    """Only map text regions for a same-source official-image portrait crop."""
    from PIL import Image
    from .visual_strategy import official_portrait_crop
    originals = {s['segment_id']: s for s in frozen['segments']}
    old_rows = {(r['segment_id'], r['component_id']): r for r in frozen_treatment.get('motion_readability', [])}
    result = copy.deepcopy(comparison)
    actual_rows = {(r['segment_id'], r['component_id']): r for r in treatment.get('motion_readability', [])}
    for segment in director['segments']:
        for component in segment['visual_strategy']['components']:
            cid = component['component_id']
            binding = segment['bindings'][cid]
            if component['kind'] != 'official_material' or 'portrait_crop' not in binding:
                continue
            old = originals[segment['segment_id']]['bindings'][cid]
            if binding.get('portrait_crop') == old.get('portrait_crop'):
                continue
            if (component['media_type'] != 'image' or any(binding.get(k) != v for k, v in old.items())
                    or set(binding) != set(old) | {'portrait_crop'}):
                raise VisualConfirmationError('official crop must retain the exact approved source binding')
            crop = official_portrait_crop(binding)
            image = _path(Path(root), binding['snapshot_path'])
            if artifacts.sha256_file(image) != binding['sha256']:
                raise VisualConfirmationError('official crop source changed')
            with Image.open(image) as picture:
                if picture.size != (crop['source_width'], crop['source_height']):
                    raise VisualConfirmationError('official crop dimensions differ from the original image')
            key = (segment['segment_id'], cid)
            before, after = old_rows[key], actual_rows[key]
            normalized = copy.deepcopy(after)
            if len(normalized.get('targets', [])) != len(before.get('targets', [])):
                raise VisualConfirmationError('official crop must retain every approved text target')
            for target, original in zip(normalized.get('targets', []), before.get('targets', [])):
                target['region'] = copy.deepcopy(original['region'])
            if normalized != before:
                raise VisualConfirmationError('official crop may map text regions only')
            for index, row in enumerate(result.get('motion_readability', [])):
                if (row['segment_id'], row['component_id']) == key:
                    result['motion_readability'][index] = copy.deepcopy(before)
    return result


def _validate_parent_camera_framing(root, proposal, frozen, director, treatment):
    """Bind the camera to the actual source; leave every semantic core field locked."""
    from . import motion_capabilities, parent_camera_framing, state
    originals = {s['segment_id']:s for s in frozen['segments']}
    for segment in director['segments']:
        for cid, binding in segment.get('bindings', {}).items():
            ref = binding.get(parent_camera_framing.FIELD)
            if ref is None:
                continue
            before = originals.get(segment['segment_id'], {})
            record, _ = motion_capabilities._ai_brief_evidence(root, treatment, segment, cid)
            if (record.get('camera_source', {}).get('framing') != ref
                    or record.get('qa', {}).get('scope') != 'framing_source'):
                raise VisualConfirmationError('camera framing requires its separately scoped original-video record')
            module = __import__('generated_media')
            module.validate_camera_source(state.load_job(Path(root)), record, segment)
            if before.get('bindings', {}).get(cid, {}).get(parent_camera_framing.FIELD) == ref:
                continue  # The exact framing is already frozen by this proposal.
            generation = record.get('generation', {})
            authorization = generation.get('approved_plan', {})
            if not isinstance(authorization.get('source'), dict):
                raise VisualConfirmationError('camera framing has no original visual confirmation reference')
            _, source_proposal = _validate_source(root, authorization['source'], job_id=record.get('job_id'))
            if source_proposal != proposal:
                raise VisualConfirmationError('camera framing belongs to another approved visual proposal')


def _normalize_verified_technical_revisions(frozen, frozen_treatment, actual, treatment, normalized):
    """Only after the two real-input verifiers, hide their revision in comparisons."""
    result = copy.deepcopy(normalized)
    old = {s['segment_id']: s for s in frozen['segments']}
    originals = {s['segment_id']: s for s in actual['segments']}
    old_scenes = {(s.get('segment_id'), s.get('component_id')): s for s in frozen_treatment.get('scenes', [])}
    scenes = {(s.get('segment_id'), s.get('component_id')): s for s in treatment.get('scenes', [])}
    for segment in result['segments']:
        sid = segment['segment_id']
        before, submitted = old.get(sid), originals.get(sid)
        if before is None or submitted is None:
            continue
        old_revision, new_revision = before.get('strategy_revision'), submitted.get('strategy_revision')
        if old_revision == new_revision or segment['strategy_revision'] == old_revision:
            continue
        if (type(old_revision) is not int or type(new_revision) is not int or new_revision <= old_revision):
            raise VisualConfirmationError('technical strategy revision must increase')
        proof = False
        for cid, binding in submitted.get('bindings', {}).items():
            prior = before.get('bindings', {}).get(cid, {})
            alignment = binding.get('invocation_record', {}).get('canvas_alignment')
            old_alignment = prior.get('invocation_record', {}).get('canvas_alignment')
            typography = scenes.get((sid, cid), {}).get('native_typography_revision')
            previous_typography = old_scenes.get((sid, cid), {}).get('native_typography_revision')
            native_origin = scenes.get((sid, cid), {}).get('native_revision_from')
            if ((binding.get('dependency_id') in MOTION_CREATION and prior.get('dependency_id') == binding.get('dependency_id')
                 and ((alignment is not None and alignment != old_alignment) or native_origin is not None))
                    or (binding.get('dependency_id') == 'lemo-opuscar' and prior.get('dependency_id') == 'lemo-opuscar'
                        and typography is not None and typography != previous_typography and binding != prior)):
                proof = True
        if not proof:
            raise VisualConfirmationError('technical strategy revision needs a verified implementation change')
        segment['strategy_revision'] = old_revision
    return result


def validate_realization_draft(job, director, treatment):
    authorized = validate_visual_authorization(job)
    frozen = _read(_exact(job.job_dir, authorized['source']['inputs']['treatment']))
    deferred = any(r.get('pending_generation') is True for r in frozen.get('motion_readability', []))
    evidence = _completed_generations(job, authorized['source']) if deferred else []
    _validate_draft_against_source(job.job_dir, authorized["source"], director, treatment,
                                 generation_evidence=evidence)
    return authorized


def _completed_generations(job, proposal):
    from . import generation_queue
    queue = generation_queue.status(job.job_dir)
    generations = []
    for step in proposal["generation_steps"]:
        rid, item = generation_item(queue, proposal, step, job)
        item = item or {}
        if item.get("status") != "completed":
            raise VisualConfirmationError("an approved generation step is not complete")
        response = item.get("completion_response", item.get("response", {}))
        media = []
        for output in response["artifacts"]:
            path = Path(output["path"])
            media.append(_record(job.job_dir, path if path.is_absolute() else job.job_dir / path))
        generations.append({"step_id": step["id"], "request_id": rid,
                            "request": item["request"], "media": media})
    return generations


def _write_unique_mapping(root, revision, payload):
    data = artifacts.canonical_json_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    directory = Path(root) / DIRECTORY / f'realization-r{revision}-{digest}'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MAPPING
    fd, temp_name = tempfile.mkstemp(prefix='.mapping-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temp_name, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise VisualConfirmationError('existing realization mapping differs')
    finally:
        os.unlink(temp_name)
    return path


def write_realization_mapping(job, *, host_qa_note, director_path, treatment_path):
    from . import state
    if (job.stages['visual_direction']['status'] == 'approved'
            or any(ref['path'].endswith('/' + MAPPING) for ref in job.stages['visual_direction']['artifacts'])):
        raise VisualConfirmationError('the reviewed realization is frozen; use the existing stage revision entry')
    authorized = validate_visual_authorization(job)
    proposal = authorized["source"]
    generations = _completed_generations(job, proposal)
    final_records = copy.deepcopy(job.stages["visual_direction"]["artifacts"])
    final = next(r for r in final_records if r["path"] == "07-visual-direction/visual-plan.json")
    treatment = _read(treatment_path)
    completed_records = []
    native_inputs = []
    realized_director = _read(director_path)
    bindings = {(seg["segment_id"], cid): value for seg in realized_director["segments"]
                for cid, value in seg.get("bindings", {}).items()}
    for scene in treatment.get("scenes", []):
        ref = scene.get("completed_record")
        if ref:
            if scene.get('asset_provenance') is not None:
                raise VisualConfirmationError('Paper crop provenance requires its bound native brief')
            record = _record(job.job_dir, _path(job.job_dir, ref["job_path"]))
            if (record["sha256"], record["bytes"]) != (ref["sha256"], ref["byte_count"]):
                raise VisualConfirmationError("completed template input changed")
            completed_records.append(record)
        elif scene.get("brief_path"):
            ref = _record(job.job_dir, _path(job.job_dir, scene["brief_path"]))
            keys = [key for key, value in bindings.items() if key[0] == scene["segment_id"]
                    and (scene.get("component_id") is None or key[1] == scene["component_id"])
                    and value.get("brief_sha256") == ref["sha256"]]
            if len(keys) != 1:
                raise VisualConfirmationError("template brief must identify one actual component")
            key = keys[0]
            if bindings.get(key, {}).get("brief_sha256") != ref["sha256"]:
                raise VisualConfirmationError("template brief differs from its actual binding")
            item = {"segment_id": key[0], "component_id": key[1], "artifact": ref}
            provenance = scene.get('asset_provenance')
            if provenance is not None:
                if (bindings[key].get('dependency_id') != 'paper-collage-hyperframes'
                        or not isinstance(provenance, dict)
                        or set(provenance) != {'job_path', 'sha256', 'byte_count'}):
                    raise VisualConfirmationError('invalid Paper scene crop provenance')
                evidence = _record(job.job_dir, _path(job.job_dir, provenance['job_path']))
                if (evidence['sha256'], evidence['bytes']) != (provenance['sha256'], provenance['byte_count']):
                    raise VisualConfirmationError('Paper crop provenance changed')
                item['asset_provenance'] = evidence
            if bindings[key].get("dependency_id") in NATIVE_RESULT_MODULES:
                item["result_record"] = _freeze_reviewed_native_result(
                    job.job_dir, treatment, key[0], key[1], _exact(job.job_dir, ref).read_bytes(),
                    bindings[key]["dependency_id"], next(s for s in realized_director['segments'] if s['segment_id'] == key[0]))
            native_inputs.append(item)
        elif scene.get('asset_provenance') is not None:
            raise VisualConfirmationError('Paper crop provenance requires its bound native brief')
    payload = {"schema_version": 1, "source_approval": authorized["artifact"],
               "proposal": authorized["payload"]["source"], "final_v3": final,
               "artifacts": final_records, "rows": proposal["rows"],
               "generations": generations, "completed_records": completed_records, "native_inputs": native_inputs,
               "realization_inputs": {"director": _record(job.job_dir, director_path),
                                      "treatment": _record(job.job_dir, treatment_path)},
               "host_qa_note": host_qa_note}
    path = _write_unique_mapping(job.job_dir, job.revision, payload)
    state.mark_visual_ready(job, [*(_path(job.job_dir, r["path"]) for r in final_records), path])
    return path

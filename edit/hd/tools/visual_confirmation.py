"""Immutable visual proposal, source approval, and realized production evidence."""
from __future__ import annotations
import copy
import hashlib
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

def _wake_adapter():
    import importlib.util
    path = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/lemo_wake_adapter.py"
    spec = importlib.util.spec_from_file_location("_wake_mapping_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wake_review_reference(treatment, segment_id, component_id, result_path):
    assessments = [item for item in treatment.get("semantic_assessments", [])
                   if item.get("segment_id") == segment_id and item.get("component_id") == component_id]
    if (len(assessments) != 1 or assessments[0].get("verdict") != "pass"
            or assessments[0].get("candidate_id") != "lemo-wake:wake"):
        raise VisualConfirmationError("Wake needs one passing content assessment for this component")
    refs = [ref for ref in assessments[0].get("content_refs", []) if ref.get("path") == result_path]
    if (len(refs) != 1 or refs[0].get("pointer") != "/status" or refs[0].get("value") != "completed"
            or not isinstance(refs[0].get("sha256"), str)):
        raise VisualConfirmationError("Wake assessment must identify the reviewed completed result")
    return refs[0]


def _freeze_reviewed_wake_result(root, treatment, segment_id, component_id, brief_payload):
    """Bind the bytes that were reviewed; never bless the current path implicitly."""
    import json
    brief = json.loads(brief_payload)
    relative = brief["result_record_path"]
    reviewed = _wake_review_reference(treatment, segment_id, component_id, relative)
    data = _path(root, relative).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != reviewed["sha256"]:
        raise VisualConfirmationError("Wake result differs from the content the host reviewed")
    _wake_adapter().inspect_result(root, brief_payload, record_bytes=data)
    return {"path": relative, "sha256": digest, "bytes": len(data)}


def _validate_native_results(root, mapping, director, treatment):
    """Validate frozen native results without calling an approved-plan loader."""
    for segment in director["segments"]:
        for cid, binding in segment.get("bindings", {}).items():
            if binding.get("dependency_id") != "lemo-wake":
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
            reviewed = _wake_review_reference(treatment, segment["segment_id"], cid, expected["path"])
            if reviewed["sha256"] != expected["sha256"]:
                raise VisualConfirmationError("Wake mapping differs from the host's reviewed result")
            _wake_adapter().load_result(root, payload, expected_record=expected)


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
    cached = motion_match_cache.validate_reviews(project, director, treatment, job_dir=job.job_dir)
    selection = treatment.get("skill_selection", {})
    if selection:
        chosen = broll_skill_selection.assign_skills(project, selection, job_dir=job.job_dir)
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
    motion_match_cache.validate_design_handoffs(director, treatment, job.job_dir)

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
    confirmed_content.check_confirmed_content(job, director)
    steps = _steps(treatment)
    try:
        _validate_template_choices(job, director, treatment)
    except ValueError as error:
        raise VisualConfirmationError("visual selection: " + str(error)) from error
    from . import overlay_alignment
    overlay_alignment.validate_treatment(job, director, Path(treatment_path))
    from . import motion_readability
    motion_readability.validate_direction_contract(job, director, treatment)
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
    if steps:
        for segment in director["segments"]:
            for cid, binding in segment.get("bindings", {}).items():
                direct = any(c["component_id"] == cid and c["kind"] == "ai_generated" for c in segment["visual_strategy"]["components"])
                if direct and any((step["segment_id"], step["component_id"]) == (segment["segment_id"], cid) for step in steps):
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
             "时间为剪后正文时间，Wake 首镜从第 0 帧开始。整表确认后按表制作并直接交付。", "",
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
    mapping = next((r for r in records if r["path"].endswith("/" + MAPPING)), None)
    if mapping:
        return _read(_exact(job.job_dir, mapping))["proposal"]
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

def validate_realization_evidence(job_dir, stages, revision, receipt_descriptor, *, job_id=None):
    """Read-only shared check; imports neither state nor media engines."""
    root = Path(job_dir)
    receipt, proposal = _validate_source(root, receipt_descriptor, job_id=job_id)
    stage = stages["visual_direction"]
    map_ref = next((r for r in stage["artifacts"] if r["path"].endswith("/" + MAPPING)), None)
    if map_ref is None:
        raise VisualConfirmationError("the realized visual mapping is missing")
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
    director = _read(_exact(root, proposal["inputs"]["director"]))
    if _core(final) != _core(director):
        raise VisualConfirmationError("realized timing, meaning or template composition changed")
    if mapping.get("rows") != proposal["rows"]:
        raise VisualConfirmationError("realized visual rows changed")
    if receipt["revision"] >= revision:
        raise VisualConfirmationError("visual approval revision is not committed")
    realized = {key: _read(_exact(root, ref)) for key, ref in mapping["realization_inputs"].items()}
    _validate_draft_against_source(root, proposal, realized["director"], realized["treatment"])
    compiled = {(seg["segment_id"], c["component_id"]): c
                for seg in final["segments"] for c in seg["shot_recipe"]["components"]}
    for seg in realized["director"]["segments"]:
        for cid, binding in seg.get("bindings", {}).items():
            consumed = {"execution_mode", "media_type", "source_dimensions"}
            if any(compiled[(seg["segment_id"], cid)].get(k) != value
                   for k, value in binding.items() if k not in consumed):
                raise VisualConfirmationError("compiled template differs from the realized inputs")
    expected_steps = {step["id"] for step in proposal["generation_steps"]}
    generations = mapping.get("generations", [])
    if {item["step_id"] for item in generations} != expected_steps or len(generations) != len(expected_steps):
        raise VisualConfirmationError("realization does not cover every approved generation step")
    for ref in mapping.get("completed_records", []):
        _exact(root, ref)
    used_hashes = set()
    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get("sha256"), str):
                used_hashes.add(value["sha256"])
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)
    _validate_native_results(root, mapping, realized["director"], realized["treatment"])
    collect(realized)
    for record in mapping.get("completed_records", []):
        collect(_read(_exact(root, record)))
    for native in mapping.get("native_inputs", []):
        collect(_read(_exact(root, native["artifact"])))
    # Generated image intermediates are consumed by later approved requests;
    # final images/videos are consumed by the native input or component binding.
    for generation in generations:
        for ref in generation["request"].get("input_files", []):
            _exact(root, ref)
            used_hashes.add(ref["sha256"])
    record_payloads = [_read(_exact(root, ref)) for ref in mapping.get("completed_records", [])]
    for generation in generations:
        step = next(step for step in proposal["generation_steps"] if step["id"] == generation["step_id"])
        target = (step["segment_id"], step["component_id"])
        for record in record_payloads:
            if record.get("generation_id") == generation["request_id"] and (record["segment_id"], record["component_id"]) != target:
                raise VisualConfirmationError("completed generation belongs to another approved visual row")
        for media in generation["media"]:
            _exact(root, media)
            if media["sha256"] not in used_hashes:
                raise VisualConfirmationError("a generated output is not bound to the realized template")
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
            validate_generation_request(job, auth, old)
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
            current = _build_generation_request(job, proposal, step)
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

def _build_generation_request(job, proposal, step):
    from . import generation_channels, generation_queue
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

def validate_generation_request(job, authorization, request):
    receipt, proposal = _validate_source(job.job_dir, authorization["source"], job_id=job.job_id)
    step_id = authorization["steps"][request["id"]]
    step = next((s for s in proposal["generation_steps"] if s["id"] == step_id), None)
    if step is None or request != _build_generation_request(job, proposal, step):
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

def _validate_draft_against_source(root, proposal, director, treatment):
    frozen = _read(_exact(root, proposal["inputs"]["director"]))
    frozen_treatment = _read(_exact(root, proposal["inputs"]["treatment"]))
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
    for segment, original in zip(director["segments"], frozen["segments"]):
        for cid, binding in original.get("bindings", {}).items():
            new = segment.get("bindings", {}).get(cid, {})
            if any(new.get(k) != v for k, v in binding.items()):
                raise VisualConfirmationError("realization replaced an approved template or source")


def validate_realization_draft(job, director, treatment):
    authorized = validate_visual_authorization(job)
    _validate_draft_against_source(job.job_dir, authorized["source"], director, treatment)
    return authorized


def write_realization_mapping(job, *, host_qa_note, director_path, treatment_path):
    from . import generation_queue, state
    authorized = validate_visual_authorization(job)
    proposal = authorized["source"]
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
            if bindings[key].get("dependency_id") == "lemo-wake":
                item["result_record"] = _freeze_reviewed_wake_result(
                    job.job_dir, treatment, key[0], key[1], _exact(job.job_dir, ref).read_bytes())
            native_inputs.append(item)
    payload = {"schema_version": 1, "source_approval": authorized["artifact"],
               "proposal": authorized["payload"]["source"], "final_v3": final,
               "artifacts": final_records, "rows": proposal["rows"],
               "generations": generations, "completed_records": completed_records, "native_inputs": native_inputs,
               "realization_inputs": {"director": _record(job.job_dir, director_path),
                                      "treatment": _record(job.job_dir, treatment_path)},
               "host_qa_note": host_qa_note}
    path = _path(job.job_dir, authorized["payload"]["source"]["path"]).parent / MAPPING
    artifacts.write_json_artifact(path, payload)
    state.mark_visual_ready(job, [*(_path(job.job_dir, r["path"]) for r in final_records), path])
    return path

"""Immutable visual proposal, source approval, and realized production evidence."""
from __future__ import annotations
import copy
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

def _prior_numbering(job):
    """Read numbering from an earlier approved proposal in this Job only.

    Older proposals did not persist numbering; their frozen row order is the
    explicit starting point for the new mapping.
    """
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
            rows = proposal.get("rows", [])
            numbering = proposal.get("numbering")
            if numbering is not None:
                _validate_numbering(numbering)
                if any(row["row_id"] not in numbering for row in rows):
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
        row_id = row.get("row_id")
        if row_id not in mapping:
            mapping[row_id] = next_number
            next_number += 1
        numbered.append({**row, "number": mapping[row_id]})
    return numbered

def approved_numbered_rows(job):
    proposal = validate_visual_authorization(job)["source"]
    return number_visual_rows(proposal["rows"], proposal.get("numbering"))

def _rows(director, treatment, speech):
    from .broll_skill_selection import source_channel

    queries = {(q["segment_id"], q["component_id"]): q for q in treatment.get("motion_queries", [])}
    assignments = {(q["segment_id"], q["component_id"]): q["candidate_id"]
                   for q in treatment.get("skill_selection", {}).get("assignments", [])}
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
            template = ("素材直用（无动效模板）" if direct_material else
                        (assignments.get((sid, cid)) or binding.get("template_id")))
            if not template and component["kind"] == "ai_generated":
                planned = [step["id"] for step in _steps(treatment) if
                           (step["segment_id"], step["component_id"]) == (sid, cid)]
                if not planned and not binding.get("generation_id") and not source:
                    raise VisualConfirmationError("direct AI B-roll needs an explicit generation plan or completed result")
                template = ("AI生成方案：" + (" → ".join(planned) or binding["generation_id"])
                            if planned or binding.get("generation_id") else "AI生成结果（无动效模板）")
            if not template:
                raise VisualConfirmationError("each visual row needs its actual template or material source")
            rows.append({"row_id": sid + ":" + cid, "segment_id": sid, "component_id": cid,
                         "start": segment["start"], "end": segment["end"],
                         "type": "贴片" if component.get("layer_role") == "annotation" else "B-roll",
                         "spoken_text": spoken, "semantic": segment["visual_intent"]["statement"],
                         "tags": tags, "source": source,
                         "channel": source_channel(binding.get("dependency_id") or
                                     binding.get("provider") or component["kind"]),
                         "template": template})
    return rows

def _validate_template_choices(job, director, treatment):
    from . import broll_skill_selection, motion_capabilities, overlay_selection
    project = Path(__file__).resolve().parents[3]
    selection = treatment.get("skill_selection", {})
    if selection:
        chosen = broll_skill_selection.assign_skills(project, selection)
        if chosen["assignments"] != selection.get("assignments"):
            raise VisualConfirmationError("complete-list template assignments have not been resolved")
    candidates = {(a["segment_id"], a["component_id"]): a["candidate_id"]
                  for a in selection.get("assignments", [])}
    for segment in director["segments"]:
        for component in segment["visual_strategy"]["components"]:
            sid, cid = segment["segment_id"], component["component_id"]
            if component["kind"] not in {"code_generated", "ai_generated"}:
                continue
            candidate = candidates.get((sid, cid))
            if segment["visual_strategy"]["composition"]["family"] == "aroll_with_overlay":
                candidate = "overlay:" + overlay_selection._route(segment["bindings"][cid])
            if candidate is None and component["kind"] == "ai_generated":
                continue  # Explicit direct generation is a material source, not a library template.
            query = next((q for q in treatment.get("motion_queries", [])
                          if (q["segment_id"], q["component_id"]) == (sid, cid)), {})
            matches = motion_capabilities.search_capabilities(project, " ".join(query.get("tags", [])),
                        use="aroll_overlay" if candidate and candidate.startswith("overlay:") else "broll")
            if candidate not in {match["candidate_id"] for match in matches}:
                raise VisualConfirmationError("the selected template does not match this row's semantic tags")

def prepare_visual_confirmation(job, director_path, treatment_path, reviewed_visual_text=None):
    from . import state, visual_plan, motion_capabilities, startup, confirmed_content
    state.require_runnable(job, "visual_direction")
    director, treatment = _read(director_path), _read(treatment_path)
    visual_plan._validate_job_context(job, director, reviewed_visual_text)
    confirmed_content.check_confirmed_content(job, director)
    steps = _steps(treatment)
    _validate_template_choices(job, director, treatment)
    from . import motion_readability
    motion_readability.validate_direction_contract(job, director, treatment)
    from . import avatar_profile, visual_review
    avatar_profile.validate_avatar_plan_policy(director["segments"])
    rows = _rows(director, treatment, motion_capabilities._approved_speech(job.job_dir))
    numbering = _prior_numbering(job)
    numbered_rows = number_visual_rows(rows, numbering)
    numbering = {**numbering, **{row["row_id"]: row["number"] for row in numbered_rows}}
    targets = {(r["segment_id"], r["component_id"]) for r in rows}
    for step in steps:
        if (step.get("segment_id"), step.get("component_id")) not in targets:
            raise VisualConfirmationError("generation step has no visual row")
        for ref in step.get("input_files", []):
            _exact(job.job_dir, ref)
    config_path, config_sha = startup._config(job)
    config = _read(config_path)
    if steps:
        channels = startup.selected_channels(config)
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
                "rows": rows, "numbering": numbering, "generation_steps": steps,
                "visual_review_policy": visual_review.POLICY_VERSION,
                "query_bindings": _record(job.job_dir, job.job_dir / "manifests/generation-channels.json")
                    if (job.job_dir / "manifests/generation-channels.json").is_file() else None}
    proposal_path = root / "proposal.json"
    artifacts.write_json_artifact(proposal_path, proposal)
    def cell(value):
        return str(value).replace("|", "／").replace("\n", "<br>")
    lines = ["# 本视频贴片与 B-roll 完整清单", "",
             "时间为剪后正文时间，不含封面。整表确认后按表制作并直接交付。", "",
             "| 编号 | 时间 | 类型 | 剪后原话 | 语义 | 标签 | 渠道 | 素材来源 | 匹配动效模板 | 生成步骤 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for row in numbered_rows:
        generated = [s for s in steps if (s["segment_id"], s["component_id"]) == (row["segment_id"], row["component_id"])]
        labels = [s["id"] + "：" + ("生图" if s["purpose"] == "image" else "生视频")
                  + ("；" + str(s["description"]) if s.get("description") else "") for s in generated]
        lines.append("| " + " | ".join(cell(v) for v in (
            row["number"], f"{row['start']:.3f}–{row['end']:.3f}s", row["type"], row["spoken_text"],
            row["semantic"], "、".join(row["tags"]), row["channel"], row["source"] or "—",
            row["template"], " → ".join(labels) or "复用/模板渲染")) + " |")
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

def generation_item(queue, proposal, step):
    """Follow only explicitly approved retry successors of the original step."""
    rid = _request_id(proposal, step)
    item = queue["items"].get(rid)
    while item is not None:
        successors = [(key, value) for key, value in queue["items"].items() if value.get("retry_of") == rid]
        if not successors:
            break
        if len(successors) != 1:
            raise VisualConfirmationError("generation retry has ambiguous successors")
        rid, item = successors[0]
    return rid, item

def resolve_generation_request(job, proposal, step):
    from . import generation_channels, generation_queue
    queue = generation_queue.status(job.job_dir)
    inputs = copy.deepcopy(step.get("input_files", []))
    def resolve(value):
        if isinstance(value, dict) and "$step" in value:
            dep = next(s for s in proposal["generation_steps"] if s["id"] == value["$step"])
            if dep["id"] not in step.get("depends_on", []):
                raise VisualConfirmationError("future input must name an approved dependency")
            _, item = generation_item(queue, proposal, dep)
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

def validate_generation_request(job, authorization, request):
    receipt, proposal = _validate_source(job.job_dir, authorization["source"], job_id=job.job_id)
    step_id = authorization["steps"][request["id"]]
    step = next((s for s in proposal["generation_steps"] if s["id"] == step_id), None)
    if step is None or request != resolve_generation_request(job, proposal, step):
        raise VisualConfirmationError("generation request differs from its approved step")
    return {"receipt": receipt, "step": step}

def generation_actions(job, *, account_limit=None):
    from . import generation_channels, generation_queue
    authorized = validate_visual_authorization(job)
    proposal = authorized["source"]
    actions = []
    for step in proposal["generation_steps"]:
        queue = generation_queue.status(job.job_dir)
        rid, item = generation_item(queue, proposal, step)
        if item and item["status"] == "completed":
            continue
        dependencies = [next(s for s in proposal["generation_steps"] if s["id"] == dep)
                        for dep in step.get("depends_on", [])]
        if any((generation_item(queue, proposal, dep)[1] or {}).get("status") != "completed" for dep in dependencies):
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
            or treatment.get("motion_queries", []) != frozen_treatment.get("motion_queries", [])
            or treatment.get("skill_selection", {}).get("assignments", []) != frozen_treatment.get("skill_selection", {}).get("assignments", [])
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
        rid, item = generation_item(queue, proposal, step)
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
            native_inputs.append({"segment_id": key[0], "component_id": key[1], "artifact": ref})
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

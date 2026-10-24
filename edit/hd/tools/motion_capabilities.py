"""Search our reviewed motion descriptions; keep native execution gates separate.

This module reads metadata and existing registrations only. It never prepares an
environment, changes a Job, invokes a renderer, or approves semantic/visual QA.
"""
from __future__ import annotations

import copy
import importlib
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping

from . import contract_artifacts

INDEX = "skill-development/hd-talking-head/references/motion-capability-index.json"
TAG_FIELDS = ("subjects", "actions", "relations", "feelings", "styles", "patterns")
USES = {"aroll_overlay", "broll", "component", "design"}
_OVERLAY_MODULES = {
    "grid-card-assemble": "hyperframes_native_adapter",
    "notification-stack": "hyperframes_native_adapter",
    "toggle-flip": "hyperframes_native_adapter",
    "before-after-wipe": "hyperframes_native_adapter",
    "hw-pipeline": "hyperframes_hw_pipeline_adapter",
    "pin-board": "overlay_studio_adapter",
    "huashu-stat": "huashu_stat_adapter",
}


def _strings(value, label, *, nonempty=False):
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(v, str) or not v.strip() for v in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"Motion capability {label} must be distinct text values")
    return value


def load_profiles(project_root: Path) -> dict[str, dict]:
    project = Path(project_root).resolve(strict=True)
    data = contract_artifacts.read_json_artifact(project / INDEX)
    if data.get("schema_version") != 2 or not isinstance(data.get("profiles"), list):
        raise ValueError("Motion capability index requires schema_version=2 and profiles")
    profiles = {}
    source_hashes = {}
    for profile in data["profiles"]:
        required = {"candidate_id", "uses", "capability_type", "reviewed_version", "title",
                    "summary", "tags", "editable_content", "limitations", "evidence", "reviewed_sources"}
        if not isinstance(profile, dict) or set(profile) != required:
            raise ValueError("Motion capability profile fields are incomplete")
        for name in ("candidate_id", "reviewed_version", "title", "summary"):
            if not isinstance(profile[name], str) or not profile[name].strip():
                raise ValueError(f"Motion capability {name} is required")
        cid = profile["candidate_id"]
        if cid in profiles:
            raise ValueError("Motion capability identity is duplicated")
        if profile["capability_type"] not in {
            "native_template", "native_component", "creative_skill", "design_source", "historical",
        }:
            raise ValueError(f"Motion capability type is invalid: {cid}")
        if set(_strings(profile["uses"], "uses", nonempty=True)) - USES:
            raise ValueError(f"Motion capability use is invalid: {cid}")
        if not isinstance(profile["tags"], dict) or set(profile["tags"]) != set(TAG_FIELDS):
            raise ValueError(f"Motion capability tag dimensions are incomplete: {cid}")
        for name in TAG_FIELDS:
            _strings(profile["tags"][name], name)
        for name in ("editable_content", "limitations", "evidence"):
            _strings(profile[name], name, nonempty=name in {"limitations", "evidence"})
        reviewed = profile["reviewed_sources"]
        if not isinstance(reviewed, dict) or set(reviewed) != set(profile["evidence"]):
            raise ValueError(f"Motion capability reviewed sources are incomplete: {cid}")
        for reference in profile["evidence"]:
            path = (project / reference).resolve(strict=True)
            if Path(reference).is_absolute() or not path.is_relative_to(project) or not path.is_file():
                raise ValueError(f"Motion capability evidence must be a project file: {cid}")
            digest = reviewed[reference]
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or reference == INDEX):
                raise ValueError(f"Motion capability reviewed source identity is invalid: {cid}")
            if reference not in source_hashes:
                source_hashes[reference] = contract_artifacts.sha256_file(path)
            if source_hashes[reference] != digest:
                raise ValueError(f"Motion capability source changed; review {cid}: {reference}")
        profiles[cid] = copy.deepcopy(profile)
    return profiles


def describe_candidates(project_root: Path, candidates: list[dict], *, use: str,
                        profiles: dict[str, dict] | None = None) -> list[dict]:
    """Join evidence-backed descriptions without altering native eligibility."""
    profiles = load_profiles(project_root) if profiles is None else profiles
    result = []
    for candidate in candidates:
        cid = candidate["candidate_id"]
        profile = profiles.get(cid)
        if profile is None:
            raise ValueError(f"Motion capability has not been reviewed: {cid}")
        permitted = use in profile["uses"] or (use == "broll" and candidate["role"] == "design"
                                               and "design" in profile["uses"])
        if (not permitted or profile["capability_type"] == "historical"
                or cid.startswith("unconnected:")):
            raise ValueError(f"Motion capability is not reviewed for {use}: {cid}")
        if profile["reviewed_version"] != candidate["producer_version"]:
            raise ValueError(f"Motion capability version changed; review affected metadata: {cid}")
        result.append({**candidate, "summary": profile["summary"], "capability": profile})
    return result


def overlay_candidates(project_root: Path, *, profiles: dict[str, dict] | None = None) -> list[dict]:
    from .broll_skill_selection import _declarations
    from .overlay_selection import _ROUTE_BY_TEMPLATE

    project = Path(project_root).resolve(strict=True)
    skill = project / "skill-development/hd-talking-head"
    rows = []
    for template, route in _ROUTE_BY_TEMPLATE.items():
        values, _ = _declarations(skill / "scripts" / (_OVERLAY_MODULES[route] + ".py"))
        entry = values["ENTRY"]
        if not (skill / entry).is_file():
            raise ValueError(f"Motion overlay entry is missing: {route}")
        rows.append({"candidate_id": "overlay:" + route,
                     "skill_id": values.get("DEPENDENCY_ID", "hyperframes"),
                     "dependency_id": values.get("DEPENDENCY_ID", "hyperframes"),
                     "entrypoint": entry, "producer_version": values["VERSION"],
                     "template_id": template, "source_route": route,
                     "role": "aroll_overlay", "status": "supported",
                     "adapter_module": _OVERLAY_MODULES[route]})
    return describe_candidates(project, rows, use="aroll_overlay", profiles=profiles)


def validate_overlay_capability(route: str, binding: Mapping, *, registered: Mapping | None = None) -> dict:
    """A metadata review never grants transparent output or timing qualification."""
    project = Path(__file__).resolve().parents[3]
    rows = ({row["source_route"]: row for row in overlay_candidates(project)}
            if registered is None else registered)
    row = rows.get(route)
    if row is None or any(binding.get(k) != row[k] for k in
                          ("dependency_id", "entrypoint", "producer_version", "template_id")):
        raise ValueError(f"Motion overlay binding differs from the registered use: {route}")
    return row["capability"]


def load_catalog(project_root: Path) -> list[dict]:
    from .broll_skill_selection import _discover_native_candidates
    from .talkcraft_matcher import load_card_catalog

    project = Path(project_root).resolve(strict=True)
    profiles = load_profiles(project)
    raw = _discover_native_candidates(project)
    rows = {row["candidate_id"]: row for row in describe_candidates(project, raw, use="broll", profiles=profiles)}
    runtime = project / "edit/hd/integrations/talkcraft/runtime"
    for card in load_card_catalog(runtime / "card-registry.json", index_path=runtime / "card-semantic-index.json"):
        production = card["production"]
        cid = "hd-talking-head-talkcraft:hd-talking-head/talkcraft/" + card["card_id"]
        if cid not in rows:
            item = {"candidate_id": cid, "skill_id": "hd-talking-head-talkcraft",
                    "dependency_id": "hd-talking-head-talkcraft", "entrypoint": production["derived_entrypoint"],
                    "producer_version": production["adapter_version"], "template_id": "hd-talking-head/talkcraft/" + card["card_id"],
                    "source_route": card["card_id"], "role": "component", "status": "needs_adapter"}
            rows[cid] = describe_candidates(project, [item], use="component", profiles=profiles)[0]
        cases_path = runtime / "qualification-cases" / (card["card_id"] + ".json")
        cases = contract_artifacts.read_json_artifact(cases_path)["cases"]
        rows[cid]["native_contract"] = {
            "production_role": card["production_role"], "layer_roles": card["layer_roles"],
            "required_media": card["required_media"], "allowed_media": card["allowed_media"],
            "motion_description": profiles[cid]["summary"],
            "qualified_raw_field_sets": [list(keys) for keys in
                sorted({tuple(sorted(case["raw"])) for case in cases})],
            "qualified_frame_counts": sorted({case["duration_frames"] for case in cases}),
            "qualification_ref": "edit/hd/integrations/talkcraft/runtime/card-registry.json",
            "event_capability_ref": "edit/hd/integrations/talkcraft/runtime/card-event-capabilities.json",
        }
    for row in overlay_candidates(project, profiles=profiles):
        rows[row["candidate_id"]] = row

    # Keep archived identities visible without restoring their old execution route.
    registry = contract_artifacts.read_json_artifact(project / "skill-development/hd-talking-head/references/verified-template-registry.json")
    active_templates = {row["template_id"] for row in raw}
    for record in registry["templates"]:
        if record["template_id"] in active_templates:
            continue
        cid = "history:" + record["template_id"]
        rows[cid] = {"candidate_id": cid, "role": "historical", "status": "excluded",
                     "template_id": record["template_id"], "producer_version": record["template_version"],
                     "capability": {"candidate_id": cid, "title": record["template_id"],
                         "summary": "保留原资格证据供追溯，当前制作政策不恢复此入口。",
                         "uses": ["component"], "capability_type": "historical",
                         "reviewed_version": record["template_version"],
                         "tags": {name: (record.get("semantic_families", []) if name == "relations" else []) for name in TAG_FIELDS},
                         "editable_content": [], "limitations": ["不进入新选型，不重签旧资格。"],
                         "evidence": ["skill-development/hd-talking-head/references/verified-template-registry.json"]}}
    for cid, profile in profiles.items():
        if cid in rows:
            continue
        if cid.startswith(("history:", "unconnected:")):
            rows[cid] = {"candidate_id": cid, "role": "historical" if cid.startswith("history:") else "component",
                         "status": "excluded" if cid.startswith("history:") else "needs_adapter",
                         "capability": profile}
        elif profile["capability_type"] != "historical":
            # A removed qualification is not resurrected by an old metadata row.
            rows[cid] = {"candidate_id": cid, "role": "unavailable", "status": "not_registered",
                         "capability": profile}
    return sorted(rows.values(), key=lambda row: row["candidate_id"])


def catalog_summary(catalog: list[dict]) -> dict:
    return {"total": len(catalog), "execution_status": dict(Counter(row["status"] for row in catalog)),
            "uses": dict(Counter(use for row in catalog for use in row["capability"]["uses"])),
            "note": "登记与标签不证明当前环境、词锚、语义或实播画面通过。"}


def _phrase_in(phrase: str, text: str) -> bool:
    """Whole reviewed phrases, never a shared Chinese character or word fragment."""
    phrase, text = phrase.casefold().strip(), text.casefold()
    if len(phrase) < 2:
        return False
    if re.search(r"[\u3400-\u9fff]", phrase):
        return re.sub(r"\s+", "", phrase) in re.sub(r"\s+", "", text)
    return re.search(r"(?<![a-z0-9_])" + re.escape(phrase) + r"(?![a-z0-9_])", text) is not None


def _match_evidence(profile: Mapping, query: str) -> dict:
    dimensions = {name: [tag for tag in profile["tags"][name] if _phrase_in(tag, query)]
                  for name in TAG_FIELDS}
    # A color, a feeling, or the mere presence of a presenter cannot establish
    # that a native animation performs the requested action or relation.
    primary = dimensions["actions"] + dimensions["relations"]
    return {"matched_dimensions": dimensions, "has_motion_basis": bool(primary),
            "semantic_review_required": True}


def search_capabilities(project_root: Path, query: str, *, use: str | None = None,
                        include_history: bool = False, catalog: list[dict] | None = None) -> list[dict]:
    """Recall candidates, not choose meanings: the host reviews full clauses next."""
    if not isinstance(query, str) or not query.strip() or (use is not None and use not in USES):
        raise ValueError("Motion search requires text and a known use")
    matches = []
    for row in catalog if catalog is not None else load_catalog(project_root):
        profile = row["capability"]
        if row["status"] == "excluded" and not include_history:
            continue
        uses = profile["uses"]
        if use is not None and use not in uses and not (use == "broll" and "design" in uses):
            continue
        evidence = _match_evidence(profile, query)
        if not evidence["has_motion_basis"]:
            continue
        dimensions = evidence["matched_dimensions"]
        score = sum(len(values) * (4 if name in {"actions", "relations"} else 1)
                    for name, values in dimensions.items())
        matches.append({**row, **evidence, "retrieval_score": score,
                        "matched_tags": [tag for values in dimensions.values() for tag in values]})
    return sorted(matches, key=lambda row: (-row["retrieval_score"], row["candidate_id"]))


def _approved_speech(job_dir: Path | None) -> list[dict] | None:
    """Read approval records directly; never load/migrate a stateful Job."""
    if job_dir is None:
        return None
    from .overlay_alignment import _path
    from .subtitles import _map_words, _validate_words

    root = Path(job_dir).resolve(strict=True)
    if not (root / "workflow.json").is_file():
        return None
    workflow = contract_artifacts.read_json_artifact(root / "workflow.json")
    inputs = []
    for stage, relative in (("speech_cleanup", "05-speech-cleanup/word-transcript.json"),
                            ("edit_structure", "06-edit-structure/timeline-map.json")):
        approved = workflow["stages"][stage]
        records = [row for row in approved["artifacts"] if row["path"] == relative]
        if approved["status"] != "approved" or len(records) != 1:
            return None
        path = _path(root, relative)
        if (contract_artifacts.sha256_file(path) != records[0]["sha256"]
                or path.stat().st_size != records[0]["bytes"]):
            raise ValueError(f"Motion check approved speech input changed: {relative}")
        inputs.append(contract_artifacts.read_json_artifact(path))
    return _map_words(_validate_words(inputs[0]), inputs[1])


def _brief_relative(treatment: Mapping, segment: Mapping, component: str) -> str | None:
    records = [row for name in ("overlay_alignment", "scenes") for row in treatment.get(name, [])
               if row.get("segment_id") == segment["segment_id"] and row.get("brief_path")
               and (row.get("component_id") == component or
                    ("component_id" not in row and len(segment["bindings"]) == 1))]
    paths = {row["brief_path"] for row in records}
    if len(paths) > 1:
        raise ValueError("Motion check has conflicting native brief references")
    if not paths:
        return None
    return paths.pop()


def _ai_brief_evidence(job_dir, treatment, segment, component):
    """Locate one explicit, hash-bound completed result; never scan Job folders."""
    from . import state
    from .overlay_alignment import _path
    rows = [row for row in treatment.get("scenes", [])
            if row.get("segment_id") == segment["segment_id"]
            and row.get("component_id", component) == component]
    if len(rows) != 1:
        raise ValueError("AI semantic content requires one explicit scene record")
    ref = rows[0].get("completed_record")
    if type(ref) is not dict or set(ref) != {"job_path", "sha256", "byte_count"}:
        raise ValueError("AI semantic content requires a completed-record descriptor")
    root = Path(job_dir).resolve(strict=True)
    path = _path(root, ref["job_path"])
    if path.stat().st_size != ref["byte_count"] or contract_artifacts.sha256_file(path) != ref["sha256"]:
        raise ValueError("AI completed record changed")
    scripts = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts"
    previous = sys.path[:]
    try:
        sys.path.insert(0, str(scripts))
        record = contract_artifacts.read_json_artifact(path)
        binding = segment["bindings"][component]
        if binding.get("execution_mode") == "reuse_completed_generated_media":
            module = importlib.import_module("generated_media")
            if Path(module.__file__).resolve() != (scripts / "generated_media.py").resolve():
                raise ValueError("AI semantic adapter belongs to another project")
            module.validate_record(record, state.load_job(root))
            expected = module.prepare_binding(record)
            if any(binding.get(k) != v for k, v in expected.items()):
                raise ValueError("generated media binding differs from its real completion record")
            if (record.get("segment_id"), record.get("component_id")) != (segment["segment_id"], component):
                raise ValueError("generated media record belongs to another visual target")
            if not record.get("semantic_brief", {}).get("observed_scene", "").strip():
                raise ValueError("generated media needs an observation of its actual scene")
            source = record.get("source_binding")
            job = state.load_job(root)
            aroll = next(r for r in job.stages["edit_structure"]["artifacts"]
                         if r["path"] == "06-edit-structure/edited-aroll.mp4")
            if source != {"aroll_sha256": aroll["sha256"], "start": segment["start"], "end": segment["end"]}:
                raise ValueError("generated media observation belongs to another speech window")
            brief, brief_ref = record, ref
        else:
            module = importlib.import_module("lovart_existing_video_adapter")
            if Path(module.__file__).resolve() != (scripts / "lovart_existing_video_adapter.py").resolve():
                raise ValueError("AI semantic adapter belongs to another project")
            brief, brief_ref = module.load_semantic_brief(
                state.load_job(root), record, binding,
                segment_id=segment["segment_id"], component_id=component,
                start=segment["start"], end=segment["end"])
    finally:
        sys.path[:] = previous
    if rows[0].get("brief_path") != brief_ref["job_path"]:
        raise ValueError("AI semantic brief differs from the explicit completed record")
    return brief, brief_ref


def _bound_brief(job_dir: Path | None, treatment: Mapping, segment: Mapping,
                 component: str) -> dict | None:
    if job_dir is None:
        return None
    if segment["bindings"][component].get("execution_mode") in {"reuse_completed_lovart_video", "reuse_completed_generated_media"}:
        return _ai_brief_evidence(job_dir, treatment, segment, component)[0]
    from .overlay_alignment import _path

    relative = _brief_relative(treatment, segment, component)
    if relative is None:
        return None
    root = Path(job_dir).resolve(strict=True)
    if not (root / relative).is_file():
        return None
    path = _path(root, relative)
    expected = segment["bindings"][component].get("brief_sha256")
    if expected is None:
        return None
    if contract_artifacts.sha256_file(path) != expected:
        raise ValueError(f"Motion check native brief differs from binding: {segment['segment_id']}")
    brief = contract_artifacts.read_json_artifact(path)
    source = brief.get("source_binding")
    if source is not None and any(source.get(k) != segment[k] for k in ("segment_id", "start", "end")):
        raise ValueError("Motion check native brief belongs to another segment")
    return brief


def _brief_overlay_route(brief: Mapping) -> str | None:
    route = brief.get("upstream_route")
    if isinstance(route, str):
        return route.removeprefix("hyperframes/")
    cards = brief.get("doc", {}).get("cards", [])
    if len(cards) == 1 and cards[0].get("kind") == "pin-board":
        return "pin-board"
    if (isinstance(brief.get("metric"), dict) and "source_binding" in brief
            and brief.get("template_request", {}).get("semantic_family") == "numeric_emphasis"):
        return "huashu-stat"
    if (len(brief.get("labels", [])) == 3 and "label_frames" in brief
            and "word_anchors" in brief and "source_binding" in brief):
        return "hw-pipeline"
    return None


def _check_talkcraft_fields(row: Mapping, brief: Mapping) -> bool:
    """Check actual proposed raw fields against existing qualified call cases."""
    native = row.get("native_contract")
    if native is None:
        return False
    card_id = row["template_id"].rsplit("/", 1)[-1]
    if brief.get("card_id") != card_id:
        raise ValueError("Motion check native card differs from the selected card")
    payloads = [event.get("payload", {}).get("raw") for event in brief.get("events", [])]
    payloads = [raw for raw in payloads if isinstance(raw, dict)]
    if not payloads:
        return False
    combinations = [set(fields) for fields in native["qualified_raw_field_sets"]]
    allowed = set().union(*combinations)
    if any(set(raw) - allowed for raw in payloads):
        raise ValueError(f"Motion check input is outside the qualified native fields: {card_id}")
    return all(bool(raw) and set(raw) in combinations for raw in payloads)


def _native_input_check(project_root: Path, row: Mapping, brief: Mapping | None, *, job_dir: Path | None = None) -> dict:
    """Reuse reviewed input validators only; never prepare or render a scene."""
    if row["role"] == "design":
        return {"status": "not_applicable", "reason": "design source; provider binding and output checks remain separate"}
    if brief is None:
        return {"status": "needs_review", "reason": "hash-bound native brief is missing"}
    method = "native_validator"
    try:
        if "native_contract" in row:
            from .talkcraft_contract import validate_production_brief
            method = "talkcraft_contract.validate_production_brief"
            validate_production_brief(brief)
            if not _check_talkcraft_fields(row, brief):
                return {"status": "needs_review", "method": method,
                        "reason": "raw fields do not match a qualified input combination"}
        else:
            name = row.get("adapter_module")
            if name is None:
                return {"status": "needs_review", "reason": "no registered native input validator"}
            scripts = Path(project_root) / "skill-development/hd-talking-head/scripts"
            previous = sys.path[:]
            try:
                sys.path.insert(0, str(scripts))
                module = importlib.import_module(name)
                if Path(module.__file__).resolve() != (scripts / (name + ".py")).resolve():
                    raise ValueError("native validator module belongs to another project")
                payload = contract_artifacts.canonical_json_bytes(brief)
                method = name + ".validate_brief"
                if hasattr(module, "validate_brief"):
                    module.validate_brief(payload)
                elif hasattr(module, "_wrapper_validator"):
                    method = name + "._wrapper_validator.validate_brief"
                    module._wrapper_validator()(payload)
                elif hasattr(module, "_wrapper"):
                    method = name + "._wrapper.validate_brief"
                    module._wrapper().validate_brief(payload)
                else:
                    # These reviewed adapters expose a JSON-only --validate branch,
                    # which exits before any runtime, browser or rendering work.
                    function = getattr(module, "_checked_brief", None) or getattr(module, "_validate", None)
                    node = shutil.which("node")
                    if function is None or node is None:
                        return {"status": "needs_review", "reason": "native JSON validator or existing Node is unavailable"}
                    method = name + "." + function.__name__ + " (--validate only)"
                    function(Path(node), payload)
                if row.get("dependency_id") == "whiteboard-video":
                    if job_dir is None:
                        return {"status": "needs_review", "reason": "bound Whiteboard assets are unavailable"}
                    from .overlay_alignment import _path
                    root = Path(job_dir).resolve(strict=True)
                    data = {asset["media_ref"]: _path(root, asset["job_path"]).read_bytes()
                            for asset in brief["assets"]}
                    data["provenance"] = _path(root, brief["provenance"]["record_path"]).read_bytes()
                    module._wrapper().validate_assets(brief, data)
            finally:
                sys.path[:] = previous
        return {"status": "pass", "method": method, "scope": "native_input_constraints_only"}
    except (ValueError, TypeError, KeyError) as error:
        return {"status": "fail", "method": method, "reason": str(error)}
    except (ImportError, OSError, subprocess.SubprocessError) as error:
        return {"status": "needs_review", "method": method, "reason": str(error)}


def _json_pointer(value, pointer: str):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("content reference requires a JSON pointer")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("invalid content array index")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def _semantic_assessment(job_dir, treatment, segment, component, row, speech, brief):
    """Validate the host's cited judgement, not infer meaning from tag hits."""
    result = {"status": "needs_review", "judged_by": "host", "binding_verified": False}
    records = treatment.get("semantic_assessments", [])
    if not isinstance(records, list):
        return {**result, "reason": "semantic_assessments must be a list"}
    matches = [record for record in records if isinstance(record, dict)
               and record.get("segment_id") == segment["segment_id"]
               and record.get("component_id") == component]
    if len(matches) != 1:
        return {**result, "reason": "one cited host assessment is required per component"}
    assessment = matches[0]
    try:
        required = {"segment_id", "component_id", "candidate_id", "verdict", "reason",
                    "transcript_refs", "content_refs"}
        if set(assessment) != required or assessment["candidate_id"] != row["candidate_id"]:
            raise ValueError("semantic assessment fields or selected candidate changed")
        if assessment["verdict"] not in {"pass", "fail", "needs_review"}:
            raise ValueError("unknown semantic verdict")
        if not isinstance(assessment["reason"], str) or not assessment["reason"].strip():
            raise ValueError("semantic assessment needs an explanation")
        if not speech or brief is None or job_dir is None:
            raise ValueError("approved speech and bound native content are required")
        current = [index for index, word in enumerate(speech)
                   if word["start"] < segment["end"] and word["end"] > segment["start"]]
        refs = assessment["transcript_refs"]
        if not isinstance(refs, list) or not refs or not current:
            raise ValueError("semantic assessment needs the current spoken clause")
        covered = False
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"start_word", "end_word", "quote", "basis"}:
                raise ValueError("invalid spoken evidence reference")
            start, end = ref["start_word"], ref["end_word"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(speech):
                raise ValueError("spoken evidence index is invalid")
            if ref["quote"] != "".join(word["text"] for word in speech[start:end]):
                raise ValueError("spoken evidence differs from approved words")
            if ref["basis"] == "current_clause":
                if [start, end] != [current[0], current[-1] + 1]:
                    raise ValueError("current clause evidence must retain the complete spoken window")
                covered = True
            elif ref["basis"] != "recap" or speech[end - 1]["end"] > segment["start"]:
                raise ValueError("context must have been spoken before this segment")
        if not covered:
            raise ValueError("current clause evidence is missing")
        relative = _brief_relative(treatment, segment, component)
        if segment["bindings"][component].get("execution_mode") in {"reuse_completed_lovart_video", "reuse_completed_generated_media"}:
            _bound, brief_ref = _ai_brief_evidence(job_dir, treatment, segment, component)
            expected_brief_sha = brief_ref["sha256"]
        else:
            expected_brief_sha = segment["bindings"][component]["brief_sha256"]
        allowed = {relative: expected_brief_sha}
        def collect(value):
            if isinstance(value, dict):
                if {"job_path", "sha256"} <= set(value):
                    allowed[value["job_path"]] = value["sha256"]
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(brief)
        refs = assessment["content_refs"]
        if not isinstance(refs, list) or not refs:
            raise ValueError("actual content evidence is missing")
        from .overlay_alignment import _path
        entry_cited = row["capability"]["capability_type"] != "creative_skill"
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) not in (
                {"path", "sha256", "pointer", "value"}, {"path", "sha256", "quote"},
                {"path", "sha256", "image"},
            ):
                raise ValueError("invalid actual content reference")
            path = ref["path"]
            if path not in allowed or ref["sha256"] != allowed[path]:
                raise ValueError("content reference is not a current bound input")
            file = _path(Path(job_dir).resolve(strict=True), path)
            if contract_artifacts.sha256_file(file) != ref["sha256"]:
                raise ValueError("referenced content changed")
            if "image" in ref:
                from PIL import Image
                if ref["image"] is not True:
                    raise ValueError("image evidence must explicitly cite a bound picture")
                with Image.open(file) as picture:
                    if picture.format not in {"PNG", "JPEG", "WEBP"}:
                        raise ValueError("image evidence must be a supported static picture")
                    picture.verify()
            elif "pointer" in ref:
                value = _json_pointer(contract_artifacts.read_json_artifact(file), ref["pointer"])
                if path == relative and ref["pointer"].split("/")[1] in {
                    "source_binding", "template_request", "creative_handoff", "upstream",
                    "composition", "canvas", "assets", "entry",
                }:
                    raise ValueError("metadata or creative instructions are not actual visible content")
                if value != ref["value"]:
                    raise ValueError("referenced content value changed")
            else:
                if path == relative or not isinstance(ref["quote"], str) or not ref["quote"].strip():
                    raise ValueError("scene evidence requires a frozen source excerpt")
                if ref["quote"] not in file.read_text(encoding="utf-8"):
                    raise ValueError("scene excerpt differs from frozen content")
            if path == brief.get("entry", {}).get("job_path"):
                entry_cited = True
        if not entry_cited:
            raise ValueError("creative Skill requires evidence from its actual frozen scene")
        return {"status": assessment["verdict"], "judged_by": "host", "binding_verified": True,
                "reason": assessment["reason"]}
    except (ValueError, KeyError, TypeError, IndexError, OSError, ImportError) as error:
        return {**result, "reason": str(error)}


def check_offline_plan(project_root: Path, draft: Mapping, treatment: Mapping, *,
                       job_dir: Path | None = None) -> dict:
    """Check real read-only inputs, distinguishing missing evidence from a pass."""
    from . import broll_skill_selection, overlay_selection

    catalog = load_catalog(project_root)
    by_id = {row["candidate_id"]: row for row in catalog}
    motion_queries = treatment.get("motion_queries")
    if not isinstance(motion_queries, list):
        return {"status": "fail", "scope": "offline_orchestration_only",
                "failures": [{"check": "motion_queries", "reason": "complete semantic retrieval table is required"}],
                "checks": [], "not_verified": [], "source_plans_modified": False}
    query_keys = [(q.get("segment_id"), q.get("component_id")) for q in motion_queries if isinstance(q, dict)]
    expected_query_keys = [(s["segment_id"], c["component_id"])
                           for s in draft["segments"] for c in s["visual_strategy"]["components"]]
    if len(query_keys) != len(motion_queries) or len(query_keys) != len(set(query_keys)) or set(query_keys) != set(expected_query_keys):
        return {"status": "fail", "scope": "offline_orchestration_only",
                "failures": [{"check": "motion_queries", "reason": "visual table must cover every visual component exactly once"}],
                "checks": [], "not_verified": [], "source_plans_modified": False}
    invalid_queries = [q for q in motion_queries
                       if not isinstance(q.get("tags"), list) or not q["tags"]
                       or any(not isinstance(tag, str) or not tag.strip() for tag in q["tags"])]
    if invalid_queries:
        return {"status": "fail", "scope": "offline_orchestration_only",
                "failures": [{"check": "motion_queries", "reason": "every visual row needs explicit semantic retrieval tags"}],
                "checks": [], "not_verified": [], "source_plans_modified": False}
    broll = broll_skill_selection.validate_selection(project_root, draft, treatment)
    speech = _approved_speech(job_dir)
    spoken_segments = {
        segment["segment_id"]: "" if speech is None else "".join(str(word["text"]) for word in speech
            if word["start"] < segment["end"] and word["end"] > segment["start"])
        for segment in draft["segments"]
    }
    routes, briefs, overlay_targets = {}, {}, []
    not_verified = []
    for segment in draft["segments"]:
        if segment["visual_strategy"]["composition"]["family"] != "aroll_with_overlay":
            continue
        for component, binding in segment["bindings"].items():
            key = (segment["segment_id"], component)
            route = overlay_selection._route(binding)
            validate_overlay_capability(route, binding)
            overlay_targets.append((segment, component, "overlay:" + route))
            brief = _bound_brief(job_dir, treatment, segment, component)
            if brief is not None:
                briefs[key] = brief
                actual_route = _brief_overlay_route(brief)
                if actual_route is not None:
                    if actual_route != route:
                        raise ValueError("Motion check actual native brief route differs from binding")
                    routes[key] = actual_route
            if key not in routes:
                not_verified.append({"segment_id": key[0], "component_id": component,
                                     "check": "actual_native_overlay_route"})
    if len(routes) == len(overlay_targets):
        overlays = overlay_selection.validate_selection(draft, treatment, routes)
    else:
        overlays = treatment.get("overlay_selection", [])
        not_verified.append({"check": "overlay_selection_contract", "reason": "native route evidence is missing"})
    segments = {segment["segment_id"]: segment for segment in draft["segments"]}
    targets = [(segments[a["segment_id"]], a["component_id"], a["candidate_id"], "broll")
               for a in broll["assignments"]]
    targets.extend((segment, component, cid, "aroll_overlay") for segment, component, cid in overlay_targets)
    checks, failures = [], []
    query_by_key = {(q.get("segment_id"), q.get("component_id")): q for q in motion_queries}
    for segment, component, cid, use in targets:
        key = (segment["segment_id"], component)
        spoken = spoken_segments[segment["segment_id"]]
        row = by_id[cid]
        retrieval = _match_evidence(row["capability"], spoken)
        query = query_by_key.get(key)
        if query is None:
            failures.append({"segment_id": key[0], "component_id": component,
                             "check": "motion_query", "reason": "missing retrieval tags"})
            query_tags, matched_dimensions = [], {}
        else:
            query_tags = query.get("tags")
            if not isinstance(query_tags, list) or not query_tags or any(not isinstance(tag, str) or not tag.strip() for tag in query_tags):
                failures.append({"segment_id": key[0], "component_id": component,
                                 "check": "motion_query", "reason": "retrieval tags are missing or invalid"})
                query_tags, matched_dimensions = [], {}
            else:
                matches = search_capabilities(project_root, " ".join(query_tags), use=use, catalog=catalog)
                matched_dimensions = {item["candidate_id"]: item["matched_dimensions"] for item in matches}
                if cid not in matched_dimensions:
                    failures.append({"segment_id": key[0], "component_id": component,
                                     "check": "motion_retrieval", "reason": "selected template is not matched by declared tags"})
        if not spoken:
            not_verified.append({"segment_id": key[0], "component_id": component,
                                 "check": "approved_spoken_text"})
        brief = briefs.get(key) if use == "aroll_overlay" else _bound_brief(job_dir, treatment, segment, component)
        semantic = _semantic_assessment(job_dir, treatment, segment, component, row, speech, brief)
        native = _native_input_check(project_root, row, brief, job_dir=job_dir)
        for name, result in (("semantic_fit", semantic), ("native_input_constraints", native)):
            item = {"segment_id": key[0], "component_id": component,
                    "check": name, "reason": result.get("reason", "")}
            if result["status"] == "fail":
                failures.append(item)
            elif result["status"] == "needs_review":
                not_verified.append(item)
        checks.append({"segment_id": key[0], "component_id": component, "use": use,
                       "selected": cid, "template_title": row["capability"]["title"],
                       "spoken_text": spoken, "retrieval": retrieval,
                       "query_tags": query_tags, "matched_dimensions": matched_dimensions,
                       "semantic": semantic, "native_input": native})
    selected_targets = {(segment["segment_id"], component) for segment, component, _, _ in targets}
    direct = [(segment, component["component_id"]) for segment in draft["segments"]
              for component in segment["visual_strategy"]["components"]
              if component["kind"] == "ai_generated"
              and (segment["segment_id"], component["component_id"]) not in selected_targets]
    for segment, component in direct:
        key = (segment["segment_id"], component)
        brief = _bound_brief(job_dir, treatment, segment, component)
        row = {"candidate_id": "ai-generated/direct", "capability": {"capability_type": "generated_scene"}}
        semantic = _semantic_assessment(job_dir, treatment, segment, component, row, speech, brief)
        checks.append({"segment_id": key[0], "component_id": component, "use": "broll",
                       "selected": "ai-generated/direct", "query_tags": query_by_key[key].get("tags", []),
                       "semantic": semantic, "native_input": {"status": "pass", "reason": "completed media binding checked"}})
        if semantic["status"] != "pass":
            (failures if semantic["status"] == "fail" else not_verified).append(
                {"segment_id": key[0], "component_id": component, "check": "semantic_fit", "reason": semantic.get("reason", "")})
    declared = treatment.get("semantic_assessments", [])
    expected = selected_targets | {(segment["segment_id"], component) for segment, component in direct}
    if isinstance(declared, list) and any(not isinstance(item, dict) or
            (item.get("segment_id"), item.get("component_id")) not in expected for item in declared):
        failures.append({"check": "semantic_assessment_target", "reason": "assessment has an unknown target"})
    return {"status": "fail" if failures else ("needs_review" if not_verified else "pass"),
            "scope": "offline_orchestration_only", "semantic_authority": "host_judgement_with_bound_sources",
            "catalog": catalog_summary(catalog), "broll_components": len(broll["assignments"]),
            "overlay_components": len(overlays), "checks": checks, "not_verified": not_verified,
            "spoken_segments": spoken_segments,
            "failures": failures,
            "not_run": ["runtime_preflight", "native_timeline_word_alignment",
                        "alpha_and_pixel_qa", "media_generation", "visual_acceptance"],
            "source_plans_modified": False}

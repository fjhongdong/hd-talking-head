"""Coordinate reviewed native Skill choices; never generate media or motion.

The host judges meaning, visual quality and shared visual patterns. Discovery
is not runtime readiness: existing preflight and adapter validators still apply.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from . import contract_artifacts

_ADAPTERS = (
    "hyperframes_native_adapter", "doudou_adapter", "hypit_native_adapter",
    "adu_native_adapter", "wise_motion_adapter", "huashu_motion_adapter",
    "paper_collage_adapter", "paper_hyperframes_adapter", "whiteboard_adapter",
    "talkcraft_native_adapter", "data_rollup_adapter", "hyperframes_notification_adapter",
    "hyperframes_chatgpt_exchange_adapter",
    "openfilm_motion_adapter",
    "upstream_scene_adapter",
    "riso_native_adapter",
    "lemo_wake_adapter",
)
_REGISTRY_DEPENDENT = {
    "huashu_motion_adapter", "data_rollup_adapter",
    "hyperframes_notification_adapter", "hyperframes_chatgpt_exchange_adapter",
}


def talkcraft_candidates(project_root: Path) -> list[dict]:
    """Read original callable recipes and retain their actual native role."""
    source = Path(project_root) / 'skill-development/hd-talking-head/scripts/talkcraft_skill_adapter.py'
    spec = importlib.util.spec_from_file_location('_talkcraft_native_catalog', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [{"candidate_id": module.DEPENDENCY_ID + ':' + card['card_id'],
             "skill_id": module.DEPENDENCY_ID, "dependency_id": module.DEPENDENCY_ID,
             "entrypoint": module.ENTRY, "template_id": module.DEPENDENCY_ID + '/' + card['card_id'],
             "producer_version": module.VERSION, "source_route": card['card_id'],
             "role": "native" if card['native_role'] == 'scene' else "component",
             "native_role": card['native_role'], "status": "supported",
             "adapter_module": "talkcraft_skill_adapter", "capacity": None,
             "semantic_families": [], "limitations": [
                 "Complete original TalkCraft Skill and recipe; opaque scene output only",
                 "Transitions, camera moves and annotations are components, not standalone B-roll or transparent overlays"]}
            for card in module.load_card_catalog(project_root)]


def motion_native_candidates(project_root: Path) -> list[dict]:
    """Whole creative workflows; their shared browser is not a source channel."""
    source = Path(project_root) / 'skill-development/hd-talking-head/scripts/motion_native_skill_adapter.py'
    spec = importlib.util.spec_from_file_location('_motion_native_catalog', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = []
    for dependency in module.SOURCES:
        for template in module.load_template_catalog(project_root, dependency_id=dependency):
            identity = template['candidate_id']
            native_id = identity.split(':', 1)[1]
            # Barty/Bang expose complete creation workflows. The broader
            # recipe catalogs explicitly distinguish scenes from components.
            native_role = ('scene' if dependency in {'barty-motion-graphics', 'bang-motion'}
                           else template['native_role'])
            rows.append({'candidate_id': identity, 'skill_id': dependency, 'dependency_id': dependency,
                'entrypoint': module.ENTRY, 'template_id': native_id, 'producer_version': module.VERSION,
                'source_route': native_id,
                'role': 'native' if native_role in {'scene', 'product_promo'} else 'component',
                'native_role': native_role, 'status': 'supported',
                'adapter_module': 'motion_native_skill_adapter', 'capacity': None,
                'semantic_families': [], 'limitations': [
                    'Invoke the complete pinned native Skill; its workflow owns design and motion',
                    'Review this scene and freeze its actual native result before production']})
            rows[-1].update({field: template[field] for field in
                             ('min_duration_seconds', 'max_duration_seconds') if field in template})
    return rows


def _declarations(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = value
    return values, tree


def _literal_field(tree, name):
    values = []
    for node in ast.walk(tree):
        expressions = []
        if isinstance(node, ast.Dict):
            expressions = [v for k, v in zip(node.keys, node.values)
                           if isinstance(k, ast.Constant) and k.value == name]
        elif isinstance(node, ast.keyword) and node.arg == name:
            expressions = [node.value]
        elif (isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript)
              and isinstance(node.left.slice, ast.Constant) and node.left.slice.value == name):
            expressions = list(node.comparators)
        for expression in expressions:
            try:
                value = ast.literal_eval(expression)
            except (ValueError, TypeError):
                continue
            if value not in values:
                values.append(value)
    return values[0] if len(values) == 1 else None


def _native_frame_floor(tree):
    """Read the two existing chained frame-clock guards without importing runtimes."""
    return _native_frame_bounds(tree)[0]


def _native_frame_bounds(tree, *, minimum=None):
    floors = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare) and len(node.ops) == 2
                and all(isinstance(op, ast.LtE) for op in node.ops)
                and ((isinstance(node.comparators[0], ast.Subscript)
                      and isinstance(node.comparators[0].slice, ast.Constant)
                      and node.comparators[0].slice.value == "frames")
                     or isinstance(node.comparators[0], ast.Name) and node.comparators[0].id == "frames")
                and isinstance(node.comparators[1], ast.Constant)
                and type(node.comparators[1].value) is int):
            if isinstance(node.left, ast.Constant) and type(node.left.value) is int:
                floor = node.left.value / 24
            elif (minimum is not None and isinstance(node.left, ast.BinOp)
                  and isinstance(node.left.op, ast.Mult)
                  and isinstance(node.left.left, ast.Subscript)
                  and isinstance(node.left.left.value, ast.Name)
                  and node.left.left.value.id == "MIN_SECONDS"
                  and isinstance(node.left.right, ast.Constant) and node.left.right.value == 24):
                floor = minimum
            else:
                raise ValueError("Native frame-clock lower bound changed")
            floors.append((floor, node.comparators[1].value / 24))
    if len(floors) != 1:
        raise ValueError("Native frame-clock declaration changed; review its duration limit")
    return floors[0]


def _native_seconds_ceiling(tree):
    limits = [node.comparators[1].value for node in ast.walk(tree)
              if isinstance(node, ast.Compare) and len(node.ops) == 2
              and isinstance(node.ops[0], ast.Lt) and isinstance(node.ops[1], ast.LtE)
              and isinstance(node.left, ast.Constant) and node.left.value == 0
              and isinstance(node.comparators[0], ast.Name) and node.comparators[0].id == "duration"
              and isinstance(node.comparators[1], ast.Constant)
              and type(node.comparators[1].value) in (int, float)]
    if len(limits) != 1:
        raise ValueError("Native duration limit changed; review its clock")
    return limits[0]


def _discover_native_candidates(project_root: Path) -> list[dict]:
    """Read actual bridge routes and qualified cards, not caller favorites."""
    project = Path(project_root).resolve(strict=True)
    skill = project / "skill-development/hd-talking-head"
    registry = contract_artifacts.read_json_artifact(
        skill / "references/verified-template-registry.json")
    templates = {t["template_id"]: t for t in registry["templates"]
                 if t["template_origin"] == "verified_third_party"}
    found = []

    def add(dep, entry, template, version, *, route=None, families=(),
            capacity=None, role="native", limitations=(), status="supported"):
        found.append({"candidate_id": f"{dep}:{route or template}", "skill_id": dep,
                      "dependency_id": dep, "entrypoint": entry,
                      "template_id": template, "producer_version": version,
                      "source_route": route or template, "role": role,
                      "semantic_families": sorted(families), "capacity": capacity,
                      "status": status, "limitations": list(limitations)})

    for module in _ADAPTERS:
        first = len(found)
        values, tree = _declarations(skill / "scripts" / (module + ".py"))
        dep = ("lemo-opuscar" if module == "upstream_scene_adapter" else
               values.get("DEPENDENCY_ID") or _literal_field(tree, "dependency_id"))
        entry, version = values["ENTRY"], values["VERSION"]
        if not isinstance(dep, str) or not (skill / entry).is_file():
            raise ValueError(f"B-roll discovery entry is incomplete: {module}")
        if module == "upstream_scene_adapter":
            styles = project / "skill-development/vendor/lemo-opuscar/styles"
            entries = sorted(p for p in styles.glob("*/style.json") if p.parent.name != "_template")
            if len(entries) != 59:
                raise ValueError("Lemo discovery requires the complete official 59-style catalog")
            for path in entries:
                metadata = contract_artifacts.read_json_artifact(path)
                slug = path.parent.name
                if metadata.get("slug") != slug or not (path.parent / "STYLE.md").is_file():
                    raise ValueError("Lemo style identity or native instructions are missing")
                add(dep, entry, dep + "/" + slug, version, route=dep + "/" + slug,
                    limitations=("Invoke the complete original Lemo Skill and selected STYLE; freeze its topic-specific project before native rendering",
                                 "Opaque B-roll only; verify actual materials, Chinese text and subject action for this content"))
        elif module == "hyperframes_native_adapter":
            routes = values.get("BROLL_ROUTES")
            if not isinstance(routes, (tuple, list)):
                raise ValueError(f"B-roll HyperFrames routes are undeclared: {module}")
            if any(route not in values["ROUTES"] for route in routes):
                raise ValueError(f"B-roll HyperFrames route has no native entry: {module}")
            for route in sorted(routes):
                add(dep, entry, route.replace("/", "-") + "-portrait-adaptation",
                    version, route=route,
                    limitations=("Public native slots only; review duration, Chinese capacity and subject action",))
        elif module == "lemo_wake_adapter":
            add(dep, entry, values["TEMPLATE_ID"], version, route="wake",
                limitations=("Complete native image-to-motion Skill; existing bound image required",
                             "First body shot uses approved cover with hidden presenter; body scenes match semantics"))
        elif module == "openfilm_motion_adapter":
            add(dep, entry, values["TEMPLATE_ID"], version, route="motion-graphics",
                limitations=("Registered native creation template: read its Skill, author the subject-specific scene, and freeze it before rendering; new scenes do not create new template identities",
                             "Opaque B-roll only; inspect real subject action, word anchors, reading time and neighboring visual patterns"))
        elif module == "riso_native_adapter":
            for route, family in sorted(values["FAMILIES"].items()):
                add(dep, entry, dep + "/" + route, version, route=route, families=[family],
                    limitations=("DATA-only native Riso information graphics; not a person/action scene or transparent A-roll overlay",))
                found[-1]["min_duration_seconds"] = values["MIN_SECONDS"][route]
        elif module == "huashu_motion_adapter":
            for name, families in sorted(values["FAMILIES"].items()):
                template = dep + "/" + name
                if module in _REGISTRY_DEPENDENT and template not in templates:
                    continue
                add(dep, entry, template, version, families=families,
                    capacity=templates[template]["capacity"],
                    limitations=("Only the registered grammar; review source media and reading time",))
        elif module == "paper_hyperframes_adapter":
            add(dep, entry, 'paper-collage-ad-hyperframes-portrait-adaptation', version,
                route=values['ROUTE'], limitations=(
                    "Complete Paper Collage Ad Skill, original Route B authoring and HyperFrames export",
                    "Real paper assets and existing source/clock validation are required",))
        elif module == "talkcraft_native_adapter":
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check_runtime")
            original_files = next(ast.literal_eval(n.value) for n in ast.walk(function)
                                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "expected" for t in n.targets))
            for filename in sorted(original_files):
                add(dep, entry, _literal_field(tree, "template_id"), version,
                    route="template/cards/" + filename,
                    limitations=("Use this original native card; only static layout, public props and clock adaptation",))
                if filename == "source-converge.tsx":
                    # Native centering ends at 4.4s and requires a >=1.2s hold.
                    found[-1]["min_duration_seconds"] = 5.6
        else:
            template = values.get("TEMPLATE_ID") or _literal_field(tree, "template_id")
            if not isinstance(template, str):
                raise ValueError(f"B-roll discovery template is incomplete: {module}")
            record = templates.get(template, {})
            # Qualified adapters need an active record, not just source files.
            if module in _REGISTRY_DEPENDENT and not record:
                continue
            families = record.get("semantic_families") or _literal_field(tree, "semantic_families") or ()
            if values.get("FAMILY"):
                families = [values["FAMILY"]]
            add(dep, entry, template, version, families=families,
                capacity=record.get("capacity") or _literal_field(tree, "capacity"),
                limitations=("Use current adapter validation and native components; not a generic scene API",))
            if module == "data_rollup_adapter":
                # render_data_rollup.cjs requires a complete 3-second, 24fps clock.
                found[-1]["min_duration_seconds"] = 3.0
        for row in found[first:]:
            row["adapter_module"] = module
            if module in {"adu_native_adapter", "hypit_native_adapter"}:
                row["min_duration_seconds"] = _native_frame_floor(tree)

    for dep, relative in (
        ("muyang-flat-animation", "muyang-flat-animation/muyang-flat-animation/SKILL.md"),
        ("gbro-collage-broll", "gbro-collage-broll/SKILL.md"),
    ):
        source = project / "skill-development/vendor" / relative
        if not source.is_file():
            raise ValueError(f"B-roll design Skill is unavailable: {dep}")
        add(dep, str(source.relative_to(project)), dep + "/design", "source",
            role="design", limitations=("Design/image source; execute through this Job selected generation channels after complete-list approval",))
    found.extend(row for row in talkcraft_candidates(project) if row['native_role'] == 'scene')
    found.extend(row for row in motion_native_candidates(project) if row['role'] == 'native')
    ids = [row["candidate_id"] for row in found]
    if len(ids) != len(set(ids)):
        raise ValueError("B-roll discovery returned duplicate identities")
    return sorted(found, key=lambda row: row["candidate_id"])


def discover_candidates(project_root: Path) -> list[dict]:
    from .motion_capabilities import describe_candidates

    return describe_candidates(project_root, _discover_native_candidates(project_root), use="broll")

def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"B-roll {label} is required")
    return value


def _duration(row):
    start, end = row.get("start"), row.get("end")
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end):
        raise ValueError("B-roll semantic window is invalid")
    return end - start


_CHANNEL_ALIASES = {"hyperframes-native-adaptation": "hyperframes",
                    "talkcraft-native-adaptation": "video-talkcraft",
                    "paper-collage-hyperframes": "paper-collage-ad"}
_TALKCRAFT_TEMPLATE_ALIASES = {
    alias: card
    for card in ("info-term-card", "number-counter", "numbered-step-stack", "source-converge")
    for alias in ("template/cards/" + card + ".tsx", "video-talkcraft/" + card)
}


def canonical_identity(row: Mapping) -> tuple[str, str | None]:
    """Resolve reviewed source/template aliases without changing execution IDs."""
    skill = row["skill_id"]
    channel = _CHANNEL_ALIASES.get(skill, skill)
    if not row.get("template_id"):
        return channel, None
    template = row.get("source_route") or row["template_id"]
    if channel == "video-talkcraft":
        template = _TALKCRAFT_TEMPLATE_ALIASES.get(template, template)
    return channel, template


def source_channel(skill_id):
    """Count native routes and component adapters under their actual source."""
    return canonical_identity({"skill_id": skill_id})[0]


def _template_identity(row):
    """Count a registered template equally, including native creation styles."""
    identity = canonical_identity(row)
    return identity if identity[1] is not None else None


def approved_creative_identity(job, generation, *, segment_id, component_id):
    """Resolve identity from the existing approved request, never its provider."""
    from . import visual_confirmation as confirmation
    if not isinstance(generation, dict):
        raise ValueError("completed generation evidence must be an object")
    authorization, request = generation.get("approved_plan"), generation.get("approved_request")
    if authorization is None and request is None:
        return None
    if not isinstance(authorization, dict) or not isinstance(request, dict):
        raise ValueError("completed media needs its complete approved request reference")
    if generation.get("approved_request_id") != request.get("id"):
        raise ValueError("completed media approved request identity changed")
    checked = confirmation.validate_generation_request(job, authorization, request)
    for reference in request.get("input_files", []):
        confirmation._exact(job.job_dir, reference)
    step = checked["step"]
    if (step["segment_id"], step["component_id"]) != (segment_id, component_id):
        raise ValueError("completed media belongs to another approved visual item")
    proposal = confirmation._read(confirmation._exact(job.job_dir, checked["receipt"]["source"]))
    treatment = confirmation._read(confirmation._exact(job.job_dir, proposal["inputs"]["treatment"]))
    selection = treatment.get("skill_selection", {})
    assignments = [a for a in [*selection.get("assignments", []), *selection.get("overlay_assignments", [])]
                   if (a["segment_id"], a["component_id"]) == (segment_id, component_id)]
    if len(assignments) > 1:
        raise ValueError("approved creative assignment is duplicated")
    if not assignments:
        # The approved plan explicitly selected a standalone generation flow.
        # This is stronger evidence than a provider name on an output receipt.
        from . import generation_channels
        provider = generation_channels.selected_channel(job, request["purpose"])
        return {"skill_id": source_channel(provider["provider"]), "template_id": None,
                "candidate_id": "ai-generated/direct"}
    assignment = assignments[0]
    for field in ("skill_id", "template_id", "candidate_id"):
        _text(assignment.get(field), "approved " + field)
    # source_route distinguishes registered cards that share a wrapper ID.
    return ({field: assignment[field] for field in ("skill_id", "template_id", "candidate_id")}
            | ({"source_route": assignment["source_route"]} if assignment.get("source_route") else {}))


def fixed_identity(row, *, job_dir=None):
    """Keep proven creation identity; an execution receipt alone is insufficient."""
    reference = row.get("completed_record")
    if reference is None:
        # These are direct material sources, not inferred creation Skills.
        if row.get("skill_id") in {"local_material", "official_material", "external_stock"}:
            return {"skill_id": row["skill_id"], "template_id": None}
        return None
    if job_dir is None:
        raise ValueError("fixed creative provenance requires --job-dir")
    from types import SimpleNamespace
    from . import visual_confirmation as confirmation
    root = Path(job_dir).resolve(strict=True)
    if not isinstance(reference, dict) or set(reference) != {"job_path", "sha256", "byte_count"}:
        raise ValueError("fixed material needs a frozen completed-record descriptor")
    record_path = confirmation._path(root, reference["job_path"])
    if (record_path.stat().st_size != reference["byte_count"]
            or contract_artifacts.sha256_file(record_path) != reference["sha256"]):
        raise ValueError("fixed completed record changed")
    record = confirmation._read(record_path)
    workflow = contract_artifacts.read_json_artifact(root / "workflow.json")
    if record.get("status") != "completed" or record.get("job_id") != workflow["job_id"]:
        raise ValueError("fixed creation record belongs to another Job or is incomplete")
    if (record.get("segment_id"), record.get("component_id")) != (row.get("segment_id"), row.get("component_id")):
        raise ValueError("fixed creation record belongs to another visual item")
    if (not isinstance(record.get("qa"), dict) or record["qa"].get("passed") is not True
            or not isinstance(record.get("semantic_brief"), dict) or not record["semantic_brief"].get("observed_scene")):
        raise ValueError("fixed creation record needs its completed visual QA")
    media = record["media"]
    path = confirmation._path(root, media["job_path"])
    if (contract_artifacts.sha256_file(path) != media["sha256"]
            or path.stat().st_size != media["byte_count"]):
        raise ValueError("fixed creation media changed")
    identity = approved_creative_identity(SimpleNamespace(job_dir=root, job_id=workflow["job_id"]),
        record["generation"], segment_id=record["segment_id"], component_id=record["component_id"])
    if identity and any(row.get(k) != identity[k] for k in ("skill_id", "template_id")):
        raise ValueError("fixed material differs from its approved creative identity")
    return identity


def _revision_selection_locks(selection, beats, job_dir, director, treatment):
    """Keep confirmed choices outside an explicitly requested local revision."""
    revision = selection.get("revision_locks")
    if revision is None:
        return {}
    if (job_dir is None or not isinstance(director, dict) or not isinstance(treatment, dict)
            or not isinstance(revision, dict)
            or set(revision) != {"previous_receipt", "user_confirmation", "changes"}
            or not isinstance(revision["user_confirmation"], str)
            or not revision["user_confirmation"].strip()
            or not isinstance(revision["changes"], list) or not revision["changes"]):
        raise ValueError("local revision needs the previous confirmation and actual user change")
    if treatment.get("skill_selection") != selection:
        raise ValueError("local revision selection differs from the current treatment")
    from . import visual_confirmation as confirmation
    root = Path(job_dir).resolve(strict=True)
    workflow = contract_artifacts.read_json_artifact(root / "workflow.json")
    _, proposal = confirmation._validate_source(root, revision["previous_receipt"],
                                                  job_id=workflow.get("job_id"))
    previous = confirmation._read(confirmation._exact(root, proposal["inputs"]["treatment"]))
    previous_director = confirmation._read(confirmation._exact(root, proposal["inputs"]["director"]))
    # A later local edit starts from the verified published realization.  The
    # proposal may still contain pre-render inputs for earlier accepted repairs.
    stage = workflow.get("stages", {}).get("visual_direction", {})
    realized = []
    for inventory in (stage.get("artifacts", []), stage.get("lineage", [])):
        records = [{k: item[k] for k in ("path", "sha256", "bytes")} for item in inventory]
        for ref in records:
            if not ref["path"].endswith("/" + confirmation.MAPPING):
                continue
            mapping = confirmation._read(confirmation._exact(root, ref))
            if mapping.get("source_approval") != revision["previous_receipt"]:
                continue
            evidence = confirmation.validate_realization_evidence(root,
                {"visual_direction": {"artifacts": records}}, workflow["revision"],
                revision["previous_receipt"], job_id=workflow.get("job_id"))
            if evidence["mapping"] not in realized:
                realized.append(evidence["mapping"])
        if realized:
            break
    if len(realized) > 1:
        raise ValueError("local revision realized baseline is ambiguous")
    if realized:
        inputs = realized[0]["realization_inputs"]
        previous_director = confirmation._read(confirmation._exact(root, inputs["director"]))
        previous = confirmation._read(confirmation._exact(root, inputs["treatment"]))
    # Once this revision is confirmed, its own receipt becomes the latest.
    # It must carry the same actual decision and the frozen revision record.
    approved = []
    for path in (root / "manifests").glob("local-qa-visual_direction-r*.json"):
        payload = confirmation._read(path)
        if (payload.get("source_schema") != confirmation.SCHEMA
                or payload.get("job_id") != workflow.get("job_id")
                or payload.get("passed") is not True or payload.get("reviewed_by") != "human"):
            continue
        checked, source = confirmation._validate_source(root, confirmation._record(root, path),
                                                         job_id=workflow.get("job_id"))
        if type(checked.get("revision")) is not int:
            raise ValueError("confirmed revision has no valid workflow revision")
        approved.append((checked["revision"], confirmation._record(root, path), checked, source))
    if not approved:
        raise ValueError("local revision needs the latest confirmed visual source")
    latest_revision = max(item[0] for item in approved)
    latest = [item for item in approved if item[0] == latest_revision]
    if len(latest) != 1:
        raise ValueError("latest visual confirmation is ambiguous")
    _, latest_ref, latest_receipt, latest_proposal = latest[0]
    compared_director, compared_treatment = director, treatment
    if latest_ref != revision["previous_receipt"]:
        frozen_treatment = confirmation._read(confirmation._exact(root, latest_proposal["inputs"]["treatment"]))
        if (frozen_treatment.get("skill_selection", {}).get("revision_locks") != revision
                or latest_receipt.get("user_confirmation") != revision["user_confirmation"]
                or latest_proposal.get("numbering") != proposal.get("numbering")
                or latest_proposal.get("numbering_scope_id") != proposal.get("numbering_scope_id")):
            raise ValueError("local revision does not reference the latest visual confirmation")
        frozen_director = confirmation._read(confirmation._exact(root, latest_proposal["inputs"]["director"]))
        compared_director, compared_treatment = confirmation._validate_motion_realization(
            root, frozen_director, frozen_treatment, director, treatment)
        compared_director, compared_treatment = confirmation._normalize_lemo_typography(
            root, frozen_director, frozen_treatment, compared_director, compared_treatment)
        compared_director = confirmation._normalize_verified_technical_revisions(
            frozen_director, frozen_treatment, director, treatment, compared_director)
    if (treatment.get("numbering_scope_id") != previous.get("numbering_scope_id")
            or proposal.get("numbering_scope_id") != previous.get("numbering_scope_id")):
        raise ValueError("local revision changed the confirmed numbering scope")
    compared_director, compared_treatment = confirmation._normalize_prepared_paper(
        root, proposal, previous_director, previous, compared_director, compared_treatment)
    old = previous["skill_selection"]
    old_beats = {(b["segment_id"], b["component_id"]): b for b in
                 [*old.get("beats", []), *old.get("overlay_beats", [])]}
    old_choices = {(a["segment_id"], a["component_id"]): a["candidate_id"] for a in
                   [*old.get("assignments", []), *old.get("overlay_assignments", [])]}
    previous_rows = {row["semantic_row_id"] for row in proposal["rows"]}
    changes, changed_rows = {}, set()
    for change in revision["changes"]:
        if (not isinstance(change, dict)
                or set(change) - {"semantic_row_id", "segment_id", "component_id", "candidate_id", "segment_changes"}
                or not {"semantic_row_id", "segment_id", "component_id", "candidate_id"} <= set(change)
                or any(not isinstance(change[k], str) or not change[k].strip()
                       for k in ("semantic_row_id", "segment_id", "component_id", "candidate_id"))
                or change["semantic_row_id"] not in previous_rows):
            raise ValueError("local revision change must identify an existing visual row and candidate")
        key = (change["segment_id"], change["component_id"])
        if key in changes:
            raise ValueError("local revision change is duplicated")
        changes[key] = change
        changed_rows.add(change["semantic_row_id"])
    checked_selection = compared_treatment.get("skill_selection", {})
    checked_beats = [*checked_selection.get("beats", []), *checked_selection.get("overlay_beats", [])]
    current = {(b["segment_id"], b["component_id"]): b for b in checked_beats}
    if len(current) != len(checked_beats) or set(current) != {(b["segment_id"], b["component_id"]) for b in beats}:
        raise ValueError("local revision selection differs from the current treatment")
    if any(key not in current or current[key].get("semantic_row_id") != change["semantic_row_id"]
           for key, change in changes.items()):
        raise ValueError("local revision change is not an actual matching semantic beat")
    if any(b.get("semantic_row_id") not in previous_rows for b in beats):
        raise ValueError("local revision cannot add an unconfirmed semantic row")
    untouched_old = {key for key, beat in old_beats.items()
                     if beat.get("semantic_row_id") not in changed_rows}
    untouched_new = {key for key, beat in current.items()
                     if beat.get("semantic_row_id") not in changed_rows}
    if untouched_old != untouched_new or not untouched_old.issubset(old_choices):
        raise ValueError("local revision changed an unaffected visual selection")
    semantic_fields = ("semantic_row_id", "start", "end", "transcript", "semantic_goal",
                       "required_change", "intent_statement", "component_brief", "candidates", "skill_reviews",
                       "binding_snapshot")
    if any(any(current[key].get(field) != old_beats[key].get(field) for field in semantic_fields)
           for key in untouched_old):
        raise ValueError("local revision changed an unaffected semantic beat or candidate review")
    if any(key not in changes for key, beat in current.items()
           if beat.get("semantic_row_id") in changed_rows):
        raise ValueError("every changed adjustable component needs the user's selected candidate")
    old_items = [(kind, row) for kind in ("broll", "overlay")
                 for row in previous.get("semantic_lists", {}).get(kind, [])]
    new_items = [(kind, row) for kind in ("broll", "overlay")
                 for row in compared_treatment.get("semantic_lists", {}).get(kind, [])]
    old_rows = {row["row_id"]: row for _, row in old_items}
    new_rows = {row["row_id"]: row for _, row in new_items}
    if (len(old_rows) != len(old_items) or len(new_rows) != len(new_items)
            or {row["row_id"]: kind for kind, row in old_items} != {
                row["row_id"]: kind for kind, row in new_items}
            or set(old_rows) != set(new_rows) or set(old_rows) != previous_rows):
        raise ValueError("local revision changed confirmed semantic rows or numbering")
    for row_id, old_row in old_rows.items():
        after = new_rows[row_id]
        if row_id in changed_rows:
            if {k: v for k, v in old_row.items() if k != "components"} != {
                    k: v for k, v in after.items() if k != "components"}:
                raise ValueError("local revision changed the confirmed row meaning")
            if ({item["segment_id"] for item in old_row["components"]} !=
                    {item["segment_id"] for item in after["components"]}):
                raise ValueError("local revision changed the confirmed row's segments")
        elif after != old_row:
            raise ValueError("local revision changed an unaffected semantic row")
    old_segments = {segment["segment_id"]: segment for segment in previous_director["segments"]}
    new_segments = {segment["segment_id"]: segment for segment in compared_director["segments"]}
    changed_segments = {r["segment_id"] for r in proposal["rows"] if r["semantic_row_id"] in changed_rows}
    if set(old_segments) != set(new_segments) or any(old_segments[sid] != new_segments[sid]
            for sid in old_segments if sid not in changed_segments):
        raise ValueError("local revision changed an unaffected component or binding")
    if any(any(old_segments[sid].get(field) != new_segments[sid].get(field)
               for field in ("start", "end", "content_item_ids", "visual_intent"))
           for sid in changed_segments):
        raise ValueError("local revision changed the confirmed time or semantic intent")
    for sid in changed_segments:
        before, after = old_segments[sid], new_segments[sid]
        updates = [c["segment_changes"] for c in changes.values()
                   if c["segment_id"] == sid and "segment_changes" in c]
        allowed = {"bindings", "visual_strategy"}
        if updates:
            update = updates[0]
            if (any(item != update for item in updates) or not isinstance(update, dict)
                    or set(update) != {"visible_text", "strategy_revision"}
                    or not isinstance(update["visible_text"], list)
                    or any(not isinstance(text, str) or not text.strip() for text in update["visible_text"])
                    or type(update["strategy_revision"]) is not int
                    or type(before.get("strategy_revision")) is not int
                    or update["strategy_revision"] != before["strategy_revision"] + 1
                    or any(after.get(k) != value for k, value in update.items())):
                raise ValueError("local revision differs from its explicit text and strategy change")
            allowed.update(update)
        if ({k: v for k, v in before.items() if k not in allowed}
                != {k: v for k, v in after.items() if k not in allowed}):
            raise ValueError("local revision changed an unapproved segment field")
        old_strategy, new_strategy = before["visual_strategy"], after["visual_strategy"]
        if ({k: v for k, v in old_strategy.items() if k not in {"mode", "components", "composition"}}
                != {k: v for k, v in new_strategy.items() if k not in {"mode", "components", "composition"}}):
            raise ValueError("local revision changed an unapproved visual strategy field")
        old_composition, new_composition = old_strategy.get("composition", {}), new_strategy.get("composition", {})
        old_components = {c["component_id"]: c for c in old_strategy["components"]}
        new_components = {c["component_id"]: c for c in new_strategy["components"]}
        added = set(new_components) - set(old_components)
        if (len(old_components) != len(old_strategy["components"])
                or len(new_components) != len(new_strategy["components"])
                or set(old_components) - set(new_components)
                or any((sid, cid) not in changes for cid in added)):
            raise ValueError("local revision changed an unapproved visual component")
        for cid, component in old_components.items():
            if (sid, cid) in changes:
                continue
            old_binding = before.get("bindings", {}).get(cid, {})
            new_binding = after.get("bindings", {}).get(cid, {})
            if (new_components[cid] != component or not isinstance(new_binding, dict)
                    or any(new_binding.get(key) != value for key, value in old_binding.items())):
                raise ValueError("local revision changed an unapproved visual component")
        permitted = {"family", "reading_order", "component_dependencies"}
        if ({k: v for k, v in old_composition.items() if k not in permitted}
                != {k: v for k, v in new_composition.items() if k not in permitted}):
            raise ValueError("local revision changed an unapproved presentation or avatar")
        if not added and old_composition != new_composition:
            raise ValueError("local revision changed an unapproved composition")
    old_component_rows = {(r["segment_id"], r["component_id"]): r["semantic_row_id"] for r in proposal["rows"]}
    for (sid, cid), row_id in old_component_rows.items():
        if row_id in changed_rows:
            continue
        before, after = old_segments[sid], new_segments[sid]
        original = [c for c in before["visual_strategy"]["components"] if c["component_id"] == cid]
        current_component = [c for c in after["visual_strategy"]["components"] if c["component_id"] == cid]
        if (len(original) != 1 or current_component != original
                or before.get("bindings", {}).get(cid) != after.get("bindings", {}).get(cid)):
            raise ValueError("local revision changed an unaffected component or binding")
    old_fixed = {(r["segment_id"], r["component_id"]): r for r in old.get("fixed_context", [])}
    new_fixed = {(r["segment_id"], r["component_id"]): r for r in checked_selection.get("fixed_context", [])}
    if (any(key not in old_component_rows for key in old_fixed)
            or {k: v for k, v in old_fixed.items() if old_component_rows[k] not in changed_rows}
            != {k: v for k, v in new_fixed.items() if k in old_component_rows
                and old_component_rows[k] not in changed_rows}):
        raise ValueError("local revision changed an unaffected fixed material")
    new_component_rows = {(ref["segment_id"], ref["component_id"]): row_id
                          for row_id, row in new_rows.items() for ref in row["components"]}
    if any(key not in new_component_rows or (new_component_rows[key] not in changed_rows and key not in old_fixed)
           for key in new_fixed):
        raise ValueError("local revision added an unaffected fixed material")
    locks = {key: old_choices[key] for key in untouched_old}
    locks.update({key: change["candidate_id"] for key, change in changes.items()})
    return locks


def _verified_supplement_routes(job_dir, director, treatment):
    """Separate execution choices only after the existing realization proof.

    The semantic row and numbering remain shared. Its approved primary choices
    stay locked; a supplement is not another opportunity to reroute the table.
    """
    if not isinstance(treatment, Mapping) or not treatment.get('native_supplements'):
        return set(), {}
    if job_dir is None or not isinstance(director, Mapping):
        raise ValueError('native supplement selection requires its actual approved Job and director')
    from . import state, visual_confirmation as confirmation
    root = Path(job_dir)
    authorized = confirmation.validate_visual_authorization(state.load_job(root))
    proposal = authorized['source']
    frozen = confirmation._read(confirmation._exact(root, proposal['inputs']['director']))
    previous = confirmation._read(confirmation._exact(root, proposal['inputs']['treatment']))
    confirmation._normalize_native_supplements(root, proposal, frozen, previous, director, treatment)
    originals = {s['segment_id']:s for s in frozen['segments']}
    current = {s['segment_id']:s for s in director['segments']}
    keys = set()
    locks = {(a['segment_id'],a['component_id']):a['candidate_id']
             for group in ('assignments','overlay_assignments')
             for a in previous.get('skill_selection', {}).get(group, [])}
    for revision in treatment['native_supplements']:
        sid, base, action = (revision[k] for k in ('segment_id','base_component_id','action_component_id'))
        key = (sid,action)
        before, after = originals[sid], current[sid]
        if (key in keys or any(before.get(k) != after.get(k) for k in
                ('start','end','content_item_ids','visual_intent','strategy_revision'))
                or any(after.get('bindings', {}).get(base, {}).get(k) != value
                       for k,value in before.get('bindings', {}).get(base, {}).items())):
            raise ValueError('native supplement selection changed the approved source, clock or row identity')
        keys.add(key)
        locks[key] = 'barty-motion-graphics:barty-motion-graphics/motion-broll'
    return keys, locks


def _execution_identity(beat, supplements):
    key = (beat['segment_id'],beat['component_id'])
    return (('native_supplement', *key) if key in supplements else
            beat.get('semantic_row_id') or (beat['segment_id'] + ':' + beat['component_id']))


def _assign_skills_once(project_root: Path, selection: Mapping, *, job_dir=None,
                        temporarily_disabled=(), director=None, treatment=None,
                        verified_supplements=None) -> dict:
    """Choose all reviewed visual items jointly: exact channels, then templates."""
    if selection.get("schema_version") != 1 or not isinstance(selection.get("beats"), list):
        raise ValueError("B-roll skill_selection requires schema_version=1 and beats")
    from .motion_capabilities import overlay_candidates
    from .visual_assignment import assign_candidates

    native = discover_candidates(project_root)
    pool = {row["candidate_id"]: row for row in [*native, *overlay_candidates(project_root)]}
    skills = {row["skill_id"] for row in native}
    overlays = selection.get("overlay_beats", [])
    if not isinstance(overlays, list):
        raise ValueError("overlay_beats must be a list")
    beats = sorted([*copy.deepcopy(selection["beats"]), *copy.deepcopy(overlays)],
                   key=lambda row: (row["start"], row["segment_id"], row["component_id"]))
    overlay_keys = {(row["segment_id"], row["component_id"]) for row in overlays}
    keys = [(b["segment_id"], b["component_id"]) for b in beats]
    if len(keys) != len(set(keys)):
        raise ValueError("B-roll semantic component is duplicated")
    revision_locks = _revision_selection_locks(selection, beats, job_dir, director, treatment)
    supplements, source_locks = (verified_supplements if verified_supplements is not None else
                                _verified_supplement_routes(job_dir, director, treatment))
    if any(key in revision_locks and revision_locks[key] != value for key,value in source_locks.items()):
        raise ValueError('native supplement selection conflicts with an approved route lock')
    revision_locks.update(source_locks)
    # The treatment's existing first-beat/opening declaration narrows only the
    # first body item.  It does not remove Wake (or any other reviewed route)
    # from the candidate pool for later semantic items.
    first = selection.get("opening")
    if first is not None:
        if not isinstance(first, dict):
            raise ValueError("opening declaration must be an object")
        for field in ("segment_id", "component_id", "candidate_id"):
            _text(first.get(field), "opening " + field)
        if first["candidate_id"] != "lemo-wake:wake":
            raise ValueError("opening must use the registered lemo-wake/wake candidate")
    if first is not None and (first["segment_id"], first["component_id"]) not in keys:
        raise ValueError("opening declaration has no B-roll semantic beat")
    partial = any(c.get("fit") == "unreviewed" for b in beats for c in b.get("candidates", []))
    domains, optimistic_domains = [], []
    for beat in beats:
        _duration(beat)
        for field in ("transcript", "semantic_goal", "required_change"):
            _text(beat.get(field), field)
        reviews = beat.get("skill_reviews", {})
        is_overlay = (beat["segment_id"], beat["component_id"]) in overlay_keys
        if not is_overlay and set(reviews) != skills:
            raise ValueError("B-roll must review the full discovered Skill pool, not only favorite sources")
        for review in reviews.values():
            if review.get("fit") not in {"preferred", "equivalent", "unsuitable", "needs_adapter", "unreviewed"}:
                raise ValueError("B-roll Skill review status is invalid")
            _text(review.get("reason"), "Skill review reason")
        candidates = beat.get("candidates", [])
        if not isinstance(candidates, list) or len({c.get("candidate_id") for c in candidates}) != len(candidates):
            raise ValueError("B-roll concrete candidate reviews are invalid")
        eligible, optimistic = [], []
        for candidate in candidates:
            cid = candidate.get("candidate_id")
            if cid not in pool:
                raise ValueError(f"B-roll candidate was not discovered: {cid}")
            fit = candidate.get("fit")
            if fit not in {"preferred", "equivalent", "unsuitable", "needs_adapter", "unreviewed"}:
                raise ValueError("B-roll candidate fit is invalid")
            _text(candidate.get("reason"), "candidate reason")
            if fit in {"preferred", "equivalent", "unreviewed"}:
                if (cid.startswith("overlay:")) != is_overlay:
                    raise ValueError("visual candidate does not support the semantic item's use")
                if pool[cid]["status"] != "supported" or (not is_overlay and reviews[pool[cid]["skill_id"]]["fit"] in {"unsuitable", "needs_adapter"}):
                    raise ValueError("B-roll candidate is not callable or contradicts the Skill review")
                if fit != "unreviewed":
                    _text(candidate.get("visual_pattern"), "shared visual pattern")
                    if partial:
                        from .motion_match_cache import _design_plan
                        _design_plan(candidate)
                identity = _execution_identity(beat, supplements)
                if ((identity, cid) not in temporarily_disabled
                        and (not partial or timing_failure(pool[cid], beat, strict=True) is None)):
                    optimistic.append(candidate)
                    if fit != "unreviewed":
                        eligible.append(candidate)
        if first is not None and (beat["segment_id"], beat["component_id"]) == (first["segment_id"], first["component_id"]):
            if beat["start"] != 0:
                raise ValueError("opening must start at 0")
            eligible = [candidate for candidate in eligible
                        if candidate["candidate_id"] == first["candidate_id"]]
            optimistic = [candidate for candidate in optimistic
                          if candidate["candidate_id"] == first["candidate_id"]]
            if not eligible:
                raise ValueError("opening candidate is missing or not suitable")
        locked = revision_locks.get((beat["segment_id"], beat["component_id"]))
        if locked is not None:
            eligible = [candidate for candidate in eligible if candidate["candidate_id"] == locked]
            optimistic = [candidate for candidate in optimistic if candidate["candidate_id"] == locked]
            if not eligible:
                raise ValueError("confirmed revision candidate is not reviewed and feasible")
        domain = eligible
        if not domain:
            frames = round(_duration(beat) * 24)
            raise ValueError(f"{beat['segment_id']}:{beat['component_id']} has no timing-feasible candidate "
                             f"for {frames} frames ({beat['start']:.3f}-{beat['end']:.3f}s)")
        domains.append(sorted(domain, key=lambda c: c["candidate_id"]))
        optimistic_domains.append(sorted(optimistic, key=lambda c: c["candidate_id"]))

    recent = selection.get("recent_context", [])
    if not isinstance(recent, list):
        raise ValueError("B-roll recent context must be a list")
    for row in recent:
        for field in ("source_ref", "video_id", "skill_id", "visual_pattern"):
            _text(row.get(field), "recent " + field)
        _duration(row)
    if len({row["video_id"] for row in recent}) > 2:
        raise ValueError("B-roll recent context is limited to the last two videos")
    _text(selection.get("history_note"), "history availability note")
    fixed = selection.get("fixed_context", [])
    if not isinstance(fixed, list):
        raise ValueError("B-roll fixed material context must be a list")
    for row in fixed:
        for field in ("segment_id", "component_id", "visual_pattern", "source_ref", "skill_id"):
            _text(row.get(field), "fixed context " + field)
        _duration(row)
    fixed_routes = [(row, fixed_identity(row, job_dir=job_dir)) for row in fixed]
    # A logical item may span several physical segments. It still receives one
    # native route, one matching operation and one source/template reward.
    grouped, optimistic_grouped, group_order = {}, {}, []
    for beat, domain, optimistic in zip(beats, domains, optimistic_domains):
        identity = _execution_identity(beat, supplements)
        if identity not in grouped:
            grouped[identity] = domain
            optimistic_grouped[identity] = optimistic
            group_order.append(identity)
        elif grouped[identity] != domain or optimistic_grouped[identity] != optimistic:
            raise ValueError("parts of one semantic visual item must share the same candidate reviews")
    def normalize(groups):
        return [[{**choice, "channel": source_channel(pool[choice["candidate_id"]]["skill_id"]),
                  "template_id": canonical_identity(pool[choice["candidate_id"]])[1]}
                 for choice in groups[identity]] for identity in group_order]
    normalized = normalize(grouped)
    fixed_channels = tuple({source_channel(identity["skill_id"]) for _, identity in fixed_routes if identity})
    fixed_templates = tuple({_template_identity(identity) for _, identity in fixed_routes
                            if identity and _template_identity(identity)})
    exact = assign_candidates(normalized,
        fixed_channels=fixed_channels, fixed_templates=fixed_templates)
    diversity_review = None
    if partial:
        optimistic = assign_candidates(normalize(optimistic_grouped),
            fixed_channels=fixed_channels, fixed_templates=fixed_templates)
        def score(choices):
            return (len(set(fixed_channels) | {c["channel"] for c in choices}),
                    len(set(fixed_templates) | {(c["channel"], c["template_id"]) for c in choices
                                                if c["template_id"] is not None}))
        lower, upper = score(exact), score(optimistic)
        if lower != upper:
            raise ValueError(f"unreviewed candidates may increase the joint maximum: {lower} < {upper}; "
                             "review the relevant candidates before assigning")
        diversity_review = {"reviewed_optimum": list(lower), "optimistic_upper_bound": list(upper),
                            "scope": "joint_broll_and_overlay_current_windows"}
    exact_by_row = {identity: choice["candidate_id"] for identity, choice in zip(group_order, exact)}
    chosen = [next(choice for choice in domain if choice["candidate_id"] == exact_by_row[
        _execution_identity(beat, supplements)])
        for beat, domain in zip(beats, domains)]

    def cost(choices):
        patterns, sources = defaultdict(float), defaultdict(float)
        channels, templates = set(), set()
        adjacency = 0.0
        for row in recent:
            duration = _duration(row)
            patterns[row["visual_pattern"]] += duration
            sources[source_channel(row["skill_id"])] += duration
        sequence = [(row["start"], row["end"], row["visual_pattern"]) for row in fixed]
        for row, identity in fixed_routes:
            duration = _duration(row)
            patterns[row["visual_pattern"]] += duration
            if identity:
                channel = source_channel(identity["skill_id"])
                sources[channel] += duration
                channels.add(channel)
            template = _template_identity(identity) if identity else None
            if template:
                templates.add(template)
        for index, (beat, choice) in enumerate(zip(beats, choices)):
            duration = _duration(beat)
            patterns[choice["visual_pattern"]] += duration
            candidate = pool[choice["candidate_id"]]
            channel = source_channel(candidate["skill_id"])
            sources[channel] += duration
            channels.add(channel)
            template = _template_identity(candidate)
            if template:
                templates.add(template)
            sequence.append((beat["start"], beat["end"], choice["visual_pattern"]))
        sequence.sort()
        for previous, current in zip(sequence, sequence[1:]):
            if current[0] >= previous[1] and current[2] == previous[2]:
                adjacency += min(current[1] - current[0], previous[1] - previous[0])
        return (-len(channels), -len(templates), adjacency,
                sum(v * v for v in patterns.values()),
                sum(v * v for v in sources.values()),
                sum(choice["fit"] != "preferred" for choice in choices))

    # The exact maxima cannot be traded away for timing/adjacency preferences.
    # A multi-part item stays on its jointly selected route during refinement.
    identities = [_execution_identity(b, supplements) for b in beats]
    repeated_items = {identity for identity in identities if identities.count(identity) > 1}
    improved = True
    while improved:
        improved = False
        for index, domain in enumerate(domains):
            if identities[index] in repeated_items:
                continue
            current_cost, best = cost(chosen), chosen[index]
            for candidate in domain:
                trial = [*chosen[:index], candidate, *chosen[index + 1:]]
                candidate_cost = cost(trial)
                if candidate_cost < current_cost:
                    best, current_cost = candidate, candidate_cost
            if best != chosen[index]:
                chosen[index] = best
                improved = True
        if improved:
            continue
        # A joint move can escape a local minimum created by two mutually
        # reinforcing choices. Keep it bounded to the reviewed domains.
        best_pair, best_cost = None, cost(chosen)
        for left in range(len(domains)):
            for right in range(left + 1, len(domains)):
                if any(identities[i] in repeated_items for i in (left, right)):
                    continue
                for first in domains[left]:
                    for second in domains[right]:
                        trial = list(chosen)
                        trial[left], trial[right] = first, second
                        trial_cost = cost(trial)
                        if trial_cost < best_cost:
                            best_pair, best_cost = (left, first, right, second), trial_cost
        if best_pair:
            left, first, right, second = best_pair
            chosen[left], chosen[right] = first, second
            improved = True
    result = copy.deepcopy(dict(selection))
    result.pop("diversity_review", None)
    if diversity_review is not None:
        result["diversity_review"] = diversity_review
    assignments = [
        {"segment_id": beat["segment_id"], "component_id": beat["component_id"],
         "candidate_id": choice["candidate_id"],
         **{key: pool[choice["candidate_id"]][key]
            for key in ("skill_id", "entrypoint", "template_id", "role", "limitations")},
         "visual_pattern": choice["visual_pattern"], "reason": choice["reason"]}
        | ({"design_plan": copy.deepcopy(choice["design_plan"])} if "design_plan" in choice else {})
        | ({"source_route": pool[choice["candidate_id"]]["source_route"]}
           if pool[choice["candidate_id"]].get("source_route") else {})
        for beat, choice in zip(beats, chosen)
    ]
    result["assignments"] = [row for row in assignments if (row["segment_id"], row["component_id"]) not in overlay_keys]
    result["overlay_assignments"] = [row for row in assignments if (row["segment_id"], row["component_id"]) in overlay_keys]
    return result


def _validate_partial_windows(selection, director):
    """A count proof cannot settle draft windows or competing presentations."""
    if not isinstance(director, Mapping) or not isinstance(director.get("segments"), list):
        raise ValueError("unreviewed candidates require the current director and resolved windows")
    segments = {}
    windows = []
    for segment in director["segments"]:
        sid = segment["segment_id"]
        if sid in segments:
            raise ValueError("director contains duplicate segment windows")
        _duration(segment)
        if any(abs(segment[k] * 24 - round(segment[k] * 24)) > 1e-6 for k in ("start", "end")):
            raise ValueError("partial review requires exact 24fps director windows")
        segments[sid] = segment
        windows.append((segment["start"], segment["end"]))
    windows.sort()
    if any(current[0] < previous[1] - 1e-8 for previous, current in zip(windows, windows[1:])):
        raise ValueError("director windows overlap; resolve B-roll and overlay presentation first")
    for group in ("beats", "overlay_beats"):
        for beat in selection.get(group, []):
            segment = segments.get(beat.get("segment_id"))
            if beat.get("window_status") != "resolved" or segment is None:
                raise ValueError("partial review requires every candidate window to be resolved")
            if any(beat[k] != segment[k] for k in ("start", "end")):
                raise ValueError("candidate window differs from the current director")
            strategy = segment["visual_strategy"]
            if (group == "overlay_beats") != (strategy["composition"]["family"] == "aroll_with_overlay"):
                raise ValueError("candidate window type differs from the director presentation")
            if beat["component_id"] not in {c["component_id"] for c in strategy["components"]}:
                raise ValueError("candidate window component is absent from the director")
    for row in selection.get("fixed_context", []):
        segment = segments.get(row.get("segment_id"))
        if segment is None or any(row[k] != segment[k] for k in ("start", "end")):
            raise ValueError("fixed material window differs from the current director")


def assign_skills(project_root: Path, selection: Mapping, *, job_dir=None, director=None, treatment=None) -> dict:
    """Assign reviewed routes, retrying only with draft-local timing exclusions."""
    from .motion_capabilities import overlay_candidates

    beats = [*selection.get("beats", []), *selection.get("overlay_beats", [])]
    verified = _verified_supplement_routes(job_dir, director, treatment)
    supplements, _ = verified
    partial = any(c.get("fit") == "unreviewed" for b in beats for c in b.get("candidates", []))
    if partial:
        _validate_partial_windows(selection, director)
    catalog = {row["candidate_id"]: row for row in
               [*discover_candidates(project_root), *overlay_candidates(project_root)]}
    disabled = set()
    if partial:
        # A route must fit every physical part of its one logical item.
        for beat in beats:
            identity = _execution_identity(beat, supplements)
            for candidate in beat.get("candidates", []):
                cid = candidate.get("candidate_id")
                if cid in catalog and timing_failure(catalog[cid], beat, strict=True):
                    disabled.add((identity, cid))
    while True:
        result = _assign_skills_once(project_root, selection, job_dir=job_dir,
                                     temporarily_disabled=disabled, director=director, treatment=treatment,
                                     verified_supplements=verified)
        failures = []
        for assignment in [*result["assignments"], *result.get("overlay_assignments", [])]:
            row = catalog[assignment["candidate_id"]]
            beat = next(b for b in [*selection["beats"], *selection.get("overlay_beats", [])]
                        if (b["segment_id"], b["component_id"]) ==
                        (assignment["segment_id"], assignment["component_id"]))
            reason = timing_failure(row, beat)
            if reason:
                identity = _execution_identity(beat, supplements)
                failures.append(((identity, row["candidate_id"]), reason))
        if not failures:
            return result
        before = len(disabled)
        disabled.update(key for key, _ in failures)
        if len(disabled) == before:
            raise ValueError("B-roll timing assignment exhausted: " + "; ".join(reason for _, reason in failures))


def timing_failure(row: Mapping, beat: Mapping, *, strict=False) -> str | None:
    """Return the native 24fps duration conflict, if any, without changing state."""
    minimum = row.get("min_duration_seconds")
    maximum = row.get("max_duration_seconds")
    module = row.get("adapter_module")
    scripts = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts"
    if module in {"adu_native_adapter", "hypit_native_adapter", "motion_graphics_adapter",
                  "huashu_motion_adapter", "lemo_wake_adapter", "upstream_scene_adapter",
                  "talkcraft_native_adapter", "doudou_adapter", "riso_native_adapter"}:
        values, tree = _declarations(scripts / (module + ".py"))
        native_minimum = (values["MIN_SECONDS"][row["source_route"]]
                          if module == "riso_native_adapter" else None)
        lower, upper = _native_frame_bounds(tree, minimum=native_minimum)
        minimum = max(minimum or 0, lower)
        maximum = min(maximum, upper) if maximum is not None else upper
    elif module in {"whiteboard_adapter", "paper_collage_adapter"}:
        _, tree = _declarations(scripts / row["entrypoint"].split("/")[-1])
        upper = _native_seconds_ceiling(tree)
        maximum = min(maximum, upper) if maximum is not None else upper
    elif module == "hyperframes_hw_pipeline_adapter":
        source = (scripts / "render_hyperframes_hw_pipeline.cjs").read_text()
        bounds = re.search(r"b\.canvas\.frames\s*>=\s*(\d+)\s*&&\s*b\.canvas\.frames\s*<=\s*(\d+)", source)
        if bounds is None:
            raise ValueError("Native overlay frame-clock declaration changed")
        minimum, maximum = (int(v) / 24 for v in bounds.groups())
    elif module in {"hyperframes_notification_adapter", "hyperframes_chatgpt_exchange_adapter"}:
        source = (scripts / row["entrypoint"].split("/")[-1]).read_text()
        frames = re.findall(r"b\.canvas\.duration_in_frames\s*===\s*(\d+)", source)
        if len(frames) != 1:
            raise ValueError("Native fixed frame-clock declaration changed")
        minimum = maximum = int(frames[0]) / 24
    elif module == "data_rollup_adapter":
        source = (scripts / row["entrypoint"].split("/")[-1]).read_text()
        frames = re.findall(r"c\.duration_in_frames\s*>=\s*(\d+)", source)
        if len(frames) != 1:
            raise ValueError("Native rollup frame-clock declaration changed")
        minimum = max(minimum or 0, int(frames[0]) / 24)
    elif module == "huashu_stat_adapter":
        source = (scripts / "huashu_stat_adapter.py").read_text()
        target = re.findall(r'm\["target_frame"\]\s*<\s*(\d+)', source)
        hold = re.findall(r'm\["hold_frames"\]\s*<\s*(\d+)', source)
        tail = re.findall(r'm\["target_frame"\]\s*\+\s*m\["hold_frames"\]\s*>\s*c\["frames"\]\s*-\s*(\d+)', source)
        if any(len(values) != 1 for values in (target, hold, tail)):
            raise ValueError("Native stat timing declaration changed")
        minimum = max(minimum or 0, sum(int(values[0]) for values in (target, hold, tail)) / 24)
    elif strict and module is None and row.get("role") != "design":
        raise ValueError("Native timing contract is missing its adapter")
    elif strict and module not in {None, "hyperframes_native_adapter", "motion_native_skill_adapter",
                                   "openfilm_motion_adapter", "overlay_studio_adapter",
                                   "paper_hyperframes_adapter", "talkcraft_skill_adapter", "wise_motion_adapter"}:
        raise ValueError("Native timing contract is unknown: " + str(module))
    if minimum is None and maximum is None and not strict:
        return None
    seconds = _duration(beat)
    frames = round(seconds * 24)
    if abs(seconds * 24 - frames) > 1e-6:
        return f"{beat['segment_id']}: {row['candidate_id']} needs an exact 24fps window"
    if minimum is not None and frames < minimum * 24:
        return (f"{beat['segment_id']}: {row['candidate_id']} has {seconds:.3f}s but needs "
                f"at least {minimum}s on an exact 24fps clock")
    if maximum is not None and frames > maximum * 24:
        return f"{beat['segment_id']}: {row['candidate_id']} exceeds its native {maximum}s maximum"
    return None


def validate_fixed_materials(draft: Mapping, selection: Mapping, *, require_bindings=True, job_dir=None) -> None:
    """Only real direct materials may contribute fixed source coverage."""
    adjustable = {(b["segment_id"], b["component_id"])
                  for b in [*selection.get("beats", []), *selection.get("overlay_beats", [])]}
    expected = {}
    for segment in draft["segments"]:
        for component in segment["visual_strategy"]["components"]:
            key = (segment["segment_id"], component["component_id"])
            if component["kind"] != "code_generated" and key not in adjustable:
                expected[key] = (segment, component)
    fixed_rows = selection.get("fixed_context", [])
    fixed = {(row["segment_id"], row["component_id"]): row for row in fixed_rows}
    if len(fixed) != len(fixed_rows) or set(fixed) != set(expected):
        raise ValueError("fixed context must contain every direct material, without adjustable overlays")
    for key, row in fixed.items():
        segment, component = expected[key]
        if component["kind"] not in {"local_material", "official_material", "external_stock", "ai_generated"}:
            raise ValueError("fixed context must reference a direct material kind")
        if any(row[field] != segment[field] for field in ("start", "end")):
            raise ValueError("fixed material window changed")
        identity = fixed_identity(row, job_dir=job_dir)
        if (not row.get("completed_record") and identity
                and identity["skill_id"] != component["kind"]):
            raise ValueError("fixed direct material source differs from its real kind")
        if row.get("template_id") is not None and not identity:
            raise ValueError("fixed material cannot invent a channel or a reusable template")
        binding = segment.get("bindings", {}).get(component["component_id"], {})
        if not binding and not require_bindings:
            continue  # Planning records a proposed source, not verified media identity.
        if row.get("completed_record") is not None:
            from . import visual_confirmation as confirmation
            record = confirmation._read(confirmation._path(Path(job_dir), row["completed_record"]["job_path"]))
            if (binding.get("sha256") != record["media"]["sha256"]
                    or any(binding.get(k) != record.get(k) for k in
                           ("generation_id", "provider", "model", "endpoint_id", "prompt_sha256"))):
                raise ValueError("fixed material binding differs from its completed result")
        dependency = binding.get("dependency_id")
        if not dependency:
            continue
        channel = source_channel(dependency)
        if source_channel(row["skill_id"]) != channel:
            raise ValueError("fixed material cannot invent a channel or a reusable template")


def validate_selection(project_root: Path, draft: Mapping, treatment: Mapping, *, job_dir=None,
                       phase="completed") -> dict:
    if phase not in {"planning", "completed"}:
        raise ValueError("unknown visual selection phase")
    selection = treatment.get("skill_selection")
    if not isinstance(selection, dict):
        raise ValueError("B-roll treatment is missing skill_selection")
    computed = assign_skills(project_root, selection, job_dir=job_dir, director=draft, treatment=treatment)
    if (computed["assignments"] != selection.get("assignments")
            or computed["overlay_assignments"] != selection.get("overlay_assignments", [])):
        raise ValueError("B-roll assignment changed; run assign before building bindings")
    expected, overlay_expected = {}, {}
    for segment in draft["segments"]:
        for component in segment["visual_strategy"]["components"]:
            key = (segment["segment_id"], component["component_id"])
            is_overlay = segment["visual_strategy"]["composition"]["family"] == "aroll_with_overlay"
            if is_overlay and component["kind"] == "code_generated":
                overlay_expected[key] = (segment, component)
                continue
            if (component["kind"] in {"code_generated", "ai_generated"}
                    and (component["kind"] != "ai_generated" or any(
                        (b.get("segment_id"), b.get("component_id")) == (segment["segment_id"], component["component_id"])
                        for b in selection["beats"]))):
                expected[(segment["segment_id"], component["component_id"])] = (segment, component)
    beats = {(b["segment_id"], b["component_id"]): b for b in selection["beats"]}
    if set(beats) != set(expected):
        raise ValueError("B-roll selection must cover every code/AI B-roll component exactly once")
    overlay_beats = {(b["segment_id"], b["component_id"]): b for b in selection.get("overlay_beats", [])}
    if len(overlay_beats) != len(selection.get("overlay_beats", [])) or set(overlay_beats) != set(overlay_expected):
        raise ValueError("joint selection must include every native A-roll overlay as an adjustable item")
    validate_fixed_materials(draft, selection, job_dir=job_dir)
    from .motion_capabilities import overlay_candidates
    pool = {row["candidate_id"]: row for row in [*discover_candidates(project_root), *overlay_candidates(project_root)]}
    from .visual_confirmation import planned_generation_targets
    planned = (planned_generation_targets(project_root, draft, treatment, job_dir=job_dir)
               if phase == "planning" else set())
    all_beats, all_expected = {**beats, **overlay_beats}, {**expected, **overlay_expected}
    for assignment in [*computed["assignments"], *computed["overlay_assignments"]]:
        key = (assignment["segment_id"], assignment["component_id"])
        beat, (segment, component) = all_beats[key], all_expected[key]
        candidate = pool[assignment["candidate_id"]]
        if beat["start"] != segment["start"] or beat["end"] != segment["end"]:
            raise ValueError("B-roll semantic window drifted from the draft")
        if beat.get("intent_statement") != segment["visual_intent"]["statement"] or beat.get("component_brief") != component["brief"]:
            raise ValueError("B-roll semantic intent or component brief changed after selection")
        binding = segment["bindings"].get(component["component_id"])
        if not isinstance(binding, dict) or beat.get("binding_snapshot") != binding:
            raise ValueError("B-roll complete binding drifted from the selected inputs")
        if key in planned:
            continue  # Exact route/config/steps checked; actual inputs remain mandatory at publication.
        if candidate["role"] == "design":
            if (component["kind"] != "ai_generated"
                    or binding.get("execution_mode") not in {"reuse_completed_generated_media", "reuse_completed_lovart_video"}
                    or not binding.get("provider") or not binding.get("generation_id")
                    or (binding.get("execution_mode") == "reuse_completed_generated_media" and not binding.get("sha256"))):
                raise ValueError("B-roll design Skill must bind a completed generated-media result")
            if job_dir is not None:
                from . import motion_capabilities, state
                record, _ = motion_capabilities._ai_brief_evidence(job_dir, treatment, segment, assignment["component_id"])
                identity = approved_creative_identity(state.load_job(Path(job_dir)), record.get("generation", {}),
                    segment_id=segment["segment_id"], component_id=assignment["component_id"])
                if not identity or any(identity[k] != assignment[k] for k in ("skill_id", "template_id", "candidate_id")):
                    raise ValueError("generated media does not belong to the approved creative template")
        elif (component["kind"] != "code_generated"
              or any(binding.get(field) != candidate[field] for field in
                     ("dependency_id", "entrypoint", "template_id", "producer_version"))):
            raise ValueError("B-roll binding does not execute the selected native candidate")
    return {"status": "pass", "planned_inputs": sorted(planned), "assignments": computed["assignments"],
            "overlay_assignments": computed["overlay_assignments"],
            "history_note": selection["history_note"],
            "recent_context": selection.get("recent_context", [])}

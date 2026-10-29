"""Coordinate reviewed native Skill choices; never generate media or motion.

The host judges meaning, visual quality and shared visual patterns. Discovery
is not runtime readiness: existing preflight and adapter validators still apply.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import math
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
            rows.append({'candidate_id': identity, 'skill_id': dependency, 'dependency_id': dependency,
                'entrypoint': module.ENTRY, 'template_id': native_id, 'producer_version': module.VERSION,
                'source_route': native_id, 'role': 'native', 'status': 'supported',
                'adapter_module': 'motion_native_skill_adapter', 'capacity': None,
                'semantic_families': [], 'limitations': [
                    'Invoke the complete pinned native Skill; its workflow owns design and motion',
                    'Review this scene and freeze its actual native result before production']})
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
    floors = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare) and len(node.ops) == 2
                and all(isinstance(op, ast.LtE) for op in node.ops)
                and isinstance(node.left, ast.Constant) and type(node.left.value) is int
                and isinstance(node.comparators[0], ast.Subscript)
                and isinstance(node.comparators[0].slice, ast.Constant)
                and node.comparators[0].slice.value == "frames"
                and isinstance(node.comparators[1], ast.Constant)):
            floors.append(node.left.value / 24)
    if len(floors) != 1:
        raise ValueError("Native frame-clock declaration changed; review its duration limit")
    return floors[0]


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
    found.extend(motion_native_candidates(project))
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


def source_channel(skill_id):
    """Count native routes and component adapters under their actual source."""
    return {"hyperframes-native-adaptation": "hyperframes",
            "talkcraft-native-adaptation": "video-talkcraft",
            "paper-collage-hyperframes": "paper-collage-ad"}.get(skill_id, skill_id)


def _template_identity(row):
    """Count a registered template equally, including native creation styles."""
    template = row.get("template_id")
    if not template:
        return None
    return (source_channel(row["skill_id"]), row.get("source_route") or template)


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


def _assign_skills_once(project_root: Path, selection: Mapping, *, job_dir=None,
                        temporarily_disabled=()) -> dict:
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
    domains = []
    for beat in beats:
        _duration(beat)
        for field in ("transcript", "semantic_goal", "required_change"):
            _text(beat.get(field), field)
        reviews = beat.get("skill_reviews", {})
        is_overlay = (beat["segment_id"], beat["component_id"]) in overlay_keys
        if not is_overlay and set(reviews) != skills:
            raise ValueError("B-roll must review the full discovered Skill pool, not only favorite sources")
        for review in reviews.values():
            if review.get("fit") not in {"preferred", "equivalent", "unsuitable", "needs_adapter"}:
                raise ValueError("B-roll Skill review status is invalid")
            _text(review.get("reason"), "Skill review reason")
        candidates = beat.get("candidates", [])
        if not isinstance(candidates, list) or len({c.get("candidate_id") for c in candidates}) != len(candidates):
            raise ValueError("B-roll concrete candidate reviews are invalid")
        eligible = []
        for candidate in candidates:
            cid = candidate.get("candidate_id")
            if cid not in pool:
                raise ValueError(f"B-roll candidate was not discovered: {cid}")
            fit = candidate.get("fit")
            if fit not in {"preferred", "equivalent", "unsuitable", "needs_adapter"}:
                raise ValueError("B-roll candidate fit is invalid")
            _text(candidate.get("reason"), "candidate reason")
            if fit in {"preferred", "equivalent"}:
                if (cid.startswith("overlay:")) != is_overlay:
                    raise ValueError("visual candidate does not support the semantic item's use")
                if pool[cid]["status"] != "supported" or (not is_overlay and reviews[pool[cid]["skill_id"]]["fit"] in {"unsuitable", "needs_adapter"}):
                    raise ValueError("B-roll candidate is not callable or contradicts the Skill review")
                _text(candidate.get("visual_pattern"), "shared visual pattern")
                identity = beat.get("semantic_row_id") or (beat["segment_id"] + ":" + beat["component_id"])
                if (identity, cid) not in temporarily_disabled:
                    eligible.append(candidate)
        if first is not None and (beat["segment_id"], beat["component_id"]) == (first["segment_id"], first["component_id"]):
            if beat["start"] != 0:
                raise ValueError("opening must start at 0")
            eligible = [candidate for candidate in eligible
                        if candidate["candidate_id"] == first["candidate_id"]]
            if not eligible:
                raise ValueError("opening candidate is missing or not suitable")
        domain = eligible
        if not domain:
            frames = round(_duration(beat) * 24)
            raise ValueError(f"{beat['segment_id']}:{beat['component_id']} has no timing-feasible candidate "
                             f"for {frames} frames ({beat['start']:.3f}-{beat['end']:.3f}s)")
        domains.append(sorted(domain, key=lambda c: c["candidate_id"]))

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
    grouped, group_order = {}, []
    for beat, domain in zip(beats, domains):
        identity = beat.get("semantic_row_id") or (beat["segment_id"] + ":" + beat["component_id"])
        if identity not in grouped:
            grouped[identity] = domain
            group_order.append(identity)
        elif grouped[identity] != domain:
            raise ValueError("parts of one semantic visual item must share the same candidate reviews")
    normalized = []
    for identity in group_order:
        choices = []
        for choice in grouped[identity]:
            candidate = pool[choice["candidate_id"]]
            template = _template_identity(candidate)
            choices.append({**choice, "channel": source_channel(candidate["skill_id"]),
                            "template_id": template[1] if template else None})
        normalized.append(choices)
    exact = assign_candidates(normalized,
        fixed_channels=tuple({source_channel(identity["skill_id"]) for _, identity in fixed_routes if identity}),
        fixed_templates=tuple({_template_identity(identity) for _, identity in fixed_routes
                               if identity and _template_identity(identity)}))
    exact_by_row = {identity: choice["candidate_id"] for identity, choice in zip(group_order, exact)}
    chosen = [next(choice for choice in domain if choice["candidate_id"] == exact_by_row[
        beat.get("semantic_row_id") or (beat["segment_id"] + ":" + beat["component_id"])])
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
    repeated_items = {b.get("semantic_row_id") for b in beats if b.get("semantic_row_id")
                      and sum(other.get("semantic_row_id") == b["semantic_row_id"] for other in beats) > 1}
    improved = True
    while improved:
        improved = False
        for index, domain in enumerate(domains):
            if beats[index].get("semantic_row_id") in repeated_items:
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
                if any(beats[i].get("semantic_row_id") in repeated_items for i in (left, right)):
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


def assign_skills(project_root: Path, selection: Mapping, *, job_dir=None) -> dict:
    """Assign reviewed routes, retrying only with draft-local timing exclusions."""
    from .motion_capabilities import overlay_candidates

    catalog = {row["candidate_id"]: row for row in
               [*discover_candidates(project_root), *overlay_candidates(project_root)]}
    disabled = set()
    while True:
        result = _assign_skills_once(project_root, selection, job_dir=job_dir,
                                     temporarily_disabled=disabled)
        failures = []
        for assignment in [*result["assignments"], *result.get("overlay_assignments", [])]:
            row = catalog[assignment["candidate_id"]]
            beat = next(b for b in [*selection["beats"], *selection.get("overlay_beats", [])]
                        if (b["segment_id"], b["component_id"]) ==
                        (assignment["segment_id"], assignment["component_id"]))
            reason = timing_failure(row, beat)
            if reason:
                identity = beat.get("semantic_row_id") or (beat["segment_id"] + ":" + beat["component_id"])
                failures.append(((identity, row["candidate_id"]), reason))
        if not failures:
            return result
        before = len(disabled)
        disabled.update(key for key, _ in failures)
        if len(disabled) == before:
            raise ValueError("B-roll timing assignment exhausted: " + "; ".join(reason for _, reason in failures))


def timing_failure(row: Mapping, beat: Mapping) -> str | None:
    """Return the native 24fps duration conflict, if any, without changing state."""
    minimum = row.get("min_duration_seconds")
    if minimum is None:
        return None
    seconds = _duration(beat)
    frames = round(seconds * 24)
    if frames < minimum * 24 or abs(seconds * 24 - frames) > 1e-6:
        return (f"{beat['segment_id']}: {row['candidate_id']} has {seconds:.3f}s but needs "
                f"at least {minimum}s on an exact 24fps clock")
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
    computed = assign_skills(project_root, selection, job_dir=job_dir)
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

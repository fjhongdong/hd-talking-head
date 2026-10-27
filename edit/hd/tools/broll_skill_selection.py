"""Coordinate reviewed native Skill choices; never generate media or motion.

The host judges meaning, visual quality and shared visual patterns. Discovery
is not runtime readiness: existing preflight and adapter validators still apply.
"""
from __future__ import annotations

import ast
import copy
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
)
_REGISTRY_DEPENDENT = {
    "huashu_motion_adapter", "data_rollup_adapter",
    "hyperframes_notification_adapter", "hyperframes_chatgpt_exchange_adapter",
}


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
        elif module == "talkcraft_native_adapter":
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check_runtime")
            original_files = next(ast.literal_eval(n.value) for n in ast.walk(function)
                                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "expected" for t in n.targets))
            for filename in sorted(original_files):
                add(dep, entry, _literal_field(tree, "template_id"), version,
                    route="template/cards/" + filename,
                    limitations=("Use this original native card; only static layout, public props and clock adaptation",))
        elif module == "paper_hyperframes_adapter":
            route = values["ROUTE"]
            add(dep, entry, route.replace("/", "-") + "-portrait-adaptation",
                version, route=route, status="needs_adapter",
                limitations=("Renderer/document route is not a reusable native scene; no new GSAP scene in this workflow",))
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
        for row in found[first:]:
            row["adapter_module"] = module
            if module in {"adu_native_adapter", "hypit_native_adapter"}:
                row["min_duration_seconds"] = _native_frame_floor(tree)

    from .talkcraft_matcher import load_card_catalog
    from .talkcraft_contract import DEPENDENCY_ID as talkcraft_dependency
    runtime = project / "edit/hd/integrations/talkcraft/runtime"
    for card in load_card_catalog(runtime / "card-registry.json",
                                  index_path=runtime / "card-semantic-index.json"):
        if "base" not in card["layer_roles"]:
            continue
        production = card["production"]
        add(talkcraft_dependency, production["derived_entrypoint"],
            "hd-talking-head/talkcraft/" + card["card_id"], production["adapter_version"],
            families=card["semantic_families"], capacity={"min_units": 1, "max_units": 8},
            status="needs_adapter",
            limitations=(card["suitable_for"], "Required media: " + ", ".join(card["required_media"]),
                         "Qualification retained; the current package has no TalkCraft production adapter"))
        found[-1]["summary"] = card["summary"]

    for dep, relative in (
        ("muyang-flat-animation", "muyang-flat-animation/muyang-flat-animation/SKILL.md"),
        ("gbro-collage-broll", "gbro-collage-broll/SKILL.md"),
    ):
        source = project / "skill-development/vendor" / relative
        if not source.is_file():
            raise ValueError(f"B-roll design Skill is unavailable: {dep}")
        add(dep, str(source.relative_to(project)), dep + "/design", "source",
            role="design", limitations=("Design/image source; execute through this Job selected generation channels after complete-list approval",))
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
    """Return the real production channel, including the one known alias."""
    return "hyperframes" if skill_id in {"hyperframes", "hyperframes-native-adaptation"} else skill_id


def _template_identity(row):
    """Count a registered template equally, including native creation styles."""
    template = row.get("template_id")
    if not template or row.get("role") == "design":
        return None
    return (source_channel(row["skill_id"]), row.get("source_route") or template)


def assign_skills(project_root: Path, selection: Mapping) -> dict:
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
                eligible.append(candidate)
        domain = eligible
        if not domain:
            raise ValueError("B-roll has no suitable supported candidate; retain A-roll or resolve the declared gap")
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
        fixed_channels=tuple({source_channel(row["skill_id"]) for row in fixed}),
        fixed_templates=tuple({_template_identity(row) for row in fixed if _template_identity(row)}))
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
        for row in fixed:
            duration = _duration(row)
            patterns[row["visual_pattern"]] += duration
            channel = source_channel(row["skill_id"])
            sources[channel] += duration
            channels.add(channel)
            template = _template_identity(row)
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
        for beat, choice in zip(beats, chosen)
    ]
    result["assignments"] = [row for row in assignments if (row["segment_id"], row["component_id"]) not in overlay_keys]
    result["overlay_assignments"] = [row for row in assignments if (row["segment_id"], row["component_id"]) in overlay_keys]
    return result


def validate_fixed_materials(draft: Mapping, selection: Mapping, *, require_bindings=True) -> None:
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
        if row.get("template_id") is not None:
            raise ValueError("fixed material cannot invent a channel or a reusable template")
        binding = segment.get("bindings", {}).get(component["component_id"], {})
        if not binding and not require_bindings:
            continue  # Planning records a proposed source, not verified media identity.
        channel = source_channel(binding.get("dependency_id") or binding.get("provider") or component["kind"])
        if source_channel(row["skill_id"]) != channel:
            raise ValueError("fixed material cannot invent a channel or a reusable template")


def validate_selection(project_root: Path, draft: Mapping, treatment: Mapping) -> dict:
    selection = treatment.get("skill_selection")
    if not isinstance(selection, dict):
        raise ValueError("B-roll treatment is missing skill_selection")
    computed = assign_skills(project_root, selection)
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
    validate_fixed_materials(draft, selection)
    from .motion_capabilities import overlay_candidates
    pool = {row["candidate_id"]: row for row in [*discover_candidates(project_root), *overlay_candidates(project_root)]}
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
        if candidate["role"] == "design":
            if (component["kind"] != "ai_generated"
                    or binding.get("execution_mode") not in {"reuse_completed_generated_media", "reuse_completed_lovart_video"}
                    or not binding.get("provider") or not binding.get("generation_id")
                    or (binding.get("execution_mode") == "reuse_completed_generated_media" and not binding.get("sha256"))):
                raise ValueError("B-roll design Skill must bind a completed generated-media result")
        elif (component["kind"] != "code_generated"
              or any(binding.get(field) != candidate[field] for field in
                     ("dependency_id", "entrypoint", "template_id", "producer_version"))):
            raise ValueError("B-roll binding does not execute the selected native candidate")
    return {"status": "pass", "assignments": computed["assignments"],
            "overlay_assignments": computed["overlay_assignments"],
            "history_note": selection["history_note"],
            "recent_context": selection.get("recent_context", [])}

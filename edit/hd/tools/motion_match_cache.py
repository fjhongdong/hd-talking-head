"""Persistent, identity-bound semantic motion matching cache."""
from __future__ import annotations
import ast, copy, hashlib, json, re
from pathlib import Path
from . import contract_artifacts, motion_capabilities, semantic_visual_plan

# Direct fixed-input routes consume these content slots. Technical settings,
# unrendered intent metadata and authored project files are not content slots.
_FIXED_CONTENT_SLOTS = {
    "adu-motion-video": ("/title", "/stamp", "/left/title", "/left/items/#",
                         "/right/title", "/right/items/#"),
    "datamagic": ("/props/title", "/props/question", "/props/metricLabel", "/props/unit", "/props/source",
                  "/props/takeaway", "/props/rows/#/label", "/props/rows/#/value", "/props/rows/#/caption"),
    "html-video": ("/props/data/title", "/props/data/unit", "/props/data/items/#/label", "/props/data/items/#/value"),
    "huashu-motion-native": ("/metric/value", "/metric/prefix", "/metric/suffix", "/metric/label"),
    "hypit-native-chat": ("/title", "/messages/#/sender", "/messages/#/text"),
    "motion-graphics-native": ("/data/label",),
    "overlay-studio-native": ("/doc/cards/0/params/items",),
    "useanimations": ("/template_id", "/labels/#/text"),
    "wise-motion": ("/title", "/context_labels/#"),
}

_RISO_CONTENT_SLOTS = {
    "compare": ("title", "before/label", "before/value", "before/unit", "after/label", "after/value", "after/unit"),
    "converge": ("from/n", "from/cap", "from/count", "to/n", "to/cap", "to/count", "names/#"),
    "focus": ("title", "items/#", "verdict/n", "verdict/text"),
    "network": ("number", "unit", "say", "nodes"),
    "number": ("number", "unit", "say", "prefix", "suffix"),
    "quote": ("lead", "quote"),
    "shot": ("caption", "source"),
    "steps": ("title/#", "steps/#"),
    "title": ("index", "kicker", "title", "sub"),
    "versus": ("before/tag", "before/text", "after/tag", "after/text"),
}

_HYPERFRAMES_CONTENT_SLOTS = {
    "render_hyperframes_hw_pipeline.cjs": ("/labels/#",),
    "render_hyperframes_notification.cjs": tuple("/props/data/" + key for key in (
        "notifTitle", "messages/#", "appName", "headlineTop", "headlineAccent", "footerText",
    )),
    "render_hyperframes_chatgpt_exchange.cjs": tuple("/props/data/" + key for key in (
        "prompt", "intro1", "intro2", "tableHeadUse", "tableHeadTool", "tableHeadWhy",
        *(f"row{index}{field}" for index in range(1, 5) for field in ("Use", "Tool", "Why", "Chip")),
    )),
}

def _fixed_content_slots(candidate):
    dependency = candidate.get("dependency_id")
    if dependency == "eian-riso-broll":
        template = candidate["template_id"].rsplit("/", 1)[-1]
        return tuple("/data/" + slot for slot in ("mast/#", *_RISO_CONTENT_SLOTS[template]))
    if dependency == "hyperframes":
        return _HYPERFRAMES_CONTENT_SLOTS[Path(candidate["entrypoint"]).name]
    return _FIXED_CONTENT_SLOTS.get(dependency)

def _catalog_projection(rows):
    projected = copy.deepcopy(rows)
    for row in projected:
        del row['capability']['reviewed_sources']
    return projected

def _policy_identity():
    # Bind the actual matching/input/completeness rules, not unrelated rendering
    # or source-review code. AST identity ignores comments and formatting only.
    rules = []
    for path, names in ((Path(motion_capabilities.__file__),
            {'_phrase_in', '_match_evidence', '_recall_evidence', 'search_capabilities'}),
            (Path(__file__), {'_catalog_projection', '_items', '_identity',
                             '_query', 'match_once', 'validate_matches', '_validate_entry'})):
        nodes = {node.name: node for node in ast.parse(path.read_text()).body
                 if isinstance(node, ast.FunctionDef)}
        for name in sorted(names):
            node = nodes[name]
            # Python 3.12 adds empty type_params to ordinary function nodes.
            # Interpreter metadata must not invalidate unchanged matching rules.
            for child in ast.walk(node):
                if getattr(child, 'type_params', None) == []:
                    child._fields = tuple(field for field in child._fields if field != 'type_params')
            rules.append((name, ast.dump(node, include_attributes=False)))
    return contract_artifacts.sha256_json({'version': motion_capabilities.MATCHING_POLICY_VERSION,
        'tag_fields': motion_capabilities.TAG_FIELDS, 'uses': sorted(motion_capabilities.USES), 'rules': rules})

def _catalog(root):
    rows = motion_capabilities.load_catalog(Path(root))  # Always verify real source bytes first.
    return rows, contract_artifacts.sha256_json(_catalog_projection(rows))

def _items(root, director, treatment):
    plan = semantic_visual_plan.validate_semantic_lists(treatment, director)
    queries = treatment.get("motion_queries", [])
    qmap = {(q.get("segment_id"), q.get("component_id")): q for q in queries if isinstance(q, dict)}
    if len(qmap) != len(queries): raise ValueError("motion_queries contain duplicate or invalid keys")
    items = []
    for row in plan["items"]:
        tags = []
        for ref in row["components"]:
            q = qmap.get((ref["segment_id"], ref["component_id"]))
            if not isinstance(q, dict) or not isinstance(q.get("tags"), list) or not q["tags"]:
                raise ValueError("every semantic component needs motion query tags")
            if not all(isinstance(x, str) and x.strip() for x in q["tags"]): raise ValueError("motion tags must be strings")
            if tags and tags != q["tags"]: raise ValueError("components sharing a semantic row need identical tags")
            tags = list(q["tags"])
        items.append((row, row["type"], tags))
    if set(qmap) != set(plan["component_rows"]): raise ValueError("motion_queries must cover every component exactly")
    return items

def _identity(row, typ):
    # Tags and retrieval policy have their own cache fields. They do not change
    # the meaning against which a host reviewed a candidate.
    payload={k:row[k] for k in ("row_id","quote","start_word","end_word","semantic","visual_task")}
    payload["type"]=typ
    if "required_content" in row:
        payload["required_content"] = row["required_content"]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()).hexdigest()

def candidate_review_identity(candidate):
    """Bind one reviewed capability and its verified sources, not its ranking."""
    payload = copy.deepcopy(candidate)
    payload.pop("title", None)
    profile = payload.get("capability", {})
    profile.pop("tags", None)
    profile.pop("title", None)
    # These are search results, never properties of the callable capability.
    for field in ("matched_dimensions", "matched_tags", "has_motion_basis",
                  "semantic_review_required", "recall_basis", "retrieval_score"):
        payload.pop(field, None)
    return contract_artifacts.sha256_json(payload)


def validate_review_identities(director, treatment, catalog):
    """Check current review facts without loading sources, searching or solving."""
    plan = semantic_visual_plan.validate_semantic_lists(treatment, director)
    by_id = catalog if isinstance(catalog, dict) else {r["candidate_id"]: r for r in catalog}
    selection = treatment.get("skill_selection", {})
    for beat in [*selection.get("beats", []), *selection.get("overlay_beats", [])]:
        key = (beat.get("segment_id"), beat.get("component_id"))
        row = plan["component_rows"].get(key)
        if row is None or beat.get("semantic_row_id") != row["row_id"]:
            raise ValueError("review beat semantic row does not match its component")
        if any(beat.get(field) != row[source] for field, source in
               (("transcript", "quote"), ("semantic_goal", "semantic"),
                ("required_change", "visual_task"))):
            raise ValueError("candidate review semantic fields changed")
        entry = treatment.get("motion_matches", {}).get(row["row_id"], {})
        identity = _identity(row, row["type"])
        if entry.get("semantic_sha256") != identity:
            raise ValueError("candidate review semantic cache identity changed")
        for review in beat.get("candidates", []):
            if review.get("fit") == "unreviewed":
                continue
            if beat.get("semantic_sha256") != identity:
                raise ValueError("candidate review semantic identity is missing or changed")
            candidate = by_id.get(review.get("candidate_id"))
            if candidate is None or review.get("capability_sha256") != candidate_review_identity(candidate):
                raise ValueError("candidate review capability identity is missing or changed")
            if review["fit"] in {"preferred", "equivalent"}:
                _validate_expression_basis(review, row, candidate)


def _validate_expression_basis(review, row, candidate):
    """Check one host judgment against the actual registered expression surface."""
    basis = review.get("expression_basis")
    if (not isinstance(basis, dict) or set(basis) not in
            ({"capability", "explanation"}, {"capability", "explanation", "content"})
            or not isinstance(basis["explanation"], str) or not basis["explanation"].strip()):
        raise ValueError("eligible candidate needs a concrete expression_basis")
    profile = candidate["capability"]
    reference = basis["capability"]
    if (not isinstance(reference, str)
            or not (reference == "summary" and profile.get("summary")
                    or re.fullmatch(r"(editable_content|evidence)/[0-9]+", reference)
                    and _capability_ref(profile, reference))):
        raise ValueError("expression_basis must cite this candidate's registered capability")

    slots = _fixed_content_slots(candidate)
    content = basis.get("content")
    if slots is None:
        if content is not None:
            raise ValueError("expression_basis content requires a registered fixed input route")
        return
    requirements = row.get("required_content", {"visual_task": {"meaning": row["visual_task"]}})
    if not isinstance(content, dict) or set(content) != set(requirements):
        raise ValueError("fixed expression_basis must bind every visible requirement")
    bound_slots = {}
    for requirement_id, fields in content.items():
        if not isinstance(fields, dict) or not fields:
            raise ValueError("fixed expression_basis must cite nonempty native content slots")
        shown = []
        for pointer, value in fields.items():
            if not isinstance(pointer, str):
                raise ValueError("fixed expression_basis must cite a native content slot")
            indexed = re.sub(r"/(?:0|[1-9][0-9]*)(?=/|$)", "/#", pointer)
            if ((pointer not in slots and indexed not in slots)
                    or type(value) not in {str, int, float} or not str(value).strip()):
                raise ValueError("fixed expression_basis must cite nonempty native content slots")
            identity = contract_artifacts.canonical_json_bytes(value)
            if bound_slots.setdefault(pointer, identity) != identity:
                raise ValueError(f"fixed expression_basis conflicts on native content slot {pointer}")
            if pointer != "/template_id":  # The icon identity selects an action, not visible text.
                shown.append(str(value))
        if any(not any(term in value for value in shown)
               for term in requirements[requirement_id].get("terms", [])):
            raise ValueError(f"fixed expression_basis omits visible terms for {requirement_id}")


def _capability_ref(profile, reference):
    field, index = reference.split("/")
    values = profile.get(field, [])
    return int(index) < len(values) and values[int(index)]


def selected_expression_bases(treatment):
    """Read the approved fit basis for the selected route of each component."""
    selection = treatment.get("skill_selection", {})
    choices = {(item["segment_id"], item["component_id"]): item["candidate_id"]
               for group in ("assignments", "overlay_assignments") for item in selection.get(group, [])}
    return {key: candidate["expression_basis"]
            for group in ("beats", "overlay_beats") for beat in selection.get(group, [])
            if (key := (beat["segment_id"], beat["component_id"])) in choices
            for candidate in beat["candidates"]
            if candidate["candidate_id"] == choices[key] and "expression_basis" in candidate}


def validate_native_expression(brief, row, basis):
    """Bind approved meaning to a creative brief or to consumed fixed slots."""
    for group, expected in (
        ("task_source", {"semantic_row_id": row["row_id"], "quote": row["quote"],
                         "semantic": row["semantic"], "required_change": row["visual_task"]}),
        ("creative_handoff", {"transcript": row["quote"], "semantic_goal": row["semantic"],
                              "required_change": row["visual_task"]}),
    ):
        if group in brief and any(brief[group].get(field) != value for field, value in expected.items()):
            raise ValueError(f"native {group} differs from the approved semantic row")
    for fields in (basis or {}).get("content", {}).values():
        for pointer, expected in fields.items():
            try:
                actual = motion_capabilities._json_pointer(brief, pointer)
            except (IndexError, KeyError, TypeError, ValueError):
                raise ValueError(f"native brief is missing approved content slot {pointer}") from None
            if contract_artifacts.canonical_json_bytes(actual) != contract_artifacts.canonical_json_bytes(expected):
                raise ValueError(f"native brief changed approved content slot {pointer}")


def _invalidate_changed_reviews(treatment, items, catalog, director):
    """Keep unaffected judgments; matching never signs a new host review."""
    selection = treatment.get("skill_selection")
    if not isinstance(selection, dict):
        return
    by_id = {r["candidate_id"]: r for r in catalog}
    # Assignment reviews every discovered B-roll source, including an unavailable
    # one. Reuse the same complete catalog rather than rediscovering its Skills.
    broll_sources = {r["skill_id"] for r in catalog if r.get("role") in {"native", "design"}
                     and set(r.get("capability", {}).get("uses", [])) & {"broll", "design"}}
    by_component = {(ref["segment_id"], ref["component_id"]): (row, typ)
                    for row, typ, _ in items for ref in row["components"]}
    segments = {s["segment_id"]: s for s in director["segments"]}
    invalidated = set()
    for group in ("beats", "overlay_beats"):
        retained = []
        for beat in selection.get(group, []):
            key = (beat.get("segment_id"), beat.get("component_id"))
            if key not in by_component:
                invalidated.add(key)
                continue
            row, typ = by_component[key]
            identity = _identity(row, typ)
            same_fields = all(
                beat.get(field) == row[source] for field, source in
                (("transcript", "quote"), ("semantic_goal", "semantic"),
                 ("required_change", "visual_task")))
            same_semantic = beat.get("semantic_sha256") == identity and same_fields
            segment = segments[key[0]]
            changed_window = any(field in beat and beat[field] != segment.get(field)
                                 for field in ("start", "end"))
            if changed_window:
                invalidated.add(key)
            expected = {m["candidate_id"] for m in treatment["motion_matches"][row["row_id"]]["matches"]}
            existing = beat.get("candidates", [])
            if not isinstance(existing, list) or any(not isinstance(r, dict) for r in existing):
                raise ValueError("review beat candidates are invalid")
            reviews = {r.get("candidate_id"): r for r in existing}
            if len(reviews) != len(existing):
                raise ValueError("review candidates contain duplicate identities")
            refreshed = []
            changed_sources = set()
            ordered = [cid for cid in reviews if cid in expected] + sorted(expected - set(reviews))
            for cid in ordered:
                old = reviews.get(cid)
                current = by_id[cid]
                stale_timing = old is not None and changed_window and old.get("rejection_basis") == "timing"
                if old is not None and not stale_timing and (old.get("fit") == "unreviewed" or
                        (same_semantic and old.get("capability_sha256") == candidate_review_identity(current))):
                    refreshed.append(old)
                    continue
                refreshed.append({"candidate_id": cid, "fit": "unreviewed",
                                  "reason": "Current semantic task or capability needs review."})
                changed_sources.add(current.get("skill_id"))
                invalidated.add(key)
            if set(reviews) != expected:
                invalidated.add(key)
            if not same_semantic and (not same_fields or beat.get("semantic_sha256") is not None
                    or any(r.get("fit") != "unreviewed" for r in reviews.values())):
                # Unknown entries may carry an old proposed design too.
                refreshed = [{"candidate_id": r["candidate_id"], "fit": "unreviewed",
                              "reason": "Current semantic task needs review."} for r in refreshed]
                if (any(r.get("fit") != "unreviewed" for r in reviews.values())
                        or any(beat.get(field) != row[source] for field, source in
                               (("transcript", "quote"), ("semantic_goal", "semantic"),
                                ("required_change", "visual_task")))):
                    invalidated.add(key)
                beat.pop("semantic_sha256", None)
                changed_sources.update(beat.get("skill_reviews", {}))
            beat.update(semantic_row_id=row["row_id"], transcript=row["quote"],
                        semantic_goal=row["semantic"], required_change=row["visual_task"],
                        candidates=refreshed)
            for field in ("start", "end"):
                if field in beat and field in segment:
                    beat[field] = segment[field]
            if group == "beats" and "skill_reviews" in beat:
                source_reviews = beat["skill_reviews"]
                if not isinstance(source_reviews, dict):
                    raise ValueError("B-roll source reviews are invalid")
                if set(source_reviews) != broll_sources:
                    changed_sources.update(set(source_reviews) ^ broll_sources)
                    invalidated.add(key)
                beat["skill_reviews"] = {source: source_reviews.get(source, {
                    "fit": "unreviewed", "reason": "New B-roll source needs review."})
                    for source in sorted(broll_sources)}
            for source in changed_sources:
                if source in beat.get("skill_reviews", {}):
                    beat["skill_reviews"][source] = {"fit": "unreviewed",
                        "reason": "Current semantic task or source capability needs review."}
            if changed_sources or not same_semantic or set(reviews) != expected:
                beat.pop("single_source_review", None)
            retained.append(beat)
        if group in selection:
            selection[group] = retained
    if invalidated:
        for group in ("assignments", "overlay_assignments"):
            if group in selection:
                selection[group] = [a for a in selection[group]
                    if (a.get("segment_id"), a.get("component_id")) not in invalidated]
        selection.pop("diversity_review", None)
        selection.pop("_optimistic_assignments", None)

def _query(row, tags):
    """Retain the whole task; lexical evidence only orders its review pool."""
    return "\n".join([row[key] for key in ("quote", "semantic", "visual_task")]
                     + [item["meaning"] for _, item in sorted(row.get("required_content", {}).items())]
                     + [" ".join(tags)])

def rebind_local_visual_tasks(project_root, director, treatment, *, job_dir):
    """Rebind requested meaning to the current approved cache without searching.

    Return a new treatment and the row IDs whose semantic digest changed. The
    caller saves only its new draft and records the actual local instruction.
    """
    from . import visual_confirmation as confirmation
    revision = treatment.get("skill_selection", {}).get("revision_locks")
    if (not isinstance(revision, dict)
            or set(revision) != {"previous_receipt", "user_confirmation", "changes"}
            or not isinstance(revision["user_confirmation"], str)
            or not revision["user_confirmation"].strip()
            or not isinstance(revision["changes"], list) or not revision["changes"]):
        raise ValueError("visual task rebinding needs an explicit local revision instruction")
    root = Path(job_dir).resolve(strict=True)
    workflow = contract_artifacts.read_json_artifact(root / "workflow.json")
    stage = workflow.get("stages", {}).get("visual_direction", {})
    if stage.get("status") != "needs_revision":
        raise ValueError("visual task rebinding requires the current visual revision")
    receipt, proposal = confirmation._validate_source(
        root, revision["previous_receipt"], job_id=workflow.get("job_id"))
    # Follow the registered current realization, including its actual rebound
    # cache. Do not scan receipts or fall back to an older proposal's inputs.
    mappings = []
    for inventory in (stage.get("artifacts", []), stage.get("lineage", [])):
        mappings = [item for item in inventory if item["path"].endswith("/" + confirmation.MAPPING)]
        if mappings:
            break
    if len(mappings) != 1:
        raise ValueError("visual task rebinding needs one registered current realization")
    descriptor = {key: mappings[0][key] for key in ("path", "sha256", "bytes")}
    mapping = confirmation._read(confirmation._exact(root, descriptor))
    if (mapping.get("source_approval") != revision["previous_receipt"]
            or mapping.get("proposal") != receipt["source"]
            or proposal.get("job_id") != workflow.get("job_id")):
        raise ValueError("visual task rebinding differs from the current approved source")
    baseline = mapping["realization_inputs"]
    previous_director = confirmation._read(confirmation._exact(root, baseline["director"]))
    previous = confirmation._read(confirmation._exact(root, baseline["treatment"]))
    old_items = {row["row_id"]: (row, typ, tags)
                 for row, typ, tags in _items(project_root, previous_director, previous)}
    current = {row["row_id"]: (row, typ, tags)
               for row, typ, tags in _items(project_root, director, treatment)}
    old_cache, supplied = previous.get("motion_matches"), treatment.get("motion_matches")
    if (not isinstance(old_cache, dict) or set(old_cache) != set(old_items)
            or not isinstance(supplied, dict) or not set(old_items) <= set(current)
            or not set(old_items) <= set(supplied) or not set(supplied) <= set(current)
            or any(supplied[key] != old_cache[key] for key in old_items)):
        raise ValueError("visual task rebinding requires the exact trusted source cache")
    changes = set()
    for change in revision["changes"]:
        if (not isinstance(change, dict) or any(not isinstance(change.get(key), str)
                or not change[key].strip() for key in
                ("semantic_row_id", "segment_id", "component_id", "candidate_id"))):
            raise ValueError("visual task rebinding needs explicit component changes")
        key = (change["semantic_row_id"], change["segment_id"], change["component_id"])
        if key in changes:
            raise ValueError("visual task rebinding change is duplicated")
        changes.add(key)
    old_segments = {s["segment_id"]: s for s in previous_director["segments"]}
    segments = {s["segment_id"]: s for s in director["segments"]}
    catalog, catalog_sha = _catalog(project_root)
    by_id = {row["candidate_id"]: row for row in catalog}
    policy = _policy_identity()
    out, rebound = copy.deepcopy(treatment), []
    if treatment.get("source_clock") != previous.get("source_clock"):
        raise ValueError("visual task rebinding cannot change the approved word clock")
    editable = {"semantic", "visual_task", "required_content"}
    for row_id, (before, typ, tags) in old_items.items():
        after, current_type, current_tags = current[row_id]
        if (typ != current_type or tags != current_tags
                or {k: v for k, v in before.items() if k not in editable}
                    != {k: v for k, v in after.items() if k not in editable}):
            raise ValueError("visual task rebinding cannot change original words, clock, components or tags")
        for ref in before["components"]:
            old, new = old_segments[ref["segment_id"]], segments[ref["segment_id"]]
            if any(old.get(key) != new.get(key) for key in ("start", "end", "content_item_ids")):
                raise ValueError("visual task rebinding cannot change the approved word clock or content")
        entry = old_cache[row_id]
        use = "aroll_overlay" if typ == "贴片" else "broll"
        if (entry.get("semantic_sha256") != _identity(before, typ)
                or entry.get("catalog_sha256") != catalog_sha or entry.get("use") != use
                or entry.get("tags") != tags or entry.get("matching_policy_sha256") != policy):
            raise ValueError("visual task rebinding source cache identity changed")
        _validate_entry(entry, catalog, use, _query(before, tags))
        if any(before.get(field) != after.get(field) for field in editable):
            if any((row_id, ref["segment_id"], ref["component_id"]) not in changes
                   for ref in before["components"]):
                raise ValueError("visual task rebinding changed an unrequested row")
            out["motion_matches"][row_id]["semantic_sha256"] = _identity(after, typ)
            # This explicit presentation revision keeps the same complete
            # use-qualified pool; refresh its lexical hints without searching.
            query = _query(after, tags)
            matches = []
            for match in entry["matches"]:
                evidence = motion_capabilities._recall_evidence(
                    by_id[match["candidate_id"]]["capability"], query)
                dimensions = evidence["matched_dimensions"]
                matches.append({"candidate_id": match["candidate_id"],
                    "matched_dimensions": dimensions, "recall_basis": evidence["recall_basis"],
                    "retrieval_score": sum(len(values) * (4 if name in {"actions", "relations"} else 1)
                                           for name, values in dimensions.items())})
            matches.sort(key=lambda match: (-match["retrieval_score"], match["candidate_id"]))
            out["motion_matches"][row_id]["matches"] = matches
            out["motion_matches"][row_id]["matches_sha256"] = contract_artifacts.sha256_json(matches)
            rebound.append(row_id)
    _invalidate_changed_reviews(out, list(current.values()), catalog, director)
    return out, sorted(rebound)

def match_once(project_root, director, treatment):
    out=copy.deepcopy(treatment); rows,csha=_catalog(project_root); items=_items(project_root,director,out)
    policy = _policy_identity()
    cache=out.get("motion_matches",{}); new={}
    for row,typ,tags in items:
        rid=row["row_id"]; use="aroll_overlay" if typ=="贴片" else "broll"
        sid=_identity(row,typ)
        old=cache.get(rid)
        if rid in cache and (not isinstance(old, dict)
                or not isinstance(old.get('matching_policy_sha256'), str)
                or re.fullmatch('[0-9a-f]{64}', old['matching_policy_sha256']) is None):
            raise ValueError('missing or malformed motion cache policy requires explicit reviewed-source rebinding evidence')
        if isinstance(old,dict) and old.get("matching_policy_sha256")==policy and old.get("matching_policy_version")==motion_capabilities.MATCHING_POLICY_VERSION and old.get("catalog_sha256")==csha and old.get("semantic_sha256")==sid and old.get("use")==use and old.get("tags")==tags:
            _validate_entry(old, rows, use, _query(row, tags))
            new[rid]=old; continue
        matches=motion_capabilities.search_capabilities(Path(project_root), _query(row, tags), use=use, catalog=rows)
        frozen = [{k:m.get(k) for k in ("candidate_id","matched_dimensions","retrieval_score","recall_basis")} for m in matches]
        new[rid]={"catalog_sha256":csha,"semantic_sha256":sid,"use":use,"tags":tags,
                  "matching_policy_version":motion_capabilities.MATCHING_POLICY_VERSION,"matching_policy_sha256":policy,
                  "matches":frozen,"matches_sha256":contract_artifacts.sha256_json(frozen)}
    out["motion_matches"]=new
    _invalidate_changed_reviews(out, items, rows, director)
    return out

def validate_matches(project_root,director,treatment):
    rows,csha=_catalog(project_root); catalog={r.get("candidate_id"):r for r in rows}; items=_items(project_root,director,treatment); cache=treatment.get("motion_matches")
    if not isinstance(cache,dict): raise ValueError("motion_matches cache is required")
    if set(cache)!={r["row_id"] for r,_,_ in items}: raise ValueError("motion_matches keys do not match semantic rows")
    out={}; policy=_policy_identity()
    for row,typ,tags in items:
        rid=row["row_id"]; e=cache[rid]; use="aroll_overlay" if typ=="贴片" else "broll"
        if e.get("matching_policy_sha256")!=policy or e.get("matching_policy_version")!=motion_capabilities.MATCHING_POLICY_VERSION or e.get("catalog_sha256")!=csha or e.get("semantic_sha256")!=_identity(row,typ) or e.get("use")!=use or e.get("tags")!=tags: raise ValueError("motion match cache identity changed")
        _validate_entry(e, rows, use, _query(row, tags))
        raw=[]
        for m in e.get("matches",[]):
            cid=m.get("candidate_id")
            if cid not in catalog: raise ValueError("cached candidate is absent from catalog")
            current=catalog[cid]
            if current.get("candidate_id")!=cid: raise ValueError("catalog identity mismatch")
            raw.append({"candidate":current,"evidence":m})
        for ref in row["components"]: out[(ref["segment_id"],ref["component_id"])]= {"row_id":rid,"semantic":row,"matches":raw}
    return out

def _validate_review_structure(project_root, director, treatment, *, job_dir=None):
    """Validate current review facts and coverage without search or solving."""
    matched = validate_matches(project_root, director, treatment)
    plan = semantic_visual_plan.validate_semantic_lists(treatment, director)
    rows = {row["row_id"]: row for row in plan["items"]}
    by_id = {m["candidate"]["candidate_id"]: m["candidate"]
             for item in matched.values() for m in item["matches"]}
    validate_review_identities(director, treatment, by_id)
    selection = treatment.get("skill_selection", {})
    beats = list(selection.get("beats", [])) + list(selection.get("overlay_beats", []))
    allowed = {"preferred", "equivalent", "unsuitable", "needs_adapter", "unreviewed"}
    basis = {"semantic", "quality", "capacity", "output", "timing", "qualification", "authorization"}
    covered = set()
    for beat in beats:
        key = (beat.get("segment_id"), beat.get("component_id"))
        if key not in matched or key in covered:
            raise ValueError("review beat target is unknown or duplicated")
        row_id = beat.get("semantic_row_id")
        if row_id not in rows or matched[key]["row_id"] != row_id:
            raise ValueError("review beat semantic row does not match its component")
        covered.add(key)
        candidates = beat.get("candidates")
        if not isinstance(candidates, list): raise ValueError("review beat candidates are required")
        ids = [c.get("candidate_id") for c in candidates]
        cached = {m["evidence"]["candidate_id"] for m in matched[key]["matches"]}
        if len(ids) != len(set(ids)) or set(ids) != cached: raise ValueError("review candidates must cover every cached match exactly")
        for candidate in candidates:
            cid = candidate.get("candidate_id"); fit = candidate.get("fit")
            if cid not in by_id or fit not in allowed or not isinstance(candidate.get("reason"), str) or not candidate["reason"].strip(): raise ValueError("invalid candidate review")
            row = by_id[cid]
            typ = matched[key]["semantic"]["type"]; required = "aroll_overlay" if typ == "贴片" else "broll"
            uses = row.get("capability", {}).get("uses", [])
            callable = required in uses or (required == "broll" and "design" in uses)
            if fit in {"preferred", "equivalent"} and (row.get("status") != "supported" or not callable): raise ValueError("unsupported candidate cannot be eligible")
            if fit == "unsuitable" and candidate.get("rejection_basis") not in basis: raise ValueError("unsuitable review needs a controlled rejection basis")
            if fit not in {"preferred", "equivalent", "unreviewed"} and row.get("status") == "supported":
                _constraint_refs(candidate, matched[key]["semantic"], row, beat, job_dir=job_dir)
        eligible = [c for c in candidates if c["fit"] in {"preferred", "equivalent"}]
        from .broll_skill_selection import source_channel
        channels = {source_channel(by_id[c["candidate_id"]]["skill_id"]) for c in eligible}
        if len(channels) == 1:
            review = beat.get("single_source_review")
            if (not isinstance(review, dict) or set(review) != {"decision", "reason"}
                    or review.get("decision") != "keep"
                    or not isinstance(review.get("reason"), str) or not review["reason"].strip()):
                raise ValueError("single-source candidates need a completed single_source_review")
    for key in matched:
        if key not in covered:
            seg, cid = key; comp = next((c for s in director.get("segments", []) if s.get("segment_id") == seg for c in s.get("visual_strategy", {}).get("components", []) if c.get("component_id") == cid), {})
            if comp.get("kind") == "code_generated": raise ValueError("code component is missing a review beat")
    return matched


def validate_reviews(project_root, director, treatment, *, job_dir=None):
    """Independently validate coverage and any outstanding joint optimum proof."""
    matched = _validate_review_structure(project_root, director, treatment, job_dir=job_dir)
    selection = treatment.get("skill_selection", {})
    beats = [*selection.get("beats", []), *selection.get("overlay_beats", [])]
    if any(c.get("fit") == "unreviewed" for b in beats for c in b["candidates"]):
        from .broll_skill_selection import assign_skills
        assign_skills(project_root, selection, job_dir=job_dir, director=director, treatment=treatment)
    return matched

DESIGN_FIELDS = ("composition", "typography", "finish", "focus")

def _constraint_refs(review, semantic, candidate, beat, *, job_dir):
    """Resolve only this row's meaning and this candidate's pinned capability."""
    refs = review.get("constraint_refs")
    if not isinstance(refs, dict) or set(refs) != {"requirement", "capability"}:
        raise ValueError("excluded supported candidate needs concrete constraint_refs")
    requirement = refs.get("requirement")
    if isinstance(requirement, str):
        if requirement not in {"quote", "semantic"} or not semantic.get(requirement):
            raise ValueError("constraint requirement must cite the current quote or semantic, not visual_task")
        if review.get("rejection_basis") in {"timing", "authorization"}:
            raise ValueError("timing and authorization exclusions need a confirmed constraint source")
    elif isinstance(requirement, dict) and set(requirement) == {"source", "receipt"}:
        basis = review.get("rejection_basis")
        if (basis not in {"timing", "authorization"}
                or requirement["source"] != {"timing": "locked_window", "authorization": "authorization"}[basis]):
            raise ValueError("constraint source does not match its rejection basis")
        if job_dir is None:
            raise ValueError("confirmed constraint source needs the existing Job directory")
        from . import visual_confirmation
        workflow = contract_artifacts.read_json_artifact(Path(job_dir) / "workflow.json")
        job_id = workflow.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("confirmed constraint source needs the current Job identity")
        _, proposal = visual_confirmation._validate_source(
            Path(job_dir), requirement["receipt"], job_id=job_id)
        targets = [r for r in proposal["rows"] if r.get("semantic_row_id") == semantic["row_id"]
                   and r["segment_id"] == beat["segment_id"] and r["component_id"] == beat["component_id"]]
        if len(targets) != 1:
            raise ValueError("confirmed constraint belongs to another visual item")
        if basis == "timing":
            target = targets[0]
            minimum = candidate.get("min_duration_seconds")
            if (any(beat.get(k) != target[k] for k in ("start", "end"))
                    or type(minimum) not in (float, int)
                    or minimum <= target["end"] - target["start"]):
                raise ValueError("timing exclusion must exceed the confirmed item's unchanged window")
    else:
        raise ValueError("invalid constraint requirement reference")
    reference = refs.get("capability")
    profile = candidate.get("capability", {})
    if isinstance(reference, str) and reference in {"summary", "status", "min_duration_seconds"}:
        value = profile.get("summary") if reference == "summary" else candidate.get(reference)
    elif isinstance(reference, str) and reference.count("/") == 1:
        field, index = reference.split("/")
        values = profile.get(field)
        value = (values[int(index)] if field in {"limitations", "editable_content", "evidence"}
                 and isinstance(values, list) and index.isascii() and index.isdigit()
                 and int(index) < len(values) else None)
    else:
        value = None
    if value is None or value == "":
        raise ValueError("constraint capability reference must belong to the current candidate")

def validate_design_handoffs(director, treatment, job_dir, *, planned_targets=()):
    """Bind approved meaning and native route; the native Skill owns its design."""
    selection = treatment.get("skill_selection", {})
    rows = semantic_visual_plan.component_semantic_rows(treatment)
    for assignment in [*selection.get("assignments", []), *selection.get("overlay_assignments", [])]:
        skill = assignment.get("skill_id")
        if skill not in {"openfilm-motion-graphics", "lemo-opuscar"}:
            continue
        key = (assignment["segment_id"], assignment["component_id"])
        if key in planned_targets:
            continue  # Realization binds the native scene once its inputs exist.
        segment = next(s for s in director["segments"] if s["segment_id"] == key[0])
        binding = segment.get("bindings", {}).get(key[1], {})
        if (binding.get("dependency_id") != skill
                or binding.get("template_id") != assignment.get("template_id")):
            raise ValueError("selected native handoff changed its approved channel or template")
        brief = motion_capabilities._bound_brief(Path(job_dir), treatment, segment, key[1])
        handoff = brief.get("creative_handoff", {}) if isinstance(brief, dict) else {}
        beat = next((b for b in [*selection.get("beats", []), *selection.get("overlay_beats", [])]
                     if (b.get("segment_id"), b.get("component_id")) == key), None)
        if not isinstance(beat, dict):
            raise ValueError("selected native component has no approved semantic beat")
        # The semantic list remains the authority. Planning art descriptions
        # are context, not text the native creator must copy back verbatim.
        row = rows.get(key)
        if row is None:
            raise ValueError("selected native component must bind exactly one approved semantic row")
        expected = {"transcript": row.get("quote"), "semantic_goal": row.get("semantic"),
                    "required_change": row.get("visual_task")}
        if (beat.get("semantic_row_id") != row.get("row_id")
                or any(not isinstance(value, str) or not value.strip()
                       or handoff.get(field) != value or beat.get(field) != value
                       for field, value in expected.items())):
            raise ValueError("selected native semantic handoff differs from the approved semantic row or beat")
        template = ("lemo-opuscar/" + brief.get("style_slug", "")
                    if skill == "lemo-opuscar" else "openfilm/motion-graphics-scene")
        if assignment.get("template_id") != template:
            raise ValueError("selected native handoff changed its approved template")

def _validate_entry(entry, rows, use, query):
    if not isinstance(entry, dict) or entry.get("matching_policy_version")!=motion_capabilities.MATCHING_POLICY_VERSION or not isinstance(entry.get("matches"), list): raise ValueError("invalid motion match cache entry")
    if entry.get("matches_sha256") != contract_artifacts.sha256_json(entry["matches"]):
        raise ValueError("complete motion match cache changed")
    catalog={r.get("candidate_id"):r for r in rows}; seen=set()
    # Recheck deterministic recall completeness against this same frozen catalog.
    # This does not rerun search or ask the host to judge candidates again.
    recalled = {}
    for cid, candidate in catalog.items():
        profile = candidate.get("capability", {})
        uses = profile.get("uses", [])
        if candidate.get("status") != "supported" or (use not in uses and not (use == "broll" and "design" in uses)):
            continue
        expected = motion_capabilities._recall_evidence(profile, query)
        if expected["recall_basis"] is not None:
            recalled[cid] = expected
    for evidence in entry["matches"]:
        if not isinstance(evidence, dict) or set(evidence)!={"candidate_id","matched_dimensions","retrieval_score","recall_basis"}: raise ValueError("invalid cached match evidence")
        cid=evidence.get("candidate_id")
        if not isinstance(cid,str) or cid in seen or cid not in catalog: raise ValueError("cached candidate is missing or duplicated")
        seen.add(cid); profile=catalog[cid].get("capability",{}); uses=profile.get("uses",[])
        if use not in uses and not (use=="broll" and "design" in uses): raise ValueError("cached candidate use is invalid")
        expected = recalled.get(cid)
        if expected is None:
            raise ValueError("cached candidate has no reviewed recall basis")
        if evidence["recall_basis"]!=expected["recall_basis"]:
            raise ValueError("cached recall basis changed")
        if evidence.get("matched_dimensions") != expected.get("matched_dimensions"):
            raise ValueError("cached matched dimensions changed")
        score=sum(len(v)*(4 if k in {"actions","relations"} else 1) for k,v in expected["matched_dimensions"].items())
        if evidence.get("retrieval_score") != score: raise ValueError("cached retrieval score changed")
    if seen != set(recalled):
        raise ValueError("motion match cache must retain the complete recalled candidate set")

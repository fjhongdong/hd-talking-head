"""Persistent, identity-bound semantic motion matching cache."""
from __future__ import annotations
import copy, hashlib, json
from pathlib import Path
from . import contract_artifacts, motion_capabilities, semantic_visual_plan

def _catalog(root):
    rows = motion_capabilities.load_catalog(Path(root))
    return rows, contract_artifacts.sha256_json(rows)

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

def _identity(row, typ, tags):
    payload={k:row[k] for k in ("row_id","quote","start_word","end_word","semantic","visual_task")}
    payload["type"]=typ; payload["tags"]=tags
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()).hexdigest()

def match_once(project_root, director, treatment):
    out=copy.deepcopy(treatment); rows,csha=_catalog(project_root); items=_items(project_root,director,out)
    cache=out.get("motion_matches",{}); new={}
    for row,typ,tags in items:
        rid=row["row_id"]; use="aroll_overlay" if typ=="贴片" else "broll"; sid=_identity(row,typ,tags)
        old=cache.get(rid)
        if isinstance(old,dict) and old.get("catalog_sha256")==csha and old.get("semantic_sha256")==sid and old.get("use")==use and old.get("tags")==tags:
            _validate_entry(old, rows, use, tags)
            new[rid]=old; continue
        matches=motion_capabilities.search_capabilities(Path(project_root), " ".join(tags), use=use, catalog=rows)
        frozen = [{k:m.get(k) for k in ("candidate_id","matched_dimensions","retrieval_score")} for m in matches]
        new[rid]={"catalog_sha256":csha,"semantic_sha256":sid,"use":use,"tags":tags,
                  "matches":frozen,"matches_sha256":contract_artifacts.sha256_json(frozen)}
    out["motion_matches"]=new; return out

def validate_matches(project_root,director,treatment):
    rows,csha=_catalog(project_root); catalog={r.get("candidate_id"):r for r in rows}; items=_items(project_root,director,treatment); cache=treatment.get("motion_matches")
    if not isinstance(cache,dict): raise ValueError("motion_matches cache is required")
    if set(cache)!={r["row_id"] for r,_,_ in items}: raise ValueError("motion_matches keys do not match semantic rows")
    out={}
    for row,typ,tags in items:
        rid=row["row_id"]; e=cache[rid]; use="aroll_overlay" if typ=="贴片" else "broll"
        if e.get("catalog_sha256")!=csha or e.get("semantic_sha256")!=_identity(row,typ,tags) or e.get("use")!=use or e.get("tags")!=tags: raise ValueError("motion match cache identity changed")
        _validate_entry(e, rows, use, tags)
        raw=[]
        for m in e.get("matches",[]):
            cid=m.get("candidate_id")
            if cid not in catalog: raise ValueError("cached candidate is absent from catalog")
            current=catalog[cid]
            if current.get("candidate_id")!=cid: raise ValueError("catalog identity mismatch")
            raw.append({"candidate":current,"evidence":m})
        for ref in row["components"]: out[(ref["segment_id"],ref["component_id"])]= {"row_id":rid,"semantic":row,"matches":raw}
    return out

def validate_reviews(project_root, director, treatment, *, job_dir=None):
    """Validate concrete per-beat review coverage without performing search."""
    matched = validate_matches(project_root, director, treatment)
    plan = semantic_visual_plan.validate_semantic_lists(treatment, director)
    rows = {row["row_id"]: row for row in plan["items"]}
    catalog, _ = _catalog(project_root); by_id = {r.get("candidate_id"): r for r in catalog}
    selection = treatment.get("skill_selection", {})
    beats = list(selection.get("beats", [])) + list(selection.get("overlay_beats", []))
    allowed = {"preferred", "equivalent", "unsuitable", "needs_adapter"}
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
            if fit in {"preferred", "equivalent"}:
                _design_plan(candidate)
            elif row.get("status") == "supported":
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

DESIGN_FIELDS = ("composition", "typography", "finish", "focus")

def _design_plan(candidate):
    """Require a content-specific plan, not an automated aesthetic score."""
    plan = candidate.get("design_plan")
    if (not isinstance(plan, dict) or set(plan) != set(DESIGN_FIELDS)
            or any(not isinstance(plan.get(k), str) or not plan[k].strip()
                   for k in DESIGN_FIELDS)):
        raise ValueError("eligible candidate needs a complete design_plan")
    return plan

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

def validate_design_handoffs(director, treatment, job_dir):
    """Pass the selected design unchanged to the native creation Skill."""
    selection = treatment.get("skill_selection", {})
    for assignment in [*selection.get("assignments", []), *selection.get("overlay_assignments", [])]:
        if assignment.get("skill_id") not in {"openfilm-motion-graphics", "lemo-opuscar"}:
            continue
        design = _design_plan(assignment)
        segment = next(s for s in director["segments"] if s["segment_id"] == assignment["segment_id"])
        brief = motion_capabilities._bound_brief(Path(job_dir), treatment, segment, assignment["component_id"])
        handoff = brief.get("creative_handoff", {}) if isinstance(brief, dict) else {}
        if assignment["skill_id"] == "lemo-opuscar":
            if (handoff.get("design_plan") != design
                    or assignment.get("template_id") != "lemo-opuscar/" + brief.get("style_slug", "")):
                raise ValueError("selected Lemo template and design_plan must reach its native creative handoff")
            continue
        style = handoff.get("style_reason")
        if not isinstance(style, str) or any(value not in style for value in design.values()):
            raise ValueError("selected OpenFilm design_plan must reach creative_handoff.style_reason")

def _validate_entry(entry, rows, use, tags):
    if not isinstance(entry, dict) or not isinstance(entry.get("matches"), list): raise ValueError("invalid motion match cache entry")
    if entry.get("matches_sha256") != contract_artifacts.sha256_json(entry["matches"]):
        raise ValueError("complete motion match cache changed")
    catalog={r.get("candidate_id"):r for r in rows}; seen=set()
    for evidence in entry["matches"]:
        if not isinstance(evidence, dict) or set(evidence)-{"candidate_id","matched_dimensions","retrieval_score"}: raise ValueError("invalid cached match evidence")
        cid=evidence.get("candidate_id")
        if not isinstance(cid,str) or cid in seen or cid not in catalog: raise ValueError("cached candidate is missing or duplicated")
        seen.add(cid); profile=catalog[cid].get("capability",{}); uses=profile.get("uses",[])
        if use not in uses and not (use=="broll" and "design" in uses): raise ValueError("cached candidate use is invalid")
        expected=motion_capabilities._match_evidence(profile," ".join(tags))
        if not expected["has_motion_basis"]:
            raise ValueError("cached candidate has no semantic motion match")
        if evidence.get("matched_dimensions") != expected.get("matched_dimensions"):
            raise ValueError("cached matched dimensions changed")
        score=sum(len(v)*(4 if k in {"actions","relations"} else 1) for k,v in expected["matched_dimensions"].items())
        if evidence.get("retrieval_score") != score: raise ValueError("cached retrieval score changed")

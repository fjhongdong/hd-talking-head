"""Pure validation for readable text in motion overlays."""
import hashlib, json, re, math
from pathlib import Path

CANVAS = (1080, 1920)
MIN_HEIGHTS = {"title": 48.0, "body": 36.0}

def _norm(s):
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", str(s)))

def _ref_key(r):
    return tuple(r.get(k) for k in ("path", "sha256", "pointer", "value"))

def _rect(r):
    if not isinstance(r, dict) or any(k not in r for k in ("x", "y", "width", "height")):
        raise ValueError("invalid region")
    if any(isinstance(r[k], bool) for k in ("x", "y", "width", "height")): raise ValueError("invalid numeric region")
    vals = [float(r[k]) for k in ("x", "y", "width", "height")]
    if not all(math.isfinite(x) for x in vals): raise ValueError("invalid numeric region")
    if vals[2] <= 0 or vals[3] <= 0 or vals[0] < 0 or vals[1] < 0 or vals[0]+vals[2] > 1080 or vals[1]+vals[3] > 1920:
        raise ValueError("region outside 1080x1920")
    return vals

def _intersects(a, b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]

def _inside(root, ref):
    p = Path(ref["path"])
    if p.is_absolute() or ".." in p.parts: raise ValueError("content_ref path must be relative")
    f = (Path(root) / p).resolve(); base = Path(root).resolve()
    if base not in f.parents: raise ValueError("content_ref escapes root")
    if hashlib.sha256(f.read_bytes()).hexdigest() != ref["sha256"]: raise ValueError("content_ref sha256 mismatch")
    source = f.read_text()
    if ref["pointer"].startswith("text:"):
        if f.suffix.lower() not in {".html", ".htm", ".tsx", ".jsx", ".js", ".mjs", ".cjs", ".ts", ".svg"}:
            raise ValueError("literal reference requires a rendered text source")
        parts = ref["pointer"].split(":")
        if len(parts) != 3 or not all(p.isdigit() for p in parts[1:]):
            raise ValueError("invalid literal text span")
        start, end = map(int, parts[1:])
        if not 0 <= start < end <= len(source) or source[start:end] != ref["value"]:
            raise ValueError("literal text reference mismatch")
        return
    obj = json.loads(source)
    for part in ref["pointer"].lstrip("/").split("/") if ref["pointer"] else []:
        part = part.replace("~1", "/").replace("~0", "~")
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    if obj != ref["value"]: raise ValueError("content_ref pointer mismatch")

def validate_targets(segments, records, required_refs, *, root=None):
    sm = {s["segment_id"]: s for s in segments}; rm = {}; out = []; ids = set()
    for r in records:
        if type(r) is not dict or set(r) - {"segment_id", "component_id", "targets", "no_critical_text_reason"}:
            raise ValueError("unknown readability record fields")
        key = (r["segment_id"], r["component_id"])
        if key in rm: raise ValueError("duplicate motion_readability record")
        rm[key] = r
    valid_keys={(sid, c.get("component_id") or c.get("id")) for sid,s in sm.items() for c in ((s.get("shot_recipe") or {}).get("components") or [])}
    if set(rm)-valid_keys: raise ValueError("unknown readability record")
    req = {(r["segment_id"], r["component_id"]): r["content_ref"] for r in required_refs}
    for sid, s in sm.items():
        comps = (s.get("shot_recipe") or {}).get("components") or []
        for c in comps:
            cid = c.get("component_id") or c.get("id")
            r = rm.get((sid, cid))
            if r is None: raise ValueError(f"missing readability record: {sid}/{cid}")
            ts = r.get("targets") or []
            if not ts:
                if req.get((sid,cid)) is not None or len(str(r.get("no_critical_text_reason", ""))) < 6: raise ValueError("missing targets")
                out.append({"segment_id": sid, "component_id": cid, "status": "not_applicable"}); continue
            duration = float(s["end"]) - float(s["start"]); spans = {}
            for t in ts:
                if type(t) is not dict or set(t) != {"target_id", "content_ref", "span", "role", "region", "windows"}:
                    raise ValueError("invalid readability target fields")
                if type(t["target_id"]) is not str or not t["target_id"].strip():
                    raise ValueError("target_id required")
                if type(t["content_ref"]) is not dict or set(t["content_ref"]) != {"path", "sha256", "pointer", "value"} or type(t["content_ref"]["value"]) is not str:
                    raise ValueError("target requires bound string content_ref")
                if t["target_id"] in ids: raise ValueError("duplicate target_id")
                ids.add(t["target_id"]); ref = t["content_ref"]
                if root is not None: _inside(root, ref)
                if not isinstance(t.get("span"), list) or len(t["span"]) != 2: raise ValueError("invalid span")
                a, b = t["span"]
                if type(a) is not int or type(b) is not int or not (0 <= a < b <= len(ref.get("value", ""))): raise ValueError("invalid span")
                text = ref["value"][a:b]
                if not _norm(text): raise ValueError("blank target")
                if t.get("role") not in MIN_HEIGHTS: raise ValueError("invalid role")
                _rect(t["region"])
                if not t.get("windows"): raise ValueError("empty windows")
                for w in t.get("windows", []):
                    if type(w) is not dict or set(w) != {"start", "end"}:
                        raise ValueError("invalid window fields")
                    if any(isinstance(w.get(k), bool) or not math.isfinite(float(w[k])) for k in ("start","end")): raise ValueError("invalid window")
                    if w["end"] <= w["start"] or w["end"]-w["start"] < .5 or w["start"] < 0 or w["end"] > duration: raise ValueError("invalid window")
                ws=sorted((w["start"],w["end"]) for w in t["windows"])
                if any(ws[i][0] < ws[i-1][1] for i in range(1,len(ws))): raise ValueError("overlapping windows")
                k = _ref_key(ref); spans.setdefault(k, []).append((a,b))
                d = dict(t); d.update(text=text, segment_id=sid, component_id=cid); out.append(d)
            for rr in required_refs:
                if rr["segment_id"] == sid and rr["component_id"] == cid:
                    val = rr["content_ref"]["value"]; covered = set()
                    for a,b in spans.get(_ref_key(rr["content_ref"]), []): covered.update(range(a,b))
                    if any(ch.isalnum() and i not in covered for i,ch in enumerate(val)): raise ValueError("required text not fully covered")
    return out

def sample_times(target, *, step=1.0):
    if not math.isfinite(step) or step <= 0: raise ValueError("step must be positive")
    vals = []
    for w in target.get("windows", []):
        a,b = float(w["start"]), float(w["end"]); e=1/24
        vals += [a+e, (a+b)/2, b-e]
        x=a
        while x < b: vals.append(x); x += step
    vals = sorted({round(x, 6) for x in vals})
    return vals

def assess_target(target, samples, *, excluded_regions=(), min_heights=None, min_confidence=.45):
    threshold = dict(MIN_HEIGHTS); threshold.update(min_heights or {}); expected=sample_times(target); result=[]; bad=False; review=False; heights=[]
    excluded=list(excluded_regions)
    for et in expected:
        s = min(samples, key=lambda x: abs(float(x.get("time", -999))-et), default=None)
        if s is None or abs(float(s.get("time", -999))-et) > 1/48:
            result.append({"time":et,"status":"needs_review","reason":"missing_sample"}); review=True; continue
        cand=[]; tr=target["region"]; trr=[tr[k] for k in ("x","y","width","height")]
        if s.get("width") != 1080 or s.get("height") != 1920:
            result.append({"time":s["time"],"status":"needs_review","reason":"invalid_frame_resolution","frame_sha256":s.get("frame_sha256"),"frame_path":s.get("frame_path" )}); review=True; continue
        for o in s.get("observations", []):
            bb=o.get("bbox");
            if bb and _norm(o.get("text", "")) == _norm(target["text"]) and bb[0] >= trr[0] and bb[1] >= trr[1] and bb[0]+bb[2] <= trr[0]+trr[2] and bb[1]+bb[3] <= trr[1]+trr[3]: cand.append(o)
        if not cand: result.append({"time":s["time"],"status":"needs_review","reason":"text_not_proven","frame_sha256":s.get("frame_sha256"),"frame_path":s.get("frame_path"),"excluded_regions":excluded+list(s.get("excluded_regions", []))}); review=True; continue
        valid=[o for o in cand if not any(_intersects(o["bbox"], x) for x in excluded+list(s.get("excluded_regions", [])))]
        if not valid: result.append({"time":s["time"],"status":"needs_review","reason":"excluded_region","frame_sha256":s.get("frame_sha256"),"frame_path":s.get("frame_path"),"excluded_regions":excluded+list(s.get("excluded_regions", []))}); review=True; continue
        reliable = [o for o in valid if float(o.get("confidence", 0)) >= min_confidence
                    and "\n" not in str(o.get("text", "")) and o.get("line_count", 1) == 1]
        # One small, reliably located instance cannot be hidden by a larger one.
        o = min(reliable, key=lambda x: float(x["bbox"][3])) if reliable else max(valid, key=lambda x: float(x.get("confidence", 0)))
        bb=o["bbox"]; h=float(bb[3]); reason=""
        if float(o.get("confidence",0)) < min_confidence: reason="low_confidence"
        elif "\n" in str(o.get("text", "")) or o.get("line_count", 1) > 1: reason="aggregate_multiline"
        elif bb[0] < 0 or bb[1] < 0 or bb[0]+bb[2] > s.get("width",1080) or bb[1]+bb[3] > s.get("height",1920): reason="clipped"
        elif h < threshold[target["role"]]: bad=True; reason="line_box_below_baseline"
        st="fail" if bad and reason=="line_box_below_baseline" else ("needs_review" if reason else "pass")
        result.append({"time":s["time"],"status":st,"reason":reason,"frame_sha256":s.get("frame_sha256"),"frame_path":s.get("frame_path"),"bbox":bb,"height":h,"excluded_regions":excluded+list(s.get("excluded_regions", []))}); heights.append(h)
        review |= st=="needs_review"
    status="fail" if any(x["status"]=="fail" for x in result) else ("needs_review" if review else "sampled_pass")
    return {"target_id":target["target_id"],"segment_id":target.get("segment_id"),"component_id":target.get("component_id"),"text":target["text"],"role":target["role"],"region":target["region"],"status":status,"minimum_height_px":min(heights) if heights else None,"minimum_required_height_px":threshold[target["role"]],"samples":result}

def validate_resolutions(report, resolutions):
    if report.get("configuration_issues"):
        raise ValueError("readability configuration must be fixed before approval")
    need={(t["target_id"], round(float(s["time"]),6)): (t,s) for t in report.get("targets",[]) for s in t.get("samples",[]) if s["status"]=="needs_review"}
    for t in report.get("targets", []):
        if t["status"] == "fail": raise ValueError("fail cannot be waived")
    seen=set()
    for r in resolutions or []:
        k=(r["target_id"],round(float(r["time"]),6))
        if k not in need or k in seen: raise ValueError("extra or duplicate resolution")
        t,s=need[k]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(r.get("frame_sha256", ""))) or r.get("frame_sha256") != s.get("frame_sha256") or _norm(r.get("text", "")) != _norm(t.get("text", "")): raise ValueError("resolution does not match frame/text")
        if len(str(r.get("reason", ""))) < 6: raise ValueError("resolution reason required")
        if not all(r.get(x) is True for x in ("unclipped","unobstructed","contrast_clear","window_reviewed")): raise ValueError("incomplete resolution")
        bb=r.get("bbox"); _rect({"x":bb[0],"y":bb[1],"width":bb[2],"height":bb[3]})
        tr=[t["region"][k] for k in ("x","y","width","height")]
        if bb[3] < t["minimum_required_height_px"] or bb[0] < tr[0] or bb[1] < tr[1] or bb[0]+bb[2] > tr[0]+tr[2] or bb[1]+bb[3] > tr[1]+tr[3]: raise ValueError("resolution bbox below baseline/outside target")
        if any(_intersects(bb, x) for x in s.get("excluded_regions", [])):
            raise ValueError("manual text box overlaps subtitles or presenter")
        seen.add(k)
    if seen != set(need): raise ValueError("missing resolution")

# Job integration. The same report is consumed by the stage UI, approval and
# delivery; no renderer-specific font declarations are trusted as measurements.
def _managed(job):
    return (job.root / 'job-context.json').exists() or (job.root / '00-user-provided').exists()


def _required_refs(treatment):
    result = []
    # Semantic references can also identify routes or assets. Only visible
    # text fields are mandatory here; every visual component still needs its
    # explicit target inventory or a concrete no-critical-text explanation.
    visible = re.compile(r'/(?:title|heading|label|labels|items|text|body|caption|stamp|prompt|question)(?:/\d+)?$')
    for item in treatment.get('semantic_assessments', []):
        for ref in item.get('content_refs', []):
            if not visible.search(str(ref.get('pointer', ''))):
                continue
            value = ref.get('value')
            refs = []
            if isinstance(value, str):
                refs = [ref]
            elif isinstance(value, list):
                refs = [{**ref, 'pointer': ref['pointer'] + '/' + str(i), 'value': text}
                        for i, text in enumerate(value) if isinstance(text, str)]
            for r in refs:
                if not re.search(r'\.(?:png|jpe?g|webp|mp4|mov|svg)$', r['value'], re.I):
                    result.append({'segment_id': item['segment_id'], 'component_id': item['component_id'], 'content_ref': r})
    # Every declared field is checked in full, including wrapped fragments.
    for item in treatment.get('motion_readability', []):
        for target in item.get('targets', []):
            result.append({'segment_id': item['segment_id'], 'component_id': item['component_id'],
                           'content_ref': target['content_ref']})
    return result


def validate_direction_contract(job, director, treatment):
    if not _managed(job):
        return
    segments = [{**s, 'shot_recipe': {'components': s['visual_strategy']['components']}}
                for s in director['segments']]
    validate_targets(segments, treatment.get('motion_readability', []),
                     _required_refs(treatment), root=job.job_dir)


def _current_inputs(job):
    from . import visual_confirmation, contract_artifacts as artifacts
    authorization = visual_confirmation.validate_visual_authorization(job, require_realized=True)
    mapping = authorization['mapping']
    ref = mapping.get('realization_inputs', {}).get('treatment')
    if ref is None:
        # Use the explicit frozen input record, never a mutable Job draft.
        ref = authorization['source']['inputs']['treatment']
    treatment_path = visual_confirmation._exact(job.job_dir, ref)
    plan_path = _published(job, 'visual_direction', '07-visual-direction/visual-plan.json')
    plan = artifacts.read_json_artifact(plan_path)
    return plan, artifacts.read_json_artifact(treatment_path), {
        'plan_sha256': artifacts.sha256_file(plan_path),
        'treatment_sha256': artifacts.sha256_file(treatment_path),
    }


def _published(job, stage, relative):
    from . import contract_artifacts as artifacts
    record = next((r for r in job.stages[stage]['artifacts'] if r['path'] == relative), None)
    path = job.job_dir / relative
    if record is None or not path.is_file() or artifacts.sha256_file(path) != record['sha256'] or path.stat().st_size != record['bytes']:
        raise ValueError('readability input is not the current published artifact: ' + relative)
    return path


def _policy():
    root = Path(__file__).resolve().parents[3]
    path = root / 'skill-development/hd-talking-head/references/production-defaults.json'
    return json.loads(path.read_text())['motion_text'], path


def _ocr(paths):
    import subprocess
    script = Path(__file__).resolve().parents[3] / 'skill-development/hd-talking-head/scripts/recognize_frame_text.swift'
    result = subprocess.run(['/usr/bin/swift', str(script), *map(str, paths)], capture_output=True, text=True, timeout=max(60, len(paths) * 15))
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError('local text measurement unavailable: ' + result.stderr[-400:]) from exc
    if result.returncode or any(x.get('status') != 'ok' for x in payload.get('images', [])):
        raise ValueError('local text measurement failed; inspect actual frames before approval')
    by_path = {str(Path(x['path']).resolve()): x for x in payload['images']}
    if set(by_path) != {str(p.resolve()) for p in paths}:
        raise ValueError('OCR did not return every actual frame')
    return by_path


def _exclusions(segment, time, subtitles):
    boxes = []
    avatar = segment['shot_recipe'].get('composition', {}).get('avatar')
    if avatar:
        position, profile = avatar['position'], avatar['profile']
        boxes.append([position['x'], position['y'], profile['diameter'], profile['diameter']])
    for cue in subtitles.get('render_plan', {}).get('cues', []):
        if cue['start'] <= time < cue['end']:
            box = cue['box']; boxes.append([box[k] for k in ('x', 'y', 'width', 'height')])
    return boxes


def inspect_job(job, stage):
    """Check every declared target in current rendered assets/final pixels."""
    import subprocess
    from . import contract_artifacts as artifacts
    if stage not in {'visual_canary', 'visual_assets', 'preview'}:
        raise ValueError('unsupported readability stage')
    plan, treatment, binding = _current_inputs(job)
    policy, policy_path = _policy()
    rules = Path(__file__).resolve()
    swift = rules.parents[3] / 'skill-development/hd-talking-head/scripts/recognize_frame_text.swift'
    binding.update(stage=stage, artifacts=job.stages[stage]['artifacts'],
                   rules_sha256=artifacts.sha256_file(rules), engine_sha256=artifacts.sha256_file(swift),
                   policy_sha256=artifacts.sha256_file(policy_path))
    report = {'schema_version': 1, 'stage': stage, 'binding': binding,
              'measurement': 'OCR line-box height in final 1080x1920 pixels; not CSS font size',
              'configuration_issues': [], 'targets': []}
    try:
        targets = validate_targets(plan['segments'], treatment.get('motion_readability', []),
                                   _required_refs(treatment), root=job.job_dir)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report.update(status='configuration_incomplete', configuration_issues=[str(exc)])
        return report
    segments = {s['segment_id']: s for s in plan['segments']}
    subtitles, offset = {}, 0.0
    media = {}
    if stage == 'preview':
        video = _published(job, stage, '11-preview/review.mp4')
        opening = job.job_dir / '11-preview/opening-manifest.json'
        if opening.is_file():
            info = artifacts.read_json_artifact(_published(job, stage, '11-preview/opening-manifest.json'))
            offset = info['body_offset_frames'] / info['fps']
        subs = job.job_dir / '10-subtitles/subtitle-plan.json'
        if subs.is_file():
            subtitles = artifacts.read_json_artifact(_published(job, 'subtitles', '10-subtitles/subtitle-plan.json'))
        media = {sid: (video, float(s['start']) + offset) for sid, s in segments.items()}
    else:
        folder, name = ('08-visual-canary', 'canary-manifest.json') if stage == 'visual_canary' else ('09-visual-assets', 'asset-manifest.json')
        manifest = artifacts.read_json_artifact(_published(job, stage, folder + '/' + name))
        for item in manifest['segments']:
            path = Path(item['video_path'])
            relative = path.relative_to(job.job_dir).as_posix() if path.is_absolute() else str(path)
            media[item['segment_id']] = (_published(job, stage, relative), 0.0)
    if stage == 'visual_assets':
        expected = {s['segment_id'] for s in plan['segments'] if s.get('shot_recipe', {}).get('components')}
        if not expected.issubset(media):
            raise ValueError('readability scan is missing rendered visual segments')
    targets = [t for t in targets if t['segment_id'] in media]
    identity = artifacts.sha256_json(binding)
    cache = job.job_dir / 'manifests/motion-readability' / (stage + '-' + identity[:16])
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / 'report.json'
    if cached.is_file():
        candidate = artifacts.read_json_artifact(cached)
        frames = [s for t in candidate.get('targets', []) for s in t.get('samples', []) if s.get('frame_path')]
        if candidate.get('binding') == binding and all(Path(s['frame_path']).is_file() and artifacts.sha256_file(Path(s['frame_path'])) == s['frame_sha256'] for s in frames):
            return candidate
    frame_records = {}
    for target in targets:
        if target.get('status') == 'not_applicable':
            continue
        for local in sample_times(target, step=policy['sample_step_seconds']):
            sid = target['segment_id']; key = (sid, local)
            if key in frame_records:
                continue
            video, base = media[sid]
            image = cache / (sid + '-' + str(round(local * 1000000)) + '.png')
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(base + local), '-i', str(video), '-frames:v', '1', str(image)], check=True, capture_output=True, timeout=30)
            frame_records[key] = {'time': local, 'frame_path': str(image), 'frame_sha256': artifacts.sha256_file(image),
                                  'excluded_regions': _exclusions(segments[sid], float(segments[sid]['start']) + local, subtitles)}
    try:
        recognized = _ocr([Path(x['frame_path']) for x in frame_records.values()]) if frame_records else {}
        for frame in frame_records.values():
            observed = recognized[str(Path(frame['frame_path']).resolve())]
            frame.update(width=observed['width'], height=observed['height'], observations=observed['observations'])
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report['ocr_issue'] = str(exc)
        for frame in frame_records.values():
            frame.update(width=1080, height=1920, observations=[])
    for target in targets:
        if target.get('status') == 'not_applicable':
            report['targets'].append(target); continue
        samples = [x for (sid, _), x in frame_records.items() if sid == target['segment_id']]
        report['targets'].append(assess_target(target, samples,
            min_heights=policy['minimum_ocr_line_height_px'], min_confidence=policy['minimum_ocr_confidence']))
    statuses = {t['status'] for t in report['targets']}
    report['status'] = 'fail' if 'fail' in statuses else ('needs_review' if 'needs_review' in statuses else ('not_applicable' if statuses == {'not_applicable'} or not statuses else 'sampled_pass'))
    artifacts.write_json_artifact(cached, report)
    return report


def validate_stage_review(job, stage, review):
    report = inspect_job(job, stage)
    validate_resolutions(report, review.get('motion_readability_resolutions', []))
    return report


def require_preview_review(job):
    """The final delivery consumer repeats the same gate, even after raw approve."""
    if not _managed(job):
        return
    report = inspect_job(job, 'preview')
    if report.get('configuration_issues') or any(t['status'] == 'fail' for t in report['targets']):
        validate_resolutions(report, [])
    if not any(t['status'] == 'needs_review' for t in report['targets']):
        return
    from . import contract_artifacts as artifacts
    for path in (job.job_dir / 'manifests').glob('local-qa-preview-r*.json'):
        receipt = artifacts.read_json_artifact(path)
        if (receipt.get('job_id') != job.job_id or receipt.get('job_dir') != str(job.job_dir)
                or receipt.get('stage') != 'preview' or receipt.get('reviewed_by') != 'host'
                or receipt.get('passed') is not True or receipt.get('artifacts') != job.stages['preview']['artifacts']
                or receipt.get('motion_readability') != report):
            continue
        validate_resolutions(report, receipt.get('motion_readability_resolutions', []))
        return
    raise ValueError('motion text readability has unresolved targets or no current bound host review')

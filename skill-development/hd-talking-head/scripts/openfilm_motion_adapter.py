"""Bound bridge for OpenFilm's native motion-graphics Skill.

The upstream Skill authors the scene; this module only freezes its inputs and
invokes the project-local OpenFilm renderer. It is deliberately not a scene
library or a motion engine.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, shutil, subprocess, tempfile
from pathlib import Path

if __name__ == "__main__" and Path(__file__).name == "<stdin>":
    p = argparse.ArgumentParser(add_help=False); p.add_argument("--skill-root", required=True, type=Path)
    SKILL = p.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    SKILL = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(SKILL / "scripts"))
from openfilm_runtime import check_runtime, probe_runtime, PACKAGE_VERSION
from adapter_kit import sha256_file as sha, validate_source_binding

ENTRY = "scripts/openfilm_motion_adapter.py"
DEPENDENCY_ID = "openfilm-motion-graphics"
VERSION = "1.0.0"
TEMPLATE_ID = "openfilm/motion-graphics-scene"

def _text(value, label, limit=4000):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid OpenFilm {label}")

def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    required = {"schema_version","source_binding","template_request","composition","entry","assets","upstream","creative_handoff"}
    if type(b) is not dict or set(b) != required or b["schema_version"] != 1: raise ValueError("Invalid OpenFilm brief")
    s, c, r = b["source_binding"], b["composition"], b["template_request"]
    validate_source_binding(s, "Invalid OpenFilm source clock")
    if type(c) is not dict or set(c) != {"width","height","fps","frames","alpha"} or any(type(c[k]) is not int or c[k] != v for k,v in (("width",1080),("height",1920),("fps",24))) or c["alpha"] is not False or type(c["frames"]) is not int or c["frames"] < 1 or abs((s["end"]-s["start"])*24-c["frames"]) > 1e-6: raise ValueError("Invalid OpenFilm composition")
    if type(r) is not dict or set(r) != {"semantic_family","information_units","numeric_values","numeric_scale"} or type(r["semantic_family"]) is not str or not r["semantic_family"] or type(r["information_units"]) is not int or r["information_units"] < 1 or type(r["numeric_values"]) is not list or r["numeric_scale"] not in {"linear","log","not_applicable"}: raise ValueError("Invalid OpenFilm template request")
    if r["numeric_values"] and r["numeric_scale"] == "not_applicable": raise ValueError("Numeric values require a scale")
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in r["numeric_values"]): raise ValueError("Invalid OpenFilm numeric values")
    if type(b["assets"]) is not list: raise ValueError("Invalid OpenFilm assets")
    records = [b["entry"], *b["assets"]]
    if len(records) > 8: raise ValueError("OpenFilm exceeds the public executor's eight frozen-file limit")
    refs, destinations = set(), set()
    for record in records:
        if type(record) is not dict or set(record) != {"media_ref","job_path","scene_path","sha256"}: raise ValueError("Invalid OpenFilm asset record")
        _text(record["media_ref"], "media_ref", 200)
        for key in ("job_path", "scene_path"): _text(record[key], key)
        p = Path(record["job_path"]); q = Path(record["scene_path"])
        if any(x.is_absolute() or '..' in x.parts or x.as_posix() == '.' for x in (p,q)) or not re.fullmatch(r"[a-f0-9]{64}", str(record["sha256"])): raise ValueError("Invalid OpenFilm asset path")
        if record["media_ref"] in refs or q.as_posix() in destinations: raise ValueError("Repeated OpenFilm media or scene path")
        refs.add(record["media_ref"])
        destinations.add(q.as_posix())
    if b["entry"]["scene_path"] != "index.html": raise ValueError("OpenFilm entry must be index.html")
    u = b["upstream"]
    if type(u) is not dict or set(u) != {"package_version","skill_sha256","manual_sha256"} or u["package_version"] != PACKAGE_VERSION or any(not re.fullmatch(r"[a-f0-9]{64}", str(u[k])) for k in ("skill_sha256","manual_sha256")): raise ValueError("Invalid OpenFilm upstream identity")
    h = b["creative_handoff"]
    if type(h) is not dict or set(h) != {"transcript","semantic_goal","required_change","subject","visual_pattern","style_reason","beats","forbidden_outcomes"}: raise ValueError("Invalid OpenFilm creative handoff")
    for k in ("transcript","semantic_goal","required_change","subject","visual_pattern","style_reason"): _text(h[k], k)
    if type(h["forbidden_outcomes"]) is not list or any(type(x) is not str or not x.strip() for x in h["forbidden_outcomes"]): raise ValueError("Invalid OpenFilm forbidden outcomes")
    if type(h["beats"]) is not list or not h["beats"]: raise ValueError("OpenFilm needs semantic beats")
    prev = -1
    for beat in h["beats"]:
        if type(beat) is not dict or set(beat) != {"start_frame","end_frame","spoken_anchor","before","action","after"}: raise ValueError("Invalid OpenFilm beat")
        if type(beat["start_frame"]) is not int or type(beat["end_frame"]) is not int or not (0 <= beat["start_frame"] < beat["end_frame"] <= c["frames"]) or beat["start_frame"] < prev: raise ValueError("Invalid OpenFilm beat range")
        prev = beat["end_frame"]
        for k in ("spoken_anchor","before","action","after"): _text(beat[k], k, 1000)
    return b

def _check_upstream(brief, runtime):
    expected = {"package_version": PACKAGE_VERSION,
                "skill_sha256": sha(Path(runtime["skill"])),
                "manual_sha256": sha(Path(runtime["manual"]))}
    if brief["upstream"] != expected:
        raise ValueError("OpenFilm brief refers to different native instructions")

def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True); runtime = check_runtime(project); entry_sha = sha(SKILL / ENTRY); py = Path(python_executable).resolve()
    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if check_runtime(project)["identity"] != runtime["identity"] or sha(SKILL / ENTRY) != entry_sha: raise ValueError("OpenFilm runtime changed")
        payload = brief_loader(job, recipe, component); b = validate_brief(payload)
        _check_upstream(b, runtime)
        plan = visual_canary.load_approved_visual_plan(job); seg = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        expected = {"aroll_sha256": plan["edited_aroll_sha256"], "segment_id": seg["segment_id"], "start": seg["start"], "end": seg["end"]}
        if seg["shot_recipe"] != json.loads(json.dumps(recipe)) or b["source_binding"] != expected or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"])) or component.get("source_sha256") != entry_sha or component.get("artifact_contract") != {"width":1080,"height":1920,"fps":24,"alpha":False} or component["render_window"].get("start_frame") != 0 or component["render_window"].get("end_frame") != b["composition"]["frames"] or component.get("layer_role") != "base" or component["render_window"].get("layout_slot") != "full_frame": raise ValueError("OpenFilm brief no longer matches approved B-roll shot")
        return payload
    def media(job, recipe, component, payload):
        b = validate_brief(payload); return tuple(ReferenceProcessMedia(media_ref=x["media_ref"], job_path=x["job_path"], sha256=x["sha256"]) for x in [b["entry"], *b["assets"]])
    return ReferenceProcessAdapter(adapter_id="openfilm-motion-graphics-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="OpenFilm", renderer_version=PACKAGE_VERSION, artifact_media_type="video", launcher=py, launcher_sha256=sha(py), brief_loader=guard, media_loader=media, self_contained_wrapper=True, timeout_seconds=300, argv_template=("{launcher}","{entrypoint}","--skill-root",str(SKILL),"--project-root",str(project),"--brief","{brief_path}","--media-manifest","{media_manifest_fd}","--runtime",runtime["root"],"--runtime-identity",runtime["identity"],"--node",runtime["node"],"--ffmpeg",runtime["ffmpeg"],"--ffprobe",runtime["ffprobe"],"--browser-cache",runtime["browser_cache"],"--output","{output_path}"))

def create_binding(adapter, brief_bytes, reference_sample):
    b=validate_brief(brief_bytes)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint != ENTRY
            or adapter.entrypoint_sha256 != sha(SKILL / ENTRY)
            or adapter.primary_renderer != "OpenFilm" or adapter.renderer_version != PACKAGE_VERSION):
        raise ValueError("OpenFilm adapter identity changed")
    return {"producer_type":"dependency","dependency_id":DEPENDENCY_ID,"entrypoint":ENTRY,"producer_version":VERSION,"primary_renderer":"OpenFilm","renderer_version":PACKAGE_VERSION,"template_origin":"custom_fallback","template_id":TEMPLATE_ID,"template_version":VERSION,"adaptation_level":"structural","source_entrypoint":ENTRY,"source_sha256":adapter.entrypoint_sha256,"sample_sha256":sha(Path(reference_sample)),"semantic_families":[b["template_request"]["semantic_family"]],"capacity":{"min_units":b["template_request"]["information_units"],"max_units":b["template_request"]["information_units"]},"brief_sha256":hashlib.sha256(brief_bytes).hexdigest(),"verification_id":hashlib.sha256((adapter.entrypoint_sha256+hashlib.sha256(brief_bytes).hexdigest()).encode()).hexdigest(),"invocation_record":{"argv":[str(adapter.launcher),ENTRY],"status":"planned","exit_code":None,"template_request":b["template_request"]}}

def _probe(path, contract, ffprobe):
    from whiteboard_adapter import create_artifact_probe
    return create_artifact_probe(ffprobe).probe(path, "video", contract)

def create_artifact_probe(ffprobe_executable):
    from whiteboard_adapter import create_artifact_probe as opaque_probe
    return opaque_probe(ffprobe_executable)

def _check_scene(scene, brief):
    """Enforce local input contracts, not a JavaScript security sandbox."""
    from urllib.parse import unquote, urlsplit
    declared = {x["scene_path"] for x in [brief["entry"], *brief["assets"]]}
    entry = (scene / "index.html").read_text(encoding="utf-8")
    if not re.search(r"window\.film\s*=", entry) or not re.search(r"\bframe\s*[:(]", entry):
        raise ValueError("OpenFilm scene must expose the native window.film/frame contract")
    for name in declared:
        file = scene / name
        if file.suffix.lower() not in {".html", ".js", ".mjs", ".css", ".svg"}:
            continue
        text = file.read_text(encoding="utf-8")
        text = text.replace("http://www.w3.org/2000/svg", "").replace("http://www.w3.org/1999/xlink", "")
        # A library's copyright URL and timer implementation do not describe
        # this page's resource access or playback. Keep actual references below
        # frozen; animation behavior is checked through OpenFilm's native clock.
        if re.search(r"<\s*(?:audio|video|iframe)\b|\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(|\bimport\s*\(", text, re.I):
            raise ValueError("OpenFilm scene requires frozen local resources without audio or dynamic network loading")
        refs = re.findall(r'''\b(?:src|href)\s*=\s*["']([^"']+)["']''', text)
        refs += re.findall(r'''url\(\s*["']?([^\s)'";]+)''', text)
        refs += re.findall(r'''(?:\bfrom\s*|\bimport\s*|@import\s*)["']([^"']+)["']''', text)
        for reference in refs:
            if reference.startswith("#"):
                continue
            url = urlsplit(reference)
            relative = Path(unquote(url.path))
            resolved = (file.parent / relative).resolve()
            if (url.scheme or url.netloc or url.query or relative.is_absolute()
                    or not resolved.is_relative_to(scene.resolve())
                    or str(resolved.relative_to(scene.resolve())) not in declared):
                raise ValueError("OpenFilm resource is not a frozen scene asset: " + reference)

def render(args):
    sys.path.insert(0, str(Path(args.project_root).resolve(strict=True)))
    payload = Path(args.brief).read_bytes()
    brief = validate_brief(payload)
    runtime = check_runtime(Path(args.project_root),
                            {key: getattr(args, key) for key in ("node", "ffmpeg", "ffprobe")},
                            args.browser_cache)
    directory = Path(tempfile.mkdtemp(prefix="openfilm-native-"))
    report = {"status": "preparing", "brief_sha256": hashlib.sha256(payload).hexdigest(),
              "source_binding": brief["source_binding"], "commands": []}
    def run(command, environment):
        record = {"argv": command, "exit_code": None}
        report["commands"].append(record)
        try:
            result = subprocess.run(command, cwd=directory, env=environment,
                                    capture_output=True, text=True, check=False, timeout=240)
        except subprocess.TimeoutExpired as error:
            record.update(stdout=(error.stdout or b"").decode("utf-8", "replace"),
                          stderr=(error.stderr or b"").decode("utf-8", "replace"), timed_out=True)
            raise
        record.update(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)
        result.check_returncode()
        return result
    try:
        if args.runtime_identity != runtime["identity"] or Path(args.runtime) != Path(runtime["root"]):
            raise ValueError("OpenFilm bound runtime changed")
        _check_upstream(brief, runtime)
        frozen = json.loads(Path(args.media_manifest).read_bytes())
        if frozen.get("schema_version") != "reference-process-media/v1" or frozen.get("brief_sha256") != report["brief_sha256"]:
            raise ValueError("Wrong OpenFilm media manifest")
        records = {x["media_ref"]: x for x in frozen["media"]}
        expected = [brief["entry"], *brief["assets"]]
        if len(records) != len(frozen["media"]) or set(records) != {r["media_ref"] for r in expected}:
            raise ValueError("Wrong frozen OpenFilm media set")
        scene = directory / "scene"
        scene.mkdir()
        for ref in expected:
            record = records[ref["media_ref"]]
            data = Path("/dev/fd/" + str(record["fd"])).read_bytes()
            if (hashlib.sha256(data).hexdigest() != ref["sha256"]
                    or record["sha256"] != ref["sha256"] or len(data) != record["byte_length"]):
                raise ValueError("Frozen OpenFilm media changed")
            destination = scene / ref["scene_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        _check_scene(scene, brief)
        environment = {key: os.environ[key] for key in ("HOME", "TMPDIR", "LANG") if key in os.environ}
        environment.update(PATH=os.pathsep.join(dict.fromkeys([
            *(str(Path(runtime[key]).parent) for key in ("node", "ffmpeg", "ffprobe")), "/usr/bin", "/bin"])),
            PLAYWRIGHT_BROWSERS_PATH=runtime["browser_cache"], OPENFILM_NO_BROWSER="1",
            OPENFILM_HOME=str(directory / "home"), OPENFILM_LIBRARY=str(directory / "library"),
            OPENFILM_SKILLS=str(directory / "skills"))
        native = directory / "native.mp4"
        # Public openfilm/render API avoids the CLI's automatic Studio opening,
        # update check and browser-download retry. The upstream renderer is unchanged.
        render_module = Path(runtime["cli"]).parents[1] / "src/render.mjs"
        invoke = ("const {render}=await import(process.argv[1]);"
                  "await render([process.argv[2]],{fps:24,workers:1,out:process.argv[3]});")
        run([runtime["node"], "--input-type=module", "-e", invoke, render_module.as_uri(),
             str(scene / "index.html"), str(native)], environment)
        target = directory / "target.mp4"
        # Metadata only; never change pixels, retime, loop or pad an invalid scene.
        run([runtime["ffmpeg"], "-v", "error", "-i", str(native), "-map", "0:v:0", "-an",
             "-c:v", "copy", "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1", str(target)], environment)
        media = _probe(target, {"width":1080, "height":1920, "fps":24, "alpha":False}, runtime["ffprobe"])
        if media["frame_count"] != brief["composition"]["frames"] or abs(media["duration"] - brief["composition"]["frames"] / 24) > 1 / 24000:
            raise ValueError("OpenFilm output does not match the approved frame clock")
        data = target.read_bytes()
        Path(args.output).write_bytes(data)
        result = {"upstream_route": "motion-graphics", "commands": report["commands"],
                  "runtime_identity": runtime["identity"], "brief_sha256": report["brief_sha256"],
                  "output_sha256": hashlib.sha256(data).hexdigest(), "frames": media["frame_count"],
                  "external_requests": 0, "authoring_mode": "openfilm_native_skill",
                  "normalization": "SAR metadata only; no new scene or asset generation"}
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
        log = directory / "failure-log.json"
        log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("OpenFilm stopped without retry; inspect " + str(log)) from error
    shutil.rmtree(directory)
    return result

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True,type=Path); p.add_argument("--probe",action="store_true"); p.add_argument("--brief"); p.add_argument("--media-manifest"); p.add_argument("--runtime"); p.add_argument("--runtime-identity",default=""); p.add_argument("--node"); p.add_argument("--ffmpeg"); p.add_argument("--ffprobe"); p.add_argument("--browser-cache"); p.add_argument("--output"); p.add_argument("--skill-root",type=Path)
    a=p.parse_args()
    if a.probe or not a.brief:
        sys.path.insert(0, str(a.project_root.resolve(strict=True)))
        adapter = create_adapter(a.project_root, sys.executable, lambda *_: b"")
        probe_runtime(a.project_root)
        print(json.dumps({"schema_version":1,"dependency_id":DEPENDENCY_ID,"entrypoint":ENTRY,"producer_version":VERSION,"adapter_identity":{"adapter_type":type(adapter).__name__,"approved_executor":adapter.approved_executor,"primary_renderer":adapter.primary_renderer}},ensure_ascii=False))
        raise SystemExit
    if a.brief: print(json.dumps(render(a), ensure_ascii=False))

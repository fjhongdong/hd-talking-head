"""Call the native single-stat template; adapt only identity, timing and alpha."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

if __name__ == "__main__" and Path(__file__).name == "<stdin>":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--skill-root", required=True, type=Path)
    SKILL = parser.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from huashu_stat_runtime import SOURCE_PIN, check_runtime, probe_runtime, sha

ENTRY = "scripts/huashu_stat_adapter.py"
DEPENDENCY_ID = "huashu-motion-native"
VERSION = "1.0.0"
TEMPLATE_ID = "huashu-motion/talking-head-stat"
RENDERER = "HuashuMotion"
STRUCTURE_SHA = "81acf35689e6f070145034b9254e777075f506e2255d95abde7ff0e5e039ae77"
REUSE_REFS = {"native-mov", "native-config", "native-evidence", "native-source"}
VARIABLES = re.compile(r"\sdata-composition-variables\s*=\s*('([^']*)'|\"([^\"]*)\")", re.I)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= 9007199254740991


def _text(value, maximum, *, empty=False):
    return (type(value) is str and (empty or bool(value.strip())) and len(value) <= maximum
            and not any(ord(c) < 32 for c in value))


def number_text(value):
    if value == int(value):
        return str(int(value))
    return format(Decimal(str(value)), "f")


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
    fields = {"schema_version", "source_binding", "composition", "parent_safe_zone", "metric",
              "layout", "style", "template_request", "upstream", "execution_mode", "assets"}
    if type(b) is not dict or set(b) != fields or type(b["schema_version"]) is not int or b["schema_version"] != 1:
        raise ValueError("Invalid Huashu stat brief")
    s, c, m = (b[k] for k in ("source_binding", "composition", "metric"))
    if (type(s) is not dict or set(s) != {"aroll_sha256", "segment_id", "start", "end"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(s["aroll_sha256"]))
            or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", str(s["segment_id"]))
            or not all(_number(s[k]) for k in ("start", "end")) or not 0 <= s["start"] < s["end"]):
        raise ValueError("Invalid stat source binding")
    if (type(c) is not dict or set(c) != {"width", "height", "fps", "frames", "alpha"}
            or any(type(c[k]) is not int or c[k] != v for k,v in (("width",1080),("height",1920),("fps",24)))
            or type(c["frames"]) is not int or c["frames"] < 1 or c["alpha"] is not True
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Stat requires the exact 1080x1920/24fps frame clock")
    if (type(m) is not dict or set(m) != {"value", "prefix", "suffix", "label", "target_frame", "hold_frames"}
            or not _number(m["value"]) or not _text(m["prefix"],12,empty=True)
            or not _text(m["suffix"],12,empty=True) or not _text(m["label"],40)
            or type(m["target_frame"]) is not int or type(m["hold_frames"]) is not int
            or m["target_frame"] < 15 or m["hold_frames"] < 24
            or m["target_frame"] + m["hold_frames"] > c["frames"] - 2):
        raise ValueError("Stat needs one real value and complete native entrance/exit")
    # The pinned native template derives decimals from String(value).
    if 0 < abs(m["value"]) < 0.000001:
        raise ValueError("Scientific-notation precision is not supported by this native counter")
    layout = b["layout"]
    if type(layout) is not dict or set(layout) != {"subject", "crop", "placement"}:
        raise ValueError("Stat requires one fixed native layout")
    subject = layout["subject"]
    if (type(subject) is not dict or set(subject) != {"subjectX", "subjectW", "subjectTop", "subjectBottom", "cardBottom"}
            or any(not _number(v) or not 0 <= v <= 1 for v in subject.values())
            or subject["subjectTop"] >= subject["subjectBottom"] or subject["subjectW"] <= 0):
        raise ValueError("Invalid native subject fractions")
    for box in (layout["crop"], layout["placement"]):
        if (type(box) is not dict or set(box) != {"x", "y", "width", "height"}
                or any(type(v) is not int for v in box.values())
                or min(box["x"],box["y"]) < 0 or min(box["width"],box["height"]) <= 0
                or box["x"] + box["width"] > 1080 or box["y"] + box["height"] > 1920):
            raise ValueError("Invalid fixed crop or placement")
    crop, place = layout["crop"], layout["placement"]
    if crop["width"] * place["height"] != crop["height"] * place["width"]:
        raise ValueError("Stat placement must preserve aspect ratio")
    zone = b["parent_safe_zone"]
    if (type(zone) is not dict or set(zone) != {"top", "bottom", "left", "right"}
            or any(type(v) is not int or v < 0 for v in zone.values())
            or zone["left"] + zone["right"] >= 1080 or zone["top"] + zone["bottom"] >= 1920):
        raise ValueError("Stat requires actual parent safe-zone margins")
    if (type(b["style"]) is not dict or set(b["style"]) != {"accent", "ink", "card", "statTint"}
            or any(not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v)) for v in b["style"].values())):
        raise ValueError("Only public native colors may be configured")
    if b["template_request"] != {"semantic_family":"numeric_emphasis", "information_units":1,
                                  "numeric_values":[m["value"]], "numeric_scale":"linear"}:
        raise ValueError("Stat template request differs from its actual single value")
    if (type(b["upstream"]) is not dict or set(b["upstream"]) != {"source_revision", "runtime_identity"}
            or b["upstream"]["source_revision"] != SOURCE_PIN
            or not re.fullmatch(r"[a-f0-9]{64}", str(b["upstream"]["runtime_identity"]))):
        raise ValueError("Stat upstream identity is missing")
    assets = b["assets"]
    if b["execution_mode"] not in {"native_export", "reuse_mov"} or type(assets) is not list:
        raise ValueError("Choose native_export or reuse_mov explicitly")
    for item in assets:
        if type(item) is not dict or set(item) != {"media_ref", "job_path", "sha256"}:
            raise ValueError("Invalid stat frozen media")
        path = PurePosixPath(item["job_path"])
        if (not item["job_path"] or path.is_absolute() or ".." in path.parts
                or path.as_posix() != item["job_path"]
                or not re.fullmatch(r"[a-f0-9]{64}", str(item["sha256"]))):
            raise ValueError("Invalid stat frozen path or hash")
    refs = [a["media_ref"] for a in assets]
    if (len(refs) != len(set(refs)) or len({a["job_path"] for a in assets}) != len(assets)
            or (b["execution_mode"] == "native_export" and assets)
            or (b["execution_mode"] == "reuse_mov" and set(refs) != REUSE_REFS)):
        raise ValueError("Stat execution mode and frozen media disagree")
    return b


def native_stat(brief):
    m = validate_brief(brief)["metric"]
    return dict(value=m["value"], prefix=m["prefix"], suffix=m["suffix"], label=m["label"],
                at=m["target_frame"]/24 - .35, hold=m["hold_frames"]/24 + .35)


def metric_texts(brief):
    m = validate_brief(brief)["metric"]
    return [m["prefix"] + number_text(m["value"]) + m["suffix"], m["label"]]


def native_variables(brief):
    b = validate_brief(brief)
    return dict(talk="", transparent=True, length=b["composition"]["frames"]/24,
                name="", role="", nameTag="", nameCue="", keywords="[]", chapter="",
                chapterNo="", chapterCue="", corner="", lead=.25,
                stats=json.dumps([native_stat(b)],ensure_ascii=False),
                **b["layout"]["subject"], **b["style"])


def native_configuration(source):
    match = VARIABLES.search(source)
    if not match:
        raise ValueError("Native stat variables missing")
    declarations = json.loads(html.unescape(match[2] if match[2] is not None else match[3]))
    metadata = [{k:v for k,v in row.items() if k != "default"} for row in declarations]
    normalized = source[:match.start()] + " data-composition-variables=" + json.dumps(metadata,ensure_ascii=False,sort_keys=True) + source[match.end():]
    normalized = re.sub(r'(<([a-z][\w-]*)\b[^>]*\sdata-var-text\s*=\s*["\'][^"\']+["\'][^>]*>)[^<]*(</\2>)',r"\1\3",normalized,flags=re.I)
    normalized = re.sub(r'\bdata-(width|height)="\d+"',r'data-\1="0"',normalized)
    if hashlib.sha256(normalized.encode()).hexdigest() != STRUCTURE_SHA:
        raise ValueError("Native template differs beyond public variables and canvas size")
    if not re.search(r'data-composition-id="film" data-width="1080" data-height="1920"', source):
        raise ValueError("Native stat stage is not portrait")
    values = {row["id"]:row.get("default") for row in declarations}
    if len(values) != len(declarations):
        raise ValueError("Native variables duplicated")
    return values


def validate_native_configuration(source, brief):
    actual = native_configuration(source)
    for key, expected in native_variables(brief).items():
        if key == "stats":
            rows = json.loads(actual[key])
            if type(rows) is not list or len(rows) != 1 or set(rows[0]) - {"value","prefix","suffix","label","at","hold"}:
                raise ValueError("Reused native stat contains another event or cue")
            observed = dict(rows[0])
            observed.setdefault("prefix", "")
            observed.setdefault("suffix", "")
            target = native_stat(brief)
            if (set(observed) != set(target) or any(observed[k] != target[k] for k in target if k not in {"at","hold"})
                    or any(abs(observed[k]-target[k]) > 1e-8 for k in ("at","hold"))):
                raise ValueError("Reused native numerical content or time differs")
        elif actual.get(key) != expected:
            raise ValueError("Reused native public variable differs: " + key)


def validate_visible_bounds(bounds, brief):
    crop, place, zone = brief["layout"]["crop"], brief["layout"]["placement"], brief["parent_safe_zone"]
    if not bounds or not (crop["x"] <= bounds[0] and crop["y"] <= bounds[1]
                         and crop["x"]+crop["width"] >= bounds[2] and crop["y"]+crop["height"] >= bounds[3]):
        raise ValueError("Fixed crop cuts native content, motion or shadows")
    left = place["x"] + (bounds[0]-crop["x"])*place["width"]//crop["width"] - 2
    top = place["y"] + (bounds[1]-crop["y"])*place["height"]//crop["height"] - 2
    right = place["x"] + math.ceil((bounds[2]-crop["x"])*place["width"]/crop["width"]) + 2
    bottom = place["y"] + math.ceil((bounds[3]-crop["y"])*place["height"]/crop["height"]) + 2
    if left < zone["left"] or top < zone["top"] or right > 1080-zone["right"] or bottom > 1920-zone["bottom"]:
        raise ValueError("Complete native stat action exceeds the approved parent safe zone")
    return left, top, right, bottom


def create_adapter(project_root, python_executable, brief_loader, *, execution_mode="native_export"):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project, mode=execution_mode)
    entry_sha, python = sha(SKILL/ENTRY), Path(python_executable).resolve(strict=True)
    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary, huashu_stat_alignment
        payload = brief_loader(job, recipe, component)
        if type(payload) is not bytes:
            raise ValueError("Stat brief loader must return its original frozen bytes")
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan["segments"] if s["segment_id"] == recipe["segment_id"])
        ar = visual_canary.approved_aroll_record(job, plan)
        if (sha(SKILL/ENTRY) != entry_sha
                or check_runtime(project,runtime,mode=execution_mode)["identity"] != runtime["identity"]
                or b["upstream"]["runtime_identity"] != runtime["identity"] or b["execution_mode"] != execution_mode
                or b["source_binding"] != dict(aroll_sha256=ar["sha256"],segment_id=segment["segment_id"],start=segment["start"],end=segment["end"])
                or json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or recipe["composition"]["family"] != "aroll_with_overlay" or component["layer_role"] != "annotation"
                or component["artifact_contract"] != dict(width=1080,height=1920,fps=24,alpha=True)
                or component["source_sha256"] != entry_sha
                or component["render_window"]["start_frame"] != 0
                or component["render_window"]["end_frame"] != b["composition"]["frames"]
                or component["render_window"]["safe_zone"] != b["parent_safe_zone"]
                or json.loads(json.dumps(component["invocation_record"]["template_request"])) != b["template_request"]):
            raise ValueError("Stat differs from the approved A-roll, recipe, timing or safe zone")
        huashu_stat_alignment.validate_approved(job, segment, component["component_id"], b, component["brief_sha256"])
        return payload
    def media(job, recipe, component, payload):
        return tuple(ReferenceProcessMedia(**a) for a in validate_brief(payload)["assets"])
    return ReferenceProcessAdapter(adapter_id="huashu-motion-stat-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer=RENDERER,
        renderer_version=VERSION, artifact_media_type="video", launcher=python, launcher_sha256=sha(python),
        brief_loader=guard, media_loader=media, self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}","{entrypoint}","--skill-root",str(SKILL),"--project-root",str(project),
                       "--mode",execution_mode,"--brief","{brief_path}","--media-manifest","{media_manifest_fd}",
                       "--output","{output_path}","--runtime-identity",runtime["identity"],
                       "--node",runtime.get("node",""),"--ffmpeg",runtime["ffmpeg"],
                       "--ffprobe",runtime["ffprobe"],"--chrome",runtime.get("chrome","")))


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint != ENTRY
            or adapter.primary_renderer != RENDERER or adapter.entrypoint_sha256 != sha(SKILL/ENTRY)):
        raise ValueError("Stat adapter identity differs")
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return dict(producer_type="dependency",dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,
        primary_renderer=RENDERER,renderer_version=VERSION,template_origin="custom_fallback",template_id=TEMPLATE_ID,
        template_version=VERSION,adaptation_level="structural",source_entrypoint=ENTRY,source_sha256=adapter.entrypoint_sha256,
        sample_sha256=sha(Path(reference_sample)),semantic_families=["numeric_emphasis"],capacity=dict(min_units=1,max_units=1),
        brief_sha256=digest,verification_id=hashlib.sha256((adapter.entrypoint_sha256+digest).encode()).hexdigest(),
        invocation_record=dict(argv=[str(adapter.launcher),ENTRY],status="planned",exit_code=None,template_request=b["template_request"]))


def create_artifact_probe(ffprobe_executable):
    from hyperframes_hw_pipeline_adapter import create_artifact_probe as alpha_probe
    return alpha_probe(ffprobe_executable=ffprobe_executable)


def _frozen_assets(args, brief, raw, directory):
    manifest = json.loads(Path(args.media_manifest).read_bytes())
    records = manifest.get("media",[])
    by_ref = {r["media_ref"]:r for r in records}
    if (manifest.get("schema_version") != "reference-process-media/v1"
            or manifest.get("brief_sha256") != hashlib.sha256(raw).hexdigest()
            or len(by_ref) != len(records) or set(by_ref) != {a["media_ref"] for a in brief["assets"]}):
        raise ValueError("Stat frozen media manifest differs")
    files = {}
    for asset in brief["assets"]:
        record = by_ref[asset["media_ref"]]
        data = Path("/dev/fd/"+str(record["fd"])).read_bytes()
        if (len(data) != record["byte_length"] or hashlib.sha256(data).hexdigest() != asset["sha256"]
                or record["sha256"] != asset["sha256"]):
            raise ValueError("Stat frozen media changed")
        target = directory / asset["media_ref"]
        target.write_bytes(data)
        files[asset["media_ref"]] = target
    return files


def validate_reuse(files, brief):
    validate_native_configuration(files["native-config"].read_text(), brief)
    source = json.loads(files["native-source"].read_bytes())
    evidence = json.loads(files["native-evidence"].read_bytes())
    if (source.get("schema_version") != 1 or source.get("source_revision") != SOURCE_PIN
            or source.get("source_binding") != brief["source_binding"]
            or source.get("native_sha256") != sha(files["native-mov"])
            or source.get("config_sha256") != sha(files["native-config"])
            or source.get("evidence_sha256") != sha(files["native-evidence"])
            or evidence.get("native_revision") != SOURCE_PIN):
        raise ValueError("Reused stat provenance does not bind this source, config and MOV")
    commands = evidence.get("commands",[])
    for stage in ("native-render", "native-probe"):
        rows = [r for r in commands if r.get("stage") == stage]
        if len(rows) != 1 or rows[0].get("exit_code") != 0 or rows[0].get("status") != "completed":
            raise ValueError("Reused stat native command was not proved successful")
        argv = rows[0].get("argv",[])
        if stage == "native-render":
            if ("--out" not in argv or argv[argv.index("--out")+1] != source.get("recorded_output")
                    or "--transparent" not in argv or "--fps" not in argv
                    or argv[argv.index("--fps")+1] != "24"):
                raise ValueError("Reused native render output identity differs")
        elif not argv or argv[-1] != source.get("recorded_output"):
            raise ValueError("Reused native probe refers to another output")
    return files["native-mov"]


def _native_export(brief, runtime, directory, run):
    cli = [runtime["node"], str(Path(runtime["vendor"])/"cli/om.js")]
    landscape, portrait = directory/"landscape", directory/"portrait"
    run("native-new", cli+["new",str(landscape),"--template","talking-head"])
    run("native-fork", cli+["fork",str(landscape),str(portrait),"--size","1080x1920"])
    pairs = [key+"="+(json.dumps(value).lower() if type(value) is bool else str(value))
             for key,value in native_variables(brief).items()]
    run("native-set", cli+["set",*pairs,str(portrait)])
    validate_native_configuration((portrait/"index.html").read_text(), brief)
    mov = directory/"native.mov"
    run("native-render",cli+["render",str(portrait),"--transparent","--fps","24","--workers","1","--out",str(mov),"--verbose"])
    run("native-probe",[runtime["ffprobe"],"-v","error","-show_streams","-show_format","-of","json",str(mov)])
    return mov


def normalize_mov(mov, brief, runtime, directory, run):
    from PIL import Image
    comp = brief["composition"]
    probe = json.loads(run("source-probe",[runtime["ffprobe"],"-v","error","-show_streams","-of","json",str(mov)]).stdout)
    streams = probe.get("streams",[])
    if (len(streams) != 1 or streams[0].get("codec_type") != "video"
            or (streams[0].get("width"),streams[0].get("height"),streams[0].get("r_frame_rate")) != (1080,1920,"24/1")
            or not re.match(r"^(yuva|gbrap|rgba|argb|bgra|abgr)",streams[0].get("pix_fmt",""))):
        raise ValueError("Stat input is not a portrait 24fps transparent video")
    argv = [runtime["ffmpeg"],"-v","error","-nostdin","-i",str(mov),"-vf","alphaextract","-f","rawvideo","-pix_fmt","gray","-"]
    union, count, visible = None, 0, []
    with (directory/"alpha.stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=stderr)
        try:
            while data := process.stdout.read(1080*1920):
                if len(data) != 1080*1920:
                    raise ValueError("Stat alpha frame is truncated")
                box = Image.frombytes("L",(1080,1920),data).point(lambda v:255 if v>4 else 0).getbbox()
                if box:
                    if box[0] == 0 or box[1] == 0 or box[2] == 1080 or box[3] == 1920:
                        raise ValueError("Stat content reaches native stage edge")
                    union = box if union is None else (min(union[0],box[0]),min(union[1],box[1]),max(union[2],box[2]),max(union[3],box[3]))
                    visible.append(count)
                count += 1
            if process.wait(timeout=30) != 0:
                raise ValueError("Stat alpha decode failed; inspect alpha.stderr.log")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    if count != comp["frames"] or not visible or visible[-1] >= count-2:
        raise ValueError("Stat frame count or complete transparent exit differs")
    parent_bounds = validate_visible_bounds(union, brief)
    crop, place = brief["layout"]["crop"], brief["layout"]["placement"]
    graph = (f'crop={crop["width"]}:{crop["height"]}:{crop["x"]}:{crop["y"]},format=rgba,'
             f'scale={place["width"]}:{place["height"]},pad=1080:1920:{place["x"]}:{place["y"]}:color=0x00000000,setsar=1')
    target = directory/"normalized.mov"
    run("normalize",[runtime["ffmpeg"],"-v","error","-nostdin","-i",str(mov),"-vf",graph,
                     "-frames:v",str(count),"-an","-c:v","qtrle","-pix_fmt","argb",str(target)])
    media = create_artifact_probe(runtime["ffprobe"]).probe(target,"video",dict(width=1080,height=1920,fps=24,alpha=True))
    if media["frame_count"] != count or abs(media["duration"]-count/24) > 1e-6:
        raise ValueError("Stat normalization changed the frame clock")
    return target, dict(native_bounds=union,parent_bounds=parent_bounds,first_visible_frame=visible[0],last_visible_frame=visible[-1])


def render(args):
    sys.path.insert(0,str(Path(args.project_root).resolve(strict=True)))
    from project_python import project_environment
    _, packages = project_environment(Path(args.project_root))
    sys.path.insert(0,str(packages))
    raw = Path(args.brief).read_bytes()
    brief = validate_brief(raw)
    runtime = check_runtime(args.project_root,{k:getattr(args,k) for k in ("node","ffmpeg","ffprobe","chrome")},mode=args.mode)
    directory = Path(tempfile.mkdtemp(prefix="huashu-stat-native-"))
    report = dict(status="preparing",execution_mode=args.mode,native_revision=SOURCE_PIN,commands=[])
    env = {k:v for k,v in os.environ.items() if k in {"HOME","TMPDIR","LANG"}}
    env["PATH"] = os.pathsep.join(dict.fromkeys([*(str(Path(runtime[k]).parent) for k in ("node","ffmpeg","ffprobe") if k in runtime),"/usr/bin","/bin"]))
    if "chrome" in runtime:
        env["OM_CHROME"] = runtime["chrome"]
    def run(stage, argv):
        record = dict(stage=stage,argv=argv,status="running",exit_code=None)
        report["commands"].append(record)
        result = subprocess.run(argv,cwd=directory,env=env,capture_output=True,text=True,timeout=260)
        record.update(status="completed" if result.returncode == 0 else "failed",exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
        result.check_returncode()
        return result
    try:
        if (brief["execution_mode"] != args.mode or runtime["identity"] != args.runtime_identity
                or brief["upstream"]["runtime_identity"] != runtime["identity"]):
            raise ValueError("Bound stat mode or runtime changed")
        files = _frozen_assets(args,brief,raw,directory)
        mov = validate_reuse(files,brief) if args.mode == "reuse_mov" else _native_export(brief,runtime,directory,run)
        target, bounds = normalize_mov(mov,brief,runtime,directory,run)
        with target.open("rb") as source, Path(args.output).open("wb") as output:
            shutil.copyfileobj(source,output)
        report.update(status="completed",frames=brief["composition"]["frames"],native_export_invoked=args.mode=="native_export",
                      runtime_identity=runtime["identity"],output_sha256=sha(target),bounds=bounds,
                      normalization="fixed crop/place; QTRLE/ARGB straight alpha; SAR 1:1; no new motion")
        if args.mode == "native_export":
            config = directory/"portrait/index.html"
            evidence = directory/"native-evidence.json"
            evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            source = dict(schema_version=1,source_revision=SOURCE_PIN,source_binding=brief["source_binding"],
                          native_sha256=sha(mov),config_sha256=sha(config),evidence_sha256=sha(evidence),recorded_output=str(mov))
            source_path = directory/"native-source.json"
            source_path.write_text(json.dumps(source,ensure_ascii=False,indent=2))
            report["reuse_files"] = {"native-mov":str(mov),"native-config":str(config),"native-evidence":str(evidence),"native-source":str(source_path)}
    except Exception as error:
        report.update(status="failed",error_type=type(error).__name__,error=str(error))
        failure = directory/"failure.json"
        failure.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        raise RuntimeError("Huashu stat stopped without retry; inspect "+str(failure)) from error
    if args.mode == "reuse_mov":
        shutil.rmtree(directory)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root",required=True,type=Path)
    parser.add_argument("--skill-root",type=Path)
    parser.add_argument("--mode",choices=("native_export","reuse_mov"),default="native_export")
    parser.add_argument("--probe",action="store_true")
    for key in ("brief","media-manifest","output","runtime-identity","node","ffmpeg","ffprobe","chrome"):
        parser.add_argument("--"+key)
    args = parser.parse_args()
    if args.probe:
        runtime = check_runtime(args.project_root,mode=args.mode)
        probe_runtime(args.project_root,runtime)
        print(json.dumps(dict(schema_version=1,dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,
            adapter_identity=dict(adapter_type="ReferenceProcessAdapter",approved_executor="reference_adapter",primary_renderer=RENDERER))))
    elif args.brief and args.output and args.media_manifest:
        print(json.dumps(render(args),ensure_ascii=False))
    else:
        parser.error("choose --probe or the complete frozen execution arguments")
